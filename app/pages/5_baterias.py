import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.gdmth import GDMTHCalculator
from core.battery import load_batteries, evaluate, optimize_units, classify_periods
from core.resilience import propose_bess, size_bess, kva_to_kw
from core.plots import (
    battery_dispatch_plot,
    battery_cost_comparison_bar,
    battery_optimization_plot,
    charge_cycle_plot,
    load_duration_curve_plot,
)
from core.exporting import chart_with_export
from core.state import keep_state
from utils.theming import inject_theme, custom_metric

st.set_page_config(page_title="Baterías — GDMTH Solar", page_icon="🔋", layout="wide")
keep_state()

inject_theme("05")
# ── CSS / Banner ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .bat-banner {
        background: linear-gradient(135deg, #0039A6 0%, #2E7D32 100%);
        padding: 2rem; border-radius: 12px; color: white;
        margin-bottom: 1.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .bat-banner h1 { color: white !important; margin: 0; font-weight: 800; font-size: 2.4em; }
    .bat-banner p { font-size: 1.1em; color: #E8F5E9; margin-top: 5px; margin-bottom: 0; }
    .section-title { color: #0039A6; margin-top: 0; margin-bottom: 1rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

_bat_subtitle = (
    "Recorte de pico (peak shaving) con carga 100% solar: elige el umbral, la ventana horaria y "
    "el arreglo, y observa cómo cambian las curvas de demanda y de gasto."
    if st.session_state.get("tariff_mode", "GDMTO") == "GDMTH" else
    "Dimensionamiento de respaldo ante apagones: elige la carga crítica y las horas de respaldo, "
    "y observa la propuesta óptima, su sensibilidad y las alternativas del catálogo."
)
st.markdown(f"""
<div class="bat-banner">
    <h1>🔋 Almacenamiento con Baterías</h1>
    <p>{_bat_subtitle}</p>
</div>
""", unsafe_allow_html=True)

# ── Tariff-mode branch ────────────────────────────────────────────────────────
# GDMTH → peak shaving (resto de la página). GDMTO → no hay periodos horarios, así
# que el valor de la batería es la CONTINUIDAD (respaldo ante apagones): aquí se
# da el análisis de respaldo especializado en vez de redirigir.
if st.session_state.get("tariff_mode", "GDMTO") == "GDMTO":
    usd_mxn = st.session_state.get("usd_mxn", 17.5)
    st.info(
        "🔀 Modo tarifario actual: **GDMTO** (tarifa plana, sin periodos horarios). El recorte de "
        "Punta no aplica; aquí la batería se dimensiona por **respaldo ante apagones** "
        "(continuidad operativa). Cambia a GDMTH en ⚙️ **Configuración** para el peak shaving horario."
    )

    # ── 1) Carga crítica y duración de respaldo ───────────────────────────────
    st.markdown("<h3 class='section-title'>1️⃣ Carga crítica y duración de respaldo</h3>",
                unsafe_allow_html=True)
    cL1, cL2, cL3 = st.columns([2, 1, 1])
    load_val = cL1.number_input(
        "Carga crítica a respaldar", min_value=0.0,
        value=float(st.session_state.get("gdmto_crit_load_val", 20.0)), step=1.0, format="%.1f",
        key="gdmto_crit_load_val",
        help="Equipos que DEBEN seguir operando durante el apagón (refrigeración, servidores, "
             "bombas, iluminación de seguridad…).",
    )
    load_unit = cL2.selectbox("Unidad", ["kW", "kVA"], key="gdmto_crit_load_unit")
    if load_unit == "kVA":
        fp_load = cL3.number_input("FP de la carga (%)", min_value=50.0, max_value=100.0,
                                   value=89.89, step=0.01, format="%.2f", key="gdmto_crit_fp")
        p_crit_kw = kva_to_kw(load_val, fp_load)
        st.caption(f"kW = kVA × FP/100 → **{p_crit_kw:.1f} kW**")
    else:
        p_crit_kw = load_val

    backup_hours = st.slider(
        "🕒 Horas de respaldo requeridas (intervalo del apagón a cubrir)",
        min_value=1, max_value=24,
        value=int(st.session_state.get("backup_hours", 0) or 4), step=1, key="gdmto_backup_hours",
        help="Duración del corte de CFE que el banco debe sostener alimentando la carga crítica.",
    )
    st.session_state["backup_hours"] = int(backup_hours)
    st.session_state["critical_load_kw"] = float(p_crit_kw)

    if p_crit_kw <= 0:
        st.warning("Ingresa una carga crítica mayor a 0 para dimensionar el banco de baterías.")
        st.session_state["bess_proposal"] = None
        st.stop()

    prop = propose_bess(float(p_crit_kw), float(backup_hours), usd_mxn=usd_mxn)
    best = prop["best"]
    st.session_state["bess_proposal"] = best
    if best is None:
        st.warning("Ningún modelo del catálogo cumple la energía y potencia requeridas.")
        st.stop()

    # ── 2) Propuesta automática ───────────────────────────────────────────────
    st.markdown("<h3 class='section-title'>2️⃣ Propuesta automática (menor CAPEX que cumple)</h3>",
                unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"**{best['brand']} {best['model']}** · {best['chemistry']} · requiere "
                    f"**{best['e_req_kwh']:,.1f} kWh** para {backup_hours} h de respaldo a "
                    f"{p_crit_kw:,.1f} kW")
        pc1, pc2, pc3, pc4 = st.columns(4)
        custom_metric(pc1, "Unidades", f"{best['units']}")
        custom_metric(pc2, "Energía útil", f"{best['total_usable_kwh']:,.1f} kWh")
        custom_metric(pc3, "Potencia", f"{best['total_power_kw']:,.1f} kW")
        custom_metric(pc4, "CAPEX", f"$ {best['capex_mxn']:,.0f} MXN",
                      help=f"$ {best['capex_usd']:,.0f} USD × TDC {usd_mxn:.2f}")
        pc5, pc6, pc7 = st.columns(3)
        custom_metric(pc5, "Ciclos", f"{best['cycles']:,}",
                      help=f"Banda típica LiFePO4: {best['cycle_band']} ciclos.")
        custom_metric(pc6, "Vida (ciclado diario)", f"{best['life_years_daily_cycling']:.1f} años",
                      help=best["life_note"])
        custom_metric(pc7, "DoD / Eficiencia RT",
                      f"{best['dod_pct']:.0f}% / {best['roundtrip_efficiency_pct']:.0f}%")
        st.caption("ℹ️ " + best["life_note"])

    # ── 3) Sensibilidad: ¿cómo escala el respaldo con las horas? ───────────────
    st.markdown("<h3 class='section-title'>3️⃣ Sensibilidad — CAPEX vs horas de respaldo</h3>",
                unsafe_allow_html=True)
    st.caption("Cómo crecen las unidades, la energía requerida y el CAPEX del mejor arreglo "
               "conforme pides cubrir apagones más largos (misma carga crítica).")
    _hrs = list(range(1, 13))
    _sweep = [propose_bess(float(p_crit_kw), float(h), usd_mxn=usd_mxn)["best"] for h in _hrs]
    _capex = [(o["capex_mxn"] if o else 0.0) for o in _sweep]
    _ereq = [(o["e_req_kwh"] if o else 0.0) for o in _sweep]
    _units = [(o["units"] if o else 0) for o in _sweep]

    from plotly.subplots import make_subplots
    fig_sweep = make_subplots(specs=[[{"secondary_y": True}]])
    fig_sweep.add_trace(go.Bar(x=_hrs, y=_capex, name="CAPEX (MXN)",
                               marker_color="#0039A6"), secondary_y=False)
    fig_sweep.add_trace(go.Scatter(x=_hrs, y=_ereq, name="Energía requerida (kWh)",
                                   line=dict(color="#F57C00", width=3),
                                   mode="lines+markers"), secondary_y=True)
    fig_sweep.add_vline(x=backup_hours, line_dash="dash", line_color="#2E7D32",
                        annotation_text=f"Seleccionado: {backup_hours} h", annotation_position="top")
    fig_sweep.update_layout(template="plotly_white", height=380,
                            xaxis_title="Horas de respaldo", hovermode="x unified",
                            legend=dict(orientation="h", y=-0.2), margin=dict(t=20, b=50))
    fig_sweep.update_yaxes(title_text="CAPEX (MXN)", secondary_y=False)
    fig_sweep.update_yaxes(title_text="Energía requerida (kWh)", secondary_y=True, showgrid=False)
    chart_with_export(fig_sweep, key="gdmto_backup_sweep", filename="respaldo_vs_horas")

    sw1, sw2, sw3 = st.columns(3)
    custom_metric(sw1, "Unidades @ horas elegidas", f"{best['units']}")
    custom_metric(sw2, "Rango de unidades (1–12 h)", f"{min(_units)}–{max(_units)}")
    custom_metric(sw3, "CAPEX @ 12 h", f"$ {_capex[-1]:,.0f} MXN")

    # ── 4) Alternativas del catálogo ──────────────────────────────────────────
    st.markdown("<h3 class='section-title'>4️⃣ Alternativas del catálogo</h3>", unsafe_allow_html=True)
    alt_rows = [{
        "Modelo": f"{o['brand']} {o['model']}",
        "Química": o["chemistry"],
        "Unidades": o["units"],
        "Energía útil (kWh)": f"{o['total_usable_kwh']:,.1f}",
        "Potencia (kW)": f"{o['total_power_kw']:,.1f}",
        "Ciclos": f"{o['cycles']:,}",
        "Vida est. (años)": f"{o['life_years_daily_cycling']:.1f}",
        "CAPEX (MXN)": f"$ {o['capex_mxn']:,.0f}",
    } for o in prop["options"]]
    st.dataframe(pd.DataFrame(alt_rows), use_container_width=True, hide_index=True)
    st.caption("Todas cumplen ambas restricciones: energía (E_req = P·h / (DoD × η_inv)) y "
               "potencia (P ≥ carga crítica). El **ROI / continuidad** se evalúa en la "
               "página **📈 Economía** (hereda esta cotización).")
    st.stop()

# ── Prerequisites ─────────────────────────────────────────────────────────────
demand_df = st.session_state.get("demand_df")
solar_kw = st.session_state.get("solar_aligned")
region = st.session_state.get("region", "Noreste")
usd_mxn = st.session_state.get("usd_mxn", 17.5)

if demand_df is None:
    st.warning("⚠️ Primero genera o sube la **curva de demanda** en la página *Demanda e Inyección*.")
    st.stop()

if solar_kw is None:
    solar_kw = pd.Series(0.0, index=demand_df["demand"].index)
    st.info("ℹ️ No hay generación solar cargada — con *carga solar* la batería no podrá cargarse. "
            "Ejecuta el **Análisis Solar** para tener excedente FV.")

calc = GDMTHCalculator(region=region)
BATTERIES = load_batteries()

# Net demand with solar only (used for the umbral slider range and baseline)
solar_aligned = solar_kw.reindex(demand_df.index, fill_value=0.0)
net_solar_series = (demand_df["demand"] - solar_aligned).clip(lower=0)
peak_net = float(net_solar_series.max())

# ── Contexto heredado: paneles/sistema FV y generación que llega aquí ─────────
# El sistema (panel + nº de paneles) se elige en Configuración, se simula en
# Análisis Solar y se alinea contra la demanda en la página Demanda. Aquí se
# muestra explícitamente para confirmar que TODO eso se está heredando.
_panel = st.session_state.get("panel") or {}
_panel_name = (f"{_panel.get('brand', '')} {_panel.get('model', '')}".strip()
               or "— (configura en ⚙️ Configuración)")
_n_panels = int(st.session_state.get("n_panels", 0) or 0)
_system_kwp = float(st.session_state.get("system_kwp", 0.0) or 0.0)
_solar_total_kwh = float(solar_aligned.sum())

with st.container(border=True):
    st.markdown("**🔗 Heredado del flujo previo (Configuración → Solar → Demanda):**")
    h1, h2, h3, h4 = st.columns(4)
    custom_metric(h1, "Paneles", f"{_n_panels} × {_panel.get('wp', '—')} Wp" if _n_panels else "—",
                  help=_panel_name)
    custom_metric(h2, "Sistema FV", f"{_system_kwp:,.2f} kWp")
    custom_metric(h3, "Generación FV disponible", f"{_solar_total_kwh:,.0f} kWh",
                  help="Generación solar alineada contra la curva de demanda (página Demanda).")
    custom_metric(h4, "Fuente de demanda", st.session_state.get("demand_source", "—"))

    # Diagnóstico: el modelo solar corrió pero no llega generación → casi siempre
    # es que el rango de fechas del modelo solar no traslapa con la curva de demanda.
    _irr = st.session_state.get("irradiance_df")
    if _irr is not None and _solar_total_kwh < 1.0:
        _ss, _se = st.session_state.get("solar_start"), st.session_state.get("solar_end")
        st.warning(
            "⚠️ Hay un modelo solar ejecutado pero **no llega generación a las baterías** "
            f"(0 kWh). Casi siempre es porque el rango de fechas del **Análisis Solar** "
            f"({_ss} → {_se}) no coincide con el de la **curva de demanda** "
            f"({demand_df.index.min().date()} → {demand_df.index.max().date()}). "
            "Regenera la demanda con el mismo rango (la página Demanda lo alinea con "
            "`solar_start`/`solar_end`) o vuelve a correr el solar en ese rango."
        )
    elif _irr is None:
        st.info("ℹ️ Aún no se ha ejecutado el **Análisis Solar**: la batería se evalúa sin "
                "generación FV. Corre el modelo solar para heredar la generación de tus paneles.")

# ── Battery selection ─────────────────────────────────────────────────────────
st.markdown("<h3 class='section-title'>1️⃣ Selecciona la batería</h3>", unsafe_allow_html=True)

bat_labels = [
    f"{b['brand']} {b['model']} — {b['usable_kwh']} kWh útil | {b['power_kw']} kW | "
    f"{b['roundtrip_efficiency_pct']}% RT | ${b['usd_per_kwh']}/kWh"
    for b in BATTERIES
]
st.session_state.setdefault("battery_model_idx", 0)
if st.session_state["battery_model_idx"] >= len(BATTERIES):
    st.session_state["battery_model_idx"] = 0
bat_idx = st.selectbox("Modelo de batería", range(len(BATTERIES)),
                       format_func=lambda i: bat_labels[i], key="battery_model_idx",
                       help="Se sincroniza con el modelo elegido en la página de **Demanda**.")
battery = BATTERIES[bat_idx]

peak_kw = float(demand_df["demand"].max())
suggested_max = int(np.clip(np.ceil(peak_kw / max(battery["power_kw"], 1.0)) + 2, 5, 60))

# ── Arreglo + estrategia de operación ─────────────────────────────────────────
st.markdown("<h3 class='section-title'>2️⃣ Arreglo y estrategia de operación</h3>", unsafe_allow_html=True)

col_left, col_right = st.columns(2)

with col_left:
    st.session_state.setdefault("battery_units_slider", 1)
    st.session_state["battery_units_slider"] = int(
        np.clip(st.session_state["battery_units_slider"], 1, suggested_max)
    )
    units = st.slider(
        "Número de unidades en el arreglo", min_value=1, max_value=suggested_max, step=1,
        key="battery_units_slider",
        help="Desliza para ver en vivo cómo cambia la curva de demanda y el gasto.",
    )
    solar_only = st.toggle(
        "🌞 Cargar las baterías sólo con paneles solares (sin red)", value=True,
        help="Si se desactiva, la batería también puede recargarse de la red en horario Base.",
    )

with col_right:
    st.session_state.setdefault("battery_window", (18, 22))
    win = st.slider(
        "🕒 Ventana horaria para usar las baterías (hora del día)",
        min_value=0, max_value=24, step=1,
        key="battery_window",
        help="Rango de horas en que la batería descarga. Por defecto el horario Punta (18–22h). "
             "Se sincroniza con la ventana elegida en la página de **Demanda**.",
    )
    use_umbral = st.toggle("Usar umbral de recorte (peak shaving a un techo)", value=True)
    default_umbral = float(np.round(net_solar_series.quantile(0.65), -1)) if peak_net > 0 else 0.0
    umbral = st.slider(
        "⚡ Umbral de demanda (kW) — descargar sólo por encima de este nivel",
        min_value=0.0, max_value=float(np.ceil(peak_net / 10) * 10 or 10.0),
        value=min(default_umbral, peak_net), step=10.0, disabled=not use_umbral,
        help="La batería recorta la demanda neta que supere este umbral, dentro de la ventana horaria.",
    )

# Build the discharge window and config
win_start, win_end = int(win[0]), int(win[1])
discharge_hours = tuple(range(win_start, win_end)) if win_end > win_start else tuple()
cfg = {
    "capacity_kwh": units * battery["usable_kwh"],
    "power_kw": units * battery["power_kw"],
    "roundtrip_pct": battery["roundtrip_efficiency_pct"],
    "solar_only_charge": bool(solar_only),
    "discharge_hours": discharge_hours,
    "discharge_threshold_kw": float(umbral) if use_umbral else None,
}
bat_capex_usd = units * battery["kwh"] * battery["usd_per_kwh"]

if not discharge_hours:
    st.warning("La ventana horaria está vacía (inicio = fin): la batería no descargará. Ajusta el rango.")

cspec1, cspec2, cspec3, cspec4 = st.columns(4)
custom_metric(cspec1, "Capacidad útil total", f"{cfg['capacity_kwh']:,.1f} kWh")
custom_metric(cspec2, "Potencia total", f"{cfg['power_kw']:,.1f} kW")
custom_metric(cspec3, "CAPEX baterías", f"${bat_capex_usd:,.0f} USD")
custom_metric(cspec4, "Modo de carga", "Solar (sin red)" if solar_only else "Solar + Red")

# ── Run dispatch (with battery) and the solar-only baseline ───────────────────
# These are two hour-by-hour dispatch models. The page used to freeze because it
# re-ran both on every interaction: st.cache_data was re-hashing the full-year
# demand/solar frames (re-committed by keep_state each run) twice per rerun, so
# cache hits were unreliable and both heavy models recomputed.
#
# Fix: the heavy objects are passed as *underscore-prefixed* args, which
# st.cache_data does NOT hash. The cache key is instead a cheap signature
# (demand source + length + first/last timestamp + total energy) plus a
# canonical, hashable tuple of the config. Hashing is now O(1)-ish and the
# solar-only baseline (capacity 0 → config-independent) is computed once and
# reused across every slider move.
def _demand_signature(dem_df: pd.DataFrame, sol_kw: pd.Series) -> tuple:
    idx = dem_df.index
    return (
        st.session_state.get("demand_source", ""),
        len(idx),
        str(idx[0]) if len(idx) else "",
        str(idx[-1]) if len(idx) else "",
        round(float(dem_df["demand"].sum()), 3),
        round(float(sol_kw.sum()), 3),
    )


def _cfg_key(c: dict) -> tuple:
    return (
        round(float(c.get("capacity_kwh", 0.0)), 6),
        round(float(c.get("power_kw", 0.0)), 6),
        round(float(c.get("roundtrip_pct", 95.0)), 6),
        bool(c.get("solar_only_charge", True)),
        tuple(int(h) for h in (c.get("discharge_hours") or ())),
        c.get("discharge_threshold_kw"),
    )


@st.cache_data(show_spinner="Calculando despacho de baterías…")
def _eval_dispatch(sig: tuple, region: str, cfg_key: tuple,
                   _demand_df: pd.DataFrame, _solar_kw: pd.Series, _cfg: dict) -> dict:
    # Only `sig`, `region` and `cfg_key` participate in the cache key; the
    # underscore-prefixed frames/config are used for compute but not hashed.
    return evaluate(GDMTHCalculator(region=region), _demand_df, _solar_kw, _cfg)


_sig = _demand_signature(demand_df, solar_kw)
_base_cfg = {"capacity_kwh": 0.0, "power_kw": 0.0, "roundtrip_pct": cfg["roundtrip_pct"]}
ev_batt = _eval_dispatch(_sig, region, _cfg_key(cfg), demand_df, solar_kw, cfg)
ev_base = _eval_dispatch(_sig, region, _cfg_key(_base_cfg), demand_df, solar_kw, _base_cfg)

annual_batt = ev_batt["annual"]
annual_base = ev_base["annual"]
sim = ev_batt["sim"]
net_batt = ev_batt["net_after"]
net_solar = ev_base["net_after"]

# Incremental value of the battery over solar-only
incr_savings = annual_batt.get("savings_mxn", 0.0) - annual_base.get("savings_mxn", 0.0)
bat_capex_mxn = bat_capex_usd * usd_mxn
payback_batt = (bat_capex_mxn / incr_savings) if incr_savings > 0 else float("inf")

# Peak / window reduction inside the discharge window
win_sel = (np.isin(net_solar.index.hour, list(discharge_hours))
           if discharge_hours else np.zeros(len(net_solar), bool))
win_before = float(net_solar[win_sel].sum())
win_after = float(net_batt[win_sel].sum())
win_red_pct = (win_before - win_after) / win_before * 100 if win_before > 0 else 0.0
peak_after = float(net_batt.max())
peak_red_pct = (peak_kw - peak_after) / peak_kw * 100 if peak_kw > 0 else 0.0

st.markdown("<h3 class='section-title'>3️⃣ Impacto del arreglo</h3>", unsafe_allow_html=True)
with st.container(border=True):
    k1, k2, k3, k4 = st.columns(4)
    custom_metric(k1, "Reducción energía en ventana", f"{win_red_pct:.1f} %")
    custom_metric(k2, "Recorte de pico (demanda)", f"{peak_red_pct:.1f} %")
    custom_metric(k3, "Ahorro anual extra (batería)", f"${incr_savings:,.0f} MXN",
              help="Ahorro adicional respecto al escenario sólo-FV.")
    custom_metric(k4, "Payback de la batería",
              f"{payback_batt:.1f} años" if payback_batt < 100 else ">100 años")

# ── Desglose amplio de operación de la batería ────────────────────────────────
charge_solar_total = float(sim["charge_solar_kw"].sum())
charge_grid_total = float(sim["charge_grid_kw"].sum())
discharge_total = float(sim["discharge_kw"].sum())
cap_total = cfg["capacity_kwh"]
equiv_cycles = discharge_total / cap_total if cap_total > 0 else 0.0
surplus_total = float((solar_aligned - demand_df["demand"]).clip(lower=0).sum())
surplus_used = charge_solar_total
surplus_wasted = max(0.0, surplus_total - surplus_used)
eff_losses = max(0.0, (charge_solar_total + charge_grid_total) - discharge_total)

# Incremental savings broken down by GDMTH charge component
incr_energy = annual_batt.get("savings_energy_mxn", 0) - annual_base.get("savings_energy_mxn", 0)
incr_cap = annual_batt.get("savings_capacidad_mxn", 0) - annual_base.get("savings_capacidad_mxn", 0)
incr_dist = annual_batt.get("savings_distribucion_mxn", 0) - annual_base.get("savings_distribucion_mxn", 0)

st.write("")
with st.container(border=True):
    st.markdown("<h3 class='section-title'>🔬 Desglose detallado de operación</h3>", unsafe_allow_html=True)

    st.markdown("**Energía de la batería (en el periodo cargado)**")
    e1, e2, e3, e4 = st.columns(4)
    custom_metric(e1, "Cargada desde solar", f"{charge_solar_total:,.0f} kWh")
    custom_metric(e2, "Cargada desde red", f"{charge_grid_total:,.0f} kWh")
    custom_metric(e3, "Descargada al consumo", f"{discharge_total:,.0f} kWh")
    custom_metric(e4, "Ciclos equivalentes", f"{equiv_cycles:,.0f}")

    st.markdown("**Aprovechamiento del excedente solar**")
    s1, s2, s3, s4 = st.columns(4)
    custom_metric(s1, "Excedente FV disponible", f"{surplus_total:,.0f} kWh")
    custom_metric(s2, "Excedente usado en batería", f"{surplus_used:,.0f} kWh")
    custom_metric(s3, "Excedente no aprovechado", f"{surplus_wasted:,.0f} kWh")
    custom_metric(s4, "Pérdidas por eficiencia", f"{eff_losses:,.0f} kWh")

    st.markdown("**¿De dónde viene el ahorro extra de la batería? (vs. sólo-FV)**")
    d1, d2, d3 = st.columns(3)
    custom_metric(d1, "Ahorro en Energía", f"${incr_energy:,.0f} MXN")
    custom_metric(d2, "Ahorro en Capacidad", f"${incr_cap:,.0f} MXN",
              help="Cargo por demanda media en Punta — clave del valor de la batería.")
    custom_metric(d3, "Ahorro en Distribución", f"${incr_dist:,.0f} MXN",
              help="Cargo por demanda máxima del mes.")

    if solar_only and discharge_total < 1.0:
        st.warning(
            "⚠️ Con **carga sólo-solar** la batería únicamente se carga con el **excedente** de los paneles "
            f"(generación que supera la demanda). Tu sistema deja {surplus_total:,.0f} kWh de excedente y la "
            "batería casi no opera. Para aprovecharla: **aumenta el número de paneles** en *Configuración* "
            "o desactiva *carga sólo-solar* para permitir recarga de red en horario Base."
        )

# ── Curve change: demand & SoC ────────────────────────────────────────────────
st.write("")
with st.container(border=True):
    st.markdown("<h3 class='section-title'>📉 Cambio en la curva de demanda</h3>", unsafe_allow_html=True)
    dates = sorted(set(demand_df.index.date))
    c_f1, c_f2 = st.columns(2)
    start_view = c_f1.selectbox("Ver desde", dates, index=0)
    end_view = c_f2.selectbox("Ver hasta", dates, index=min(6, len(dates) - 1))

    mask = (demand_df.index.date >= start_view) & (demand_df.index.date <= end_view)
    fig_disp = battery_dispatch_plot(
        demand_df.loc[mask, "demand"],
        solar_aligned.loc[mask],
        net_solar.loc[mask],
        net_batt.loc[mask],
        sim["soc"].loc[mask],
        cfg["capacity_kwh"],
        threshold_kw=cfg["discharge_threshold_kw"],
        discharge_hours=discharge_hours,
    )
    chart_with_export(fig_disp, key="bat_dispatch", filename="despacho_bateria")
    st.caption("🔴 Demanda original · 🟠 Neta con FV · 🔵 Neta con FV+Batería (rellena) · 🟢 SoC · "
               "🟩 línea = umbral · banda = ventana horaria de descarga.")

# ── Curve change: charge-cycle behavior (SoC + energía por hora) ──────────────
st.write("")
with st.container(border=True):
    st.markdown("<h3 class='section-title'>🔄 Comportamiento de los ciclos de carga</h3>",
                unsafe_allow_html=True)
    chart_with_export(
        charge_cycle_plot(
            {k: v.loc[mask] for k, v in sim.items()},
            cfg["capacity_kwh"],
        ),
        key="bat_charge_cycle", filename="ciclos_carga_bateria",
    )
    st.caption("🟢 Estado de carga (SoC, %) · 🟡 carga desde solar · 🔵 carga desde red · "
               "🟠 descarga (kWh/hora). Muestra cómo se llena y vacía la batería cada día.")

# ── Curve change: load-duration curve ─────────────────────────────────────────
st.write("")
with st.container(border=True):
    st.markdown("<h3 class='section-title'>📐 Curva de duración de carga</h3>",
                unsafe_allow_html=True)
    chart_with_export(
        load_duration_curve_plot(
            demand_df.loc[mask, "demand"],
            net_solar.loc[mask],
            net_batt.loc[mask],
        ),
        key="bat_ldc", filename="curva_duracion_carga_bateria",
    )
    st.caption("Demanda ordenada de mayor a menor. Cuanto más se aplana y baja el pico de la curva "
               "azul (FV + batería), mayor el recorte de demanda máxima.")

# ── Curve change: monthly cost ('gasto de energía') ───────────────────────────
st.write("")
with st.container(border=True):
    st.markdown("<h3 class='section-title'>💸 Cambio en el gasto de energía</h3>", unsafe_allow_html=True)
    fig_cost = battery_cost_comparison_bar(ev_base["monthly"], ev_batt["monthly"])
    chart_with_export(fig_cost, key="bat_cost", filename="gasto_energia_comparacion")

    g1, g2, g3 = st.columns(3)
    custom_metric(g1, "Factura anual sin FV", f"${annual_base.get('orig_total_mxn', 0):,.0f} MXN")
    custom_metric(g2, "Factura anual sólo FV", f"${annual_base.get('total_mxn', 0):,.0f} MXN")
    custom_metric(g3, "Factura anual FV + Batería", f"${annual_batt.get('total_mxn', 0):,.0f} MXN",
              delta=f"-${annual_base.get('total_mxn', 0) - annual_batt.get('total_mxn', 0):,.0f} MXN",
              delta_color="inverse")

# ── Apply to economic analysis ────────────────────────────────────────────────
st.write("")
include = st.toggle(
    "Incluir esta batería en el Análisis Económico", value=st.session_state.get("use_battery", False),
    help="Al activarlo, la página de Economía sumará el CAPEX y el efecto de la batería.",
)
if include:
    st.session_state.update({
        "use_battery": True,
        "battery": battery,
        "battery_units": int(units),
        "battery_cfg": cfg,
        "battery_capex_usd": bat_capex_usd,
    })
    st.success(f"✅ Batería incluida: {units} × {battery['brand']} {battery['model']} "
               f"({cfg['capacity_kwh']:,.0f} kWh) — se reflejará en la página de Economía.")
else:
    st.session_state["use_battery"] = False

# ── Optimization ──────────────────────────────────────────────────────────────
st.divider()
st.markdown("<h3 class='section-title'>🎯 Optimización del arreglo</h3>", unsafe_allow_html=True)
st.caption("Barre distintos números de baterías (con la estrategia actual: umbral, ventana y modo de carga) "
           "y encuentra el arreglo con mayor Valor Presente Neto (VPN).")

with st.container(border=True):
    o1, o2, o3 = st.columns(3)
    opt_max = o1.number_input("Máx. unidades a evaluar", min_value=2, max_value=60,
                              value=min(suggested_max, 20), step=1)
    opt_life = o2.number_input("Vida útil del proyecto (años)", min_value=5, max_value=30, value=25, step=1)
    opt_infl = o3.number_input("Inflación tarifaria CFE (%/año)", min_value=0.0, max_value=15.0,
                               value=5.0, step=0.5)
    o4, o5, _ = st.columns(3)
    opt_disc = o4.number_input("Tasa de descuento / WACC (%)", min_value=1.0, max_value=25.0,
                               value=10.0, step=0.5)
    opt_inst = o5.number_input("Factor de instalación (%)", min_value=0.0, max_value=60.0,
                               value=20.0, step=1.0)

    if st.button("🚀 Optimizar arreglo de baterías", type="primary", use_container_width=True):
        with st.spinner(f"Evaluando 0 a {int(opt_max)} unidades…"):
            opt = optimize_units(
                calc, demand_df, solar_kw, battery,
                max_units=int(opt_max), usd_mxn=usd_mxn,
                install_factor_pct=opt_inst, project_life=int(opt_life),
                inflation_pct=opt_infl, discount_pct=opt_disc,
                solar_only_charge=bool(solar_only),
                discharge_hours=discharge_hours,
                discharge_threshold_kw=float(umbral) if use_umbral else None,
            )
        st.session_state["battery_opt"] = opt

    opt = st.session_state.get("battery_opt")
    if opt:
        best = opt["best"]
        chart_with_export(battery_optimization_plot(opt["rows"], best["units"]),
                          key="bat_optimization", filename="optimizacion_baterias")

        if best["units"] == 0:
            st.warning("Con los parámetros actuales, **ninguna batería es rentable** (VPN máximo en 0 unidades). "
                       "Prueba bajando el umbral, ampliando la ventana o con mayor inflación tarifaria.")
        else:
            st.markdown("#### 🏆 Mejor arreglo encontrado")
            b1, b2, b3, b4 = st.columns(4)
            custom_metric(b1, "Unidades óptimas", f"{best['units']}")
            custom_metric(b2, "Capacidad", f"{best['capacity_kwh']:,.0f} kWh")
            custom_metric(b3, "VPN de la batería", f"${best['npv_mxn']:,.0f} MXN")
            custom_metric(b4, "Payback", f"{best['payback_years']:.1f} años"
                      if best["payback_years"] < 100 else ">100 años")

            if st.button(f"📌 Aplicar mejor arreglo ({best['units']} unidades)", use_container_width=True):
                st.session_state["battery_units_slider"] = int(best["units"])
                st.rerun()

        with st.expander("📄 Ver tabla completa de la optimización"):
            df_opt = pd.DataFrame([{
                "Unidades": r["units"],
                "Capacidad (kWh)": f"{r['capacity_kwh']:,.0f}",
                "Potencia (kW)": f"{r['power_kw']:,.0f}",
                "CAPEX (MXN)": f"${r['capex_mxn']:,.0f}",
                "Ahorro extra/año (MXN)": f"${r['incr_savings_mxn']:,.0f}",
                "VPN (MXN)": f"${r['npv_mxn']:,.0f}",
                "Payback (años)": f"{r['payback_years']:.1f}" if r["payback_years"] < 100 else "∞",
            } for r in opt["rows"]])
            st.dataframe(df_opt, use_container_width=True, hide_index=True)
