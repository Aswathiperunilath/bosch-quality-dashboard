import pandas as pd
from etl import build_parts

def test_build_parts_basic():
    events = pd.DataFrame({"part_id": [1, 1, 2], "line": [0, 3, 3],
                           "station": [0, 29, 29], "time": [100.0, 150.0, 250.0]})
    parts = build_parts(events)
    assert len(parts) == 2
    assert parts.loc[parts.part_id == 1, "line"].iloc[0] == 0
    assert set(parts["shift"]).issubset({"A", "B", "C"})