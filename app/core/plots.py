"""Plotly chart builders for the GDMTH solar app."""

from __future__ import annotations

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# Color palette
TEC_BLUE = "#0039A6"
SOLAR_YELLOW = "#FFB300"
SOLAR_ORANGE = "#F57C00"
GREEN = "#2E7D32"
RED = "#C62828"
LIGHT_BLUE = "#90CAF9"


def irradiance_plot(df: pd.DataFrame, selected_date: str | None = None) -> go.Figure:
    """Plot hourly GHI, DNI, DHI and POA irradiance."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        subplot_titles=["Irradiance Components (W/m²)", "Plane of Array (POA) W/m²"],
                        vertical_spacing=0.12)

    if selected_date:
        day_df = df[df.index.date == pd.Timestamp(selected_date).date()]
    else:
        day_df = df

    fig.add_trace(go.Scatter(x=day_df.index, y=day_df["ghi"], name="GHI",
                             line=dict(color=SOLAR_YELLOW, width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=day_df.index, y=day_df["dni"], name="DNI",
                             line=dict(color=SOLAR_ORANGE, width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=day_df.index, y=day_df["dhi"], name="DHI",
                             line=dict(color=LIGHT_BLUE, width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=day_df.index, y=day_df["poa_global"], name="POA Global",
                             line=dict(color=TEC_BLUE, width=2.5)), row=2, col=1)
    fig.add_trace(go.Scatter(x=day_df.index, y=day_df["poa_sky_diffuse"], name="POA Diffuse",
                             line=dict(color=LIGHT_BLUE, width=1.5, dash="dot"),
                             fill="tozeroy", fillcolor="rgba(144,202,249,0.2)"), row=2, col=1)

    fig.update_layout(
        template="plotly_white",
        height=480,
        legend=dict(orientation="h", y=-0.12),
        margin=dict(t=40, b=40),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="W/m²", row=1, col=1)
    fig.update_yaxes(title_text="W/m²", row=2, col=1)
    return fig


def generation_bar(df: pd.DataFrame, freq: str = "D") -> go.Figure:
    """Bar chart of aggregated PV generation."""
    label_map = {"D": "Daily kWh", "W": "Weekly kWh", "ME": "Monthly kWh"}
    agg = df["pv_kw"].resample(freq).sum()
    agg.index = agg.index.strftime("%Y-%m-%d")

    fig = go.Figure(go.Bar(
        x=agg.index, y=agg.values,
        marker_color=SOLAR_YELLOW,
        marker_line_color=SOLAR_ORANGE,
        marker_line_width=1,
        name=label_map.get(freq, "kWh"),
    ))
    fig.update_layout(
        template="plotly_white",
        xaxis_title="Date",
        yaxis_title=label_map.get(freq, "kWh"),
        height=360,
        margin=dict(t=20, b=40),
    )
    return fig


def demand_injection_plot(demand_kw: pd.Series, solar_kw: pd.Series, net_kw: pd.Series) -> go.Figure:
    """Dual-trace: original demand vs. net demand after solar injection."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=demand_kw.index, y=demand_kw.values,
        name="Demanda original (kW)",
        line=dict(color=RED, width=2),
        hovertemplate="<b>%{x|%Y-%m-%d %H:%M}</b><br>Demanda: %{y:.1f} kW<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=net_kw.index, y=net_kw.values,
        name="Demanda neta con FV (kW)",
        line=dict(color=TEC_BLUE, width=2),
        hovertemplate="<b>%{x|%Y-%m-%d %H:%M}</b><br>Neta: %{y:.1f} kW<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=solar_kw.index, y=solar_kw.values,
        name="Generación FV (kW)",
        line=dict(color=SOLAR_YELLOW, width=1.5, dash="dot"),
        fill="tozeroy",
        fillcolor="rgba(255,179,0,0.15)",
        hovertemplate="<b>%{x|%Y-%m-%d %H:%M}</b><br>Solar: %{y:.1f} kW<extra></extra>",
    ))

    # Shade Punta period (18-22h) as a background band for each day
    if not demand_kw.empty:
        dates = pd.Series(demand_kw.index.date).unique()
        for d in dates[:7]:  # limit bands to first 7 days for legibility
            fig.add_vrect(
                x0=pd.Timestamp(d) + pd.Timedelta(hours=18),
                x1=pd.Timestamp(d) + pd.Timedelta(hours=22),
                fillcolor="rgba(197,57,41,0.07)",
                line_width=0,
                annotation_text="Punta" if d == dates[0] else "",
                annotation_position="top left",
            )

    fig.update_layout(
        template="plotly_white",
        height=420,
        xaxis_title="Tiempo",
        yaxis_title="Potencia (kW)",
        legend=dict(orientation="h", y=-0.15),
        hovermode="x unified",
        margin=dict(t=20, b=60),
    )
    return fig


def savings_waterfall(result: dict) -> go.Figure:
    """Waterfall chart showing savings breakdown."""
    categories = ["Factura base", "Ahorro energía Punta", "Ahorro energía Intermedia",
                  "Ahorro energía Base", "Ahorro Capacidad", "Ahorro Distribución", "Factura con FV"]

    e_punta_saving = result["orig_charge_punta"] - result["charge_punta"]
    e_inter_saving = result["orig_charge_inter"] - result["charge_inter"]
    e_base_saving = result["orig_charge_base"] - result["charge_base"]
    cap_saving = result["orig_charge_capacidad"] - result["charge_capacidad"]
    dist_saving = result["orig_charge_distribucion"] - result["charge_distribucion"]

    measure = ["absolute", "relative", "relative", "relative", "relative", "relative", "total"]
    x = categories
    y = [
        result["orig_total_mxn"],
        -e_punta_saving,
        -e_inter_saving,
        -e_base_saving,
        -cap_saving,
        -dist_saving,
        result["total_mxn"],
    ]

    fig = go.Figure(go.Waterfall(
        name="GDMTH",
        orientation="v",
        measure=measure,
        x=x,
        y=y,
        text=[f"${v:,.0f}" for v in y],
        textposition="outside",
        decreasing={"marker": {"color": GREEN}},
        increasing={"marker": {"color": RED}},
        totals={"marker": {"color": TEC_BLUE}},
        connector={"line": {"color": "gray", "width": 1}},
    ))

    fig.update_layout(
        template="plotly_white",
        yaxis_title="MXN / mes",
        height=420,
        margin=dict(t=20, b=80),
        showlegend=False,
        xaxis_tickangle=-20,
    )
    return fig


def energy_pie(result: dict) -> go.Figure:
    """Pie chart of energy consumption breakdown by period (with solar)."""
    labels = ["Punta", "Intermedia", "Base"]
    values = [result["punta_kwh"], result["inter_kwh"], result["base_kwh"]]
    colors = [RED, SOLAR_ORANGE, TEC_BLUE]

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors),
        hole=0.4,
        hovertemplate="%{label}: %{value:,.0f} kWh (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white",
        height=320,
        margin=dict(t=10, b=10),
        legend=dict(orientation="h"),
    )
    return fig


def monthly_savings_bar(monthly_results: list[dict]) -> go.Figure:
    """Grouped bar chart of monthly original vs new bill."""
    months = [r.get("month", i + 1) for i, r in enumerate(monthly_results)]
    month_labels = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    labels = [month_labels[m - 1] for m in months]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Sin FV", x=labels,
                         y=[r["orig_total_mxn"] for r in monthly_results],
                         marker_color=RED))
    fig.add_trace(go.Bar(name="Con FV", x=labels,
                         y=[r["total_mxn"] for r in monthly_results],
                         marker_color=TEC_BLUE))

    fig.update_layout(
        barmode="group",
        template="plotly_white",
        yaxis_title="MXN / mes",
        height=360,
        legend=dict(orientation="h", y=-0.15),
        margin=dict(t=10, b=60),
    )
    return fig


def poa_heatmap(df: pd.DataFrame) -> go.Figure:
    """Heatmap of daily hourly POA irradiance."""
    df2 = df.copy()
    df2["date"] = df2.index.date
    df2["hour"] = df2.index.hour
    pivot = df2.pivot_table(values="poa_global", index="hour", columns="date", aggfunc="mean")

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[str(c) for c in pivot.columns],
        y=pivot.index,
        colorscale="YlOrRd",
        colorbar=dict(title="W/m²"),
        hovertemplate="Date: %{x}<br>Hour: %{y}:00<br>POA: %{z:.0f} W/m²<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white",
        xaxis_title="Date",
        yaxis_title="Hour of Day",
        height=380,
        margin=dict(t=10, b=40),
    )
    return fig
