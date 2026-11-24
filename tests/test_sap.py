"""SAP S/4HANA extract: the tables follow their layouts, and the HANA SQL analyses (run on DuckDB through the
dialect shim) give the same numbers as the simulation's own tables."""
from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import export_sap as sap  # noqa: E402


@pytest.fixture(scope="module")
def extract(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sap")
    run = tmp / "baseline_seed5"
    subprocess.run([sys.executable, "main.py", "--headless", "--days", "8", "--seed", "5", "--out", str(run)],
                   cwd=ROOT, check=True, capture_output=True)
    tables = sap.export(str(run), str(tmp / "sap"), sql_dir=None)
    return run, tables, sap.load_duckdb(tables)


def src(run, table):
    return pd.read_csv(run / f"{table}.csv")


def test_tables_follow_their_layouts(extract):
    run, tables, _ = extract
    for name, (_, fields) in sap.TABLES.items():
        assert list(tables[name].columns) == [f for f, _, _ in fields], name
        assert len(tables[name]), name
    md = tables["MATDOC"]
    assert md["BUDAT"].str.fullmatch(r"\d{8}").all() and md["CPUTM"].str.fullmatch(r"\d{6}").all()
    assert set(md["BWART"]) <= {"101", "122", "321", "551", "553", "601"}
    assert set(md["SHKZG"]) == {"S", "H"}
    assert len(tables["LTAP"]) == len(src(run, "fact_transactions"))      # one warehouse task per scan
    assert len(tables["VBFA"]) == len(tables["VBAK"]) == len(tables["LIKP"])


def test_generated_sql_in_the_repo_is_current():
    """sap_hana/00 and 01 are generated: regenerate them (python analytics/export_sap.py) after editing TABLES."""
    with open(os.path.join(sap.SQL_DIR, "00_create_tables.sql"), encoding="utf-8") as fh:
        assert fh.read() == sap.ddl()
    with open(os.path.join(sap.SQL_DIR, "01_import.sql"), encoding="utf-8") as fh:
        assert fh.read() == sap.import_sql()


def test_otif_matches_the_simulation(extract):
    run, tables, con = extract
    r = sap.run_analysis(con, "03_otif_by_route.sql")
    o = src(run, "fact_orders")
    otif = ((o["on_time"] == 1) & (o["fill_rate"] >= 0.999)).mean() * 100
    assert r["ORDERS"].sum() == len(o)
    assert (r["OTIF_PCT"] * r["ORDERS"]).sum() / r["ORDERS"].sum() == pytest.approx(otif, abs=0.1)
    assert (r["ON_TIME_PCT"] * r["ORDERS"]).sum() / r["ORDERS"].sum() == pytest.approx(100 * o["on_time"].mean(), abs=0.1)
    lips = tables["LIPS"].assign(q=pd.to_numeric(tables["LIPS"]["LFIMG"])).groupby("VGBEL")["q"].sum()
    shipped = o.set_index(sap.doc("1", o["order_id"]))["cases_shipped"]
    assert (lips.reindex(shipped.index, fill_value=0) == shipped).all()   # delivered = shipped, order by order


def test_dock_to_stock_matches_the_putaway_dwell(extract):
    run, _, con = extract
    r = sap.run_analysis(con, "02_dock_to_stock.sql")
    p = src(run, "fact_putaway")
    assert (r["AVG_MIN"] * r["PALLETS"]).sum() / r["PALLETS"].sum() == pytest.approx(p["dock_dwell_min"].mean(), abs=0.5)


def test_batch_trace_finds_every_customer(extract):
    run, _, con = extract
    lots = src(run, "fact_shipment_lots")
    lot = lots.groupby("lot")["store_id"].nunique().idxmax()
    with open(os.path.join(sap.SQL_DIR, "04_batch_trace.sql"), encoding="utf-8") as fh:
        sql = fh.read().replace("'6370'", f"'{lot}'")
    r = con.execute(sap.hana_to_duckdb(sql)).df()
    assert set(r["KUNNR"]) == set(lots[lots["lot"] == lot]["store_id"])
    assert r["CASES"].sum() == lots[lots["lot"] == lot]["cases"].sum()


def test_vendor_receipts_match_the_dock(extract):
    run, _, con = extract
    r = sap.run_analysis(con, "05_vendor_quality.sql").set_index("LIFNR")
    rec = src(run, "fact_pallet_receipts")
    accepted = rec[rec["decision"] != "reject"].groupby("plant_code")["cases"].sum()
    assert (r["RECEIVED_CASES"].reindex(accepted.index) == accepted).all()
    refused = rec[rec["decision"] == "reject"].groupby("plant_code")["cases"].sum()
    assert (r["RETURNED_CASES"].reindex(refused.index) >= refused).all()   # door refusals + QA returns


def test_shim_translates_only_hana_spellings():
    sql = "SELECT SECONDS_BETWEEN(TO_TIMESTAMP(A || B, 'YYYYMMDDHH24MISS'), X), DAYS_BETWEEN(TO_DATE(D, 'YYYYMMDD'), E)"
    out = sap.hana_to_duckdb(sql)
    assert "date_diff('second', strptime(A || B, '%Y%m%d%H%M%S'), X)" in out
    assert "date_diff('day', CAST(strptime(D, '%Y%m%d') AS DATE), E)" in out
