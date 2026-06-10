"""Tests for the continuity (Sección 4) present-value cashflow helper."""

import math

import pytest

from core.resilience import continuity_cashflows


def test_npv_matches_optimize_units_pattern():
    capex, benefit, life, infl, disc = 200_000.0, 60_000.0, 10, 5.0, 10.0
    cf = continuity_cashflows(capex, benefit, life, infl, disc)
    expected = -capex + sum(
        benefit * ((1 + 0.05) ** (y - 1)) / ((1 + 0.10) ** y) for y in range(1, life + 1)
    )
    assert cf["npv_mxn"] == pytest.approx(expected, rel=1e-12)


def test_monthly_flows_structure_and_sum():
    cf = continuity_cashflows(100_000.0, 30_000.0, 10, 5.0, 10.0)
    assert len(cf["monthly_pv_flows"]) == 10 * 12 + 1
    assert cf["months"][0] == 0
    assert cf["monthly_pv_flows"][0] == pytest.approx(-100_000.0)   # month-0 CAPEX
    # Monthly PV bars sum exactly to the NPV
    assert sum(cf["monthly_pv_flows"]) == pytest.approx(cf["npv_mxn"], rel=1e-12)
    assert cf["cumulative_pv"][-1] == pytest.approx(cf["npv_mxn"], rel=1e-9)


def test_each_year_spread_evenly():
    cf = continuity_cashflows(0.0, 12_000.0, 2, 0.0, 0.0)
    # No inflation/discount → each month = 12,000/12 = 1,000
    year1 = cf["monthly_pv_flows"][1:13]
    assert all(f == pytest.approx(1000.0) for f in year1)


def test_payback():
    cf = continuity_cashflows(120_000.0, 40_000.0, 10, 5.0, 10.0)
    assert cf["payback_years"] == pytest.approx(3.0)
    cf0 = continuity_cashflows(120_000.0, 0.0, 10, 5.0, 10.0)
    assert math.isinf(cf0["payback_years"])
    assert cf0["npv_mxn"] == pytest.approx(-120_000.0)
