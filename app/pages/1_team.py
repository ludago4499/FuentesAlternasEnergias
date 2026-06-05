import streamlit as st

st.set_page_config(page_title="Equipo — GDMTH Solar", page_icon="👥", layout="wide")

# ── CSS MEJORADO (Tarjetas, Avatares y Efectos Hover) ────────────────────────
st.markdown("""
<style>
    /* Banner del equipo */
    .team-banner {
        background: linear-gradient(135deg, #0039A6 0%, #001f5c 100%);
        padding: 2.5rem;
        border-radius: 12px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* Tarjetas de perfil interactivas */
    .profile-card {
        background-color: white;
        border: 1px solid #f0f2f6;
        border-radius: 12px;
        padding: 25px 15px;
        text-align: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        margin-bottom: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .profile-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 16px rgba(0,57,166,0.15);
        border: 1px solid #0039A6;
    }
    
    /* Círculo con las iniciales (Avatar) */
    .avatar {
        width: 65px;
        height: 65px;
        background: linear-gradient(135deg, #f0f2f6, #e0e0e0);
        color: #0039A6;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 1.5em;
        font-weight: 800;
        margin-bottom: 15px;
        border: 2px solid white;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }

    /* Insignias de roles */
    .role-badge {
        display: inline-block; 
        padding: 4px 12px; 
        border-radius: 20px;
        font-size: 0.85em; 
        font-weight: 600; 
        margin-top: 15px;
    }
    .pm { background: #FFB300; color: #000; }
    .solar { background: #0039A6; color: #FFF; }
    .econ { background: #2E7D32; color: #FFF; }
    .data { background: #C62828; color: #FFF; }
    .otro { background: #6A1B9A; color: #FFF; }
</style>
""", unsafe_allow_html=True)

# ── DATOS DEL EQUIPO ─────────────────────────────────────────────────────────
TEAM_NUMBER = 4

MEMBERS = [
    {"name": "Luis Daniel González Alcocer", "student_id": "A01286903", "role": "Project Manager (PM)"},
    {"name": "Andrés Saul Pérez Martinez", "student_id": "A01199376", "role": "Ingeniero Solar"},
    {"name": "Regina Echavarría Torres", "student_id": "A00841096", "role": "Ingeniero Solar"},
    {"name": "María Alejandra Peiro Loera", "student_id": "A00841878", "role": "Economista"},
    {"name": "Maximilien Tragarz Quintana", "student_id": "A01735557", "role": "Científico de Datos"},
    {"name": "Giancarlo Calcáneo Cadenas", "student_id": "A01664374", "role": "Analista de Datos"},
]

ABSTRACT = (
    "Esta herramienta permite la simulación fotovoltaica de instalaciones industriales bajo la "
    "tarifa GDMTH de CFE. La metodología implementada se basa en el modelo de Jensen para el "
    "cálculo de la irradiancia en el plano del arreglo (POA), considerando las componentes "
    "directa, difusa y reflejada. La aplicación permite dimensionar sistemas fotovoltaicos "
    "optimizados, evaluando el impacto económico en los cargos por energía (base, intermedia y "
    "punta), capacidad y distribución. Se incluye la justificación técnica de la selección de "
    "paneles Canadian Solar de 580W (Tier 1, eficiencia 22.5%) y baterías de litio LFP de "
    "5.12 kWh, así como el análisis comparativo entre la curva de carga original y la curva con "
    "inyección solar."
)

ROLE_CSS = {
    "Project Manager (PM)": "pm",
    "Ingeniero Solar": "solar",
    "Economista": "econ",
    "Analista de Datos": "data",
    "Científico de Datos": "data", # Añadido para que Maximilien tenga el color rojo
    "Otro": "otro",
}

# ── ENCABEZADO Y RESUMEN (Abstract) ──────────────────────────────────────────
st.markdown(f"""
<div class="team-banner">
    <h1 style="color: white !important; margin: 0; font-weight: 800; font-size: 3em;">Equipo {TEAM_NUMBER}</h1>
    <p style="font-size: 1.2em; color: #E0E0E0; margin-top: 5px;">Proyecto: Análisis Económico Solar GDMTH — Tecnológico de Monterrey</p>
</div>
""", unsafe_allow_html=True)

with st.container(border=True):
    st.markdown("### 📄 Abstract del Proyecto")
    st.write(ABSTRACT)

st.divider()

# ── INTEGRANTES (Tarjetas) ───────────────────────────────────────────────────
st.markdown("<h2 style='color: #0039A6; text-align: center; margin-bottom: 30px;'>Integrantes del Proyecto</h2>", unsafe_allow_html=True)

cols = st.columns(3)
for idx, m in enumerate(MEMBERS):
    with cols[idx % 3]:
        css = ROLE_CSS.get(m["role"], "otro")
        
        # Extraemos las iniciales del nombre (ej. Luis Daniel -> LD)
        nombres = m["name"].split()
        iniciales = f"{nombres[0][0]}{nombres[1][0]}" if len(nombres) > 1 else nombres[0][0]
        
        st.markdown(
            f"""
            <div class='profile-card'>
                <div class='avatar'>{iniciales}</div>
                <h4 style='color:#0039A6; margin:0; font-size: 1.1em;'>{m['name']}</h4>
                <p style='color:gray; margin:5px 0 0 0; font-size:0.9em;'>{m['student_id']}</p>
                <span class='role-badge {css}'>{m['role']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ── NOTA METODOLÓGICA JENSEN ─────────────────────────────────────────────────
st.divider()
with st.expander("📚 Sobre el modelo Jensen (isótropo difuso) — pvlib", expanded=False):
    st.markdown("""
    **Modelo de irradiancia isótropa (Jensen / Hay & Davies simplificado)**

    El modelo Jensen asume que la radiación difusa del cielo se distribuye de manera isótropa, es decir,
    con igual intensidad en todas las direcciones del hemisferio celeste. Esto permite calcular la
    irradiancia en el plano del panel (POA) a partir de los componentes GHI, DNI y DHI mediante:
    """)

    # Renderizado nativo de ecuaciones en Streamlit para evitar problemas visuales
    st.latex(r"G_{POA} = G_{b} \cdot R_b + G_{dh} \cdot \frac{1+\cos\beta}{2} + G_{gh} \cdot \rho \cdot \frac{1-\cos\beta}{2}")

    st.markdown("""
    *Donde:*
    * $R_b$ es el factor geométrico beam.
    * $\beta$ es el ángulo de inclinación.
    * $\rho$ es el albedo.

    **Referencia:** Jensen, A. R., Anderson, K. S., Holmgren, W. F., Mikofski, M. A., Hansen, C. W., Boeman, L. J., & Loonen, R. (2023).
    *pvlib iotools—Open-source Python functions for seamless access to solar irradiance data.*
    Solar Energy, 266, 112092. [DOI: 10.1016/j.solener.2023.112092](https://doi.org/10.1016/j.solener.2023.112092)

    Se eligió este modelo por su robustez comprobada, integración nativa en pvlib, y comportamiento
    conservador en estimaciones de generación (adecuado para proyecciones financieras).
    """)
    