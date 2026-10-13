# NimbusAI — GPU Cost Optimization Report

**Period:** monthly  
**Baseline spend:** $27,133  
**Optimized spend:** $14,826  
**Projected savings:** $12,307  (**45%**)

## Savings by lever

| Lever | Savings (USD) |
|---|---|
| Inference (cascade/cache/batch) | $1,212 |
| Purchasing (spot/reserved) | $9,696 |
| Right-size memory-bound GPUs | $799 |
| Kill idle GPUs | $600 |

## Sustainability

- Energy per query: 0.24 Wh
- Carbon per query: 0.091 gCO2e
- Cleanest region (lowest gCO2/kWh): europe-north1
- Cheapest electricity region: us-east-wa
- Balanced region (50/50 carbon+price): us-east-wa

_Figures are June-2026 as-of snapshots; re-baseline before acting._

## Unit economics & audit notes

- Inference $/1M-token: $6.488 → $1.126 (82.6% saved)
- Purchasing: $25,667 on-demand → $15,971 (37.8% saved)
- GPU-Util lies (util ≥90%, MFU <0.30): gpu-h100-4, gpu-a10g-1
- Right-size lever: $799 capacity-checked (Extension 2) vs $655 with the blind one-tier-down map

## Extension 1 — Purchasing tier policy

Policy adds per-GPU spot interruption rate, a minimum job duration for commitments, the cheaper 1yr/3yr term for a 36-month service lifetime, and bills commitments 24h/day.

| Job | GPU | Old tier | New tier | On-demand | Old cost | New cost | Why |
|---|---|---|---|---|---|---|---|
| job-train-llm | H100 | spot | spot | $12,000 | $7,596 | $7,596 | unchanged |
| job-train-embed | A100 | spot | spot | $2,148 | $1,393 | $1,406 | spot rework priced at 7%/h interrupt rate for A100 (was flat 5%) |
| job-finetune | H100 | spot | spot | $900 | $570 | $570 | unchanged |
| job-infer-chat | A10G | reserved | reserved-3yr | $4,320 | $2,592 | $2,592 | unchanged |
| job-infer-rag | A100 | reserved | reserved-3yr | $3,866 | $2,160 | $2,160 | unchanged |
| job-infer-search | L4 | reserved | reserved-3yr | $1,728 | $972 | $1,296 | commitment billed 24h/day, not 18h used -> 3yr still beats on-demand |
| job-dev-sandbox | A10G | spot | spot | $480 | $203 | $209 | spot rework priced at 12%/h interrupt rate for A10G (was flat 5%) |
| job-batch-eval | H100 | spot | spot | $225 | $142 | $142 | unchanged |

- **savings_pct: old 39.1% → new 37.8%** ($15,627 → $15,971 per month vs $25,667 on-demand)
- Lifetime sensitivity: 12 mo → 1yr 29.4%; 24 mo → 1yr 29.4%; 36 mo → 3yr 37.8%
- Assumptions: spot interrupt rate/h {'A100': 0.07, 'A10G': 0.12, 'H100': 0.05, 'L4': 0.1}; no commitment for jobs < 30 days; reserved billed 24h/day.

Tier matrix (ongoing job, 36-month lifetime; BE = break-even h/day):

| GPU | Interruptible | BE h/d | 4h | 8h | 12h | 14h | 16h | 20h | 24h |
|---|---|---|---|---|---|---|---|---|---|
| H100 | yes | 13.4 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| H100 | no | 13.4 | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr | reserved-3yr |
| H200 | yes | 14.6 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| H200 | no | 14.6 | on_demand | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr |
| A100 | yes | 13.4 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| A100 | no | 13.4 | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr | reserved-3yr |
| A10G | yes | 14.4 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| A10G | no | 14.4 | on_demand | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr |
| L4 | yes | 13.5 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| L4 | no | 13.5 | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr | reserved-3yr |
| B200 | yes | 15.1 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| B200 | no | 15.1 | on_demand | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr |
| MI300X | yes | 14.8 | spot | spot | spot | spot | spot | spot | reserved-3yr |
| MI300X | no | 14.8 | on_demand | on_demand | on_demand | on_demand | reserved-3yr | reserved-3yr | reserved-3yr |

## Extension 2 — MBU right-sizing

Memory-bound GPUs (roofline FLOP/byte below ridge) are moved to the cheapest NVIDIA GPU that fits peak VRAM ×1.1 and peak bandwidth/TFLOPs ×1.2.

| GPU | Current | Proposed | MBU | Reason | USD/month |
|---|---|---|---|---|---|
| gpu-h100-4 | H100 | A100 | 0.207 | fits 74GB/1.09TB/s/271TF in 80GB/2.0TB/s; $/GB-VRAM 0.031->0.022 | $511 |
| gpu-a10g-0 | A10G | L4 | 0.235 | fits 22GB/0.22TB/s/37TF in 24GB/0.3TB/s; $/GB-VRAM 0.042->0.033 | $144 |
| gpu-a10g-1 | A10G | L4 | 0.302 | fits 22GB/0.25TB/s/45TF in 24GB/0.3TB/s; $/GB-VRAM 0.042->0.033 | $144 |
| gpu-h100-0 | H100 | H100 | 0.446 | keep: no cheaper GPU has 2.10TB/s | $0 |
| gpu-h100-1 | H100 | H100 | 0.44 | keep: no cheaper GPU has 2.13TB/s | $0 |
| gpu-h100-2 | H100 | H100 | 0.423 | keep: no cheaper GPU has 2.10TB/s | $0 |
| gpu-h100-3 | H100 | H100 | 0.444 | keep: no cheaper GPU has 2.09TB/s | $0 |
| gpu-h100-5 | H100 | H100 | 0.271 | keep: no cheaper GPU has 485 TFLOPs | $0 |
| gpu-a100-0 | A100 | A100 | 0.276 | keep: no cheaper GPU has 74GB VRAM | $0 |
| gpu-a100-1 | A100 | A100 | 0.247 | keep: no cheaper GPU has 74GB VRAM | $0 |
| gpu-l4-0 | L4 | L4 | 0.328 | keep: already the cheapest GPU | $0 |

- **Total right-sizing: $799/month**
- Consolidation option (AMD, not counted): 2x A100 → 1x MI300X (148.9 GB needed) saves $1,174/month
- Limitation: throughput not benchmarked — lower peak bandwidth may raise latency; validate with a load test before migrating.

## Extension 3 — Carbon-aware scheduling

Interruptible jobs only, same Wh in every region; days basis: actual workloads.days (not a 30-day month). us-east-1 → europe-north1.

| Job | GPU | kWh | gCO2e us-east-1 | gCO2e europe-north1 | Saved |
|---|---|---|---|---|---|
| job-train-llm | H100 | 1,568.0 | 595,840 | 47,040 | 548,800 (92.1%) |
| job-train-embed | A100 | 80.0 | 30,400 | 2,400 | 28,000 (92.1%) |
| job-finetune | H100 | 25.2 | 9,576 | 756 | 8,820 (92.1%) |
| job-dev-sandbox | A10G | 52.8 | 20,064 | 1,584 | 18,480 (92.1%) |
| job-batch-eval | H100 | 63.0 | 23,940 | 1,890 | 22,050 (92.1%) |

- **Total: 679.8 → 53.7 kgCO2e (−626,150 g, 92.1%)**

| Region | $/kWh | gCO2/kWh | Electricity $ | kgCO2e |
|---|---|---|---|---|
| europe-north1 | 0.09 | 30 | $161.01 | 53.7 |
| us-east-wa | 0.055 | 90 | $98.39 | 161.0 |
| us-west-2 | 0.07 | 120 | $125.23 | 214.7 |
| us-east-1 | 0.12 | 380 | $214.68 | 679.8 |
| europe-central2 | 0.18 | 660 | $322.02 | 1,180.7 |

- Cheapest electricity: **us-east-wa**; cleanest: **europe-north1**; balanced: **us-east-wa**. Choosing cleanest over cheapest costs $583/tCO2e avoided.
- Trade-off: the cleanest region may be far from users or outside data residency — move only interruptible batch/training work.