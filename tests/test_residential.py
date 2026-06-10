"""Tests for the residential 1A–1F block accumulator and DAC flag."""

import pytest

from core.residential import split_blocks, is_dac, classify, LIMITS, TARIFFS


def test_table_matches_spec():
    assert TARIFFS == ["1A", "1B", "1C", "1D", "1E", "1F"]
    assert LIMITS["1A"] == {"basico": 150, "intermedio": 150, "verano1": 200,
                            "verano2": None, "dac_kwh_bimestre": 350}
    assert LIMITS["1F"] == {"basico": 150, "intermedio": 450, "verano1": 1800,
                            "verano2": 2600, "dac_kwh_bimestre": 5000}


def test_blocks_fill_in_order_1b():
    # 1B: 150 + 250 + 250 + 200 = 850 → 1,000 kWh leaves 150 in excedente
    b = split_blocks(1000.0, "1B")
    assert b == {"basico": 150.0, "intermedio": 250.0, "verano1": 250.0,
                 "verano2": 200.0, "excedente": 150.0}


def test_partial_fill_stops_midblock():
    b = split_blocks(300.0, "1C")
    assert b["basico"] == 150.0
    assert b["intermedio"] == 150.0          # only half of the 250 cap
    assert b["verano1"] == 0.0
    assert b["excedente"] == 0.0


def test_1a_has_no_verano2():
    b = split_blocks(600.0, "1A")
    assert b == {"basico": 150.0, "intermedio": 150.0, "verano1": 200.0,
                 "verano2": 0.0, "excedente": 100.0}


@pytest.mark.parametrize("tarifa", TARIFFS)
@pytest.mark.parametrize("kwh", [0.0, 120.0, 850.0, 3000.0, 7000.0])
def test_blocks_always_sum_to_input(tarifa, kwh):
    b = split_blocks(kwh, tarifa)
    assert sum(b.values()) == pytest.approx(kwh)
    assert all(v >= 0 for v in b.values())


def test_dac_threshold_is_strictly_greater():
    assert not is_dac(350.0, "1A")
    assert is_dac(350.1, "1A")
    assert not is_dac(5000.0, "1F")
    assert is_dac(5001.0, "1F")


def test_classify_bundle():
    r = classify(900.0, "1B")
    assert r["dac"] is True                  # 900 > 800
    assert r["dac_kwh_bimestre"] == 800
    assert r["blocks"]["excedente"] == pytest.approx(50.0)
    with pytest.raises(ValueError):
        classify(100.0, "1Z")
