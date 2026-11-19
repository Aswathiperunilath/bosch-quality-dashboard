import sqlite3

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, dash_table, dcc, html

DB = "data/quality.db"
PERIOD_HOURS = 6

# Load once at startup
with sqlite3.connect(DB) as con:
    PARTS = pd.read_sql_query("SELECT * FROM parts", con)
    EVENTS = pd.read_sql_query(
        "SELECT e.station, p.defect, p.line, p.shift "
        "FROM station_events e JOIN parts p USING (part_id)",
        con,
    )

LINES = sorted(int(x) for x in PARTS["line"].unique())
SHIFTS = ["A", "B", "C"]

app = Dash(__name__)
server = app.server  # for gunicorn / deployment

CARD = {"padding": "12px 20px", "border": "1px solid #ddd", "borderRadius": "8px",
        "textAlign": "center", "minWidth": "150px"}


def kpi(id_, label):
    return html.Div([html.H2(id=id_, style={"margin": 0}), html.P(label, style={"margin": 0})], style=CARD)


app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "maxWidth": "1200px", "margin": "auto", "padding": "16px"},
    children=[
        html.H1("Manufacturing Quality Dashboard"),
        html.P("Bosch Production Line Performance data (sample). Shifts and time are derived from anonymized timestamps."),
        html.Div(style={"display": "flex", "gap": "24px", "marginBottom": "16px"}, children=[
            html.Div([html.Label("Line (entry)"),
                      dcc.Dropdown(id="line", multi=True, value=LINES,
                                   options=[{"label": f"Line {l}", "value": l} for l in LINES])],
                     style={"width": "320px"}),
            html.Div([html.Label("Shift"),
                      dcc.Checklist(id="shift", value=SHIFTS, inline=True,
                                    options=[{"label": f" {s} ", "value": s} for s in SHIFTS])]),
        ]),
        html.Div(style={"display": "flex", "gap": "16px", "marginBottom": "16px"}, children=[
            kpi("kpi-parts", "Parts"), kpi("kpi-defects", "Defects"),
            kpi("kpi-rate", "Defect rate"), kpi("kpi-fpy", "First-pass yield"),
        ]),
        dcc.Graph(id="pchart"),
        html.Div(style={"display": "flex", "gap": "16px"}, children=[
            html.Div(dcc.Graph(id="heatmap"), style={"flex": 1}),
            html.Div(dcc.Graph(id="stations"), style={"flex": 2}),
        ]),
        html.H3("Flagged periods (outside control limits)"),
        dash_table.DataTable(id="anomalies", page_size=8,
                             columns=[{"name": n, "id": i} for i, n in [
                                 ("period", "Period"), ("n", "Parts"), ("d", "Defects"),
                                 ("rate_pct", "Rate %"), ("ucl_pct", "UCL %"), ("lcl_pct", "LCL %")]]),
    ],
)


@app.callback(
    Output("kpi-parts", "children"), Output("kpi-defects", "children"),
    Output("kpi-rate", "children"), Output("kpi-fpy", "children"),
    Output("pchart", "figure"), Output("heatmap", "figure"),
    Output("stations", "figure"), Output("anomalies", "data"),
    Input("line", "value"), Input("shift", "value"),
)
def update(lines, shifts):
    lines = lines or LINES
    shifts = shifts or SHIFTS
    df = PARTS[PARTS["line"].isin(lines) & PARTS["shift"].isin(shifts)]
    ev = EVENTS[EVENTS["line"].isin(lines) & EVENTS["shift"].isin(shifts)]

    if df.empty:
        return "0", "0", "-", "-", go.Figure(), go.Figure(), go.Figure(), []

    n, d = len(df), int(df["defect"].sum())
    p_bar = d / n

    # ---- p-chart ----
    g = df.groupby("period").agg(n=("defect", "size"), d=("defect", "sum")).reset_index()
    g["rate"] = g["d"] / g["n"]
    sigma = np.sqrt(p_bar * (1 - p_bar) / g["n"])
    g["ucl"] = p_bar + 3 * sigma
    g["lcl"] = np.clip(p_bar - 3 * sigma, 0, None)
    g["flag"] = (g["rate"] > g["ucl"]) | (g["rate"] < g["lcl"])

    pfig = go.Figure()
    pfig.add_trace(go.Scatter(x=g["period"], y=g["rate"] * 100, mode="lines+markers", name="Defect rate %"))
    pfig.add_trace(go.Scatter(x=g["period"], y=g["ucl"] * 100, mode="lines", name="UCL",
                              line=dict(dash="dash", color="red")))
    pfig.add_trace(go.Scatter(x=g["period"], y=g["lcl"] * 100, mode="lines", name="LCL",
                              line=dict(dash="dash", color="red")))
    pfig.add_hline(y=p_bar * 100, line_dash="dot", annotation_text="Center line")
    out = g[g["flag"]]
    pfig.add_trace(go.Scatter(x=out["period"], y=out["rate"] * 100, mode="markers", name="Out of control",
                              marker=dict(color="red", size=12, symbol="x")))
    pfig.update_layout(title=f"p-chart: defect rate per {PERIOD_HOURS}h block",
                       xaxis_title="Period", yaxis_title="Defect rate (%)")

    # ---- heatmap: line x shift ----
    pivot = df.pivot_table(index="line", columns="shift", values="defect", aggfunc="mean") * 100
    hfig = go.Figure(go.Heatmap(z=pivot.values, x=list(pivot.columns),
                                y=[f"Line {i}" for i in pivot.index],
                                colorbar=dict(title="%"), hovertemplate="%{y}, shift %{x}: %{z:.2f}%<extra></extra>"))
    hfig.update_layout(title="Defect rate % by line and shift")

    # ---- station risk ranking ----
    s = ev.groupby("station").agg(n=("defect", "size"), rate=("defect", "mean"))
    s = s[s["n"] >= 500].nlargest(15, "rate")
    sfig = go.Figure(go.Bar(x="S" + s.index.astype(str), y=s["rate"] * 100, name="Defect rate %"))
    sfig.add_hline(y=ev["defect"].mean() * 100, line_dash="dash", annotation_text="Average")
    sfig.update_layout(title="Top 15 riskiest stations (>= 500 parts)",
                       xaxis_title="Station", yaxis_title="Defect rate of parts passing (%)")

    table = pd.DataFrame({
        "period": out["period"], "n": out["n"], "d": out["d"],
        "rate_pct": (out["rate"] * 100).round(3),
        "ucl_pct": (out["ucl"] * 100).round(3),
        "lcl_pct": (out["lcl"] * 100).round(3),
    }).to_dict("records")

    return f"{n:,}", f"{d:,}", f"{p_bar:.2%}", f"{1 - p_bar:.2%}", pfig, hfig, sfig, table


if __name__ == "__main__":
    app.run(debug=True)