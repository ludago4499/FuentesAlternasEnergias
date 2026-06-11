"""Unit tests for core.pv_finance (degradation/O&M cashflows, LCOE, trade-offs)."""

import math

import pytest

from core.pv_finance import (
    annual_net_benefits,
    series_cashflows,
    pv_cashflows,
    cashflow_irr,
    lcoe_mxn_kwh,
    cooling_vs_extra_panels,
    investment_metrics,
)
from core.resilience import continuity_cashflows, investment_irr


# ── annual_net_benefits ───────────────────────────────────────────────────────

def test_benefits_no_degradation_no_om_matches_inflation_growth():
    b = annual_net_benefits(1000.0, 3, inflation_pct=10.0)
    assert b == pytest.approx([1000.0, 1100.0, 1210.0])


def test_benefits_degradation_reduces_each_year():
    flat = annual_net_benefits(1000.0, 5, inflation_pct=0.0)
    degr = annual_net_benefits(1000.0, 5, inflation_pct=0.0, degradation_pct=0.5)
    assert degr[0] == pytest.approx(1000.0)
    assert all(d < f for d, f in zip(degr[1:], flat[1:]))
    assert degr[4] == pytest.approx(1000.0 * 0.995 ** 4)


def test_benefits_om_subtracted_and_inflation_indexed():
    b = annual_net_benefits(1000.0, 2, inflation_pct=10.0, om_annual_mxn=100.0)
    assert b == pytest.approx([900.0, 990.0])


# ── series / pv cashflows ─────────────────────────────────────────────────────

def test_pv_cashflows_zero_degr_om_matches_continuity():
    """With degradation=0 and O&M=0 the model must reproduce the legacy
    continuity_cashflows NPV exactly."""
    legacy = continuity_cashflows(100_000.0, 20_000.0, 10, 5.0, 10.0)
    new = pv_cashflows(100_000.0, 20_000.0, 10, 5.0, 10.0,
                       degradation_pct=0.0, om_annual_mxn=0.0)
    assert new["npv_mxn"] == pytest.approx(legacy["npv_mxn"])
    assert new["monthly_pv_flows"] == pytest.approx(legacy["monthly_pv_flows"])


def test_degradation_lowers_npv():
    base = pv_cashflows(100_000.0, 20_000.0, 10, 5.0, 10.0, degradation_pct=0.0)
    degraded = pv_cashflows(100_000.0, 20_000.0, 10, 5.0, 10.0, degradation_pct=1.0)
    assert degraded["npv_mxn"] < base["npv_mxn"]


def test_monthly_bars_sum_to_npv():
    cf = pv_cashflows(50_000.0, 12_000.0, 8, 4.0, 9.0, 0.5, 600.0)
    assert sum(cf["monthly_pv_flows"]) == pytest.approx(cf["npv_mxn"])
    assert cf["cumulative_pv"][-1] == pytest.approx(cf["npv_mxn"])
    assert len(cf["monthly_pv_flows"]) == 1 + 8 * 12


def test_payback_interpolated_nominal():
    # 10k capex, flat 4k/yr → payback exactly 2.5 yr
    cf = pv_cashflows(10_000.0, 4_000.0, 10, 0.0, 10.0, degradation_pct=0.0)
    assert cf["payback_years"] == pytest.approx(2.5)


def test_payback_infinite_when_no_benefit():
    cf = series_cashflows(10_000.0, [0.0] * 5, 10.0)
    assert cf["payback_years"] == float("inf")


# ── IRR ───────────────────────────────────────────────────────────────────────

def test_cashflow_irr_matches_legacy_investment_irr():
    benefits = annual_net_benefits(20_000.0, 10, inflation_pct=5.0)
    irr_new = cashflow_irr(100_000.0, benefits)
    irr_old = investment_irr(100_000.0, 20_000.0, 10, 5.0)
    assert irr_new == pytest.approx(irr_old, abs=1e-6)


def test_cashflow_irr_nan_when_never_profitable():
    assert math.isnan(cashflow_irr(100_000.0, [1.0] * 5))


def test_cashflow_irr_inf_above_bracket():
    assert cashflow_irr(100.0, [100_000.0] * 5) == float("inf")


# ── LCOE ──────────────────────────────────────────────────────────────────────

def test_lcoe_basic_sanity():
    lcoe = lcoe_mxn_kwh(100_000.0, 20_000.0, project_life_years=25,
                        discount_pct=10.0, degradation_pct=0.5)
    assert 0.0 < lcoe < 2.0  # cheap solar vs CFE ~2.67


def test_lcoe_increases_with_om_and_degradation():
    base = lcoe_mxn_kwh(100_000.0, 20_000.0, 25, 10.0, 0.0, 0.0)
    worse = lcoe_mxn_kwh(100_000.0, 20_000.0, 25, 10.0, 1.0, 2_000.0)
    assert worse > base


def test_lcoe_nan_without_generation():
    assert math.isnan(lcoe_mxn_kwh(100_000.0, 0.0))


# ── Trade-offs ────────────────────────────────────────────────────────────────

def test_cooling_tradeoff_panels_win_when_cooling_expensive():
    t = cooling_vs_extra_panels(
        annual_gen_kwh=50_000.0, temp_loss_pct=5.0, cooling_recovery_pct=60.0,
        cooling_capex_mxn=1_000_000.0, cooling_opex_mxn_yr=50_000.0,
        panel_kwh_yr=900.0, panel_capex_mxn=5_000.0, energy_value_mxn_kwh=2.67,
    )
    assert t["winner"] == "panels"
    assert t["recovered_kwh_yr"] == pytest.approx(1_500.0)
    assert t["extra_panels"] == 2  # ceil(1500/900)


def test_cooling_tradeoff_cooling_wins_when_cheap():
    t = cooling_vs_extra_panels(
        annual_gen_kwh=50_000.0, temp_loss_pct=8.0, cooling_recovery_pct=80.0,
        cooling_capex_mxn=2_000.0, cooling_opex_mxn_yr=0.0,
        panel_kwh_yr=900.0, panel_capex_mxn=20_000.0, energy_value_mxn_kwh=2.67,
    )
    assert t["winner"] == "cooling"


def test_investment_metrics_bundle():
    m = investment_metrics(100_000.0, 20_000.0, 10, 5.0, 10.0)
    legacy = continuity_cashflows(100_000.0, 20_000.0, 10, 5.0, 10.0)
    assert m["npv_mxn"] == pytest.approx(legacy["npv_mxn"])
    assert m["npv_per_peso"] == pytest.approx(m["npv_mxn"] / 100_000.0)
    assert m["irr"] > 0
