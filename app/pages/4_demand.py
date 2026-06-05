import sys
from pathlib import Path
import io

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.plots import demand_injection_plot

st.set_page_config(page_title="Demanda e Inyección — GDMTH Solar", page_icon="📊", layout="wide")

st.markdown("<h1 style='color:#0039A6;font-weight:700'>Demanda Industrial e Inyección Solar</h1>",
            unsafe_allow_html=True)
st.caption("Genera un perfil típico sintético o sube tu propia curva de carga.")

DATA_DIR = Path(__file__).parent.parent / "data"

# ─────────────────────────────────────────────────────────────────────────────
# DEMAND PROFILE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

# Industry archetypes: (label, base_factor, daily_shape, weekend_factor, seasonal_summer)
# daily_shape: list of 24 hourly multipliers (0–1) relative to peak demand
_SHAPES = {
    "Manufactura / Automotriz": {
        "base_factor": 0.40,
        "weekend_factor": 0.45,
        "seasonal_summer": 1.08,
        "hourly": [0.42, 0.40, 0.39, 0.38, 0.39, 0.43,   # 00–05 (Base)
                   0.65, 0.82, 0.95, 0.98, 1.00, 0.99,   # 06–11 (Intermedia/ramp)
                   0.97, 0.96, 0.97, 0.96, 0.95, 0.96,   # 12–17
                   0.98, 1.00, 0.99, 0.95, 0.80, 0.55],  # 18–23 (Punta peak)
        "noise_pct": 3.5,
    },
    "Alimentos y Bebidas (24/7)": {
        "base_factor": 0.68,
        "weekend_factor": 0.90,
        "seasonal_summer": 1.05,
        "hourly": [0.72, 0.70, 0.69, 0.68, 0.70, 0.73,
                   0.78, 0.85, 0.90, 0.92, 0.93, 0.94,
                   0.95, 0.94, 0.93, 0.92, 0.93, 0.96,
                   1.00, 0.99, 0.97, 0.90, 0.82, 0.76],
        "noise_pct": 2.5,
    },
    "Comercio / Retail": {
        "base_factor": 0.20,
        "weekend_factor": 0.85,
        "seasonal_summer": 1.12,
        "hourly": [0.22, 0.20, 0.19, 0.19, 0.20, 0.22,
                   0.28, 0.45, 0.70, 0.88, 0.96, 1.00,
                   0.99, 0.97, 0.96, 0.95, 0.94, 0.97,
                   0.99, 0.98, 0.90, 0.72, 0.45, 0.28],
        "noise_pct": 4.0,
    },
    "Minería / Extracción": {
        "base_factor": 0.75,
        "weekend_factor": 0.95,
        "seasonal_summer": 1.02,
        "hourly": [0.80, 0.79, 0.78, 0.78, 0.79, 0.82,
                   0.88, 0.93, 0.97, 0.99, 1.00, 1.00,
                   0.99, 0.99, 0.99, 0.98, 0.97, 0.97,
                   0.96, 0.95, 0.93, 0.90, 0.87, 0.83],
        "noise_pct": 2.0,
    },
    "Bodega Frigorífica": {
        "base_factor": 0.60,
        "weekend_factor": 0.70,
        "seasonal_summer": 1.18,
        "hourly": [0.62, 0.60, 0.59, 0.59, 0.61, 0.65,
                   0.72, 0.80, 0.88, 0.93, 0.96, 0.98,
                   1.00, 0.99, 0.98, 0.97, 0.95, 0.95,
                   0.96, 0.97, 0.95, 0.88, 0.78, 0.69],
        "noise_pct": 3.0,
    },
}

VERANO_MONTHS = {4, 5, 6, 7, 8, 9, 10}


def generate_demand_profile(
    index: pd.DatetimeIndex,
    peak_kw: float,
    industry: str,
    seed: int = 42,
) -> pd.Series:
    """
    Generate synthetic hourly demand (kW) for the given DatetimeIndex.

    Formula per period:
        demand_i = peak_kw × shape[hour] × weekday_factor × season_factor × (1 + ε)
    where ε ~ N(0, noise_pct/100).
    """
    rng = np.random.default_rng(seed)
    arch = _SHAPES[industry]
    hourly_shape = np.array(arch["hourly"])
    noise_std = arch["noise_pct"] / 100.0

    demands = []
    for ts in index:
        h = ts.hour
        wd = ts.weekday()
        month = ts.month

        shape = hourly_shape[h]
        wf = arch["weekend_factor"] if wd >= 5 else 1.0
        sf = arch["seasonal_summer"] if month in VERANO_MONTHS else 1.0
        noise = 1.0 + rng.normal(0, noise_std)
        noise = max(0.85, min(noise, 1.15))

        demands.append(peak_kw * shape * wf * sf * noise)

    return pd.Series(demands, index=index, name="demand")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

tab_gen, tab_upload = st.tabs(["Generador de perfil típico", "Subir CSV propio"])

# ── TAB 1: Generator ──────────────────────────────────────────────────────────
with tab_gen:
    st.markdown("### Perfil típico de demanda industrial")
    st.caption("Genera una serie de tiempo sintética parametrizable para usar directamente en el análisis.")

    col_g1, col_g2 = st.columns([2, 1])
    with col_g1:
        industry = st.selectbox("Tipo de industria", list(_SHAPES.keys()))
        peak_kw = st.number_input("Demanda pico (kW)", min_value=50.0, max_value=20000.0,
                                   value=600.0, step=50.0)
    with col_g2:
        # Date range aligned with solar model if available
        solar_start = st.session_state.get("solar_start")
        solar_end   = st.session_state.get("solar_end")
        import datetime
        default_start = pd.Timestamp(solar_start).date() if solar_start else datetime.date(2024, 1, 1)
        default_end   = pd.Timestamp(solar_end).date()   if solar_end   else datetime.date(2024, 12, 31)

        gen_start = st.date_input("Desde", value=default_start, key="gen_start")
        gen_end   = st.date_input("Hasta", value=default_end,   key="gen_end")
        seed      = st.number_input("Semilla aleatoria", min_value=0, max_value=999, value=42, step=1)

    tz = st.session_state.get("tz", "America/Monterrey")

    # Live profile preview
    arch = _SHAPES[industry]
    preview_hours = np.arange(24)
    preview_vals  = np.array(arch["hourly"]) * peak_kw
    fig_prev = go.Figure()
    fig_prev.add_trace(go.Scatter(x=preview_hours, y=preview_vals,
                                   mode="lines+markers", line=dict(color="#0039A6", width=2.5),
                                   name="Perfil típico (día laboral)"))
    fig_prev.add_vrect(x0=18, x1=22, fillcolor="rgba(197,57,41,0.10)", line_width=0,
                        annotation_text="Punta", annotation_position="top left")
    fig_prev.update_layout(template="plotly_white", height=240,
                            xaxis=dict(title="Hora del día", tickvals=list(range(0, 24, 2))),
                            yaxis_title="kW", margin=dict(t=10, b=30),
                            showlegend=False)
    st.plotly_chart(fig_prev, use_container_width=True)

    st.markdown(f"""
    | Parámetro | Valor |
    |-----------|-------|
    | Factor base (nocturno) | {arch['base_factor']*100:.0f}% de pico |
    | Factor fin de semana | {arch['weekend_factor']*100:.0f}% del día laboral |
    | Factor estacional verano | {arch['seasonal_summer']:.2f}× |
    | Ruido aleatorio (σ) | ±{arch['noise_pct']:.1f}% |
    """)

    if st.button("Generar serie de tiempo", type="primary", use_container_width=True):
        if gen_end < gen_start:
            st.error("La fecha fin debe ser mayor a la fecha inicio.")
        else:
            with st.spinner("Generando perfil de demanda…"):
                idx = pd.date_range(start=str(gen_start), end=str(gen_end),
                                     freq="h", tz=tz, inclusive="left")
                # extend to cover full end day
                idx_full = pd.date_range(
                    start=str(gen_start),
                    end=(pd.Timestamp(gen_end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    freq="h", tz=tz, inclusive="left"
                )
                series = generate_demand_profile(idx_full, peak_kw, industry, seed=int(seed))
                df_gen = series.to_frame(name="demand")
                st.session_state["demand_df"] = df_gen
                st.session_state["demand_source"] = f"Sintético — {industry} — {peak_kw:.0f} kW pico"
            n_days_gen = (gen_end - gen_start).days + 1
            n_periods  = len(df_gen)
            st.success(
                f"Perfil generado: **{n_periods:,} períodos horarios** "
                f"({n_days_gen} días) | "
                f"E total = {df_gen['demand'].sum():.0f} kWh"
            )

# ── TAB 2: Upload ─────────────────────────────────────────────────────────────
with tab_upload:
    with open(DATA_DIR / "sample_load.csv", "rb") as f:
        sample_bytes = f.read()
    st.download_button("Descargar plantilla CSV de muestra", data=sample_bytes,
                        file_name="plantilla_carga_industrial.csv", mime="text/csv")
    st.caption("Formato: columnas `timestamp` (YYYY-MM-DD HH:MM:SS) y `demand_kw` (kW, resolución horaria).")

    uploaded = st.file_uploader("Sube tu CSV de curva de carga industrial", type=["csv"])
    if uploaded:
        try:
            df_up = pd.read_csv(uploaded, parse_dates=["timestamp"])
            df_up = df_up.rename(columns={"timestamp": "ts", "demand_kw": "demand"})
            df_up = df_up.set_index("ts").sort_index()
            df_up.index = pd.DatetimeIndex(df_up.index)
            st.session_state["demand_df"] = df_up
            st.session_state["demand_source"] = "CSV cargado por usuario"
            st.success(f"Cargado: {len(df_up):,} filas | pico = {df_up['demand'].max():.1f} kW")
        except Exception as e:
            st.error(f"Error al leer el archivo: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS (uses whichever source is in session_state)
# ─────────────────────────────────────────────────────────────────────────────
st.divider()

demand_df = st.session_state.get("demand_df")
if demand_df is None:
    # Auto-load sample so something is always visible
    _idx = pd.date_range("2024-01-01", periods=168, freq="h", tz="America/Monterrey")
    _s = generate_demand_profile(_idx, 600.0, "Manufactura / Automotriz", seed=42)
    demand_df = _s.to_frame(name="demand")
    st.session_state["demand_df"] = demand_df
    st.session_state["demand_source"] = "Sintético — muestra automática"
    st.info("Usando perfil de muestra automático. Ve a **Generador de perfil típico** para personalizar.")

source_label = st.session_state.get("demand_source", "Desconocido")
st.markdown(f"**Fuente de demanda activa:** `{source_label}`")

# ── Solar injection ───────────────────────────────────────────────────────────
df_irr = st.session_state.get("irradiance_df")

def align_solar(dem: pd.DataFrame, sol_df: pd.DataFrame) -> pd.Series:
    s = sol_df["pv_kw"].copy()
    dt_h = sol_df.attrs.get("dt_h", 1.0)
    if dt_h < 1.0:
        s = s.resample("h").mean()
    return s.reindex(dem.index, method="nearest",
                     tolerance=pd.Timedelta("65min")).fillna(0.0)

allow_export = st.toggle("Permitir exportación (venta a red)", value=False)

if df_irr is not None:
    solar_kw = align_solar(demand_df, df_irr)
else:
    solar_kw = pd.Series(0.0, index=demand_df.index)
    st.warning("Ejecuta primero el modelo solar (página **Análisis Solar**) para ver la inyección.")

st.session_state["solar_aligned"] = solar_kw

net_kw = (demand_df["demand"] - solar_kw) if allow_export else (demand_df["demand"] - solar_kw).clip(lower=0)
st.session_state["net_demand"] = net_kw

# ── Period view selector ──────────────────────────────────────────────────────
dates = sorted(set(demand_df.index.date))
col_f1, col_f2 = st.columns(2)
start_view = col_f1.selectbox("Ver desde", dates, index=0)
end_view   = col_f2.selectbox("Ver hasta", dates, index=min(6, len(dates) - 1))

mask     = (demand_df.index.date >= start_view) & (demand_df.index.date <= end_view)
dem_view = demand_df.loc[mask, "demand"]
sol_view = solar_kw.loc[mask]
net_view = net_kw.loc[mask]

# ── Metrics ───────────────────────────────────────────────────────────────────
st.markdown("### Métricas del período seleccionado")
peak_orig = dem_view.max()
peak_net  = net_view.max()
peak_shaving  = (peak_orig - peak_net) / peak_orig * 100 if peak_orig > 0 else 0.0
total_dem_kwh = float(dem_view.sum())
total_sol_kwh = float(sol_view.sum())
self_ratio    = min(total_sol_kwh, total_dem_kwh) / total_sol_kwh * 100 if total_sol_kwh > 0 else 0.0
surplus_kwh   = max(0.0, total_sol_kwh - total_dem_kwh)

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Demanda pico original",  f"{peak_orig:.1f} kW")
m2.metric("Demanda pico neta",      f"{peak_net:.1f} kW")
m3.metric("Peak shaving",           f"{peak_shaving:.1f} %")
m4.metric("Autoconsumo solar",      f"{self_ratio:.1f} %")
m5.metric("Excedente FV",           f"{surplus_kwh:.1f} kWh")
m6.metric("Reducción energía",
          f"{(total_dem_kwh - float(net_view.sum())) / total_dem_kwh * 100:.1f} %"
          if total_dem_kwh > 0 else "—")

# ── Dual plot ─────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### Curva de carga vs. inyección solar")
fig = demand_injection_plot(dem_view, sol_view, net_view)
st.plotly_chart(fig, use_container_width=True)

# ── Load duration curve ───────────────────────────────────────────────────────
st.divider()
st.markdown("### Curva de duración de carga")
sorted_orig = np.sort(dem_view.values)[::-1]
sorted_net  = np.sort(net_view.values)[::-1]
hours_axis  = np.arange(1, len(sorted_orig) + 1)

fig_ldc = go.Figure()
fig_ldc.add_trace(go.Scatter(x=hours_axis, y=sorted_orig, name="Sin FV",
                              line=dict(color="#C62828", width=2)))
fig_ldc.add_trace(go.Scatter(x=hours_axis, y=sorted_net,  name="Con FV",
                              line=dict(color="#0039A6", width=2),
                              fill="tonexty", fillcolor="rgba(0,57,166,0.10)"))
fig_ldc.update_layout(template="plotly_white",
                       xaxis_title="Períodos (ordenados de mayor a menor carga)",
                       yaxis_title="Demanda (kW)", height=360,
                       legend=dict(orientation="h"), hovermode="x unified",
                       margin=dict(t=10, b=40))
st.plotly_chart(fig_ldc, use_container_width=True)

# ── Hourly stats table ────────────────────────────────────────────────────────
st.divider()
with st.expander("Tabla de serie de tiempo (primeras 168 horas)"):
    disp = pd.DataFrame({
        "Timestamp":        demand_df.index[:168],
        "Demanda (kW)":     demand_df["demand"].values[:168].round(1),
        "Solar FV (kW)":    solar_kw.values[:168].round(1),
        "Demanda neta (kW)":net_kw.values[:168].round(1),
    })
    st.dataframe(disp, use_container_width=True, hide_index=True)

# ── Download ──────────────────────────────────────────────────────────────────
result_df = pd.DataFrame({
    "timestamp":      demand_df.index.strftime("%Y-%m-%d %H:%M:%S"),
    "demand_kw":      demand_df["demand"].values.round(2),
    "solar_kw":       solar_kw.values.round(2),
    "net_demand_kw":  net_kw.values.round(2),
})
st.download_button("Descargar serie de tiempo completa (CSV)",
                    data=result_df.to_csv(index=False).encode(),
                    file_name="demanda_neta_solar.csv", mime="text/csv")