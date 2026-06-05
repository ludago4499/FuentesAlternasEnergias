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


# ── New: cloud comparison & losses ───────────────────────────────────────────

def irradiance_comparison_plot(
    df_actual: pd.DataFrame,
    df_clearsky: pd.DataFrame,
    selected_date: str | None = None,
) -> go.Figure:
    """
    Overlay actual vs. clear-sky irradiance for a selected day or the full range.
    Top panel: GHI; Bottom panel: POA Global.
    The area between the two curves is shaded to highlight cloud attenuation.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        subplot_titles=["GHI — Cielo despejado vs Real (W/m²)", "POA Global — Cielo despejado vs Real (W/m²)"],
        vertical_spacing=0.12,
    )

    if selected_date:
        d = pd.Timestamp(selected_date).date()
        act = df_actual[df_actual.index.date == d]
        cs = df_clearsky[df_clearsky.index.date == d]
    else:
        act = df_actual
        cs = df_clearsky

    # GHI
    fig.add_trace(go.Scatter(x=cs.index, y=cs["ghi"], name="GHI despejado",
                             line=dict(color=TEC_BLUE, width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=act.index, y=act["ghi"], name="GHI real",
                             line=dict(color=SOLAR_YELLOW, width=2),
                             fill="tonexty", fillcolor="rgba(255,179,0,0.18)"), row=1, col=1)

    # POA
    fig.add_trace(go.Scatter(x=cs.index, y=cs["poa_global"], name="POA despejado",
                             line=dict(color=TEC_BLUE, width=2, dash="dot"),
                             showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=act.index, y=act["poa_global"], name="POA real",
                             line=dict(color=SOLAR_ORANGE, width=2),
                             fill="tonexty", fillcolor="rgba(245,124,0,0.18)",
                             showlegend=False), row=2, col=1)

    fig.update_layout(
        template="plotly_white",
        height=500,
        legend=dict(orientation="h", y=-0.10),
        margin=dict(t=40, b=50),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="W/m²", row=1, col=1)
    fig.update_yaxes(title_text="W/m²", row=2, col=1)
    return fig


def losses_waterfall_chart(losses: dict) -> go.Figure:
    """
    Waterfall chart of the energy loss chain from clear-sky potential to AC output.
    """
    categories = [
        "Potencial cielo despejado",
        "Pérdida nubosidad",
        "Pérdida temperatura",
        "Pérdida suciedad",
        "Pérdida cableado",
        "Pérdida inversor",
        "Generación AC final",
    ]
    measure = ["absolute", "relative", "relative", "relative", "relative", "relative", "total"]
    y = [
        losses["e_clearsky_kwh"],
        -losses["loss_cloud_kwh"],
        -losses["loss_temp_kwh"],
        -losses["loss_soiling_kwh"],
        -losses["loss_wiring_kwh"],
        -losses["loss_inverter_kwh"],
        losses["e_ac_kwh"],
    ]
    text = [
        f"{losses['e_clearsky_kwh']:,.0f} kWh",
        f"-{losses['loss_cloud_pct']:.1f}%",
        f"-{losses['loss_temp_pct']:.1f}%",
        f"-{losses['loss_soiling_pct']:.1f}%",
        f"-{losses['loss_wiring_pct']:.1f}%",
        f"-{losses['loss_inverter_pct']:.1f}%",
        f"{losses['e_ac_kwh']:,.0f} kWh",
    ]

    fig = go.Figure(go.Waterfall(
        name="Pérdidas",
        orientation="v",
        measure=measure,
        x=categories,
        y=y,
        text=text,
        textposition="outside",
        decreasing={"marker": {"color": RED}},
        increasing={"marker": {"color": GREEN}},
        totals={"marker": {"color": TEC_BLUE}},
        connector={"line": {"color": "rgba(150,150,150,0.5)", "width": 1}},
    ))
    fig.update_layout(
        template="plotly_white",
        yaxis_title="kWh",
        height=440,
        margin=dict(t=20, b=80),
        showlegend=False,
        xaxis_tickangle=-18,
    )
    return fig


def poa_exceedance_plot(
    df_actual: pd.DataFrame,
    df_clearsky: pd.DataFrame | None = None,
) -> go.Figure:
    """
    Top panel: exceedance curve (P-curve) — % of daytime hours ≥ POA value.
    Bottom panel: histogram of daytime POA values.
    Marks P50 and P90 on both panels.
    """
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=["Curva de excedencia POA (horario diurno)", "Distribución de POA diurno (histograma)"],
        vertical_spacing=0.14,
    )

    def _exceedance(df: pd.DataFrame, col: str = "poa_global"):
        vals = df[col].values
        daytime = np.sort(vals[vals > 10])[::-1]
        if len(daytime) == 0:
            return np.array([0.0]), np.array([0.0])
        pct = np.linspace(0, 100, len(daytime))
        return pct, daytime

    pct_a, poa_a = _exceedance(df_actual)
    p50_a = float(np.percentile(df_actual["poa_global"].values[df_actual["poa_global"].values > 10], 50)) if (df_actual["poa_global"] > 10).any() else 0
    p90_a = float(np.percentile(df_actual["poa_global"].values[df_actual["poa_global"].values > 10], 10)) if (df_actual["poa_global"] > 10).any() else 0

    fig.add_trace(go.Scatter(x=pct_a, y=poa_a, name="Real", line=dict(color=SOLAR_YELLOW, width=2.5)),
                  row=1, col=1)
    fig.add_hline(y=p50_a, line_dash="dash", line_color=SOLAR_YELLOW, annotation_text=f"P50={p50_a:.0f}",
                  annotation_position="right", row=1, col=1)
    fig.add_hline(y=p90_a, line_dash="dot", line_color=SOLAR_ORANGE, annotation_text=f"P90={p90_a:.0f}",
                  annotation_position="right", row=1, col=1)

    if df_clearsky is not None:
        pct_c, poa_c = _exceedance(df_clearsky)
        fig.add_trace(go.Scatter(x=pct_c, y=poa_c, name="Cielo despejado",
                                 line=dict(color=TEC_BLUE, width=2, dash="dot")), row=1, col=1)

    # Histogram
    daytime_vals = df_actual["poa_global"].values[df_actual["poa_global"].values > 10]
    fig.add_trace(go.Histogram(x=daytime_vals, nbinsx=40, name="POA real",
                               marker_color=SOLAR_YELLOW, opacity=0.75, showlegend=False),
                  row=2, col=1)
    if df_clearsky is not None:
        cs_vals = df_clearsky["poa_global"].values[df_clearsky["poa_global"].values > 10]
        fig.add_trace(go.Histogram(x=cs_vals, nbinsx=40, name="POA despejado",
                                   marker_color=LIGHT_BLUE, opacity=0.55, showlegend=False),
                      row=2, col=1)

    fig.update_layout(
        template="plotly_white",
        height=520,
        legend=dict(orientation="h", y=-0.08),
        margin=dict(t=40, b=50),
        barmode="overlay",
    )
    fig.update_xaxes(title_text="% del tiempo ≥ valor", row=1, col=1)
    fig.update_yaxes(title_text="POA (W/m²)", row=1, col=1)
    fig.update_xaxes(title_text="POA (W/m²)", row=2, col=1)
    fig.update_yaxes(title_text="Horas", row=2, col=1)
    return fig


def efficiency_breakdown_table(losses: dict) -> go.Figure:
    """
    Table showing per-component efficiency factors and loss percentages.
    """
    soiling_pct = losses["soiling_loss_frac"] * 100
    wiring_pct = losses["wiring_loss_frac"] * 100
    temp_derate_pct = (1.0 - losses["avg_temp_derate_factor"]) * 100

    headers = ["Componente", "Factor de eficiencia", "Pérdida (%)"]
    rows = [
        ["Panel FV", f"{losses['panel_efficiency_pct']:.1f} %", "—"],
        ["Temperatura celda (NOCT)", f"{losses['avg_temp_derate_factor']:.3f}", f"{losses['loss_temp_pct']:.2f} %"],
        ["Suciedad / polvo", f"{1 - losses['soiling_loss_frac']:.3f}", f"{soiling_pct:.1f} %"],
        ["Cableado DC", f"{1 - losses['wiring_loss_frac']:.3f}", f"{wiring_pct:.1f} %"],
        ["Inversor", "0.960", f"{losses['loss_inverter_pct']:.2f} %"],
        ["Nubosidad", "—", f"{losses['loss_cloud_pct']:.2f} %"],
        ["Sistema total (AC / Cielo despejado)", "—", f"{100 - losses['overall_system_efficiency_pct']:.2f} % pérdida"],
    ]

    fig = go.Figure(go.Table(
        header=dict(
            values=headers,
            fill_color=TEC_BLUE,
            font=dict(color="white", size=13),
            align="left",
            height=32,
        ),
        cells=dict(
            values=list(zip(*rows)),
            fill_color=[["white", "#F5F5F5"] * (len(rows) // 2 + 1)],
            align="left",
            height=28,
            font=dict(size=12),
        ),
    ))
    fig.update_layout(
        template="plotly_white",
        height=320,
        margin=dict(t=10, b=10),
    )
    return fig


def sunrise_sunset_pattern_plot(df: pd.DataFrame) -> go.Figure:
    """
    Full-range POA heatmap (day-of-year × hour) with sunrise/sunset overlay.
    Shows seasonal availability patterns and cloud variability at a glance.
    """
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
        hovertemplate="Fecha: %{x}<br>Hora: %{y}:00<br>POA: %{z:.0f} W/m²<extra></extra>",
    ))

    # Sunrise / sunset overlay from zenith column (zenith < 90° → sunlit)
    if "zenith" in df.columns:
        df3 = df.copy()
        df3["date"] = df3.index.date
        df3["hour"] = df3.index.hour
        sunrise = df3[df3["zenith"] < 89].groupby("date")["hour"].min()
        sunset = df3[df3["zenith"] < 89].groupby("date")["hour"].max()
        dates_str = [str(d) for d in sunrise.index]
        fig.add_trace(go.Scatter(x=dates_str, y=sunrise.values, name="Salida del sol",
                                 mode="lines", line=dict(color="white", width=1.5, dash="dot"),
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=dates_str, y=sunset.values, name="Puesta del sol",
                                 mode="lines", line=dict(color="white", width=1.5, dash="dot"),
                                 hoverinfo="skip"))

    fig.update_layout(
        template="plotly_white",
        xaxis_title="Fecha",
        yaxis_title="Hora del día",
        height=420,
        legend=dict(orientation="h", y=-0.10),
        margin=dict(t=10, b=50),
    )
    return fig
