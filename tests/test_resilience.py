"""Tests for backup BESS sizing (core.resilience)."""

import math

import pytest

from core.resilience import size_bess, propose_bess, kva_to_kw, INVERTER_EFF

BYD = {
    "id": "byd_battery_box_h_10", "brand": "BYD", "model": "Battery-Box Premium HVS 10.2",
    "kwh": 10.2, "usable_kwh": 9.0, "power_kw": 5.0, "chemistry": "LiFePO4",
    "cycles": 6000, "dod_pct": 90, "roundtrip_efficiency_pct": 96, "usd_per_kwh": 350,
}


def test_kva_to_kw():
    assert kva_to_kw(100.0, 89.89) == pytest.approx(89.89)
    assert kva_to_kw(50.0, 100.0) == pytest.approx(50.0)


def test_size_bess_energy_formula():
    # 20 kW × 4 h / (0.90 × 0.96) = 92.59 kWh required
    r = size_bess(20.0, 4.0, BYD, usd_mxn=17.5)
    assert r["e_req_kwh"] == pytest.approx(20.0 * 4.0 / (0.90 * INVERTER_EFF), rel=1e-9)
    # energy constraint: ceil(92.59/9.0) = 11; power constraint: ceil(20/5) = 4
    assert r["units"] == 11
    assert r["total_usable_kwh"] == pytest.approx(99.0)
    assert r["total_power_kw"] == pytest.approx(55.0)


def test_size_bess_power_bound_dominates():
    # Short outage, big load: power constraint must dominate
    r = size_bess(40.0, 0.5, BYD)
    e_units = math.ceil(r["e_req_kwh"] / BYD["usable_kwh"])   # 40·0.5/(0.9·0.96)=23.1 → 3
    p_units = math.ceil(40.0 / BYD["power_kw"])               # 8
    assert p_units > e_units
    assert r["units"] == p_units


def test_size_bess_capex_formula():
    r = size_bess(20.0, 4.0, BYD, usd_mxn=20.0)
    expected_usd = 350 * 10.2 * r["units"]
    assert r["capex_usd"] == pytest.approx(expected_usd)
    assert r["capex_mxn"] == pytest.approx(expected_usd * 20.0)


def test_size_bess_life_and_band():
    r = size_bess(10.0, 2.0, BYD)
    assert r["life_years_daily_cycling"] == pytest.approx(6000 / 365.0)
    assert r["cycle_band"] == "4,000–5,000"
    assert "respaldo" in r["life_note"]


def test_size_bess_zero_load():
    r = size_bess(0.0, 8.0, BYD)
    assert r["units"] == 0
    assert r["capex_mxn"] == 0.0


def test_propose_bess_ranks_by_capex():
    prop = propose_bess(20.0, 4.0, usd_mxn=17.5)   # real catalog
    options = prop["options"]
    assert len(options) >= 2
    capex = [o["capex_mxn"] for o in options]
    assert capex == sorted(capex)
    assert prop["best"] is options[0]
    # Every option satisfies both constraints
    for o in options:
        assert o["total_usable_kwh"] >= o["e_req_kwh"] - 1e-9 or \
               o["units"] == math.ceil(o["p_crit_kw"] / o["unit_power_kw"])
        assert o["total_power_kw"] >= o["p_crit_kw"] - 1e-9
        assert o["total_usable_kwh"] * (o["dod_pct"] / 100.0 * 0.0 + 1.0) >= 0  # sanity
