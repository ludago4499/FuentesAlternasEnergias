"""
Acceptance tests for the GDMTO calculator, calibrated against the real
Streger S.A. receipt (Coatepec, Ver., Mayo 2026): 9,520 kWh, 80 kW, FP 89.89%.
"""

import math

import pytest

from core.gdmto import GDMTOCalculator, fp_adjustment_pct, power_factor_from_meter

KWH = 9520.0
KW = 80.0
FP = 89.89


@pytest.fixture(scope="module")
def receipt_bill():
    calc = GDMTOCalculator()
    return calc.compute_bill(kwh=KWH, kw_max=KW, fp_pct=FP)


def test_energy_total(receipt_bill):
    assert receipt_bill["energy_total_mxn"] == pytest.approx(12_521.75, abs=0.5)


def test_demand_total(receipt_bill):
    assert receipt_bill["demand_total_mxn"] == pytest.approx(11_813.86, abs=0.5)


def test_mem_total(receipt_bill):
    assert receipt_bill["mem_total_mxn"] == pytest.approx(24_984.44, abs=0.5)


def test_bt_charge(receipt_bill):
    assert receipt_bill["bt_charge_mxn"] == pytest.approx(499.69, abs=0.1)


def test_fp_pct_rounded_to_one_decimal(receipt_bill):
    # CFE rounds the recargo % to one decimal — must be exactly 0.1 for FP 89.89
    assert receipt_bill["fp_pct_applied"] == 0.1


def test_fp_charge(receipt_bill):
    assert receipt_bill["fp_charge_mxn"] == pytest.approx(25.48, abs=0.05)


def test_subtotal(receipt_bill):
    assert receipt_bill["subtotal_mxn"] == pytest.approx(25_509.62, abs=0.5)


def test_iva(receipt_bill):
    assert receipt_bill["iva_mxn"] == pytest.approx(4_081.54, abs=0.1)


def test_total(receipt_bill):
    assert receipt_bill["total_mxn"] == pytest.approx(29_591.16, abs=1.0)


def test_fp_from_meter_readings():
    # FP = kWh / sqrt(kWh² + kvarh²) with the receipt's kvarh
    fp = power_factor_from_meter(KWH, 4640.0)
    assert fp == pytest.approx(89.89, abs=0.05)


# ── Component itemization & solar behavior ────────────────────────────────────

def test_energy_components_itemized(receipt_bill):
    parts = ["energia", "transmision", "cenace", "scnmem"]
    total = sum(receipt_bill[f"energy_{p}_mxn"] for p in parts)
    assert total == pytest.approx(receipt_bill["energy_total_mxn"], abs=1e-6)
    assert receipt_bill["energy_energia_mxn"] == pytest.approx(KWH * 1.120709, abs=1e-4)


def test_demand_components_itemized(receipt_bill):
    total = receipt_bill["demand_capacidad_mxn"] + receipt_bill["demand_distribucion_mxn"]
    assert total == pytest.approx(receipt_bill["demand_total_mxn"], abs=1e-6)


def test_orig_equals_new_without_solar(receipt_bill):
    assert receipt_bill["orig_total_mxn"] == pytest.approx(receipt_bill["total_mxn"])
    assert receipt_bill["savings_mxn"] == pytest.approx(0.0, abs=1e-9)


def test_solar_reduces_energy_not_demand():
    calc = GDMTOCalculator()
    r = calc.compute_bill(kwh=KWH, kw_max=KW, fp_pct=FP, solar_kwh=3000.0)
    assert r["net_kwh"] == pytest.approx(KWH - 3000.0)
    assert r["billed_kw"] == pytest.approx(KW)          # demand untouched by default
    assert r["energy_total_mxn"] < r["orig_energy_total_mxn"]
    assert r["demand_total_mxn"] == pytest.approx(r["orig_demand_total_mxn"])
    assert r["savings_mxn"] > 0


def test_solar_clamps_at_zero_net():
    calc = GDMTOCalculator()
    r = calc.compute_bill(kwh=1000.0, kw_max=KW, fp_pct=FP, solar_kwh=5000.0)
    assert r["net_kwh"] == 0.0
    assert r["energy_total_mxn"] == pytest.approx(0.0)
    # Fixed + demand charges remain even at zero net energy
    assert r["total_mxn"] > 0


def test_demand_reduction_pct():
    calc = GDMTOCalculator()
    r = calc.compute_bill(kwh=KWH, kw_max=KW, fp_pct=FP, demand_reduction_pct=25.0)
    assert r["billed_kw"] == pytest.approx(60.0)
    assert r["demand_total_mxn"] == pytest.approx(0.75 * r["orig_demand_total_mxn"])


# ── FP adjustment edge cases ──────────────────────────────────────────────────

def test_fp_bonus_above_90():
    # FP 95 → bonus (1/4)(1 − 90/95)·100 = 1.3158 → rounded 1.3, negative
    assert fp_adjustment_pct(95.0) == pytest.approx(-1.3)


def test_fp_bonus_capped_at_2_5():
    assert fp_adjustment_pct(100.0) == pytest.approx(-2.5)


def test_fp_recargo_capped_at_120():
    assert fp_adjustment_pct(20.0) == 120.0
    assert fp_adjustment_pct(0.0) == 120.0


def test_fp_exactly_90_no_adjustment():
    assert fp_adjustment_pct(90.0) == 0.0


# ── Annual projection ─────────────────────────────────────────────────────────

def test_annual_projection_streger_year():
    calc = GDMTOCalculator()
    rows = [{"mes": m, "kwh": KWH, "demanda_kw": KW, "fp_pct": FP} for m in range(1, 13)]
    proj = calc.annual_projection(rows, solar_monthly_kwh=[0.0] * 12)
    assert len(proj["monthly"]) == 12
    assert proj["monthly"][0]["month"] == 1
    assert proj["annual"]["orig_total_mxn"] == pytest.approx(12 * 29_591.16, abs=12.0)
    assert proj["annual"]["savings_mxn"] == pytest.approx(0.0, abs=1e-6)


def test_annual_projection_with_solar_and_string_months():
    calc = GDMTOCalculator()
    rows = [{"mes": mes, "kwh": KWH, "demanda_kw": KW, "fp_pct": FP}
            for mes in ["Ene", "Feb", "Mar"]]
    proj = calc.annual_projection(rows, solar_monthly_kwh=[1000.0, 1000.0, 1000.0])
    assert [b["month"] for b in proj["monthly"]] == [1, 2, 3]
    assert proj["annual"]["solar_generated_kwh"] == pytest.approx(3000.0)
    assert proj["annual"]["savings_mxn"] > 0
    assert proj["annual"]["savings_demand_mxn"] == pytest.approx(0.0, abs=1e-9)


def test_payback_period():
    calc = GDMTOCalculator()
    assert calc.payback_period(100_000.0, 25_000.0) == pytest.approx(4.0)
    assert math.isinf(calc.payback_period(100_000.0, 0.0))
