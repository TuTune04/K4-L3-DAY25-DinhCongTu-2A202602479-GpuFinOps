"""M1 — Efficiency Audit: MFU/MBU, the GPU-Util lie, and idle waste (deck §5).

Extension 2: right-size memory-bound GPUs (roofline) by VRAM, bandwidth and $/GB-VRAM.

Run: python missions/m1_efficiency_audit.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from collections import defaultdict
from missions._common import load_csv, num, catalog_by_type
from finops import metrics, rightsizing


def run(verbose: bool = True) -> dict:
    tel = load_csv("gpu_telemetry.csv")
    cat = catalog_by_type()

    # per-row MFU/MBU, then aggregate per GPU
    agg = defaultdict(lambda: {"util": [], "mfu": [], "mbu": [], "type": None, "idle_hours": 0,
                               "mem": [], "tf": [], "bw": [], "workload": None})
    for r in tel:
        gtype = r["gpu_type"]
        peak_fp16 = num(cat[gtype]["peak_tflops_fp16"])
        peak_bw = num(cat[gtype]["peak_bw_tbs"])
        mfu = metrics.compute_mfu(num(r["achieved_tflops"]), peak_fp16)
        mbu = metrics.compute_mbu(num(r["achieved_bw_tbs"]), peak_bw)
        a = agg[r["gpu_id"]]
        a["type"] = gtype
        a["util"].append(num(r["gpu_util_pct"]))
        a["mfu"].append(mfu)
        a["mbu"].append(mbu)
        a["mem"].append(num(r["mem_used_gb"]))
        a["tf"].append(num(r["achieved_tflops"]))
        a["bw"].append(num(r["achieved_bw_tbs"]))
        a["workload"] = r.get("workload")
        if num(r["gpu_util_pct"]) < 10:  # effectively idle this interval (1h)
            a["idle_hours"] += 1

    summary = []
    for gid, a in agg.items():
        summary.append({
            "gpu_id": gid, "gpu_type": a["type"],
            "gpu_util_pct": round(sum(a["util"]) / len(a["util"]), 1),
            "mfu": round(sum(a["mfu"]) / len(a["mfu"]), 3),
            "mbu": round(sum(a["mbu"]) / len(a["mbu"]), 3),
            "idle_hours": a["idle_hours"],
            "workload": a["workload"],
            "mem_used_gb_max": round(max(a["mem"]), 1),
            "achieved_tflops": round(sum(a["tf"]) / len(a["tf"]), 1),
            "achieved_tflops_max": round(max(a["tf"]), 1),
            "achieved_bw_tbs": round(sum(a["bw"]) / len(a["bw"]), 3),
            "achieved_bw_tbs_max": round(max(a["bw"]), 3),
        })

    lies = metrics.flag_util_lies(summary)
    idle_waste = 0.0
    for s in summary:
        on_demand = num(catalog_by_type()[s["gpu_type"]]["on_demand_hr"])
        idle_waste += metrics.idle_waste_usd(s["idle_hours"], on_demand)

    rs = rightsize(summary, cat)

    if verbose:
        print("== M1 Efficiency Audit ==")
        print(f"{'GPU':14}{'type':7}{'util%':>7}{'MFU':>7}{'MBU':>7}{'idle_h':>8}")
        for s in sorted(summary, key=lambda x: x["mfu"]):
            print(f"{s['gpu_id']:14}{s['gpu_type']:7}{s['gpu_util_pct']:>7}{s['mfu']:>7}{s['mbu']:>7}{s['idle_hours']:>8}")
        print(f"\nGPU-Util LIES (util>=90% but MFU<30%): {[l['gpu_id'] for l in lies]}")
        print(f"Idle waste (1 day): ${idle_waste:,.2f}  ->  ${idle_waste*30:,.0f}/month")
        print_rightsizing(rs, cat)

    return {"summary": summary, "lies": lies, "idle_waste_daily": round(idle_waste, 2),
            "rightsizing": rs["recommendations"],
            "rightsizing_monthly_savings": rs["monthly_savings"],
            "consolidation": rs["consolidation"]}


def rightsize(summary: list, cat: dict) -> dict:
    """Extension 2: one recommendation per memory-bound GPU, sized on observed peaks."""
    recs = []
    for s in summary:
        c = cat[s["gpu_type"]]
        if not rightsizing.is_memory_bound(s["achieved_tflops"], s["achieved_bw_tbs"],
                                           num(c["peak_tflops_fp16"]), num(c["peak_bw_tbs"])):
            continue
        rec = rightsizing.recommend_gpu(s["gpu_type"], s["mem_used_gb_max"], s["achieved_bw_tbs_max"],
                                        cat, achieved_tflops=s["achieved_tflops_max"])
        recs.append({"gpu_id": s["gpu_id"], "workload": s["workload"], "mbu": s["mbu"], **rec})
    recs.sort(key=lambda r: -r["usd_month_saving"])
    # $/GB-VRAM view: can same-type inference replicas share one bigger card?
    consolidation = []
    groups = defaultdict(list)
    for s in summary:
        if s["workload"] != "train":
            groups[s["gpu_type"]].append(s)
    for gtype, members in groups.items():
        if len(members) < 2:
            continue
        opt = rightsizing.consolidation_option(gtype, len(members), max(m["mem_used_gb_max"] for m in members),
                                               max(m["achieved_bw_tbs_max"] for m in members), cat)
        per_gpu = sum(r["usd_month_saving"] for r in recs if r["gpu_id"] in {m["gpu_id"] for m in members})
        if opt and opt["usd_month_saving"] > per_gpu:  # only when it beats one-for-one right-sizing
            consolidation.append({**opt, "gpu_ids": [m["gpu_id"] for m in members]})
    return {"recommendations": recs, "consolidation": consolidation,
            "monthly_savings": round(sum(r["usd_month_saving"] for r in recs), 2)}


def print_rightsizing(rs: dict, cat: dict) -> None:
    print("\n-- Right-sizing by MBU (Extension 2) --")
    print(f"{'type':8}{'$/hr':>6}{'VRAM':>6}{'TB/s':>6}{'$/GB-VRAM-h':>13}{'$/TBs-h':>9}{'ridge F/B':>10}")
    for v in rightsizing.gpu_value_table(cat):
        print(f"{v['gpu_type']:8}{v['on_demand_hr']:>6}{v['hbm_gb']:>6.0f}{v['peak_bw_tbs']:>6}"
              f"{v['usd_per_gb_vram_hr']:>13.4f}{v['usd_per_tbs_hr']:>9.3f}{v['ridge_flop_per_byte']:>10.0f}")
    print(f"\n{'GPU':12}{'now':7}{'->':7}{'MBU':>6}{'USD/mo':>9}  reason")
    for r in rs["recommendations"]:
        print(f"{r['gpu_id']:12}{r['current']:7}{r['proposed']:7}{r['mbu']:>6}"
              f"{r['usd_month_saving']:>9,.0f}  {r['reason']}")
    print(f"right-sizing total: ${rs['monthly_savings']:,.0f}/month "
          f"(sized on peak VRAM x{rightsizing.VRAM_HEADROOM}, peak BW/TFLOPs x{rightsizing.BW_HEADROOM}, NVIDIA only)")
    for c in rs["consolidation"]:
        print(f"consolidation option ({c['vendor']}, not in total): {c['from']} {c['gpu_ids']} -> {c['to']} "
              f"needs {c['need_vram_gb']}GB, saves ${c['usd_month_saving']:,.0f}/month")
    print("LIMITATION: throughput not benchmarked — lower peak bandwidth may raise latency; "
          "validate with a load test before migrating.")


if __name__ == "__main__":
    run()
