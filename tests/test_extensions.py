import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from finops import pricing, rightsizing, sustainability, report
from missions._common import catalog_by_type


# --- Extension 1: recommend_tier ---------------------------------------------------

def test_legacy_recommend_tier_unchanged():
    assert pricing.recommend_tier(2, True) == "spot"
    assert pricing.recommend_tier(24, False) == "reserved"
    assert pricing.recommend_tier(4, False) == "on_demand"
    assert pricing.recommend_tier(24, True) == "reserved"


def test_interrupt_rate_by_gpu_type():
    assert pricing.spot_interrupt_rate("A10G") > pricing.spot_interrupt_rate("H100")
    assert pricing.spot_interrupt_rate("unknown") == pricing.DEFAULT_INTERRUPT_RATE
    # a GPU whose spot pool is too volatile is not sent to spot
    assert pricing.recommend_tier(2, True, gpu_type="A10G", max_interrupt_rate=0.10) != "spot"
    assert pricing.recommend_tier(2, True, gpu_type="H100", max_interrupt_rate=0.10) == "spot"


def test_reserved_term_by_duration():
    assert pricing.choose_reserved_term(36, 1.4, 1.0)[0] == "3yr"
    assert pricing.choose_reserved_term(12, 1.4, 1.0)[0] == "1yr"
    term, eff = pricing.choose_reserved_term(24, 2.0, 1.4)   # H100: 3yr paid 36 of 24 months
    assert term == "1yr" and abs(eff - 2.0) < 1e-9
    assert pricing.recommend_tier(24, False, job_days=5) == "on_demand"   # too short to commit
    assert pricing.reserved_monthly_cost(2, 1.0, 30) == 1440


def test_tier_matrix_shape():
    m = pricing.tier_matrix(catalog_by_type())
    assert len(m) == 2 * len(catalog_by_type())
    h100 = next(r for r in m if r["gpu_type"] == "H100" and not r["interruptible"])
    assert h100["cells"][4] == "on_demand" and h100["cells"][24].startswith("reserved")


def test_m3_new_policy():
    from missions import m3_purchasing
    r = m3_purchasing.run(verbose=False)
    assert r["savings_pct"] > 0 and "old_savings_pct" in r
    tiers = {x["tier"] for x in r["recommendations"]}
    assert {"spot", "reserved"} <= tiers
    assert all("old_tier" in x and "term" in x for x in r["recommendations"])
    # shorter service lifetime -> 1yr term and lower savings
    short = m3_purchasing.run(verbose=False, lifetime_months=24)
    assert short["savings_pct"] < r["savings_pct"]


# --- Extension 2: right-sizing -----------------------------------------------------

def test_gpu_value_table():
    rows = {r["gpu_type"]: r for r in rightsizing.gpu_value_table(catalog_by_type())}
    assert abs(rows["L4"]["usd_per_gb_vram_hr"] - 0.8 / 24) < 1e-9


def test_recommend_gpu_checks_capacity():
    cat = catalog_by_type()
    small = rightsizing.recommend_gpu("H100", 20, 0.25, cat)
    assert small["proposed"] != "H100" and small["usd_month_saving"] > 0
    assert float(cat[small["proposed"]]["hbm_gb"]) >= 24
    big = rightsizing.recommend_gpu("H100", 70, 0.25, cat)          # VRAM rules out 24GB cards
    assert float(cat[big["proposed"]]["hbm_gb"]) >= 77
    keep = rightsizing.recommend_gpu("L4", 10, 0.1, cat)
    assert keep["proposed"] == "L4" and keep["usd_month_saving"] == 0


def test_m1_rightsizing():
    from missions import m1_efficiency_audit
    r = m1_efficiency_audit.run(verbose=False)
    assert any(l["gpu_id"] == "gpu-h100-4" for l in r["lies"])
    assert r["rightsizing"] and r["rightsizing_monthly_savings"] > 0
    # the A100 inference replicas use ~67GB, so they must not be moved to a 24GB card
    assert all(x["proposed"] == "A100" for x in r["rightsizing"] if x["current"] == "A100")


# --- Extension 5: carbon-aware scheduling ------------------------------------------

def test_regions_consistent():
    assert set(sustainability.REGION_CARBON) == set(sustainability.REGION_PRICE_KWH)


def test_region_choices():
    assert sustainability.job_energy_wh(700, 8, 20, 14) == 700 * 8 * 20 * 14
    assert sustainability.cleanest_region() == "europe-north1"
    assert sustainability.cheapest_region() == "us-east-wa"      # cheapest != cleanest
    rows = sustainability.region_comparison(1000)
    assert len(rows) == 5 and rows == sorted(rows, key=lambda x: x["carbon_g"])


def test_m6_carbon():
    from missions import m6_carbon_scheduling
    r = m6_carbon_scheduling.run(verbose=False)
    assert r["saved_g"] > 0 and r["optimized_g"] < r["baseline_g"]
    assert r["jobs"] and all(j["interruptible"] for j in r["jobs"])


# --- Report ------------------------------------------------------------------------

def test_report_has_extensions():
    from missions import m5_report
    r = m5_report.run(verbose=False)
    assert 40 <= r["total_savings_pct"] <= 95
    md = open(os.path.join(ROOT, "outputs", "report.md")).read()
    for h in ("Savings by lever", "Sustainability", "Extension 1", "Extension 2", "Extension 3"):
        assert h in md
