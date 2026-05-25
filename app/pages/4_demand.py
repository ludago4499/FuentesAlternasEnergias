import sys
from pathlib import Path
import io

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.plots import demand_injection_plot

st.set_page_config(page_title="Demanda e Inyección — GDMTH Solar", page_icon="📊", layout="wide")

st.markdown("<h1 style='color:#0039A6;font-weight:700'>Demanda Industrial e Inyección Solar</h1>",
            unsafe_allow_html=True)

DATA_DIR = Path(__file__).parent.parent / "data"

# ── Template download ─────────────────────────────────────────────────────────
with open(DATA_DIR / "sample_load.csv", "rb") as f:
    sample_bytes = f.read()

st.download_button(
    "Descargar plantilla de carga (CSV de muestra)",
    data=sample_bytes,
    file_name="plantilla_carga_industrial.csv",
    mime="text/csv",
)

st.caption("Formato requerido: columnas `timestamp` (YYYY-MM-DD HH:MM:SS) y `demand_kw` (potencia en kW, resolución horaria).")

# ── Upload ────────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Sube tu CSV de curva de carga industrial", type=["csv"])

allow_export = st.toggle("Permitir exportación (venta a red)", value=False,
                          help="Si se activa, el excedente solar se exporta. Por defecto solo autoconsumo.")


def load_demand(file_obj) -> pd.DataFrame:
    df = pd.read_csv(file_obj, parse_dates=["timestamp"])
    df = df.rename(columns={"timestamp": "ts", "demand_kw": "demand"})
    df = df.set_index("ts").sort_index()
    df.index = pd.DatetimeIndex(df.index)
    return df


def align_solar(demand_df: pd.DataFrame, solar_df: pd.DataFrame) -> pd.Series:
    """Reindex solar to match demand timestamps."""
    solar_hourly = solar_df["pv_kw"].copy()
    solar_aligned = solar_hourly.reindex(demand_df.index, method="nearest",
                                          tolerance=pd.Timedelta("30min")).fillna(0.0)
    return solar_aligned


if uploaded:
    try:
        df_demand = load_demand(uploaded)
        st.session_state["demand_df"] = df_demand
    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")
        st.stop()
elif "demand_df" in st.session_state:
    df_demand = st.session_state["demand_df"]
    st.info("Usando la curva de carga cargada anteriormente.")
else:
    st.info("Carga un CSV o usa la plantilla de muestra para continuar.")
    # Auto-load sample for demo
    df_demand = load_demand(DATA_DIR / "sample_load.csv")
    st.session_state["demand_df"] = df_demand
    st.caption("Vista previa con datos de muestra.")

# ── Solar injection ───────────────────────────────────────────────────────────
df_irr = st.session_state.get("irradiance_df")
system_kwp = st.session_state.get("system_kwp", 0.0)

if df_irr is None:
    st.warning("Ejecuta primero el modelo solar en la página **Análisis Solar** para ver la inyección.")
    solar_kw = pd.Series(0.0, index=df_demand.index)
else:
    solar_kw = align_solar(df_demand, df_irr)
    st.session_state["solar_aligned"] = solar_kw

# Net demand
if allow_export:
    net_kw = df_demand["demand"] - solar_kw
else:
    net_kw = (df_demand["demand"] - solar_kw).clip(lower=0)

st.session_state["net_demand"] = net_kw

# ── Period filter ─────────────────────────────────────────────────────────────
st.divider()
dates = sorted(set(df_demand.index.date))
col_f1, col_f2 = st.columns(2)
start_view = col_f1.selectbox("Desde", dates, index=0)
end_view = col_f2.selectbox("Hasta", dates, index=min(6, len(dates) - 1))

mask = (df_demand.index.date >= start_view) & (df_demand.index.date <= end_view)
dem_view = df_demand.loc[mask, "demand"]
sol_view = solar_kw.loc[mask]
net_view = net_kw.loc[mask]

# ── Metrics ───────────────────────────────────────────────────────────────────
st.markdown("### Métricas del período seleccionado")
peak_orig = dem_view.max()
peak_net = net_view.max()
peak_shaving = (peak_orig - peak_net) / peak_orig * 100 if peak_orig > 0 else 0.0

total_demand_kwh = dem_view.sum()
total_solar_kwh = sol_view.sum()
self_consumption = min(total_solar_kwh, total_demand_kwh)
self_ratio = self_consumption / total_solar_kwh * 100 if total_solar_kwh > 0 else 0.0

surplus_kwh = max(0.0, float(total_solar_kwh) - float(total_demand_kwh))

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Demanda pico original", f"{peak_orig:.1f} kW")
m2.metric("Demanda pico neta", f"{peak_net:.1f} kW")
m3.metric("Peak shaving", f"{peak_shaving:.1f} %")
m4.metric("Autoconsumo", f"{self_ratio:.1f} %")
m5.metric("Excedente", f"{surplus_kwh:.1f} kWh")

# ── Dual plot ─────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### Curva de carga vs. inyección solar")
fig = demand_injection_plot(dem_view, sol_view, net_view)
st.plotly_chart(fig, use_container_width=True)

# ── Load duration curve ───────────────────────────────────────────────────────
st.divider()
st.markdown("### Curva de duración de carga")
import plotly.graph_objects as go

sorted_orig = np.sort(dem_view.values)[::-1]
sorted_net = np.sort(net_view.values)[::-1]
hours_axis = np.arange(1, len(sorted_orig) + 1)

fig_ldc = go.Figure()
fig_ldc.add_trace(go.Scatter(x=hours_axis, y=sorted_orig, name="Sin FV",
                              line=dict(color="#C62828", width=2)))
fig_ldc.add_trace(go.Scatter(x=hours_axis, y=sorted_net, name="Con FV",
                              line=dict(color="#0039A6", width=2),
                              fill="tonexty", fillcolor="rgba(0,57,166,0.1)"))
fig_ldc.update_layout(
    template="plotly_white",
    xaxis_title="Horas (ordenadas de mayor a menor carga)",
    yaxis_title="Demanda (kW)",
    height=360,
    legend=dict(orientation="h"),
    margin=dict(t=10, b=40),
    hovermode="x unified",
)
st.plotly_chart(fig_ldc, use_container_width=True)

# ── Hourly stats table ────────────────────────────────────────────────────────
st.divider()
with st.expander("Tabla de datos horarios (primeras 168 horas)"):
    display_df = pd.DataFrame({
        "Timestamp": df_demand.index[:168],
        "Demanda (kW)": df_demand["demand"].values[:168].round(1),
        "Solar FV (kW)": solar_kw.values[:168].round(1),
        "Demanda neta (kW)": net_kw.values[:168].round(1),
    })
    st.dataframe(display_df, use_container_width=True, hide_index=True)

# ── Download processed data ───────────────────────────────────────────────────
result_df = pd.DataFrame({
    "timestamp": df_demand.index,
    "demand_kw": df_demand["demand"].values.round(2),
    "solar_kw": solar_kw.values.round(2),
    "net_demand_kw": net_kw.values.round(2),
})
st.download_button("Descargar demanda neta procesada (CSV)",
                    data=result_df.to_csv(index=False).encode(),
                    file_name="demanda_neta_solar.csv", mime="text/csv")
