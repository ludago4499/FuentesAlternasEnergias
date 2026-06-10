
"""
Streger Solar — Evaluación Financiera de Continuidad de Negocio (Sección 4)
Tecnológico de Monterrey

Página independiente. Reemplaza por completo a la página "Economía GDMTH
Kardashev": borra ese archivo de pages/ y coloca este en su lugar (mismo
nombre de archivo para conservar su posición en el menú).

No depende de ningún otro archivo: sólo lee de st.session_state.
  Cotización de baterías -> Sección 3 (bess_proposal) o página Baterías
                            (battery_capex_usd / use_battery).
  Costo de apagones        -> input manual de esta página.
  Ahorro FV y CAPEX FV     -> Sección 2 (ahorro_fv_anual / s2_fv_capex_mxn), opcional.

Outputs (objetivo Sección 4):
  ROI basado en pérdidas operativas evitadas y cashflow mensual con y sin paneles.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.resilience import continuity_cashflows
from core.plots import continuity_cashflow_bar

st.set_page_config(page_title="Continuidad de Negocio", layout="wide")

st.title("Evaluación Financiera de Continuidad de Negocio")


def _roi_total_continuidad(capex_mxn, annual_benefit_mxn, project_life, inflation_pct):
    if capex_mxn <= 0:
        return float("nan")
    infl = inflation_pct / 100.0
    total = sum(annual_benefit_mxn * ((1 + infl) ** (yr - 1))
                for yr in range(1, project_life + 1))
    return (total - capex_mxn) / capex_mxn * 100.0


# Cotización de baterías (desde la sección de baterías)
usd_mxn = st.session_state.get("usd_mxn", 17.5)
_bess = st.session_state.get("bess_proposal")
_bat_page_usd = st.session_state.get("battery_capex_usd")
_use_bat_page = st.session_state.get("use_battery", False)

_quote_sources = []
if _bat_page_usd and _use_bat_page:
    _quote_sources.append(("Página Baterías", float(_bat_page_usd) * usd_mxn))
if _bess is not None:
    _quote_sources.append(("Sección 3 — Resiliencia", float(_bess["capex_mxn"])))

if not _quote_sources:
    st.warning("Dimensiona el banco de respaldo en la Sección 3 (o en la página Baterías) "
               "para traer la cotización aquí.")
    st.stop()

if len(_quote_sources) > 1:
    _idx = st.radio("Fuente de la cotización de baterías", range(len(_quote_sources)),
                    format_func=lambda i: _quote_sources[i][0], key="cont_quote_source")
else:
    _idx = 0
_capex_auto = _quote_sources[_idx][1]

c1, c2 = st.columns(2)
_override = c1.number_input("Cotización de baterías (MXN)", min_value=0.0,
                            value=float(_capex_auto), step=1000.0, format="%.2f",
                            key="cont_quote")
outage_cost = c2.number_input("Costo anual histórico por apagones (MXN/año)", min_value=0.0,
                              value=float(st.session_state.get("outage_cost_annual", 0.0)),
                              step=1000.0, format="%.2f", key="cont_outage_cost")
st.session_state["battery_quote_mxn"] = float(_override)
st.session_state["outage_cost_annual"] = float(outage_cost)
capex_batt = _override if _override > 0 else _capex_auto

fp1, fp2, fp3 = st.columns(3)
project_life = fp1.number_input("Vida del proyecto (años)", min_value=5, max_value=25,
                                value=10, step=1, key="cont_life")
inflation_pct = fp2.number_input("Inflación (%/año)", min_value=0.0, max_value=15.0,
                                 value=5.0, step=0.5, key="cont_infl")
discount_pct = fp3.number_input("Tasa de descuento (%)", min_value=1.0, max_value=25.0,
                                value=10.0, step=0.5, key="cont_disc")

ahorro_fv = float(st.session_state.get("ahorro_fv_anual", 0.0))
fv_capex = float(st.session_state.get("s2_fv_capex_mxn", 0.0))

if outage_cost <= 0 and ahorro_fv <= 0:
    st.info("Ingresa el costo anual por apagones para evaluar el ROI.")
    st.stop()

# Escenarios: sin paneles (batería sola) y con paneles (batería + FV)
cf_sin = continuity_cashflows(capex_batt, outage_cost,
                              int(project_life), inflation_pct, discount_pct)
cf_con = continuity_cashflows(capex_batt + fv_capex, outage_cost + ahorro_fv,
                              int(project_life), inflation_pct, discount_pct)

roi_sin = _roi_total_continuidad(capex_batt, outage_cost, int(project_life), inflation_pct)
roi_con = _roi_total_continuidad(capex_batt + fv_capex, outage_cost + ahorro_fv,
                                 int(project_life), inflation_pct)

# Output 1: ROI por pérdidas evitadas
st.subheader("ROI")
if fv_capex > 0 or ahorro_fv > 0:
    o1, o2 = st.columns(2)
    o1.metric("ROI sin paneles", f"{roi_sin:,.0f} %" if roi_sin == roi_sin else "—")
    o2.metric("ROI con paneles", f"{roi_con:,.0f} %" if roi_con == roi_con else "—")
else:
    st.metric("ROI sin paneles", f"{roi_sin:,.0f} %" if roi_sin == roi_sin else "—")

# Output 2: cashflow mensual con y sin paneles
st.subheader("Cashflow mensual con y sin paneles")
st.plotly_chart(
    continuity_cashflow_bar(
        cf_con["months"], cf_con["monthly_pv_flows"], cf_sin["monthly_pv_flows"],
        cf_con["cumulative_pv"], cf_sin["cumulative_pv"],
    ),
    use_container_width=True,
)

