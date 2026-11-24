"""WMS scan log, master data and the AS/400 extract on a short headless run."""
from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import export_as400  # noqa: E402
import masterdata as M  # noqa: E402


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("wms") / "baseline_seed4"
    subprocess.run([sys.executable, "main.py", "--headless", "--days", "3", "--seed", "4", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    read = lambda t: pd.read_csv(out / f"{t}.csv", dtype={"sscc": str, "from_sscc": str, "to_sscc": str,
                                                         "gtin": str, "gtin_case": str, "gtin_each": str})
    return out, read


def test_sscc_and_gtin_check_digits(run):
    _, read = run
    t = read("fact_transactions")
    for code in pd.concat([t["sscc"], read("dim_sku")["gtin_case"]]).dropna().unique():
        assert code[-1] == M.check_digit(code[:-1]), code
    rcv = t[t.txn_type.isin(["RCV", "RQA", "REJ"])]
    assert rcv["sscc"].is_unique and rcv["sscc"].str.len().eq(18).all()


def test_pallet_life_is_in_order(run):
    _, read = run
    t = read("fact_transactions")
    first = t.pivot_table(index="sscc", columns="txn_type", values="ts", aggfunc="min")
    done = first.dropna(subset=["RCV", "TXI", "PUT"])
    assert len(done) > 50
    assert (done["RCV"] <= done["TXI"]).all() and (done["TXI"] <= done["PUT"]).all()


def test_case_quantities_agree(run):
    _, read = run
    t, picks = read("fact_transactions"), read("fact_picks")
    pck = t[t.txn_type == "PCK"]
    assert pck["cases"].sum() == picks["cases"].sum()                       # scan log = pick table
    built = t[t.txn_type == "BLD"].set_index("sscc")["cases"]
    picked = pck.groupby("sscc")["cases"].sum()
    assert (picked.loc[built.index] == built).all()                         # pallet = sum of its picks
    shp = t[t.txn_type == "SHP"].set_index("sscc")["cases"]
    assert (shp <= built.loc[shp.index]).all()                              # recall removals only reduce


def test_scan_locations_exist_and_item_master_is_consistent(run):
    _, read = run
    t, loc, sku = read("fact_transactions"), read("dim_location"), read("dim_sku")
    codes = set(loc["location"])
    used = set(t["from_loc"].dropna()) | set(t["to_loc"].dropna())
    internal = {c for c in used if c.split("-")[0] in ("FR", "TR", "CG", "STG", "PD", "QA")}
    assert internal <= codes
    assert (sku["ti"] * sku["hi"] == sku["cases_per_pallet"]).all()
    assert ((sku["net_kg_nominal"] + sku["tare_kg"] - sku["gross_kg_nominal"]).abs() < 0.01).all()


def test_as400_extract_reads_back_at_documented_positions(run, tmp_path):
    out, _ = run
    counts = export_as400.export(str(out), str(tmp_path / "as400"))
    for name, (_desc, table, fields) in export_as400.LAYOUTS.items():
        pos = export_as400.positions(fields)
        width = sum(f[2] for f in fields)
        lines = (tmp_path / "as400" / f"{name}.TXT").read_text(encoding="cp1252").splitlines()
        assert len(lines) == counts[name]
        assert all(len(line) == width for line in lines), name
        fixed = pd.read_fwf(tmp_path / "as400" / f"{name}.TXT", colspecs=[(p[4] - 1, p[5]) for p in pos],
                            names=[p[0] for p in pos], dtype=str, encoding="cp1252", keep_default_na=False)
        csv = pd.read_csv(tmp_path / "as400" / f"{name}.CSV", dtype=str, encoding="cp1252", keep_default_na=False)
        pd.testing.assert_frame_equal(fixed.apply(lambda c: c.str.strip()), csv, check_dtype=False)
    assert export_as400.cyymmdd("2026-12-01 05:30:10") == 1261201
    assert export_as400.cyymmdd("1999-07-04") == 990704
    assert export_as400.hhmmss("2026-12-01 05:30:10") == 53010
