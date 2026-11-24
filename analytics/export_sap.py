"""Export one run as SAP S/4HANA tables, with HANA SQL to create, load and analyse them.

    python analytics/export_sap.py                          # data/baseline_seed42 -> data/sap/
    python analytics/export_sap.py --run data/chaos_seed42
    python analytics/export_sap.py --check                  # also run the sap_hana/ analyses on DuckDB

What an SAP S/4HANA warehouse hands to the analytics team, next to the AS/400 extract:
- master data MARA, MAKT, MARM (units and GTINs), MCH1 (batches), LFA1 (vendors), KNA1 (customers),
- purchasing EKKO/EKPO, inventory postings MATDOC (movement types 101, 122, 321, 551, 553, 601),
  warehouse tasks LTAP (every scan, bin to bin, storage unit = SSCC),
- sales VBAK/VBAP, deliveries LIKP/LIPS (batch per line) and the document flow VBFA.
SAP field names; dates YYYYMMDD and times HHMMSS stored as text, as in the ABAP dictionary (DATS, TIMS).
Fields SAP does not have are Z fields (ZZ...), the usual convention for customer fields.
sap_hana/00_create_tables.sql and 01_import.sql are GENERATED from TABLES below, so they always match.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402
import masterdata as M  # noqa: E402

SCHEMA = "BOREAL"
WERKS = "BV01"                     # the distribution center as an SAP plant
LGNUM = "BV1"                      # its warehouse number
SQL_DIR = os.path.join(ROOT, "sap_hana")
LGORT = {zone: M.ROOM_CODE[zone] + "01" for zone in M.ROOM_CODE}    # storage location per room: FR01, TR01, CG01

# table -> (description, [(field, HANA type, description)])
TABLES = {
    "MARA": ("General material data", [
        ("MATNR", "NVARCHAR(40)", "Material"), ("MTART", "NVARCHAR(4)", "Material type (HAWA = trading goods)"),
        ("MATKL", "NVARCHAR(9)", "Material group"), ("MEINS", "NVARCHAR(3)", "Base unit (CS = case)"),
        ("BRGEW", "DECIMAL(13,3)", "Gross weight per case"), ("NTGEW", "DECIMAL(13,3)", "Net weight per case"),
        ("GEWEI", "NVARCHAR(3)", "Weight unit"), ("EAN11", "NVARCHAR(18)", "GTIN-14 of the case"),
        ("MHDHB", "INTEGER", "Total shelf life (days)"), ("RAUBE", "NVARCHAR(2)", "Storage conditions (room FR/TR/CG)"),
        ("XCHPF", "NVARCHAR(1)", "Batch management (X)"), ("ZZCATCH", "NVARCHAR(1)", "Catch weight (X)")]),
    "MAKT": ("Material descriptions", [
        ("MATNR", "NVARCHAR(40)", "Material"), ("SPRAS", "NVARCHAR(1)", "Language (F, E)"),
        ("MAKTX", "NVARCHAR(40)", "Description")]),
    "MARM": ("Units of measure", [
        ("MATNR", "NVARCHAR(40)", "Material"), ("MEINH", "NVARCHAR(3)", "Unit (CS case, ST piece)"),
        ("UMREZ", "INTEGER", "Numerator: base units"), ("UMREN", "INTEGER", "Denominator: alternative units"),
        ("EAN11", "NVARCHAR(18)", "GTIN of this unit")]),
    "MCH1": ("Batches", [
        ("MATNR", "NVARCHAR(40)", "Material"), ("CHARG", "NVARCHAR(10)", "Batch (lot)"),
        ("HSDAT", "NVARCHAR(8)", "Production (pack) date"), ("VFDAT", "NVARCHAR(8)", "Best-before date"),
        ("LIFNR", "NVARCHAR(10)", "Vendor (plant)")]),
    "LFA1": ("Vendors", [
        ("LIFNR", "NVARCHAR(10)", "Vendor"), ("NAME1", "NVARCHAR(35)", "Name"),
        ("LAND1", "NVARCHAR(3)", "Country"), ("REGIO", "NVARCHAR(3)", "Region")]),
    "KNA1": ("Customers", [
        ("KUNNR", "NVARCHAR(10)", "Customer (store)"), ("NAME1", "NVARCHAR(35)", "Name"),
        ("ORT01", "NVARCHAR(35)", "City"), ("LAND1", "NVARCHAR(3)", "Country"), ("REGIO", "NVARCHAR(3)", "Region"),
        ("KDGRP", "NVARCHAR(10)", "Customer group (grocery, club, restaurant)"),
        ("ZZROUTE", "NVARCHAR(6)", "Delivery route"), ("ZZSTOP", "INTEGER", "Stop on the route")]),
    "EKKO": ("Purchase order headers", [
        ("EBELN", "NVARCHAR(10)", "Purchase order"), ("BSART", "NVARCHAR(4)", "Order type (NB)"),
        ("LIFNR", "NVARCHAR(10)", "Vendor"), ("BEDAT", "NVARCHAR(8)", "Order date"),
        ("ZZEINDT", "NVARCHAR(8)", "Scheduled delivery date"), ("ZZEINTM", "NVARCHAR(6)", "Scheduled delivery time"),
        ("ZZPAL_ORD", "INTEGER", "Pallets ordered")]),
    "EKPO": ("Purchase order items (cases received per material)", [
        ("EBELN", "NVARCHAR(10)", "Purchase order"), ("EBELP", "NVARCHAR(5)", "Item"),
        ("MATNR", "NVARCHAR(40)", "Material"), ("WERKS", "NVARCHAR(4)", "Plant"),
        ("MENGE", "DECIMAL(13,3)", "Quantity"), ("MEINS", "NVARCHAR(3)", "Unit")]),
    "MATDOC": ("Material documents (inventory postings)", [
        ("MBLNR", "NVARCHAR(10)", "Material document"), ("MJAHR", "NVARCHAR(4)", "Year"),
        ("ZEILE", "NVARCHAR(4)", "Item"), ("BWART", "NVARCHAR(3)", "Movement type"),
        ("SHKZG", "NVARCHAR(1)", "Debit S / credit H"), ("MATNR", "NVARCHAR(40)", "Material"),
        ("WERKS", "NVARCHAR(4)", "Plant"), ("LGORT", "NVARCHAR(4)", "Storage location"),
        ("CHARG", "NVARCHAR(10)", "Batch"), ("INSMK", "NVARCHAR(1)", "Stock type (X = quality inspection)"),
        ("MENGE", "DECIMAL(13,3)", "Quantity"), ("MEINS", "NVARCHAR(3)", "Unit"),
        ("BUDAT", "NVARCHAR(8)", "Posting date"), ("CPUDT", "NVARCHAR(8)", "Entry date"),
        ("CPUTM", "NVARCHAR(6)", "Entry time"), ("USNAM", "NVARCHAR(12)", "User"),
        ("EBELN", "NVARCHAR(10)", "Purchase order"), ("LIFNR", "NVARCHAR(10)", "Vendor"),
        ("SGTXT", "NVARCHAR(50)", "Item text (reason)")]),
    "LTAP": ("Warehouse tasks: every confirmed scan, bin to bin", [
        ("LGNUM", "NVARCHAR(3)", "Warehouse number"), ("TANUM", "NVARCHAR(10)", "Transfer order"),
        ("TAPOS", "NVARCHAR(4)", "Item"), ("BWLVS", "NVARCHAR(3)", "Movement type (999 = internal move)"),
        ("ZZSCAN", "NVARCHAR(3)", "Scan type (RCV, TXI, PUT, PCK, BLD, LOD, SHP...)"),
        ("MATNR", "NVARCHAR(40)", "Material"), ("CHARG", "NVARCHAR(10)", "Batch"),
        ("VLPLA", "NVARCHAR(18)", "Source bin"), ("NLPLA", "NVARCHAR(18)", "Destination bin"),
        ("VLENR", "NVARCHAR(20)", "Source storage unit (SSCC)"), ("NLENR", "NVARCHAR(20)", "Destination storage unit (SSCC)"),
        ("VSOLM", "DECIMAL(13,3)", "Quantity (cases)"), ("ALTME", "NVARCHAR(3)", "Unit"),
        ("BRGEW", "DECIMAL(13,3)", "Weight (kg)"), ("QNAME", "NVARCHAR(12)", "Confirmed by"),
        ("QDATU", "NVARCHAR(8)", "Confirmation date"), ("QZEIT", "NVARCHAR(6)", "Confirmation time")]),
    "VBAK": ("Sales order headers", [
        ("VBELN", "NVARCHAR(10)", "Sales order"), ("AUART", "NVARCHAR(4)", "Order type (OR, ZRUS = rush)"),
        ("KUNNR", "NVARCHAR(10)", "Sold-to (store)"), ("ERDAT", "NVARCHAR(8)", "Created on"),
        ("ERZET", "NVARCHAR(6)", "Created at"), ("VDATU", "NVARCHAR(8)", "Requested delivery date"),
        ("NETWR", "DECIMAL(15,2)", "Net value")]),
    "VBAP": ("Sales order items", [
        ("VBELN", "NVARCHAR(10)", "Sales order"), ("POSNR", "NVARCHAR(6)", "Item"),
        ("MATNR", "NVARCHAR(40)", "Material"), ("KWMENG", "DECIMAL(15,3)", "Ordered quantity"),
        ("VRKME", "NVARCHAR(3)", "Sales unit")]),
    "LIKP": ("Outbound delivery headers", [
        ("VBELN", "NVARCHAR(10)", "Delivery"), ("LFART", "NVARCHAR(4)", "Delivery type (LF)"),
        ("KUNNR", "NVARCHAR(10)", "Ship-to (store)"), ("ROUTE", "NVARCHAR(6)", "Route"),
        ("VSART", "NVARCHAR(2)", "Shipping type (01 route truck, 02 expedited)"),
        ("WADAT", "NVARCHAR(8)", "Planned goods issue date"), ("WAUHR", "NVARCHAR(6)", "Planned goods issue time"),
        ("WADAT_IST", "NVARCHAR(8)", "Actual goods issue date"), ("ZZWAUHR_IST", "NVARCHAR(6)", "Actual goods issue time")]),
    "LIPS": ("Outbound delivery items (one per batch shipped)", [
        ("VBELN", "NVARCHAR(10)", "Delivery"), ("POSNR", "NVARCHAR(6)", "Item"),
        ("MATNR", "NVARCHAR(40)", "Material"), ("CHARG", "NVARCHAR(10)", "Batch"),
        ("LFIMG", "DECIMAL(13,3)", "Delivered quantity"), ("VRKME", "NVARCHAR(3)", "Unit"),
        ("VGBEL", "NVARCHAR(10)", "Reference sales order")]),
    "VBFA": ("Sales document flow (order -> delivery)", [
        ("VBELV", "NVARCHAR(10)", "Preceding document (sales order)"), ("VBELN", "NVARCHAR(10)", "Subsequent document (delivery)"),
        ("VBTYP_N", "NVARCHAR(1)", "Subsequent category (J = delivery)")]),
}


def dats(ts):
    return ts.str[:10].str.replace("-", "", regex=False).fillna("")


def tims(ts):
    return ts.str[11:19].str.replace(":", "", regex=False).fillna("")


def doc(prefix, ids, width=10):
    return prefix + ids.astype(str).str.zfill(width - len(prefix))


def read(run, table):
    return pd.read_csv(os.path.join(run, table + ".csv"), dtype=str, keep_default_na=False)


def build(run):
    """{table: DataFrame} with exactly the TABLES columns, in order."""
    sku, store, plant = read(run, "dim_sku"), read(run, "dim_store"), read(run, "dim_plant")
    tx, rec, trucks = read(run, "fact_transactions"), read(run, "fact_pallet_receipts"), read(run, "fact_inbound_trucks")
    orders, lines, lots = read(run, "fact_orders"), read(run, "fact_order_lines"), read(run, "fact_shipment_lots")
    zone = dict(zip(sku["sku_code"], sku["zone"]))
    out = {}
    out["MARA"] = pd.DataFrame({
        "MATNR": sku["sku_code"], "MTART": "HAWA", "MATKL": sku["category"], "MEINS": "CS",
        "BRGEW": sku["gross_kg_nominal"], "NTGEW": sku["net_kg_nominal"], "GEWEI": "KG", "EAN11": sku["gtin_case"],
        "MHDHB": sku["shelf_life_days"], "RAUBE": sku["zone"].map(M.ROOM_CODE),
        "XCHPF": sku["lot_controlled"].map(lambda v: "X" if v == "1" else ""),
        "ZZCATCH": sku["catch_weight"].map(lambda v: "X" if v == "1" else "")})
    out["MAKT"] = pd.concat([pd.DataFrame({"MATNR": sku["sku_code"], "SPRAS": lang, "MAKTX": sku[col]})
                             for lang, col in (("F", "name_fr"), ("E", "name_en"))]).sort_values(["MATNR", "SPRAS"])
    out["MARM"] = pd.concat([
        pd.DataFrame({"MATNR": sku["sku_code"], "MEINH": "CS", "UMREZ": "1", "UMREN": "1", "EAN11": sku["gtin_case"]}),
        pd.DataFrame({"MATNR": sku["sku_code"], "MEINH": "ST", "UMREZ": "1", "UMREN": sku["pieces_per_case"],
                      "EAN11": sku["gtin_each"]})]).sort_values(["MATNR", "MEINH"])
    out["MCH1"] = (rec.drop_duplicates(["sku_code", "lot"])
                   .assign(MATNR=lambda d: d["sku_code"], CHARG=lambda d: d["lot"], HSDAT=lambda d: dats(d["pack_date"]),
                           VFDAT=lambda d: dats(d["best_before"]), LIFNR=lambda d: d["plant_code"]))
    out["LFA1"] = pd.DataFrame({"LIFNR": plant["plant_code"], "NAME1": plant["name_fr"], "LAND1": "CA", "REGIO": "QC"})
    out["KNA1"] = pd.DataFrame({"KUNNR": store["store_id"], "NAME1": store["name"], "ORT01": store["city"], "LAND1": "CA",
                                "REGIO": "QC", "KDGRP": store["kind"], "ZZROUTE": store["route_id"], "ZZSTOP": store["stop"]})
    out["EKKO"] = pd.DataFrame({"EBELN": trucks["po_number"], "BSART": "NB", "LIFNR": trucks["plant_code"],
                                "BEDAT": dats(trucks["scheduled_ts"]), "ZZEINDT": dats(trucks["scheduled_ts"]),
                                "ZZEINTM": tims(trucks["scheduled_ts"]), "ZZPAL_ORD": trucks["pallets_ordered"]})
    po = (rec.assign(cases=pd.to_numeric(rec["cases"])).groupby(["po_number", "sku_code"], as_index=False)["cases"].sum()
          .sort_values(["po_number", "sku_code"]))
    po["EBELP"] = ((po.groupby("po_number").cumcount() + 1) * 10).astype(str).str.zfill(5)
    out["EKPO"] = pd.DataFrame({"EBELN": po["po_number"], "EBELP": po["EBELP"], "MATNR": po["sku_code"], "WERKS": WERKS,
                                "MENGE": po["cases"], "MEINS": "CS"})

    # MATDOC: inventory-relevant scans; a 321 release from quality inspection posts two items (QI out, unrestricted in)
    vendor = dict(zip(trucks["po_number"], trucks["plant_code"]))
    m = tx[tx["mvt_type"].isin(["101", "122", "321", "551", "553", "601"])].copy()
    m["cases_abs"] = pd.to_numeric(m["cases"]).abs()
    base = pd.DataFrame({
        "MBLNR": doc("49", m["txn_id"]), "MJAHR": m["ts"].str[:4], "BWART": m["mvt_type"], "MATNR": m["sku_code"],
        "WERKS": WERKS, "LGORT": m["sku_code"].map(zone).map(LGORT), "CHARG": m["lot"], "MENGE": m["cases_abs"],
        "MEINS": "CS", "BUDAT": dats(m["ts"]), "CPUDT": dats(m["ts"]), "CPUTM": tims(m["ts"]), "USNAM": m["user_id"],
        "EBELN": m["doc_no"].where(m["doc_type"] == "PO", ""), "SGTXT": m["reason"].str[:50]})
    base["LIFNR"] = base["EBELN"].map(vendor).fillna("")
    qi_in = (m["txn_type"] == "RQA").to_numpy()                       # received into quality inspection
    first = base.assign(ZEILE="0001", SHKZG=m["mvt_type"].map(lambda b: "S" if b == "101" else "H").to_numpy(),
                        INSMK=["X" if q or b in ("321", "553") else "" for q, b in zip(qi_in, m["mvt_type"])])
    second = base[base["BWART"] == "321"].assign(ZEILE="0002", SHKZG="S", INSMK="")
    out["MATDOC"] = pd.concat([first, second]).sort_values(["MBLNR", "ZEILE"])

    out["LTAP"] = pd.DataFrame({
        "LGNUM": LGNUM, "TANUM": tx["txn_id"].str.zfill(10), "TAPOS": "0001",
        "BWLVS": tx["mvt_type"].replace("", "999"), "ZZSCAN": tx["txn_type"], "MATNR": tx["sku_code"], "CHARG": tx["lot"],
        "VLPLA": tx["from_loc"].str[:18], "NLPLA": tx["to_loc"].str[:18], "VLENR": tx["from_sscc"], "NLENR": tx["sscc"],
        "VSOLM": pd.to_numeric(tx["cases"], errors="coerce").abs(), "ALTME": "CS", "BRGEW": tx["weight_kg"],
        "QNAME": tx["user_id"], "QDATU": dats(tx["ts"]), "QZEIT": tims(tx["ts"])})

    so = doc("1", orders["order_id"])
    out["VBAK"] = pd.DataFrame({"VBELN": so, "AUART": orders["rush"].map(lambda r: "ZRUS" if r == "1" else "OR"),
                                "KUNNR": orders["store_id"], "ERDAT": dats(orders["created_ts"]),
                                "ERZET": tims(orders["created_ts"]), "VDATU": dats(orders["scheduled_departure_ts"]),
                                "NETWR": orders["revenue"]})
    lines = lines.sort_values(["order_id", "sku_code"], key=lambda s: s.astype(int) if s.name == "order_id" else s)
    out["VBAP"] = pd.DataFrame({"VBELN": doc("1", lines["order_id"]),
                                "POSNR": ((lines.groupby("order_id").cumcount() + 1) * 10).astype(str).str.zfill(6),
                                "MATNR": lines["sku_code"], "KWMENG": lines["cases_ordered"], "VRKME": "CS"})
    planned = pd.to_datetime(orders["scheduled_departure_ts"])
    actual = planned + pd.to_timedelta(pd.to_numeric(orders["late_min"]).fillna(0), unit="min")
    act = actual.dt.strftime("%Y-%m-%d %H:%M:%S")
    dl = doc("8", orders["order_id"])
    out["LIKP"] = pd.DataFrame({"VBELN": dl, "LFART": "LF", "KUNNR": orders["store_id"], "ROUTE": orders["route_id"],
                                "VSART": orders["expedited"].map(lambda e: "02" if e == "1" else "01"),
                                "WADAT": dats(orders["scheduled_departure_ts"]), "WAUHR": tims(orders["scheduled_departure_ts"]),
                                "WADAT_IST": dats(act), "ZZWAUHR_IST": tims(act)})
    lots = lots.sort_values(["order_id", "sku_code", "lot"], key=lambda s: s.astype(int) if s.name == "order_id" else s)
    out["LIPS"] = pd.DataFrame({"VBELN": doc("8", lots["order_id"]),
                                "POSNR": ((lots.groupby("order_id").cumcount() + 1) * 10).astype(str).str.zfill(6),
                                "MATNR": lots["sku_code"], "CHARG": lots["lot"], "LFIMG": lots["cases"], "VRKME": "CS",
                                "VGBEL": doc("1", lots["order_id"])})
    out["VBFA"] = pd.DataFrame({"VBELV": so, "VBELN": dl, "VBTYP_N": "J"})
    return {t: out[t][[f for f, _, _ in TABLES[t][1]]].reset_index(drop=True) for t in TABLES}


def ddl():
    lines = ["-- Generated by analytics/export_sap.py: SAP S/4HANA-style tables for the Boréal Viandes extract.",
             f"CREATE SCHEMA {SCHEMA};", ""]
    for t, (desc, fields) in TABLES.items():
        cols = "\n".join(f"    {f:<12} {typ + (',' if i < len(fields) - 1 else ''):<15} -- {d}"
                         for i, (f, typ, d) in enumerate(fields))
        lines += [f"-- {t}: {desc}", f"CREATE COLUMN TABLE {SCHEMA}.{t} (\n{cols}\n);", ""]
    return "\n".join(lines)


def import_sql(folder="/hana/work/boreal"):
    lines = ["-- Generated by analytics/export_sap.py. Copy data/sap/*.csv to a folder the HANA server can read",
             f"-- (here {folder}), or use Import Data in SAP HANA Database Explorer (HANA Cloud) with the same files.", ""]
    for t in TABLES:
        lines.append(f"IMPORT FROM CSV FILE '{folder}/{t}.csv' INTO {SCHEMA}.{t}\n"
                     "    WITH RECORD DELIMITED BY '\\n' FIELD DELIMITED BY ',' OPTIONALLY ENCLOSED BY '\"'\n"
                     f"    SKIP FIRST 1 ROW ERROR LOG '{folder}/{t}.err';")
    return "\n".join(lines) + "\n"


# The analyses are written in HANA SQL. To check them without a HANA server, this shim translates the few
# HANA-only spellings they use into DuckDB SQL; everything else is standard SQL that both accept.
_SHIM = [
    (re.compile(r"\bNVARCHAR\b"), "VARCHAR"),
    (re.compile(r"CREATE COLUMN TABLE"), "CREATE TABLE"),
    (re.compile(r"TO_TIMESTAMP\(([^,]+?),\s*'YYYYMMDDHH24MISS'\)"), r"strptime(\1, '%Y%m%d%H%M%S')"),
    (re.compile(r"TO_DATE\(([^,]+?),\s*'YYYYMMDD'\)"), r"CAST(strptime(\1, '%Y%m%d') AS DATE)"),
    (re.compile(r"SECONDS_BETWEEN\("), "date_diff('second', "),
    (re.compile(r"DAYS_BETWEEN\("), "date_diff('day', "),
]


def hana_to_duckdb(sql):
    for pat, rep in _SHIM:
        sql = pat.sub(rep, sql)
    return sql


def load_duckdb(tables, con=None):
    """Create the generated HANA tables in DuckDB (through the shim) and insert the extract."""
    import duckdb
    con = con or duckdb.connect()
    for stmt in hana_to_duckdb(ddl()).split(";"):
        body = "\n".join(line.split("--")[0] for line in stmt.splitlines()).strip()
        if body:
            con.execute(body)
    con.execute("CREATE TABLE DUMMY (DUMMY VARCHAR)")          # HANA's one-row table
    con.execute("INSERT INTO DUMMY VALUES ('X')")
    for t, df in tables.items():
        con.register("src", df.astype(str).replace({"nan": None, "": None}))
        con.execute(f"INSERT INTO {SCHEMA}.{t} SELECT * FROM src")
        con.unregister("src")
    return con


def analyses():
    return sorted(f for f in os.listdir(SQL_DIR) if re.match(r"0[2-9]_.*\.sql$", f))


def run_analysis(con, name):
    with open(os.path.join(SQL_DIR, name), encoding="utf-8") as fh:
        return con.execute(hana_to_duckdb(fh.read())).df()


def export(run, out_dir, sql_dir=SQL_DIR):
    tables = build(run)
    os.makedirs(out_dir, exist_ok=True)
    for t, df in tables.items():
        df.to_csv(os.path.join(out_dir, f"{t}.csv"), index=False)
    if sql_dir:
        os.makedirs(sql_dir, exist_ok=True)
        with open(os.path.join(sql_dir, "00_create_tables.sql"), "w", encoding="utf-8") as fh:
            fh.write(ddl())
        with open(os.path.join(sql_dir, "01_import.sql"), "w", encoding="utf-8") as fh:
            fh.write(import_sql())
    print(f"{len(tables)} SAP tables, {sum(len(d) for d in tables.values()):,} rows -> {out_dir}")
    return tables


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default=os.path.join(ROOT, C.DATA_DIR, "baseline_seed42"))
    ap.add_argument("--out", default=os.path.join(ROOT, C.DATA_DIR, "sap"))
    ap.add_argument("--check", action="store_true", help="run the sap_hana/ analyses on DuckDB through the shim")
    args = ap.parse_args(argv)
    tables = export(args.run, args.out)
    if args.check:
        con = load_duckdb(tables)
        for name in analyses():
            print(f"=== {name}")
            print(run_analysis(con, name).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
