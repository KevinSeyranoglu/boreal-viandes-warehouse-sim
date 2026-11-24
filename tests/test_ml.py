"""ML pipeline on a 50-day, 3-scenario run (February–March, no seasonal peak): every model trains, and the key ones beat their baselines."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analytics"))
sys.path.insert(0, os.path.join(ROOT, "ml"))

import build_db  # noqa: E402


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ml")

    def gen(scenario):
        subprocess.run([sys.executable, "main.py", "--headless", "--days", "50", "--seed", "11", "--start", "2027-02-01",
                        "--scenario", scenario, "--out", str(tmp / f"{scenario}_seed11")],
                       cwd=ROOT, check=True, capture_output=True)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(gen, ("baseline", "lean_staff", "extra_pickers")))
    db = tmp / "warehouse.db"
    build_db.build(build_db.run_dirs(str(tmp)), str(db))
    import train_all
    out = train_all.run_all(str(db), out_dir=str(tmp / "out"), plot=False)
    return out, tmp / "out"


def test_all_models_report(results):
    out, path = results
    assert set(out) == {"demand", "labour", "spoilage", "late_orders", "temperature"}
    saved = json.loads((path / "metrics.json").read_text())
    assert saved["demand"]["wape_store_sku"] == out["demand"]["wape_store_sku"]
    assert (path / "RESULTS.md").exists()


def test_demand_beats_same_weekday_last_week(results):
    d = results[0]["demand"]
    assert d["wape_store_sku"] < d["wape_store_sku_baseline"]
    assert d["wape_sku_day"] < d["wape_sku_day_baseline"]
    assert abs(d["bias"]) < 0.05


def test_labour_plan_cheaper_than_fixed_crew(results):
    lb = results[0]["labour"]
    assert 70 < lb["target_load_cases_per_picker_hour"] < 110
    assert lb["plan"]["total_cost_per_day"] < lb["fixed"]["total_cost_per_day"]


def test_night_picks_after_midnight_belong_to_the_shift_that_started_the_day_before():
    import pandas as pd
    import labour_shift
    ts = pd.Series(["2027-02-02 01:30:00", "2027-02-02 23:00:00", "2027-02-02 09:00:00"])
    shift = pd.Series(["night", "night", "day"])
    assert list(labour_shift._shift_date(ts, shift)) == ["2027-02-01", "2027-02-02", "2027-02-02"]


def test_shift_plan_staffs_the_busy_shifts_and_trims_the_evening(results):
    """The evening shift picks little (waves for 03:00–18:00 departures fall on night and day), so the
    per-shift plan keeps its minimum crew there and puts the pickers on the shifts that pick."""
    import common as cm
    import labour_shift
    con = cm.connect(str(results[1].parent / "warehouse.db"))
    r = labour_shift.run(con)
    con.close()
    assert r["plan_load"]["evening"] is None and r["shift_share"]["evening"] < labour_shift.MIN_SHARE
    assert all(day["evening"] == labour_shift.MIN_CREW for day in r["plan"].values())
    assert r["planned_pickers"]["day"] > labour_shift.MIN_CREW and r["planned_pickers"]["night"] > labour_shift.MIN_CREW
    assert sum(r["planned_pickers"].values()) < sum(r["fixed_crew"].values())
    assert set(r["plan"]) == set(r["static_plan"])


def test_late_order_model_beats_largest_order_rule(results):
    lo = results[0]["late_orders"]
    if "skipped" in lo:
        pytest.skip(lo["skipped"])
    assert lo["pr_auc"] > lo["pr_auc_rule"]
    top = list(lo["importance"])[:4]
    assert "load_ratio" in top or "pickers_in" in top       # it found the staffing mechanism
