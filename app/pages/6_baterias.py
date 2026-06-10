import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.gdmth import GDMTHCalculator
from core.battery import load_batteries, evaluate, optimize_units, classify_periods
from core.plots import (
    battery_dispatch_plot,
    battery_cost_comparison_bar,
    battery_optimization_plot,
)
from core.exporting import chart_with_export

st.set_page_config(page_title="Baterías — GDMTH Solar", page_icon="🔋", layout="wide")

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

st.markdown("""
<div class="bat-banner">
    <h1>🔋 Almacenamiento con Baterías</h1>
    <p>Recorte de pico (peak shaving) con carga 100% solar: elige el umbral, la ventana horaria y el arreglo, y observa cómo cambian las curvas de demanda y de gasto.</p>
</div>
""", unsafe_allow_html=True)

# ── Tariff-mode branch: peak shaving only makes sense under GDMTH ─────────────
if st.session_state.get("tariff_mode", "GDMTO") == "GDMTO":
    st.info(
        "🔀 Modo tarifario actual: **GDMTO** (sin periodos horarios). El recorte de Punta no aplica: "
        "bajo GDMTO la batería se justifica por **resiliencia ante apagones**. "
        "Usa la página **principal** (Sección 3 — Resiliencia y Sección 4 — Continuidad). "
        "Cambia el modo a GDMTH en ⚙️ **Configuración** para el análisis de peak shaving."
    )
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

# ── Battery selection ─────────────────────────────────────────────────────────
st.markdown("<h3 class='section-title'>1️⃣ Selecciona la batería</h3>", unsafe_allow_html=True)

bat_labels = [
    f"{b['brand']} {b['model']} — {b['usable_kwh']} kWh útil | {b['power_kw']} kW | "
    f"{b['roundtrip_efficiency_pct']}% RT | ${b['usd_per_kwh']}/kWh"
    for b in BATTERIES
]
bat_idx = st.selectbox("Modelo de batería", range(len(BATTERIES)),
                       format_func=lambda i: bat_labels[i])
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
    win = st.slider(
        "🕒 Ventana horaria para usar las baterías (hora del día)",
        min_value=0, max_value=24, value=(18, 22), step=1,
        help="Rango de horas en que la batería descarga. Por defecto el horario Punta (18–22h).",
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
cspec1.metric("Capacidad útil total", f"{cfg['capacity_kwh']:,.1f} kWh")
cspec2.metric("Potencia total", f"{cfg['power_kw']:,.1f} kW")
cspec3.metric("CAPEX baterías", f"${bat_capex_usd:,.0f} USD")
cspec4.metric("Modo de carga", "Solar (sin red)" if solar_only else "Solar + Red")

# ── Run dispatch (with battery) and the solar-only baseline ───────────────────
periods = classify_periods(demand_df["demand"].index)
ev_batt = evaluate(calc, demand_df, solar_kw, cfg, periods=periods)
ev_base = evaluate(calc, demand_df, solar_kw,
                   {"capacity_kwh": 0.0, "power_kw": 0.0, "roundtrip_pct": cfg["roundtrip_pct"]},
                   periods=periods)

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
    k1.metric("Reducción energía en ventana", f"{win_red_pct:.1f} %")
    k2.metric("Recorte de pico (demanda)", f"{peak_red_pct:.1f} %")
    k3.metric("Ahorro anual extra (batería)", f"${incr_savings:,.0f} MXN",
              help="Ahorro adicional respecto al escenario sólo-FV.")
    k4.metric("Payback de la batería",
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
    e1.metric("Cargada desde solar", f"{charge_solar_total:,.0f} kWh")
    e2.metric("Cargada desde red", f"{charge_grid_total:,.0f} kWh")
    e3.metric("Descargada al consumo", f"{discharge_total:,.0f} kWh")
    e4.metric("Ciclos equivalentes", f"{equiv_cycles:,.0f}")

    st.markdown("**Aprovechamiento del excedente solar**")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Excedente FV disponible", f"{surplus_total:,.0f} kWh")
    s2.metric("Excedente usado en batería", f"{surplus_used:,.0f} kWh")
    s3.metric("Excedente no aprovechado", f"{surplus_wasted:,.0f} kWh")
    s4.metric("Pérdidas por eficiencia", f"{eff_losses:,.0f} kWh")

    st.markdown("**¿De dónde viene el ahorro extra de la batería? (vs. sólo-FV)**")
    d1, d2, d3 = st.columns(3)
    d1.metric("Ahorro en Energía", f"${incr_energy:,.0f} MXN")
    d2.metric("Ahorro en Capacidad", f"${incr_cap:,.0f} MXN",
              help="Cargo por demanda media en Punta — clave del valor de la batería.")
    d3.metric("Ahorro en Distribución", f"${incr_dist:,.0f} MXN",
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

# ── Curve change: monthly cost ('gasto de energía') ───────────────────────────
st.write("")
with st.container(border=True):
    st.markdown("<h3 class='section-title'>💸 Cambio en el gasto de energía</h3>", unsafe_allow_html=True)
    fig_cost = battery_cost_comparison_bar(ev_base["monthly"], ev_batt["monthly"])
    chart_with_export(fig_cost, key="bat_cost", filename="gasto_energia_comparacion")

    g1, g2, g3 = st.columns(3)
    g1.metric("Factura anual sin FV", f"${annual_base.get('orig_total_mxn', 0):,.0f} MXN")
    g2.metric("Factura anual sólo FV", f"${annual_base.get('total_mxn', 0):,.0f} MXN")
    g3.metric("Factura anual FV + Batería", f"${annual_batt.get('total_mxn', 0):,.0f} MXN",
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
            b1.metric("Unidades óptimas", f"{best['units']}")
            b2.metric("Capacidad", f"{best['capacity_kwh']:,.0f} kWh")
            b3.metric("VPN de la batería", f"${best['npv_mxn']:,.0f} MXN")
            b4.metric("Payback", f"{best['payback_years']:.1f} años"
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
