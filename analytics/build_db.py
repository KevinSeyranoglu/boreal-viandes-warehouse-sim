"""Load headless runs (data/<scenario>_seed<seed>/*.csv) into one SQLite star schema.

    python analytics/build_db.py                       # every run folder in data/
    python analytics/build_db.py --runs data/baseline_seed42 --db data/warehouse.db

Every fact table gets `scenario` and `seed` columns so runs can be compared in SQL
or Power BI. Shared dimensions (SKU, store, route, plant, zone) are stored once;
dim_worker is per run. dim_date is generated with French and English names.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402

SHARED_DIMS = ("dim_sku", "dim_store", "dim_route", "dim_plant", "dim_zone", "dim_location")
RUN_RE = re.compile(r"^(?P<scenario>.+)_seed(?P<seed>\d+)$")

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

INDEXES = {
    "fact_orders": ["order_id", "store_id", "scheduled_departure_ts"],
    "fact_order_lines": ["order_id", "sku_code"],
    "fact_picks": ["order_id", "picker_id", "sku_code", "lot"],
    "fact_shipment_lots": ["lot", "store_id"],
    "fact_pallet_receipts": ["pallet_id", "lot", "truck_id"],
    "fact_temperature": ["zone", "ts"],
    "fact_inventory_daily": ["date", "sku_code"],
    "fact_daily_kpi": ["date"],
    "fact_transactions": ["sscc", "txn_type", "sku_code", "lot", "ts"],
}


def run_dirs(data_dir):
    return sorted(d for d in glob.glob(os.path.join(data_dir, "*_seed*")) if os.path.isdir(d))


def season_of(d):
    md = (d.month, d.day)
    for name, (start, end, _, _) in C.SEASONS.items():
        if start <= md <= end:
            return name
    return ""


def dim_date(dates):
    days = pd.to_datetime(sorted(set(dates)))
    return pd.DataFrame({
        "date": days.strftime("%Y-%m-%d"),
        "year": days.year,
        "month": days.month,
        "month_fr": [MONTHS_FR[m - 1] for m in days.month],
        "month_en": days.strftime("%B"),
        "day": days.day,
        "weekday": days.day_of_week + 1,                   # 1 = Monday
        "weekday_fr": [DAYS_FR[w] for w in days.day_of_week],
        "weekday_en": days.strftime("%A"),
        "iso_week": days.isocalendar().week.astype(int).values,
        "is_weekend": (days.day_of_week >= 5).astype(int),
        "season": [season_of(d) for d in days],
    })


def build(runs, db_path):
    if not runs:
        raise SystemExit("No run folders found. Generate data first: python main.py --headless --days 180")
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(db_path)
    dates, written = [], set()
    for run in runs:
        m = RUN_RE.match(os.path.basename(run.rstrip("/")))
        scenario, seed = (m["scenario"], int(m["seed"])) if m else (os.path.basename(run), 0)
        for path in sorted(glob.glob(os.path.join(run, "*.csv"))):
            table = os.path.basename(path)[:-4]
            df = pd.read_csv(path, low_memory=False)
            if table in SHARED_DIMS:
                if table in written:
                    continue
            else:
                df.insert(0, "seed", seed)
                df.insert(0, "scenario", scenario)
            if "date" in df.columns:
                dates.extend(df["date"].dropna().unique())
            df.to_sql(table, con, if_exists="append", index=False)
            written.add(table)
        print(f"loaded {scenario} (seed {seed})")
    dim_date(dates).to_sql("dim_date", con, index=False)
    for table, cols in INDEXES.items():
        if table in written:
            for col in cols:
                con.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} (scenario, {col})")
    con.commit()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    con.close()
    print(f"{db_path}: {len(tables)} tables")
    return tables


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", nargs="*", help="run folders (default: every data/*_seed* folder)")
    ap.add_argument("--db", default=os.path.join(ROOT, C.DATA_DIR, "warehouse.db"))
    args = ap.parse_args(argv)
    build(args.runs or run_dirs(os.path.join(ROOT, C.DATA_DIR)), args.db)


if __name__ == "__main__":
    main()
