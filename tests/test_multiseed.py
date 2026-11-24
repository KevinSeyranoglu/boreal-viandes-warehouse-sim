"""Multi-seed summary: mean ± sd per scenario, paired differences to the baseline, and the report."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import multiseed as ms  # noqa: E402


def fake_runs():
    """Baseline profit varies a lot by seed; extra_pickers is always exactly $100 better (same seed)."""
    rows = []
    for seed, noise in zip((1, 2, 3, 4, 5), (-800, 300, 0, 900, -400)):
        for scenario, lift in (("baseline", 0), ("extra_pickers", 100)):
            r = {k: 50.0 for k in ms.KPIS}
            r.update(scenario=scenario, seed=seed, profit_per_day=2500 + noise + lift, wages_per_day=16000 + 2 * lift)
            rows.append(r)
    return pd.DataFrame(rows)


def test_ci_matches_t_interval():
    m, sd, h = ms.ci([1, 2, 3, 4, 5])
    assert m == 3 and sd == pytest.approx(1.5811, abs=1e-4)
    assert h == pytest.approx(2.776 * 1.5811 / 5 ** 0.5, abs=1e-3)


def test_pairing_removes_shared_noise():
    summ, diff = ms.summarise(fake_runs())
    base = summ[(summ.scenario == "baseline") & (summ.kpi == "profit_per_day")].iloc[0]
    assert base["sd"] > 500                                   # unpaired, the noise hides a $100 effect
    d = diff[diff.kpi == "profit_per_day"].iloc[0]
    assert d["diff"] == pytest.approx(100) and d["sd"] == pytest.approx(0)
    assert d.seeds_better == 5
    w = diff[diff.kpi == "wages_per_day"].iloc[0]            # lower wages are better: higher is never "better"
    assert w.seeds_better == 0


def test_report_formats_signs_and_points(tmp_path):
    runs = fake_runs()
    summ, diff = ms.summarise(runs)
    path = tmp_path / "MULTISEED.md"
    ms.write_report(runs, summ, diff, pd.DataFrame(), path=str(path))
    text = path.read_text(encoding="utf-8")
    assert "| `extra_pickers` | Profit / day | **+$100** |" in text
    assert "+0.0 pts" in text and "$-" not in text
