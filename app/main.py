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

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from core.jensen import run_jensen_model, compute_pv_generation, energy_kwh, peak_sun_hours
from core.plots import irradiance_plot

st.set_page_config(
    page_title="Streger Solar — Análisis CFE",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
st.markdown("""
<style>
    h1 { color: #0039A6 !important; font-weight: 800 !important; }
    h2, h3 { color: #F57C00 !important; }
</style>
""", unsafe_allow_html=True)

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
    st.markdown("### ⚙️ Resumen")
    cs1, cs2 = st.columns(2)
    cs1.metric("Ciudad", st.session_state.get("city", "—").split(",")[0])
    cs2.metric("Modo", st.session_state.get("tariff_mode", "GDMTO"))
    cs3, cs4 = st.columns(2)
    cs3.metric("Sistema (kWp)", f"{st.session_state.get('system_kwp', 0.0):.1f}")
    cs4.metric("Respaldo (h)", st.session_state.get("backup_hours", 0))

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — VISTA RÁPIDA (siempre visible)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("## 🔆 Sección 1 — Vista Rápida")
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
tilt = col_tilt.slider(
    "Inclinación del panel (°)", min_value=0, max_value=60, value=opt_tilt,
    help=f"Por defecto la inclinación óptima anual ≈ latitud del sitio ({opt_tilt}°). Ajústala si tu techo lo requiere.",
)
azimuth = col_az.slider(
    "Azimut del panel (0° = Sur | −90° = Este | +90° = Oeste)",
    min_value=-180, max_value=180, value=0, step=5,
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
q1.metric("Generación por panel", f"{kwh_day_panel:.2f} kWh/día",
          help=f"Panel de referencia: {panel_ref['brand']} {panel_ref['model']} ({panel_ref['wp']} W)")
q2.metric("Equivalente mensual", f"{kwh_day_panel * 30:.0f} kWh/mes",
          help="Por panel (≈ 30 días como el día representativo).")
q3.metric("Horas solares pico", f"{peak_sun_hours(df_day):.1f} h")
q4.metric("POA máxima", f"{float(df_day['poa_global'].max()):.0f} W/m²")

st.plotly_chart(irradiance_plot(df_day), use_container_width=True)
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
if s2_on:
    st.info("🚧 Captura de consumo en construcción — se habilita en la siguiente etapa del flujo.")
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
        help="Duración del apagón que el banco de baterías debe cubrir alimentando la carga crítica.",
    )
    st.session_state["backup_hours"] = int(backup_hours)
    st.info("🚧 Dimensionamiento del banco de respaldo en construcción — siguiente etapa del flujo.")
else:
    st.session_state["backup_hours"] = 0
    st.caption("Activa esta sección si los cortes de CFE afectan tu operación.")

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — EVALUACIÓN FINANCIERA DE CONTINUIDAD
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("## 📈 Sección 4 — Evaluación financiera de continuidad")
s4_on = st.checkbox("Análisis avanzado de continuidad", key="s4_enabled")
if s4_on:
    if st.session_state.get("bess_proposal") is None:
        st.warning("⚠️ Primero dimensiona el banco de respaldo en la **Sección 3** "
                   "para evaluar el costo-beneficio de la continuidad.")
    else:
        st.info("🚧 Evaluación financiera en construcción — siguiente etapa del flujo.")
else:
    st.caption("Desbloquea el ROI de la continuidad: costo histórico de apagones vs inversión en respaldo.")
