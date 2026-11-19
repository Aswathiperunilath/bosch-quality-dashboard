"""ETL: Bosch production line data -> SQLite."""
import logging
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("etl")

RAW = Path("data/raw")
DB = Path("data/quality.db")
N_ROWS = 100_000        # sample size (the full set is 1.18M parts)
CHUNK = 5_000           # rows per processing chunk (keeps memory low)
UNITS_PER_HOUR = 10     # ASSUMPTION: anonymized time units -> pseudo-hours
PERIOD_HOURS = 6        # control-chart bucket size
DATE_COL = re.compile(r"^L(\d+)_S(\d+)_D(\d+)$")


# ---------- EXTRACT ----------
def extract_labels() -> pd.DataFrame:
    log.info("Extracting labels")
    df = pd.read_csv(RAW / "train_numeric.csv.zip", usecols=["Id", "Response"], nrows=N_ROWS)
    return df.rename(columns={"Id": "part_id", "Response": "defect"})


def extract_date_chunks():
    return pd.read_csv(RAW / "train_date.csv.zip", nrows=N_ROWS, chunksize=CHUNK)


# ---------- TRANSFORM ----------
def transform_events(chunk: pd.DataFrame) -> pd.DataFrame:
    """Wide (1 col per sensor timestamp) -> long: one row per part per station."""
    date_cols = [c for c in chunk.columns if DATE_COL.match(c)]
    long = (
        chunk.melt(id_vars="Id", value_vars=date_cols, var_name="col", value_name="time")
        .dropna(subset=["time"])
    )
    parsed = long["col"].str.extract(DATE_COL.pattern).astype(int)
    long["line"], long["station"] = parsed[0], parsed[1]
    return (
        long.groupby(["Id", "line", "station"], as_index=False)["time"].min()
        .rename(columns={"Id": "part_id"})
    )


def build_parts(events: pd.DataFrame) -> pd.DataFrame:
    """One row per part: entry line, start/end time, pseudo-shift, time period."""
    events = events.sort_values(["part_id", "time"])
    first_line = events.groupby("part_id")["line"].first().rename("line")
    agg = events.groupby("part_id").agg(
        start_time=("time", "min"),
        end_time=("time", "max"),
        n_stations=("station", "nunique"),
    )
    parts = agg.join(first_line).reset_index()

    hours = parts["start_time"] / UNITS_PER_HOUR
    hour_of_day = hours % 24
    parts["shift"] = np.select(
        [(hour_of_day >= 6) & (hour_of_day < 14), (hour_of_day >= 14) & (hour_of_day < 22)],
        ["A", "B"],
        default="C",
    )
    parts["period"] = (hours // PERIOD_HOURS).astype(int)
    return parts


# ---------- VALIDATE ----------
def validate(parts: pd.DataFrame) -> None:
    assert parts["part_id"].is_unique, "duplicate part ids"
    assert parts["defect"].isin([0, 1]).all(), "defect must be 0/1 (or missing label)"
    assert (parts["end_time"] >= parts["start_time"]).all(), "negative duration"


# ---------- LOAD ----------
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_part ON station_events(part_id);
CREATE INDEX IF NOT EXISTS idx_events_station ON station_events(station);
CREATE INDEX IF NOT EXISTS idx_parts_line_shift ON parts(line, shift);
CREATE INDEX IF NOT EXISTS idx_parts_period ON parts(period);
"""


def main():
    DB.parent.mkdir(exist_ok=True)
    DB.unlink(missing_ok=True)
    labels = extract_labels()
    con = sqlite3.connect(DB)

    total = 0
    for i, chunk in enumerate(extract_date_chunks(), start=1):
        events = transform_events(chunk)
        parts = build_parts(events).merge(labels, on="part_id", how="inner")
        validate(parts)
        events.to_sql("station_events", con, if_exists="append", index=False)
        parts.to_sql("parts", con, if_exists="append", index=False)
        total += len(parts)
        log.info("chunk %d loaded | parts so far: %d", i, total)

    con.executescript(INDEXES)
    stats = con.execute(
        "SELECT COUNT(*), SUM(defect), MIN(start_time), MAX(start_time) FROM parts"
    ).fetchone()
    log.info("DONE | parts=%d defects=%d time_range=[%.1f, %.1f]", *stats)
    con.close()


if __name__ == "__main__":
    main()