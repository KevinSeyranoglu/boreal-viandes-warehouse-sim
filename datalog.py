"""Operational data export: a star schema of dim_* / fact_* CSV tables.

The simulation calls row(table, **fields) at every business event. CsvLog
buffers rows and appends them to <out_dir>/<table>.csv; the files load
straight into Power BI, pandas or SQLite. NullLog drops everything (the
animated game does not need to write data unless asked to).
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict

import config as C

# Data contract: every fact table and its columns, in file order. Tables that got no rows
# in a run are still written (header only) so downstream SQL and Power BI never break.
# tests/test_analytics.py checks the simulation's row() calls against this.
FACT_COLUMNS = {
    "fact_daily_kpi": ["date", "revenue", "costs", "profit", "wages", "energy", "spoilage", "penalties",
                       "rejected_cost", "expedite_cost", "repair_cost", "incident_cost", "fixed_cost", "cases_shipped",
                       "cases_picked", "orders", "on_time", "fill_rate", "accuracy", "cph", "compliance",
                       "temp_alarms", "pallets_received", "pallets_rejected", "pallets_qa", "inbound_trucks",
                       "inbound_late", "breakdowns", "expedites", "spoiled_cases", "sick_calls",
                       "injuries_lost_time", "injuries_medical", "forklift_incidents", "damaged_cases", "cash"],
    "fact_energy_daily": ["date", "zone", "kwh", "cost", "door_passes"],
    "fact_equipment": ["ts", "forklift_id", "event", "battery_pct"],
    "fact_events": ["ts", "event_type", "detail"],
    "fact_incidents": ["ts", "incident_id", "category", "incident_type", "severity", "worker_id", "role",
                       "forklift_id", "zone", "days_lost", "cases_damaged", "cost"],
    "fact_inbound_trucks": ["truck_id", "plant_code", "scheduled_ts", "gate_ts", "dock_ts", "unload_end_ts",
                            "door", "pallets_ordered", "pallets", "pallets_rejected", "aged_load", "late_min",
                            "reefer_failure"],
    "fact_inventory_daily": ["date", "sku_code", "zone", "pallets", "cases_on_hand", "cases_reserved",
                             "cases_expiring_2d", "avg_days_to_expiry"],
    "fact_labor": ["date", "worker_id", "role", "shift", "start_ts", "end_ts", "hours", "tasks",
                   "cases_picked", "break_taken", "skill"],
    "fact_order_lines": ["order_id", "store_id", "sku_code", "cases_ordered", "cases_allocated",
                         "cases_picked", "cases_shipped"],
    "fact_orders": ["order_id", "store_id", "route_id", "created_ts", "cutoff_ts", "scheduled_departure_ts",
                    "closed_ts", "lines", "cases_ordered", "cases_allocated", "cases_shipped", "fill_rate",
                    "on_time", "late_min", "rush", "expedited", "mispicks_uncaught", "revenue", "penalty"],
    "fact_pallet_receipts": ["pallet_id", "truck_id", "sku_code", "lot", "plant_code", "cases", "weight_kg",
                             "pack_date", "best_before", "arrival_temp_c", "decision", "received_ts",
                             "receiver_id"],
    "fact_picks": ["pick_id", "order_id", "store_id", "job_id", "picker_id", "sku_code", "lot", "pallet_id",
                   "slot_id", "zone", "level", "cases", "weight_kg", "start_ts", "end_ts", "travel_m",
                   "mispick", "mispick_caught", "shift", "picker_skill", "days_to_expiry"],
    "fact_putaway": ["pallet_id", "sku_code", "zone", "slot_id", "level", "operator_id", "forklift_id",
                     "start_ts", "end_ts", "travel_m", "dock_dwell_min"],
    "fact_shipment_lots": ["order_id", "store_id", "sku_code", "lot", "cases", "shipped_ts"],
    "fact_shipments": ["shipment_id", "route_id", "truck_id", "door", "scheduled_departure_ts",
                       "actual_departure_ts", "orders", "pallets", "cases", "revenue", "late_min",
                       "load_sequence_violations"],
    "fact_spoilage": ["ts", "pallet_id", "sku_code", "lot", "cases", "value", "reason"],
    "fact_temperature": ["ts", "zone", "temp_c", "setpoint_c", "max_c", "alarm", "door_open_s"],
    "fact_weather": ["date", "ambient_mean_c", "ambient_max_c"],
}


class NullLog:
    def write_dims(self, sim):
        pass

    def row(self, table, **fields):
        pass

    def flush(self):
        pass

    def close(self, sim=None):
        pass


class CsvLog(NullLog):
    FLUSH_EVERY = 5000

    def __init__(self, out_dir):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.buffers = defaultdict(list)
        self.headers = {}
        self.pending = 0

    def write_dims(self, sim):
        self._write_table("dim_sku", [
            {"sku_code": s.code, "name_fr": s.name_fr, "name_en": s.name_en, "category": s.category,
             "zone": s.zone, "temp_class": s.temp_class, "case_kg_min": s.weight_min,
             "case_kg_max": s.weight_max, "shelf_life_days": s.shelf_days,
             "cases_per_pallet": s.cases_per_pallet, "value_per_case": s.value,
             "base_demand_cases_day": s.base_demand, "plant_code": s.plant, "season": s.season or ""}
            for s in sim.skus.values()])
        self._write_table("dim_store", [
            {"store_id": s.id, "name": s.name, "city": s.city, "kind": s.kind, "size_index": s.size,
             "route_id": s.route, "stop": s.stop} for s in sim.stores.values()])
        self._write_table("dim_route", [
            {"route_id": r, "departure_hour": h, "shipping_door": door + 1} for r, (h, door) in C.ROUTES.items()])
        self._write_table("dim_plant", [
            {"plant_code": code, "name_fr": p["fr"], "name_en": p["en"],
             "late_mean_min": p["late_mean"], "late_sd_min": p["late_sd"]} for code, p in C.PLANTS.items()])
        self._write_table("dim_zone", [
            {"zone": key, "setpoint_c": z["setpoint"], "min_c": z["min"], "max_c": z["max"], "kw_at_rest": z["kw"]}
            for key, z in C.ZONES.items()])

    def row(self, table, **fields):
        self.buffers[table].append(fields)
        self.pending += 1
        if self.pending >= self.FLUSH_EVERY:
            self.flush()

    def flush(self):
        for table, rows in self.buffers.items():
            if rows:
                self._append(table, rows)
        self.buffers.clear()
        self.pending = 0

    def close(self, sim=None):
        self.flush()
        for table, cols in FACT_COLUMNS.items():      # header-only files for tables with no rows
            if table not in self.headers:
                with open(os.path.join(self.out_dir, table + ".csv"), "w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow(cols)
        if sim is not None:
            self._write_table("dim_worker", [
                {"worker_id": w.id, "name": w.name, "role": w.role, "shift": w.shift, "skill": w.skill}
                for w in sim.workers.values()])

    # ------------------------------------------------------------ files
    def _write_table(self, table, rows):
        path = os.path.join(self.out_dir, table + ".csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def _append(self, table, rows):
        path = os.path.join(self.out_dir, table + ".csv")
        header = self.headers.get(table)
        new = header is None
        if new:
            header = list(rows[0])
            self.headers[table] = header
        with open(path, "w" if new else "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
            if new:
                writer.writeheader()
            writer.writerows(rows)
