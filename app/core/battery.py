"""
Battery storage dispatch & GDMTH peak-shaving optimization.

The economic value of a battery under the CFE GDMTH tariff comes almost entirely
from **peak shaving**: discharging during the expensive Punta hours (which also
set the Cargo por Capacidad) and recharging during the cheap Base hours or from
surplus PV generation.

This module provides:
  - simulate_dispatch : greedy hour-by-hour battery dispatch over a load series.
  - dispatch_net      : convenience wrapper returning only the post-battery grid demand.
  - evaluate          : run a dispatch and compute the resulting monthly GDMTH bills.
  - optimize_units    : sweep the number of battery units and rank them by NPV.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from core.gdmth import GDMTHCalculator, classify_period

_BAT_PATH = Path(__file__).parent.parent / "data" / "batteries.json"


def load_batteries() -> list[dict]:
    """Load the battery catalog (list of unit specs)."""
    with open(_BAT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def classify_periods(index: pd.DatetimeIndex) -> np.ndarray:
    """Pre-compute the CFE period ('punta'/'intermedia'/'base') for each timestamp."""
    return np.array([classify_period(ts) for ts in index])


def simulate_dispatch(
    demand_kw: pd.Series,
    solar_kw: pd.Series | None = None,
    *,
    capacity_kwh: float,
    power_kw: float,
    roundtrip_pct: float = 95.0,
    periods: np.ndarray | None = None,
    solar_only_charge: bool = True,
    discharge_hours: tuple[int, ...] | None = None,
    discharge_periods: tuple[str, ...] = ("punta",),
    discharge_threshold_kw: float | None = None,
    charge_periods: tuple[str, ...] = ("base",),
    init_soc_frac: float = 0.0,
) -> dict:
    """
    Greedy battery dispatch optimised for GDMTH peak shaving.

    Strategy, applied hour by hour:
      1. Charge from PV surplus (solar > demand) — free energy.
      2. During the discharge window, discharge to shave demand. If a
         *discharge_threshold_kw* (umbral) is given, only the load above that
         level is shaved (target ceiling); otherwise the battery discharges as
         much as it can.
      3. If *solar_only_charge* is False, recharge from the grid during the cheap
         Base period to be ready for the next discharge window.

    Round-trip efficiency is split symmetrically across charge and discharge
    (one-way efficiency = sqrt(roundtrip)).

    Parameters
    ----------
    demand_kw : hourly demand (kW), DatetimeIndex
    solar_kw  : hourly PV generation (kW). None ⇒ no solar.
    capacity_kwh : usable battery capacity (kWh).
    power_kw  : max charge/discharge power (kW).
    roundtrip_pct : round-trip efficiency (%).
    periods   : optional pre-computed period array (see classify_periods) to skip
        re-classifying timestamps when sweeping many configurations.
    solar_only_charge : if True (default) the battery charges ONLY from PV surplus.
    discharge_hours : explicit set/tuple of hours-of-day (0–23) when discharge is
        allowed. When given it overrides *discharge_periods*.
    discharge_periods : CFE periods used as the discharge window when
        *discharge_hours* is None.
    discharge_threshold_kw : umbral (kW). Only demand above this level is shaved.
        None ⇒ shave as much as possible.

    Returns dict of Series: net_after (grid kW after battery), soc (kWh),
    charge_solar_kw, charge_grid_kw, charge_kw, discharge_kw.
    """
    idx = demand_kw.index
    d = np.asarray(demand_kw.values, dtype=float)
    if solar_kw is not None:
        s = np.asarray(solar_kw.reindex(idx, fill_value=0.0).values, dtype=float)
    else:
        s = np.zeros(len(idx))

    if periods is None:
        periods = classify_periods(idx)
    else:
        periods = np.asarray(periods)
    hours = np.asarray(idx.hour)

    eff = (max(roundtrip_pct, 1.0) / 100.0) ** 0.5  # one-way efficiency
    n = len(idx)
    post = np.empty(n)
    soc_arr = np.empty(n)
    chg_solar = np.zeros(n)
    chg_grid = np.zeros(n)
    dis = np.zeros(n)

    dis_set = set(discharge_periods)
    chg_set = set(charge_periods)
    dh = set(int(h) for h in discharge_hours) if discharge_hours is not None else None
    threshold = discharge_threshold_kw
    soc = init_soc_frac * capacity_kwh

    for i in range(n):
        gross = d[i] - s[i]
        load = gross if gross > 0.0 else 0.0
        surplus = -gross if gross < 0.0 else 0.0
        p = periods[i]
        h = hours[i]

        if capacity_kwh > 0.0:
            # 1) Charge from PV surplus (free)
            if surplus > 0.0 and soc < capacity_kwh:
                room_in = (capacity_kwh - soc) / eff
                c = min(surplus, power_kw, room_in)
                soc += c * eff
                chg_solar[i] += c

            # 2) Discharge inside the chosen window, down to the umbral if set
            in_window = (h in dh) if dh is not None else (p in dis_set)
            if in_window and load > 0.0 and soc > 0.0:
                want = (load - threshold) if threshold is not None else load
                if want > 0.0:
                    served = min(power_kw, want, soc * eff)
                    if served > 0.0:
                        soc -= served / eff
                        load -= served
                        dis[i] += served
            # 3) Optional grid recharge during Base (only if not solar-only)
            elif (not solar_only_charge) and surplus == 0.0 and p in chg_set and soc < capacity_kwh:
                room_in = (capacity_kwh - soc) / eff
                c = min(power_kw, room_in)
                soc += c * eff
                load += c
                chg_grid[i] += c

        post[i] = load
        soc_arr[i] = soc

    return {
        "net_after": pd.Series(post, index=idx, name="net_after"),
        "soc": pd.Series(soc_arr, index=idx, name="soc"),
        "charge_solar_kw": pd.Series(chg_solar, index=idx, name="charge_solar_kw"),
        "charge_grid_kw": pd.Series(chg_grid, index=idx, name="charge_grid_kw"),
        "charge_kw": pd.Series(chg_solar + chg_grid, index=idx, name="charge_kw"),
        "discharge_kw": pd.Series(dis, index=idx, name="discharge_kw"),
    }


def _dispatch_kwargs(cfg: dict) -> dict:
    """Extract the simulate_dispatch keyword options carried inside a config dict."""
    return dict(
        capacity_kwh=cfg["capacity_kwh"],
        power_kw=cfg["power_kw"],
        roundtrip_pct=cfg.get("roundtrip_pct", 95.0),
        solar_only_charge=cfg.get("solar_only_charge", True),
        discharge_hours=cfg.get("discharge_hours"),
        discharge_threshold_kw=cfg.get("discharge_threshold_kw"),
    )


def dispatch_net(demand_df: pd.DataFrame, solar_kw: pd.Series | None, cfg: dict) -> pd.Series:
    """Return only the post-battery grid demand (kW) for the given config."""
    sim = simulate_dispatch(demand_df["demand"], solar_kw, **_dispatch_kwargs(cfg))
    return sim["net_after"]


def evaluate(
    calc: GDMTHCalculator,
    demand_df: pd.DataFrame,
    solar_kw: pd.Series | None,
    cfg: dict,
    periods: np.ndarray | None = None,
) -> dict:
    """
    Dispatch a battery config and compute the resulting monthly GDMTH bills.

    Returns dict with: sim, net_after, monthly (list of bill dicts), annual.
    """
    demand_series = demand_df["demand"]
    if solar_kw is None:
        solar_kw = pd.Series(0.0, index=demand_series.index)

    sim = simulate_dispatch(demand_series, solar_kw, periods=periods, **_dispatch_kwargs(cfg))
    net_after = sim["net_after"]

    monthly = []
    for m in sorted(demand_series.groupby(demand_series.index.month).groups.keys()):
        mask = demand_series.index.month == m
        r = calc.compute_bill(
            demand_series[mask],
            solar_kw=solar_kw[mask],
            final_net_kw=net_after[mask],
        )
        if r:
            monthly.append(r)

    annual = calc.annual_savings(monthly)
    return {"sim": sim, "net_after": net_after, "monthly": monthly, "annual": annual}


def optimize_units(
    calc: GDMTHCalculator,
    demand_df: pd.DataFrame,
    solar_kw: pd.Series | None,
    battery: dict,
    *,
    max_units: int,
    usd_mxn: float,
    install_factor_pct: float = 20.0,
    project_life: int = 25,
    inflation_pct: float = 5.0,
    discount_pct: float = 10.0,
    solar_only_charge: bool = True,
    discharge_hours: tuple[int, ...] | None = None,
    discharge_threshold_kw: float | None = None,
) -> dict:
    """
    Sweep 0..max_units battery units and rank configurations by the *incremental*
    net present value the battery adds over the solar-only baseline (0 units).

    The marginal annual cash flow of a battery is the extra GDMTH saving it
    produces beyond what solar alone already saves. CAPEX is the battery cost
    (units × nominal kWh × $/kWh, plus installation factor).

    Returns dict: rows (one per unit count), best (the max-NPV row).
    """
    periods = classify_periods(demand_df.index)
    inflation = inflation_pct / 100.0
    discount = discount_pct / 100.0
    years = range(1, project_life + 1)

    rows = []
    base_savings = None
    for n in range(0, max_units + 1):
        cfg = {
            "capacity_kwh": n * battery["usable_kwh"],
            "power_kw": n * battery["power_kw"],
            "roundtrip_pct": battery["roundtrip_efficiency_pct"],
            "solar_only_charge": solar_only_charge,
            "discharge_hours": discharge_hours,
            "discharge_threshold_kw": discharge_threshold_kw,
        }
        ev = evaluate(calc, demand_df, solar_kw, cfg, periods=periods)
        total_savings = ev["annual"].get("savings_mxn", 0.0)
        if base_savings is None:
            base_savings = total_savings  # n = 0 → solar-only baseline

        incr_savings = total_savings - base_savings  # battery's marginal year-1 saving

        capex_usd = n * battery["kwh"] * battery["usd_per_kwh"] * (1 + install_factor_pct / 100.0)
        capex_mxn = capex_usd * usd_mxn

        npv = -capex_mxn + sum(
            incr_savings * ((1 + inflation) ** (y - 1)) / ((1 + discount) ** y) for y in years
        )
        payback = capex_mxn / incr_savings if incr_savings > 0 else float("inf")

        rows.append({
            "units": n,
            "capacity_kwh": cfg["capacity_kwh"],
            "power_kw": cfg["power_kw"],
            "capex_usd": capex_usd,
            "capex_mxn": capex_mxn,
            "incr_savings_mxn": incr_savings,
            "total_savings_mxn": total_savings,
            "npv_mxn": npv,
            "payback_years": payback,
        })

    best = max(rows, key=lambda r: r["npv_mxn"])
    return {"rows": rows, "best": best}
