"""
CFE residential tariffs 1A–1F: bimonthly consumption block accumulator and
DAC (Doméstica de Alto Consumo) threshold flag.

Each bimestre the consumption fills the blocks in order — Básico → Intermedio
→ Verano 1 → Verano 2 — up to each block's kWh limit; whatever remains is
billed as Excedente. A "—" (None) limit means the tariff has no such block.
All limits, including the DAC threshold, are kWh per bimestre.
"""

from __future__ import annotations

BLOCK_ORDER = ["basico", "intermedio", "verano1", "verano2"]

BLOCK_LABELS = {
    "basico": "Básico",
    "intermedio": "Intermedio",
    "verano1": "Verano 1",
    "verano2": "Verano 2",
    "excedente": "Excedente",
}

# kWh per bimestre: block limits and DAC threshold per tariff
LIMITS: dict[str, dict] = {
    "1A": {"basico": 150, "intermedio": 150, "verano1": 200, "verano2": None, "dac_kwh_bimestre": 350},
    "1B": {"basico": 150, "intermedio": 250, "verano1": 250, "verano2": 200, "dac_kwh_bimestre": 800},
    "1C": {"basico": 150, "intermedio": 250, "verano1": 300, "verano2": 300, "dac_kwh_bimestre": 1700},
    "1D": {"basico": 150, "intermedio": 250, "verano1": 450, "verano2": 400, "dac_kwh_bimestre": 2000},
    "1E": {"basico": 150, "intermedio": 350, "verano1": 600, "verano2": 600, "dac_kwh_bimestre": 5000},
    "1F": {"basico": 150, "intermedio": 450, "verano1": 1800, "verano2": 2600, "dac_kwh_bimestre": 5000},
}

TARIFFS = list(LIMITS.keys())


def split_blocks(kwh_bimestre: float, tarifa: str) -> dict[str, float]:
    """Fill the tariff's blocks in order with the bimonthly kWh; the remainder
    lands in 'excedente'. Returns kWh assigned to every block (0 if absent)."""
    limits = LIMITS[tarifa]
    remaining = max(float(kwh_bimestre), 0.0)
    out: dict[str, float] = {}
    for block in BLOCK_ORDER:
        cap = limits[block]
        if cap is None:
            out[block] = 0.0
            continue
        take = min(remaining, float(cap))
        out[block] = take
        remaining -= take
    out["excedente"] = remaining
    return out


def is_dac(kwh_bimestre: float, tarifa: str) -> bool:
    """True when the bimonthly consumption exceeds the tariff's DAC threshold."""
    return float(kwh_bimestre) > LIMITS[tarifa]["dac_kwh_bimestre"]


def classify(kwh_bimestre: float, tarifa: str) -> dict:
    """Blocks + DAC flag + threshold in a single result dict."""
    if tarifa not in LIMITS:
        raise ValueError(f"Tarifa residencial desconocida: {tarifa!r}. Opciones: {TARIFFS}")
    blocks = split_blocks(kwh_bimestre, tarifa)
    return {
        "tarifa": tarifa,
        "kwh_bimestre": float(kwh_bimestre),
        "blocks": blocks,
        "dac": is_dac(kwh_bimestre, tarifa),
        "dac_kwh_bimestre": LIMITS[tarifa]["dac_kwh_bimestre"],
    }
