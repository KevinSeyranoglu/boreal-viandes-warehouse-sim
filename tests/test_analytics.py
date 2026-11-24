"""SQLite build + KPI queries on a short headless run."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import build_db  # noqa: E402
import run_sql  # noqa: E402


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wh")
    for scenario in ("baseline", "lean_staff"):
        out = tmp / f"{scenario}_seed5"
        subprocess.run([sys.executable, "main.py", "--headless", "--days", "4", "--seed", "5",
                        "--scenario", scenario, "--out", str(out)], cwd=ROOT, check=True, capture_output=True)
    path = tmp / "warehouse.db"
    build_db.build(build_db.run_dirs(str(tmp)), str(path))
    con = sqlite3.connect(path)
    yield con
    con.close()


def test_star_schema_tables(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"dim_date", "dim_sku", "dim_store", "dim_worker", "fact_orders", "fact_picks",
            "fact_temperature", "fact_inbound_trucks", "fact_daily_kpi"} <= tables
    assert db.execute("SELECT COUNT(*) FROM dim_sku").fetchone()[0] == 15        # shared dims stored once
    assert db.execute("SELECT COUNT(DISTINCT scenario) FROM fact_orders").fetchone()[0] == 2


@pytest.mark.parametrize("path", run_sql.queries(), ids=os.path.basename)
def test_every_query_returns_rows(db, path):
    params = {"scenario": "baseline", "lot": run_sql.default_lot(db, "baseline")}
    df = run_sql.run(path, db, params)
    with open(path, encoding="utf-8") as fh:
        driven_by_spoilage = "FROM fact_spoilage" in fh.read()
    spoiled = db.execute("SELECT COUNT(*) FROM fact_spoilage WHERE scenario='baseline'").fetchone()[0]
    if not (driven_by_spoilage and spoiled == 0):   # a short run may have no spoilage yet
        assert len(df) > 0


def test_daily_query_agrees_with_sim_kpis(db):
    df = run_sql.run(run_sql.queries("01_")[0], db, {"scenario": "baseline", "lot": 0})
    kpi = pd.read_sql_query("SELECT date, cases_shipped FROM fact_daily_kpi WHERE scenario='baseline'", db)
    merged = df.merge(kpi, on="date", suffixes=("", "_kpi"))
    assert (merged.cases_shipped == merged.cases_shipped_kpi).all()


def test_shipped_lots_match_order_lines(db):
    """Lot-level shipment records (recall trace) add up to the shipped order lines."""
    lots, lines = db.execute("""
        SELECT (SELECT SUM(cases) FROM fact_shipment_lots WHERE scenario='baseline'),
               (SELECT SUM(cases_shipped) FROM fact_order_lines WHERE scenario='baseline')""").fetchone()
    assert lots == lines


def test_door_numbers_are_human(db):
    assert db.execute("SELECT MIN(door), MAX(door) FROM fact_inbound_trucks").fetchone()[0] >= 1
    lo, hi = db.execute("SELECT MIN(door), MAX(door) FROM fact_shipments").fetchone()
    assert 1 <= lo and hi <= 6


def test_sim_rows_match_data_contract():
    """Every self.data.row(table, ...) call in the simulation writes exactly the declared columns."""
    import ast

    from datalog import FACT_COLUMNS
    with open(os.path.join(ROOT, "simulation.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    seen = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "row"
                and node.args and isinstance(node.args[0], ast.Constant)):
            table = node.args[0].value
            cols = [k.arg for k in node.keywords]
            assert table in FACT_COLUMNS, f"{table} missing from FACT_COLUMNS"
            if cols != [None]:                      # fact_daily_kpi passes **row
                assert cols == FACT_COLUMNS[table], table
            seen.add(table)
    assert seen == set(FACT_COLUMNS)


def test_every_fact_table_exists_even_if_empty(db):
    from datalog import FACT_COLUMNS
    for table, cols in FACT_COLUMNS.items():
        got = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        assert got[2:] == cols, table              # after the scenario, seed columns
