"""Report assembly — the lab's deliverable: baseline vs optimized + savings chart."""
from __future__ import annotations


def build_report(baseline_usd: float, optimized_usd: float, levers: dict,
                 sustainability: dict | None = None, period: str = "monthly") -> str:
    """Return a markdown cost-optimization report."""
    savings = baseline_usd - optimized_usd
    pct = (savings / baseline_usd * 100.0) if baseline_usd > 0 else 0.0
    lines = [
        "# NimbusAI — GPU Cost Optimization Report",
        "",
        f"**Period:** {period}  ",
        f"**Baseline spend:** ${baseline_usd:,.0f}  ",
        f"**Optimized spend:** ${optimized_usd:,.0f}  ",
        f"**Projected savings:** ${savings:,.0f}  (**{pct:.0f}%**)",
        "",
        "## Savings by lever",
        "",
        "| Lever | Savings (USD) |",
        "|---|---|",
    ]
    for name, amount in levers.items():
        lines.append(f"| {name} | ${amount:,.0f} |")
    if sustainability:
        lines += [
            "",
            "## Sustainability",
            "",
            f"- Energy per query: {sustainability.get('wh_per_query', 0):.2f} Wh",
            f"- Carbon per query: {sustainability.get('carbon_g', 0):.3f} gCO2e",
        ]
        if "cheapest_region" in sustainability:
            lines += [
                f"- Cleanest region (lowest gCO2/kWh): {sustainability.get('best_region', 'n/a')}",
                f"- Cheapest electricity region: {sustainability['cheapest_region']}",
                f"- Balanced region (50/50 carbon+price): {sustainability.get('balanced_region', 'n/a')}",
            ]
        else:
            lines.append(f"- Cheapest+cleanest region: {sustainability.get('best_region', 'n/a')}")
    lines += ["", "_Figures are June-2026 as-of snapshots; re-baseline before acting._"]
    return "\n".join(lines)


def build_extensions_section(purchasing: dict, rightsizing: dict, carbon: dict) -> str:
    """Markdown for the three "Your Turn" extensions (before/after tables + assumptions)."""
    p, rs, c = purchasing, rightsizing, carbon
    lines = [
        "## Extension 1 — Purchasing tier policy",
        "",
        "Policy adds per-GPU spot interruption rate, a minimum job duration for commitments, the cheaper "
        f"1yr/3yr term for a {p['lifetime_months']}-month service lifetime, and bills commitments 24h/day.",
        "",
        "| Job | GPU | Old tier | New tier | On-demand | Old cost | New cost | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in p["recommendations"]:
        new = r["tier"] + (f"-{r['term']}" if r["term"] else "")
        lines.append(f"| {r['job_id']} | {r['gpu_type']} | {r['old_tier']} | {new} | ${r['on_demand']:,} | "
                     f"${r['old_optimized']:,} | ${r['optimized']:,} | {r.get('reason') or 'unchanged'} |")
    lines += [
        "",
        f"- **savings_pct: old {p['old_savings_pct']}% → new {p['savings_pct']}%** "
        f"(${p['old_optimized_monthly']:,} → ${p['optimized_monthly']:,} per month vs ${p['on_demand_monthly']:,} on-demand)",
        "- Lifetime sensitivity: " + "; ".join(
            f"{s['lifetime_months']} mo → {'/'.join(s['terms'])} {s['savings_pct']}%" for s in p["sensitivity"]),
        f"- Assumptions: spot interrupt rate/h {p['interrupt_rates']}; no commitment for jobs < 30 days; "
        "reserved billed 24h/day.",
    ]
    if p.get("tier_matrix"):
        hours = list(p["tier_matrix"][0]["cells"].keys())
        lines += [
            "",
            f"Tier matrix (ongoing job, {p['lifetime_months']}-month lifetime; BE = break-even h/day):",
            "",
            "| GPU | Interruptible | BE h/d | " + " | ".join(f"{h}h" for h in hours) + " |",
            "|---|---|---|" + "---|" * len(hours),
        ]
        for m in p["tier_matrix"]:
            lines.append(f"| {m['gpu_type']} | {'yes' if m['interruptible'] else 'no'} | {m['break_even_h']} | "
                         + " | ".join(m["cells"][h] for h in hours) + " |")
    lines += [
        "",
        "## Extension 2 — MBU right-sizing",
        "",
        "Memory-bound GPUs (roofline FLOP/byte below ridge) are moved to the cheapest NVIDIA GPU that fits "
        "peak VRAM ×1.1 and peak bandwidth/TFLOPs ×1.2.",
        "",
        "| GPU | Current | Proposed | MBU | Reason | USD/month |",
        "|---|---|---|---|---|---|",
    ]
    for r in rs["recommendations"]:
        lines.append(f"| {r['gpu_id']} | {r['current']} | {r['proposed']} | {r['mbu']} | {r['reason']} | "
                     f"${r['usd_month_saving']:,.0f} |")
    lines.append("")
    lines.append(f"- **Total right-sizing: ${rs['monthly_savings']:,.0f}/month**")
    for o in rs.get("consolidation", []):
        lines.append(f"- Consolidation option ({o['vendor']}, not counted): {o['from']} → {o['to']} "
                     f"({o['need_vram_gb']} GB needed) saves ${o['usd_month_saving']:,.0f}/month")
    lines += [
        "- Limitation: throughput not benchmarked — lower peak bandwidth may raise latency; "
        "validate with a load test before migrating.",
        "",
        "## Extension 3 — Carbon-aware scheduling",
        "",
        f"Interruptible jobs only, same Wh in every region; days basis: {c['days_basis']} "
        f"(not a 30-day month). {c['baseline_region']} → {c['cleanest_region']}.",
        "",
        f"| Job | GPU | kWh | gCO2e {c['baseline_region']} | gCO2e {c['cleanest_region']} | Saved |",
        "|---|---|---|---|---|---|",
    ]
    for j in c["jobs"]:
        lines.append(f"| {j['job_id']} | {j['gpu_type']} | {j['wh']/1000:,.1f} | {j['baseline_g']:,.0f} | "
                     f"{j['optimized_g']:,.0f} | {j['saved_g']:,.0f} ({j['saved_pct']:.1f}%) |")
    lines += [
        "",
        f"- **Total: {c['baseline_g']/1000:,.1f} → {c['optimized_g']/1000:,.1f} kgCO2e "
        f"(−{c['saved_g']:,} g, {c['saved_pct']}%)**",
        "",
        "| Region | $/kWh | gCO2/kWh | Electricity $ | kgCO2e |",
        "|---|---|---|---|---|",
    ]
    for g in c["regions"]:
        lines.append(f"| {g['region']} | {g['usd_kwh']} | {g['gco2_kwh']} | ${g['energy_usd']:,.2f} | "
                     f"{g['carbon_g']/1000:,.1f} |")
    lines += [
        "",
        f"- Cheapest electricity: **{c['cheapest_region']}**; cleanest: **{c['cleanest_region']}**; "
        f"balanced: **{c['balanced_region']}**. Choosing cleanest over cheapest costs "
        f"${c['abatement_usd_per_t']:,}/tCO2e avoided.",
        "- Trade-off: the cleanest region may be far from users or outside data residency — move only "
        "interruptible batch/training work.",
    ]
    return "\n".join(lines)


def savings_waterfall(levers: dict, path: str) -> str:
    """Write a simple savings bar chart PNG. Returns the path. No-op if matplotlib absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return ""
    names = list(levers.keys())
    vals = [levers[n] for n in names]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(names, vals, color="#2e548a")
    ax.set_ylabel("Savings (USD / month)")
    ax.set_title("GPU cost savings by FinOps lever")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
