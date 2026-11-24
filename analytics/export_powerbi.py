"""Export the SQLite star schema as Power BI-ready CSVs, plus the expected value of every DAX measure.

    python analytics/export_powerbi.py                 # data/warehouse.db -> data/powerbi/

Power BI relationships use one column, so composite keys (scenario + id) become single text keys
(`worker_key`, `order_key`, ...). Every fact table gets a `date` column for dim_date.
Temperature is pre-aggregated to one row per zone and hour. `_expected_measures.csv` holds what each
measure in dashboard/POWERBI_GUIDE.md must show for each scenario: use it to check the report.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402

SCENARIO_LABELS = {
    "baseline": ("Référence", "Baseline", "Current crew and normal incident rates"),
    "lean_staff": ("Effectif réduit", "Lean staff", "2 pickers fewer per shift, fewer drivers"),
    "extra_pickers": ("Préparateurs +", "Extra pickers", "+4 pickers per shift"),
    "chaos": ("Chaos", "Chaos", "3x more late trucks, failures and accidents"),
    "summer_bbq": ("BBQ d'été", "Summer BBQ", "June start: barbecue season peak"),
    "shared_dock": ("Quai partagé", "Shared dock", "14 doors on one wall both receive and ship (U-flow)"),
}

# fact table -> (timestamp column that defines its date, {id column: key prefix})
FACTS = {
    "fact_orders": ("scheduled_departure_ts", {"order_id": "order"}),
    "fact_order_lines": (None, {"order_id": "order"}),
    "fact_picks": ("start_ts", {"order_id": "order", "picker_id": "worker"}),
    "fact_shipments": ("scheduled_departure_ts", {}),
    "fact_shipment_lots": ("shipped_ts", {"order_id": "order"}),
    "fact_inbound_trucks": ("gate_ts", {}),
    "fact_pallet_receipts": ("received_ts", {"receiver_id": "worker"}),
    "fact_putaway": ("end_ts", {"operator_id": "worker"}),
    "fact_inventory_daily": (None, {}),
    "fact_spoilage": ("ts", {}),
    "fact_incidents": ("ts", {"worker_id": "worker"}),
    "fact_labor": (None, {"worker_id": "worker"}),
    "fact_equipment": ("ts", {}),
    "fact_events": ("ts", {}),
    "fact_daily_kpi": (None, {}),
    "fact_energy_daily": (None, {}),
    "fact_weather": (None, {}),
}
KEY_COLUMN = {"order": "order_key", "worker": "worker_key"}


def key(scenario, ids):
    return scenario.astype(str) + "|" + ids.astype("Int64").astype(str)


def load(con, table):
    return pd.read_sql_query(f"SELECT * FROM {table}", con)


def export(db_path, out_dir):
    con = sqlite3.connect(db_path)
    os.makedirs(out_dir, exist_ok=True)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    written = {}

    for dim in ("dim_sku", "dim_store", "dim_route", "dim_plant", "dim_zone", "dim_date"):
        written[dim] = load(con, dim)
    w = load(con, "dim_worker")
    w.insert(0, "worker_key", key(w["scenario"], w["worker_id"]))
    written["dim_worker"] = w
    scen = sorted(pd.read_sql_query("SELECT DISTINCT scenario FROM fact_daily_kpi", con)["scenario"])
    written["dim_scenario"] = pd.DataFrame(
        [{"scenario": s, "label_fr": SCENARIO_LABELS.get(s, (s, s, ""))[0],
          "label_en": SCENARIO_LABELS.get(s, (s, s, ""))[1], "description": SCENARIO_LABELS.get(s, (s, s, ""))[2],
          "sort": i} for i, s in enumerate(sorted(scen, key=lambda s: list(SCENARIO_LABELS).index(s)
                                                  if s in SCENARIO_LABELS else 99))])

    for table, (ts_col, keys) in FACTS.items():
        if table not in tables:
            continue
        df = load(con, table)
        for col, prefix in keys.items():
            df[KEY_COLUMN[prefix]] = key(df["scenario"], df[col])
        if ts_col:
            df["date"] = df[ts_col].astype(str).str[:10]
        if table == "fact_inbound_trucks":
            gate, dock = pd.to_datetime(df["gate_ts"]), pd.to_datetime(df["dock_ts"])
            df["yard_wait_min"] = ((dock - gate).dt.total_seconds() / 60).round(1)
            df["gate_hour"] = gate.dt.hour
        if table == "fact_orders":
            df["otif"] = ((df["on_time"] == 1) & (df["fill_rate"] >= 0.999)).astype(int)
        written[table] = df
    if "fact_order_lines" in written and "fact_orders" in written:   # lines take their order's date
        dates = written["fact_orders"][["order_key", "date"]]
        written["fact_order_lines"] = written["fact_order_lines"].merge(dates, on="order_key", how="left")

    t = pd.read_sql_query("""
        SELECT t.scenario, substr(t.ts, 1, 10) AS date, CAST(substr(t.ts, 12, 2) AS INTEGER) AS hour, t.zone,
               ROUND(AVG(t.temp_c), 2) AS avg_temp_c, ROUND(MAX(t.temp_c), 2) AS max_temp_c,
               COUNT(*) AS readings,
               SUM(CASE WHEN t.temp_c BETWEEN z.min_c AND z.max_c THEN 1 ELSE 0 END) AS readings_in_spec,
               MAX(t.alarm) AS alarm
        FROM fact_temperature t JOIN dim_zone z USING (zone)
        GROUP BY t.scenario, date, hour, t.zone""", con)
    written["fact_temperature_hourly"] = t
    con.close()

    for name, df in written.items():
        df.to_csv(os.path.join(out_dir, name + ".csv"), index=False)
    expected = expected_measures(written)
    expected.to_csv(os.path.join(out_dir, "_expected_measures.csv"), index=False)
    print(f"{out_dir}: {len(written)} tables")
    print(expected.to_string(index=False))
    return written, expected


def expected_measures(t):
    """Each DAX measure of the guide, computed the same way per scenario (the report must match)."""
    rows = []
    for s in t["dim_scenario"]["scenario"]:
        def f(name):
            df = t[name]
            return df[df["scenario"] == s]
        o, k, inc, lab = f("fact_orders"), f("fact_daily_kpi"), f("fact_incidents"), f("fact_labor")
        tr, sp, pk, th = f("fact_inbound_trucks"), f("fact_spoilage"), f("fact_picks"), f("fact_temperature_hourly")
        picker_h = lab.loc[lab["role"] == "picker", "hours"].sum()
        lost = int((inc["severity"] == "lost_time").sum())
        rows.append({
            "scenario": s,
            "Orders": len(o),
            "On-Time %": round(o["on_time"].mean(), 4),
            "OTIF %": round(o["otif"].mean(), 4),
            "Fill Rate %": round(o["cases_shipped"].sum() / o["cases_ordered"].sum(), 4),
            "Cases Shipped": int(o["cases_shipped"].sum()),
            "Cases per Picker Hour": round(pk["cases"].sum() / picker_h, 1),
            "Spoilage $": round(sp["value"].sum(), 0),
            "Spoilage %": round(sp["cases"].sum() / o["cases_shipped"].sum(), 5),
            "Air Temp In Spec %": round(th["readings_in_spec"].sum() / th["readings"].sum(), 4),
            "Cold-Chain Compliance %": round(k["compliance"].mean(), 4),
            "Avg Yard Wait (min)": round(tr["yard_wait_min"].mean(), 1),
            "Supplier On-Time %": round((tr["late_min"] <= 15).mean(), 4),
            "Short-Ship %": round(1 - tr["pallets"].sum() / tr["pallets_ordered"].sum(), 4),
            "Profit per Day $": round(k["profit"].sum() / k["date"].nunique(), 0),
            "Lost-Time Injuries": lost,
            "LTI Rate per 100 FTE": round(lost * C.FTE_HOURS_PER_YEAR * 100 / lab["hours"].sum(), 2),
        })
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join(ROOT, C.DATA_DIR, "warehouse.db"))
    ap.add_argument("--out", default=os.path.join(ROOT, C.DATA_DIR, "powerbi"))
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        raise SystemExit(f"{args.db} not found. Build it first: python analytics/build_db.py")
    export(args.db, args.out)


if __name__ == "__main__":
    main()
