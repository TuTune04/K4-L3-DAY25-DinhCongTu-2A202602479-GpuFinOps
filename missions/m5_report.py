"""M5 — Optimization Report: combine M1-M4 into baseline-vs-optimized (deck §1/§11).

Run: python missions/m5_report.py   ->  outputs/report.md + outputs/savings.png
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
from missions._common import num, catalog_by_type, ROOT
from finops import report, sustainability
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing, m6_carbon_scheduling

DAYS = 30
# one tier down for over-provisioned ("util-lie") GPUs — original blind mapping, kept for comparison.
# The lever now uses Extension 2 (capacity-checked right-sizing of memory-bound GPUs).
RIGHTSIZE_MAP = {"H100": "A100", "H200": "H100", "A100": "A10G", "A10G": "L4", "L4": "L4"}


def run(verbose: bool = True) -> dict:
    r1 = m1_efficiency_audit.run(verbose=False)
    r2 = m2_inference_levers.run(verbose=False)
    r3 = m3_purchasing.run(verbose=False)
    r6 = m6_carbon_scheduling.run(verbose=False)
    cat = catalog_by_type()

    # --- buckets ---
    infer_savings = (r2["baseline_daily"] - r2["optimized_daily"]) * DAYS
    purchasing_savings = r3["on_demand_monthly"] - r3["optimized_monthly"]

    idle_savings = r1["idle_waste_daily"] * DAYS
    blind_rightsize = 0.0
    for lie in r1["lies"]:
        cur = lie["gpu_type"]
        tgt = RIGHTSIZE_MAP.get(cur, cur)
        delta = num(cat[cur]["on_demand_hr"]) - num(cat[tgt]["on_demand_hr"])
        blind_rightsize += max(0.0, delta) * 24 * DAYS
    rightsize_savings = r1["rightsizing_monthly_savings"]

    levers = {
        "Inference (cascade/cache/batch)": round(infer_savings),
        "Purchasing (spot/reserved)": round(purchasing_savings),
        "Right-size memory-bound GPUs": round(rightsize_savings),
        "Kill idle GPUs": round(idle_savings),
    }
    baseline = r2["baseline_daily"] * DAYS + r3["on_demand_monthly"]
    optimized = baseline - sum(levers.values())
    total_pct = sum(levers.values()) / baseline * 100 if baseline else 0.0

    # --- sustainability snapshot ---
    median_tokens = 800
    wh = sustainability.wh_per_query(median_tokens)
    sust = {
        "wh_per_query": wh,
        "carbon_g": sustainability.carbon_g(wh, "us-east-1"),
        "best_region": min(sustainability.REGION_CARBON, key=sustainability.REGION_CARBON.get),
        "cheapest_region": sustainability.cheapest_region(),
        "balanced_region": sustainability.balanced_region(),
    }

    md = report.build_report(baseline, optimized, levers, sustainability=sust)
    md += "\n\n" + "\n".join([
        "## Unit economics & audit notes",
        "",
        f"- Inference $/1M-token: ${r2['baseline_per_m']} → ${r2['optimized_per_m']} ({r2['savings_pct']}% saved)",
        f"- Purchasing: ${r3['on_demand_monthly']:,} on-demand → ${r3['optimized_monthly']:,} ({r3['savings_pct']}% saved)",
        f"- GPU-Util lies (util ≥90%, MFU <0.30): {', '.join(l['gpu_id'] for l in r1['lies'])}",
        f"- Right-size lever: ${round(rightsize_savings):,} capacity-checked (Extension 2) vs "
        f"${round(blind_rightsize):,} with the blind one-tier-down map",
    ])
    md += "\n\n" + report.build_extensions_section(
        r3, {"recommendations": r1["rightsizing"], "monthly_savings": r1["rightsizing_monthly_savings"],
             "consolidation": r1["consolidation"]}, r6)
    out_md = os.path.join(ROOT, "outputs", "report.md")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w") as f:
        f.write(md)
    png = report.savings_waterfall(levers, os.path.join(ROOT, "outputs", "savings.png"))

    if verbose:
        print("== M5 Optimization Report ==")
        print(md)
        print(f"\nWritten: outputs/report.md" + (f" + outputs/savings.png" if png else " (matplotlib absent: PNG skipped)"))

    return {"baseline_monthly": round(baseline), "optimized_monthly": round(optimized),
            "levers": levers, "total_savings_pct": round(total_pct, 1), "extensions": True}


if __name__ == "__main__":
    run()
