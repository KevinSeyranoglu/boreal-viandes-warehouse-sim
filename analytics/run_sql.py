"""Run the KPI queries in analytics/sql/ against the SQLite database and print the results.

    python analytics/run_sql.py                         # every query, scenario baseline
    python analytics/run_sql.py 06 --scenario chaos     # one query (by number or name)
    python analytics/run_sql.py 07 --lot 4251           # recall trace for a lot
"""
from __future__ import annotations

import argparse
import glob
import os
import sqlite3

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(os.path.dirname(HERE), "data", "warehouse.db")


def queries(pattern=""):
    return [p for p in sorted(glob.glob(os.path.join(HERE, "sql", "*.sql"))) if pattern in os.path.basename(p)]


def default_lot(con, scenario):
    """A recalled lot if there was one (the most widely shipped), else the most widely shipped lot."""
    row = con.execute("""
        SELECT l.lot FROM fact_shipment_lots l
        WHERE l.scenario = :s AND l.lot IN (
            SELECT CAST(json_extract(detail, '$.lot') AS INTEGER) FROM fact_events
            WHERE scenario = :s AND event_type = 'ev_recall')
        GROUP BY l.lot ORDER BY COUNT(DISTINCT l.store_id) DESC LIMIT 1""", {"s": scenario}).fetchone()
    row = row or con.execute("""
        SELECT lot FROM fact_shipment_lots WHERE scenario = :s
        GROUP BY lot ORDER BY COUNT(DISTINCT store_id) DESC LIMIT 1""", {"s": scenario}).fetchone()
    return row[0] if row else 0


def run(path, con, params):
    with open(path, encoding="utf-8") as fh:
        sql = fh.read()
    return pd.read_sql_query(sql, con, params=params)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query", nargs="?", default="", help="number or part of a file name in analytics/sql/")
    ap.add_argument("--scenario", default="baseline")
    ap.add_argument("--lot", type=int)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--rows", type=int, default=15)
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        raise SystemExit(f"{args.db} not found. Build it first: python analytics/build_db.py")
    con = sqlite3.connect(args.db)
    params = {"scenario": args.scenario, "lot": args.lot or default_lot(con, args.scenario)}
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    for path in queries(args.query):
        df = run(path, con, params)
        print(f"\n=== {os.path.basename(path)}  ({len(df)} rows; scenario={args.scenario}, lot={params['lot']})")
        print(df.head(args.rows).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
