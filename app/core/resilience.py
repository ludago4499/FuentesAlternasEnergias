"""
Backup (resilience) BESS sizing for GDMTO customers.

Under GDMTO there are no hourly periods, so a battery cannot arbitrage Punta
prices: its value is CONTINUITY — riding through CFE outages (apagones) while
feeding the critical load. This module sizes a battery bank for a required
backup duration and ranks the catalog by cost.

Sizing model:
    E_req [kWh] = P_crit · hours / ((DoD/100) · η_inv)      with η_inv = 0.96
    units       = max( ceil(E_req / usable_kwh), ceil(P_crit / power_kw) )

Both constraints must hold: enough usable energy for the duration AND enough
inverter power to carry the critical load.
"""

from __future__ import annotations

import math

from core.battery import load_batteries

INVERTER_EFF = 0.96
# Typical LiFePO4 deep-cycle band shown to the user alongside the catalog value
CYCLE_BAND = "4,000–5,000"


def kva_to_kw(kva: float, fp_pct: float = 89.89) -> float:
    """Convert apparent power to real power: kW = kVA × FP/100."""
    return kva * fp_pct / 100.0


def size_bess(p_crit_kw: float, hours: float, battery: dict,
              usd_mxn: float = 17.5) -> dict:
    """
    Size a bank of identical *battery* units to back up *p_crit_kw* for *hours*.

    Returns the unit count, totals, cycle life (worst case: one full cycle per
    day) and CAPEX = usd_per_kwh × nominal kWh × units × usd_mxn.
    """
    dod = battery.get("dod_pct", 90.0) / 100.0
    usable = float(battery["usable_kwh"])
    power = float(battery["power_kw"])

    if p_crit_kw <= 0 or hours <= 0:
        e_req = 0.0
        units = 0
    else:
        e_req = p_crit_kw * hours / (dod * INVERTER_EFF)
        units = max(math.ceil(e_req / usable), math.ceil(p_crit_kw / power))

    capex_usd = battery["usd_per_kwh"] * battery["kwh"] * units
    cycles = int(battery.get("cycles", 4000))

    return {
        "battery_id": battery.get("id", ""),
        "brand": battery.get("brand", ""),
        "model": battery.get("model", ""),
        "chemistry": battery.get("chemistry", ""),
        "units": units,
        "p_crit_kw": p_crit_kw,
        "backup_hours": hours,
        "e_req_kwh": e_req,
        "unit_usable_kwh": usable,
        "unit_power_kw": power,
        "total_usable_kwh": units * usable,
        "total_power_kw": units * power,
        "dod_pct": battery.get("dod_pct", 90.0),
        "roundtrip_efficiency_pct": battery.get("roundtrip_efficiency_pct", 95.0),
        "cycles": cycles,
        "cycle_band": CYCLE_BAND,
        # Worst case: one full cycle per day. In backup-only duty the battery
        # cycles only during outages, so calendar aging dominates instead.
        "life_years_daily_cycling": cycles / 365.0,
        "life_note": ("Peor caso: 1 ciclo completo/día. En uso sólo-respaldo los ciclos "
                      "se consumen únicamente durante apagones y la vida la limita el "
                      "calendario (10–15 años típico LiFePO4)."),
        "capex_usd": capex_usd,
        "capex_mxn": capex_usd * usd_mxn,
    }


def continuity_cashflows(
    capex_mxn: float,
    annual_benefit_mxn: float,
    project_life_years: int = 10,
    inflation_pct: float = 5.0,
    discount_pct: float = 10.0,
) -> dict:
    """
    Present-value cashflow series for the continuity investment.

    Annual NPV uses the same pattern as battery.optimize_units:
        NPV = −CAPEX + Σ_y benefit·(1+infl)^(y−1) / (1+disc)^y
    Each year's discounted net benefit is spread evenly over its 12 months for
    the monthly chart, so the monthly bars sum exactly to the NPV. Month 0 is
    the initial CAPEX as a negative flow.
    """
    inflation = inflation_pct / 100.0
    discount = discount_pct / 100.0
    years = range(1, int(project_life_years) + 1)

    annual_pv = [annual_benefit_mxn * ((1 + inflation) ** (y - 1)) / ((1 + discount) ** y)
                 for y in years]
    npv = -capex_mxn + sum(annual_pv)

    monthly_pv = [-capex_mxn]
    for pv_y in annual_pv:
        monthly_pv.extend([pv_y / 12.0] * 12)

    cumulative = []
    acc = 0.0
    for f in monthly_pv:
        acc += f
        cumulative.append(acc)

    payback_years = capex_mxn / annual_benefit_mxn if annual_benefit_mxn > 0 else float("inf")

    return {
        "months": list(range(len(monthly_pv))),
        "monthly_pv_flows": monthly_pv,
        "cumulative_pv": cumulative,
        "npv_mxn": npv,
        "payback_years": payback_years,
    }


def propose_bess(p_crit_kw: float, hours: float, usd_mxn: float = 17.5,
                 catalog: list[dict] | None = None) -> dict:
    """
    Size every catalog battery for the requirement and rank by lowest CAPEX
    (every sized option already meets both energy and power constraints).

    Returns {"best": option, "options": [all options sorted by capex_mxn]}.
    """
    catalog = catalog if catalog is not None else load_batteries()
    options = [size_bess(p_crit_kw, hours, b, usd_mxn) for b in catalog]
    options = [o for o in options if o["units"] > 0]
    options.sort(key=lambda o: o["capex_mxn"])
    return {"best": options[0] if options else None, "options": options}
