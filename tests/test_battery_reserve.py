"""
Regression tests for the new reserve_kwh parameter of simulate_dispatch:
default 0 must keep GDMTH dispatch bit-for-bit identical, and a positive
reserve must floor the SoC during economic discharge.
"""

import numpy as np
import pandas as pd
import pytest

from core.battery import simulate_dispatch


def _scenario():
    """Two days: flat 100 kW load, midday PV surplus, evening discharge window."""
    idx = pd.date_range("2024-06-03", periods=48, freq="h", tz="America/Monterrey")
    demand = pd.Series(100.0, index=idx, name="demand")
    solar = pd.Series(0.0, index=idx)
    solar[(idx.hour >= 10) & (idx.hour <= 15)] = 200.0   # 100 kW surplus those hours
    return demand, solar


KW = dict(capacity_kwh=50.0, power_kw=25.0, roundtrip_pct=100.0,
          solar_only_charge=True, discharge_hours=(18, 19, 20, 21))


def test_reserve_default_identical_to_legacy():
    demand, solar = _scenario()
    base = simulate_dispatch(demand, solar, **KW)
    explicit = simulate_dispatch(demand, solar, **KW, reserve_kwh=0.0)
    for key in ("net_after", "soc", "charge_kw", "discharge_kw"):
        assert np.allclose(base[key].values, explicit[key].values), key


def test_reserve_floors_soc_during_discharge():
    demand, solar = _scenario()
    reserve = 20.0
    sim = simulate_dispatch(demand, solar, **KW, reserve_kwh=reserve)
    idx = demand.index
    # After the first full charge, discharge must stop at the reserve floor
    after_charge = sim["soc"][idx.hour >= 16]
    assert float(after_charge.min()) >= reserve - 1e-9
    # It still discharges down to exactly the reserve on day 1 (soc 50 → 20)
    day1_window = sim["discharge_kw"][(idx.day == 3) & (idx.hour >= 18) & (idx.hour <= 21)]
    assert float(day1_window.sum()) == pytest.approx(30.0)


def test_reserve_reduces_total_discharge():
    demand, solar = _scenario()
    free = simulate_dispatch(demand, solar, **KW)
    held = simulate_dispatch(demand, solar, **KW, reserve_kwh=20.0)
    assert float(held["discharge_kw"].sum()) < float(free["discharge_kw"].sum())
    # Less discharge ⇒ grid demand can only be equal or higher
    assert (held["net_after"].values >= free["net_after"].values - 1e-9).all()


def test_full_reserve_blocks_discharge_entirely():
    demand, solar = _scenario()
    sim = simulate_dispatch(demand, solar, **KW, reserve_kwh=KW["capacity_kwh"])
    assert float(sim["discharge_kw"].sum()) == 0.0
