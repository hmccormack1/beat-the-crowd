"""Probability history charts, with an explicitly current model reference."""
import altair as alt
import pandas as pd


def probability_history(points: list[dict], model_probability: float):
    frame = pd.DataFrame(points)
    frame["date"] = pd.to_datetime(frame["t"], unit="s", utc=True)
    frame = frame.sort_values("date")
    scale = alt.Scale(domain=[0, 1])
    history = alt.Chart(frame).mark_line(color="#2458D3", strokeWidth=2.5).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d", labelAngle=0)),
        y=alt.Y("p:Q", title="YES probability", scale=scale, axis=alt.Axis(format=".0%")),
        tooltip=[alt.Tooltip("date:T", title="Date (UTC)", format="%b %d, %Y"),
                 alt.Tooltip("p:Q", title="Crowd", format=".1%")],
    )
    reference = alt.Chart(pd.DataFrame({"probability": [model_probability]})).mark_rule(
        color="#B35925", strokeDash=[6, 4], strokeWidth=2
    ).encode(
        y=alt.Y("probability:Q", scale=scale),
        tooltip=[alt.Tooltip("probability:Q", title="Model now", format=".1%")],
    )
    return (history + reference).properties(height=205).configure_view(
        stroke=None
    ).configure_axis(gridColor="#E8EDF5", labelColor="#536078", titleColor="#536078")
