import sys
from pathlib import Path
import datetime

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.jensen import (run_jensen_model, compute_pv_generation, capacity_factor,
                          peak_sun_hours, energy_kwh, compute_losses_breakdown)
from core.plots import (irradiance_plot, generation_bar, poa_heatmap,
                         irradiance_comparison_plot, losses_waterfall_chart,
                         poa_exceedance_plot, efficiency_breakdown_table,
                         sunrise_sunset_pattern_plot)
from core.exporting import chart_with_export
from core.state import keep_state
from utils.theming import inject_theme, custom_metric

st.set_page_config(page_title="Análisis Solar — GDMTH Solar", page_icon="🌞", layout="wide")
keep_state()

inject_theme("03")
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
n_panels_cfg = st.session_state.get("n_panels", 30)
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
with st.expander("Fórmula implementada", expanded=True):
    st.markdown(r"""
    $$\text{Pow} \; [kW] = \text{POA} \; [W/m^2] \times \text{Área}_{panel} \; [m^2] \times \eta_{panel}$$

    $$E_{anual} \; [kWh] = \sum_{i=1}^{N} \left( \text{Pow}_i \times \frac{\Delta t \; [min]}{60} \right)$$
    """)
    col_f1, col_f2 = st.columns(2)
    col_f1.info(f"**Área por panel:** {panel_area_m2:.3f} m²  |  **Área total:** {total_panel_area_m2:.1f} m²  |  **η:** {panel_eta} %")
    col_f2.info("**Quinceminutal:** N = 35,040 periodos/año, Δt = 15 min  |  **Horario:** N = 8,760, Δt = 60 min")

# ── Date range and resolution ─────────────────────────────────────────────────
st.divider()
st.markdown(f""" **Elige el intérvalo de fechas** \\
            Temporalmente solo permite fechas entre 2020 y 2025""")

col_d1, col_d2, col_res = st.columns([2, 2, 1])
start_dt = col_d1.date_input("Fecha inicio", value=datetime.date(2024, 1, 1),
                              min_value=datetime.date(2020, 1, 1),
                              max_value=datetime.date(2025, 12, 31))
end_dt = col_d2.date_input("Fecha fin", value=datetime.date(2024, 1, 31),
                             min_value=datetime.date(2020, 1, 1),
                             max_value=datetime.date(2025, 12, 31))
resolution = col_res.radio("Resolución temporal", ["Horaria (1 h)", "Quinceminutal (15 min)"],
                            index=1, help="Quinceminutal genera 4× más puntos, tomando 4 intérvalos cada hora.")

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
    st.warning("Resolución quinceminutal con más de 31 días puede ser lenta.")

st.caption(f"Períodos esperados: **{n_periods_expected:,}** | N anual equivalente: **{'35,040' if freq=='15min' else '8,760'}**")

# ── Weather source ─────────────────────────────────────────────────────────────
st.divider()
with st.expander("Fuente de datos meteorológicos", expanded=True):
    _SOURCE_LABELS = {
        "Variabilidad estocástica — AR(1)": "stochastic",
        "Cielo despejado (modelo ideal)": "clearsky",
    }
    weather_label = st.radio(
        "Fuente de datos",
        list(_SOURCE_LABELS.keys()),
        index=0,  # Variabilidad estocástica (AR-1) por defecto
        horizontal=True,
        help=(
            "**Estocástico**: proceso AR(1) diario que simula días nublados/despejados, "
            "reviertiendo hacia la claridad climática real del sitio (turbidez de Linke por mes). "
            "**Cielo despejado**: Ineichen sin nubes."
        ),
    )
    weather_source = _SOURCE_LABELS[weather_label]

    ar1_seed = st.number_input(
        "Semilla aleatoria", value=42, min_value=0, step=1,
        disabled=(weather_source != "stochastic"),
        help="Cambia la semilla para obtener un perfil estocástico diferente.",
    )

    if weather_source == "stochastic":
        with st.expander("Parámetros AR(1) — variabilidad nubosa", expanded=False):
            cc1, cc2 = st.columns(2)
            ar1_phi = cc1.slider(
                "Autocorrelación φ (persistencia día a día)", 0.50, 0.98, 0.92, 0.01,
                help="φ alto → días similares entre sí (más persistencia). φ bajo → alta variabilidad.",
            )
            ar1_sigma = cc2.slider(
                "Ruido σ (amplitud del cambio diario)", 0.03, 0.30, 0.10, 0.01,
                help="σ alto → mayor diferencia entre días consecutivos.",
            )
    else:
        ar1_phi, ar1_sigma = 0.92, 0.10

    with st.expander("Parámetros de pérdidas del sistema", expanded=False):
        lc1, lc2 = st.columns(2)
        soiling_pct = lc1.slider("Pérdida por suciedad / polvo (%)", 0.0, 10.0, 2.0, 0.5,
                                  help="Suciedad acumulada sobre los paneles.")
        wiring_pct = lc2.slider("Pérdida por cableado DC (%)", 0.0, 5.0, 1.5, 0.5,
                                 help="Resistencia del cableado entre paneles e inversor.")

# ── Run model ─────────────────────────────────────────────────────────────────
run_col, _ = st.columns([1, 3])
run_btn = run_col.button(
    "Ejecutar modelo Jensen", type="primary",
    use_container_width=True,
)

if run_btn or "irradiance_df" in st.session_state:
    if run_btn:
        with st.spinner(f"Calculando irradiancia ({resolution}) — fuente: {weather_label}…"):
            try:
                result = run_jensen_model(
                    lat=lat, lon=lon, tilt=tilt, azimuth=azimuth_pvlib,
                    start_date=str(start_dt), end_date=str(end_dt),
                    tz=tz, altitude=altitude, freq=freq,
                    weather_source=weather_source,
                    stochastic_seed=int(ar1_seed),
                    ar1_phi=ar1_phi,
                    ar1_sigma=ar1_sigma,
                    soiling_loss_frac=soiling_pct / 100.0,
                    wiring_loss_frac=wiring_pct / 100.0,
                    return_clearsky_baseline=True,
                )
                df_irr, df_cs = result
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
                losses = compute_losses_breakdown(
                    df_irr, df_cs,
                    system_kwp=system_kwp,
                    panel_efficiency=panel_eta,
                    panel_wp=panel_wp,
                    panel_area_m2=panel_area_m2,
                    n_panels=n_panels_cfg,
                    temp_coeff_pmax=panel.get("temp_coeff_pmax", -0.30),
                    noct=panel.get("noct", 43),
                    soiling_loss_frac=soiling_pct / 100.0,
                    wiring_loss_frac=wiring_pct / 100.0,
                )
                st.session_state["irradiance_df"] = df_irr
                st.session_state["irradiance_df_clearsky"] = df_cs
                st.session_state["losses_breakdown"] = losses
                st.session_state["solar_start"] = str(start_dt)
                st.session_state["solar_end"] = str(end_dt)
                st.session_state["solar_freq"] = freq
                st.session_state["weather_source_label"] = weather_label
            except Exception as e:
                st.error(f"Error en el modelo: {e}")
                st.stop()

    df = st.session_state.get("irradiance_df")
    df_clearsky = st.session_state.get("irradiance_df_clearsky", df)
    losses = st.session_state.get("losses_breakdown", {})
    if df is None:
        st.stop()

    _dt_h = df.attrs.get("dt_h", 1.0)
    _ws_label = st.session_state.get("weather_source_label", weather_label)

    # ── Shared KPIs ────────────────────────────────────────────────────────────
    total_kwh = energy_kwh(df["pv_kw"], df)
    cf = capacity_factor(df["pv_kw"], system_kwp, df) * 100
    psh = peak_sun_hours(df)
    max_poa = float(df["poa_global"].max())
    avg_daily_kwh = total_kwh / max(n_days, 1)
    n_periods_actual = len(df)

    st.divider()
    st.caption(f"Fuente activa: **{_ws_label}**")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    custom_metric(m1, "Generación total", f"{total_kwh:,.0f} kWh")
    custom_metric(m2, "Períodos calculados", f"{n_periods_actual:,}")
    custom_metric(m3, "Factor de capacidad", f"{cf:.1f} %")
    custom_metric(m4, "PSH totales", f"{psh:.1f} h")
    custom_metric(m5, "POA máxima", f"{max_poa:.0f} W/m²")
    custom_metric(m6, "Promedio diario", f"{avg_daily_kwh:.1f} kWh/día")

    # ── 4 TABS ─────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "Modelo", "Irradiancia", "Pérdidas del sistema", "Disponibilidad solar"
    ])

    # ── TAB 1: Modelo ─────────────────────────────────────────────────────────
    with tab1:
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

        st.markdown("### Irradiancia diaria — despejado vs real")
        available_dates = sorted(set(df.index.date))
        selected_date = st.select_slider("Selecciona día", options=available_dates,
                                          value=available_dates[0])
        fig_comp = irradiance_comparison_plot(df, df_clearsky, selected_date=str(selected_date))
        chart_with_export(fig_comp, key="sol_irr_comp", filename="irradiancia_comparacion")

        st.divider()
        st.markdown("### Generación FV agregada")
        agg_opt = st.radio("Agregación", ["Diaria", "Semanal", "Mensual"], horizontal=True)
        freq_map_agg = {"Diaria": "D", "Semanal": "W", "Mensual": "ME"}
        df_energy = df.copy()
        df_energy["pv_kw"] = df_energy["pv_kw"] * _dt_h
        fig_bar = generation_bar(df_energy, freq=freq_map_agg[agg_opt])
        chart_with_export(fig_bar, key="sol_gen_bar", filename="generacion_agregada")

        if n_days <= 62 and freq == "h":
            st.divider()
            st.markdown("### Mapa de calor — POA horaria (W/m²)")
            fig_heat = poa_heatmap(df)
            chart_with_export(fig_heat, key="sol_heat", filename="poa_heatmap")

        st.divider()
        col_dl1, col_dl2 = st.columns(2)
        col_dl1.download_button(
            "Descargar datos reales (CSV)", df.to_csv().encode(),
            file_name="irradiancia_real.csv", mime="text/csv",
        )
        col_dl2.download_button(
            "Descargar cielo despejado (CSV)", df_clearsky.to_csv().encode(),
            file_name="irradiancia_clearsky.csv", mime="text/csv",
        )

    # ── TAB 2: Irradiancia ────────────────────────────────────────────────────
    with tab2:
        st.markdown("### Comparación cielo despejado vs real — rango completo")
        fig_full = irradiance_comparison_plot(df, df_clearsky, selected_date=None)
        chart_with_export(fig_full, key="sol_full", filename="poa_patron_anual")

        st.divider()
        st.markdown("### Curva de excedencia y distribución de POA")
        st.caption("P50: el 50% del tiempo diurno la POA supera este valor. "
                   "P90: el 90% del tiempo diurno la POA supera este valor.")

        if losses:
            ec1, ec2, ec3, ec4 = st.columns(4)
            custom_metric(ec1, "POA real P50", f"{losses.get('poa_p50_wm2', 0):.0f} W/m²")
            custom_metric(ec2, "POA real P90", f"{losses.get('poa_p90_wm2', 0):.0f} W/m²")
            custom_metric(ec3, "POA despejado P50", f"{losses.get('poa_clearsky_p50_wm2', 0):.0f} W/m²")
            custom_metric(ec4, "POA despejado P90", f"{losses.get('poa_clearsky_p90_wm2', 0):.0f} W/m²")

        fig_exc = poa_exceedance_plot(df, df_clearsky)
        chart_with_export(fig_exc, key="sol_exc", filename="poa_excedencia")

        st.divider()
        st.markdown("### Patrón estacional — disponibilidad solar (hora × día)")
        fig_sun = sunrise_sunset_pattern_plot(df)
        chart_with_export(fig_sun, key="sol_sun", filename="amanecer_atardecer")

    # ── TAB 3: Pérdidas ───────────────────────────────────────────────────────
    with tab3:
        st.markdown("### Cadena de pérdidas del sistema")
        st.caption(
            "Cada barra muestra cuánta energía se pierde en cada etapa, "
            "como porcentaje del potencial de cielo despejado sin pérdidas."
        )

        if losses:
            lm1, lm2, lm3, lm4, lm5 = st.columns(5)
            custom_metric(lm1, "Nubosidad", f"{losses.get('loss_cloud_pct', 0):.1f} %",
                        delta=f"-{losses.get('loss_cloud_kwh', 0):,.0f} kWh", delta_color="inverse")
            custom_metric(lm2, "Temperatura", f"{losses.get('loss_temp_pct', 0):.1f} %",
                        delta=f"-{losses.get('loss_temp_kwh', 0):,.0f} kWh", delta_color="inverse")
            custom_metric(lm3, "Suciedad", f"{losses.get('loss_soiling_pct', 0):.1f} %",
                        delta=f"-{losses.get('loss_soiling_kwh', 0):,.0f} kWh", delta_color="inverse")
            custom_metric(lm4, "Cableado", f"{losses.get('loss_wiring_pct', 0):.1f} %",
                        delta=f"-{losses.get('loss_wiring_kwh', 0):,.0f} kWh", delta_color="inverse")
            custom_metric(lm5, "Inversor", f"{losses.get('loss_inverter_pct', 0):.1f} %",
                        delta=f"-{losses.get('loss_inverter_kwh', 0):,.0f} kWh", delta_color="inverse")

            fig_wf = losses_waterfall_chart(losses)
            chart_with_export(fig_wf, key="sol_losses_wf", filename="cadena_perdidas")

            st.divider()
            st.markdown("### Eficiencia por componente")
            fig_tbl = efficiency_breakdown_table(losses)
            chart_with_export(fig_tbl, key="sol_eff_tbl", filename="eficiencia_componentes")

            eff_col1, eff_col2 = st.columns(2)
            custom_metric(eff_col1, 
                "Eficiencia global del sistema",
                f"{losses.get('overall_system_efficiency_pct', 0):.1f} %",
                help="Generación AC / Potencial cielo despejado",
            )
            custom_metric(eff_col2, 
                "Factor de derating por temperatura",
                f"{losses.get('avg_temp_derate_factor', 1.0):.3f}",
                help="Media del factor (1 + α·(T_cell−25)) durante horas diurnas",
            )
        else:
            st.info("Ejecuta el modelo para ver el análisis de pérdidas.")

        with st.expander("Metodología de pérdidas"):
            st.markdown("La cadena de pérdidas sigue el orden:")
            st.latex(
                r"E_{CS} \xrightarrow{-\text{nubes}} E_{cloud} "
                r"\xrightarrow{-\text{temp}} E_{temp} "
                r"\xrightarrow{-\text{suciedad}} E_{soil} "
                r"\xrightarrow{-\text{cableado}} E_{wire} "
                r"\xrightarrow{-\text{inversor}} E_{AC}"
            )
            st.markdown(
                "- **Nubosidad** — reducción de GHI/DNI/DHI por nubosidad real o "
                "estocástica (kt × irradiancia)\n"
                "- **Temperatura** — derating NOCT: "
                r"$T_{cell} = T_{amb} + (NOCT-20)\cdot G_{POA}/800$; "
                r"pérdida $= \alpha_{P_{max}}\,(T_{cell}-25)$" "\n"
                "- **Suciedad** — pérdida fija configurable (default 2%)\n"
                "- **Cableado DC** — pérdida fija configurable (default 1.5%)\n"
                "- **Inversor** — eficiencia fija 96%"
            )

    # ── TAB 4: Disponibilidad solar ───────────────────────────────────────────
    with tab4:
        st.markdown("### Distribución mensual de POA diurno")

        df_monthly = df.copy()
        df_monthly = df_monthly[df_monthly["poa_global"] > 10]
        df_monthly["mes"] = df_monthly.index.month
        month_names_short = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                              "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

        import plotly.graph_objects as go
        fig_box = go.Figure()
        for m in sorted(df_monthly["mes"].unique()):
            vals = df_monthly[df_monthly["mes"] == m]["poa_global"].values
            fig_box.add_trace(go.Box(
                y=vals, name=month_names_short[m - 1],
                marker_color="#FFB300", showlegend=False,
                boxmean="sd",
            ))
        fig_box.update_layout(
            template="plotly_white",
            yaxis_title="POA (W/m²)",
            xaxis_title="Mes",
            height=400,
            margin=dict(t=20, b=40),
        )
        chart_with_export(fig_box, key="sol_box", filename="poa_distribucion_mensual")

        st.divider()
        st.markdown("### Horas solares útiles por mes (POA > 200 W/m²)")
        useful_hours = (
            df[df["poa_global"] > 200]
            .resample("ME")["poa_global"]
            .count() * _dt_h
        )
        fig_uh = go.Figure(go.Bar(
            x=[month_names_short[t.month - 1] for t in useful_hours.index],
            y=useful_hours.values,
            marker_color="#0039A6",
        ))
        fig_uh.update_layout(
            template="plotly_white",
            yaxis_title="Horas útiles (h)",
            height=320,
            margin=dict(t=10, b=40),
        )
        chart_with_export(fig_uh, key="sol_useful_hours", filename="horas_solares_utiles")

    # ── Methodology note ──────────────────────────────────────────────────────
    with st.expander("Notas metodológicas"):
        st.markdown(f"""
        - **Modelo de cielo claro:** Ineichen-Perez (`pvlib.location.get_clearsky`)
        - **Transposición:** Modelo isótropo difuso (Jensen) — `pvlib.irradiance.get_total_irradiance(model='isotropic')`
        - **Fuente meteorológica activa:** {_ws_label}
        - **Variabilidad estocástica:** Proceso AR(1) diario — kt[d] = μ + φ·(kt[d-1]−μ) + σ·ε
        - **Resolución temporal:** {resolution} (Δt = {_dt_h} h, N anual = {'35,040' if freq == '15min' else '8,760'})
        - **Temperatura de celda (NOCT):** $T_{{cell}} = T_{{amb}} + (NOCT-20) \\cdot G_{{POA}}/800$
        - **Cadena de pérdidas:** Nubosidad → Temperatura → Suciedad ({soiling_pct:.1f}%) → Cableado ({wiring_pct:.1f}%) → Inversor (4%)
        - **Albedo:** 0.25 | **η inversor:** 96%
        - **Referencia:** Jensen et al. (2023). Solar Energy, 266, 112092. [DOI:10.1016/j.solener.2023.112092](https://doi.org/10.1016/j.solener.2023.112092)
        """)
else:
    st.info("Configura los parámetros y haz clic en **Ejecutar modelo Jensen** para calcular la generación solar.")
