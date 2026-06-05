"""
GDMTH Solar Analysis Tool — Main entry point
Tecnológico de Monterrey
"""

import streamlit as st

st.set_page_config(
    page_title="GDMTH Solar Analyzer",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Global CSS (Solo estético, no rompe la navegación de tus compañeros) ─────
st.markdown("""
<style>
    /* Colores y tipografía */
    h1 { color: #0039A6 !important; font-weight: 800 !important; }
    h2, h3 { color: #F57C00 !important; }
    
    /* Cajas de texto resaltadas */
    .highlight-box {
        background-color: #f8f9fa;
        border-left: 6px solid #0039A6;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    
    /* Texto con degradado para subtítulos pro */
    .gradient-text {
        background: linear-gradient(90deg, #0039A6 0%, #FFB300 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900;
        font-size: 1.8em;
        margin-top: 10px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ── 1. Banner Principal (Imagen de alto impacto) ─────────────────────────────
# Usamos una imagen libre de derechos de Unsplash para darle un toque muy pro
st.image("https://images.unsplash.com/photo-1508514177221-188b1cf16e9d?ixlib=rb-4.0.3&auto=format&fit=crop&w=2000&q=80", use_container_width=True)

# ── 2. Encabezado Hero ───────────────────────────────────────────────────────
st.markdown("<h1 style='text-align: center; font-size: 3.5em; margin-top: 20px;'>☀️ Análisis Económico Solar GDMTH</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; font-size: 1.3em; color: gray; margin-bottom: 30px;'>Tecnológico de Monterrey — Herramienta de Viabilidad para Tarifa Industrial CFE</p>", unsafe_allow_html=True)

st.divider()

# ── 3. Contenido Principal en Columnas Asimétricas ───────────────────────────
col1, col2 = st.columns([1.5, 1]) # La primera columna es un poco más ancha

with col1:
    st.markdown("""
    <div class="highlight-box">
        <h3 style="color:#0039A6 !important; margin-top:0;">Bienvenido a la Herramienta</h3>
        <p style="font-size: 1.1em;">Esta aplicación evalúa la viabilidad económica de un sistema fotovoltaico (FV) para clientes industriales tarifados bajo la tarifa <b>GDMTH</b> (Gran Demanda en Media Tensión Horaria) de CFE.</p>
        <p style="font-size: 1.1em;">Utilizamos el <b>modelo de irradiancia isótropa de Jensen</b> para calcular la generación solar horaria, contrastándolo contra la estructura tarifaria vigente.</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Barras visuales para darle estilo de Dashboard
    st.markdown("#### ⚡ Capacidad del Motor de Análisis")
    st.progress(100, text="Precisión Isótropa (Modelo Jensen pvlib)")
    st.progress(100, text="Estructura Tarifaria (CFE GDMTH Actualizada)")

with col2:
    # Tarjeta tipo widget con colores institucionales
    st.markdown("""
    <div style="background: linear-gradient(135deg, #0039A6, #001f5c); padding: 30px; border-radius: 15px; text-align: center; color: white; box-shadow: 0 8px 16px rgba(0,0,0,0.2);">
        <h2 style="color: #FFB300 !important; margin-bottom: 5px;">Equipo 4</h2>
        <p style="font-size: 1.2em; opacity: 0.9;">Proyecto de Energía Solar</p>
        <hr style="border-color: rgba(255,255,255,0.2);">
        <h1 style="color: white !important; font-size: 3.5em; margin: 10px 0;">👈</h1>
        <p style="margin-top: 10px; font-size: 1.1em;"><b>Utiliza el menú lateral izquierdo</b> para navegar entre las secciones de Configuración, Demanda y Análisis Económico.</p>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ── 4. Sección de Detalles Técnicos ──────────────────────────────────────────
st.markdown("<div class='gradient-text'>Características del Modelo</div>", unsafe_allow_html=True)

col_a, col_b, col_c = st.columns(3)

with col_a:
    with st.container(border=True):
        st.markdown("### 🕒 Horarios Punta")
        st.markdown("""
        **Zonas Centro, Sur, Peninsular:**
        * **Verano:** L–V 20:00–22:00
        * **Invierno:** L–V 18:00–22:00
        * Sábados invernales: 19:00–21:00
        * Domingos/Festivos: Sin Punta
        """)

with col_b:
    with st.container(border=True):
        st.markdown("### 💰 Cargos GDMTH")
        st.markdown("""
        Desglose de factura mensual:
        1. ⚡ **Energía** (Suma de Punta/Intermedia/Base)
        2. 🏭 **Capacidad** (Máxima demanda en Punta)
        3. 🔌 **Distribución** (Máxima demanda general)
        """)

with col_c:
    with st.container(border=True):
        st.markdown("### 🌞 Ecuación Jensen")
        st.markdown("Cálculo de irradiancia POA:")
        st.latex(r"G_{POA} = G_b R_b + G_d \frac{1+\cos\beta}{2} + G \rho \frac{1-\cos\beta}{2}")
        st.markdown("<small style='color:gray;'>Ref: Jensen <i>et al.</i> (2022)</small>", unsafe_allow_html=True)

# ── Sidebar Original (Se mantiene debajo de la navegación automática) ────────
with st.sidebar:
    st.divider()
    st.markdown("### ⚙️ Resumen de Configuración")
    
    col_s1, col_s2 = st.columns(2)
    col_s1.metric("Ciudad", st.session_state.get('city', '—'))
    col_s2.metric("Sistema (kWp)", f"{st.session_state.get('system_kwp', 0):.1f}")
    
    col_s3, col_s4 = st.columns(2)
    col_s3.metric("Paneles", st.session_state.get('n_panels', 0))
    col_s4.metric("Región CFE", st.session_state.get('region', '—'))
