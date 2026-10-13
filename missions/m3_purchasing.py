"""M3 — Purchasing Strategy: break-even, tier choice, spot-checkpoint sim (deck §4).

Extension 1: compares the original policy with a policy that uses the per-GPU spot
interruption rate, the job duration and the cheaper 1yr/3yr commitment, and bills a
commitment 24h/day (you pay for the reservation whether or not the GPU is busy).

Run: python missions/m3_purchasing.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num, catalog_by_type
from finops import pricing

DAYS = 30                          # monthly view: every job is costed over 30 days
SENSITIVITY_MONTHS = (12, 24, 36)  # service lifetimes for the 1yr-vs-3yr sensitivity


def _old_policy(gpu_hours, hpd, interruptible, c):
    tier = pricing.recommend_tier(hpd, interruptible)
    od = num(c["on_demand_hr"])
    if tier == "spot":
        cost = pricing.spot_checkpoint_cost(gpu_hours, num(c["spot_hr"]), od)["spot_cost"]
    elif tier == "reserved":
        cost = gpu_hours * num(c["reserved_3yr_hr"])
    else:
        cost = gpu_hours * od
    return tier, cost


def _new_policy(gtype, ngpu, gpu_hours, hpd, interruptible, job_days, c, lifetime_months):
    od = num(c["on_demand_hr"])
    on_demand_cost = gpu_hours * od
    term, term_hr = pricing.choose_reserved_term(lifetime_months, num(c["reserved_1yr_hr"]),
                                                 num(c["reserved_3yr_hr"]))
    tier = pricing.recommend_tier(hpd, interruptible, 1.0 - term_hr / od,
                                  gpu_type=gtype, job_days=job_days)
    if tier == "spot":
        cost = pricing.spot_checkpoint_cost(gpu_hours, num(c["spot_hr"]), od,
                                            interrupt_rate=pricing.spot_interrupt_rate(gtype))["spot_cost"]
    elif tier == "reserved":
        cost = pricing.reserved_monthly_cost(ngpu, term_hr, DAYS)
    else:
        cost = on_demand_cost
    if cost >= on_demand_cost:     # guard: never pay more than on-demand
        tier, cost = "on_demand", on_demand_cost
    return tier, (term if tier == "reserved" else ""), cost


def _evaluate(jobs, cat, lifetime_months):
    recs = []
    for j in jobs:
        gtype = j["gpu_type"]
        ngpu = int(num(j["num_gpus"]))
        hpd = num(j["hours_per_day"])
        interruptible = bool(int(num(j["interruptible"])))
        c = cat[gtype]
        gpu_hours = hpd * DAYS * ngpu
        on_demand_cost = gpu_hours * num(c["on_demand_hr"])
        old_tier, old_cost = _old_policy(gpu_hours, hpd, interruptible, c)
        tier, term, cost = _new_policy(gtype, ngpu, gpu_hours, hpd, interruptible,
                                       num(j["days"]), c, lifetime_months)
        recs.append({"job_id": j["job_id"], "gpu_type": gtype, "tier": tier, "term": term,
                     "old_tier": old_tier, "hours_per_day": hpd, "days": int(num(j["days"])),
                     "interruptible": interruptible,
                     "on_demand": round(on_demand_cost), "old_optimized": round(old_cost),
                     "optimized": round(cost),
                     "_od": on_demand_cost, "_old": old_cost, "_new": cost})
    od_total = sum(r.pop("_od") for r in recs)
    old_total = sum(r.pop("_old") for r in recs)
    new_total = sum(r.pop("_new") for r in recs)
    return recs, od_total, old_total, new_total


def _pct(base, opt):
    return (base - opt) / base * 100 if base else 0.0


def _change_reason(r):
    if r["old_tier"] == r["tier"] and r["old_optimized"] == r["optimized"]:
        return ""
    if r["tier"] == "spot":
        rate = pricing.spot_interrupt_rate(r["gpu_type"])
        return f"spot rework priced at {rate:.0%}/h interrupt rate for {r['gpu_type']} (was flat 5%)"
    if r["tier"] == "reserved":
        if r["hours_per_day"] < 24:
            return (f"commitment billed 24h/day, not {r['hours_per_day']:.0f}h used "
                    f"-> {r['term']} still beats on-demand")
        return f"{r['term']} term has the lowest effective rate"
    if r["old_tier"] == "reserved":
        return "24h/day commitment costs >= on-demand at this duty cycle"
    return "tier changed"


def run(verbose: bool = True, lifetime_months: float = pricing.SERVICE_LIFETIME_MONTHS) -> dict:
    jobs = load_csv("workloads.csv")
    cat = catalog_by_type()
    recs, on_demand_monthly, old_monthly, optimized_monthly = _evaluate(jobs, cat, lifetime_months)
    savings_pct = _pct(on_demand_monthly, optimized_monthly)
    old_savings_pct = _pct(on_demand_monthly, old_monthly)
    for r in recs:
        r["reason"] = _change_reason(r)

    sensitivity = []
    for m in SENSITIVITY_MONTHS:
        s_recs, s_od, _, s_new = _evaluate(jobs, cat, m)
        sensitivity.append({"lifetime_months": m, "optimized_monthly": round(s_new),
                            "savings_pct": round(_pct(s_od, s_new), 1),
                            "terms": sorted({r["term"] for r in s_recs if r["term"]})})
    rates = {g: pricing.spot_interrupt_rate(g) for g in sorted({r["gpu_type"] for r in recs})}
    matrix = pricing.tier_matrix(cat, lifetime_months=lifetime_months)

    if verbose:
        print("== M3 Purchasing Strategy ==")
        print(f"break-even utilization @ 45% reserved discount = {pricing.break_even_utilization(0.45):.0%}")
        print(f"{'job':18}{'gpu':7}{'old tier':11}{'new tier':14}{'on-demand':>11}{'old cost':>11}{'new cost':>11}")
        for r in recs:
            new = r["tier"] + (f"-{r['term']}" if r["term"] else "")
            print(f"{r['job_id']:18}{r['gpu_type']:7}{r['old_tier']:11}{new:14}"
                  f"${r['on_demand']:>10,}${r['old_optimized']:>10,}${r['optimized']:>10,}")
        print(f"\nmonthly: on-demand ${on_demand_monthly:,.0f} -> optimized ${optimized_monthly:,.0f}  ({savings_pct:.1f}% saved)")
        print(f"savings_pct old {old_savings_pct:.1f}% -> new {savings_pct:.1f}%  "
              f"(old policy ${old_monthly:,.0f}/month)")
        print("changed jobs:")
        for r in recs:
            if r["reason"]:
                print(f"  {r['job_id']:18}{r['old_tier']} -> {r['tier']}: {r['reason']}")
        print(f"spot interrupt rate/h (ASSUMPTION): {rates}")
        print(f"\nservice-lifetime sensitivity (default {lifetime_months} months):")
        for s in sensitivity:
            print(f"  {s['lifetime_months']:>3} months -> terms {s['terms']}  optimized ${s['optimized_monthly']:,}"
                  f"  ({s['savings_pct']}% saved)")
        hours = list(matrix[0]["cells"].keys())
        print(f"\ntier matrix (ongoing job, {lifetime_months}-month lifetime):")
        print(f"{'gpu':7}{'intr':6}{'BE h/d':>7}  " + "".join(f"{str(h) + 'h':>13}" for h in hours))
        for m in matrix:
            print(f"{m['gpu_type']:7}{'yes' if m['interruptible'] else 'no':6}{m['break_even_h']:>7}  "
                  + "".join(f"{m['cells'][h]:>13}" for h in hours))

    return {"recommendations": recs, "on_demand_monthly": round(on_demand_monthly),
            "optimized_monthly": round(optimized_monthly), "savings_pct": round(savings_pct, 1),
            "old_optimized_monthly": round(old_monthly), "old_savings_pct": round(old_savings_pct, 1),
            "lifetime_months": lifetime_months, "interrupt_rates": rates,
            "sensitivity": sensitivity, "tier_matrix": matrix}


if __name__ == "__main__":
    run()
