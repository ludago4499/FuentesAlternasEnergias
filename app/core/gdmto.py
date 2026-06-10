"""
CFE GDMTO (Gran Demanda en Media Tensión Ordinaria) tariff calculator.

Unlike GDMTH, GDMTO has NO hourly periods: a single flat energy rate stack
(energía + transmisión + CENACE + SCnMEM), two demand charges (capacidad +
distribución) on the billed kW, a 2% low-tension loss surcharge, a power-factor
adjustment, and 16% IVA.

Calibrated against a real receipt: Streger S.A., Coatepec, Veracruz,
Mayo 2026 (31 days, multiplicador 80, 9,520 kWh, 80 kW, FP 89.89%).

Usage:
    from core.gdmto import GDMTOCalculator
    calc = GDMTOCalculator()
    bill = calc.compute_bill(kwh=9520, kw_max=80, fp_pct=89.89)
"""

from __future__ import annotations

import json
import math
from pathlib import Path

_TARIFF_PATH = Path(__file__).parent.parent / "data" / "tariff_gdmto_streger.json"

MONTH_ABBR_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                 "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def power_factor_from_meter(kwh: float, kvarh: float) -> float:
    """FP (%) = kWh / sqrt(kWh² + kvarh²) × 100, from billed meter readings."""
    if kwh <= 0:
        return 0.0
    return kwh / math.sqrt(kwh ** 2 + kvarh ** 2) * 100.0


def fp_adjustment_pct(fp_pct: float) -> float:
    """
    CFE power-factor adjustment percentage applied on (cargos + 2% BT).

    FP < 90 → recargo = (3/5)·(90/FP − 1)·100, capped at 120%.
    FP > 90 → bonificación = (1/4)·(1 − 90/FP)·100, capped at 2.5%
              (returned negative — it is a credit).
    CFE rounds the percentage to ONE decimal before applying it; this rounding
    is required to reproduce the printed receipt amounts.
    """
    if fp_pct <= 0:
        return 120.0
    if fp_pct < 90.0:
        pct = round((3.0 / 5.0) * (90.0 / fp_pct - 1.0) * 100.0, 1)
        return min(pct, 120.0)
    if fp_pct > 90.0:
        pct = round((1.0 / 4.0) * (1.0 - 90.0 / fp_pct) * 100.0, 1)
        return -min(pct, 2.5)
    return 0.0


class GDMTOCalculator:
    def __init__(self, tariff_path: str | Path | None = None):
        path = Path(tariff_path) if tariff_path else _TARIFF_PATH
        with open(path, "r", encoding="utf-8") as f:
            self.tariff = json.load(f)
        self.name = self.tariff.get("name", "GDMTO")
        self.fixed = float(self.tariff["fixed_mxn_month"])
        self.energy_rates: dict[str, float] = self.tariff["energy_mxn_kwh"]
        self.demand_rates: dict[str, float] = self.tariff["demand_mxn_kw_month"]
        self.bt_loss_pct = float(self.tariff.get("bt_loss_pct", 2.0))
        self.iva_pct = float(self.tariff.get("iva_pct", 16.0))

    # ── Single-scenario charge stack ──────────────────────────────────────────
    def _charges(self, net_kwh: float, billed_kw: float, fp_pct: float) -> dict:
        energy_items = {k: r * net_kwh for k, r in self.energy_rates.items()}
        demand_items = {k: r * billed_kw for k, r in self.demand_rates.items()}
        energy_total = sum(energy_items.values())
        demand_total = sum(demand_items.values())
        mem_total = self.fixed + energy_total + demand_total

        bt_charge = mem_total * self.bt_loss_pct / 100.0
        fp_pct_applied = fp_adjustment_pct(fp_pct)
        fp_charge = (mem_total + bt_charge) * fp_pct_applied / 100.0

        subtotal = mem_total + bt_charge + fp_charge
        iva = subtotal * self.iva_pct / 100.0
        total = subtotal + iva

        out = {
            "net_kwh": net_kwh,
            "billed_kw": billed_kw,
            "fixed_mxn": self.fixed,
            "energy_total_mxn": energy_total,
            "demand_total_mxn": demand_total,
            "mem_total_mxn": mem_total,
            "bt_charge_mxn": bt_charge,
            "fp_pct_applied": fp_pct_applied,
            "fp_charge_mxn": fp_charge,
            "subtotal_mxn": subtotal,
            "iva_mxn": iva,
            "total_mxn": total,
        }
        for k, v in energy_items.items():
            out[f"energy_{k}_mxn"] = v
        for k, v in demand_items.items():
            out[f"demand_{k}_mxn"] = v
        return out

    def compute_bill(
        self,
        kwh: float,
        kw_max: float,
        fp_pct: float,
        solar_kwh: float = 0.0,
        demand_reduction_pct: float = 0.0,
    ) -> dict:
        """
        Compute one GDMTO billing month, with and without solar.

        net_kwh = max(kwh − solar_kwh, 0); billed_kw = kw_max·(1 − reduction/100).
        Returns every itemized component plus orig_* mirrors (no solar, no
        demand reduction) and savings_mxn = orig_total − total.
        """
        net_kwh = max(kwh - solar_kwh, 0.0)
        billed_kw = kw_max * (1.0 - demand_reduction_pct / 100.0)

        new = self._charges(net_kwh, billed_kw, fp_pct)
        orig = self._charges(kwh, kw_max, fp_pct)

        result = dict(new)
        result.update({
            "kwh": kwh,
            "kw_max": kw_max,
            "fp_pct": fp_pct,
            "solar_kwh": solar_kwh,
            "solar_used_kwh": kwh - net_kwh,
            "demand_reduction_pct": demand_reduction_pct,
        })
        for k, v in orig.items():
            result[f"orig_{k}"] = v
        result["savings_mxn"] = orig["total_mxn"] - new["total_mxn"]
        return result

    # ── Annual aggregation ────────────────────────────────────────────────────
    def annual_projection(
        self,
        monthly_rows: list[dict],
        solar_monthly_kwh: list[float] | None = None,
        demand_reduction_pct: float = 0.0,
    ) -> dict:
        """
        Compute one bill per row in *monthly_rows* (S2 table schema:
        mes, kwh, demanda_kw, fp_pct — extra keys ignored) offset by the
        matching entry of *solar_monthly_kwh*.

        Returns {"monthly": [bill dicts with "month"], "annual": {...}} with
        annual keys mirroring GDMTHCalculator.annual_savings where sensible.
        """
        solar = list(solar_monthly_kwh or [])
        monthly: list[dict] = []
        for i, row in enumerate(monthly_rows):
            mes = row.get("mes", row.get("month", i + 1))
            if isinstance(mes, str):
                month_num = MONTH_ABBR_ES.index(mes[:3].capitalize()) + 1 \
                    if mes[:3].capitalize() in MONTH_ABBR_ES else i + 1
            else:
                month_num = int(mes)
            bill = self.compute_bill(
                kwh=float(row.get("kwh", 0.0) or 0.0),
                kw_max=float(row.get("demanda_kw", row.get("kw_max", 0.0)) or 0.0),
                fp_pct=float(row.get("fp_pct", 90.0) or 90.0),
                solar_kwh=float(solar[i]) if i < len(solar) else 0.0,
                demand_reduction_pct=demand_reduction_pct,
            )
            bill["month"] = month_num
            monthly.append(bill)

        annual = {
            "solar_generated_kwh": sum(b["solar_kwh"] for b in monthly),
            "solar_used_kwh": sum(b["solar_used_kwh"] for b in monthly),
            "kwh": sum(b["kwh"] for b in monthly),
            "net_kwh": sum(b["net_kwh"] for b in monthly),
            "savings_mxn": sum(b["savings_mxn"] for b in monthly),
            "savings_energy_mxn": sum(
                b["orig_energy_total_mxn"] - b["energy_total_mxn"] for b in monthly),
            "savings_demand_mxn": sum(
                b["orig_demand_total_mxn"] - b["demand_total_mxn"] for b in monthly),
            "orig_total_mxn": sum(b["orig_total_mxn"] for b in monthly),
            "total_mxn": sum(b["total_mxn"] for b in monthly),
        }
        return {"monthly": monthly, "annual": annual}

    def payback_period(self, capex_mxn: float, annual_savings_mxn: float) -> float:
        if annual_savings_mxn <= 0:
            return float("inf")
        return capex_mxn / annual_savings_mxn
