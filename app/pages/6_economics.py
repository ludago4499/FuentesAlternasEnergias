"""
Streger Solar — Evaluación Financiera de Continuidad de Negocio
Tecnológico de Monterrey

Página económica. Hereda **limpiamente** las variables generadas por el análisis
de baterías y de FV; aquí no se recalcula generación, sólo se evalúa el ROI, el
flujo de caja y los trade-offs tecnológicos.

Variables heredadas (st.session_state):
  Cotización / CAPEX de baterías
      - Página Baterías  : battery_capex_usd · use_battery (× usd_mxn → MXN)
      - Sección 3 (main) : bess_proposal["capex_mxn"]
  Ahorro, CAPEX y generación FV (dos fuentes posibles)
      - Sección 2 (main)  : ahorro_fv_anual · s2_fv_capex_mxn · s2_gen_monthly ·
                            s2_panel · s2_temp_loss_kwh
      - ⚙️ Configuración  : panel · n_panels · panel_capex_usd (+ irradiance_df
                            de 🌞 Análisis Solar para anualizar la generación)
  Costo de apagones
      - outage_cost_annual (input manual de esta página)

Outputs:
  1. ROI / VPN / TIR / LCOE con supuestos FV avanzados (degradación + O&M
     + CAPEX llave en mano).
  2. Cashflow anual: histograma de flujos mensuales netos a valor presente
     (ahorro energético FV + apagones evitados − inversión batería/FV).
  3. Trade-off tecnológico: enfriamiento activo vs módulos extra, y
     FV vs BESS (costo de oportunidad).
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.jensen import compute_pv_generation
from core.pv_finance import (annual_net_benefits, series_cashflows, cashflow_irr,
                             lcoe_mxn_kwh, cooling_vs_extra_panels, investment_metrics)
from core.plots import continuity_cashflow_bar, tradeoff_npv_bar
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


def _roi_total(capex_mxn: float, nominal_benefits: list[float]) -> float:
    """Simple lifetime ROI (%) over nominal (undiscounted) net benefits."""
    if capex_mxn <= 0:
        return float("nan")
    total = sum(nominal_benefits)
    return (total - capex_mxn) / capex_mxn * 100.0


def _fmt_pct(v: float) -> str:
    if v != v:                      # nan
        return "—"
    if v == float("inf"):
        return "> 100 %"
    return f"{v * 100:.1f} %"


def _fmt_years(v: float) -> str:
    return f"{v:.1f} años" if v < 100 else "∞"


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

# ── Variables heredadas: sistema FV (Sección 2 ó ⚙️ Configuración) ────────────
costo_kwh = float(st.session_state.get("demand_costo_kwh")
                  or st.session_state.get("costo_promedio_kwh", 2.67))


def _s2_fv_source() -> dict | None:
    """PV system captured in Sección 2 of the standalone main page (GDMTO)."""
    capex_mod = float(st.session_state.get("s2_fv_capex_mxn", 0.0) or 0.0)
    ahorro = float(st.session_state.get("ahorro_fv_anual", 0.0) or 0.0)
    if capex_mod <= 0 and ahorro <= 0:
        return None
    return {
        "label": "Sección 2 (página principal)",
        "panel": st.session_state.get("s2_panel"),
        "n_panels": int(st.session_state.get("s2_n_panels_input", 0) or 0),
        "capex_mod_mxn": capex_mod,
        "gen_annual_kwh": float(sum(st.session_state.get("s2_gen_monthly") or [])),
        "temp_loss_kwh": float(st.session_state.get("s2_temp_loss_kwh", 0.0) or 0.0),
        "ahorro_anual": ahorro,
        "ahorro_is_express": False,
    }


def _config_fv_source() -> dict | None:
    """PV system saved in ⚙️ Configuración (GDMTH / advanced flow). Generation
    and thermal loss are derived from the irradiance run saved by 🌞 Análisis
    Solar (with/without temp-coefficient passes, annualized to 365 days); the
    tariff saving is an express estimate (kWh × average $/kWh) until the GDMTH
    flow exports a formal one."""
    panel = st.session_state.get("panel")
    n = int(st.session_state.get("n_panels", 0) or 0)
    capex_mod = float(st.session_state.get("panel_capex_usd", 0.0) or 0.0) * usd_mxn
    if panel is None or n <= 0 or capex_mod <= 0:
        return None
    gen = loss_kwh = 0.0
    df_irr = st.session_state.get("irradiance_df")
    if df_irr is not None and len(df_irr) > 0:
        _kwargs = dict(system_kwp=n * panel["wp"] / 1000.0,
                       panel_efficiency=panel["efficiency_pct"], panel_wp=panel["wp"],
                       panel_area_m2=panel.get("area_m2"), n_panels=n,
                       noct=panel.get("noct", 43))
        pv = compute_pv_generation(
            df_irr, temp_coeff_pmax=panel.get("temp_coeff_pmax", -0.30), **_kwargs)
        pv_ideal = compute_pv_generation(df_irr, temp_coeff_pmax=0.0, **_kwargs)
        dt_h = df_irr.attrs.get("dt_h", 1.0)
        days = max(len(df_irr) * dt_h / 24.0, 1.0)
        scale = 365.0 / days
        gen = float(pv.sum() * dt_h) * scale
        loss_kwh = max(float(pv_ideal.sum() * dt_h) * scale - gen, 0.0)
    return {
        "label": "⚙️ Configuración (avanzado)",
        "panel": panel,
        "n_panels": n,
        "capex_mod_mxn": capex_mod,
        "gen_annual_kwh": gen,
        "temp_loss_kwh": loss_kwh,
        "ahorro_anual": gen * costo_kwh,
        "ahorro_is_express": True,
    }


_FV_EMPTY = {"label": "—", "panel": None, "n_panels": 0, "capex_mod_mxn": 0.0,
             "gen_annual_kwh": 0.0, "temp_loss_kwh": 0.0, "ahorro_anual": 0.0,
             "ahorro_is_express": False}
_fv_sources = [s for s in (_s2_fv_source(), _config_fv_source()) if s]
if len(_fv_sources) > 1:
    # Both flows captured a system: let the user pick, defaulting to the flow
    # that matches the active tariff mode.
    _pref = 1 if st.session_state.get("tariff_mode") == "GDMTH" else 0
    _fi = st.radio("Fuente del sistema FV", range(len(_fv_sources)), index=_pref,
                   format_func=lambda i: _fv_sources[i]["label"],
                   horizontal=True, key="eco_fv_source")
    _fv = _fv_sources[_fi]
elif _fv_sources:
    _fv = _fv_sources[0]
    st.caption(f"Sistema FV heredado de: **{_fv['label']}**")
else:
    _fv = _FV_EMPTY

ahorro_fv = float(_fv["ahorro_anual"])
fv_capex_mod = float(_fv["capex_mod_mxn"])
annual_gen_kwh = float(_fv["gen_annual_kwh"])
_fv_on = fv_capex_mod > 0 or ahorro_fv > 0
if _fv["ahorro_is_express"] and ahorro_fv > 0:
    st.caption(f"💡 Ahorro FV **estimado express** (Configuración no exporta ahorro "
               f"tarifario): {annual_gen_kwh:,.0f} kWh/año × $ {costo_kwh:.2f}/kWh "
               f"= **$ {ahorro_fv:,.2f}/año**. Corre 🌞 Análisis Solar con un rango "
               f"amplio para mejorar la anualización.")
if _fv["panel"] is not None and _fv["n_panels"] > 0:
    _p = _fv["panel"]
    st.caption(f"🔆 Sistema: **{_fv['n_panels']} × {_p['brand']} {_p['model']}** "
               f"({_fv['n_panels'] * _p['wp'] / 1000.0:.2f} kWp)")

# ── Supuestos avanzados del sistema FV ────────────────────────────────────────
with st.expander("⚙️ Supuestos avanzados del sistema FV", expanded=_fv_on):
    st.caption("El CAPEX heredado de la Sección 2 cubre **sólo los módulos** (Wp × $/W). "
               "Un sistema llave en mano (inversor, estructura, BOS, instalación, trámites "
               "CFE) cuesta típicamente **1.8–2.5×** el costo de los módulos.")
    av1, av2, av3 = st.columns(3)
    capex_factor = av1.slider("Factor llave en mano (× módulos)", min_value=1.0,
                              max_value=3.0, value=2.0, step=0.1, key="eco_capex_factor",
                              help="Multiplica el CAPEX de módulos para aproximar el costo "
                                   "instalado completo. 1.0 = sólo módulos (como en la "
                                   "página principal).")
    degradation_pct = av2.number_input("Degradación del panel (%/año)", min_value=0.0,
                                       max_value=2.0, value=0.5, step=0.05, format="%.2f",
                                       key="eco_degradation",
                                       help="Pérdida anual de generación (típico 0.4–0.6 %/año; "
                                            "la garantía de potencia del fabricante la acota).")
    om_pct = av3.number_input("O&M anual (% del CAPEX FV)", min_value=0.0, max_value=5.0,
                              value=1.0, step=0.25, format="%.2f", key="eco_om_pct",
                              help="Limpieza, monitoreo y seguros, creciente con inflación.")

    fv_capex = fv_capex_mod * capex_factor
    om_annual = fv_capex * om_pct / 100.0
    if _fv_on:
        st.markdown(f"**CAPEX FV instalado:** $ {fv_capex:,.2f} MXN "
                    f"(módulos $ {fv_capex_mod:,.2f} × {capex_factor:.1f}) · "
                    f"**O&M:** $ {om_annual:,.2f} MXN/año")

st.markdown(f"**CAPEX baterías:** $ {capex_batt:,.2f} MXN · **CAPEX FV:** $ {fv_capex:,.2f} MXN · "
            f"**Beneficio anual:** apagones evitados $ {outage_cost:,.2f}"
            + (f" + ahorro FV $ {ahorro_fv:,.2f}" if _fv_on else ""))
if not _fv_on:
    st.caption("ℹ️ Sin sistema FV heredado — completa la **Sección 2** (página principal, "
               "paneles > 0 y evaluación económica) o guarda la **⚙️ Configuración** "
               "(flujo avanzado) para incluir el escenario *Con paneles*.")

if outage_cost <= 0 and ahorro_fv <= 0:
    st.info("Ingresa el costo anual por apagones para evaluar el ROI.")
    st.stop()

# ── Escenarios: sin paneles (batería sola) y con paneles (batería + FV) ────────
# FV saving degrades with the panels and pays O&M; the avoided-outage benefit
# only grows with inflation. Mixing both dynamics requires the series API.
fv_benefits = annual_net_benefits(ahorro_fv, int(project_life), inflation_pct,
                                  degradation_pct if _fv_on else 0.0,
                                  om_annual if _fv_on else 0.0)
outage_benefits = annual_net_benefits(outage_cost, int(project_life), inflation_pct)
con_benefits = [f + o for f, o in zip(fv_benefits, outage_benefits)]

cf_sin = series_cashflows(capex_batt, outage_benefits, discount_pct)
cf_con = series_cashflows(capex_batt + fv_capex, con_benefits, discount_pct)

roi_sin = _roi_total(capex_batt, outage_benefits)
roi_con = _roi_total(capex_batt + fv_capex, con_benefits)
irr_sin = cashflow_irr(capex_batt, outage_benefits)
irr_con = cashflow_irr(capex_batt + fv_capex, con_benefits)


def _roi_str(v: float) -> str:
    return f"{v:,.0f} %" if v == v else "—"   # v != v → nan


# ── Output 1: ROI, VPN, TIR y LCOE ────────────────────────────────────────────
st.subheader("ROI, VPN y TIR")
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
    o5, o6, o7, o8 = st.columns(4)
    custom_metric(o5, "TIR sin paneles", _fmt_pct(irr_sin),
                  help="Tasa que anula el VPN del escenario sólo-batería.")
    custom_metric(o6, "TIR con paneles", _fmt_pct(irr_con),
                  help="Tasa que anula el VPN del escenario batería + FV; "
                       "rentable cuando supera la tasa de descuento.")
    custom_metric(o7, "Payback con paneles", _fmt_years(cf_con["payback_years"]),
                  help="Años para recuperar la inversión con beneficios nominales "
                       "(inflación − degradación − O&M).")
    if annual_gen_kwh > 0 and fv_capex > 0:
        lcoe = lcoe_mxn_kwh(fv_capex, annual_gen_kwh, int(project_life), discount_pct,
                            degradation_pct, om_annual, inflation_pct)
        custom_metric(o8, "LCOE del sistema FV", f"$ {lcoe:.2f}/kWh",
                      delta=f"CFE $ {costo_kwh:.2f}/kWh",
                      delta_color="normal" if lcoe < costo_kwh else "inverse",
                      help="Costo nivelado de cada kWh solar sobre la vida del proyecto "
                           "(CAPEX + O&M descontados ÷ energía descontada). Si es menor "
                           "al costo CFE, cada kWh solar sale más barato que comprarlo.")
else:
    o1, o2, o3 = st.columns(3)
    custom_metric(o1, "ROI sin paneles", _roi_str(roi_sin))
    custom_metric(o2, "VPN sin paneles", f"$ {cf_sin['npv_mxn']:,.2f}",
                  delta="Rentable" if cf_sin["npv_mxn"] > 0 else "No rentable",
                  delta_color="normal" if cf_sin["npv_mxn"] > 0 else "inverse")
    custom_metric(o3, "TIR sin paneles", _fmt_pct(irr_sin))
    st.caption("Sin datos de paneles; se muestra sólo el escenario por pérdidas evitadas.")

# ── Output 2: Cashflow anual (histograma de flujos mensuales netos a VP) ──────
st.subheader("Cashflow anual — flujos mensuales netos a valor presente")
st.caption("Histograma de los flujos netos a valor presente: ahorro por consumo energético "
           "(FV, con degradación y O&M)"
           + (" + apagones evitados" if outage_cost > 0 else "")
           + " − inversión en baterías y FV (mes 0).")
chart_with_export(
    continuity_cashflow_bar(
        cf_con["months"], cf_con["monthly_pv_flows"], cf_sin["monthly_pv_flows"],
        cf_con["cumulative_pv"], cf_sin["cumulative_pv"],
    ),
    key="cont_cashflow", filename="flujo_continuidad",
)
st.caption("Mes 0 = CAPEX inicial negativo. Cada año: "
           "[ahorro·(1+inflación)^(año−1)·(1−degradación)^(año−1) − O&M] / (1+descuento)^año, "
           "repartido en 12 meses; las barras suman exactamente el VPN.")

# ══════════════════════════════════════════════════════════════════════════════
# Trade-off tecnológico
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("⚖️ Trade-off tecnológico")

# ── A) Enfriamiento activo vs módulos adicionales ─────────────────────────────
st.markdown("#### ❄️ Enfriamiento activo vs módulos adicionales")
panel = _fv["panel"]
n_panels = int(_fv["n_panels"])

if annual_gen_kwh <= 0 or panel is None or n_panels <= 0:
    st.info("Necesitas un sistema FV con generación: captura paneles en la **Sección 2** "
            "(página principal) o guarda la **⚙️ Configuración** y corre **🌞 Análisis "
            "Solar** (flujo avanzado).")
else:
    st.caption("¿Conviene invertir en enfriar los paneles para recuperar la energía perdida "
               "por temperatura, o es más barato instalar módulos adicionales que generen "
               "esa misma energía?")

    # Thermal loss: inherited from the with/without-NOCT-derate passes of the
    # selected source (exact under the model). Manual fallback if absent.
    gamma = abs(float(panel.get("temp_coeff_pmax", -0.30)))
    temp_loss_kwh = float(_fv["temp_loss_kwh"])
    if temp_loss_kwh > 0:
        _ideal_kwh = annual_gen_kwh + temp_loss_kwh
        temp_loss_pct = temp_loss_kwh / _ideal_kwh * 100.0 if _ideal_kwh > 0 else 0.0
        st.caption(f"🌡️ Pérdida térmica **heredada del modelo NOCT** ({_fv['label']}): "
                   f"**{temp_loss_kwh:,.0f} kWh/año** ({temp_loss_pct:.1f} % de la generación "
                   f"ideal a 25 °C de celda).")
    else:
        temp_loss_pct = st.number_input(
            "Pérdida térmica anual (%) — estimación manual", min_value=0.0, max_value=20.0,
            value=5.0, step=0.5, format="%.1f", key="eco_temp_loss",
            help="No se encontró la pérdida térmica del modelo (recalcula la Sección 2 en "
                 "la página principal o corre 🌞 Análisis Solar). Estimación típica en "
                 "clima mexicano: 4–8 %.")
        # gen = ideal·(1−p/100) → loss = gen·(p/100)/(1−p/100)
        temp_loss_kwh = annual_gen_kwh * (temp_loss_pct / 100.0) / max(1.0 - temp_loss_pct / 100.0, 1e-9)

    tc1, tc2, tc3 = st.columns(3)
    cooling_dt = tc1.slider("ΔT de enfriamiento (°C)", min_value=0.0, max_value=25.0,
                            value=15.0, step=0.5, key="eco_cool_dt",
                            help=f"Reducción de temperatura de celda lograda por el sistema "
                                 f"(aspersión de agua ≈ 10–20 °C). Cada °C recupera "
                                 f"|γ| = {gamma:.2f} %/°C de potencia, acotado a la pérdida "
                                 f"térmica real del modelo.")
    cooling_capex = tc2.number_input("CAPEX enfriamiento (MXN)", min_value=0.0,
                                     value=float(n_panels * 800.0), step=1000.0, format="%.0f",
                                     key="eco_cool_capex",
                                     help="Aspersores/ventilación + bombas + control. "
                                          "Por defecto ≈ $800 MXN por panel.")
    cooling_opex = tc3.number_input("OPEX enfriamiento (MXN/año)", min_value=0.0,
                                    value=float(cooling_capex * 0.05), step=500.0, format="%.0f",
                                    key="eco_cool_opex",
                                    help="Agua, bombeo y mantenimiento anual del sistema "
                                         "de enfriamiento.")

    panel_capex_mxn = panel["wp"] * panel["usd_per_w"] * usd_mxn * capex_factor
    panel_kwh_yr = annual_gen_kwh / n_panels

    trade = cooling_vs_extra_panels(
        annual_gen_kwh, temp_loss_kwh, cooling_dt, -gamma, cooling_capex, cooling_opex,
        panel_kwh_yr, panel_capex_mxn, costo_kwh,
        int(project_life), inflation_pct, discount_pct, degradation_pct,
    )

    ta1, ta2, ta3 = st.columns(3)
    custom_metric(ta1, "Energía recuperada", f"{trade['recovered_kwh_yr']:,.0f} kWh/año",
                  delta="⚠️ Acotada por la pérdida térmica"
                  if trade["capped_by_thermal_loss"] else None,
                  delta_color="off",
                  help=f"E = generación × |γ| × ΔT = {annual_gen_kwh:,.0f} × {gamma:.2f}%/°C × "
                       f"{cooling_dt:.1f} °C, acotada a la pérdida térmica del modelo "
                       f"({temp_loss_kwh:,.0f} kWh/año): el enfriamiento no puede recuperar "
                       f"más de lo que la temperatura pierde.")
    custom_metric(ta2, "Módulos equivalentes", f"{trade['extra_panels']}",
                  help=f"Paneles {panel['brand']} {panel['model']} extra que generan la "
                       f"misma energía ({panel_kwh_yr:,.0f} kWh/año c/u, "
                       f"$ {panel_capex_mxn:,.0f} MXN c/u instalado).")
    custom_metric(ta3, "CAPEX por kWh/año",
                  f"❄️ $ {trade['cooling_capex_per_kwh_yr']:,.0f} vs "
                  f"➕ $ {trade['panels_capex_per_kwh_yr']:,.0f}",
                  help="Inversión por cada kWh anual ganado: enfriamiento vs módulos extra.")

    chart_with_export(
        tradeoff_npv_bar(
            ["❄️ Enfriamiento activo", "➕ Módulos adicionales"],
            [trade["cooling_capex_mxn"], trade["panels_capex_mxn"]],
            [trade["cooling_npv_mxn"], trade["panels_npv_mxn"]],
        ),
        key="eco_tradeoff_cooling", filename="tradeoff_enfriamiento",
    )
    if trade["winner"] == "cooling":
        st.success(f"✅ **Veredicto de ingeniería:** el enfriamiento activo es más rentable "
                   f"(VPN $ {trade['cooling_npv_mxn']:,.0f} vs "
                   f"$ {trade['panels_npv_mxn']:,.0f} de los módulos extra), porque recupera "
                   f"{trade['recovered_kwh_yr']:,.0f} kWh/año con menor inversión por kWh.")
    else:
        st.success(f"✅ **Veredicto de ingeniería:** conviene añadir **{trade['extra_panels']} "
                   f"módulos** (VPN $ {trade['panels_npv_mxn']:,.0f} vs "
                   f"$ {trade['cooling_npv_mxn']:,.0f} del enfriamiento). Los módulos no "
                   f"tienen OPEX de bombeo/agua y su costo por kWh anual es menor.")

# ── B) Costo de oportunidad: FV vs BESS ───────────────────────────────────────
st.markdown("#### 🔆 FV vs 🔋 BESS — costo de oportunidad")
if not _fv_on or fv_capex <= 0:
    st.info("Necesitas un sistema FV heredado (Sección 2 o ⚙️ Configuración) para comparar "
            "el rendimiento de cada peso invertido en paneles vs en baterías.")
elif capex_batt <= 0 or outage_cost <= 0:
    st.info("Para comparar contra el BESS necesitas una **cotización de baterías** y un "
            "**costo anual por apagones** mayores a 0 (el beneficio de la batería en GDMTO "
            "es la continuidad).")
else:
    st.caption("Cada peso tiene un costo de oportunidad: ¿rinde más invertido en paneles "
               "(ahorro tarifario) o en el banco de baterías (apagones evitados)?")
    m_fv = investment_metrics(fv_capex, ahorro_fv, int(project_life), inflation_pct,
                              discount_pct, degradation_pct, om_annual)
    m_bess = investment_metrics(capex_batt, outage_cost, int(project_life), inflation_pct,
                                discount_pct)

    tb1, tb2, tb3, tb4 = st.columns(4)
    custom_metric(tb1, "TIR FV", _fmt_pct(m_fv["irr"]))
    custom_metric(tb2, "TIR BESS", _fmt_pct(m_bess["irr"]))
    custom_metric(tb3, "VPN por peso — FV", f"$ {m_fv['npv_per_peso']:.2f}",
                  help="VPN ÷ CAPEX: valor presente neto generado por cada peso invertido.")
    custom_metric(tb4, "VPN por peso — BESS", f"$ {m_bess['npv_per_peso']:.2f}",
                  help="VPN ÷ CAPEX: valor presente neto generado por cada peso invertido.")

    chart_with_export(
        tradeoff_npv_bar(
            ["🔆 Sistema FV", "🔋 BESS (continuidad)"],
            [m_fv["capex_mxn"], m_bess["capex_mxn"]],
            [m_fv["npv_mxn"], m_bess["npv_mxn"]],
        ),
        key="eco_tradeoff_fv_bess", filename="tradeoff_fv_bess",
    )

    if m_fv["npv_per_peso"] >= m_bess["npv_per_peso"]:
        st.success(f"✅ **Veredicto:** cada peso invertido en **FV** rinde más "
                   f"($ {m_fv['npv_per_peso']:.2f} vs $ {m_bess['npv_per_peso']:.2f} de VPN "
                   f"por peso). El BESS se justifica como **seguro de continuidad**, no como "
                   f"inversión de retorno: prioriza FV y dimensiona la batería al mínimo "
                   f"respaldo necesario.")
    else:
        st.success(f"✅ **Veredicto:** con un costo de apagones de $ {outage_cost:,.0f}/año, "
                   f"el **BESS** rinde más por peso invertido ($ {m_bess['npv_per_peso']:.2f} "
                   f"vs $ {m_fv['npv_per_peso']:.2f}). La continuidad domina: asegura el "
                   f"respaldo antes de ampliar el arreglo FV.")
