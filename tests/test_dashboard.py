"""Power BI export and Streamlit dashboard on a short headless run."""
from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import build_db  # noqa: E402
import export_powerbi  # noqa: E402


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dash")
    for scenario in ("baseline", "lean_staff"):
        subprocess.run([sys.executable, "main.py", "--headless", "--days", "3", "--seed", "3",
                        "--scenario", scenario, "--out", str(tmp / f"{scenario}_seed3")],
                       cwd=ROOT, check=True, capture_output=True)
    path = tmp / "warehouse.db"
    build_db.build(build_db.run_dirs(str(tmp)), str(path))
    return path


def test_powerbi_export(db_path, tmp_path):
    tables, expected = export_powerbi.export(str(db_path), str(tmp_path / "pbi"))
    files = set(os.listdir(tmp_path / "pbi"))
    assert {"dim_date.csv", "dim_scenario.csv", "dim_worker.csv", "fact_orders.csv",
            "fact_temperature_hourly.csv", "_expected_measures.csv"} <= files
    w = tables["dim_worker"]
    assert w["worker_key"].is_unique                       # one-column key for Power BI relationships
    picks = tables["fact_picks"]
    assert set(picks["worker_key"]) <= set(w["worker_key"])  # every fact key finds its dimension row
    for name, df in tables.items():
        if name.startswith("fact_") and name not in ("fact_weather",):
            assert "date" in df.columns, name
    assert list(expected["scenario"]) == ["baseline", "lean_staff"]


def test_expected_measures_match_sim_kpis(db_path, tmp_path):
    tables, expected = export_powerbi.export(str(db_path), str(tmp_path / "pbi2"))
    k = tables["fact_daily_kpi"]
    base = expected.set_index("scenario").loc["baseline"]
    kb = k[k["scenario"] == "baseline"]
    assert base["Profit per Day $"] == round(kb["profit"].sum() / kb["date"].nunique(), 0)
    assert 0.5 < base["Fill Rate %"] <= 1


def test_dashboard_renders_every_tab(db_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("WAREHOUSE_DB", str(db_path))
    at = AppTest.from_file(os.path.join(ROOT, "dashboard", "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 8 and len(at.metric) >= 15
    at.sidebar.selectbox[0].set_value("lean_staff").run()
    assert not at.exception
    assert any("vs" in (m.delta or "") for m in at.metric)    # cards compare against the baseline
    at.sidebar.radio[0].set_value("EN").run()
    assert not at.exception and "dashboard" in at.title[0].value
