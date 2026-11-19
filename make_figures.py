import sqlite3
import matplotlib.pyplot as plt
import pandas as pd

con = sqlite3.connect("data/quality.db")
df = pd.read_sql_query(
    "SELECT period, COUNT(*) n, SUM(defect) d FROM parts GROUP BY period", con)
df["rate"] = 100 * df["d"] / df["n"]

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(df["period"], df["rate"], marker="o")
ax.axhline(df["rate"].mean(), ls="--", color="gray")
ax.set_title("Defect rate per 6h block")
ax.set_xlabel("Period"); ax.set_ylabel("Defect rate (%)")
fig.tight_layout()
fig.savefig("docs_defect_trend.png", dpi=150)