"""
Streger Solar — Evaluación Financiera de Continuidad de Negocio (Sección 4)
Tecnológico de Monterrey

Página independiente del flujo GDMTH. Sustituye a la antigua página de
"Economía GDMTH" conservando su posición en el menú lateral (mismo nombre de
archivo: 5_economics.py).

No modifica ni depende de ningún otro archivo: sólo LEE de `st.session_state`,
que es alimentado por las demás secciones:
  • Cotización de baterías  → Sección 3 (bess_proposal) y/o página 🔋 Baterías
                              (battery_capex_usd / use_battery).
  • Costo de apagones        → input manual de esta página (outage_cost_annual).
  • Ahorro FV y CAPEX FV     → Sección 2 (ahorro_fv_anual / s2_fv_capex_mxn),
                              opcionales: si existen, se evalúa el escenario
                              "con paneles".

OBJETIVO (Sección 4):
  INPUT  — Monto anual histórico gastado en reparaciones por apagones (manual).
  INPUT  — Cotización comercial de baterías (desde la sección de baterías).
  OUTPUT — ROI basado en pérdidas operativas evitadas (costo de la inacción),
           VPN, payback y simulación de cashflow mensual CON y SIN paneles.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.resilience import continuity_cashflows
from core.plots import continuity_cashflow_bar
from core.exporting import chart_with_export
from core.state import keep_state

st.set_page_config(page_title="Continuidad de Negocio — ROI", page_icon="📈", layout="wide")
keep_state()

# ── Estilos ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    h1 { color: #0039A6 !important; font-weight: 800 !important; }
    h3, h4 { color: #0039A6 !important; }
    .cont-banner {
        background: linear-gradient(135deg, #0039A6 0%, #C62828 100%);
        padding: 1.6rem 2rem; border-radius: 12px; color: white;
        margin-bottom: 1.2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .cont-banner h1 { color: white !important; margin: 0; font-size: 2.2em; }
    .cont-banner p { color: #FFE0E0; margin: 6px 0 0 0; font-size: 1.05em; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="cont-banner">
    <h1>📈 Evaluación Financiera de Continuidad de Negocio</h1>
    <p>ROI del respaldo ante apagones: cuánto cuesta NO invertir (costo de la inacción)
    frente a la inversión en baterías. Simulación de cashflow con y sin paneles.</p>
</div>
""", unsafe_allow_html=True)


# ── Helper: ROI nominal por pérdidas evitadas ─────────────────────────────────
def _roi_total_continuidad(capex_mxn: float, annual_benefit_mxn: float,
                           project_life: int, inflation_pct: float) -> float:
    """
    ROI total (%) = (beneficios nominales acumulados − CAPEX) / CAPEX × 100.

    El beneficio anual (pérdidas evitadas + ahorro FV) crece con la inflación de
    costos año con año. Es un ROI nominal; el descuento se maneja aparte en el VPN.
    'Basado en pérdidas evitadas' = el beneficio es el costo de los apagones que se
    deja de pagar.
    """
    if capex_mxn <= 0:
        return float("nan")
    infl = inflation_pct / 100.0
    total_benefit = sum(annual_benefit_mxn * ((1 + infl) ** (yr - 1))
                        for yr in range(1, project_life + 1))
    return (total_benefit - capex_mxn) / capex_mxn * 100.0


# ── Resolver la cotización de baterías DESDE la sección de baterías ───────────
usd_mxn = st.session_state.get("usd_mxn", 17.5)
_bess = st.session_state.get("bess_proposal")              # Sección 3 (resiliencia GDMTO)
_bat_page_usd = st.session_state.get("battery_capex_usd")  # página 🔋 Baterías (flujo GDMTH)
_use_bat_page = st.session_state.get("use_battery", False)

_quote_sources = []   # lista de (etiqueta, capex_mxn, detalle)
if _bat_page_usd and _use_bat_page:
    _b = st.session_state.get("battery", {})
    _u = st.session_state.get("battery_units", 0)
    _cfg = st.session_state.get("battery_cfg", {})
    _quote_sources.append((
        "Página 🔋 Baterías (arreglo configurado)",
        float(_bat_page_usd) * usd_mxn,
        f"{_u} × {_b.get('brand', '')} {_b.get('model', '')} · "
        f"{_cfg.get('capacity_kwh', 0):,.0f} kWh útil",
    ))
if _bess is not None:
    _quote_sources.append((
        "Sección 3 — Resiliencia (dimensionamiento automático)",
        float(_bess["capex_mxn"]),
        f"{_bess.get('units', '?')} × {_bess.get('brand', '')} {_bess.get('model', '')} · "
        f"{_bess.get('total_usable_kwh', 0):,.1f} kWh útil",
    ))

# ── Prerrequisito: necesita una cotización de baterías ────────────────────────
if not _quote_sources:
    st.warning(
        "⚠️ No hay **cotización de baterías** disponible todavía. Dimensiona el banco de "
        "respaldo en la **Sección 3 — Resiliencia** de la página principal (o configura un "
        "arreglo en la página **🔋 Baterías** del modo GDMTH). La cotización se trae "
        "automáticamente aquí, no necesitas capturarla a mano."
    )
    st.stop()

# ── 1) Cotización de baterías (viene de la sección de baterías) ───────────────
st.markdown("#### 🔋 Cotización de baterías (desde la sección de baterías)")
if len(_quote_sources) > 1:
    _idx = st.radio(
        "Fuente de la cotización", range(len(_quote_sources)),
        format_func=lambda i: _quote_sources[i][0], key="cont_quote_source",
    )
else:
    _idx = 0
_src_label, _capex_auto, _src_detail = _quote_sources[_idx]
st.caption(f"📦 {_src_detail} → **$ {_capex_auto:,.2f} MXN**")

_override = st.number_input(
    "Sustituir por cotización comercial real en PDF (MXN, opcional)", min_value=0.0,
    value=float(st.session_state.get("battery_quote_mxn", 0.0)),
    step=1000.0, format="%.2f", key="cont_quote_override",
    help="Si ya tienes una cotización de proveedor, ingrésala para sustituir la de "
         "catálogo. Deja 0 para usar la cotización traída de la sección de baterías.",
)
st.session_state["battery_quote_mxn"] = float(_override)
capex_batt = _override if _override > 0 else _capex_auto
capex_src = "cotización comercial (manual)" if _override > 0 else _src_label

# ── 2) INPUT manual: costo histórico anual por apagones (costo de la inacción) ─
st.markdown("#### 💥 Costo de la inacción")
outage_cost = st.number_input(
    "Monto anual histórico gastado en reparaciones por apagones (MXN/año)",
    min_value=0.0, value=float(st.session_state.get("outage_cost_annual", 0.0)),
    step=1000.0, format="%.2f", key="cont_outage_cost",
    help="Gasto histórico real en reparaciones de equipo, mermas, producto perdido y "
         "paros de producción causados por cortes de CFE. Es el costo que el respaldo evita.",
)
st.session_state["outage_cost_annual"] = float(outage_cost)

# ── 3) Parámetros financieros ─────────────────────────────────────────────────
fp1, fp2, fp3 = st.columns(3)
project_life = fp1.number_input("Vida del proyecto (años)", min_value=5, max_value=25,
                                value=10, step=1, key="cont_life")
inflation_pct = fp2.number_input("Inflación de costos (%/año)", min_value=0.0,
                                 max_value=15.0, value=5.0, step=0.5, key="cont_infl")
discount_pct = fp3.number_input("Tasa de descuento / WACC (%)", min_value=1.0,
                                max_value=25.0, value=10.0, step=0.5, key="cont_disc")

# ── 4) Escenario con paneles (FV) — automático desde Sección 2 o manual ───────
# Para que el escenario "con paneles" funcione bajo cualquier tarifa (GDMTO o
# GDMTH), tomamos el ahorro FV de la Sección 2 si existe y, si no, dejamos que el
# usuario lo capture aquí. Así siempre se pueden comparar ambos escenarios.
_fv_auto_ahorro = float(st.session_state.get("ahorro_fv_anual", 0.0))
_fv_auto_capex = float(st.session_state.get("s2_fv_capex_mxn", 0.0))

st.markdown("#### ☀️ Escenario con paneles solares (FV)")
incluir_fv = st.toggle(
    "Comparar también el escenario CON paneles solares", value=(_fv_auto_ahorro > 0 or _fv_auto_capex > 0),
    key="cont_incluir_fv",
    help="Si la Sección 2 ya calculó tu ahorro FV se usa automáticamente; también puedes "
         "capturarlo a mano para comparar con y sin paneles en cualquier tarifa.",
)
if incluir_fv:
    cfv1, cfv2 = st.columns(2)
    fv_capex = cfv1.number_input(
        "CAPEX de paneles FV (MXN)", min_value=0.0, value=_fv_auto_capex, step=1000.0,
        format="%.2f", key="cont_fv_capex",
        help="Inversión en paneles. Se trae de la Sección 2 si está disponible.",
    )
    ahorro_fv = cfv2.number_input(
        "Ahorro anual por FV (MXN/año)", min_value=0.0, value=_fv_auto_ahorro, step=1000.0,
        format="%.2f", key="cont_fv_ahorro",
        help="Ahorro tarifario anual que aportan los paneles.",
    )
else:
    fv_capex, ahorro_fv = 0.0, 0.0

if outage_cost <= 0 and ahorro_fv <= 0:
    st.info("ℹ️ Ingresa el costo anual por apagones (y/o activa el escenario **con paneles** "
            "arriba) para evaluar el ROI de la continuidad.")
    st.stop()

# ── 5) Escenarios de flujo (mismo motor que la optimización de baterías) ──────
# SIN paneles: batería sola, justificada SÓLO por las pérdidas evitadas.
cf_sin = continuity_cashflows(capex_batt, outage_cost,
                              int(project_life), inflation_pct, discount_pct)
# CON paneles: batería + FV → pérdidas evitadas + ahorro tarifario FV.
cf_con = continuity_cashflows(capex_batt + fv_capex, outage_cost + ahorro_fv,
                              int(project_life), inflation_pct, discount_pct)

roi_sin = _roi_total_continuidad(capex_batt, outage_cost,
                                 int(project_life), inflation_pct)
roi_con = _roi_total_continuidad(capex_batt + fv_capex, outage_cost + ahorro_fv,
                                 int(project_life), inflation_pct)

# Costo acumulado de NO hacer nada (apagones a lo largo de la vida útil)
_infl = inflation_pct / 100.0
inaccion_total = sum(outage_cost * ((1 + _infl) ** (yr - 1))
                     for yr in range(1, int(project_life) + 1))

st.markdown(
    f"**CAPEX baterías ({capex_src}):** $ {capex_batt:,.2f} MXN · "
    f"**CAPEX FV:** $ {fv_capex:,.2f} MXN · "
    f"**Beneficio anual:** apagones evitados $ {outage_cost:,.2f}"
    + (f" + ahorro FV $ {ahorro_fv:,.2f}" if ahorro_fv > 0 else "")
)

# ── 6) OUTPUT principal: ROI por pérdidas evitadas (costo de la inacción) ──────
st.markdown("#### 🎯 ROI basado en pérdidas evitadas (costo de la inacción)")
with st.container(border=True):
    r1, r2, r3 = st.columns(3)
    r1.metric("ROI — sólo respaldo (sin paneles)",
              f"{roi_sin:,.0f} %" if roi_sin == roi_sin else "—",
              help="Retorno de invertir SÓLO en baterías, justificado únicamente por las "
                   "reparaciones por apagones que se evitan.")
    r2.metric("Payback — sin paneles",
              f"{cf_sin['payback_years']:.1f} años"
              if cf_sin["payback_years"] < 100 else "∞",
              help="CAPEX batería / costo anual de apagones evitado.")
    r3.metric("VPN — sin paneles", f"$ {cf_sin['npv_mxn']:,.0f} MXN",
              delta="Rentable" if cf_sin["npv_mxn"] > 0 else "No rentable",
              delta_color="normal" if cf_sin["npv_mxn"] > 0 else "inverse")
    st.caption(
        f"💥 Costo de NO invertir a lo largo de {int(project_life)} años (apagones "
        f"acumulados): **$ {inaccion_total:,.0f} MXN** frente a una inversión en baterías "
        f"de **$ {capex_batt:,.0f} MXN**."
    )

# ── 7) OUTPUT secundario: ROI integral (respaldo + paneles) ───────────────────
if fv_capex > 0 or ahorro_fv > 0:
    st.markdown("#### ☀️ ROI integral (respaldo + paneles)")
    with st.container(border=True):
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("ROI — con paneles",
                   f"{roi_con:,.0f} %" if roi_con == roi_con else "—",
                   help="Retorno de baterías + FV: pérdidas evitadas + ahorro tarifario.")
        rc2.metric("Payback — con paneles",
                   f"{cf_con['payback_years']:.1f} años"
                   if cf_con["payback_years"] < 100 else "∞")
        rc3.metric("VPN — con paneles", f"$ {cf_con['npv_mxn']:,.0f} MXN",
                   delta="Rentable" if cf_con["npv_mxn"] > 0 else "No rentable",
                   delta_color="normal" if cf_con["npv_mxn"] > 0 else "inverse")

# ── 8) OUTPUT: simulación de cashflow mensual CON y SIN paneles ───────────────
st.markdown("#### 💸 Cashflow mensual a valor presente — con y sin paneles")
chart_with_export(
    continuity_cashflow_bar(
        cf_con["months"], cf_con["monthly_pv_flows"], cf_sin["monthly_pv_flows"],
        cf_con["cumulative_pv"], cf_sin["cumulative_pv"],
    ),
    key="cont_cashflow", filename="cashflow_continuidad",
)
st.caption(
    "Mes 0 = CAPEX inicial (negativo). **Con paneles** = baterías + FV "
    "(apagones evitados + ahorro tarifario). **Sin paneles** = baterías solas "
    "(sólo apagones evitados). Patrón de descuento: "
    "beneficio·(1+inflación)^(año−1) / (1+descuento)^año."
)
