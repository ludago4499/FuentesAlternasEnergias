"""
PV-specific financial models for the economics page.

Extends the plain continuity pattern (core.resilience.continuity_cashflows)
with the solar-panel realities the simple model ignores:

  - Panel degradation: generation (and therefore the tariff saving) decays
    ~0.5 %/yr, so the benefit is benefit·(1+infl)^(y−1)·(1−degr)^(y−1).
  - O&M: an annual operating cost (cleaning, monitoring, insurance) that
    grows with inflation and is subtracted from the gross benefit.
  - LCOE: levelized cost of energy, comparable head-to-head with the CFE
    average $/kWh.
  - Technology trade-offs: active panel cooling vs adding extra modules,
    and PV vs BESS opportunity cost (NPV per peso invested).

All functions are pure (no Streamlit) so they are unit-testable.
"""

from __future__ import annotations

import math


def annual_net_benefits(
    annual_benefit_mxn: float,
    project_life_years: int,
    inflation_pct: float = 5.0,
    degradation_pct: float = 0.0,
    om_annual_mxn: float = 0.0,
) -> list[float]:
    """Nominal net benefit per year (1-indexed): the gross benefit grows with
    tariff inflation but decays with panel degradation, while O&M only grows
    with inflation (a cleaning crew does not degrade with the panels)."""
    infl = inflation_pct / 100.0
    degr = degradation_pct / 100.0
    return [
        annual_benefit_mxn * ((1 + infl) ** (y - 1)) * ((1 - degr) ** (y - 1))
        - om_annual_mxn * ((1 + infl) ** (y - 1))
        for y in range(1, int(project_life_years) + 1)
    ]


def series_cashflows(
    capex_mxn: float,
    nominal_benefits: list[float],
    discount_pct: float = 10.0,
) -> dict:
    """
    Present-value cashflow series for an upfront CAPEX repaid by an arbitrary
    nominal yearly benefit series (year 1 first).

    Same shape as core.resilience.continuity_cashflows — month 0 is the CAPEX
    as a negative flow and each year's discounted net benefit is spread evenly
    over its 12 months so the bars sum exactly to the NPV. Accepting a series
    lets the caller mix benefits with different dynamics (e.g. a degrading FV
    saving plus a non-degrading avoided-outage cost).

    Payback is computed on NOMINAL cumulative net benefits (linear
    interpolation inside the crossing year), so it stays comparable with the
    simple "CAPEX / annual saving" figure when degradation and O&M are 0.
    """
    discount = discount_pct / 100.0
    nominal = list(nominal_benefits)
    annual_pv = [b / ((1 + discount) ** y) for y, b in enumerate(nominal, start=1)]
    npv = -capex_mxn + sum(annual_pv)

    monthly_pv = [-capex_mxn]
    for pv_y in annual_pv:
        monthly_pv.extend([pv_y / 12.0] * 12)

    cumulative = []
    acc = 0.0
    for f in monthly_pv:
        acc += f
        cumulative.append(acc)

    payback = float("inf")
    acc_nom = 0.0
    for y, b in enumerate(nominal, start=1):
        if b > 0 and acc_nom + b >= capex_mxn:
            payback = (y - 1) + (capex_mxn - acc_nom) / b
            break
        acc_nom += b

    return {
        "months": list(range(len(monthly_pv))),
        "monthly_pv_flows": monthly_pv,
        "cumulative_pv": cumulative,
        "annual_net_benefits": nominal,
        "npv_mxn": npv,
        "payback_years": payback,
    }


def pv_cashflows(
    capex_mxn: float,
    annual_benefit_mxn: float,
    project_life_years: int = 25,
    inflation_pct: float = 5.0,
    discount_pct: float = 10.0,
    degradation_pct: float = 0.5,
    om_annual_mxn: float = 0.0,
) -> dict:
    """``series_cashflows`` with the standard PV benefit dynamics: tariff
    inflation growth, panel degradation decay and inflation-indexed O&M."""
    nominal = annual_net_benefits(annual_benefit_mxn, project_life_years,
                                  inflation_pct, degradation_pct, om_annual_mxn)
    return series_cashflows(capex_mxn, nominal, discount_pct)


def cashflow_irr(capex_mxn: float, net_benefits: list[float]) -> float:
    """
    IRR (fraction/yr) of an upfront CAPEX repaid by the given yearly net
    benefits. Bisection on the 0–100 %/yr bracket, mirroring
    core.resilience.investment_irr: nan if never profitable, inf above 100 %.
    """
    if capex_mxn <= 0 or not net_benefits or sum(net_benefits) <= 0:
        return float("nan")

    def _npv_at(rate: float) -> float:
        return -capex_mxn + sum(
            b / ((1 + rate) ** y) for y, b in enumerate(net_benefits, start=1)
        )

    if _npv_at(0.0) < 0:
        return float("nan")
    if _npv_at(1.0) > 0:
        return float("inf")
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _npv_at(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def lcoe_mxn_kwh(
    capex_mxn: float,
    annual_gen_kwh: float,
    project_life_years: int = 25,
    discount_pct: float = 10.0,
    degradation_pct: float = 0.5,
    om_annual_mxn: float = 0.0,
    inflation_pct: float = 5.0,
) -> float:
    """
    Levelized Cost of Energy:
        LCOE = [CAPEX + Σ O&M_y/(1+d)^y] / [Σ E_y/(1+d)^y]
    with E_y = annual_gen·(1−degr)^(y−1) and O&M growing with inflation.
    Directly comparable with the CFE average $/kWh: below it → PV wins.
    """
    if annual_gen_kwh <= 0 or project_life_years <= 0:
        return float("nan")
    d = discount_pct / 100.0
    degr = degradation_pct / 100.0
    infl = inflation_pct / 100.0
    years = range(1, int(project_life_years) + 1)
    pv_energy = sum(annual_gen_kwh * ((1 - degr) ** (y - 1)) / ((1 + d) ** y) for y in years)
    pv_costs = capex_mxn + sum(om_annual_mxn * ((1 + infl) ** (y - 1)) / ((1 + d) ** y)
                               for y in years)
    return pv_costs / pv_energy if pv_energy > 0 else float("nan")


# ── Technology trade-offs ─────────────────────────────────────────────────────

def cooling_vs_extra_panels(
    annual_gen_kwh: float,
    thermal_loss_kwh: float,
    cooling_delta_t_c: float,
    temp_coeff_pmax: float,
    cooling_capex_mxn: float,
    cooling_opex_mxn_yr: float,
    panel_kwh_yr: float,
    panel_capex_mxn: float,
    energy_value_mxn_kwh: float,
    project_life_years: int = 25,
    inflation_pct: float = 5.0,
    discount_pct: float = 10.0,
    degradation_pct: float = 0.5,
) -> dict:
    """
    Engineering trade-off: recover thermally-lost energy with an active
    cooling system, or simply buy extra modules that produce the same kWh?

    The cooling side speaks engineering language: a ΔT (°C) cell-temperature
    reduction achieved by the system (water spray ≈ 10–20 °C). Recovered
    energy uses the panel's own power-temperature coefficient γ:

        E_rec = min( E_gen · |γ|/100 · ΔT ,  E_thermal_loss )

    The cap keeps the model congruent with physics: cooling can never recover
    more than what the NOCT derating actually lost (``thermal_loss_kwh``,
    surfaced by main.py from the with/without-derate year runs).

    Both options are valued with the same degradation-aware NPV so the
    comparison is apples-to-apples:
      - Cooling: −capex + PV(recovered kWh · tariff − opex)
      - Panels : −n·panel_capex + PV(n · panel_kwh · tariff)
    """
    recovered_uncapped = annual_gen_kwh * (abs(temp_coeff_pmax) / 100.0) * cooling_delta_t_c
    recovered_kwh = min(recovered_uncapped, max(thermal_loss_kwh, 0.0))

    n_panels = math.ceil(recovered_kwh / panel_kwh_yr) if panel_kwh_yr > 0 else 0
    panels_kwh = n_panels * panel_kwh_yr
    panels_capex = n_panels * panel_capex_mxn

    cf_cooling = pv_cashflows(cooling_capex_mxn, recovered_kwh * energy_value_mxn_kwh,
                              project_life_years, inflation_pct, discount_pct,
                              degradation_pct, om_annual_mxn=cooling_opex_mxn_yr)
    cf_panels = pv_cashflows(panels_capex, panels_kwh * energy_value_mxn_kwh,
                             project_life_years, inflation_pct, discount_pct,
                             degradation_pct, om_annual_mxn=0.0)

    cost_kwh_cooling = (cooling_capex_mxn / recovered_kwh) if recovered_kwh > 0 else float("inf")
    cost_kwh_panels = (panels_capex / panels_kwh) if panels_kwh > 0 else float("inf")

    if recovered_kwh <= 0:
        winner = "panels"
    elif cf_cooling["npv_mxn"] > cf_panels["npv_mxn"]:
        winner = "cooling"
    else:
        winner = "panels"

    return {
        "recovered_kwh_yr": recovered_kwh,
        "recovered_kwh_uncapped": recovered_uncapped,
        "capped_by_thermal_loss": recovered_uncapped > recovered_kwh,
        "cooling_delta_t_c": cooling_delta_t_c,
        "cooling_capex_mxn": cooling_capex_mxn,
        "cooling_npv_mxn": cf_cooling["npv_mxn"],
        "cooling_capex_per_kwh_yr": cost_kwh_cooling,
        "extra_panels": n_panels,
        "panels_kwh_yr": panels_kwh,
        "panels_capex_mxn": panels_capex,
        "panels_npv_mxn": cf_panels["npv_mxn"],
        "panels_capex_per_kwh_yr": cost_kwh_panels,
        "winner": winner,
    }


def investment_metrics(
    capex_mxn: float,
    annual_benefit_mxn: float,
    project_life_years: int,
    inflation_pct: float = 5.0,
    discount_pct: float = 10.0,
    degradation_pct: float = 0.0,
    om_annual_mxn: float = 0.0,
) -> dict:
    """NPV / IRR / payback / NPV-per-peso bundle for one investment option —
    the common currency for the PV-vs-BESS opportunity-cost comparison."""
    cf = pv_cashflows(capex_mxn, annual_benefit_mxn, project_life_years,
                      inflation_pct, discount_pct, degradation_pct, om_annual_mxn)
    irr = cashflow_irr(capex_mxn, cf["annual_net_benefits"])
    return {
        "capex_mxn": capex_mxn,
        "npv_mxn": cf["npv_mxn"],
        "irr": irr,
        "payback_years": cf["payback_years"],
        "npv_per_peso": (cf["npv_mxn"] / capex_mxn) if capex_mxn > 0 else float("nan"),
    }
