"""Right-sizing by MBU — pick the cheapest GPU that still fits the workload (Extension 2).

A memory-bound workload (roofline: arithmetic intensity below the GPU's ridge point)
does not use the FLOPs it rents, so a smaller card can serve it — but only if the
model + KV-cache still fit in VRAM and the card has enough bandwidth (and compute).
That is why the answer is never just "the lowest $/GPU-hr".
"""
from __future__ import annotations

VRAM_HEADROOM = 1.10   # ASSUMPTION: +10% over observed peak for KV-cache growth / fragmentation
BW_HEADROOM = 1.20     # ASSUMPTION: +20% over observed peak HBM bandwidth (burst traffic)
TFLOPS_HEADROOM = 1.20 # ASSUMPTION: +20% over observed peak TFLOPs so prefill does not saturate
HOURS_PER_MONTH = 24 * 30
# Swapping NVIDIA -> AMD needs a ROCm port and re-validation, so it is off by default.
GPU_VENDOR = {"MI300X": "AMD"}  # every other catalog type is NVIDIA


def vendor(gpu_type: str) -> str:
    return GPU_VENDOR.get(gpu_type, "NVIDIA")


def gpu_value_table(catalog: dict) -> list:
    """Per GPU type: $/hr, VRAM, bandwidth, $/GB-VRAM-hr, $/(TB/s)-hr and roofline ridge point."""
    rows = []
    for gtype, c in catalog.items():
        od, hbm, bw = float(c["on_demand_hr"]), float(c["hbm_gb"]), float(c["peak_bw_tbs"])
        tf = float(c["peak_tflops_fp16"])
        rows.append({"gpu_type": gtype, "on_demand_hr": od, "hbm_gb": hbm, "peak_bw_tbs": bw,
                     "peak_tflops_fp16": tf,
                     "usd_per_gb_vram_hr": od / hbm if hbm else 0.0,
                     "usd_per_tbs_hr": od / bw if bw else 0.0,
                     "ridge_flop_per_byte": tf / bw if bw else 0.0})
    return sorted(rows, key=lambda r: r["usd_per_gb_vram_hr"])


def is_memory_bound(achieved_tflops: float, achieved_bw_tbs: float,
                    peak_tflops: float, peak_bw_tbs: float) -> bool:
    """Roofline test: workload FLOP/byte below the GPU ridge point -> bandwidth-limited."""
    if achieved_bw_tbs <= 0 or peak_bw_tbs <= 0:
        return False
    return achieved_tflops / achieved_bw_tbs < peak_tflops / peak_bw_tbs


def recommend_gpu(current_type: str, mem_used_gb: float, achieved_bw_tbs: float, catalog: dict,
                  achieved_tflops: float = 0.0, allow_vendor_switch: bool = False) -> dict:
    """Cheapest GPU (by $/hr, ties by $/GB-VRAM) that meets VRAM, bandwidth and compute needs.

    Keeps the current type when nothing cheaper is feasible. One GPU replaces one GPU,
    so the bill is driven by $/hr *after* the capacity constraints are met.
    """
    need_vram = mem_used_gb * VRAM_HEADROOM
    need_bw = achieved_bw_tbs * BW_HEADROOM
    need_tf = achieved_tflops * TFLOPS_HEADROOM
    table = {r["gpu_type"]: r for r in gpu_value_table(catalog)}
    cur = table[current_type]
    feasible = [r for r in table.values()
                if r["hbm_gb"] >= need_vram and r["peak_bw_tbs"] >= need_bw
                and r["peak_tflops_fp16"] >= need_tf
                and (allow_vendor_switch or vendor(r["gpu_type"]) == vendor(current_type))]
    best = min(feasible, key=lambda r: (r["on_demand_hr"], r["usd_per_gb_vram_hr"]), default=None)
    if best is None or best["on_demand_hr"] >= cur["on_demand_hr"]:
        blocker = _binding_constraint(table, cur, need_vram, need_bw, need_tf)
        return {"current": current_type, "proposed": current_type,
                "need_vram_gb": round(need_vram, 1), "need_bw_tbs": round(need_bw, 2),
                "need_tflops": round(need_tf), "reason": f"keep: {blocker}", "usd_month_saving": 0.0}
    reason = (f"fits {need_vram:.0f}GB/{need_bw:.2f}TB/s/{need_tf:.0f}TF in {best['hbm_gb']:.0f}GB/"
              f"{best['peak_bw_tbs']}TB/s; $/GB-VRAM {cur['usd_per_gb_vram_hr']:.3f}->"
              f"{best['usd_per_gb_vram_hr']:.3f}")
    saving = max(0.0, (cur["on_demand_hr"] - best["on_demand_hr"]) * HOURS_PER_MONTH)
    return {"current": current_type, "proposed": best["gpu_type"],
            "need_vram_gb": round(need_vram, 1), "need_bw_tbs": round(need_bw, 2),
            "need_tflops": round(need_tf), "reason": reason, "usd_month_saving": round(saving, 2)}


def _binding_constraint(table, cur, need_vram, need_bw, need_tf) -> str:
    """Name what stops every cheaper same-vendor GPU (VRAM is checked first)."""
    cheaper = [r for r in table.values() if r["on_demand_hr"] < cur["on_demand_hr"]
               and vendor(r["gpu_type"]) == vendor(cur["gpu_type"])]
    if not cheaper:
        return "already the cheapest GPU"
    if all(r["hbm_gb"] < need_vram for r in cheaper):
        return f"no cheaper GPU has {need_vram:.0f}GB VRAM"
    if all(r["hbm_gb"] < need_vram or r["peak_bw_tbs"] < need_bw for r in cheaper):
        return f"no cheaper GPU has {need_bw:.2f}TB/s"
    return f"no cheaper GPU has {need_tf:.0f} TFLOPs"


def consolidation_option(gpu_type: str, count: int, mem_used_gb: float, achieved_bw_tbs: float,
                         catalog: dict) -> dict | None:
    """Can `count` memory-bound GPUs be packed onto ONE larger card (any vendor)?

    This is where $/GB-VRAM matters: a 192GB card at a low $/GB can host two 80GB
    replicas for less than two 80GB cards. Returns None if nothing is cheaper.
    """
    need_vram = mem_used_gb * count * VRAM_HEADROOM
    need_bw = achieved_bw_tbs * count * BW_HEADROOM
    cur_cost = float(catalog[gpu_type]["on_demand_hr"]) * count
    fits = [r for r in gpu_value_table(catalog)
            if r["hbm_gb"] >= need_vram and r["peak_bw_tbs"] >= need_bw and r["on_demand_hr"] < cur_cost]
    if not fits:
        return None
    best = min(fits, key=lambda r: r["on_demand_hr"])
    return {"from": f"{count}x {gpu_type}", "to": f"1x {best['gpu_type']}",
            "vendor": vendor(best["gpu_type"]), "need_vram_gb": round(need_vram, 1),
            "usd_month_saving": round((cur_cost - best["on_demand_hr"]) * HOURS_PER_MONTH, 2)}
