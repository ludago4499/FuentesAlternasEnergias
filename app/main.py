"""
GDMTH Solar Analysis Tool — Main entry point
Tecnológico de Monterrey

Run: streamlit run app/main.py
"""

import streamlit as st

st.set_page_config(
    page_title="GDMTH Solar Analyzer",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Herramienta de análisis económico solar para tarifa GDMTH — Tec de Monterrey",
    },
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Tec de Monterrey brand colors */
    :root {
        --tec-blue: #0039A6;
        --solar-yellow: #FFB300;
        --solar-orange: #F57C00;
    }
    /* Sidebar nav header */
    [data-testid="stSidebarNav"] { padding-top: 1rem; }
    /* Primary button overrides */
    div.stButton > button[kind="primary"] {
        background-color: #0039A6;
        border-color: #0039A6;
        color: white;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #002580;
        border-color: #002580;
    }
    /* Metric delta positive */
    [data-testid="stMetricDelta"] { font-size: 0.85em; }
    /* Page headings */
    h1 { color: #0039A6 !important; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='text-align:center; padding: 10px 0;'>
        <div style='background:#0039A6; border-radius:10px; padding:16px; margin-bottom:8px;'>
            <span style='font-size:2.2em;'>☀️</span><br>
            <span style='color:white; font-weight:700; font-size:1.1em;'>GDMTH Solar</span><br>
            <span style='color:#FFB300; font-size:0.8em;'>Tec de Monterrey</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Config summary
    if "system_kwp" in st.session_state:
        st.markdown("#### Configuración actual")
        st.markdown(f"""
        | Parámetro | Valor |
        |-----------|-------|
        | Ciudad | {st.session_state.get('city', '—')} |
        | Sistema | {st.session_state.get('system_kwp', 0):.1f} kWp |
        | Paneles | {st.session_state.get('n_panels', 0)} |
        | Región CFE | {st.session_state.get('region', '—')} |
        | USD/MXN | {st.session_state.get('usd_mxn', 17.5):.2f} |
        """)

    st.divider()
    st.markdown("""
    <small style='color:gray;'>
    Modelo: Jensen isótropo (pvlib)<br>
    DOI: <a href='https://doi.org/10.1016/j.softx.2022.101070' target='_blank'>10.1016/j.softx.2022.101070</a>
    </small>
    """, unsafe_allow_html=True)

# ── Home / Welcome screen ──────────────────────────────────────────────────────
st.markdown("<h1 style='color:#0039A6;font-weight:700'>Herramienta de Análisis Económico Solar GDMTH</h1>",
            unsafe_allow_html=True)

st.markdown("""
**Bienvenido.** Esta herramienta evalúa la viabilidad económica de un sistema fotovoltaico (FV)
para clientes industriales tarifados bajo la tarifa **GDMTH** (Gran Demanda en Media Tensión Horaria) de CFE.

Utiliza el **modelo de irradiancia isótropa de Jensen** implementado en [pvlib](https://pvlib-python.readthedocs.io/)
para calcular la generación solar horaria, y la estructura tarifaria GDMTH vigente para cuantificar los ahorros.
""")

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("""
    #### Esquema de la página
    1. **Equipo** — La información del equipo 4.
    2. **Configuración** — Panel, batería, ubicación
    3. **Análisis Solar** — Modelo Jensen + pvlib
    4. **Demanda** — Curva de carga real
    5. **Economía** — Ahorros GDMTH + reporte PDF
    """)

with col2:
    st.markdown("""
    #### Tarifa GDMTH
    La tarifa incluye tres cargos principales:
    - **Energía** (Punta / Intermedia / Base)
    - **Capacidad** (máx. demanda media Punta)
    - **Distribución** (máx. demanda integrada)

    **Horario Punta** (Regiones Central, Noreste, Noroeste, Norte, Peninsular, Sur):
    - **Verano** (1er dom. abril → sáb. previo al último dom. octubre): L–V 20:00–22:00
    - **Invierno** (último dom. octubre → sáb. previo al 1er dom. abril): L–V 18:00–22:00; Sáb 19:00–21:00
    - Domingo y festivo: sin Punta
    """)   

with col3:
    st.markdown("""
    #### Modelo Jensen (pvlib)
    El modelo isótropo calcula la irradiancia en el
    plano del panel (POA) mediante:

    $$G_{POA} = G_b R_b + G_d \\frac{1+\\cos\\beta}{2} + G \\rho \\frac{1-\\cos\\beta}{2}$$

    Referencia: Jensen *et al.* (2022), SoftwareX.
    DOI: [10.1016/j.softx.2022.101070](https://doi.org/10.1016/j.softx.2022.101070)
    """)

st.divider()
st.info("Usa la barra de navegación izquierda para avanzar por las secciones.")
