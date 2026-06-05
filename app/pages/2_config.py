import json
from pathlib import Path

import streamlit as st
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Configuración — GDMTH Solar", page_icon="⚙️", layout="wide")

# ── CSS MEJORADO (Banner y Tarjetas) ─────────────────────────────────────────
st.markdown("""
<style>
    .config-banner {
        background: linear-gradient(135deg, #0039A6 0%, #0055ff 100%);
        padding: 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .config-banner h1 {
        color: white !important;
        margin: 0;
        font-weight: 800;
        font-size: 2.5em;
    }
    .config-banner p {
        font-size: 1.1em;
        color: #E0E0E0;
        margin-top: 5px;
        margin-bottom: 0;
    }
</style>
""", unsafe_allow_html=True)

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
        "city": "Monterrey, NL",
        "lat": 25.6866,
        "lon": -100.3161,
        "altitude": 540.0,
        "tz": "America/Monterrey",
        "panel_id": PANELS[0]["id"],
        "n_panels": 100,
        "tilt": 20.0,
        "azimuth": 0.0,
        "region": "Noreste",
        "usd_mxn": 17.5,
        "panel_justification": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── ENCABEZADO ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="config-banner">
    <h1>⚙️ Configuración del Sistema</h1>
    <p>Ajusta los parámetros geográficos y técnicos para la simulación fotovoltaica.</p>
</div>
""", unsafe_allow_html=True)


# ── LOCATION (Tarjeta 1) ──────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("<h3 style='color:#0039A6; margin-top:0;'>📍 1. Ubicación y Tarifa</h3>", unsafe_allow_html=True)
    
    col_city, col_region = st.columns([2, 1])
    with col_city:
        city = st.selectbox("Ciudad predefinida", list(CITIES.keys()),
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

    st.markdown("##### Coordenadas exactas")
    col_lat, col_lon, col_alt = st.columns(3)
    lat = col_lat.number_input("Latitud (°N)", value=float(lat_default or st.session_state["lat"]),
                               min_value=14.5, max_value=32.7, step=0.001, format="%.4f")
    lon = col_lon.number_input("Longitud (°E)", value=float(lon_default or st.session_state["lon"]),
                               min_value=-118.4, max_value=-86.7, step=0.001, format="%.4f")
    alt = col_alt.number_input("Altitud (msnm)", value=st.session_state["altitude"],
                               min_value=0.0, max_value=5000.0, step=10.0)

    # Mapa interactivo dentro de un expander para no saturar la vista
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

            with st.spinner("Obteniendo altitud satelital..."):
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
    panel_idx = st.selectbox("Selecciona un panel del catálogo", range(len(PANELS)), format_func=lambda i: panel_labels[i],
                             index=current_panel_idx)
    panel = PANELS[panel_idx]

    # Sub-tarjeta de especificaciones del panel
    with st.container(border=True):
        col_p1, col_p2, col_p3 = st.columns(3)
        col_p1.metric("Potencia pico", f"{panel['wp']} Wp")
        col_p2.metric("Eficiencia", f"{panel['efficiency_pct']} %")
        col_p3.metric("Precio unitario", f"${panel['usd_per_w']:.2f} USD/W")

        col_p4, col_p5, col_p6 = st.columns(3)
        col_p4.metric("Voltaje (Voc)", f"{panel['voc']} V")
        col_p5.metric("Corriente (Isc)", f"{panel['isc']} A")
        col_p6.metric("Garantía", f"{panel['warranty_years']} años")

    # Physical dimensions
    st.markdown("##### Dimensiones Físicas y Arreglo")
    w = panel.get("width_m", panel["wp"] / (1000 * panel["efficiency_pct"] / 100) ** 0.5)
    l = panel.get("length_m", panel["wp"] / (1000 * panel["efficiency_pct"] / 100) ** 0.5)
    area_m2 = panel.get("area_m2", panel["wp"] / (1000.0 * panel["efficiency_pct"] / 100.0))
    
    col_dim1, col_dim2, col_dim3 = st.columns(3)
    col_dim1.metric("Ancho del panel", f"{w:.3f} m")
    col_dim2.metric("Largo del panel", f"{l:.3f} m")
    col_dim3.metric("Área por panel", f"{area_m2:.3f} m²")

    st.write("---")
    
    col_n, col_tilt, col_az = st.columns(3)
    n_panels = col_n.number_input("Número de paneles", min_value=1, max_value=5000,
                                  value=st.session_state["n_panels"], step=1)
    tilt = col_tilt.number_input("Ángulo de inclinación (°)", min_value=0.0, max_value=90.0,
                                 value=st.session_state["tilt"], step=0.5)
    azimuth = col_az.number_input("Azimut (0=Sur, −=Este, +=Oeste)",
                                  min_value=-180.0, max_value=180.0,
                                  value=st.session_state["azimuth"], step=1.0)
    st.caption("💡 **Tip de Azimut:** **0°** = Sur (Óptimo para México) | **−90°** = Este | **+90°** = Oeste | **±180°** = Norte")

    system_kwp = (n_panels * panel["wp"]) / 1000.0
    capex_usd = n_panels * panel["wp"] * panel["usd_per_w"]

    st.success(
        f"**📊 Resumen del Arreglo:** Tamaño del sistema: **{system_kwp:.2f} kWp**  |  "
        f"CAPEX estimado paneles: **${capex_usd:,.0f} USD**"
    )

    justification = st.text_area(
        "Justificación técnica de la selección",
        value=st.session_state.get("panel_justification") or (
            f"Se seleccionó el panel {panel['brand']} {panel['model']} por su alta eficiencia "
            f"de {panel['efficiency_pct']}%, certificación Tier {panel['tier']}, y garantía de "
            f"{panel['warranty_years']} años. La tecnología monocristalina PERC ofrece mejor "
            f"rendimiento en condiciones de irradiancia difusa, relevante para el sitio seleccionado."
        ),
        height=100,
    )

use_battery = False
battery = None
bat_kwh = 0.0
bat_idx = 0

st.write("") # Espaciador

# ── FINANZAS (Tarjeta 3) ──────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("<h3 style='color:#2E7D32; margin-top:0;'>💵 3. Parámetros Financieros</h3>", unsafe_allow_html=True)
    col_fx, _ = st.columns([1, 2])
    usd_mxn = col_fx.number_input("Tipo de cambio actual (USD/MXN)", min_value=10.0, max_value=30.0,
                                  value=st.session_state["usd_mxn"], step=0.1, format="%.2f")

# ── SAVE ──────────────────────────────────────────────────────────────────────
st.write("")
if st.button("💾 Guardar configuración del sistema", type="primary", use_container_width=True):
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
        "region": region,
        "usd_mxn": usd_mxn,
        "panel_justification": justification,
    })
    st.success("✅ ¡Configuración guardada exitosamente! Ya puedes avanzar al Análisis Solar o al Análisis de Demanda.")
    st.balloons()
    
