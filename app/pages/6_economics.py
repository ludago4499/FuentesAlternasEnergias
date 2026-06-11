"""
Streger Solar — Evaluación Financiera de Continuidad de Negocio
Tecnológico de Monterrey

Página económica. Hereda **limpiamente** las variables generadas por el análisis
de baterías y de FV; aquí no se recalcula nada pesado, sólo se evalúa el ROI y el
flujo de caja con y sin paneles.

Variables heredadas (st.session_state):
  Cotización / CAPEX de baterías
      - Página Baterías  : battery_capex_usd · use_battery (× usd_mxn → MXN)
      - Sección 3 (main) : bess_proposal["capex_mxn"]
  Ahorro y CAPEX FV
      - ahorro_fv_anual · s2_fv_capex_mxn (opcionales)
  Costo de apagones
      - outage_cost_annual (input manual de esta página)

Outputs: ROI y cashflow mensual con y sin paneles (pérdidas operativas evitadas).
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.resilience import continuity_cashflows
from core.plots import continuity_cashflow_bar
from core.exporting import chart_with_export
from core.state import keep_state
from utils.theming import inject_theme, custom_metric

st.set_page_config(page_title="Continuidad de Negocio", page_icon="📈", layout="wide")
keep_state()

inject_theme("06")
st.title("📈 Evaluación Financiera de Continuidad de Negocio")
st.caption("Evalúa el retorno económico con y sin paneles. La batería es **opcional**: "
           "si la dimensionaste, su CAPEX se hereda automáticamente; si no, puedes evaluar "
           "sólo el sistema FV y/o las pérdidas por apagones evitadas.")


def _roi_total_continuidad(capex_mxn, annual_benefit_mxn, project_life, inflation_pct):
    """ROI total simple sobre la vida del proyecto con beneficio creciente por inflación."""
    if capex_mxn <= 0:
        return float("nan")
    infl = inflation_pct / 100.0
    total = sum(annual_benefit_mxn * ((1 + infl) ** (yr - 1))
                for yr in range(1, project_life + 1))
    return (total - capex_mxn) / capex_mxn * 100.0


# ── Variables heredadas: CAPEX de baterías ────────────────────────────────────
usd_mxn = st.session_state.get("usd_mxn", 17.5)
_bess = st.session_state.get("bess_proposal")
_bat_page_usd = st.session_state.get("battery_capex_usd")
_use_bat_page = st.session_state.get("use_battery", False)

_quote_sources: list[tuple[str, float]] = []
if _bat_page_usd and _use_bat_page:
    _quote_sources.append(("Página Baterías", float(_bat_page_usd) * usd_mxn))
if _bess is not None:
    _quote_sources.append(("Sección 3 — Resiliencia", float(_bess["capex_mxn"])))

# La batería es opcional: si no hay cotización heredada, el CAPEX de batería
# arranca en 0 y la evaluación procede sólo con FV y/o apagones evitados.
if not _quote_sources:
    _capex_auto = 0.0
    st.info("ℹ️ No hay cotización de baterías heredada — evaluando **sin batería**. "
            "Dimensiona el banco en la **Sección 3** (página principal) o en **🔋 Baterías** "
            "para incluir su CAPEX aquí.")
elif len(_quote_sources) > 1:
    _idx = st.radio("Fuente de la cotización de baterías", range(len(_quote_sources)),
                    format_func=lambda i: _quote_sources[i][0], key="cont_quote_source")
    _capex_auto = _quote_sources[_idx][1]
else:
    st.caption(f"Cotización heredada de: **{_quote_sources[0][0]}**")
    _capex_auto = _quote_sources[0][1]

# ── Inputs de la evaluación ───────────────────────────────────────────────────
c1, c2 = st.columns(2)
_override = c1.number_input("Cotización de baterías (MXN)", min_value=0.0,
                            value=float(_capex_auto), step=1000.0, format="%.2f",
                            key="cont_quote",
                            help="Heredada del análisis de baterías; edítala si tienes una "
                                 "cotización comercial real.")
outage_cost = c2.number_input("Costo anual histórico por apagones (MXN/año)", min_value=0.0,
                              value=float(st.session_state.get("outage_cost_annual", 0.0)),
                              step=1000.0, format="%.2f", key="cont_outage_cost",
                              help="Gasto histórico por cortes de CFE (mermas, paros, producto "
                                   "perdido). Con respaldo, este costo se evita.")
st.session_state["battery_quote_mxn"] = float(_override)
st.session_state["outage_cost_annual"] = float(outage_cost)
capex_batt = _override if _override > 0 else _capex_auto

fp1, fp2, fp3 = st.columns(3)
project_life = fp1.number_input("Vida del proyecto (años)", min_value=5, max_value=25,
                                value=int(st.session_state.get("cont_life_val", 10)), step=1,
                                key="cont_life")
inflation_pct = fp2.number_input("Inflación (%/año)", min_value=0.0, max_value=15.0,
                                 value=5.0, step=0.5, key="cont_infl")
discount_pct = fp3.number_input("Tasa de descuento (%)", min_value=1.0, max_value=25.0,
                                value=10.0, step=0.5, key="cont_disc")

# ── Variables heredadas: ahorro y CAPEX FV ────────────────────────────────────
ahorro_fv = float(st.session_state.get("ahorro_fv_anual", 0.0))
fv_capex = float(st.session_state.get("s2_fv_capex_mxn", 0.0))
_fv_on = fv_capex > 0 or ahorro_fv > 0

st.markdown(f"**CAPEX baterías:** $ {capex_batt:,.2f} MXN · **CAPEX FV:** $ {fv_capex:,.2f} MXN · "
            f"**Beneficio anual:** apagones evitados $ {outage_cost:,.2f}"
            + (f" + ahorro FV $ {ahorro_fv:,.2f}" if _fv_on else ""))
if not _fv_on:
    st.caption("ℹ️ Sin ahorro tarifario FV heredado — completa la **Sección 2** (paneles > 0 y "
               "evaluación económica) para incluir el escenario *Con paneles*.")

if outage_cost <= 0 and ahorro_fv <= 0:
    st.info("Ingresa el costo anual por apagones para evaluar el ROI.")
    st.stop()

# ── Escenarios: sin paneles (batería sola) y con paneles (batería + FV) ────────
cf_sin = continuity_cashflows(capex_batt, outage_cost,
                              int(project_life), inflation_pct, discount_pct)
cf_con = continuity_cashflows(capex_batt + fv_capex, outage_cost + ahorro_fv,
                              int(project_life), inflation_pct, discount_pct)

roi_sin = _roi_total_continuidad(capex_batt, outage_cost, int(project_life), inflation_pct)
roi_con = _roi_total_continuidad(capex_batt + fv_capex, outage_cost + ahorro_fv,
                                 int(project_life), inflation_pct)


def _roi_str(v: float) -> str:
    return f"{v:,.0f} %" if v == v else "—"   # v != v → nan


# ── Output 1: ROI y VPN por pérdidas evitadas ─────────────────────────────────
st.subheader("ROI y VPN")
if _fv_on:
    o1, o2, o3, o4 = st.columns(4)
    custom_metric(o1, "ROI sin paneles", _roi_str(roi_sin))
    custom_metric(o2, "ROI con paneles", _roi_str(roi_con))
    custom_metric(o3, "VPN sin paneles", f"$ {cf_sin['npv_mxn']:,.2f}",
                  delta="Rentable" if cf_sin["npv_mxn"] > 0 else "No rentable",
                  delta_color="normal" if cf_sin["npv_mxn"] > 0 else "inverse")
    custom_metric(o4, "VPN con paneles", f"$ {cf_con['npv_mxn']:,.2f}",
                  delta="Rentable" if cf_con["npv_mxn"] > 0 else "No rentable",
                  delta_color="normal" if cf_con["npv_mxn"] > 0 else "inverse")
else:
    o1, o2 = st.columns(2)
    custom_metric(o1, "ROI sin paneles", _roi_str(roi_sin))
    custom_metric(o2, "VPN sin paneles", f"$ {cf_sin['npv_mxn']:,.2f}",
                  delta="Rentable" if cf_sin["npv_mxn"] > 0 else "No rentable",
                  delta_color="normal" if cf_sin["npv_mxn"] > 0 else "inverse")
    st.caption("Sin datos de paneles; se muestra sólo el escenario por pérdidas evitadas.")

# ── Output 2: cashflow mensual con y sin paneles ──────────────────────────────
st.subheader("Cashflow mensual con y sin paneles")
chart_with_export(
    continuity_cashflow_bar(
        cf_con["months"], cf_con["monthly_pv_flows"], cf_sin["monthly_pv_flows"],
        cf_con["cumulative_pv"], cf_sin["cumulative_pv"],
    ),
    key="cont_cashflow", filename="flujo_continuidad",
)
st.caption("Flujos mensuales **a valor presente** (mes 0 = CAPEX inicial negativo). "
           "Beneficio·(1+inflación)^(año−1)/(1+descuento)^año.")
