"""
CFE GDMTH (Gran Demanda en Media Tensión Horaria) tariff calculator.

Tariff structure (per CFE 2024 acuerdo tarifario):
  - Cargo por Energía: three periods — Punta, Intermedia, Base (MXN/kWh)
  - Cargo por Capacidad: based on mean demand during Punta hours in highest
    month of the trailing 12 months (MXN/kW/month)
  - Cargo por Distribución: based on maximum integrated demand across all
    hours of the billing period (MXN/kW/month)

Usage:
    from core.gdmth import GDMTHCalculator
    calc = GDMTHCalculator(rates)
    result = calc.compute_bill(demand_series)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

_TARIFF_PATH = Path(__file__).parent.parent / "data" / "tariff_gdmth.json"


def load_tariff_data() -> dict:
    with open(_TARIFF_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_verano(ts: pd.Timestamp) -> bool:
    """
    Returns True if timestamp falls in CFE 'verano' (summer) schedule.
    Verano: 1st Sunday of April through Saturday before last Sunday of October.
    Approximated by months 4–10 inclusive (accurate for most GDMTH billing purposes).
    """
    return ts.month in (4, 5, 6, 7, 8, 9, 10)


def classify_period(ts: pd.Timestamp) -> Literal["punta", "intermedia", "base"]:
    """
    CFE GDMTH period classification per official tariff schedule
    (Regiones Central, Noreste, Noroeste, Norte, Peninsular, Sur).

    VERANO (1er dom. abril → sáb. anterior al último dom. octubre):
      L–V : Base 0:00–6:00 | Intermedia 6:00–20:00, 22:00–24:00 | Punta 20:00–22:00
      Sáb : Base 0:00–7:00 | Intermedia 7:00–24:00               | sin Punta
      Dom : Base 0:00–19:00| Intermedia 19:00–24:00               | sin Punta

    INVIERNO (último dom. octubre → sáb. anterior al 1er dom. abril):
      L–V : Base 0:00–6:00 | Intermedia 6:00–18:00, 22:00–24:00 | Punta 18:00–22:00
      Sáb : Base 0:00–8:00 | Intermedia 8:00–19:00, 21:00–24:00 | Punta 19:00–21:00
      Dom : Base 0:00–18:00| Intermedia 18:00–24:00               | sin Punta
    """
    hour = ts.hour
    weekday = ts.weekday()   # 0=Mon … 6=Sun
    verano = _is_verano(ts)

    # ── Domingo y festivo — never Punta ──────────────────────────────────────
    if weekday == 6:
        base_limit = 19 if verano else 18
        return "base" if hour < base_limit else "intermedia"

    # ── Sábado ───────────────────────────────────────────────────────────────
    if weekday == 5:
        if verano:
            return "base" if hour < 7 else "intermedia"
        else:                                  # invierno
            if hour < 8:
                return "base"
            if 19 <= hour < 21:
                return "punta"
            return "intermedia"

    # ── Lunes a viernes ──────────────────────────────────────────────────────
    if hour < 6:
        return "base"
    if verano and 20 <= hour < 22:
        return "punta"
    if not verano and 18 <= hour < 22:
        return "punta"
    return "intermedia"


def get_season(month: int) -> Literal["temporada_alta", "temporada_baja"]:
    if month in (2, 3, 4, 5, 6, 7, 8, 9):
        return "temporada_alta"
    return "temporada_baja"


class GDMTHCalculator:
    def __init__(self, region: str = "Noreste"):
        data = load_tariff_data()
        self.region = region
        self.rates = data["rates_by_region"][region]

    def _get_rates(self, month: int) -> dict:
        season = get_season(month)
        return self.rates[season]

    def compute_bill(
        self,
        demand_kw: pd.Series,
        solar_kw: pd.Series | None = None,
        trailing_12_punta_means: list[float] | None = None,
    ) -> dict:
        """
        Compute one billing month's GDMTH charges.

        Parameters
        ----------
        demand_kw : hourly demand series (kW), DatetimeIndex
        solar_kw  : hourly solar generation (kW). If provided, net = demand - solar
        trailing_12_punta_means : list of previous months' mean Punta demands (kW)
            for Cargo por Capacidad. If None, uses current month only.

        Returns dict with energy charges, capacity charge, distribution charge,
        subtotals, and all intermediate values.
        """
        if demand_kw.empty:
            return {}

        df = pd.DataFrame({"demand": demand_kw.values}, index=demand_kw.index)
        if solar_kw is not None:
            aligned = solar_kw.reindex(df.index, fill_value=0.0)
            df["solar"] = aligned.values
            df["net_demand"] = (df["demand"] - df["solar"]).clip(lower=0)
        else:
            df["net_demand"] = df["demand"]

        df["period"] = df.index.map(classify_period)

        month = df.index[0].month
        rates = self._get_rates(month)

        # --- Energy charges ---
        punta_kwh = df.loc[df["period"] == "punta", "net_demand"].sum()
        inter_kwh = df.loc[df["period"] == "intermedia", "net_demand"].sum()
        base_kwh = df.loc[df["period"] == "base", "net_demand"].sum()

        charge_punta = punta_kwh * rates["punta_mxn_kwh"]
        charge_inter = inter_kwh * rates["intermedia_mxn_kwh"]
        charge_base = base_kwh * rates["base_mxn_kwh"]

        # --- Cargo por Capacidad ---
        # Mean demand during Punta hours of current month
        punta_mask = df["period"] == "punta"
        current_punta_mean = df.loc[punta_mask, "net_demand"].mean() if punta_mask.any() else 0.0

        if trailing_12_punta_means:
            all_means = trailing_12_punta_means + [current_punta_mean]
            capacidad_kw = max(all_means)
        else:
            capacidad_kw = current_punta_mean

        charge_capacidad = capacidad_kw * rates["capacidad_mxn_kw_month"]

        # --- Cargo por Distribución ---
        max_demand_kw = df["net_demand"].max()
        charge_distribucion = max_demand_kw * rates["distribucion_mxn_kw_month"]

        # --- Subtotals for original (no solar) bill ---
        orig_punta_kwh = df.loc[df["period"] == "punta", "demand"].sum()
        orig_inter_kwh = df.loc[df["period"] == "intermedia", "demand"].sum()
        orig_base_kwh = df.loc[df["period"] == "base", "demand"].sum()
        orig_charge_punta = orig_punta_kwh * rates["punta_mxn_kwh"]
        orig_charge_inter = orig_inter_kwh * rates["intermedia_mxn_kwh"]
        orig_charge_base = orig_base_kwh * rates["base_mxn_kwh"]
        orig_punta_mean = df.loc[punta_mask, "demand"].mean() if punta_mask.any() else 0.0
        orig_capacidad_kw = orig_punta_mean
        if trailing_12_punta_means:
            orig_capacidad_kw = max(trailing_12_punta_means + [orig_punta_mean])
        orig_charge_capacidad = orig_capacidad_kw * rates["capacidad_mxn_kw_month"]
        orig_max_demand = df["demand"].max()
        orig_charge_distribucion = orig_max_demand * rates["distribucion_mxn_kw_month"]

        orig_total = orig_charge_punta + orig_charge_inter + orig_charge_base + orig_charge_capacidad + orig_charge_distribucion
        new_total = charge_punta + charge_inter + charge_base + charge_capacidad + charge_distribucion

        # Solar contribution
        solar_generated_kwh = df["solar"].sum() if "solar" in df.columns else 0.0
        solar_punta_kwh = df.loc[punta_mask, "solar"].sum() if "solar" in df.columns and punta_mask.any() else 0.0
        solar_inter_kwh = df.loc[df["period"] == "intermedia", "solar"].sum() if "solar" in df.columns else 0.0
        solar_base_kwh = df.loc[df["period"] == "base", "solar"].sum() if "solar" in df.columns else 0.0

        return {
            "region": self.region,
            "month": month,
            "season": get_season(month),
            "rates": rates,
            # With solar
            "punta_kwh": punta_kwh,
            "inter_kwh": inter_kwh,
            "base_kwh": base_kwh,
            "charge_punta": charge_punta,
            "charge_inter": charge_inter,
            "charge_base": charge_base,
            "capacidad_kw": capacidad_kw,
            "charge_capacidad": charge_capacidad,
            "max_demand_kw": max_demand_kw,
            "charge_distribucion": charge_distribucion,
            "total_mxn": new_total,
            # Without solar
            "orig_punta_kwh": orig_punta_kwh,
            "orig_inter_kwh": orig_inter_kwh,
            "orig_base_kwh": orig_base_kwh,
            "orig_charge_punta": orig_charge_punta,
            "orig_charge_inter": orig_charge_inter,
            "orig_charge_base": orig_charge_base,
            "orig_capacidad_kw": orig_capacidad_kw,
            "orig_charge_capacidad": orig_charge_capacidad,
            "orig_max_demand_kw": orig_max_demand,
            "orig_charge_distribucion": orig_charge_distribucion,
            "orig_total_mxn": orig_total,
            # Solar info
            "solar_generated_kwh": solar_generated_kwh,
            "solar_punta_kwh": solar_punta_kwh,
            "solar_inter_kwh": solar_inter_kwh,
            "solar_base_kwh": solar_base_kwh,
            "savings_mxn": orig_total - new_total,
            "savings_energy_mxn": (orig_charge_punta + orig_charge_inter + orig_charge_base)
                - (charge_punta + charge_inter + charge_base),
            "savings_capacidad_mxn": orig_charge_capacidad - charge_capacidad,
            "savings_distribucion_mxn": orig_charge_distribucion - charge_distribucion,
        }

    def annual_savings(self, monthly_results: list[dict]) -> dict:
        """Aggregate a list of monthly result dicts into annual totals."""
        if not monthly_results:
            return {}
        keys = [
            "solar_generated_kwh", "savings_mxn", "savings_energy_mxn",
            "savings_capacidad_mxn", "savings_distribucion_mxn",
            "orig_total_mxn", "total_mxn",
        ]
        return {k: sum(r.get(k, 0) for r in monthly_results) for k in keys}

    def payback_period(self, capex_mxn: float, annual_savings_mxn: float) -> float:
        if annual_savings_mxn <= 0:
            return float("inf")
        return capex_mxn / annual_savings_mxn
