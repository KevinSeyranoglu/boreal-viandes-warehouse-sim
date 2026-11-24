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
