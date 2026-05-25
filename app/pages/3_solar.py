import sys
from pathlib import Path
import datetime

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.jensen import run_jensen_model, compute_pv_generation, capacity_factor, peak_sun_hours, energy_kwh
from core.plots import irradiance_plot, generation_bar, poa_heatmap

st.set_page_config(page_title="Análisis Solar — GDMTH Solar", page_icon="🌞", layout="wide")

st.markdown("<h1 style='color:#0039A6;font-weight:700'>Análisis Solar — Modelo Jensen (pvlib)</h1>",
            unsafe_allow_html=True)

# ── Check config ─────────────────────────────────────────────────────────────
if "lat" not in st.session_state:
    st.warning("Primero configura la ubicación y sistema en la página **Configuración**.")
    st.stop()

lat = st.session_state["lat"]
lon = st.session_state["lon"]
tilt = st.session_state.get("tilt", 20.0)
azimuth_user = st.session_state.get("azimuth", 0.0)   # 0=Sur, −=Este, +=Oeste
azimuth_pvlib = (180.0 + azimuth_user) % 360.0        # pvlib: 0=Norte, 90=Este, 180=Sur
tz = st.session_state.get("tz", "America/Monterrey")
altitude = st.session_state.get("altitude", 500.0)
system_kwp = st.session_state.get("system_kwp", 50.0)
n_panels_cfg = st.session_state.get("n_panels", 100)
panel = st.session_state.get("panel", {"wp": 580, "efficiency_pct": 22.3,
                                        "temp_coeff_pmax": -0.30, "noct": 43, "area_m2": 2.583})

panel_area_m2 = panel.get("area_m2")
panel_wp = panel.get("wp", 580)
panel_eta = panel.get("efficiency_pct", 22.3)
total_panel_area_m2 = n_panels_cfg * (panel_area_m2 or panel_wp / (1000.0 * panel_eta / 100.0))

az_label = f"{azimuth_user:+.0f}° ({'Sur' if azimuth_user == 0 else 'Este' if azimuth_user < 0 else 'Oeste'})"
st.markdown(f"""
**Ubicación:** {lat:.4f}°N, {lon:.4f}°E &nbsp;|&nbsp;
**Inclinación:** {tilt}° &nbsp;|&nbsp;
**Azimut:** {az_label} &nbsp;|&nbsp;
**Sistema:** {system_kwp:.2f} kWp &nbsp;|&nbsp;
**Área total paneles:** {total_panel_area_m2:.1f} m²
""")

# ── Lecture formula display ───────────────────────────────────────────────────
with st.expander("Fórmula de generación (Instrucciones de Tarea)", expanded=True):
    st.markdown(r"""
    $$\text{Pow} \; [kW] = \text{POA} \; [W/m^2] \times \text{Área}_{panel} \; [m^2] \times \eta_{panel}$$

    $$E_{anual} \; [kWh] = \sum_{i=1}^{N} \left( \text{Pow}_i \times \frac{\Delta t \; [min]}{60} \right)$$
    """)
    col_f1, col_f2 = st.columns(2)
    col_f1.info(f"**Área por panel:** {panel_area_m2:.3f} m²  |  **Área total:** {total_panel_area_m2:.1f} m²  |  **η:** {panel_eta} %")
    col_f2.info("**Quinceminutal:** N = 35,040 periodos/año, Δt = 15 min  |  **Horario:** N = 8,760, Δt = 60 min")

# ── Date range and resolution ─────────────────────────────────────────────────
st.divider()
col_d1, col_d2, col_res = st.columns([2, 2, 1])
start_dt = col_d1.date_input("Fecha inicio", value=datetime.date(2024, 1, 1),
                              min_value=datetime.date(2020, 1, 1),
                              max_value=datetime.date(2025, 12, 31))
end_dt = col_d2.date_input("Fecha fin", value=datetime.date(2024, 1, 31),
                             min_value=datetime.date(2020, 1, 1),
                             max_value=datetime.date(2025, 12, 31))
resolution = col_res.radio("Resolución temporal", ["Horaria (1 h)", "Quinceminutal (15 min)"],
                            index=0, help="Quinceminutal genera 4× más puntos — usa rangos cortos (<30 días)")

freq = "15min" if "Quinceminutal" in resolution else "h"
dt_h = 0.25 if freq == "15min" else 1.0

if end_dt < start_dt:
    st.error("La fecha fin debe ser mayor a la fecha inicio.")
    st.stop()

n_days = (end_dt - start_dt).days + 1
n_periods_expected = n_days * (96 if freq == "15min" else 24)

if n_days > 366:
    st.warning("El rango máximo recomendado es 1 año.")
if freq == "15min" and n_days > 31:
    st.warning("Resolución quinceminutal con más de 31 días puede ser lenta. Considera usar rango mensual.")

st.caption(f"Períodos esperados: **{n_periods_expected:,}** | N anual equivalente: **{'35,040' if freq=='15min' else '8,760'}**")

# ── Run model ─────────────────────────────────────────────────────────────────
run_col, _ = st.columns([1, 3])
run_btn = run_col.button("Ejecutar modelo Jensen", type="primary", use_container_width=True)

if run_btn or "irradiance_df" in st.session_state:
    if run_btn:
        with st.spinner(f"Calculando irradiancia ({resolution}) con modelo isótropo (Jensen)…"):
            try:
                df_irr = run_jensen_model(
                    lat=lat, lon=lon, tilt=tilt, azimuth=azimuth_pvlib,
                    start_date=str(start_dt), end_date=str(end_dt),
                    tz=tz, altitude=altitude, freq=freq,
                )
                df_irr["pv_kw"] = compute_pv_generation(
                    df_irr,
                    system_kwp=system_kwp,
                    panel_efficiency=panel_eta,
                    panel_wp=panel_wp,
                    panel_area_m2=panel_area_m2,
                    n_panels=n_panels_cfg,
                    temp_coeff_pmax=panel.get("temp_coeff_pmax", -0.30),
                    noct=panel.get("noct", 43),
                )
                st.session_state["irradiance_df"] = df_irr
                st.session_state["solar_start"] = str(start_dt)
                st.session_state["solar_end"] = str(end_dt)
                st.session_state["solar_freq"] = freq
            except Exception as e:
                st.error(f"Error en el modelo: {e}")
                st.stop()

    df = st.session_state.get("irradiance_df")
    if df is None:
        st.stop()

    _dt_h = df.attrs.get("dt_h", 1.0)

    # ── KPI metrics ───────────────────────────────────────────────────────────
    total_kwh = energy_kwh(df["pv_kw"], df)
    cf = capacity_factor(df["pv_kw"], system_kwp, df) * 100
    psh = peak_sun_hours(df)
    max_poa = float(df["poa_global"].max())
    avg_daily_kwh = total_kwh / max(n_days, 1)
    n_periods_actual = len(df)

    st.divider()
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Generación total", f"{total_kwh:,.0f} kWh")
    m2.metric("Períodos calculados", f"{n_periods_actual:,}")
    m3.metric("Factor de capacidad", f"{cf:.1f} %")
    m4.metric("PSH totales", f"{psh:.1f} h")
    m5.metric("POA máxima", f"{max_poa:.0f} W/m²")
    m6.metric("Promedio diario", f"{avg_daily_kwh:.1f} kWh/día")

    # ── Explicit formula with numbers ─────────────────────────────────────────
    with st.expander("Verificación del cálculo con valores reales"):
        poa_sample = float(df["poa_global"].mean())
        pow_sample = poa_sample * total_panel_area_m2 * (panel_eta / 100.0) / 1000.0
        st.markdown(f"""
        **Con valores del sistema configurado:**
        - Área total = {n_panels_cfg} paneles × {panel_area_m2:.3f} m² = **{total_panel_area_m2:.1f} m²**
        - POA promedio del período = **{poa_sample:.1f} W/m²**
        - Pow promedio = {poa_sample:.1f} × {total_panel_area_m2:.1f} × {panel_eta/100:.3f} / 1000 = **{pow_sample:.2f} kW**
        - E total = Σ(Pow_i × {_dt_h} h) = **{total_kwh:,.0f} kWh** en {n_periods_actual:,} períodos
        """)

    # ── Day picker for daily plot ─────────────────────────────────────────────
    st.divider()
    st.markdown("### Irradiancia diaria")
    available_dates = sorted(set(df.index.date))
    selected_date = st.select_slider("Selecciona día", options=available_dates,
                                      value=available_dates[0])
    fig_irr = irradiance_plot(df, selected_date=str(selected_date))
    st.plotly_chart(fig_irr, use_container_width=True)

    # ── Aggregation bar chart ─────────────────────────────────────────────────
    st.divider()
    st.markdown("### Generación FV agregada")
    agg_opt = st.radio("Agregación", ["Diaria", "Semanal", "Mensual"], horizontal=True)
    freq_map_agg = {"Diaria": "D", "Semanal": "W", "Mensual": "ME"}
    # For bar chart, resample power × dt_h to get kWh sums
    df_energy = df.copy()
    df_energy["pv_kw"] = df_energy["pv_kw"] * _dt_h   # convert to kWh per interval
    fig_bar = generation_bar(df_energy, freq=freq_map_agg[agg_opt])
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── POA heatmap (hourly resolution only for clarity) ──────────────────────
    if n_days <= 62 and freq == "h":
        st.divider()
        st.markdown("### Mapa de calor — POA horaria (W/m²)")
        fig_heat = poa_heatmap(df)
        st.plotly_chart(fig_heat, use_container_width=True)

    # ── Raw data download ─────────────────────────────────────────────────────
    st.divider()
    csv_data = df.to_csv().encode()
    st.download_button("Descargar datos de irradiancia (CSV)", csv_data,
                        file_name="irradiancia_jensen.csv", mime="text/csv")

    # ── Methodology note ──────────────────────────────────────────────────────
    with st.expander("Notas metodológicas"):
        st.markdown(f"""
        - **Modelo de cielo claro:** Ineichen-Perez (`pvlib.location.get_clearsky`)
        - **Transposición:** Modelo isótropo difuso (Jensen) — `pvlib.irradiance.get_total_irradiance(model='isotropic')`
        - **Resolución temporal:** {resolution} (Δt = {_dt_h} h, N anual = {'35,040' if freq == '15min' else '8,760'})
        - **Temperatura de celda (NOCT):** $T_{{cell}} = T_{{amb}} + (NOCT-20) \\cdot G_{{POA}}/800$
        - **Fórmula de potencia:** $Pow = POA \\times Área_{{panel}} \\times \\eta_{{panel}}$
        - **Fórmula de energía:** $E = \\sum_{{i=1}}^{{N}} Pow_i \\times \\Delta t$
        - **Albedo:** 0.25 | **η inversor:** 96%
        - **Coordenadas:** {lat}°N, {lon}°E | Altitud: {altitude} msnm
        - **Referencia:** Jensen et al. (2022). SoftwareX. [DOI:10.1016/j.softx.2022.101070](https://doi.org/10.1016/j.softx.2022.101070)
        """)
else:
    st.info("Configura los parámetros y haz clic en **Ejecutar modelo Jensen** para calcular la generación solar.")
