"""Pricing & purchasing economics — measure in $/1M-token, not $/GPU-hr.

Figures are June-2026 as-of snapshots from the deck's RESEARCH dossier; treat
live prices as fast-moving (re-baseline before each cohort).
"""
from __future__ import annotations
import math


def request_cost(
    input_tok: int,
    output_tok: int,
    price_in_per_m: float,
    price_out_per_m: float,
    cached_in: int = 0,
    cache_discount: float = 0.10,   # Anthropic cached-read ~0.1x (=-90%)
    batch: bool = False,
    batch_discount: float = 0.50,   # Batch API ~ -50%
) -> float:
    """USD cost of a single request. Cached input billed at cache_discount x price."""
    cached_in = min(max(0, cached_in), input_tok)
    uncached_in = input_tok - cached_in
    cost = (
        (uncached_in / 1e6) * price_in_per_m
        + (cached_in / 1e6) * price_in_per_m * cache_discount
        + (output_tok / 1e6) * price_out_per_m
    )
    if batch:
        cost *= batch_discount
    return cost


def dollars_per_million(total_cost_usd: float, total_tokens: int) -> float:
    """Aggregate unit economics: $ per 1,000,000 tokens served."""
    if total_tokens <= 0:
        return 0.0
    return total_cost_usd / (total_tokens / 1e6)


def discount_stack(
    batch: bool = False,
    cache_hit_frac: float = 0.0,
    batch_discount: float = 0.50,
    cache_discount: float = 0.10,
) -> float:
    """Effective fraction of the naive bill after stacking discounts (input-heavy view).

    Discounts MULTIPLY: cache applies to the cached share of input, batch to the
    whole bill. batch + 100% cache-hit -> 0.5 * 0.1 = 0.05 (~95% off).
    """
    cache_mult = cache_hit_frac * cache_discount + (1.0 - cache_hit_frac)
    batch_mult = batch_discount if batch else 1.0
    return cache_mult * batch_mult


def break_even_utilization(discount_frac: float) -> float:
    """Utilization at which a commitment pays off ~= 1 - discount.

    A 45% reserved discount needs ~55% utilization (~13.2h/day) to beat on-demand.
    """
    return max(0.0, min(1.0, 1.0 - discount_frac))


# --- Extension 1: tier policy inputs -------------------------------------------------
# Per-hour chance a spot GPU is reclaimed. ASSUMPTION: mapped from the AWS Spot Instance
# Advisor "frequency of interruption" buckets (<5%, 5-10%, 10-15% per month of instances,
# here read as a per-hour rate for the simulation) and the deck note that H100 spot is
# reclaimed less often than A10G. Scarce, newest SKUs sit in larger pools -> lower rate.
SPOT_INTERRUPT_RATE_PER_HR = {
    "H100": 0.05, "H200": 0.05, "B200": 0.06,
    "A100": 0.07, "MI300X": 0.08, "L4": 0.10, "A10G": 0.12,
}
DEFAULT_INTERRUPT_RATE = 0.05      # = old spot_checkpoint_cost default
MAX_SPOT_INTERRUPT_RATE = 0.15     # ASSUMPTION: above this, rework + restarts make spot unreliable
MIN_COMMIT_DAYS = 30               # ASSUMPTION: a job shorter than a month cannot use a 1yr/3yr commitment
# ASSUMPTION: NimbusAI's 24/7 inference baseline is expected to run >= 3 years on the same
# GPU class. Sensitivity at 12/24 months is printed by M3 (1yr wins below 36 months).
SERVICE_LIFETIME_MONTHS = 36


def spot_interrupt_rate(gpu_type: str | None) -> float:
    """Per-hour spot interruption rate for a GPU type (default when unknown)."""
    return SPOT_INTERRUPT_RATE_PER_HR.get(gpu_type or "", DEFAULT_INTERRUPT_RATE)


def choose_reserved_term(expected_months: float, reserved_1yr_hr: float, reserved_3yr_hr: float) -> tuple:
    """Pick the 1yr or 3yr commitment with the lower *effective* hourly rate.

    A commitment is paid for whole terms, so if the workload only lives `expected_months`,
    the effective rate is term_rate * paid_months / used_months. Ties go to '1yr' (less lock-in).
    """
    if expected_months <= 0:
        return "1yr", reserved_1yr_hr
    m = float(expected_months)
    eff_1yr = reserved_1yr_hr * math.ceil(m / 12) * 12 / m
    eff_3yr = reserved_3yr_hr * math.ceil(m / 36) * 36 / m
    return ("3yr", eff_3yr) if eff_3yr < eff_1yr else ("1yr", eff_1yr)


def reserved_monthly_cost(num_gpus: float, reserved_hr: float, days: float = 30) -> float:
    """A commitment is billed 24h/day whether the GPU is busy or not."""
    return num_gpus * 24 * days * reserved_hr


def recommend_tier(hours_per_day: float, interruptible: bool, reserved_discount: float = 0.45, *,
                   gpu_type: str | None = None, job_days: float | None = None,
                   max_interrupt_rate: float = MAX_SPOT_INTERRUPT_RATE) -> str:
    """Pick a purchasing tier from a workload's duty cycle + interruptibility.

    Policy (with only the first three args it behaves exactly like the original):
      - interruptible & not 24/7            -> 'spot'      (checkpoint and ride the discount)
          ... unless gpu_type is given and its spot interrupt rate > max_interrupt_rate
      - duty cycle >= break-even            -> 'reserved'  (steady, high utilization)
          ... unless job_days is given and < MIN_COMMIT_DAYS (one-off job, no commitment)
      - otherwise                           -> 'on_demand' (spiky / low duty / short)
    Pass reserved_discount from the chosen term (see choose_reserved_term) so the
    break-even reflects the real 1yr/3yr rate of that GPU type.
    """
    duty = max(0.0, hours_per_day) / 24.0
    be = break_even_utilization(reserved_discount)
    spot_ok = gpu_type is None or spot_interrupt_rate(gpu_type) <= max_interrupt_rate
    if interruptible and hours_per_day < 24 and spot_ok:
        return "spot"
    commit_ok = job_days is None or job_days >= MIN_COMMIT_DAYS
    if duty >= be and commit_ok:
        return "reserved"
    return "on_demand"


def tier_matrix(catalog: dict, duty_hours=(4, 8, 12, 14, 16, 20, 24),
                lifetime_months: float = SERVICE_LIFETIME_MONTHS) -> list:
    """Policy matrix GPU type x duty cycle x interruptible -> tier (+term) for an ongoing job."""
    rows = []
    for gtype, c in catalog.items():
        od = float(c["on_demand_hr"])
        term, term_hr = choose_reserved_term(lifetime_months, float(c["reserved_1yr_hr"]),
                                             float(c["reserved_3yr_hr"]))
        disc = 1.0 - term_hr / od if od > 0 else 0.0
        for interruptible in (True, False):
            cells = {}
            for h in duty_hours:
                t = recommend_tier(h, interruptible, disc, gpu_type=gtype)
                cells[h] = f"reserved-{term}" if t == "reserved" else t
            rows.append({"gpu_type": gtype, "interruptible": interruptible,
                         "break_even_h": round(break_even_utilization(disc) * 24, 1), "cells": cells})
    return rows


def spot_checkpoint_cost(
    job_hours: float,
    spot_hr: float,
    on_demand_hr: float,
    interrupt_rate: float = 0.05,      # per-hour chance (H100 spot ~<5%)
    ckpt_overhead_frac: float = 0.03,  # steady cost of writing checkpoints
    rework_hours_per_interrupt: float = 0.5,
) -> dict:
    """Effective cost of running a checkpointable job on spot vs on-demand.

    Interruptions waste the compute since the last checkpoint (rework); checkpointing
    adds a small steady overhead. Spot still wins for interruptible jobs.
    """
    expected_interrupts = job_hours * interrupt_rate
    rework_hours = expected_interrupts * rework_hours_per_interrupt
    effective_hours = job_hours * (1.0 + ckpt_overhead_frac) + rework_hours
    spot_cost = effective_hours * spot_hr
    on_demand_cost = job_hours * on_demand_hr
    savings_pct = (1.0 - spot_cost / on_demand_cost) * 100.0 if on_demand_cost > 0 else 0.0
    return {
        "spot_effective_hours": round(effective_hours, 2),
        "spot_cost": round(spot_cost, 2),
        "on_demand_cost": round(on_demand_cost, 2),
        "savings_pct": round(savings_pct, 1),
    }
