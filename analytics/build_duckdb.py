"""Load every headless run into one DuckDB database (typed columns, analytic views, optional Parquet).

    python analytics/build_duckdb.py                  # data/*_seed*/ -> data/warehouse.duckdb
    python analytics/build_duckdb.py --parquet        # also data/parquet/<table>/scenario=<name>/*.parquet

Same star schema as the SQLite build (analytics/build_db.py), but columnar and typed: timestamps are
TIMESTAMP, dates DATE, and barcodes (SSCC, GTIN) and document numbers stay text so leading zeros survive.
Each table is read from all run folders in one pass; `scenario` and `seed` come from the folder name.
The same KPI queries run on both: python analytics/run_sql.py --engine duckdb
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
import time

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_db  # noqa: E402
import config as C  # noqa: E402

TEXT_COLUMNS = {"sscc", "from_sscc", "to_sscc", "gtin", "gtin_case", "gtin_each", "po_number", "bol_number",
                "doc_no", "supplier_item", "location", "from_loc", "to_loc", "equipment_id", "detail", "mvt_type"}
DATE_COLUMNS = {"date", "pack_date", "best_before"}
# text columns besides identifiers, used to type tables that have no rows in any run (header only)
TEXT_NAMES = {"sku_code", "store_id", "route_id", "plant_code", "zone", "role", "shift", "reason", "category",
              "incident_type", "severity", "event_type", "decision", "kind", "txn_type", "doc_type", "name",
              "name_fr", "name_en", "city", "season", "temp_class", "loc_type", "level_code", "brand"}
SHARED_DIMS = build_db.SHARED_DIMS

# SQLite compatibility, so analytics/sql/*.sql runs unchanged
MACROS = ["CREATE OR REPLACE MACRO julianday(x) AS epoch(CAST(x AS TIMESTAMP)) / 86400.0 + 2440587.5"]

VIEWS = {
    "v_dock_to_stock": """
        SELECT r.scenario, r.sscc, r.sku_code, k.zone, r.ts AS received_ts, p.ts AS putaway_ts,
               date_diff('second', r.ts, p.ts) / 60.0 AS dock_to_stock_min, hour(r.ts) AS received_hour
        FROM fact_transactions r
        JOIN fact_transactions p ON p.scenario = r.scenario AND p.sscc = r.sscc AND p.txn_type = 'PUT'
        JOIN dim_sku k ON k.sku_code = r.sku_code
        WHERE r.txn_type IN ('RCV', 'RQA')""",
    "v_lot_trace": """
        SELECT p.scenario, p.lot, p.sku_code, p.from_sscc AS inbound_sscc, p.sscc AS outbound_sscc,
               p.cases, p.ts AS picked_ts, s.ts AS shipped_ts, replace(s.to_loc, 'CUST-', '') AS store_id,
               st.name AS store_name, st.city, s.doc_no AS bol
        FROM fact_transactions p
        LEFT JOIN fact_transactions s ON s.scenario = p.scenario AND s.sscc = p.sscc AND s.txn_type = 'SHP'
        LEFT JOIN dim_store st ON st.store_id = replace(s.to_loc, 'CUST-', '')
        WHERE p.txn_type = 'PCK'
          AND NOT EXISTS (SELECT 1 FROM fact_transactions r          -- lot taken off that pallet by a recall
                          WHERE r.scenario = p.scenario AND r.txn_type = 'RCL' AND r.sscc = p.sscc AND r.lot = p.lot)""",
    "v_pallet_history": """
        SELECT scenario, sscc, ts, txn_type, mvt_type, sku_code, lot, cases, weight_kg, from_loc, to_loc,
               user_id, equipment_id, doc_type, doc_no, reason,
               row_number() OVER (PARTITION BY scenario, sscc ORDER BY ts, txn_id) AS step
        FROM fact_transactions""",
    "v_order_service": """
        SELECT o.*, (o.on_time = 1 AND o.fill_rate >= 0.999)::INTEGER AS otif, s.name AS store_name, s.kind, s.city
        FROM fact_orders o JOIN dim_store s USING (store_id)""",
}


def header(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh), [])


def column_types(cols, empty=False):
    types = {}
    for c in cols:
        if empty and c not in DATE_COLUMNS and not (c == "ts" or c.endswith("_ts")):
            types[c] = "VARCHAR" if c in TEXT_COLUMNS | TEXT_NAMES else "DOUBLE"   # nothing to infer from
        elif c in TEXT_COLUMNS:
            types[c] = "VARCHAR"
        elif c in DATE_COLUMNS:
            types[c] = "DATE"
        elif c == "ts" or c.endswith("_ts"):
            types[c] = "TIMESTAMP"
    return types


def sql_types(types):
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in types.items()) + "}"


def build(runs, db_path, parquet_dir=None):
    if not runs:
        raise SystemExit("No run folders found. Generate data first: python main.py --headless --days 180")
    t0 = time.time()
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)
    tables = sorted({os.path.basename(p)[:-4] for r in runs for p in glob.glob(os.path.join(r, "*.csv"))})
    for table in tables:
        files = [os.path.join(r, table + ".csv") for r in runs if os.path.exists(os.path.join(r, table + ".csv"))]
        cols = header(files[0])
        empty = all(sum(1 for _ in open(f, encoding="utf-8")) <= 1 for f in files)
        types = column_types(cols, empty)
        if table in SHARED_DIMS:
            src = f"read_csv('{files[0]}', header=true, types={sql_types(types)})"
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM {src}")
            continue
        file_list = "[" + ", ".join(f"'{f}'" for f in files) + "]"
        src = (f"read_csv({file_list}, header=true, union_by_name=true, filename=true, "
               f"types={sql_types(types)})")
        con.execute(f"""
            CREATE TABLE {table} AS
            SELECT regexp_extract(filename, '([^/]+)_seed(\\d+)/[^/]+$', 1) AS scenario,
                   CAST(regexp_extract(filename, '_seed(\\d+)/[^/]+$', 1) AS INTEGER) AS seed,
                   * EXCLUDE (filename)
            FROM {src}""")
    dated = [t for (t,) in con.execute("SELECT DISTINCT table_name FROM information_schema.columns "
                                         "WHERE column_name = 'date'").fetchall()]
    dates = sorted({d for t in dated for (d,) in con.execute(
        f"SELECT DISTINCT CAST(date AS VARCHAR) FROM {t} WHERE date IS NOT NULL").fetchall()})
    dd = build_db.dim_date(dates)
    con.register("dd", dd)
    con.execute("CREATE TABLE dim_date AS SELECT CAST(date AS DATE) AS date, * EXCLUDE (date) FROM dd")
    con.unregister("dd")
    for m in MACROS:
        con.execute(m)
    for name, sql in VIEWS.items():
        con.execute(f"CREATE VIEW {name} AS {sql}")
    if parquet_dir:
        os.makedirs(parquet_dir, exist_ok=True)
        for (table,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE'").fetchall():
            cols = [c for (c,) in con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()]
            target = os.path.join(parquet_dir, table)
            part = ", PARTITION_BY (scenario), OVERWRITE_OR_IGNORE" if "scenario" in cols else ""
            con.execute(f"COPY {table} TO '{target}{'' if part else '.parquet'}' (FORMAT PARQUET{part})")
    n = con.execute("SELECT count(*) FROM information_schema.tables").fetchone()[0]
    con.close()
    print(f"{db_path}: {n} tables and views in {time.time() - t0:.0f} s")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", nargs="*", help="run folders (default: every data/*_seed* folder)")
    ap.add_argument("--db", default=os.path.join(ROOT, C.DATA_DIR, "warehouse.duckdb"))
    ap.add_argument("--parquet", nargs="?", const=os.path.join(ROOT, C.DATA_DIR, "parquet"), default=None,
                    help="also export every table to Parquet (partitioned by scenario)")
    args = ap.parse_args(argv)
    build(args.runs or build_db.run_dirs(os.path.join(ROOT, C.DATA_DIR)), args.db, args.parquet)


if __name__ == "__main__":
    main()
