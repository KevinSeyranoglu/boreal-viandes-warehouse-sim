"""Run the KPI queries in analytics/sql/ against the SQLite database and print the results.

    python analytics/run_sql.py                         # every query, scenario baseline
    python analytics/run_sql.py 06 --scenario chaos     # one query (by number or name)
    python analytics/run_sql.py 07 --lot 4251           # recall trace for a lot
    python analytics/run_sql.py --engine duckdb         # same queries on data/warehouse.duckdb
    python analytics/run_sql.py --engine duckdb --file analytics/duckdb_examples.sql
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(os.path.dirname(HERE), "data", "warehouse.db")
DEFAULT_DUCKDB = os.path.join(os.path.dirname(HERE), "data", "warehouse.duckdb")


def is_duckdb(con):
    return "duckdb" in type(con).__module__


def connect(engine="sqlite", db=None):
    if engine == "duckdb":
        import duckdb
        return duckdb.connect(db or DEFAULT_DUCKDB, read_only=True)
    return sqlite3.connect(db or DEFAULT_DB)


def query(con, sql, params):
    """Run a :named-parameter query on SQLite or DuckDB (DuckDB spells parameters $name)."""
    if is_duckdb(con):
        used = set(re.findall(r":(\w+)", sql))
        sql = re.sub(r":(\w+)", r"$\1", sql)
        return con.execute(sql, {k: v for k, v in params.items() if k in used}).df()
    return pd.read_sql_query(sql, con, params=params)


def queries(pattern=""):
    return [p for p in sorted(glob.glob(os.path.join(HERE, "sql", "*.sql"))) if pattern in os.path.basename(p)]


def default_lot(con, scenario):
    """A recalled lot if there was one (the most widely shipped), else the most widely shipped lot."""
    df = query(con, """
        SELECT l.lot FROM fact_shipment_lots l
        WHERE l.scenario = :s AND l.lot IN (
            SELECT CAST(json_extract(detail, '$.lot') AS INTEGER) FROM fact_events
            WHERE scenario = :s AND event_type = 'ev_recall')
        GROUP BY l.lot ORDER BY COUNT(DISTINCT l.store_id) DESC, l.lot LIMIT 1""", {"s": scenario})
    if df.empty:
        df = query(con, """
            SELECT lot FROM fact_shipment_lots WHERE scenario = :s
            GROUP BY lot ORDER BY COUNT(DISTINCT store_id) DESC, lot LIMIT 1""", {"s": scenario})
    return int(df.iloc[0, 0]) if len(df) else 0


def run(path, con, params):
    with open(path, encoding="utf-8") as fh:
        sql = fh.read()
    return query(con, sql, params)


def statements(path):
    """(title, sql) for each statement of a file; the title is the comment line just before it."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = []
    for chunk in text.split(";"):
        lines = [ln for ln in chunk.strip().splitlines()]
        titles = [ln[2:].strip() for ln in lines if ln.startswith("--")]
        sql = "\n".join(ln for ln in lines if not ln.startswith("--")).strip()
        if sql:
            out.append((titles[-1] if titles else "", sql))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query", nargs="?", default="", help="number or part of a file name in analytics/sql/")
    ap.add_argument("--scenario", default="baseline")
    ap.add_argument("--lot", type=int)
    ap.add_argument("--engine", choices=["sqlite", "duckdb"], default="sqlite")
    ap.add_argument("--db", default=None, help="database file (default data/warehouse.db or .duckdb)")
    ap.add_argument("--rows", type=int, default=15)
    ap.add_argument("--file", help="run every statement of this SQL file instead")
    args = ap.parse_args(argv)
    db = args.db or (DEFAULT_DUCKDB if args.engine == "duckdb" else DEFAULT_DB)
    if not os.path.exists(db):
        builder = "build_duckdb.py" if args.engine == "duckdb" else "build_db.py"
        raise SystemExit(f"{db} not found. Build it first: python analytics/{builder}")
    con = connect(args.engine, db)
    params = {"scenario": args.scenario, "lot": args.lot or default_lot(con, args.scenario)}
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    if args.file:
        for title, sql in statements(args.file):
            df = query(con, sql, params)
            print(f"\n=== {title}  ({len(df)} rows)")
            print(df.head(args.rows).to_string(index=False))
        return
    for path in queries(args.query):
        df = run(path, con, params)
        print(f"\n=== {os.path.basename(path)}  ({len(df)} rows; scenario={args.scenario}, lot={params['lot']})")
        print(df.head(args.rows).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
