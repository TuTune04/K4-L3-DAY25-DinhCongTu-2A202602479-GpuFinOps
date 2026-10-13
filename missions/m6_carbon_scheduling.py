"""M6 — Carbon-aware Scheduling (Extension 5): move interruptible jobs to a cleaner grid.

Same work everywhere (same Wh); only the grid changes. Energy uses each job's ACTUAL
duration from workloads.csv (days column), not a 30-day month.

Run: python missions/m6_carbon_scheduling.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num, catalog_by_type
from finops import sustainability as sus

BASELINE_REGION = "us-east-1"
DAYS_BASIS = "actual workloads.days"


def run(verbose: bool = True) -> dict:
    jobs = [j for j in load_csv("workloads.csv") if int(num(j["interruptible"])) == 1]
    cat = catalog_by_type()
    target = sus.cleanest_region()
    rows = []
    for j in jobs:
        ngpu, hpd, days = num(j["num_gpus"]), num(j["hours_per_day"]), num(j["days"])
        wh = sus.job_energy_wh(num(cat[j["gpu_type"]]["watts"]), ngpu, hpd, days)
        before, after = sus.carbon_g(wh, BASELINE_REGION), sus.carbon_g(wh, target)
        rows.append({"job_id": j["job_id"], "gpu_type": j["gpu_type"], "interruptible": True,
                     "gpu_hours": ngpu * hpd * days, "days": days, "wh": wh,
                     "baseline_g": before, "optimized_g": after, "saved_g": before - after,
                     "saved_pct": (before - after) / before * 100 if before else 0.0,
                     "usd_before": sus.energy_cost_usd(wh, BASELINE_REGION),
                     "usd_after": sus.energy_cost_usd(wh, target)})
    total_wh = sum(r["wh"] for r in rows)
    baseline_g = sum(r["baseline_g"] for r in rows)
    optimized_g = sum(r["optimized_g"] for r in rows)
    regions = sus.region_comparison(total_wh)
    picks = {"cheapest_region": sus.cheapest_region(), "cleanest_region": target,
             "balanced_region": sus.balanced_region()}
    by_region = {g["region"]: g for g in regions}
    cheap, clean = by_region[picks["cheapest_region"]], by_region[target]
    extra_usd = clean["energy_usd"] - cheap["energy_usd"]
    avoided_t = (cheap["carbon_g"] - clean["carbon_g"]) / 1e6
    abatement = extra_usd / avoided_t if avoided_t > 0 else 0.0  # $ per tCO2e: cleanest vs cheapest

    if verbose:
        print("== M6 Carbon-aware Scheduling ==")
        print(f"interruptible jobs only; energy = TDP x GPUs x h/day x days ({DAYS_BASIS}); "
              f"{BASELINE_REGION} -> {target}")
        print(f"{'job':18}{'gpu':6}{'GPU-h':>7}{'kWh':>9}{'gCO2 ' + BASELINE_REGION:>18}{'gCO2 ' + target:>20}"
              f"{'saved %':>9}{'$elec':>8}{'->':>8}")
        for r in rows:
            print(f"{r['job_id']:18}{r['gpu_type']:6}{r['gpu_hours']:>7,.0f}{r['wh']/1000:>9,.1f}"
                  f"{r['baseline_g']:>18,.0f}{r['optimized_g']:>20,.0f}{r['saved_pct']:>8.1f}%"
                  f"{r['usd_before']:>8,.2f}{r['usd_after']:>8,.2f}")
        print(f"\ntotal: {total_wh/1000:,.1f} kWh  {baseline_g/1000:,.1f} kgCO2e -> {optimized_g/1000:,.1f} kgCO2e"
              f"  (saved {(baseline_g-optimized_g)/1000:,.1f} kg = {(baseline_g-optimized_g):,.0f} g, "
              f"{(baseline_g-optimized_g)/baseline_g*100:.1f}%)")
        print(f"\n{'region':17}{'$/kWh':>7}{'gCO2/kWh':>10}{'elec $':>9}{'kgCO2e':>9}")
        for g in regions:
            print(f"{g['region']:17}{g['usd_kwh']:>7}{g['gco2_kwh']:>10}{g['energy_usd']:>9,.2f}{g['carbon_g']/1000:>9,.1f}")
        print(f"\ncheapest power: {picks['cheapest_region']} | cleanest: {picks['cleanest_region']} | "
              f"balanced (50/50): {picks['balanced_region']}")
        if picks["cheapest_region"] != picks["cleanest_region"]:
            print("-> cheapest and cleanest differ: pick by the company's priority (cost vs carbon target).")
            print(f"   {target} vs {picks['cheapest_region']}: +${extra_usd:,.2f} electricity for "
                  f"-{avoided_t*1000:,.1f} kgCO2e  = ${abatement:,.0f}/tCO2e abatement cost")
        print("note: electricity $ is a proxy — rented GPU $/hr already bundles power; the regional GPU "
              "price is not in the catalog.")
        print("trade-off: the cleanest region may be far from users (latency) or outside the data-residency "
              "zone; move only interruptible batch/training work, keep latency-bound inference near users.")

    return {"jobs": rows, "total_wh": round(total_wh), "baseline_g": round(baseline_g),
            "optimized_g": round(optimized_g), "saved_g": round(baseline_g - optimized_g),
            "saved_pct": round((baseline_g - optimized_g) / baseline_g * 100, 1) if baseline_g else 0.0,
            "regions": regions, "abatement_usd_per_t": round(abatement), "days_basis": DAYS_BASIS, "baseline_region": BASELINE_REGION, **picks}


if __name__ == "__main__":
    run()
