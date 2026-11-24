"""DuckDB build: same data as the SQLite build, typed columns, views, Parquet, and the KPI queries agree."""
from __future__ import annotations

import os
import subprocess
import sys

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import build_db  # noqa: E402
import build_duckdb  # noqa: E402
import run_sql  # noqa: E402


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("duck")
    for scenario in ("baseline", "lean_staff"):
        subprocess.run([sys.executable, "main.py", "--headless", "--days", "4", "--seed", "6",
                        "--scenario", scenario, "--out", str(tmp / f"{scenario}_seed6")],
                       cwd=ROOT, check=True, capture_output=True)
    runs = build_db.run_dirs(str(tmp))
    build_db.build(runs, str(tmp / "w.db"))
    build_duckdb.build(runs, str(tmp / "w.duckdb"), parquet_dir=str(tmp / "parquet"))
    s = run_sql.connect("sqlite", str(tmp / "w.db"))
    d = run_sql.connect("duckdb", str(tmp / "w.duckdb"))
    yield s, d, tmp
    s.close()
    d.close()


def test_same_tables_and_row_counts(dbs):
    s, d, _ = dbs
    lite = {t for (t,) in s.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    duck = {t for (t,) in d.execute("SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'").fetchall()}
    assert lite == duck
    for t in lite:
        assert s.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == d.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], t


def test_types_keep_barcodes_and_timestamps(dbs):
    _, d, _ = dbs
    types = dict(d.execute("SELECT column_name, data_type FROM information_schema.columns "
                           "WHERE table_name = 'fact_transactions'").fetchall())
    assert types["ts"] == "TIMESTAMP" and types["sscc"] == "VARCHAR" and types["gtin"] == "VARCHAR"
    sscc = d.execute("SELECT sscc FROM fact_transactions WHERE txn_type = 'RCV' LIMIT 1").fetchone()[0]
    assert len(sscc) == 18 and sscc.startswith("0")          # leading zero survived


@pytest.mark.parametrize("path", run_sql.queries(), ids=os.path.basename)
def test_kpi_queries_agree_with_sqlite(dbs, path):
    s, d, _ = dbs
    params = {"scenario": "baseline", "lot": run_sql.default_lot(s, "baseline")}
    a, b = run_sql.run(path, d, params), run_sql.run(path, s, params)
    assert a.shape == b.shape
    for col in a.columns:                                   # numbers equal up to the last rounded digit
        if pd.api.types.is_datetime64_any_dtype(a[col]):    # DuckDB returns real dates, SQLite text
            left = a[col].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("").str.replace(" 00:00:00", "")
            right = b[col].fillna("").astype(str).replace({"None": "", "nan": ""}).str.replace(" 00:00:00", "")
            assert sorted(left) == sorted(right), col
            continue
        x, y = pd.to_numeric(a[col], errors="coerce"), pd.to_numeric(b[col], errors="coerce")
        if x.notna().any():
            xs, ys = np.sort(x.fillna(-1e18).values), np.sort(y.fillna(-1e18).values)
            assert np.allclose(xs, ys, rtol=1e-6, atol=0.11), col


def test_views_and_examples_run(dbs):
    _, d, _ = dbs
    for v in ("v_pallet_history", "v_dock_to_stock", "v_lot_trace", "v_order_service"):
        assert d.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0] > 0, v
    for title, sql in run_sql.statements(os.path.join(ROOT, "analytics", "duckdb_examples.sql")):
        run_sql.query(d, sql, {})                            # every example parses and runs


def test_parquet_export_reads_back(dbs):
    _, d, tmp = dbs
    n = d.execute("SELECT COUNT(*) FROM fact_transactions").fetchone()[0]
    p = duckdb.connect().execute(
        f"SELECT COUNT(*), COUNT(DISTINCT scenario) FROM read_parquet('{tmp}/parquet/fact_transactions/*/*.parquet', "
        "hive_partitioning=true)").fetchone()
    assert p == (n, 2)
