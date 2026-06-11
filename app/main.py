"""
Streger Solar — CFE tariff analysis tool, main entry point.
Tecnológico de Monterrey

Progressive-disclosure flow for the PRIMARY tariff GDMTO (flat rates):
  Sección 1 — Vista Rápida (always visible): location, tilt/azimuth, instant
              clear-sky irradiance + per-panel kWh/day estimate.
  Sección 2 — CFE consumption history, solar balance, Módulo Express / GDMTO.
  Sección 3 — Resilience sizing (backup against apagones).
  Sección 4 — Continuity financial evaluation.

The GDMTH (hourly) flow remains available behind the tariff toggle and lives
in the sidebar pages (Configuración → Análisis Solar → Demanda → Economía →
Baterías).
"""

import sys
import json
from pathlib import Path
import base64
import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from core.jensen import run_jensen_model, compute_pv_generation, energy_kwh, peak_sun_hours
from core.gdmto import GDMTOCalculator, MONTH_ABBR_ES
from core.resilience import propose_bess, kva_to_kw, continuity_cashflows, investment_irr
from core.plots import (irradiance_plot, monthly_demand_vs_solar_bar,
                        gdmto_savings_waterfall, typical_day_profile_plot,
                        monthly_savings_bar, continuity_cashflow_bar)
from core.exporting import chart_with_export
from core.state import keep_state
from utils.theming import inject_theme, custom_metric

st.set_page_config(
    page_title="Streger Solar — Análisis CFE",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)
keep_state()

inject_theme("00")
DATA = Path(__file__).parent / "data"


@st.cache_data(show_spinner=False)
def _load_panels() -> list[dict]:
    with open(DATA / "panels.json", encoding="utf-8") as f:
        return json.load(f)


PANELS = _load_panels()

# ── Mexican state capitals (lat, lon, altitude msnm). Coatepec is the default
#    site (Streger S.A.); "Personalizada" allows manual coordinates. ──────────
CITIES: dict[str, tuple[float | None, float | None, float]] = {
    "Coatepec, Ver.": (19.452, -96.962, 1250.0),
    "Aguascalientes, Ags.": (21.8853, -102.2916, 1888.0),
    "Campeche, Camp.": (19.8301, -90.5349, 10.0),
    "Chetumal, Q.R.": (18.5002, -88.2961, 10.0),
    "Chihuahua, Chih.": (28.6353, -106.0889, 1415.0),
    "Chilpancingo, Gro.": (17.5514, -99.5006, 1250.0),
    "Ciudad de México, CDMX": (19.4326, -99.1332, 2240.0),
    "Ciudad Victoria, Tamps.": (23.7369, -99.1411, 320.0),
    "Colima, Col.": (19.2452, -103.7241, 550.0),
    "Cuernavaca, Mor.": (18.9242, -99.2216, 1510.0),
    "Culiacán, Sin.": (24.8091, -107.3940, 54.0),
    "Durango, Dgo.": (24.0277, -104.6532, 1890.0),
    "Guadalajara, Jal.": (20.6597, -103.3496, 1566.0),
    "Guanajuato, Gto.": (21.0190, -101.2574, 2017.0),
    "Hermosillo, Son.": (29.0729, -110.9559, 210.0),
    "La Paz, B.C.S.": (24.1426, -110.3128, 27.0),
    "Mérida, Yuc.": (20.9674, -89.5926, 10.0),
    "Mexicali, B.C.": (32.6245, -115.4523, 8.0),
    "Monterrey, N.L.": (25.6866, -100.3161, 540.0),
    "Morelia, Mich.": (19.7060, -101.1950, 1920.0),
    "Oaxaca, Oax.": (17.0732, -96.7266, 1555.0),
    "Pachuca, Hgo.": (20.1011, -98.7591, 2400.0),
    "Puebla, Pue.": (19.0414, -98.2063, 2135.0),
    "Querétaro, Qro.": (20.5888, -100.3899, 1820.0),
    "Saltillo, Coah.": (25.4232, -100.9930, 1600.0),
    "San Luis Potosí, S.L.P.": (22.1565, -100.9855, 1860.0),
    "Tepic, Nay.": (21.5042, -104.8946, 915.0),
    "Tlaxcala, Tlax.": (19.3139, -98.2404, 2230.0),
    "Toluca, Méx.": (19.2826, -99.6557, 2660.0),
    "Tuxtla Gutiérrez, Chis.": (16.7516, -93.1161, 522.0),
    "Villahermosa, Tab.": (17.9892, -92.9475, 10.0),
    "Xalapa, Ver.": (19.5438, -96.9102, 1417.0),
    "Zacatecas, Zac.": (22.7709, -102.5832, 2440.0),
    "Personalizada": (None, None, 500.0),
}

_TZ_OVERRIDES = {
    "Mexicali, B.C.": "America/Tijuana",
    "La Paz, B.C.S.": "America/Mazatlan",
    "Culiacán, Sin.": "America/Mazatlan",
    "Tepic, Nay.": "America/Mazatlan",
    "Hermosillo, Son.": "America/Hermosillo",
    "Chihuahua, Chih.": "America/Chihuahua",
    "Monterrey, N.L.": "America/Monterrey",
    "Saltillo, Coah.": "America/Monterrey",
    "Ciudad Victoria, Tamps.": "America/Monterrey",
    "Chetumal, Q.R.": "America/Cancun",
}


def _tz_for(city: str) -> str:
    return _TZ_OVERRIDES.get(city, "America/Mexico_City")


# ── Session-state contract for the progressive GDMTO flow ─────────────────────
_DEFAULTS = {
    "tariff_mode": "GDMTO",          # "GDMTO" (default) | "GDMTH"
    "city": "Coatepec, Ver.",
    "lat": 19.452,
    "lon": -96.962,
    "altitude": 1250.0,
    "tz": "America/Mexico_City",
    "usd_mxn": 17.5,
    # Sección 2
    "cfe_history": None,             # DataFrame: mes, kwh, demanda_kw, costo_medio_mxn_kwh, fp_pct
    "costo_promedio_kwh": 2.67,
    # Sección 3
    "backup_hours": 0,
    "critical_load_kw": 0.0,
    "bess_proposal": None,           # dict from core.resilience sizing
    # Sección 4
    "outage_cost_annual": 0.0,
    "battery_quote_mxn": 0.0,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Global CSS ────────────────────────────────────────────────────────────────
# (Los colores de header los define ahora el tema en utils/theming → styles.css.)

_BANNER_PATH = Path(__file__).parent / "pages" / "banner.jpg"


@st.cache_data(show_spinner=False)
def _banner_b64() -> str:
    if not _BANNER_PATH.exists():
        return ""
    return base64.b64encode(_BANNER_PATH.read_bytes()).decode()


_banner = _banner_b64()
if _banner:
    st.markdown(
        f"<img src='data:image/jpeg;base64,{_banner}' "
        "style='width:100%;height:220px;object-fit:cover;border-radius:12px;"
        "margin-bottom:10px;box-shadow:0 4px 6px rgba(0,0,0,0.1)'/>",
        unsafe_allow_html=True,
    )

st.markdown(
    "<h1 style='margin-bottom:0'>☀️ Streger Solar — Análisis CFE</h1>"
    "<p style='color:gray;font-size:1.1em;margin-top:4px'>"
    "Viabilidad fotovoltaica y de respaldo bajo tarifas GDMTO / GDMTH · "
    "Tecnológico de Monterrey</p>",
    unsafe_allow_html=True,
)

# ── Sidebar: tariff mode + summary ────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚡ Modo tarifario")
    st.radio(
        "Tarifa CFE", ["GDMTO", "GDMTH"], key="tariff_mode", horizontal=True,
        help="GDMTO: Gran Demanda en Media Tensión **Ordinaria** (tarifas planas, sin horarios) — flujo en esta página. "
             "GDMTH: Gran Demanda en Media Tensión **Horaria** — flujo en las páginas del menú.",
    )
    st.divider()
    # ── Ruta recomendada según la tarifa elegida al inicio ─────────────────────
    st.markdown("### 🧭 Ruta recomendada")
    if st.session_state["tariff_mode"] == "GDMTH":
        st.markdown(
            "Tarifa **GDMTH** (horaria):\n"
            "1. ⚙️ Configuración\n"
            "2. 🌞 Análisis Solar\n"
            "3. 📊 Demanda **+ baterías**\n"
            "4. 🔋 Baterías (peak shaving)\n"
            "5. 📈 Continuidad / ROI"
        )
    else:
        st.markdown(
            "Tarifa **GDMTO** (plana):\n"
            "1. 🧾 Secciones 2–4 (esta página)\n"
            "2. ⚙️ Configuración (panel y ubicación)\n"
            "3. 🔋 Baterías → respaldo\n"
            "4. 📈 Continuidad / ROI"
        )
    st.divider()
    st.markdown("### ⚙️ Resumen")
    cs1, cs2 = st.columns(2)
    custom_metric(cs1, "Ciudad", st.session_state.get("city", "—").split(",")[0])
    custom_metric(cs2, "Modo", st.session_state.get("tariff_mode", "GDMTO"))
    if st.session_state["tariff_mode"] == "GDMTH":
        # Bajo GDMTH el flujo es horario y vive en las páginas: el resumen apunta
        # a esos datos (no se muestran controles/resúmenes residenciales/GDMTO).
        cs3, cs4 = st.columns(2)
        _kwp = st.session_state.get("system_kwp", 0.0)
        custom_metric(cs3, "Sistema (kWp)", f"{_kwp:.1f}")
        custom_metric(cs4, "Región CFE", st.session_state.get("region", "—"))
    else:
        cs3, cs4 = st.columns(2)
        _kwp = st.session_state.get("s2_system_kwp") or st.session_state.get("system_kwp", 0.0)
        custom_metric(cs3, "Sistema (kWp)", f"{_kwp:.1f}")
        custom_metric(cs4, "Respaldo (h)", st.session_state.get("backup_hours", 0))

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — VISTA RÁPIDA (desplegable / colapsable)
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🔆 Sección 1 — Vista Rápida · ubicación, orientación y generación por panel", expanded=False):
    st.caption("Elige la ubicación y orientación del arreglo: irradiancia de un día representativo "
               "(equinoccio, cielo despejado, modelo Jensen/pvlib) y estimación instantánea por panel.")

    col_city, col_lat, col_lon = st.columns([2, 1, 1])
    city_names = list(CITIES.keys())
    _city_idx = city_names.index(st.session_state["city"]) if st.session_state["city"] in city_names \
        else city_names.index("Personalizada")
    city = col_city.selectbox("Ubicación (capitales de estado de México)", city_names, index=_city_idx)

    if city != "Personalizada":
        _lat_d, _lon_d, _alt_d = CITIES[city]
    else:
        _lat_d = st.session_state["lat"]
        _lon_d = st.session_state["lon"]
        _alt_d = st.session_state["altitude"]

    lat = col_lat.number_input("Latitud (°N)", min_value=14.5, max_value=32.7,
                               value=float(_lat_d), step=0.001, format="%.4f")
    lon = col_lon.number_input("Longitud (°E)", min_value=-118.4, max_value=-86.7,
                               value=float(_lon_d), step=0.001, format="%.4f")
    st.caption("💡 Edita las coordenadas si tu sitio no es la capital. "
               "El mapa interactivo completo está en ⚙️ **Configuración**.")

    opt_tilt = int(round(abs(lat)))
    col_tilt, col_az = st.columns(2)
    # key= keeps the user's override across page navigation (without a key the
    # slider resets to the optimal default every time the page is revisited).
    tilt = col_tilt.slider(
        "Inclinación del panel (°)", min_value=0, max_value=60, value=opt_tilt,
        key="s1_tilt",
        help=f"Por defecto la inclinación óptima anual ≈ latitud del sitio ({opt_tilt}°). Ajústala si tu techo lo requiere.",
    )
    azimuth = col_az.slider(
        "Azimut del panel (0° = Sur | −90° = Este | +90° = Oeste)",
        min_value=-180, max_value=180, value=0, step=5, key="s1_azimuth",
        help="Convención del proyecto: 0° = Sur (óptimo en México).",
    )
    azimuth_pvlib = (180.0 + float(azimuth)) % 360.0

    tz = _tz_for(city)

    # Persist S1 so the GDMTH pages (Configuración, Análisis Solar…) share the site
    st.session_state.update({
        "city": city,
        "lat": float(lat),
        "lon": float(lon),
        "altitude": float(_alt_d),
        "tz": tz,
        "tilt": float(tilt),
        "azimuth": float(azimuth),
    })

    _TYPICAL_DAY = "2024-03-21"   # equinox ≈ annual-average solar geometry


    @st.cache_data(show_spinner=False)
    def _quick_day_irradiance(lat: float, lon: float, tilt: float, az_pvlib: float,
                              tz: str, altitude: float) -> pd.DataFrame:
        return run_jensen_model(
            lat=lat, lon=lon, tilt=tilt, azimuth=az_pvlib,
            start_date=_TYPICAL_DAY, end_date=_TYPICAL_DAY,
            tz=tz, altitude=altitude, freq="h", weather_source="clearsky",
        )


    df_day = _quick_day_irradiance(float(lat), float(lon), float(tilt), azimuth_pvlib,
                                   tz, float(_alt_d))

    panel_ref = PANELS[0]
    pv_day_kw = compute_pv_generation(
        df_day,
        system_kwp=panel_ref["wp"] / 1000.0,
        panel_efficiency=panel_ref["efficiency_pct"],
        panel_wp=panel_ref["wp"],
        panel_area_m2=panel_ref.get("area_m2"),
        n_panels=1,
        temp_coeff_pmax=panel_ref.get("temp_coeff_pmax", -0.30),
        noct=panel_ref.get("noct", 43),
    )
    kwh_day_panel = energy_kwh(pv_day_kw, df_day)

    q1, q2, q3, q4 = st.columns(4)
    custom_metric(q1, "Generación por panel", f"{kwh_day_panel:.2f} kWh/día",
              help=f"Panel de referencia: {panel_ref['brand']} {panel_ref['model']} ({panel_ref['wp']} W)")
    custom_metric(q2, "Equivalente mensual", f"{kwh_day_panel * 30:.0f} kWh/mes",
              help="Por panel (≈ 30 días como el día representativo).")
    custom_metric(q3, "Horas solares pico", f"{peak_sun_hours(df_day):.1f} h")
    custom_metric(q4, "POA máxima", f"{float(df_day['poa_global'].max()):.0f} W/m²")

    chart_with_export(irradiance_plot(df_day), key="s1_irradiance", filename="irradiancia_dia")
    st.caption(f"Día representativo: {_TYPICAL_DAY} (equinoccio) · Cielo despejado Ineichen · "
               f"Transposición isótropa (Jensen) · Inclinación {tilt}° · Azimut {azimuth:+d}° (0=Sur)")

# ══════════════════════════════════════════════════════════════════════════════
# Modo GDMTH → el flujo detallado vive en las páginas laterales
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
if st.session_state["tariff_mode"] == "GDMTH":
    st.info(
        "🕒 **Modo GDMTH activo.** El análisis horario completo está en el menú lateral: "
        "**⚙️ Configuración → 🌞 Análisis Solar → 📊 Demanda → 💰 Economía → 🔋 Baterías**. "
        "Las Secciones 2–4 de esta página aplican al modo **GDMTO**."
    )
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — CONSUMO CFE Y BALANCE (GDMTO)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("## 🧾 Sección 2 — Tu consumo CFE")
s2_on = st.toggle(
    "Ingresar mi consumo CFE",
    key="s2_enabled",
    help="Captura tu historial de recibos GDMTO para comparar contra la generación solar.",
)
# Reference 24-h industrial shape (manufactura archetype, mirrors 4_demand) used
# only to draw hourly profiles; billing always uses the user-entered demanda_kw.
_DAY_SHAPE = np.array([0.42, 0.40, 0.39, 0.38, 0.39, 0.43,
                       0.65, 0.82, 0.95, 0.98, 1.00, 0.99,
                       0.97, 0.96, 0.97, 0.96, 0.95, 0.96,
                       0.98, 1.00, 0.99, 0.95, 0.80, 0.55])
_DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # 2024 (solar year)
_SOLAR_YEAR = ("2024-01-01", "2024-12-31")


@st.cache_data(show_spinner="Calculando generación solar del año completo…")
def _year_pv_monthly(lat: float, lon: float, tilt: float, az_pvlib: float, tz: str,
                     altitude: float, panel_id: str, n_panels: int):
    """Hourly year with AR(1) cloud variability (fixed seed → reproducible)
    → (monthly kWh ×12, mean-day kW profile 12×24, annual kWh)."""
    panel = next(p for p in PANELS if p["id"] == panel_id)
    df = run_jensen_model(
        lat=lat, lon=lon, tilt=tilt, azimuth=az_pvlib,
        start_date=_SOLAR_YEAR[0], end_date=_SOLAR_YEAR[1],
        tz=tz, altitude=altitude, freq="h",
        weather_source="stochastic", stochastic_seed=42,
    )
    pv_kw = compute_pv_generation(
        df,
        system_kwp=n_panels * panel["wp"] / 1000.0,
        panel_efficiency=panel["efficiency_pct"],
        panel_wp=panel["wp"],
        panel_area_m2=panel.get("area_m2"),
        n_panels=n_panels,
        temp_coeff_pmax=panel.get("temp_coeff_pmax", -0.30),
        noct=panel.get("noct", 43),
    )
    monthly = pv_kw.groupby(pv_kw.index.month).sum()              # dt = 1 h → kWh
    monthly_kwh = [float(monthly.get(m, 0.0)) for m in range(1, 13)]
    prof = pv_kw.groupby([pv_kw.index.month, pv_kw.index.hour]).mean().unstack(fill_value=0.0)
    prof = prof.reindex(index=range(1, 13), columns=range(24), fill_value=0.0)
    return monthly_kwh, prof.values, float(pv_kw.sum())


if s2_on:
    # ── A) Historial CFE ──────────────────────────────────────────────────────
    input_mode = st.radio("Modo de captura", ["Promedio mensual", "Tabla de 12 meses"],
                          horizontal=True, key="s2_input_mode")

    if input_mode == "Promedio mensual":
        ca1, ca2, ca3, ca4 = st.columns(4)
        kwh_avg = ca1.number_input("Consumo mensual (kWh)", min_value=0.0,
                                   value=9520.0, step=100.0, format="%.0f", key="s2_kwh_avg")
        kw_avg = ca2.number_input("Demanda máxima (kW)", min_value=0.0,
                                  value=80.0, step=1.0, format="%.1f", key="s2_kw_avg")
        fp_avg = ca3.number_input("Factor de potencia (%)", min_value=50.0, max_value=100.0,
                                  value=89.89, step=0.01, format="%.2f", key="s2_fp_avg")
        costo_avg = ca4.number_input("Costo medio del recibo ($/kWh)", min_value=0.0,
                                     value=2.67, step=0.01, format="%.2f", key="s2_costo_avg")
        cfe_history = pd.DataFrame({
            "mes": MONTH_ABBR_ES,
            "kwh": [kwh_avg] * 12,
            "demanda_kw": [kw_avg] * 12,
            "costo_medio_mxn_kwh": [costo_avg] * 12,
            "fp_pct": [fp_avg] * 12,
        })
    else:
        st.caption("Edita los valores de cada recibo. La plantilla trae los valores del recibo "
                   "Streger de Mayo 2026 (9,520 kWh · 80 kW · $2.67/kWh · FP 89.89%).")
        _template = pd.DataFrame({
            "mes": MONTH_ABBR_ES,
            "kwh": [9520.0] * 12,
            "demanda_kw": [80.0] * 12,
            "costo_medio_mxn_kwh": [2.67] * 12,
            "fp_pct": [89.89] * 12,
        })
        cfe_history = st.data_editor(
            _template,
            hide_index=True,
            num_rows="fixed",
            use_container_width=True,
            key="s2_cfe_editor",
            column_config={
                "mes": st.column_config.TextColumn("Mes", disabled=True),
                "kwh": st.column_config.NumberColumn("Consumo (kWh)", min_value=0.0, format="%.0f"),
                "demanda_kw": st.column_config.NumberColumn("Demanda (kW)", min_value=0.0, format="%.1f"),
                "costo_medio_mxn_kwh": st.column_config.NumberColumn("Costo medio ($/kWh)",
                                                                     min_value=0.0, format="%.2f"),
                "fp_pct": st.column_config.NumberColumn("FP (%)", min_value=0.0,
                                                        max_value=100.0, format="%.2f"),
            },
        )
        cfe_history = cfe_history.fillna(0.0)

    st.session_state["cfe_history"] = cfe_history

    # ── B) Sistema fotovoltaico propuesto ─────────────────────────────────────
    st.markdown("#### 🔆 Sistema fotovoltaico propuesto")
    cb1, cb2 = st.columns([2, 1])
    _panel_labels = [f"{p['brand']} {p['model']} — {p['wp']} Wp | {p['efficiency_pct']}% | "
                     f"${p['usd_per_w']}/W" for p in PANELS]
    s2_panel_idx = cb1.selectbox("Panel fotovoltaico", range(len(PANELS)),
                                 format_func=lambda i: _panel_labels[i], key="s2_panel_idx")
    s2_panel = PANELS[s2_panel_idx]
    s2_n_panels = cb2.number_input("Número de paneles", min_value=0, max_value=5000,
                                   value=0, step=1, key="s2_n_panels_input")
    s2_kwp = s2_n_panels * s2_panel["wp"] / 1000.0
    usd_mxn = st.session_state.get("usd_mxn", 17.5)
    s2_fv_capex_mxn = s2_n_panels * s2_panel["wp"] * s2_panel["usd_per_w"] * usd_mxn
    st.caption(f"**Sistema:** {s2_kwp:.2f} kWp · **CAPEX paneles:** $ {s2_fv_capex_mxn:,.2f} MXN "
               f"(TDC {usd_mxn:.2f})")

    st.session_state.update({
        "s2_panel": s2_panel,
        "s2_system_kwp": s2_kwp,
        "s2_fv_capex_mxn": s2_fv_capex_mxn,
    })

    if s2_n_panels > 0:
        gen_monthly, gen_profile, gen_annual = _year_pv_monthly(
            float(lat), float(lon), float(tilt), azimuth_pvlib, tz, float(_alt_d),
            s2_panel["id"], int(s2_n_panels),
        )
    else:
        gen_monthly, gen_profile, gen_annual = [0.0] * 12, np.zeros((12, 24)), 0.0
        st.info("💡 Ingresa un número de paneles mayor a 0 para ver la generación solar.")

    # ── C) Balance mensual demanda vs generación ──────────────────────────────
    demand_monthly = [float(v) for v in cfe_history["kwh"].tolist()]
    total_dem = sum(demand_monthly)
    total_gen = sum(gen_monthly)
    coverage = (sum(min(d, g) for d, g in zip(demand_monthly, gen_monthly)) / total_dem * 100.0
                if total_dem > 0 else 0.0)

    st.markdown("#### ⚖️ Balance mensual: demanda vs generación")
    st.caption("Generación *real*: modelo horario Jensen con nubosidad estocástica AR(1) "
               "(semilla fija) y derating por temperatura NOCT.")
    chart_with_export(monthly_demand_vs_solar_bar(MONTH_ABBR_ES, demand_monthly, gen_monthly),
                      key="s2_balance", filename="balance_demanda_generacion")
    bal1, bal2, bal3 = st.columns(3)
    custom_metric(bal1, "Demanda anual", f"{total_dem:,.0f} kWh")
    custom_metric(bal2, "Generación FV anual", f"{total_gen:,.0f} kWh")
    custom_metric(bal3, "Balance anual neto", f"{total_dem - total_gen:,.0f} kWh",
                delta=f"FV cubre {coverage:.1f}% del consumo",
                help="Positivo: consumo no cubierto por FV. Negativo: excedente anual.")

    with st.expander("📈 Ver perfil horario típico (demanda vs solar)"):
        sel_mes = st.selectbox("Mes", MONTH_ABBR_ES, key="s2_mes_perfil")
        m_idx = MONTH_ABBR_ES.index(sel_mes)
        kwh_m = demand_monthly[m_idx]
        shape_day_kwh = float(_DAY_SHAPE.sum())
        scale = kwh_m / (shape_day_kwh * _DAYS_IN_MONTH[m_idx]) if shape_day_kwh > 0 else 0.0
        demand_24 = (_DAY_SHAPE * scale).tolist()
        chart_with_export(typical_day_profile_plot(demand_24, gen_profile[m_idx].tolist(),
                                                   month_label=sel_mes),
                          key="s2_perfil_dia", filename="perfil_dia_tipico")
        st.caption("Perfil sintético (arquetipo industrial) escalado para que el mes sume "
                   f"{kwh_m:,.0f} kWh. La **demanda facturable** es la capturada en tu recibo "
                   f"({float(cfe_history['demanda_kw'].iloc[m_idx]):,.1f} kW), no el pico del perfil.")

    # Persist the balance intermediates so the economic evaluation (Sección 4,
    # tras la Sección de baterías) puede consumirlos sin recalcular.
    st.session_state["s2_gen_monthly"] = gen_monthly
    st.session_state["s2_demand_monthly"] = demand_monthly
    st.caption("💡 La **evaluación económica** (ahorro FV, TIR/VPN) aparece en la **Sección 4**, "
               "después del dimensionamiento de baterías.")
else:
    st.caption("Activa esta sección para capturar tus recibos y ver el balance demanda vs generación.")

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — RESILIENCIA ANTE APAGONES
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## 🔌 Sección 3 — Resiliencia ante apagones")
s3_on = st.toggle(
    "Mi sitio sufre apagones y necesito respaldo",
    key="s3_enabled",
    help="En GDMTO la batería se justifica por continuidad operativa (respaldo), no por arbitraje horario.",
)
if s3_on:
    backup_hours = st.slider(
        "Horas de respaldo requeridas", min_value=1, max_value=24,
        value=max(int(st.session_state.get("backup_hours", 0)) or 4, 1),
        key="s3_hours",
        help="Duración del apagón que el banco de baterías debe cubrir alimentando la carga crítica.",
    )
    st.session_state["backup_hours"] = int(backup_hours)

    cl1, cl2, cl3 = st.columns([2, 1, 1])
    load_val = cl1.number_input(
        "Carga crítica a respaldar", min_value=0.0, value=20.0, step=1.0, format="%.1f",
        key="s3_load",
        help="Equipos que DEBEN seguir operando durante el apagón (refrigeración, "
             "servidores, bombas, iluminación de seguridad…).",
    )
    load_unit = cl2.selectbox("Unidad", ["kW", "kVA"], key="s3_load_unit")
    if load_unit == "kVA":
        fp_load = cl3.number_input("FP de la carga (%)", min_value=50.0, max_value=100.0,
                                   value=89.89, step=0.01, format="%.2f", key="s3_fp_load")
        p_crit_kw = kva_to_kw(load_val, fp_load)
        st.caption(f"kW = kVA × FP/100 → **{p_crit_kw:.1f} kW**")
    else:
        p_crit_kw = load_val
    st.session_state["critical_load_kw"] = float(p_crit_kw)

    if p_crit_kw <= 0:
        st.warning("Ingresa una carga crítica mayor a 0 para dimensionar el banco de baterías.")
        st.session_state["bess_proposal"] = None
    else:
        usd_mxn_s3 = st.session_state.get("usd_mxn", 17.5)
        prop = propose_bess(float(p_crit_kw), float(backup_hours), usd_mxn=usd_mxn_s3)
        best = prop["best"]
        st.session_state["bess_proposal"] = best

        st.markdown("#### 🏆 Propuesta automática (menor CAPEX que cumple energía y potencia)")
        with st.container(border=True):
            st.markdown(f"**{best['brand']} {best['model']}** · {best['chemistry']} · "
                        f"requiere **{best['e_req_kwh']:,.1f} kWh** para {backup_hours} h "
                        f"de respaldo a {p_crit_kw:,.1f} kW")
            pc1, pc2, pc3, pc4 = st.columns(4)
            custom_metric(pc1, "Unidades", f"{best['units']}")
            custom_metric(pc2, "Energía útil", f"{best['total_usable_kwh']:,.1f} kWh")
            custom_metric(pc3, "Potencia", f"{best['total_power_kw']:,.1f} kW")
            custom_metric(pc4, "CAPEX", f"$ {best['capex_mxn']:,.2f} MXN",
                       help=f"$ {best['capex_usd']:,.0f} USD × TDC {usd_mxn_s3:.2f}")
            pc5, pc6, pc7 = st.columns(3)
            custom_metric(pc5, "Ciclos", f"{best['cycles']:,}",
                       help=f"Banda típica LiFePO4: {best['cycle_band']} ciclos.")
            custom_metric(pc6, "Vida (ciclado diario)", f"{best['life_years_daily_cycling']:.1f} años",
                       help=best["life_note"])
            custom_metric(pc7, "DoD / Eficiencia RT",
                       f"{best['dod_pct']:.0f}% / {best['roundtrip_efficiency_pct']:.0f}%")
            st.caption("ℹ️ " + best["life_note"])

        with st.expander("🔍 Ver alternativas del catálogo"):
            alt_rows = [{
                "Modelo": f"{o['brand']} {o['model']}",
                "Química": o["chemistry"],
                "Unidades": o["units"],
                "Energía útil (kWh)": f"{o['total_usable_kwh']:,.1f}",
                "Potencia (kW)": f"{o['total_power_kw']:,.1f}",
                "Ciclos": f"{o['cycles']:,}",
                "Vida est. (años)": f"{o['life_years_daily_cycling']:.1f}",
                "CAPEX (MXN)": f"$ {o['capex_mxn']:,.2f}",
            } for o in prop["options"]]
            st.dataframe(pd.DataFrame(alt_rows), use_container_width=True, hide_index=True)
            st.caption("Todas las opciones cumplen ambas restricciones: energía "
                       "(E_req = P·h / (DoD × η_inv)) y potencia (P ≥ carga crítica).")
else:
    st.session_state["backup_hours"] = 0
    st.session_state["bess_proposal"] = None
    st.caption("Activa esta sección si los cortes de CFE afectan tu operación.")

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — EVALUACIÓN ECONÓMICA (tras el dimensionamiento de baterías)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## 📈 Sección 4 — Evaluación económica")

# ── A) Rentabilidad del sistema FV (consume los datos de la Sección 2) ─────────
# Se evalúa aquí, después de baterías, para que toda la economía quede junta y
# después del análisis de respaldo. Produce `ahorro_fv_anual`, que la continuidad
# (parte B) y la página de Economía heredan.
st.markdown("### 💰 Rentabilidad del sistema fotovoltaico")
if s2_on:
    eval_mode = st.radio("Tipo de evaluación", ["Módulo Express", "Desglose formal GDMTO"],
                         horizontal=True, key="s2_eval_mode",
                         help="Express: estimación inmediata con tu costo medio por kWh. "
                              "Desglose formal: factura GDMTO completa (energía, demanda, 2% BT, FP, IVA).")

    ahorro_fv_anual = 0.0
    if eval_mode == "Módulo Express":
        costo_monthly = [float(c) for c in cfe_history["costo_medio_mxn_kwh"].tolist()]
        costo_medio = float(np.mean(costo_monthly)) if costo_monthly else 0.0
        st.session_state["costo_promedio_kwh"] = costo_medio
        st.caption(f"Usando el **costo medio del recibo** capturado en la Sección 2 "
                   f"(${costo_medio:.2f}/kWh prom.).")
        pago_actual = sum(k * c for k, c in zip(demand_monthly, costo_monthly))
        pago_con_fv = sum(max(k - g, 0.0) * c
                          for k, c, g in zip(demand_monthly, costo_monthly, gen_monthly))
        ahorro_fv_anual = pago_actual - pago_con_fv
        ex1, ex2 = st.columns(2)
        custom_metric(ex1, "Pago anual actual", f"$ {pago_actual:,.2f}")
        custom_metric(ex2, "Pago anual con FV", f"$ {pago_con_fv:,.2f}",
                   delta=f"-$ {ahorro_fv_anual:,.2f}", delta_color="inverse")
        st.caption("Estimación rápida: Σ kWh × costo medio — no requiere el motor tarifario.")
    else:
        dr_pct = st.slider("Reducción de demanda facturable por FV (%)", 0, 30, 0,
                           key="s2_dr_pct",
                           help="En GDMTO el FV normalmente NO reduce la demanda máxima "
                                "(suele ocurrir fuera de horas solares). Ajusta sólo si tienes "
                                "evidencia de coincidencia pico-sol.")
        calc_gdmto = GDMTOCalculator()
        proj = calc_gdmto.annual_projection(
            cfe_history.to_dict("records"), gen_monthly, demand_reduction_pct=float(dr_pct),
        )
        annual = proj["annual"]
        ahorro_fv_anual = annual["savings_mxn"]

        fa1, fa2, fa3, fa4 = st.columns(4)
        custom_metric(fa1, "Factura anual sin FV", f"$ {annual['orig_total_mxn']:,.2f}")
        custom_metric(fa2, "Factura anual con FV", f"$ {annual['total_mxn']:,.2f}")
        custom_metric(fa3, "Ahorro anual", f"$ {annual['savings_mxn']:,.2f}",
                   delta=f"{annual['savings_mxn'] / annual['orig_total_mxn'] * 100:.1f}%"
                   if annual["orig_total_mxn"] > 0 else None)
        custom_metric(fa4, "Tarifa", calc_gdmto.name, help="Componentes calibrados al recibo real.")

        chart_with_export(monthly_savings_bar(proj["monthly"]),
                          key="s2_monthly_savings", filename="ahorro_mensual_gdmto")

        sel_mes_wf = st.selectbox("Mes para el desglose en cascada", MONTH_ABBR_ES,
                                  index=4, key="s2_mes_waterfall")
        bill_sel = proj["monthly"][MONTH_ABBR_ES.index(sel_mes_wf)]
        chart_with_export(gdmto_savings_waterfall(bill_sel),
                          key="s2_waterfall", filename="cascada_ahorro_gdmto")

        with st.expander("📄 Ver componentes de la factura por mes"):
            rows = []
            for b in proj["monthly"]:
                rows.append({
                    "Mes": MONTH_ABBR_ES[b["month"] - 1],
                    "kWh neto": f"{b['net_kwh']:,.0f}",
                    "Fijo": f"$ {b['fixed_mxn']:,.2f}",
                    "Energía": f"$ {b['energy_total_mxn']:,.2f}",
                    "Demanda": f"$ {b['demand_total_mxn']:,.2f}",
                    "2% BT": f"$ {b['bt_charge_mxn']:,.2f}",
                    "FP": f"$ {b['fp_charge_mxn']:,.2f}",
                    "IVA": f"$ {b['iva_mxn']:,.2f}",
                    "Total": f"$ {b['total_mxn']:,.2f}",
                    "Total sin FV": f"$ {b['orig_total_mxn']:,.2f}",
                    "Ahorro": f"$ {b['savings_mxn']:,.2f}",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("##### 📊 Rentabilidad de la inversión en paneles")
    if s2_fv_capex_mxn > 0 and ahorro_fv_anual > 0:
        rp1, rp2, rp3 = st.columns(3)
        fv_life = int(rp1.number_input("Vida del proyecto (años)", min_value=5, max_value=30,
                                       value=25, step=1, key="s2_fv_life"))
        fv_infl = rp2.number_input("Inflación tarifaria (%/año)", min_value=0.0, max_value=15.0,
                                   value=5.0, step=0.5, key="s2_fv_infl")
        fv_disc = rp3.number_input("Tasa de descuento (%)", min_value=1.0, max_value=25.0,
                                   value=10.0, step=0.5, key="s2_fv_disc")

        cf_fv = continuity_cashflows(s2_fv_capex_mxn, ahorro_fv_anual,
                                     fv_life, fv_infl, fv_disc)
        tir = investment_irr(s2_fv_capex_mxn, ahorro_fv_anual, fv_life, fv_infl)
        if tir != tir:                       # nan
            tir_str = "—"
        elif tir == float("inf"):
            tir_str = "> 100 %"
        else:
            tir_str = f"{tir * 100:.1f} %"
        pb = cf_fv["payback_years"]

        rr1, rr2, rr3 = st.columns(3)
        custom_metric(rr1, "TIR (Tasa Interna de Retorno)", tir_str,
                   help="Cuánto crece cada peso invertido en los paneles por año; "
                        "rentable cuando supera tu tasa de descuento.")
        custom_metric(rr2, "VPN (Valor Presente Neto)", f"$ {cf_fv['npv_mxn']:,.2f}",
                   delta="Rentable" if cf_fv["npv_mxn"] > 0 else "No rentable",
                   delta_color="normal" if cf_fv["npv_mxn"] > 0 else "inverse",
                   help="Valor de hoy de los ahorros futuros menos la inversión inicial.")
        custom_metric(rr3, "Periodo de recuperación",
                   f"{pb:.1f} años" if pb < 100 else "∞",
                   help="CAPEX de paneles ÷ ahorro anual (recuperación simple).")
        st.caption(f"Sobre una inversión FV de **$ {s2_fv_capex_mxn:,.2f} MXN** y un ahorro anual "
                   f"de **$ {ahorro_fv_anual:,.2f}** creciente con la inflación tarifaria "
                   "(beneficio·(1+inflación)^(año−1)/(1+descuento)^año).")
    else:
        st.info("Ingresa un número de paneles **> 0** (Sección 2) y un ahorro FV positivo "
                "para ver la TIR, el VPN y el periodo de recuperación.")

    st.session_state["ahorro_fv_anual"] = float(ahorro_fv_anual)
else:
    st.caption("Activa la **Sección 2** (Tu consumo CFE) para evaluar el ahorro FV, la TIR y el VPN.")

# ── B) Continuidad ante apagones (batería ± FV) ───────────────────────────────
st.divider()
st.markdown("### 🛡️ Continuidad de negocio ante apagones")
s4_on = st.checkbox("Análisis avanzado de continuidad", key="s4_enabled")
if s4_on:
    bess = st.session_state.get("bess_proposal")
    if bess is None:
        st.warning("⚠️ Primero dimensiona el banco de respaldo en la **Sección 3** "
                   "para evaluar el costo-beneficio de la continuidad.")
    else:
        fi1, fi2 = st.columns(2)
        outage_cost = fi1.number_input(
            "Costo anual histórico por apagones (MXN/año)", min_value=0.0,
            value=float(st.session_state.get("outage_cost_annual", 0.0)),
            step=1000.0, format="%.2f", key="s4_outage",
            help="Gasto histórico en reparaciones, mermas, producto perdido y paros "
                 "causados por cortes de CFE. Con respaldo, este costo se evita.",
        )
        quote = fi2.number_input(
            "Cotización comercial de baterías (MXN, opcional)", min_value=0.0,
            value=float(st.session_state.get("battery_quote_mxn", 0.0)),
            step=1000.0, format="%.2f", key="s4_quote",
            help="Si tienes una cotización real, SUSTITUYE al CAPEX de catálogo "
                 "en toda esta sección. Deja 0 para usar el catálogo.",
        )
        st.session_state["outage_cost_annual"] = float(outage_cost)
        st.session_state["battery_quote_mxn"] = float(quote)

        fp1, fp2, fp3 = st.columns(3)
        project_life = fp1.number_input("Vida del proyecto (años)", min_value=5, max_value=25,
                                        value=10, step=1, key="s4_life")
        inflation_pct = fp2.number_input("Inflación tarifaria/costos (%/año)", min_value=0.0,
                                         max_value=15.0, value=5.0, step=0.5, key="s4_infl")
        discount_pct = fp3.number_input("Tasa de descuento / WACC (%)", min_value=1.0,
                                        max_value=25.0, value=10.0, step=0.5, key="s4_disc")

        capex_batt = quote if quote > 0 else float(bess["capex_mxn"])
        capex_src = "cotización comercial" if quote > 0 else "catálogo"
        ahorro_fv = float(st.session_state.get("ahorro_fv_anual", 0.0))
        fv_capex = float(st.session_state.get("s2_fv_capex_mxn", 0.0))
        if ahorro_fv <= 0:
            st.caption("ℹ️ Sin ahorro tarifario FV registrado — completa la **Sección 2** "
                       "(paneles > 0 y evaluación económica) para incluirlo en el escenario *Con FV*.")

        # Scenario A: battery + PV → tariff saving + avoided outage losses
        cf_con = continuity_cashflows(capex_batt + fv_capex, ahorro_fv + outage_cost,
                                      int(project_life), inflation_pct, discount_pct)
        # Scenario B: battery only → avoided outage losses
        cf_sin = continuity_cashflows(capex_batt, outage_cost,
                                      int(project_life), inflation_pct, discount_pct)

        st.markdown(f"**CAPEX baterías ({capex_src}):** $ {capex_batt:,.2f} MXN · "
                    f"**CAPEX FV:** $ {fv_capex:,.2f} MXN · "
                    f"**Beneficio anual:** ahorro FV $ {ahorro_fv:,.2f} + "
                    f"apagones evitados $ {outage_cost:,.2f}")

        rc1, rc2, rc3, rc4 = st.columns(4)
        custom_metric(rc1, "Payback — Con FV",
                   f"{cf_con['payback_years']:.1f} años" if cf_con["payback_years"] < 100 else "∞",
                   help="CAPEX total (batería + FV) / beneficio anual (ahorro FV + apagones evitados).")
        custom_metric(rc2, "VPN — Con FV", f"$ {cf_con['npv_mxn']:,.2f}",
                   delta="Rentable" if cf_con["npv_mxn"] > 0 else "No rentable",
                   delta_color="normal" if cf_con["npv_mxn"] > 0 else "inverse")
        custom_metric(rc3, "Payback — Sin FV",
                   f"{cf_sin['payback_years']:.1f} años" if cf_sin["payback_years"] < 100 else "∞",
                   help="CAPEX batería / costo anual de apagones evitado.")
        custom_metric(rc4, "VPN — Sin FV", f"$ {cf_sin['npv_mxn']:,.2f}",
                   delta="Rentable" if cf_sin["npv_mxn"] > 0 else "No rentable",
                   delta_color="normal" if cf_sin["npv_mxn"] > 0 else "inverse")

        chart_with_export(
            continuity_cashflow_bar(cf_con["months"], cf_con["monthly_pv_flows"],
                                    cf_sin["monthly_pv_flows"],
                                    cf_con["cumulative_pv"], cf_sin["cumulative_pv"]),
            key="s4_continuity_cashflow", filename="flujo_continuidad",
        )
        st.caption("Flujos mensuales **a valor presente** (mes 0 = CAPEX inicial negativo). "
                   "VPN con el mismo patrón de descuento que la optimización de baterías: "
                   "beneficio·(1+inflación)^(año−1)/(1+descuento)^año.")
else:
    st.caption("Desbloquea el ROI de la continuidad: costo histórico de apagones vs inversión en respaldo.")
