import json
from pathlib import Path

import sys

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Configuración — GDMTH Solar", page_icon="⚙️", layout="wide")

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.state import keep_state
from utils.theming import inject_theme, custom_metric

keep_state()

inject_theme("02")
# ── Load catalog data ─────────────────────────────────────────────────────────
DATA = Path(__file__).parent.parent / "data"

with open(DATA / "panels.json") as f:
    PANELS = json.load(f)

# with open(DATA / "batteries.json") as f:   # BATTERY — disabled for now
#     BATTERIES = json.load(f)

with open(DATA / "tariff_gdmth.json") as f:
    TARIFF = json.load(f)

# ── Mexican city presets ──────────────────────────────────────────────────────
CITIES = {
    "Personalizada": (None, None),
    "Monterrey, NL": (25.6866, -100.3161),
    "Ciudad de México, CDMX": (19.4326, -99.1332),
    "Guadalajara, JAL": (20.6597, -103.3496),
    "Tijuana, BC": (32.5149, -117.0382),
    "Ciudad Juárez, CHIH": (31.7381, -106.4870),
    "León, GTO": (21.1221, -101.6824),
    "Puebla, PUE": (19.0414, -98.2063),
    "Querétaro, QRO": (20.5888, -100.3899),
    "Mérida, YUC": (20.9674, -89.5926),
    "Hermosillo, SON": (29.0729, -110.9559),
    "Chihuahua, CHIH": (28.6353, -106.0889),
    "Saltillo, COAH": (25.4232, -100.9930),
    "Mexicali, BC": (32.6245, -115.4523),
    "San Luis Potosí, SLP": (22.1565, -100.9855),
    "Torreón, COAH": (25.5428, -103.4068),
    "Xalapa, VER": (19.3200, -96.9336),   # reference city from lecture
}

TZ_MAP = {
    "Monterrey, NL": "America/Monterrey",
    "Ciudad de México, CDMX": "America/Mexico_City",
    "Guadalajara, JAL": "America/Mexico_City",
    "Tijuana, BC": "America/Tijuana",
    "Ciudad Juárez, CHIH": "America/Chihuahua",
    "León, GTO": "America/Mexico_City",
    "Puebla, PUE": "America/Mexico_City",
    "Querétaro, QRO": "America/Mexico_City",
    "Mérida, YUC": "America/Merida",
    "Hermosillo, SON": "America/Hermosillo",
    "Chihuahua, CHIH": "America/Chihuahua",
    "Saltillo, COAH": "America/Monterrey",
    "Mexicali, BC": "America/Tijuana",
    "San Luis Potosí, SLP": "America/Mexico_City",
    "Torreón, COAH": "America/Monterrey",
    "Xalapa, VER": "America/Mexico_City",
    "Personalizada": "America/Mexico_City",
}


def _init():
    defaults = {
        "tariff_mode": "GDMTO",
        "city": "Monterrey, NL",
        "lat": 25.6866,
        "lon": -100.3161,
        "altitude": 540.0,
        "tz": "America/Monterrey",
        "panel_id": PANELS[0]["id"],
        "n_panels": 30,
        "tilt": 20.0,
        "azimuth": 0.0,
        # "battery_id": BATTERIES[0]["id"],   # BATTERY — disabled for now
        # "battery_kwh": BATTERIES[0]["kwh"],
        # "use_battery": False,
        "region": "Noreste",
        "usd_mxn": 17.5,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()

st.markdown("<h1 style='color:#0039A6;font-weight:700'>Configuración del Sistema</h1>",
            unsafe_allow_html=True)

# ── TARIFF MODE ───────────────────────────────────────────────────────────────
st.markdown("## ⚡ Modo tarifario")
st.radio(
    "Tarifa CFE a analizar", ["GDMTO", "GDMTH"], key="tariff_mode", horizontal=True,
    help="**GDMTO** — Gran Demanda en Media Tensión Ordinaria: tarifas planas sin horarios; "
         "el flujo guiado vive en la página **principal** (Secciones 1–4). "
         "**GDMTH** — Gran Demanda en Media Tensión Horaria: usa las páginas "
         "Análisis Solar → Demanda → Economía → Baterías.",
)
if st.session_state["tariff_mode"] == "GDMTO":
    st.caption("Modo GDMTO activo: el análisis económico y de respaldo se realiza en la página "
               "**principal** (Vista Rápida → Secciones 2–4). Esta página sigue siendo útil para "
               "elegir panel, ubicación fina y tipo de cambio.")

# ── RESIDENTIAL TARIFFS 1A–1F (informative tool) ──────────────────────────────
# Bajo GDMTH el cliente es de media tensión horaria: la herramienta residencial
# (y su deslizable) no aplica, así que se oculta para una interfaz más limpia.
if st.session_state["tariff_mode"] != "GDMTH":
    with st.expander("🏠 Tarifas residenciales 1A–1F — bloques y umbral DAC", expanded=False):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.residential import classify, BLOCK_LABELS, TARIFFS as RES_TARIFFS, LIMITS as RES_LIMITS
        from core.plots import residential_blocks_bar
        from core.exporting import chart_with_export

        st.caption("Acumulador de bloques **por bimestre**: el consumo llena Básico → Intermedio → "
                   "Verano 1 → Verano 2 y el resto se factura como **Excedente**. Si superas el "
                   "límite DAC pasas a tarifa Doméstica de Alto Consumo.")
        cr1, cr2 = st.columns([1, 2])
        res_tarifa = cr1.selectbox("Tarifa", RES_TARIFFS, index=2)
        res_kwh = cr2.number_input("Consumo del bimestre (kWh)", min_value=0.0,
                                   value=900.0, step=10.0, format="%.0f")

        res = classify(res_kwh, res_tarifa)
        chart_with_export(residential_blocks_bar(res["blocks"], res["dac_kwh_bimestre"]),
                          key="res_blocks", filename="bloques_residenciales")

        _lims = RES_LIMITS[res_tarifa]
        _rows = []
        for _b in ["basico", "intermedio", "verano1", "verano2", "excedente"]:
            _cap = _lims.get(_b)
            _rows.append({
                "Bloque": BLOCK_LABELS[_b],
                "Límite (kWh/bim)": "resto" if _b == "excedente" else ("—" if _cap is None else f"{_cap:,}"),
                "Consumo asignado (kWh)": f"{res['blocks'][_b]:,.0f}",
            })
        st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

        if res["dac"]:
            st.error(f"⚠️ **DAC**: {res_kwh:,.0f} kWh supera el límite de "
                     f"{res['dac_kwh_bimestre']:,} kWh/bimestre para {res_tarifa} — "
                     "el servicio se reclasifica como Doméstica de Alto Consumo.")
        else:
            st.success(f"✅ Dentro del límite DAC ({res['dac_kwh_bimestre']:,} kWh/bimestre "
                       f"para {res_tarifa}).")

# ── LOCATION ──────────────────────────────────────────────────────────────────
st.markdown("## 📍 Ubicación")
col_city, col_region = st.columns([2, 1])
with col_city:
    city = st.selectbox("Ciudad", list(CITIES.keys()),
                        index=list(CITIES.keys()).index(st.session_state["city"])
                        if st.session_state["city"] in CITIES else 0)
with col_region:
    region = st.selectbox("Región CFE (tarifa)", TARIFF["regions"],
                          index=TARIFF["regions"].index(st.session_state["region"])
                          if st.session_state["region"] in TARIFF["regions"] else 0)

if city != "Personalizada":
    lat_default, lon_default = CITIES[city]
    tz_default = TZ_MAP.get(city, "America/Mexico_City")
else:
    lat_default = st.session_state["lat"]
    lon_default = st.session_state["lon"]
    tz_default = st.session_state["tz"]

col_lat, col_lon, col_alt = st.columns(3)
lat = col_lat.number_input("Latitud (°N)", value=float(lat_default or st.session_state["lat"]),
                            min_value=14.5, max_value=32.7, step=0.001, format="%.4f")
lon = col_lon.number_input("Longitud (°E)", value=float(lon_default or st.session_state["lon"]),
                            min_value=-118.4, max_value=-86.7, step=0.001, format="%.4f")
alt = col_alt.number_input("Altitud (msnm)", value=st.session_state["altitude"],
                            min_value=0.0, max_value=5000.0, step=10.0)

# ── Mapa interactivo ────────────────────────────────────────── (MAX)

import requests
import folium
from streamlit_folium import st_folium

def _get_altitude(lat: float, lon: float) -> float:
    try:
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return float(r.json()["elevation"][0])
    except Exception:
        return st.session_state.get("altitude", 540.0)

def _infer_cfe_region(lat: float, lon: float) -> str:
    # Fuera de México → default seguro
    if not (14.5 <= lat <= 32.7 and -118.4 <= lon <= -86.7):
        return TARIFF["regions"][0]   # ← antes retornaba "Norte"/"Sureste"/"Centro" hardcoded

    # Baja California (península)
    if lon < -109.5:
        if lat >= 28.0:
            return "Baja California"
        else:
            return "Baja California Sur"

    # Noroeste: Sonora, Sinaloa, Nayarit (norte)
    if lon <= -105.0 and lat >= 21.0:
        return "Noroeste"

    # Norte: Chihuahua, Durango, Coahuila (interior seco)
    if lat >= 26.0 and lon > -109.5:
        return "Norte"

    # Noreste: Nuevo León, Tamaulipas, parte de Coahuila
    if lat >= 23.0 and lon >= -102.0:
        return "Noreste"

    # Peninsular: Yucatán, Campeche, Q. Roo
    if lon >= -92.0 and lat <= 21.5:
        return "Peninsular"

    # Sureste: Chiapas, Tabasco, Veracruz sur
    if lat <= 18.5 and lon >= -96.0:
        return "Sureste"

    # Sur: Oaxaca, Guerrero, Michoacán costa
    if lat <= 20.0:
        return "Sur"

    return "Centro"

with st.expander("🗺️ Seleccionar ubicación en mapa (opcional)", expanded=False):
    st.caption("Haz **click** en el mapa para autorellenar latitud, longitud, altitud y región CFE.")

    m = folium.Map(
        location=[lat, lon],
        zoom_start=11,
        tiles="CartoDB positron",
    )
    folium.Marker(
        location=[lat, lon],
        tooltip="Ubicación actual",
        icon=folium.Icon(color="blue", icon="sun", prefix="fa"),
    ).add_to(m)

    map_data = st_folium(m, height=380, width="100%", returned_objects=["last_clicked"])

    if map_data and map_data.get("last_clicked"):
        clicked_lat = map_data["last_clicked"]["lat"]
        clicked_lon = map_data["last_clicked"]["lng"]

        with st.spinner("Obteniendo altitud..."):
            clicked_alt = _get_altitude(clicked_lat, clicked_lon)

        clicked_region = _infer_cfe_region(clicked_lat, clicked_lon)
        if clicked_region not in TARIFF["regions"]:
            clicked_region = TARIFF["regions"][0]

        safe_lat = max(14.5, min(32.7, clicked_lat))
        safe_lon = max(-118.4, min(-86.7, clicked_lon))

        st.success(
            f"📌 **{clicked_lat:.4f}° N**, **{clicked_lon:.4f}° E** — "
            f"Altitud: **{clicked_alt:.0f} msnm** — "
            f"Región CFE: **{clicked_region}**"
        )

        st.session_state["lat"]      = safe_lat
        st.session_state["lon"]      = safe_lon
        st.session_state["altitude"] = clicked_alt
        st.session_state["city"]     = "Personalizada"
        st.session_state["region"]   = clicked_region
        st.rerun()
    
# ── PANEL SELECTION ───────────────────────────────────────────────────────────
st.divider()
st.markdown("## 🔆 Panel Fotovoltaico")

panel_ids = [p["id"] for p in PANELS]
panel_labels = [f"{p['brand']} {p['model']} — {p['wp']}Wp | {p['efficiency_pct']}% | ${p['usd_per_w']}/W | Tier {p['tier']}"
                for p in PANELS]

current_panel_idx = panel_ids.index(st.session_state["panel_id"]) if st.session_state["panel_id"] in panel_ids else 0
panel_idx = st.selectbox("Selecciona panel", range(len(PANELS)), format_func=lambda i: panel_labels[i],
                          index=current_panel_idx)
panel = PANELS[panel_idx]

col_p1, col_p2, col_p3 = st.columns(3)
custom_metric(col_p1, "Potencia pico", f"{panel['wp']} Wp")
custom_metric(col_p2, "Eficiencia", f"{panel['efficiency_pct']} %")
custom_metric(col_p3, "Precio", f"${panel['usd_per_w']:.2f} USD/W")

col_p4, col_p5, col_p6 = st.columns(3)
custom_metric(col_p4, "Voc", f"{panel['voc']} V")
custom_metric(col_p5, "Isc", f"{panel['isc']} A")
custom_metric(col_p6, "Garantía", f"{panel['warranty_years']} años")

# Physical dimensions — required for Pow = POA × AreaPanel × η
w = panel.get("width_m", panel["wp"] / (1000 * panel["efficiency_pct"] / 100) ** 0.5)
l = panel.get("length_m", panel["wp"] / (1000 * panel["efficiency_pct"] / 100) ** 0.5)
area_m2 = panel.get("area_m2", panel["wp"] / (1000.0 * panel["efficiency_pct"] / 100.0))
col_dim1, col_dim2, col_dim3 = st.columns(3)
custom_metric(col_dim1, "Ancho del panel", f"{w:.3f} m")
custom_metric(col_dim2, "Largo del panel", f"{l:.3f} m")
custom_metric(col_dim3, "Área del panel (ancho × largo)", f"{area_m2:.3f} m²")

col_n, col_tilt, col_az = st.columns(3)
n_panels = col_n.number_input("Número de paneles", min_value=1, max_value=5000,
                               value=st.session_state["n_panels"], step=1)
tilt = col_tilt.number_input("Ángulo de inclinación (°)", min_value=0.0, max_value=90.0,
                               value=st.session_state["tilt"], step=0.5)
azimuth = col_az.number_input("Azimut del panel (0=Sur, −=Este, +=Oeste)",
                               min_value=-180.0, max_value=180.0,
                               value=st.session_state["azimuth"], step=1.0)
st.caption("Azimut: **0°** = Sur (óptimo México) | **−90°** = Este | **+90°** = Oeste | **±180°** = Norte")

system_kwp = (n_panels * panel["wp"]) / 1000.0
capex_usd = n_panels * panel["wp"] * panel["usd_per_w"]

col_info, col_help = st.columns([5, 1])
col_info.info(
    f"**Tamaño del sistema:** {system_kwp:.2f} kWp  |  "
    f"**CAPEX estimado paneles:** ${capex_usd:,.0f} USD"
)
with col_help.popover("ℹ️ ¿Qué es el CAPEX?", use_container_width=True):
    st.markdown(
        "**CAPEX** (*Capital Expenditure*) es la **inversión inicial de capital** "
        "necesaria para comprar e instalar el sistema fotovoltaico.\n\n"
        "El **CAPEX estimado de paneles** que se muestra arriba considera únicamente "
        "el costo de los módulos solares:\n\n"
        "$$\\text{CAPEX}_{paneles} = N_{paneles} \\times P_{pico}\\,[\\text{W}] "
        "\\times \\text{precio}\\,[\\text{USD/W}]$$\n\n"
        f"- **Paneles:** {n_panels:,} × {panel['wp']} Wp × ${panel['usd_per_w']:.2f}/W "
        f"= **${capex_usd:,.0f} USD**\n"
        "- No incluye estructura, inversores, cableado ni mano de obra "
        "(esos se suman como *factor de instalación* en la página de Economía).\n"
        "- Tampoco incluye baterías ni OPEX (gastos de operación y mantenimiento)."
    )

# ── BATTERY SELECTION — disabled for now, uncomment to re-enable ──────────────
# st.divider()
# st.markdown("## 🔋 Sistema de Baterías (opcional)")
#
# use_battery = st.toggle("Incluir batería de almacenamiento", value=st.session_state.get("use_battery", False))
#
# if use_battery:
#     bat_ids = [b["id"] for b in BATTERIES]
#     bat_labels = [f"{b['brand']} {b['model']} — {b['kwh']} kWh | {b['cycles']} ciclos | ${b['usd_per_kwh']}/kWh"
#                   for b in BATTERIES]
#     cur_bat_idx = bat_ids.index(st.session_state["battery_id"]) if st.session_state.get("battery_id") in bat_ids else 0
#     bat_idx = st.selectbox("Selecciona batería", range(len(BATTERIES)),
#                             format_func=lambda i: bat_labels[i], index=cur_bat_idx)
#     battery = BATTERIES[bat_idx]
#     bat_kwh = st.slider("Capacidad instalada (kWh)", min_value=battery["kwh"],
#                          max_value=battery["kwh"] * 10, value=st.session_state.get("battery_kwh", battery["kwh"]),
#                          step=battery["kwh"])
#     col_b1, col_b2, col_b3 = st.columns(3)
#     custom_metric(col_b1, "Capacidad útil", f"{battery['usable_kwh']} kWh")
#     custom_metric(col_b2, "Química", battery["chemistry"])
#     custom_metric(col_b3, "Eficiencia RT", f"{battery['roundtrip_efficiency_pct']} %")
#     bat_capex_usd = (bat_kwh / battery["kwh"]) * battery["kwh"] * battery["usd_per_kwh"]
#     st.info(f"**CAPEX estimado baterías:** ${bat_capex_usd:,.0f} USD  |  "
#             f"**Ciclos de vida:** {battery['cycles']:,}")
# else:
#     battery = None
#     bat_kwh = 0.0
#     bat_idx = 0

use_battery = False
battery = None
bat_kwh = 0.0
bat_idx = 0

# ── EXCHANGE RATE ─────────────────────────────────────────────────────────────
st.divider()
col_fx, _ = st.columns([1, 2])
usd_mxn = col_fx.number_input("Tipo de cambio USD/MXN", min_value=10.0, max_value=30.0,
                               value=st.session_state["usd_mxn"], step=0.1, format="%.2f")

# ── SAVE ──────────────────────────────────────────────────────────────────────
st.divider()
if st.button("Guardar configuración", type="primary", use_container_width=True):
    st.session_state.update({
        "city": city,
        "lat": lat,
        "lon": lon,
        "altitude": alt,
        "tz": TZ_MAP.get(city, "America/Mexico_City"),
        "panel_id": panel["id"],
        "panel": panel,
        "n_panels": int(n_panels),
        "tilt": tilt,
        "azimuth": azimuth,
        "system_kwp": system_kwp,
        "panel_capex_usd": capex_usd,
        # "use_battery": use_battery,       # BATTERY — disabled for now
        # "battery_id": ...,
        # "battery": battery,
        # "battery_kwh": bat_kwh,
        "region": region,
        "usd_mxn": usd_mxn,
    })
    st.success("Configuración guardada. Puedes avanzar a la página de Análisis Solar.")
    st.balloons()