import streamlit as st

st.set_page_config(page_title="Equipo — GDMTH Solar", page_icon="☀️", layout="wide")

st.markdown("""
<style>
    .tec-header { color: #0039A6; font-weight: 700; }
    .role-badge {
        display:inline-block; padding:2px 10px; border-radius:12px;
        font-size:0.82em; font-weight:600; margin-left:8px;
    }
    .pm { background:#FFB300; color:#000; }
    .solar { background:#0039A6; color:#FFF; }
    .econ { background:#2E7D32; color:#FFF; }
    .data { background:#C62828; color:#FFF; }
    .otro { background:#6A1B9A; color:#FFF; }
</style>
""", unsafe_allow_html=True)

# ── HARDCODED TEAM DATA ──────────────────────────────────────────────────────
TEAM_NUMBER = 1

MEMBERS = [
    {"name": "Luis Daniel González Alcocer", "student_id": "A01286903", "role": "Project Manager (PM)"},
    {"name": "Andrés Saul Pérez Martinez", "student_id": "A01199376", "role": "Ingeniero Solar"},
    {"name": "Regina Echavarría Torres", "student_id": "A00841096", "role": "Ingeniero Solar"},
    {"name": "María Alejandra Peiro Loera", "student_id": "A00841878", "role": "Economista"},
    {"name": "Maximilien Tragarz Quintana", "student_id": "A01735557", "role": "Economista"},
    {"name": "Giancarlo Calcáneo Cadenas", "student_id": "A01664374", "role": "Analista de Datos"},
]

ABSTRACT = (
    "El proyecto evalúa la viabilidad económica de un sistema fotovoltaico para un cliente "
    "industrial tarifado bajo GDMTH de CFE. Se utiliza el modelo de irradiancia isótropa (Jensen) "
    "implementado en pvlib para calcular la irradiancia en el plano del panel (POA) a partir de "
    "datos GHI, DNI y DHI. El análisis integra la generación estimada con la estructura tarifaria "
    "GDMTH (cargos por energía en punta, intermedia y base, más demanda facturable) para cuantificar "
    "el ahorro anual, calcular indicadores financieros (VPN, TIR, payback) y determinar la "
    "rentabilidad del proyecto bajo distintos escenarios de inversión y degradación del sistema."
)

ROLE_CSS = {
    "Project Manager (PM)": "pm",
    "Ingeniero Solar": "solar",
    "Economista": "econ",
    "Analista de Datos": "data",
    "Otro": "otro",
}

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown(f"<h1 class='tec-header'>Equipo {TEAM_NUMBER}</h1>", unsafe_allow_html=True)
st.caption("Proyecto: Análisis Económico Solar GDMTH — Tecnológico de Monterrey")

st.divider()

# ── Members ──────────────────────────────────────────────────────────────────
st.markdown("### Integrantes")

cols = st.columns(3)
for idx, m in enumerate(MEMBERS):
    with cols[idx % 3]:
        css = ROLE_CSS.get(m["role"], "otro")
        st.markdown(
            f"""
            <div style='border:1px solid #ddd;border-radius:8px;padding:12px;margin-bottom:12px;'>
                <strong>{m['name']}</strong><br>
                <small style='color:gray'>{m['student_id']}</small><br>
                <span class='role-badge {css}'>{m['role']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ── Abstract ─────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### Abstract")
st.info(ABSTRACT)

# ── Jensen methodology note ──────────────────────────────────────────────────
st.divider()
with st.expander("Sobre el modelo Jensen (isótropo difuso) — pvlib", expanded=False):
    st.markdown("""
    **Modelo de irradiancia isótropa (Jensen / Hay & Davies simplificado)**

    El modelo Jensen asume que la radiación difusa del cielo se distribuye de manera isótropa, es decir,
    con igual intensidad en todas las direcciones del hemisferio celeste. Esto permite calcular la
    irradiancia en el plano del panel (POA) a partir de los componentes GHI, DNI y DHI mediante:

    $$G_{POA} = G_{b} \\cdot R_b + G_{dh} \\cdot \\frac{1+\\cos\\beta}{2} + G_{gh} \\cdot \\rho \\cdot \\frac{1-\\cos\\beta}{2}$$

    donde $R_b$ es el factor geométrico beam, $\\beta$ el ángulo de inclinación y $\\rho$ el albedo.

    **Referencia:** Jensen, A. R., Anderson, K. S., Holmgren, W. F., Mikofski, M. A., Hansen, C. W., Boeman, L. J., & Loonen, R. (2023).
    *pvlib iotools—Open-source Python functions for seamless access to solar irradiance data.*
    Solar Energy, 266, 112092. [DOI: 10.1016/j.solener.2023.112092](https://doi.org/10.1016/j.solener.2023.112092)

    Se eligió este modelo por su robustez comprobada, integración nativa en pvlib, y comportamiento
    conservador en estimaciones de generación (adecuado para proyecciones financieras).
    """)