"""Sustainability economics — energy and carbon as governed cost levers (deck §11).

Region selection cuts $ and carbon together; reasoning queries are an energy bomb.
"""
from __future__ import annotations

# Grid carbon intensity (gCO2 / kWh) — illustrative 2026 snapshot.
REGION_CARBON = {
    "us-east-1": 380,
    "us-west-2": 120,   # Oregon hydro
    "europe-north1": 30,  # Norway
    "europe-central2": 660,  # Poland (dirtiest)
    "us-east-wa": 90,
}
# Electricity price (USD / kWh) — illustrative.
REGION_PRICE_KWH = {
    "us-east-1": 0.12,
    "us-west-2": 0.07,
    "europe-north1": 0.09,
    "europe-central2": 0.18,
    "us-east-wa": 0.055,
}

REASONING_ENERGY_MULTIPLIER = 80.0  # deck: reasoning ~74-86x a small-model query


def wh_per_query(total_tokens: int, wh_per_1k_tokens: float = 0.30, is_reasoning: bool = False) -> float:
    """Energy for one query. Median Gemini prompt ~0.24 Wh; reasoning ~74-86x."""
    base = (total_tokens / 1000.0) * wh_per_1k_tokens
    return base * (REASONING_ENERGY_MULTIPLIER if is_reasoning else 1.0)


def carbon_g(wh: float, region: str = "us-east-1") -> float:
    """Grams CO2 for an energy amount in a region."""
    gco2_kwh = REGION_CARBON.get(region, 400)
    return (wh / 1000.0) * gco2_kwh


def energy_cost_usd(wh: float, region: str = "us-east-1") -> float:
    """Electricity cost of an energy amount in a region."""
    return (wh / 1000.0) * REGION_PRICE_KWH.get(region, 0.12)


def tokens_per_watt(total_tokens: int, wh: float, seconds: float = 1.0) -> float:
    """Energy efficiency of serving: tokens per watt (higher is better)."""
    watts = (wh * 3600.0) / seconds if seconds > 0 else 0.0
    return total_tokens / watts if watts > 0 else 0.0


# --- Extension 5: carbon-aware scheduling -------------------------------------------
PUE = 1.0  # ASSUMPTION: board power only (PUE ignored); multiply by ~1.1-1.4 for facility overhead


def job_energy_wh(watts: float, num_gpus: float, hours_per_day: float, days: float) -> float:
    """Energy of a job at full board power (ASSUMPTION: GPUs draw rated TDP while running)."""
    return watts * num_gpus * hours_per_day * days * PUE


def region_comparison(wh: float) -> list:
    """Same energy in every region: grid intensity, $/kWh, electricity cost and carbon (sorted by carbon)."""
    rows = [{"region": r, "gco2_kwh": REGION_CARBON[r], "usd_kwh": REGION_PRICE_KWH[r],
             "carbon_g": carbon_g(wh, r), "energy_usd": energy_cost_usd(wh, r)} for r in REGION_CARBON]
    return sorted(rows, key=lambda x: x["carbon_g"])


def cleanest_region() -> str:
    return min(REGION_CARBON, key=REGION_CARBON.get)


def cheapest_region() -> str:
    return min(REGION_PRICE_KWH, key=REGION_PRICE_KWH.get)


def balanced_region(carbon_weight: float = 0.5) -> str:
    """Lowest weighted sum of carbon and price, each normalised to the worst region (0..1)."""
    max_c, max_p = max(REGION_CARBON.values()), max(REGION_PRICE_KWH.values())
    return min(REGION_CARBON, key=lambda r: carbon_weight * REGION_CARBON[r] / max_c
               + (1 - carbon_weight) * REGION_PRICE_KWH[r] / max_p)
