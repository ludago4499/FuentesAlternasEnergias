"""
Automated smoke test of the progressive GDMTO flow (S1→S4) using Streamlit's
AppTest: default Coatepec site, Streger receipt values, receipt totals in the
"Desglose formal" view (sin solar) and reasonable savings with 20 × 580 W
panels. Also covers the GDMTH branch guards on pages 5 and 6.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).parent.parent / "app"
ANNUAL_RECEIPT_TOTAL = 12 * 29_591.16   # 12 identical Streger months


def _main_app() -> AppTest:
    return AppTest.from_file(str(APP_DIR / "main.py"), default_timeout=120)


def _metric_value(at: AppTest, label: str) -> str:
    for m in at.metric:
        if m.label == label:
            return m.value
    raise AssertionError(f"metric '{label}' not found; got {[m.label for m in at.metric]}")


def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", "").strip())


def test_s1_vista_rapida_defaults():
    at = _main_app().run()
    assert not at.exception
    assert at.session_state["tariff_mode"] == "GDMTO"
    assert at.session_state["city"] == "Coatepec, Ver."
    assert at.session_state["lat"] == pytest.approx(19.452)
    assert at.session_state["lon"] == pytest.approx(-96.962)
    # Optimal tilt default = round(abs(lat)) = 19
    assert at.session_state["tilt"] == pytest.approx(19.0)
    assert at.session_state["azimuth"] == pytest.approx(0.0)
    # Quick per-panel estimate rendered
    assert any("Generación por panel" == m.label for m in at.metric)


def test_s2_desglose_formal_reproduces_receipt_sin_solar():
    at = _main_app().run()
    at.toggle(key="s2_enabled").set_value(True).run()
    assert not at.exception
    # Mode A defaults = Streger receipt; 0 panels = sin solar
    at.radio(key="s2_eval_mode").set_value("Desglose formal GDMTO").run()
    assert not at.exception
    sin_fv = _money(_metric_value(at, "Factura anual sin FV"))
    con_fv = _money(_metric_value(at, "Factura anual con FV"))
    assert sin_fv == pytest.approx(ANNUAL_RECEIPT_TOTAL, abs=12.0)
    assert con_fv == pytest.approx(sin_fv, abs=0.01)            # no solar → identical
    assert at.session_state["ahorro_fv_anual"] == pytest.approx(0.0, abs=1e-6)


def test_s2_savings_with_20_panels():
    at = _main_app().run()
    at.toggle(key="s2_enabled").set_value(True).run()
    at.number_input(key="s2_n_panels_input").set_value(20).run()
    at.radio(key="s2_eval_mode").set_value("Desglose formal GDMTO").run()
    assert not at.exception
    ahorro = at.session_state["ahorro_fv_anual"]
    # ~19 MWh/yr of PV against a $355k bill → tens of thousands of MXN
    assert 10_000 < ahorro < 120_000
    assert at.session_state["s2_system_kwp"] == pytest.approx(11.6)
    # Express module also works and roughly agrees in order of magnitude
    at.radio(key="s2_eval_mode").set_value("Módulo Express").run()
    assert not at.exception
    pago_actual = _money(_metric_value(at, "Pago anual actual"))
    assert pago_actual == pytest.approx(12 * 9520 * 2.67, abs=1.0)


def test_s3_resilience_proposal():
    at = _main_app().run()
    at.toggle(key="s3_enabled").set_value(True).run()
    assert not at.exception
    assert at.session_state["backup_hours"] == 4          # slider default
    assert at.session_state["critical_load_kw"] == pytest.approx(20.0)
    bess = at.session_state["bess_proposal"]
    assert bess is not None and bess["units"] >= 1
    # Both constraints met
    assert bess["total_power_kw"] >= 20.0
    assert bess["total_usable_kwh"] >= bess["e_req_kwh"] - 1e-6
    # kVA path: 25 kVA × 89.89% ≈ 22.47 kW
    at.selectbox(key="s3_load_unit").set_value("kVA").run()
    at.number_input(key="s3_load").set_value(25.0).run()
    assert not at.exception
    assert at.session_state["critical_load_kw"] == pytest.approx(25.0 * 0.8989, rel=1e-3)


def test_s4_continuity_evaluation_and_quote_override():
    at = _main_app().run()
    at.toggle(key="s3_enabled").set_value(True).run()
    at.checkbox(key="s4_enabled").set_value(True).run()
    assert not at.exception
    at.number_input(key="s4_outage").set_value(80_000.0).run()
    assert not at.exception
    assert at.session_state["outage_cost_annual"] == pytest.approx(80_000.0)
    labels = [m.label for m in at.metric]
    assert "Payback — Sin FV" in labels and "VPN — Con FV" in labels
    catalog_capex = at.session_state["bess_proposal"]["capex_mxn"]
    sin_fv_payback = float(_metric_value(at, "Payback — Sin FV").split()[0])
    assert sin_fv_payback == pytest.approx(catalog_capex / 80_000.0, abs=0.06)
    # Commercial quote overrides the catalog CAPEX
    at.number_input(key="s4_quote").set_value(40_000.0).run()
    assert not at.exception
    quoted_payback = float(_metric_value(at, "Payback — Sin FV").split()[0])
    assert quoted_payback == pytest.approx(40_000.0 / 80_000.0, abs=0.06)


def test_gdmth_mode_stops_main_flow():
    at = _main_app().run()
    at.radio(key="tariff_mode").set_value("GDMTH").run()
    assert not at.exception
    # The GDMTO sections must not render in GDMTH mode
    assert all(t.label != "Ingresar mi consumo CFE" for t in at.toggle)


def test_baterias_warns_and_stops_under_gdmto():
    at = AppTest.from_file(str(APP_DIR / "pages" / "6_baterias.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert len(at.info) >= 1          # the GDMTO redirect notice


def test_baterias_gdmth_path_reaches_demand_warning():
    # Baterías still requires an explicit demand curve and warns if missing.
    at = AppTest.from_file(str(APP_DIR / "pages" / "6_baterias.py"), default_timeout=60)
    at.session_state["tariff_mode"] = "GDMTH"
    at.run()
    assert not at.exception
    assert len(at.warning) >= 1       # "carga la demanda" guard


def test_continuity_page_requires_battery_quote():
    # The new Continuity page (5_economics.py) needs a battery quote from
    # Sección 3 / página Baterías; with none it warns and stops cleanly.
    at = AppTest.from_file(str(APP_DIR / "pages" / "5_economics.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert len(at.warning) >= 1       # "no hay cotización de baterías" guard


def test_continuity_page_computes_roi_with_quote_and_outage():
    # With a battery proposal and an outage cost it produces the ROI metrics
    # and the cashflow chart without errors.
    at = AppTest.from_file(str(APP_DIR / "pages" / "5_economics.py"), default_timeout=60)
    at.session_state["bess_proposal"] = {
        "capex_mxn": 500_000.0, "units": 4, "brand": "Test", "model": "BESS",
        "total_usable_kwh": 40.0,
    }
    at.session_state["outage_cost_annual"] = 120_000.0
    at.run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("ROI" in l for l in labels)
    assert any("VPN" in l for l in labels)


def test_config_page_with_residential_tool():
    at = AppTest.from_file(str(APP_DIR / "pages" / "2_config.py"), default_timeout=60)
    at.run()
    assert not at.exception
    # Residential expander defaults: 900 kWh on 1C → within DAC limit (1,700)
    assert any("DAC" in s.value for s in at.success)
