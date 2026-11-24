"""All warehouse logic on a fixed time step. No pygame in here.

main.py calls Simulation.step(dt); the renderer and UI only read the state.
The same code runs headless (python main.py --headless) to generate data.
"""
from __future__ import annotations

import datetime as dtm
import heapq
import json
import math
import random
from collections import deque

import config as C
from datalog import NullLog
from events import EventManager
from models import (SKU, Door, Forklift, Job, Order, Pallet, RackSlot, Spot,
                    Store, Truck, Worker, Zone, from_dict, to_dict)
from pathfinding import NavGrid
import masterdata as M

YARD, ROAD, FLOOR, WALL, RACK, DOCKDOOR = range(6)
DAY = 86400.0
ROOM_X = C.ROOM_X                      # generated from the site size in config.py
ROOM_Y0, ROOM_Y1 = C.ROOM_Y0, C.ROOM_Y1
_BX0, _BY0, _BX1, _BY1 = C.BUILDING
_RX0 = min(ROOM_X.values())
_N_CHARGERS = sum(n for _, n in C.FORKLIFTS)
_CHARGE_W = 4 * ((_N_CHARGERS + 1) // 2) + 3
NORTH_ROOMS = {"qa": (_RX0, _RX0 + 19), "break": (_RX0 + 24 + _CHARGE_W, _RX0 + 39 + _CHARGE_W),
               "office": (_RX0 + 42 + _CHARGE_W, _RX0 + 53 + _CHARGE_W)}
CHARGING_AREA = (_RX0 + 21, _BY0 + 1, _RX0 + 21 + _CHARGE_W, _BY0 + 10)
SPAWN = ((NORTH_ROOMS["office"][0] + NORTH_ROOMS["office"][1]) // 2, _BY0 + 5)
ZONE_ORDER = {"fresh": 0, "processed": 1, "freezer": 2}
PRODUCT_SPEC_MAX = {"fresh": 4.0, "processed": 4.0, "freezer": -15.0, "chilled": 4.0, "frozen": -15.0}
DOCK_DWELL_GRACE_S = 45 * 60

# job kinds a role will take, tier by tier (best priority wins inside a tier)
ROLE_JOBS = {
    "receiver": [["unload"], ["load"]],
    "taxi": [["taxi"]],
    "forklift": [["move_qa", "putaway"]],
    "picker": [["pick"], ["load"]],
    "loader": [["load"], ["unload"]],
    "qa": [["inspect"]],
}
FORKLIFT_JOBS = {"putaway", "move_qa"}
TRUCK_JOBS = ("unload", "load")
JOB_KINDS = ("unload", "taxi", "putaway", "move_qa", "inspect", "pick", "load")
_MID_Y = (ROOM_Y0 + ROOM_Y1) // 2
SHARED = C.DOCK_LAYOUT == "shared"
_DOCK_IN_X = _BX1 - 19 - C.SHARED_IN_COLS // 2 if SHARED else _BX0 + 4   # receivers wait by inbound staging
IDLE_POINTS = {"receiver": (_DOCK_IN_X, _MID_Y),"taxi": (_DOCK_IN_X if SHARED else _BX0 + 12, _BY0 + 13),
               "forklift": ((CHARGING_AREA[0] + CHARGING_AREA[2]) // 2, _BY0 + 13),
               "picker": ((_RX0 + _BX1) // 2, ROOM_Y0 - 3), "loader": (_BX1 - 8, _MID_Y),
               "qa": (_RX0 + 9, _BY0 + 5)}


def G(x, y):
    return {"op": "goto", "x": int(x), "y": int(y)}


def W(s, act):
    return {"op": "wait", "s": float(s), "act": act}


def F(h, s):
    return {"op": "fork", "h": float(h), "s": float(s), "act": "fork"}


def D(fn, **a):
    return {"op": "do", "fn": fn, "a": a}


# ====================================================================== layout
class Layout:
    """Static floor plan: tiles, rack slots, staging spots, doors, chargers."""

    def __init__(self):
        W_, H_ = C.MAP_W, C.MAP_H
        self.w, self.h = W_, H_
        t = bytearray([YARD]) * (W_ * H_)
        self.tiles = t

        def fill(x0, y0, x1, y1, v):
            for y in range(max(0, y0), min(H_ - 1, y1) + 1):
                base = y * W_
                for x in range(max(0, x0), min(W_ - 1, x1) + 1):
                    t[base + x] = v

        bx0, by0, bx1, by1 = C.BUILDING
        fill(0, C.ROAD_Y0, W_ - 1, C.ROAD_Y1, ROAD)
        fill(bx0, by0, bx1, by1, WALL)
        fill(bx0 + 1, by0 + 1, bx1 - 1, by1 - 1, FLOOR)

        self.doors = []
        for y in C.RECEIVING_DOOR_Y:
            fill(bx0, y - 1, bx0, y + 1, DOCKDOOR)
            self.doors.append(Door(id=len(self.doors), side="in", x=bx0, y=y))
        for y in C.SHIPPING_DOOR_Y:
            fill(bx1, y - 1, bx1, y + 1, DOCKDOOR)
            self.doors.append(Door(id=len(self.doors), side="both" if SHARED else "out", x=bx1, y=y))
        self.in_doors = [d for d in self.doors if d.side in ("in", "both")]
        self.out_doors = [d for d in self.doors if d.side in ("out", "both")]   # route door = out_doors[i]
        # door number as the dock staff say it: receiving and shipping count separately when split
        self.door_num = [(self.in_doors if d.side == "in" else self.out_doors).index(d) + 1 for d in self.doors]

        self.areas = {}
        for name, (x0, x1) in NORTH_ROOMS.items():
            fill(x0, by0, x1, by0 + 11, WALL)
            fill(x0 + 1, by0 + 1, x1 - 1, by0 + 10, FLOOR)
            mid = (x0 + x1) // 2
            fill(mid - 1, by0 + 11, mid + 1, by0 + 11, FLOOR)
            self.areas[name] = (x0, by0, x1, by0 + 11)
        self.areas["charging"] = CHARGING_AREA

        self.room_door = {}          # tile index -> zone key
        self.slots = []
        self.spots = []
        seg_starts = [ROOM_Y0 + 3 + i * (C.RACK_RUN + 2) for i in range(C.RACK_SEGMENTS)]
        for key, x0 in ROOM_X.items():
            pairs = C.ROOMS[key]
            x1 = x0 + 5 * pairs + 4
            fill(x0, ROOM_Y0, x1, ROOM_Y1, WALL)
            fill(x0 + 1, ROOM_Y0 + 1, x1 - 1, ROOM_Y1 - 1, FLOOR)
            for k in range(pairs + 1):                    # one 3-wide opening per aisle
                ax = x0 + 1 + 5 * k
                wy = ROOM_Y0 if k % 2 == 0 else ROOM_Y1   # alternate north / south doors
                for x in range(ax, min(ax + 3, x1)):
                    t[wy * W_ + x] = FLOOR
                    self.room_door[wy * W_ + x] = key
            for p in range(pairs):
                rc = x0 + 4 + 5 * p
                for col, acc in ((rc, rc - 1), (rc + 1, rc + 2)):
                    for ys in seg_starts:
                        ye = ys + C.RACK_RUN - 1
                        fill(col, ys, col, ye, RACK)
                        for by in range(ys, ye + 1, 2):
                            for lvl in range(C.RACK_LEVELS):
                                self.slots.append(RackSlot(id=len(self.slots), zone=key, x=col, y=by,
                                                           level=lvl, ax=acc, ay=by))
            self.areas[key] = (x0, ROOM_Y0, x1, ROOM_Y1)
            # drop points (P&D) in the corridor in front of the room: taxis drop, reach trucks pick up
            for x in range(x0 + 1, x1, 2):
                self.spots.append(Spot(id=len(self.spots), kind="drop", x=x, y=ROOM_Y0 - 2, zone=key))

        for d in self.doors:
            staging = {"in": [("in", range(bx0 + 6, bx0 + 16))], "out": [("out", range(bx1 - 17, bx1 - 3))],
                       # shared door: outbound staging by the wall, inbound behind it (1-tile aisle between)
                       "both": [("out", range(bx1 - 17, bx1 - 3)),
                                ("in", range(bx1 - 18 - C.SHARED_IN_COLS, bx1 - 18))]}[d.side]
            for kind, xs in staging:
                for row in (d.y - 1, d.y + 1):
                    for x in xs:
                        self.spots.append(Spot(id=len(self.spots), kind=kind, x=x, y=row, door=d.id))
        qx0 = NORTH_ROOMS["qa"][0]
        for y in range(by0 + 3, by0 + 10, 2):
            for x in range(qx0 + 2, qx0 + 18, 2):
                self.spots.append(Spot(id=len(self.spots), kind="qa", x=x, y=y))

        cx0, cy0, cx1, _ = CHARGING_AREA
        self.chargers = [(cx0 + 2 + 4 * i, y) for y in (cy0 + 2, cy0 + 6) for i in range((cx1 - cx0 - 1) // 4)]
        bx_0, _, bx_1, _ = self.areas["break"]
        self.seats = [(x, y) for y in range(by0 + 3, by0 + 10, 3) for x in range(bx_0 + 2, bx_1 - 1)]
        self.walkable = bytearray(1 if v == FLOOR else 0 for v in t)

        # temperature zones: cold rooms and QA cage; every other building floor tile is the dock
        self.zone_rects = {"qa": [[qx0 + 1, by0 + 1, NORTH_ROOMS["qa"][1] - 1, by0 + 10]]}
        for key, (x0, y0, x1, y1) in ((k, self.areas[k]) for k in ROOM_X):
            self.zone_rects[key] = [[x0 + 1, y0 + 1, x1 - 1, y1 - 1]]
        self.zone_rects["dock"] = [[bx0 + 1, by0 + 12, bx1 - 1, by1 - 1],
                                   [bx0 + 1, by0 + 1, qx0 - 1, by0 + 11],
                                   [NORTH_ROOMS["qa"][1] + 1, by0 + 1, NORTH_ROOMS["break"][0] - 1, by0 + 11],
                                   [NORTH_ROOMS["office"][1] + 1, by0 + 1, bx1 - 1, by0 + 11]]
        self.zone_map = {}
        for key in ("qa", *ROOM_X, "dock"):              # first match wins: rooms before the dock
            for x0, y0, x1, y1 in self.zone_rects[key]:
                for y in range(y0, y1 + 1):
                    for x in range(x0, x1 + 1):
                        if t[y * W_ + x] != WALL:
                            self.zone_map.setdefault(y * W_ + x, key)

        # WMS location codes: rack slot ROOM-ROW-BAY-LEVEL (FR-03-17-C), floor spots by area
        self.slot_code = [""] * len(self.slots)
        for key in ROOM_X:
            zs = [sl for sl in self.slots if sl.zone == key]
            cols = {x: i + 1 for i, x in enumerate(sorted({sl.x for sl in zs}))}
            bays = {x: {y: i + 1 for i, y in enumerate(sorted({sl.y for sl in zs if sl.x == x}))} for x in cols}
            for sl in zs:
                self.slot_code[sl.id] = (f"{M.ROOM_CODE[key]}-{cols[sl.x]:02d}-{bays[sl.x][sl.y]:02d}-"
                                         f"{M.LEVEL_LETTER[sl.level]}")
        self.spot_code, seen = [""] * len(self.spots), {}
        for sp in self.spots:
            if sp.kind == "in":
                area = f"STG-R{self.door_num[sp.door]:02d}"
            elif sp.kind == "out":
                area = f"STG-S{self.door_num[sp.door]:02d}"
            elif sp.kind == "drop":
                area = f"PD-{M.ROOM_CODE[sp.zone]}"
            else:
                area = "QA"
            seen[area] = seen.get(area, 0) + 1
            self.spot_code[sp.id] = f"{area}-{seen[area]:02d}"
        prefix = {"in": "RCV", "out": "SHP", "both": "DCK"}
        self.door_code = [f"{prefix[d.side]}-D{self.door_num[d.id]:02d}" for d in self.doors]

        # truck routes (tile coordinates): west yard for receiving doors, east apron for the east doors
        self.in_dock_x = bx0 - 8          # trailer centre when backed onto a receiving door
        self.in_lane_x = bx0 - 24         # north-south lane in front of the receiving doors
        self.in_turn_x = bx0 - 34
        self.out_dock_x = bx1 + 8
        self.out_lane_x = bx1 + 21
        self.out_turn_x = bx1 + 31

    def approach(self, door):
        """(lane x, turn x, dock x, outward step) for the apron in front of this door's wall."""
        if door.x == C.BUILDING[0]:
            return self.in_lane_x, self.in_turn_x, self.in_dock_x, -2
        return self.out_lane_x, self.out_turn_x, self.out_dock_x, 2

    def zone_at(self, x: float, y: float):
        return self.zone_map.get(int(y) * self.w + int(x))


# ====================================================================== simulation
class Simulation:
    def __init__(self, seed: int | None = None, datalog=None, state: dict | None = None):
        self.layout = Layout()
        L = self.layout
        self.nav = NavGrid(L.w, L.h, L.walkable)
        self.data = datalog or NullLog()
        self.skus = {row[0]: SKU(*row) for row in C.SKUS}
        self.gtin = {code: M.gtin14(1, int(code[1:])) for code in self.skus}
        for sku in self.skus.values():
            sku.base_demand *= C.DEMAND_SCALE
        self.stores = {row[0]: Store(*row) for row in C.STORES}
        size_sum = sum(s.size for s in self.stores.values())
        self.store_share = {k: s.size / size_sum for k, s in self.stores.items()}
        self.start_date = dtm.datetime(*C.START_DATE)
        self.events = EventManager()
        self.fx = []
        self.summary_ready = None
        self.slots = L.slots
        self.spots = L.spots
        self.doors = L.doors
        self.spots_by_kind = {k: [s for s in self.spots if s.kind == k] for k in ("in", "out", "qa", "drop")}
        self.slots_by_zone = {}
        for key in ROOM_X:
            entry_x = ROOM_X[key] + 2
            zs = [s for s in self.slots if s.zone == key]
            zs.sort(key=lambda s: abs(s.ax - entry_x) + abs(s.ay - ROOM_Y0) + s.level * 6)
            self.slots_by_zone[key] = zs
        if state:
            self._restore(state)
        else:
            self._fresh(C.RANDOM_SEED if seed is None else seed)

    # ------------------------------------------------------------------ setup
    def _fresh(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.t = C.START_HOUR * 3600
        self.day = 0
        self.ids = {}
        self.money = C.STARTING_CASH
        self.pallets, self.trucks, self.orders = {}, {}, {}
        self.workers, self.forklifts, self.jobs = {}, {}, {}
        self.open_jobs = {k: [] for k in JOB_KINDS}
        self.stock = {code: [] for code in self.skus}
        self.zones = {}
        for key, z in C.ZONES.items():
            self.zones[key] = Zone(key=key, rects=self.layout.zone_rects[key], setpoint=z["setpoint"],
                                   tmin=z["min"], tmax=z["max"], kw=z["kw"], temp=z["setpoint"])
        self.sched, self.seq = [], 0
        self.departures = {}
        self.lots = {}
        self.lot_shipments = {}
        self.recall = None
        self.last_recall = None
        self.pending_putaway = []
        self.demand_by_day = {code: {} for code in self.skus}
        self.parking = [None] * len(C.PARKING)
        self.weather_anom = self.rng.gauss(0, 3)
        self.amb_base = self._ambient_base(0)
        self.stats = self._new_stats()
        self.cum = {"orders": 0, "on_time": 0, "ordered": 0, "shipped": 0, "lines": 0,
                    "mispicks": 0, "comp_out": 0, "comp_total": 0, "damaged_cases": 0}
        self.history = []
        self.logbook = deque(maxlen=300)
        self.chart_shipped = [0] * 24
        self.chart_freezer = deque(maxlen=96)
        self.chart_picks = deque([0] * 24, maxlen=24)
        self.picks_this_hour = 0
        self.flags = {"season": None, "temp_ticks": 0, "zone_full_logged": {}}

        for kind, n in C.FORKLIFTS:
            for _ in range(n):
                fid = self._nid("forklift")
                ch = self.layout.chargers[(fid - 1) % len(self.layout.chargers)]
                self.forklifts[fid] = Forklift(id=fid, kind=kind, charger=(fid - 1) % len(self.layout.chargers),
                                               x=ch[0] + 0.5, y=ch[1] + 0.5, heading=-math.pi / 2,
                                               battery=self.rng.uniform(70, 100), state="charging")
        for shift, roles in C.HEADCOUNT.items():
            for role, n in roles.items():
                for _ in range(n):
                    self._hire(role, shift, announce=False)

        self._seed_inventory()
        next_mid = (self.t // DAY + 1) * DAY
        self._schedule(next_mid, "day_start")
        for name, (h0, _) in C.SHIFTS.items():
            st = (self.t // DAY) * DAY + h0 * 3600
            if st <= self.t:
                st += DAY
            self._schedule(st, "shift", name=name)
        self._schedule((self.t // 3600 + 1) * 3600, "hourly")
        self._schedule(self.t + 60, "temp_log")
        self._plan_day(0, first=True)
        cur = self.current_shift()
        for w in self.workers.values():
            if w.shift == cur:
                self._spawn(w, at_idle=True)
        self.log("log_welcome", "info")
        self.data.write_dims(self)

    def _seed_inventory(self):
        for code, sku in self.skus.items():
            target = C.COVER_DAYS[sku.zone] * sku.base_demand * self._season_factor(sku, self.date(self.t)) * 0.9
            n = max(2, math.ceil(target / sku.cases_per_pallet))
            for i in range(n):
                if sku.zone == "freezer":
                    age = self.rng.uniform(10, 120)
                else:
                    age = self.rng.uniform(0.05, 0.4) * sku.shelf_days
                pack = -age
                if pack + sku.shelf_days < C.MIN_REMAINING_DAYS[sku.zone] + 1:
                    pack = C.MIN_REMAINING_DAYS[sku.zone] + 1 - sku.shelf_days
                cases = sku.cases_per_pallet if i else self.rng.randint(sku.cases_per_pallet // 4, sku.cases_per_pallet)
                p = self._make_pallet(code, sku.plant, pack, cases)
                slot = self._find_slot(sku.zone)
                if slot is None:
                    del self.pallets[p.id]
                    break
                self._put_in_slot(p, slot)
                p.received_t = self.t

    # ------------------------------------------------------------------ helpers
    def _nid(self, kind):
        self.ids[kind] = self.ids.get(kind, 0) + 1
        return self.ids[kind]

    def _schedule(self, t, kind, **payload):
        heapq.heappush(self.sched, [t, self.seq, kind, payload])
        self.seq += 1

    def date(self, t=None):
        return self.start_date + dtm.timedelta(seconds=self.t if t is None else t)

    def ts(self, t=None):
        return self.date(t).strftime("%Y-%m-%d %H:%M:%S")

    def day_str(self, day):
        return (self.start_date + dtm.timedelta(days=day)).strftime("%Y-%m-%d")

    def hour(self):
        return (self.t % DAY) / 3600.0

    def current_shift(self, t=None):
        h = ((self.t if t is None else t) % DAY) / 3600.0
        for name, (h0, h1) in C.SHIFTS.items():
            if h0 < h1 and h0 <= h < h1:
                return name
        return "night"

    def log(self, key, lvl="info", **kw):
        self.logbook.append({"t": self.t, "key": key, "lvl": lvl, "kw": kw})
        if lvl in ("warn", "bad", "event"):
            self.data.row("fact_events", ts=self.ts(), event_type=key,
                          detail=json.dumps(kw, ensure_ascii=False))

    # ------------------------------------------------------------------ WMS scan log
    MVT = {"RCV": "101", "RQA": "101", "REJ": "122", "TXI": "999", "PUT": "999", "QAM": "999", "QRL": "321",
           "QRJ": "553", "PCK": "999", "BLD": "", "LOD": "", "SHP": "601", "SPL": "551", "ADJ": "551",
           "RCL": "344", "DSP": "", "RTV": "122"}

    def loc_of(self, p):
        if p.loc == "slot":
            return self.layout.slot_code[p.ref]
        if p.loc == "spot":
            return self.layout.spot_code[p.ref]
        return {"truck": "TRL-", "worker": "JACK-", "forklift": "FLT-"}.get(p.loc, "") + str(p.ref or "")

    def _txn(self, kind, p=None, *, sku=None, lot=None, cases=None, kg=None, sscc=None, from_sscc="",
             frm="", to="", user="", equip="", doc_type="", doc_no="", reason=""):
        """One scan in the WMS transaction history (one row per pallet movement or pick line)."""
        sku = sku if sku is not None else (p.sku if p is not None else None)
        self.data.row("fact_transactions", ts=self.ts(), txn_id=self._nid("txn"), txn_type=kind,
                      mvt_type=self.MVT.get(kind, ""), sscc=sscc if sscc is not None else (p.sscc if p else ""),
                      from_sscc=from_sscc, sku_code=sku or "MIXED", gtin=self.gtin.get(sku, ""),
                      lot=lot if lot is not None else (p.lot if p is not None and not p.mixed else ""),
                      cases=cases if cases is not None else (p.cases if p is not None else 0),
                      weight_kg=round(kg if kg is not None else (p.weight_kg if p is not None else 0.0), 2),
                      from_loc=frm, to_loc=to, user_id=user, equipment_id=equip,
                      doc_type=doc_type, doc_no=doc_no, reason=reason)

    @staticmethod
    def po_no(truck_id):
        return f"PO{truck_id:07d}"

    @staticmethod
    def so_no(order_id):
        return f"SO{order_id:07d}"

    @staticmethod
    def bol_no(truck_id):
        return f"BL{truck_id:07d}"

    def fx_text(self, x, y, key, color="good", **kw):
        self.fx.append({"kind": "text", "x": x, "y": y, "key": key, "kw": kw, "color": color})

    def _cost(self, kind, amount):
        self.money -= amount
        self.stats[kind] += amount

    @staticmethod
    def _new_stats():
        keys = ["revenue", "wages", "energy", "spoilage", "penalties", "rejected_cost", "expedite_cost",
                "repair_cost", "fixed_cost", "cases_shipped", "cases_picked", "lines_picked", "mispicks",
                "picker_hours", "orders_closed", "orders_on_time", "cases_ordered_closed",
                "cases_shipped_closed", "temp_alarms", "pallets_received", "pallets_rejected", "pallets_qa",
                "inbound_trucks", "inbound_late", "breakdowns", "expedites", "comp_out", "comp_total",
                "orders_received", "spoiled_cases", "sick_calls", "incident_cost", "injuries_lost_time",
                "injuries_medical", "forklift_incidents", "damaged_cases"]
        return {k: 0.0 for k in keys}

    # ------------------------------------------------------------------ weather & demand
    def _ambient_base(self, day):
        d = self.start_date + dtm.timedelta(days=day)
        m = d.month - 1
        frac = (d.day - 15) / 30.0
        nb = (m + (1 if frac >= 0 else -1)) % 12
        return C.AMBIENT_BY_MONTH[m] + (C.AMBIENT_BY_MONTH[nb] - C.AMBIENT_BY_MONTH[m]) * abs(frac)

    def ambient(self, t=None):
        t = self.t if t is None else t
        h = (t % DAY) / 3600.0
        return self.amb_base + self.weather_anom + C.AMBIENT_DAILY_SWING * math.sin((h - 9) / 24 * 2 * math.pi)

    def season_on(self, d):
        md = (d.month, d.day)
        for name, (start, end, _, _) in C.SEASONS.items():
            if start <= md <= end:
                return name
        return None

    def _season_factor(self, sku, d):
        md = (d.month, d.day)
        for name, (start, end, f_season, f_other) in C.SEASONS.items():
            if start <= md <= end:
                f = f_season if sku.season == name else f_other
                if name == "bbq" and sku.season == "bbq":
                    f *= 1 + C.BBQ_HEAT_SENSITIVITY * max(0.0, self.amb_base + self.weather_anom + C.AMBIENT_DAILY_SWING - 18)
                return f
        start, end, f = C.POST_XMAS_LULL
        if start <= md <= end:
            return f
        return 1.0

    def _demand_lines(self, store, dep_t):
        d = self.date(dep_t)
        dow = d.weekday()
        dep_day = int(dep_t // DAY)
        lines = []
        for code, sku in self.skus.items():
            mean = (sku.base_demand * self.store_share[store.id] * C.WEEKDAY_FACTOR[dow]
                    * self._season_factor(sku, d) * C.KIND_MIX[store.kind][sku.category])
            if self.rng.random() < C.LINE_SKIP_PROB:
                continue
            if mean < 3:
                qty = sum(1 for _ in range(4) if self.rng.random() < mean / 4)
            else:
                qty = int(round(max(0.0, self.rng.gauss(mean, mean * C.DEMAND_CV))))
            if qty <= 0:
                continue
            lines.append({"sku": code, "qty": qty, "alloc": 0, "picked": 0, "shipped": 0})
            hist = self.demand_by_day[code]
            hist[dep_day] = hist.get(dep_day, 0) + qty
        return lines

    # ------------------------------------------------------------------ planning
    def _plan_day(self, day, first=False):
        self._replenish(day)
        for route, (hour, _door) in C.ROUTES.items():
            dep = (day + 1) * DAY + hour * 3600
            self._schedule_departure(route, dep)
            if first:
                dep0 = day * DAY + hour * 3600
                if dep0 - self.t >= (C.CUTOFF_H + 1) * 3600:    # only departures we can still pick for
                    self._schedule_departure(route, dep0)

    def _schedule_departure(self, route, dep):
        key = f"{route}@{int(dep)}"
        self.departures[key] = {"route": route, "dep": dep, "orders": [], "truck": None, "done": False}
        for s in self.stores.values():
            if s.route != route:
                continue
            ct = dep - self.rng.uniform(*C.ORDER_WINDOW_H) * 3600
            self._schedule(max(self.t, ct), "order", store=s.id, key=key)
        self._schedule(max(self.t, dep - C.CUTOFF_H * 3600), "wave", key=key)
        self._schedule(max(self.t, dep - C.OUTBOUND_YARD_BEFORE_H * 3600), "out_yard", key=key)
        self._schedule(max(self.t, dep - C.OUTBOUND_ARRIVE_BEFORE_H * 3600), "out_arrive", key=key)

    def _replenish(self, day):
        position = {code: 0 for code in self.skus}
        for p in self.pallets.values():
            if p.mixed or p.sku is None or p.recalled:
                continue
            if p.status == "stored":
                position[p.sku] += p.cases - p.reserved
            elif p.status in ("received", "qa_hold", "inbound"):
                position[p.sku] += p.cases
        d = self.start_date + dtm.timedelta(days=day + 1)
        need = {}
        for code, sku in self.skus.items():
            expected = sku.base_demand * self._season_factor(sku, d) * 0.96
            hist = self.demand_by_day[code]
            recent = [hist.get(k, 0) for k in range(day - 7, day)]
            fc = expected if day < 7 else 0.5 * expected + 0.5 * sum(recent) / 7
            deficit = C.COVER_DAYS[sku.zone] * fc * max(0.3, self.rng.gauss(1, C.ORDER_NOISE_CV)) - position[code]
            need[code] = math.ceil(deficit / sku.cases_per_pallet) if deficit > 0 else 0
        for plant, info in C.PLANTS.items():
            codes = [c for c, s in self.skus.items() if s.plant == plant for _ in range(need[c])]
            if not codes:
                continue
            self.rng.shuffle(codes)
            # consolidate: as few trucks as capacity allows, more only if each stays well loaded
            slots = [day * DAY + h * 3600 for h in info["hours"] if day * DAY + h * 3600 >= self.t - 1800]
            if not slots:
                slots = [self.t + 3600]
            cap = self.rng.randint(C.TRUCK_CAPACITY_MIN, C.TRUCK_CAPACITY)       # 28–30 pallets this time
            n = max(math.ceil(len(codes) / cap), len(codes) // C.MIN_INBOUND_PALLETS, 1)
            n_slots = min(n, len(slots))
            for i in range(n):
                load = codes[i::n]
                k = i % n_slots
                sched = slots[k * len(slots) // n_slots] + (i // n_slots) * 600   # a convoy, 10 min apart
                self._create_inbound(plant, sched, load)

    def _lot(self, plant, code, pack_day):
        key = f"{plant}|{code}|{int(math.floor(pack_day))}"
        recalled = self.flags.setdefault("recalled_lots", [])
        while key in self.lots and self.lots[key] in recalled:
            key += "|new"                      # the plant never ships a recalled lot again: new lot number
        if key not in self.lots:
            self.lots[key] = 4000 + len(self.lots)
        return self.lots[key]

    def _make_pallet(self, code, plant, pack_day, cases):
        sku = self.skus[code]
        pid = self._nid("pallet")
        avg = (sku.weight_min + sku.weight_max) / 2
        p = Pallet(id=pid, sku=code, lot=self._lot(plant, code, pack_day), cases=cases, sscc=M.sscc(pid),
                   pack_day=pack_day,
                   bb_day=pack_day + sku.shelf_days, plant=plant,
                   weight_kg=round(cases * avg * (1 + self.rng.gauss(0, 0.01)), 1),
                   temp_class=sku.temp_class, temp_c=C.INBOUND_SPEC[sku.zone]["target"])
        self.pallets[pid] = p
        return p

    def _create_inbound(self, plant, sched, codes):
        info = C.PLANTS[plant]
        tid = self._nid("truck")
        late = min(max(self.rng.gauss(info["late_mean"], info["late_sd"]), C.LATENESS_CLIP_MIN[0]),
                   C.LATENESS_CLIP_MIN[1])
        tr = Truck(id=tid, kind="in", origin=plant, sched_t=sched, planned_t=sched + late * 60,
                   pallets_ordered=len(codes), aged_load=self.rng.random() < info["aged_prob"])
        for code in codes:
            if self.rng.random() < info["short_prob"]:
                continue                        # short-shipped by the plant
            sku = self.skus[code]
            age = self.rng.uniform(*C.PACK_AGE_DAYS[sku.zone])
            if tr.aged_load:
                age += self.rng.uniform(*C.AGED_EXTRA_DAYS[sku.zone])
            p = self._make_pallet(code, plant, sched / DAY - age, sku.cases_per_pallet)
            p.loc, p.ref, p.truck_id = "truck", tid, tid
            tr.pallets.append(p.id)
        if not tr.pallets:                      # everything short-shipped: no truck comes
            return
        self.trucks[tid] = tr
        self._schedule(max(self.t, tr.planned_t), "in_arrive", tid=tid)

    # ------------------------------------------------------------------ main step
    def step(self, dt):
        self.t += dt
        for tr in self.trucks.values():
            tr.trail = [(tr.x, tr.y)]
        for f in self.forklifts.values():
            f.trail = [(f.x, f.y)]
        for w in self.workers.values():
            if w.state != "off":
                w.trail = [(w.x, w.y)]
        while self.sched and self.sched[0][0] <= self.t:
            _, _, kind, payload = heapq.heappop(self.sched)
            getattr(self, "_ev_" + kind)(**payload)
        self._update_zones(dt)
        self._update_doors(dt)
        self._update_trucks(dt)
        self._update_workers(dt)
        self._update_forklifts(dt)
        self._accrue(dt)
        if len(self.fx) > 150:
            del self.fx[:-150]

    # ------------------------------------------------------------------ scheduled events
    def _ev_day_start(self):
        day = int(round(self.t / DAY))
        self.summary_ready = self._close_day(day - 1)
        self.day = day
        self.stats = self._new_stats()
        self.chart_shipped = [0] * 24
        self.weather_anom = 0.7 * self.weather_anom + self.rng.gauss(0, 3)
        self.amb_base = self._ambient_base(day)
        self._cost("fixed_cost", C.FIXED_DAILY_COST)
        self._inventory_snapshot(day)
        self._plan_day(day)
        self._prune(day)
        self.events.day_start(self)
        self.data.flush()
        self._schedule(self.t + DAY, "day_start")

    def _ev_shift(self, name):
        for w in self.workers.values():
            if w.state == "active" and w.shift != name:
                w.state = "leaving"
        for w in list(self.workers.values()):
            if w.shift != name or w.state != "off" or w.fired or w.injured_until > self.t:
                continue
            if self.events.sick_call(self, w):
                w.sick = True
                self.stats["sick_calls"] += 1
                self.log("ev_sick", "warn", name=w.name, role=w.role)
                continue
            w.sick = False
            self._spawn(w)
        self.log("log_shift", "info", shift=name)
        self._schedule(self.t + DAY, "shift", name=name)

    def _ev_hourly(self):
        h = int(self.hour()) % 24
        self.chart_picks.append(self.picks_this_hour)
        self.picks_this_hour = 0
        self.events.hourly(self)
        self._check_spoilage()
        self._check_recall_done()
        self._schedule(self.t + 3600, "hourly")
        _ = h

    def _ev_temp_log(self):
        self.flags["temp_ticks"] += 1
        for z in self.zones.values():
            reading = z.temp + self.rng.gauss(0, C.TEMP_SENSOR_NOISE)
            self.data.row("fact_temperature", ts=self.ts(), zone=z.key, temp_c=round(reading, 2),
                          setpoint_c=z.setpoint, max_c=z.tmax, alarm=int(z.alarm),
                          door_open_s=round(z.door_open_s, 1))
        if self.flags["temp_ticks"] % 3 == 0:
            self.chart_freezer.append(self.zones["freezer"].temp)
        self._check_excursions(C.TEMP_LOG_EVERY_MIN)
        self._dispatch_waiting_inbound()          # new shift crews can pull trailers from the yard
        if self.pending_putaway:
            waiting, self.pending_putaway = self.pending_putaway, []
            for pid in waiting:
                p = self.pallets.get(pid)
                if p and p.status == "received" and p.loc == "spot":
                    self._request_putaway(p)
        self._schedule(self.t + C.TEMP_LOG_EVERY_MIN * 60, "temp_log")

    def _ev_order(self, store, key):
        dep = self.departures.get(key)
        if dep is None:
            return
        s = self.stores[store]
        oid = self._nid("order")
        o = Order(id=oid, store=store, route=s.route, created_t=self.t,
                  cutoff_t=dep["dep"] - C.CUTOFF_H * 3600, departure_t=dep["dep"],
                  lines=self._demand_lines(s, dep["dep"]))
        self.orders[oid] = o
        dep["orders"].append(oid)
        self.stats["orders_received"] += 1
        if self.t >= o.cutoff_t:
            self._release(o)

    def _ev_wave(self, key):
        dep = self.departures.get(key)
        if dep is None:
            return
        n = 0
        for oid in dep["orders"]:
            o = self.orders.get(oid)
            if o and o.status == "open":
                self._release(o)
                n += 1
        if n:
            self.log("log_wave", "info", route=dep["route"], orders=n)

    def _ev_in_arrive(self, tid):
        tr = self.trucks.get(tid)
        if tr is None or tr.state not in ("scheduled", "queued", "parked"):
            return
        if tr.state == "scheduled" and tr.planned_t > self.t + 1:
            self._schedule(tr.planned_t, "in_arrive", tid=tid)
            return
        if tr.arrive_t is None:
            tr.arrive_t = self.t
            amb = self.ambient()
            for pid in tr.pallets:
                p = self.pallets[pid]
                spec = C.INBOUND_SPEC[self.skus[p.sku].zone]
                temp = self.rng.gauss(spec["target"], spec["sd"]) + 0.04 * max(0.0, amb - 15)
                if tr.reefer_fail:
                    temp += self.rng.uniform(*C.REEFER_FAIL_WARMUP)
                p.temp_c = round(temp, 1)
            self.stats["inbound_trucks"] += 1
            late = (self.t - tr.sched_t) / 60
            if late > 15:
                self.stats["inbound_late"] += 1
            self.log("log_truck_in", "info", plant=tr.origin, truck=tid, late=int(late))
        door = self._free_inbound_door()
        if door is not None and self._receiving_capacity():
            from_park = tr.state == "parked"
            if from_park:
                self.parking[tr.park] = None
                tr.park = None
            else:
                tr.x, tr.y, tr.heading = -25.0, C.IN_LANE_Y, 0.0
            door.truck = tid
            tr.door = door.id
            tr.dest = "dock"
            tr.state = "approach"
            tr.waypoints = self._wp_in_dock(door, from_park, tr)
            return
        if tr.state != "parked":
            k = next((i for i, v in enumerate(self.parking) if v is None), None)
            if k is not None:
                self.parking[k] = tid
                tr.park = k
                tr.x, tr.y, tr.heading = -25.0, C.IN_LANE_Y, 0.0
                tr.dest, tr.state = "park", "approach"
                px, py = C.PARKING[k]
                tr.waypoints = [[px - 12, C.IN_LANE_Y, False], [px - 12, py + 0.5, False],
                                [px + 0.5, py + 0.5, False]]
                return
            tr.state = "queued"

    def _new_out_truck(self, dep, door):
        tid = self._nid("truck")
        tr = Truck(id=tid, kind="out", origin=dep["route"], state="approach", door=door.id,
                   x=C.MAP_W + 25.0, y=C.OUT_LANE_Y, heading=math.pi, sched_t=self.t, arrive_t=self.t,
                   departure_t=dep["dep"])
        self.trucks[tid] = tr
        dep["truck"] = tid
        return tr

    def _ev_out_yard(self, key):
        """The carrier drops the empty reefer trailer in the yard a few hours before departure."""
        dep = self.departures.get(key)
        if dep is None or dep["truck"] is not None:
            return
        k = next((i for i, v in enumerate(self.parking) if v is None), None)
        if k is None:
            return                                   # yard full: it comes straight to the door later
        door = self._route_door(dep["route"])
        tr = self._new_out_truck(dep, door)
        self.parking[k] = tr.id
        tr.park, tr.dest = k, "park"
        px, py = C.PARKING[k]
        tr.waypoints = [[px + 12, C.OUT_LANE_Y, False], [px + 12, py + 0.5, False], [px + 0.5, py + 0.5, False]]

    def _ev_out_arrive(self, key):
        dep = self.departures.get(key)
        if dep is None:
            return
        door = self._route_door(dep["route"])
        tr = self.trucks.get(dep["truck"]) if dep["truck"] is not None else None
        if door.truck is not None or (tr is not None and tr.state == "approach"):
            self._schedule(self.t + 300, "out_arrive", key=key)
            return
        L = self.layout
        y = door.y + 0.5
        to_door = [[L.out_lane_x, y, False], [L.out_turn_x, y, False], [L.out_dock_x, y, True]]
        if tr is None:                               # straight from the highway
            tr = self._new_out_truck(dep, door)
            tr.waypoints = [[L.out_lane_x, C.OUT_LANE_Y, False]] + to_door
        else:                                        # pulled from the yard
            self.parking[tr.park] = None
            tr.park = None
            tr.state = "approach"
            tr.waypoints = [[tr.x - 10, tr.y, False], [tr.x - 10, C.OUT_LANE_Y, False],
                            [L.out_lane_x, C.OUT_LANE_Y, False]] + to_door
        tr.dest = "dock"
        door.truck = tr.id

    def _ev_repair(self, fid):
        f = self.forklifts[fid]
        f.broken_until = None
        if f.operator is None:                   # the mechanic returns it to its charger, plugged in
            cx, cy = self.layout.chargers[f.charger]
            f.x, f.y, f.state = cx + 0.5, cy + 0.5, "charging"
        else:
            f.state = "idle"
        self.log("log_repaired", "info", fid=fid)
        self.data.row("fact_equipment", ts=self.ts(), forklift_id=fid, event="repaired", battery_pct=round(f.battery, 1))

    def _ev_dispose(self, pid):
        p = self.pallets.get(pid)
        if p is None:
            return
        self._txn("DSP", p, frm=self.loc_of(p), to="DISPOSAL", reason=p.status)
        if p.loc == "spot":
            sp = self.spots[p.ref]
            sp.pallet = None
            self.fx_text(sp.x + 0.5, sp.y + 0.5, "fx_disposed", "warn", lot=p.lot)
        del self.pallets[pid]

    def _ev_door_fix(self, zone):
        z = self.zones[zone]
        if z.stuck_open:
            z.stuck_open = False
            self.log("log_door_fixed", "info", zone=zone)

    def _ev_recall_auto(self):
        if self.recall and not self.recall["pulling"]:
            self.log("log_recall_auto", "warn", lot=self.recall["lot"])
            self.recall_pull_all()

    # ------------------------------------------------------------------ zones & doors
    def _update_zones(self, dt):
        amb = self.ambient()
        k = min(1.0, dt / C.ZONE_TAU_S)
        for z in self.zones.values():
            z.temp += (z.setpoint - z.temp) * k
        dock = self.zones["dock"]
        open_sum = sum(d.open for d in self.doors)
        dock.temp += (amb - dock.temp) * min(1.0, C.DOCK_DOOR_LEAK * open_sum * dt)
        for key in ROOM_X:
            z = self.zones[key]
            leak = 0.0
            if z.stuck_open:
                leak = C.ROOM_DOOR_STUCK_LEAK
            elif z.door_open_s > 0:
                leak = C.ROOM_DOOR_LEAK
                z.door_open_s = max(0.0, z.door_open_s - dt)
            if leak:
                x0, y0, x1, y1 = self.layout.areas[key]
                leak *= C.REF_ROOM_AREA / ((x1 - x0 - 1) * (y1 - y0 - 1))     # same heat, more air
                z.temp += (dock.temp - z.temp) * min(1.0, leak * dt)
        amb_factor = 1 + C.ENERGY_AMBIENT_FACTOR * max(0.0, amb)
        for z in self.zones.values():
            out = z.temp > z.tmax or z.temp < z.tmin
            if out and not z.alarm:
                z.alarm = True
                self.stats["temp_alarms"] += 1
                self.log("log_alarm", "bad", zone=z.key, temp=round(z.temp, 1))
                cx, cy = self._zone_center(z.key)
                self.fx_text(cx, cy, "fx_alarm", "bad", zone=z.key)
            elif z.alarm and z.tmin + C.ALARM_HYSTERESIS < z.temp < z.tmax - C.ALARM_HYSTERESIS:
                z.alarm = False
                self.log("log_alarm_end", "info", zone=z.key)
            kw = z.kw * amb_factor * (1 + 0.15 * max(0.0, z.temp - z.setpoint))
            kwh = kw * dt / 3600
            z.kwh_today += kwh
            self._cost("energy", kwh * C.ENERGY_PRICE_KWH)

    def _zone_center(self, key):
        x0, y0, x1, y1 = self.layout.zone_rects[key][0]
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _update_doors(self, dt):
        step = dt / C.DOOR_OPEN_SECONDS
        for d in self.doors:
            tr = self.trucks.get(d.truck) if d.truck is not None else None
            target = 1.0 if tr is not None and tr.state == "docked" else 0.0
            if d.open < target:
                d.open = min(target, d.open + step)
            elif d.open > target:
                d.open = max(target, d.open - step)

    def set_door_stuck(self, zone, minutes):
        z = self.zones[zone]
        z.stuck_open = True
        self._schedule(self.t + minutes * 60, "door_fix", zone=zone)
        self.log("ev_door_stuck", "event", zone=zone, minutes=int(minutes))

    def close_stuck_door(self, zone):
        """Player action from the zone popup."""
        self._ev_door_fix(zone)

    def _check_excursions(self, minutes):
        for p in list(self.pallets.values()):
            if p.loc == "slot":
                zone = self.slots[p.ref].zone
            elif p.loc == "spot":
                zone = "qa" if self.spots[p.ref].kind == "qa" else "dock"
            else:
                continue
            spec_key = p.temp_class if p.mixed else self.skus[p.sku].zone
            air = self.zones[zone].temp
            p.temp_c += (air - p.temp_c) * min(1.0, minutes * 60 / C.PRODUCT_TAU_S[p.temp_class])
            if zone == "dock" and p.received_t is not None and self.t - p.received_t < DOCK_DWELL_GRACE_S:
                out = False
            else:
                out = p.temp_c > PRODUCT_SPEC_MAX[spec_key]   # product temperature, not air
            self.stats["comp_total"] += 1
            self.cum["comp_total"] += 1
            if out:
                self.stats["comp_out"] += 1
                self.cum["comp_out"] += 1
                p.excursion_min += minutes
                if (p.status == "stored" and not p.mixed and p.excursion_min >= C.EXCURSION_QA_MIN
                        and not p.recalled):
                    self._send_to_qa(p, "excursion")

    # ------------------------------------------------------------------ trucks
    def _wp_in_dock(self, door, from_park, tr):
        y = door.y + 0.5
        lane_x, turn_x, dock_x, _ = self.layout.approach(door)
        if from_park:                      # pull out of the yard, back onto the road, up to the door
            return [[tr.x + 10, tr.y, False], [tr.x + 10, C.IN_LANE_Y, False], [lane_x, C.IN_LANE_Y, False],
                    [lane_x, y, False], [turn_x, y, False], [dock_x, y, True]]
        return [[lane_x, C.IN_LANE_Y, False], [lane_x, y, False], [turn_x, y, False], [dock_x, y, True]]

    def _route_door(self, route):
        return self.layout.out_doors[C.ROUTES[route][1]]

    def _free_inbound_door(self):
        """First free door that can receive. A shared door is kept free from INBOUND_DOOR_BUFFER_H before
        its next outbound trailer arrives until that trailer has left."""
        busy = set()
        if SHARED:
            soon = self.t + (C.INBOUND_DOOR_BUFFER_H + C.OUTBOUND_ARRIVE_BEFORE_H) * 3600
            busy = {self._route_door(d["route"]).id for d in self.departures.values()
                    if not d["done"] and d["dep"] <= soon}
        return next((d for d in self.layout.in_doors if d.truck is None and d.id not in busy), None)

    def _update_trucks(self, dt):
        for tr in list(self.trucks.values()):
            if tr.state in ("approach", "departing"):
                self._drive(tr, dt)
            elif tr.state == "docked":
                if tr.kind == "in":
                    self._check_inbound_done(tr)
                else:
                    self._update_outbound(tr)

    def _drive(self, tr, dt):
        budget = dt
        while budget > 1e-9 and tr.waypoints:
            tx, ty, rev = tr.waypoints[0]
            dx, dy = tx - tr.x, ty - tr.y
            d = math.hypot(dx, dy)
            if d < 1e-6:
                tr.waypoints.pop(0)
                continue
            spd = C.TRUCK_REVERSE_SPEED if rev else C.TRUCK_SPEED
            tr.heading = math.atan2(-dy, -dx) if rev else math.atan2(dy, dx)
            reach = spd * budget
            if reach >= d:
                tr.x, tr.y = tx, ty
                budget -= d / spd
                tr.waypoints.pop(0)
            else:
                tr.x += dx / d * reach
                tr.y += dy / d * reach
                budget = 0
            tr.trail.append((tr.x, tr.y))
        if tr.waypoints:
            return
        if tr.state == "departing":
            tr.state = "gone"
            del self.trucks[tr.id]
        elif tr.dest == "park":
            tr.state = "parked"
        else:
            tr.state = "docked"
            tr.dock_t = self.t
            if tr.kind == "in":
                for pid in tr.pallets:
                    self._new_job("unload", pallet=pid, truck=tr.id, priority=50 - (tr.arrive_t or 0) / 1e6)

    def _check_inbound_done(self, tr):
        for pid in tr.pallets:
            if self.pallets[pid].status == "inbound":
                return
        tr.unload_end_t = self.t
        rejected = [pid for pid in tr.pallets if self.pallets[pid].status == "rejected"]
        n_total = sum(1 for _ in rejected) + tr.__dict__.get("_unloaded", 0)
        for pid in rejected:
            del self.pallets[pid]
        self.data.row("fact_inbound_trucks", truck_id=tr.id, po_number=self.po_no(tr.id), plant_code=tr.origin,
                      scheduled_ts=self.ts(tr.sched_t), gate_ts=self.ts(tr.arrive_t),
                      dock_ts=self.ts(tr.dock_t), unload_end_ts=self.ts(self.t),
                      door=self.layout.door_num[tr.door], pallets_ordered=tr.pallets_ordered, pallets=n_total,
                      pallets_rejected=len(rejected), aged_load=int(tr.aged_load),
                      late_min=round((tr.arrive_t - tr.sched_t) / 60, 1), reefer_failure=int(tr.reefer_fail))
        tr.pallets = rejected and [] or []
        self._truck_leave(tr)

    def _truck_leave(self, tr):
        door = self.doors[tr.door]
        door.truck = None
        y = door.y + 0.5
        tr.leave_t = self.t
        tr.state = "departing"
        _, turn_x, _, out = self.layout.approach(door)
        if tr.kind == "in":                 # back to the plants: west on the far lane
            tr.waypoints = [[turn_x + out, y, False], [turn_x + out, C.OUT_LANE_Y, False], [-30, C.OUT_LANE_Y, False]]
            self._dispatch_waiting_inbound()
        else:
            tr.waypoints = [[turn_x + out, y, False], [turn_x + out, C.IN_LANE_Y, False],
                            [C.MAP_W + 30, C.IN_LANE_Y, False]]

    def _receiving_capacity(self):
        """Drop-trailer yard rule: a trailer is pulled to a door only when a dock worker is free for it
        (fewer trailers at the doors than receivers on shift); otherwise it waits in the yard."""
        at_doors = sum(1 for tr in self.trucks.values()
                       if tr.kind == "in" and (tr.state == "docked" or (tr.state == "approach" and tr.dest == "dock")))
        crew = sum(1 for w in self.workers.values() if w.role == "receiver" and w.state == "active")
        return at_doors < max(1, crew)

    def _dispatch_waiting_inbound(self):
        waiting = [tr for tr in self.trucks.values() if tr.kind == "in" and tr.state in ("parked", "queued")]
        waiting.sort(key=lambda tr: (tr.state != "parked", tr.arrive_t or 0))
        for tr in waiting:
            if self._free_inbound_door() is None or not self._receiving_capacity():
                break
            self._ev_in_arrive(tr.id)

    def _update_outbound(self, tr):
        dep = self.departures.get(f"{tr.origin}@{int(tr.departure_t)}")
        if dep is None:
            return
        orders = [self.orders[i] for i in dep["orders"] if i in self.orders]
        if self.doors[tr.door].open >= 0.9:
            relax = self.t >= tr.departure_t - C.LOAD_RELAX_MIN * 60
            blocked = False
            for o in sorted(orders, key=lambda o: -self.stores[o.store].stop):
                for pid in o.pallets:
                    p = self.pallets.get(pid)
                    if p is not None and p.status == "staged_out":
                        p.status = "to_load"
                        if blocked:
                            tr.seq_violations += 1
                        self._new_job("load", pallet=pid, truck=tr.id, order=o.id,
                                      priority=70 + self.stores[o.store].stop * 0.1)
                unfinished = o.status in ("open", "released") or any(
                    self.pallets[pid].status != "loaded" for pid in o.pallets if pid in self.pallets)
                if unfinished:
                    blocked = True
                    if not relax:
                        break
        if self.t < tr.departure_t:
            return
        all_loaded = all(o.status in ("picked", "closed") and o.jobs_open == 0 and all(
            self.pallets[pid].status == "loaded" for pid in o.pallets if pid in self.pallets) for o in orders)
        if all_loaded or self.t >= tr.departure_t + C.DEPARTURE_MAX_WAIT_MIN * 60:
            self._depart_outbound(tr, dep, orders)

    def _depart_outbound(self, tr, dep, orders):
        late = max(0.0, (self.t - tr.departure_t) / 60)
        cases = rev = 0.0
        n_pallets = len(tr.pallets)
        for pid in list(tr.pallets):
            p = self.pallets.get(pid)
            if p is None:
                continue
            c, r = self._ship_pallet(p, self.orders[p.order_id])
            cases += c
            rev += r
        tr.pallets = []
        for jid in list(self.open_jobs["load"]):
            if self.jobs[jid].truck == tr.id:
                self.open_jobs["load"].remove(jid)
                del self.jobs[jid]
        for o in orders:
            o.departed = True
            o.late_min = late
            for pid in list(o.pallets):
                p = self.pallets.get(pid)
                if p is not None and p.loc == "spot":
                    self._expedite(p, o)
            if o.jobs_open > 0 or any(pid in self.pallets for pid in o.pallets):
                o.on_truck = False
            self._maybe_close_order(o)
        dep["done"] = True
        self.chart_shipped[int(self.hour()) % 24] += int(cases)
        self.data.row("fact_shipments", shipment_id=tr.id, bol_number=self.bol_no(tr.id), route_id=tr.origin,
                      truck_id=tr.id,
                      door=self.layout.door_num[tr.door], scheduled_departure_ts=self.ts(tr.departure_t),
                      actual_departure_ts=self.ts(), orders=len(orders), pallets=n_pallets, cases=int(cases),
                      revenue=round(rev, 2), late_min=round(late, 1), load_sequence_violations=tr.seq_violations)
        self.fx_text(tr.x, tr.y - 2, "fx_shipped", "good", amount=rev)
        self.log("log_departed", "info" if late <= C.DEPARTURE_GRACE_MIN else "warn",
                 route=tr.origin, cases=int(cases), late=int(late))
        self._truck_leave(tr)

    # ------------------------------------------------------------------ orders
    def _line(self, o, code):
        for ln in o.lines:
            if ln["sku"] == code:
                return ln
        ln = {"sku": code, "qty": 0, "alloc": 0, "picked": 0, "shipped": 0}
        o.lines.append(ln)
        return ln

    def _min_bb(self, o, code):
        return o.departure_t / DAY + C.MIN_REMAINING_DAYS[self.skus[code].zone]

    def _allocate(self, code, qty, min_bb):
        cands = []
        for pid in self.stock[code]:
            p = self.pallets[pid]
            if (p.status == "stored" and not p.recalled and p.bb_day >= min_bb
                    and p.cases - p.reserved > 0):
                cands.append(p)
        cands.sort(key=lambda p: (p.bb_day, p.cases))          # FEFO
        picks = []
        for p in cands:
            if qty <= 0:
                break
            take = min(qty, p.cases - p.reserved)
            p.reserved += take
            picks.append((p.id, take))
            qty -= take
        return picks, qty

    def _pick_item(self, pid, code, n):
        slot = self.slots[self.pallets[pid].ref]
        return {"p": pid, "sku": code, "n": n, "slot": slot.id, "ax": slot.ax, "ay": slot.ay,
                "z": ZONE_ORDER[slot.zone]}

    def _release(self, o):
        o.status = "released"
        groups = {"chilled": [], "frozen": []}
        for ln in o.lines:
            sku = self.skus[ln["sku"]]
            picks, rem = self._allocate(sku.code, ln["qty"], self._min_bb(o, sku.code))
            ln["alloc"] = ln["qty"] - rem
            for pid, n in picks:
                groups[sku.temp_class].append(self._pick_item(pid, sku.code, n))
        prio = self._pick_priority(o)
        for tc, items in groups.items():
            items.sort(key=lambda it: (it["z"], it["ax"], it["ay"] if (it["ax"] // 5) % 2 == 0 else -it["ay"]))
            chunk, count = [], 0
            for it in items:
                n = it["n"]
                while n > 0:
                    take = min(n, C.PALLET_MAX_CASES - count)
                    chunk.append(dict(it, n=take))
                    count += take
                    n -= take
                    if count >= C.PALLET_MAX_CASES:
                        self._new_job("pick", order=o.id, picks=chunk, temp_class=tc, priority=prio)
                        o.jobs_open += 1
                        chunk, count = [], 0
            if chunk:
                self._new_job("pick", order=o.id, picks=chunk, temp_class=tc, priority=prio)
                o.jobs_open += 1
        if o.jobs_open == 0:
            o.status = "picked"

    def _pick_priority(self, o):
        return 100 - (o.departure_t - self.t) / 3600 + (5 if o.rush else 0) + o.priority * 3

    def prioritize_order(self, oid):
        """Player action: bump an order. Releases it now if still waiting for its wave."""
        o = self.orders.get(oid)
        if o is None or o.status == "closed":
            return
        o.priority += 1
        if o.status == "open":
            self._release(o)
        for jid in self.open_jobs["pick"]:
            j = self.jobs[jid]
            if j.order == oid:
                j.priority += 3
        self.log("log_prioritized", "info", store=o.store)

    def create_rush_order(self, store_id):
        s = self.stores[store_id]
        keys = sorted((d["dep"], k) for k, d in self.departures.items()
                      if d["route"] == s.route and not d["done"] and d["dep"] - self.t > 3 * 3600)
        if not keys:
            return
        dep_t, key = keys[0]
        lines = self._demand_lines(s, dep_t)
        for ln in lines:
            ln["qty"] = int(math.ceil(ln["qty"] * 0.6))
        oid = self._nid("order")
        o = Order(id=oid, store=store_id, route=s.route, created_t=self.t, cutoff_t=self.t,
                  departure_t=dep_t, lines=lines, rush=True, priority=2)
        self.orders[oid] = o
        self.departures[key]["orders"].append(oid)
        self.stats["orders_received"] += 1
        self._release(o)
        self.log("ev_rush", "event", store=s.name, cases=sum(ln["qty"] for ln in lines))

    def _ship_pallet(self, p, o):
        on_truck = p.loc == "truck"
        self._txn("SHP", p, frm=self.loc_of(p), to=f"CUST-{o.store}", doc_type="BOL" if on_truck else "EXP",
                  doc_no=self.bol_no(p.ref) if on_truck else f"EX{o.id:07d}", reason="" if on_truck else "expedited")
        cases = rev = 0.0
        for code, lot, n, _kg in p.contents:
            r = n * self.skus[code].value * C.DISTRIBUTION_FEE_RATE
            self._line(o, code)["shipped"] += n
            rev += r
            cases += n
            self.lot_shipments.setdefault(str(lot), []).append([o.store, n, self.t])
            self.data.row("fact_shipment_lots", order_id=o.id, store_id=o.store, sku_code=code, lot=lot,
                          cases=n, shipped_ts=self.ts())
        if p.loc == "spot":
            sp = self.spots[p.ref]
            if sp.pallet == p.id:
                sp.pallet = None
        p.status, p.loc = "shipped", "gone"
        del self.pallets[p.id]
        o.revenue += rev
        self.money += rev
        self.stats["revenue"] += rev
        self.stats["cases_shipped"] += cases
        return cases, rev

    def _expedite(self, p, o):
        if not o.expedited:
            o.expedited = True
            self._cost("expedite_cost", C.EXPEDITE_COST)
            self.stats["expedites"] += 1
            self.log("log_expedite", "warn", store=o.store)
        o.on_truck = False
        o.late_min = max(o.late_min, (self.t - o.departure_t) / 60)
        x, y = p.x, p.y
        c, _ = self._ship_pallet(p, o)
        self.chart_shipped[int(self.hour()) % 24] += int(c)
        self.fx_text(x, y, "fx_expedite", "warn")

    def _maybe_close_order(self, o):
        if o.status == "closed" or not o.departed or o.jobs_open > 0:
            return
        if any(pid in self.pallets for pid in o.pallets):
            return
        ordered = sum(ln["qty"] for ln in o.lines)
        shipped = sum(ln["shipped"] for ln in o.lines)
        allocated = sum(ln["alloc"] for ln in o.lines)
        on_time = o.on_truck and o.late_min <= C.DEPARTURE_GRACE_MIN
        short = max(0, ordered - shipped)
        value = sum(ln["qty"] * self.skus[ln["sku"]].value for ln in o.lines)
        penalty = (0 if on_time else C.LATE_PENALTY_SHARE * value) + short * C.SHORT_PENALTY_PER_CASE \
            + o.mispicks_uncaught * C.MISPICK_PENALTY
        self._cost("penalties", penalty)
        st = self.stats
        st["orders_closed"] += 1
        st["orders_on_time"] += int(on_time)
        st["cases_ordered_closed"] += ordered
        st["cases_shipped_closed"] += shipped
        self.cum["orders"] += 1
        self.cum["on_time"] += int(on_time)
        self.cum["ordered"] += ordered
        self.cum["shipped"] += shipped
        o.status = "closed"
        o.shipped_t = self.t
        self.data.row("fact_orders", order_id=o.id, store_id=o.store, route_id=o.route,
                      created_ts=self.ts(o.created_t), cutoff_ts=self.ts(o.cutoff_t),
                      scheduled_departure_ts=self.ts(o.departure_t), closed_ts=self.ts(),
                      lines=len(o.lines), cases_ordered=ordered, cases_allocated=allocated,
                      cases_shipped=shipped, fill_rate=round(shipped / ordered, 4) if ordered else 1,
                      on_time=int(on_time), late_min=round(o.late_min, 1), rush=int(o.rush),
                      expedited=int(o.expedited), mispicks_uncaught=o.mispicks_uncaught,
                      revenue=round(o.revenue, 2), penalty=round(penalty, 2))
        for ln in o.lines:
            self.data.row("fact_order_lines", order_id=o.id, store_id=o.store, sku_code=ln["sku"],
                          cases_ordered=ln["qty"], cases_allocated=ln["alloc"], cases_picked=ln["picked"],
                          cases_shipped=ln["shipped"])
        if short > 0:
            self.log("log_short", "warn", store=o.store, cases=short)

    # ------------------------------------------------------------------ stock movements
    def _find_slot(self, zone):
        for s in self.slots_by_zone[zone]:
            if s.pallet is None and s.reserved_for is None:
                return s
        return None

    def _put_in_slot(self, p, slot):
        slot.pallet = p.id
        slot.reserved_for = None
        p.loc, p.ref, p.status = "slot", slot.id, "stored"
        p.x, p.y = slot.x + 0.5, slot.y + 1.0
        self.stock[p.sku].append(p.id)

    def _take_from_slot(self, p):
        slot = self.slots[p.ref]
        if slot.pallet == p.id:
            slot.pallet = None
        if p.id in self.stock.get(p.sku, []):
            self.stock[p.sku].remove(p.id)

    def _free_spot(self, kind, door=None):
        best = None
        for sp in self.spots_by_kind[kind]:
            if sp.pallet is None and sp.reserved is None:
                if door is None or sp.door == door:
                    return sp
                if best is None:
                    best = sp
        return best

    def _free_drop(self, zone):
        for sp in self.spots_by_kind["drop"]:
            if sp.zone == zone and sp.pallet is None and sp.reserved is None:
                return sp
        return None

    def _request_putaway(self, p):
        """Dock or QA cage -> taxi to the room's drop point; drop point -> reach truck to a rack slot."""
        zone = self.skus[p.sku].zone
        slot = self._find_slot(zone)
        drop = None
        if slot is not None and p.loc == "spot" and self.spots[p.ref].kind != "drop":
            drop = self._free_drop(zone)
            if drop is not None:
                drop.reserved = p.id
                self._new_job("taxi", pallet=p.id, target=drop.id, priority=45 if zone == "freezer" else 40)
                return
        on_drop = p.loc == "spot" and self.spots[p.ref].kind == "drop"
        if slot is None or not on_drop:          # room full, or every drop point busy: retry later
            if p.id not in self.pending_putaway:
                self.pending_putaway.append(p.id)
            last = self.flags["zone_full_logged"].get(zone, -1e9)
            if slot is None and self.t - last > 3600:
                self.flags["zone_full_logged"][zone] = self.t
                self.log("log_zone_full", "warn", zone=zone)
            return
        slot.reserved_for = p.id
        self._new_job("putaway", pallet=p.id, target=slot.id,
                      priority=45 if zone == "freezer" else 40)

    def _send_to_qa(self, p, reason):
        """Queue a forklift move to the QA cage (excursion, spoiled, recall)."""
        if p.loc == "slot":
            self._take_from_slot(p)
            self.slots[p.ref].pallet = p.id   # stays physically in the slot until lifted
        for jid in list(self.open_jobs["putaway"]):
            j = self.jobs[jid]
            if j.pallet == p.id:
                self.open_jobs["putaway"].remove(jid)
                self.slots[j.target].reserved_for = None
                del self.jobs[jid]
        for jid in list(self.open_jobs["taxi"]):
            j = self.jobs[jid]
            if j.pallet == p.id:
                self.open_jobs["taxi"].remove(jid)
                if self.spots[j.target].reserved == p.id:
                    self.spots[j.target].reserved = None
                del self.jobs[jid]
        for jid in self.open_jobs["move_qa"]:
            j = self.jobs[jid]
            if j.pallet == p.id:
                j.reason = reason
                j.priority = max(j.priority, 80 if reason == "recall" else j.priority)
                return
        if any(j.pallet == p.id and j.worker is not None for j in self.jobs.values()):
            return   # already being carried; handled when it lands
        p.status = {"excursion": "qa_hold", "spoiled": "spoiled", "recall": "recalled"}.get(reason, "qa_hold")
        if reason == "excursion":
            p.qa_reason = "excursion"
        prio = {"recall": 80, "excursion": 60, "spoiled": 20}.get(reason, 45)
        self._new_job("move_qa", pallet=p.id, reason=reason, priority=prio)

    def _check_spoilage(self):
        today = self.t / DAY
        for p in list(self.pallets.values()):
            if p.mixed or p.status not in ("stored", "received", "qa_hold"):
                continue
            if today > p.bb_day:
                loss = p.cases * self.skus[p.sku].value
                self._cost("spoilage", loss)
                self.stats["spoiled_cases"] += p.cases
                self.data.row("fact_spoilage", ts=self.ts(), pallet_id=p.id, sku_code=p.sku, lot=p.lot,
                              cases=p.cases, value=round(loss, 2), reason="expired")
                self.log("log_spoiled", "bad", lot=p.lot, sku=p.sku, cases=p.cases)
                self._txn("SPL", p, frm=self.loc_of(p), to=self.loc_of(p), reason="past best-before")
                self.fx_text(p.x, p.y, "fx_spoiled", "bad", lot=p.lot)
                if p.loc == "spot" and self.spots[p.ref].kind == "qa":
                    p.status = "spoiled"
                    self._schedule(self.t + C.DISPOSE_AFTER_H * 3600, "dispose", pid=p.id)
                else:
                    self._send_to_qa(p, "spoiled")

    def _inventory_snapshot(self, day):
        agg = {}
        for p in self.pallets.values():
            if p.mixed or p.status != "stored":
                continue
            a = agg.setdefault(p.sku, [0, 0, 0, 0, 0.0])
            a[0] += 1
            a[1] += p.cases
            a[2] += p.reserved
            if p.bb_day - day <= 2:
                a[3] += p.cases
            a[4] += (p.bb_day - day) * p.cases
        for code, sku in self.skus.items():
            n, cases, res, exp, wdays = agg.get(code, [0, 0, 0, 0, 0.0])
            self.data.row("fact_inventory_daily", date=self.day_str(day), sku_code=code, zone=sku.zone,
                          pallets=n, cases_on_hand=cases, cases_reserved=res, cases_expiring_2d=exp,
                          avg_days_to_expiry=round(wdays / cases, 2) if cases else "")

    # ------------------------------------------------------------------ recall
    def start_recall(self, lot):
        self.flags.setdefault("recalled_lots", []).append(lot)      # blocked for good (WMS lot hold)
        targets = []
        sku = None
        for p in self.pallets.values():
            hit = (not p.mixed and p.lot == lot) or (p.mixed and any(c[1] == lot for c in p.contents))
            if hit and p.status not in ("inbound", "rejected", "shipped"):
                p.recalled = True
                targets.append(p.id)
                if not p.mixed:
                    sku = p.sku
        if not targets:
            return False
        stores = sorted({row[0] for row in self.lot_shipments.get(str(lot), [])})
        self.recall = {"lot": lot, "sku": sku, "start_t": self.t, "targets": targets, "pulling": False,
                       "stores": stores, "shipped_cases": sum(r[1] for r in self.lot_shipments.get(str(lot), [])),
                       "response_min": None}
        # The WMS lot hold is immediate: dock scans take the lot off every outbound pallet and picker jack
        # now (nothing of it can be loaded or shipped). Only rack pallets wait for the physical pull.
        for pid in [t for t in targets if self.pallets[t].mixed]:
            self.recall_pull(pid)
        for w in self.workers.values():
            held = [c for c in w.jack_load if c[1] == lot]
            if held:
                w.jack_load = [c for c in w.jack_load if c[1] != lot]
                n = sum(c[2] for c in held)
                self.cum["recall_jack_cases"] = self.cum.get("recall_jack_cases", 0) + n
                self._txn("RCL", sku=held[0][0], lot=lot, cases=-n, kg=-sum(c[3] for c in held), sscc=w.build_sscc,
                          frm=f"JACK-{w.id}", to="QUARANTINE", user=w.id, doc_type="RCL",
                          reason="recalled lot removed from picker jack")
        self._schedule(self.t + self.rng.uniform(*C.RECALL_AUTO_PULL_H) * 3600, "recall_auto")
        self.log("ev_recall", "event", lot=lot, sku=sku, pallets=len(targets), stores=len(stores))
        cx, cy = self._zone_center("dock")
        self.fx_text(cx, cy, "fx_recall", "bad", lot=lot)
        return True

    def recall_pull_all(self):
        """Player action (or supervisor after a delay): pull every pallet of the recalled lot."""
        rc = self.recall
        if not rc or rc["pulling"]:
            return
        rc["pulling"] = True
        rc["response_min"] = round((self.t - rc["start_t"]) / 60, 1)
        for pid in rc["targets"]:
            self.recall_pull(pid)
        self.log("log_recall_pulling", "event", lot=rc["lot"], minutes=rc["response_min"])

    def recall_pull(self, pid):
        rc = self.recall
        p = self.pallets.get(pid)
        if rc is None or p is None or p.status in ("recalled", "shipped"):
            return
        if p.mixed:
            removed = sum(c[2] for c in p.contents if c[1] == rc["lot"])
            if removed:
                self._txn("RCL", p, sku=next(c[0] for c in p.contents if c[1] == rc["lot"]), lot=rc["lot"],
                          cases=-removed, kg=0.0, frm=self.loc_of(p), to="QUARANTINE", doc_type="RCL",
                          reason="recalled lot removed from outbound pallet")
            keep = [c for c in p.contents if c[1] != rc["lot"]]
            p.contents = keep
            p.cases = sum(c[2] for c in keep)
            p.recalled = False
            if p.cases == 0:
                if p.loc == "spot":
                    self.spots[p.ref].pallet = None
                elif p.loc == "truck":
                    tr = self.trucks.get(p.ref)
                    if tr and pid in tr.pallets:
                        tr.pallets.remove(pid)
                for jid in list(self.open_jobs["load"]):      # nothing left to load (a claimed job aborts itself)
                    if self.jobs[jid].pallet == pid:
                        self.open_jobs["load"].remove(jid)
                        del self.jobs[jid]
                o = self.orders.get(p.order_id)
                del self.pallets[pid]
                if o:
                    self._maybe_close_order(o)
            return
        if p.loc == "spot" and self.spots[p.ref].kind == "qa":
            for jid in list(self.open_jobs["inspect"]):
                if self.jobs[jid].pallet == pid:
                    self.open_jobs["inspect"].remove(jid)
                    del self.jobs[jid]
            p.status = "recalled"
            self._schedule(self.t + C.DISPOSE_AFTER_H * 3 * 3600, "dispose", pid=pid)
            return
        if p.loc in ("slot", "spot"):
            self._send_to_qa(p, "recall")

    def _check_recall_done(self):
        rc = self.recall
        if not rc or not rc["pulling"]:
            return
        for pid in rc["targets"]:
            p = self.pallets.get(pid)
            if p is not None and p.recalled and p.status != "recalled":
                return
        hours = round((self.t - rc["start_t"]) / 3600, 1)
        self.log("log_recall_done", "event", lot=rc["lot"], hours=hours)
        rc["done_t"] = self.t
        self.last_recall = rc
        self.recall = None

    # ------------------------------------------------------------------ forklifts
    def break_forklift(self, fid):
        f = self.forklifts[fid]
        if f.state == "broken":
            return
        if f.operator is not None:
            f.pending_break = True
        else:
            self._break_now(f)

    def _break_now(self, f):
        f.pending_break = False
        f.state = "broken"
        hours = self.rng.uniform(*C.FORKLIFT_REPAIR_HOURS)
        f.broken_until = self.t + hours * 3600
        self._schedule(f.broken_until, "repair", fid=f.id)
        self._cost("repair_cost", C.FORKLIFT_REPAIR_COST)
        self.stats["breakdowns"] += 1
        self.log("ev_breakdown", "event", fid=f.id, hours=round(hours, 1))
        self.fx_text(f.x, f.y, "fx_breakdown", "bad", fid=f.id)
        self.data.row("fact_equipment", ts=self.ts(), forklift_id=f.id, event="breakdown",
                      battery_pct=round(f.battery, 1))

    def _update_forklifts(self, dt):
        for f in self.forklifts.values():
            if f.fork_h != f.fork_target:
                step = dt * 0.15
                f.fork_h = min(f.fork_target, f.fork_h + step) if f.fork_h < f.fork_target \
                    else max(f.fork_target, f.fork_h - step)
            if f.state == "charging":
                f.battery = min(100.0, f.battery + C.BATTERY_CHARGE_PER_H * dt / 3600)
            elif f.state != "broken":
                f.battery = max(0.0, f.battery - C.BATTERY_IDLE_DRAIN_PER_H * dt / 3600)

    def _free_forklift(self, w):
        """Nearest charged forklift; failing that, the nearest low one that sits unplugged
        (parked for a break or just repaired) so the driver takes it to a charger.
        Without that fallback, parked trucks drain to 0 % and the fleet strands itself."""
        best, bd = None, 1e9
        low, ld = None, 1e9
        for f in self.forklifts.values():
            if f.state in ("broken", "busy") or f.operator is not None or f.reserved_by is not None:
                continue
            d = abs(f.x - w.x) + abs(f.y - w.y)
            if f.battery >= C.BATTERY_MIN_TO_TAKE:
                if d < bd:
                    best, bd = f, d
            elif f.state != "charging" and d < ld:
                low, ld = f, d
        return best or low

    # ------------------------------------------------------------------ incidents (rates: config + events.py)
    def _incident_row(self, category, kind, severity, w=None, f=None, days=0.0, cases=0, cost=0.0, x=None, y=None):
        zone = self.layout.zone_at(x, y) if x is not None else None
        self.data.row("fact_incidents", ts=self.ts(), incident_id=self._nid("incident"), category=category,
                      incident_type=kind, severity=severity, worker_id=w.id if w else "",
                      role=w.role if w else "", forklift_id=f.id if f else "", zone=zone or "",
                      days_lost=round(days, 1), cases_damaged=cases, cost=round(cost, 2))

    def injure(self, w, kind, lost_time, forklift=None):
        """A worker is hurt: treated and sent home for the shift, or off for days (lost-time claim)."""
        if lost_time:
            median, sigma, cap = C.INJURY_DAYS_LOST
            days = min(cap, max(1.0, self.rng.lognormvariate(math.log(median), sigma)))
            w.injured_until = self.t + days * DAY
            hours_paid = days * 5 / 7 * 8                           # working days off
            cost = hours_paid * C.WAGES[w.role] * C.INJURY_INDEMNITY_SHARE
            self.stats["injuries_lost_time"] += 1
        else:
            days = 0.0
            w.injured_until = self.t + 8 * 3600                    # home for the rest of the shift
            cost = 150.0                                           # first aid / clinic visit
            self.stats["injuries_medical"] += 1
        self._cost("incident_cost", cost)
        if w.state == "active":
            w.state = "leaving"
        self._incident_row("injury", kind, "lost_time" if lost_time else "medical_aid", w=w, f=forklift,
                           days=days, cost=cost, x=w.x, y=w.y)
        self.log("ev_injury", "bad", name=w.name, kind=kind, days=round(days))
        self.fx_text(w.x, w.y, "fx_injury", "bad")

    def forklift_accident(self, f, kind, injury):
        """Collision or tip-over (injury), or property damage only (rack strike, dropped pallet, damage)."""
        self.stats["forklift_incidents"] += 1
        op = self.workers.get(f.operator) if f.operator is not None else None
        if injury:
            victim = op
            if kind == "pedestrian_struck":
                walkers = [w for w in self.workers.values() if w.state == "active" and w.forklift is None]
                if walkers:
                    victim = min(walkers, key=lambda w: abs(w.x - f.x) + abs(w.y - f.y))
            if victim is not None:
                self.injure(victim, kind, lost_time=True, forklift=f)
            self.break_forklift(f.id)
            return
        cases, cost = 0, 0.0
        if kind == "dropped_pallet" and f.carrying in self.pallets and not self.pallets[f.carrying].mixed:
            p = self.pallets[f.carrying]
            cases = max(1, min(p.cases - 1, round(p.cases * self.rng.uniform(*C.DROPPED_PALLET_LOSS))))
            p.cases -= cases
            cost = cases * self.skus[p.sku].value
            self._txn("ADJ", p, cases=-cases, kg=-cases * (self.skus[p.sku].weight_min + self.skus[p.sku].weight_max) / 2,
                      frm=self.loc_of(p), to=self.loc_of(p), user=op.id if op else "", equip=f"FLT-{f.id}",
                      doc_type="ADJ", reason="dropped pallet")
            self.stats["damaged_cases"] += cases
            self.cum["damaged_cases"] = self.cum.get("damaged_cases", 0) + cases
        elif kind == "equipment_damage" or kind == "dropped_pallet":
            kind = "equipment_damage"
            self.break_forklift(f.id)
        else:                                                      # rack strike: the nearest bay is closed
            bay = min(self.slots, key=lambda sl: abs(sl.x - f.x) + abs(sl.y - f.y))
            hours = self.rng.uniform(*C.RACK_REPAIR_HOURS)
            for sl in self.slots:
                if sl.x == bay.x and sl.y == bay.y and sl.pallet is None and sl.reserved_for is None:
                    sl.reserved_for = -1                           # blocked until repaired
            self._schedule(self.t + hours * 3600, "rack_repaired", x=bay.x, y=bay.y)
            cost = C.RACK_REPAIR_COST
        self._cost("incident_cost", cost)
        self._incident_row("forklift", kind, "property_damage", w=op, f=f, cases=cases, cost=cost, x=f.x, y=f.y)
        self.log("ev_forklift", "event", fid=f.id, kind=kind)
        self.fx_text(f.x, f.y, "fx_forklift", "warn")

    def _ev_rack_repaired(self, x, y):
        for sl in self.slots:
            if sl.x == x and sl.y == y and sl.reserved_for == -1:
                sl.reserved_for = None

    # ------------------------------------------------------------------ staff
    def _hire(self, role, shift, announce=True):
        wid = self._nid("worker")
        name = f"{self.rng.choice(C.FIRST_NAMES)} {self.rng.choice(C.LAST_NAMES)}"
        skill = min(1.4, max(0.6, self.rng.gauss(1.0, C.SKILL_SD)))
        w = Worker(id=wid, name=name, role=role, shift=shift, skill=round(skill, 3))
        self.workers[wid] = w
        if announce:
            self.log("log_hired", "info", name=name, role=role, shift=shift)
            if shift == self.current_shift():
                self._spawn(w)
        return w

    def hire(self, role, shift):
        """Player action."""
        self._hire(role, shift)

    def fire(self, role, shift):
        """Player action: remove one worker of that role/shift (off-shift first)."""
        pool = [w for w in self.workers.values() if w.role == role and w.shift == shift and not w.fired]
        if not pool:
            return
        pool.sort(key=lambda w: w.state != "off")
        w = pool[0]
        w.fired = True
        if w.state == "off":
            del self.workers[w.id]
        else:
            w.state = "leaving"
        self.log("log_fired", "info", name=w.name, role=role)

    def headcount(self, shift, role):
        return sum(1 for w in self.workers.values() if w.shift == shift and w.role == role and not w.fired)

    def _spawn(self, w, at_idle=False):
        w.state, w.task = "active", ""
        w.steps, w.path, w.job = [], [], None
        w.carrying, w.jack_load, w.forklift, w.cargo = None, [], None, []
        if at_idle:
            x, y = self._idle_tile(w)
        else:
            x, y = SPAWN
        w.x, w.y = x + 0.5, y + 0.5
        w.trail = [(w.x, w.y)]
        w.on_since = self.t
        w.hours = 0.0
        w.tasks_done = w.cases_picked = 0
        w.break_done = False
        w.break_at = self.t + self.rng.uniform(3.0, 4.5) * 3600
        w.activity = ""

    def _idle_tile(self, w):
        bx, by = IDLE_POINTS[w.role]
        return self.nav.nearest_walkable(bx + (w.id % 5) - 2, by + (w.id // 5) % 3 - 1)

    def _accrue(self, dt):
        h = dt / 3600
        for w in self.workers.values():
            if w.state == "off":
                continue
            self._cost("wages", C.WAGES[w.role] * C.SHIFT_PREMIUM[w.shift] * h)
            w.hours += h
            if w.role == "picker":
                self.stats["picker_hours"] += h

    # ------------------------------------------------------------------ workers: brain
    def _entity(self, w):
        return self.forklifts[w.forklift] if w.forklift is not None else w

    def _update_workers(self, dt):
        for w in list(self.workers.values()):
            if w.state == "off":
                continue
            if w.task in ("", "idle"):
                self._find_work(w)
            self._run_steps(w, dt)

    def _find_work(self, w):
        if w.forklift is not None and self.forklifts[w.forklift].pending_break:
            f = self.forklifts[w.forklift]
            f.operator = None
            w.forklift = None
            self._break_now(f)
            w.x, w.y = f.x + 0.6, f.y
        if w.state == "leaving":
            steps = []
            if w.forklift is not None:
                cx, cy = self.layout.chargers[self.forklifts[w.forklift].charger]
                steps += [G(cx, cy), D("plug")]
            steps += [G(*SPAWN), D("despawn")]
            self._set_task(w, "leave", steps)
            return
        if w.role == "forklift" and w.forklift is None:
            f = self._free_forklift(w)
            if f is not None:
                f.reserved_by = w.id
                self._set_task(w, "mount", [G(int(f.x), int(f.y)), D("mount", fid=f.id)])
            elif w.task != "idle":
                x, y = self._idle_tile(w)
                self._set_task(w, "idle", [G(x, y)])
            return
        if not w.break_done and self.t >= w.break_at:
            seat = self.layout.seats[w.id % len(self.layout.seats)]
            steps = []
            if w.forklift is not None:
                f = self.forklifts[w.forklift]
                if f.battery < C.BATTERY_MIN_TO_TAKE:          # plug it in over the break
                    steps = [G(*self.layout.chargers[f.charger]), D("plug")]
                else:
                    steps = [D("park_here")]
            steps += [G(*seat), W(C.MEAL_BREAK_S, "break"), D("end_break")]
            self._set_task(w, "break", steps)
            return
        if w.forklift is not None and self.forklifts[w.forklift].battery < C.BATTERY_LOW:
            f = self.forklifts[w.forklift]
            cx, cy = self.layout.chargers[f.charger]
            self._set_task(w, "charge", [G(cx, cy), D("plug")])
            self.log("log_low_battery", "info", fid=f.id)
            return
        job = self._claim_job(w)
        if job is not None:
            w.job = job.id
            self._set_task(w, "job", self._job_steps(w, job))
            return
        if w.task != "idle":
            x, y = self._idle_tile(w)
            self._set_task(w, "idle", [G(x, y)])
            w.activity = "idle"

    @staticmethod
    def _set_task(w, task, steps):
        w.task = task
        w.steps = steps
        w.path = []

    def _claim_job(self, w):
        for tier in ROLE_JOBS[w.role]:
            cands = []
            for kind in tier:
                if kind in FORKLIFT_JOBS and w.forklift is None:
                    continue
                cands.extend(self.open_jobs[kind])
            if not cands:
                continue
            mine = self._own_trailer(w)
            cands.sort(key=lambda jid: (self.jobs[jid].truck != mine if mine is not None else False,
                                        -self.jobs[jid].priority, self.jobs[jid].created_t))
            # scan them all: a window of top jobs can be all blocked (QA full) and starve the
            # put-aways that would unblock them -> staging fills and inbound deadlocks
            for jid in cands:
                job = self.jobs[jid]
                if job.kind in TRUCK_JOBS and not self._may_work_trailer(w, job, mine):
                    continue
                if self._can_start(job):
                    self.open_jobs[job.kind].remove(jid)
                    job.worker = w.id
                    job.start_t = self.t
                    if job.kind == "taxi":
                        self._pair_taxi(w, job)
                    if job.kind in TRUCK_JOBS:
                        self._take_trailer(w, self.trucks[job.truck])
                    return job
        return None

    # one dock worker owns a trailer: unloads (or loads) every pallet of it, then takes the next one
    def _own_trailer(self, w):
        return next((tr.id for tr in self.trucks.values() if tr.crew == w.id), None)

    def _crew_present(self, wid, tid):
        """The owner still counts while on shift and either free or working this trailer; a picker who
        loaded a pallet and went back to picking, or anyone on break, hands the trailer over."""
        o = self.workers.get(wid)
        if o is None or o.state != "active" or o.task in ("break", "leave"):
            return False
        job = self.jobs.get(o.job) if o.job is not None else None
        return job is None or job.truck == tid

    def _may_work_trailer(self, w, job, mine):
        tr = self.trucks.get(job.truck)
        if tr is None:
            return True                                   # _can_start refuses it
        if tr.crew is not None and tr.crew != w.id and self._crew_present(tr.crew, tr.id):
            return False                                  # someone else's trailer
        if mine is not None and mine != tr.id:
            return False                                  # your trailer until it leaves the door
        return True

    def _take_trailer(self, w, tr):
        for other in self.trucks.values():                # a new trailer frees the finished one
            if other.crew == w.id and other is not tr:
                other.crew = None
        tr.crew = w.id

    def _pair_taxi(self, w, job):
        """Fill the rider jack: add up to TAXI_PALLETS-1 more pallets going to the same room,
        nearest to the first one."""
        zone = self.spots[job.target].zone
        p0 = self.pallets[job.pallet]
        cands = []
        for jid in self.open_jobs["taxi"]:
            j2 = self.jobs[jid]
            if self.spots[j2.target].zone == zone:
                p = self.pallets[j2.pallet]
                cands.append((abs(p.x - p0.x) + abs(p.y - p0.y), jid))
        for _, jid in sorted(cands)[:C.TAXI_PALLETS - 1]:
            self.open_jobs["taxi"].remove(jid)
            self.jobs[jid].worker = w.id
            self.jobs[jid].start_t = self.t
            job.picks.append(jid)

    def _can_start(self, job):
        k = job.kind
        if k in ("unload", "load"):
            tr = self.trucks.get(job.truck)
            if tr is None or tr.state != "docked" or self.doors[tr.door].open < 0.9:
                return False
            if k == "unload" and self.t < (tr.dock_t or 0) + C.DOCK_CHECKIN_S:
                return False                       # still checking in (paperwork, seal, first probe)
            if k == "unload" and any(j.kind == "unload" and j.truck == tr.id and j.worker is not None
                                     for j in self.jobs.values()):
                return False                       # one dock worker per trailer
            if k == "unload":
                sp = self._free_spot("in", tr.door)
                if sp is None:
                    return False
                sp.reserved = job.pallet
                job.target = sp.id
            return True
        if k == "taxi" and self.t - job.created_t < C.TAXI_MAX_WAIT_S:
            zone = self.spots[job.target].zone      # wait for a full load (2 pallets) unless it has waited long
            same = sum(1 for jid in self.open_jobs["taxi"] if self.spots[self.jobs[jid].target].zone == zone)
            return same >= C.TAXI_PALLETS
        if k == "move_qa" and job.target is None:
            sp = self._free_spot("qa")
            if sp is None:
                return False
            sp.reserved = job.pallet
            job.target = sp.id
        return True

    def _new_job(self, kind, priority=0.0, **kw):
        jid = self._nid("job")
        job = Job(id=jid, kind=kind, priority=priority, created_t=self.t, **kw)
        self.jobs[jid] = job
        self.open_jobs[kind].append(jid)
        return job

    def _level_h(self, level):
        return 0.15 + 0.8 * level

    def _lift_s(self, w, level):
        f = self.forklifts[w.forklift]
        s = C.FORK_LIFT_S + level * C.FORK_LIFT_PER_LEVEL_S
        return s * (C.REACH_LIFT_FACTOR if f.kind == "reach" else 1.0)

    def _job_steps(self, w, job):
        k = job.kind
        w.dist = 0.0
        w.mark_t = self.t
        if k == "unload":
            d = self.doors[self.trucks[job.truck].door]
            return [G(d.x + 1, d.y), W(C.UNLOAD_SCAN_S, "scan"), D("receive_check", j=job.id)]
        if k == "taxi":
            legs = [job] + [self.jobs[j2] for j2 in job.picks]
            steps = []
            for jb in legs:
                p = self.pallets[jb.pallet]
                steps += [G(int(p.x), int(p.y)), W(C.DROP_S, "engage"), D("taxi_load", j=jb.id)]
            for jb in legs:
                sp = self.spots[jb.target]
                steps += [G(sp.x, sp.y), W(C.DROP_S, "drop"), D("taxi_drop", j=jb.id)]
            return steps
        if k in ("putaway", "move_qa"):
            p = self.pallets[job.pallet]
            if p.loc == "slot":
                s = self.slots[p.ref]
                steps = [G(s.ax, s.ay), F(self._level_h(s.level), self._lift_s(w, s.level)),
                         W(C.FORK_ENGAGE_S, "engage"), D("lift", j=job.id), F(0.15, self._lift_s(w, s.level))]
            else:
                sp = self.spots[p.ref]
                steps = [G(sp.x, sp.y), F(0.0, 4), W(C.FORK_ENGAGE_S, "engage"), D("lift", j=job.id),
                         F(0.15, 3)]
            if k == "putaway":
                s = self.slots[job.target]
                steps += [G(s.ax, s.ay), F(self._level_h(s.level), self._lift_s(w, s.level)),
                          W(8, "place"), D("place_slot", j=job.id), F(0.0, self._lift_s(w, s.level))]
            else:
                sp = self.spots[job.target]
                steps += [G(sp.x, sp.y), F(0.0, C.FORK_LIFT_S), W(6, "drop"), D("drop_qa", j=job.id)]
            return steps
        if k == "inspect":
            sp = self.spots[self.pallets[job.pallet].ref]
            return [G(sp.x, sp.y), W(C.QA_INSPECT_S, "inspect"), D("qa_decide", j=job.id)]
        if k == "pick":
            steps = []
            for i, pk in enumerate(job.picks):
                steps += [G(pk["ax"], pk["ay"]),
                          W(C.PICK_LINE_S + pk["n"] * C.PICK_CASE_S / w.skill, "pick"),
                          D("pick", j=job.id, i=i)]
            steps.append(D("finish_pick", j=job.id))
            return steps
        if k == "load":
            p = self.pallets[job.pallet]
            sp = self.spots[p.ref]
            d = self.doors[self.trucks[job.truck].door]
            return [G(sp.x, sp.y), W(8, "hook"), D("take", j=job.id), G(d.x - 1, d.y),
                    W(C.LOAD_S, "load"), D("load_truck", j=job.id)]
        return []

    def _finish_job(self, w):
        job = self.jobs.pop(w.job, None) if w.job is not None else None
        w.job = None
        w.tasks_done += 1
        w.activity = ""
        if job and job.kind == "move_qa" and job.target is not None:
            sp = self.spots[job.target]
            if sp.reserved == job.pallet:
                sp.reserved = None
        if job and job.kind == "taxi":
            for j2 in job.picks:
                self.jobs.pop(j2, None)

    def _abort_job(self, w):
        job = self.jobs.get(w.job) if w.job is not None else None
        if job:
            if job.kind == "putaway" and job.target is not None:
                slot = self.slots[job.target]
                if slot.reserved_for == job.pallet:
                    slot.reserved_for = None
            if job.kind in ("unload", "move_qa") and job.target is not None:
                sp = self.spots[job.target]
                if sp.reserved == job.pallet:
                    sp.reserved = None
        w.steps = []
        if w.forklift is not None:
            self.forklifts[w.forklift].fork_target = 0.0

    # ------------------------------------------------------------------ workers: legs
    def _run_steps(self, w, dt):
        budget = dt
        guard = 0
        while budget > 1e-9 and w.steps and guard < 60:
            guard += 1
            st = w.steps[0]
            op = st["op"]
            if op == "goto":
                ent = self._entity(w)
                if not st.get("go"):
                    st["go"] = 1
                    w.path = self.nav.find_path((ent.x, ent.y), (st["x"], st["y"]))
                budget = self._move(w, ent, budget)
                if not w.path:
                    w.steps.pop(0)
            elif op in ("wait", "fork"):
                if op == "fork" and w.forklift is not None:
                    self.forklifts[w.forklift].fork_target = st["h"]
                w.activity = st.get("act", w.activity)
                use = min(budget, st["s"])
                st["s"] -= use
                budget -= use
                if st["s"] <= 1e-9:
                    w.steps.pop(0)
            else:
                w.steps.pop(0)
                if getattr(self, "_do_" + st["fn"])(w, **st["a"]) is False:
                    w.steps.insert(0, st)
                    w.activity = "waiting"
                    break
            if w.state == "off":
                return
        if not w.steps and w.task in ("job", "mount", "charge", "break"):
            if w.task == "job":
                self._finish_job(w)
            w.task = ""

    def _move(self, w, ent, budget):
        if w.forklift is not None:
            speed = C.REACH_SPEED if ent.kind == "reach" else C.FORKLIFT_SPEED
        elif w.role == "taxi":
            speed = C.TAXI_SPEED * (0.85 + 0.15 * w.skill)
        else:
            loaded = w.carrying is not None or w.jack_load or (w.role == "picker" and w.task == "job")
            speed = (C.JACK_SPEED if loaded else C.WALK_SPEED) * (0.85 + 0.15 * w.skill)
        moved_total = 0.0
        while budget > 1e-9 and w.path:
            tx, ty = w.path[0]
            dx, dy = tx - ent.x, ty - ent.y
            d = math.hypot(dx, dy)
            if d < 1e-6:
                w.path.pop(0)
                continue
            ent.heading = math.atan2(dy, dx)
            spd, seg = speed, d
            if len(w.path) > 1:
                if d > C.CORNER_SLOW_DIST + 1e-6:     # tolerance: float creep would loop forever
                    seg = d - C.CORNER_SLOW_DIST
                else:
                    spd = speed * C.CORNER_SLOW_FACTOR
            reach = spd * budget
            x0, y0 = ent.x, ent.y
            if reach >= seg:
                ent.x += dx / d * seg
                ent.y += dy / d * seg
                budget -= seg / spd
                moved = seg
                if seg >= d - 1e-9:
                    ent.x, ent.y = tx, ty
                    w.path.pop(0)
            else:
                ent.x += dx / d * reach
                ent.y += dy / d * reach
                moved = reach
                budget = 0.0
            ent.trail.append((ent.x, ent.y))
            moved_total += moved
            if int(y0) != int(ent.y):
                self._check_door_crossing(int(ent.x), int(y0), int(ent.y))
        w.dist += moved_total
        if w.forklift is not None:
            ent.battery = max(0.0, ent.battery - moved_total * C.BATTERY_DRAIN_PER_TILE)
            w.x, w.y, w.heading = ent.x, ent.y, ent.heading
        return budget

    def _check_door_crossing(self, x, y0, y1):
        lo, hi = min(y0, y1), max(y0, y1)
        W_ = self.layout.w
        for y in range(lo, hi + 1):
            key = self.layout.room_door.get(y * W_ + x)
            if key:
                z = self.zones[key]
                z.door_open_s = max(z.door_open_s, C.ROOM_DOOR_PASS_S)
                z.door_passes_today += 1
                if key == "freezer":
                    self.fx.append({"kind": "fog", "x": x + 0.5, "y": y + 0.5})
                return

    # ------------------------------------------------------------------ workers: actions (_do_*)
    def _do_despawn(self, w):
        self.data.row("fact_labor", date=self.day_str(int(w.on_since // DAY)), worker_id=w.id, role=w.role,
                      shift=w.shift, start_ts=self.ts(w.on_since), end_ts=self.ts(), hours=round(w.hours, 2),
                      tasks=w.tasks_done, cases_picked=w.cases_picked, break_taken=int(w.break_done),
                      skill=w.skill)
        w.state, w.task, w.steps, w.path = "off", "", [], []
        if w.fired:
            del self.workers[w.id]

    def _do_mount(self, w, fid):
        f = self.forklifts[fid]
        f.reserved_by = None
        if f.state == "broken" or f.operator is not None:
            return True
        if f.state == "charging":
            self.data.row("fact_equipment", ts=self.ts(), forklift_id=fid, event="unplug",
                          battery_pct=round(f.battery, 1))
        f.operator, f.state = w.id, "busy"
        w.forklift = fid
        w.x, w.y = f.x, f.y
        return True

    def _do_plug(self, w):
        if w.forklift is None:
            return True
        f = self.forklifts[w.forklift]
        f.state, f.operator, f.fork_target = "charging", None, 0.0
        w.forklift = None
        w.x, w.y = f.x + 0.8, f.y + 0.6
        self.data.row("fact_equipment", ts=self.ts(), forklift_id=f.id, event="plug",
                      battery_pct=round(f.battery, 1))
        return True

    def _do_park_here(self, w):
        if w.forklift is not None:
            f = self.forklifts[w.forklift]
            f.state, f.operator, f.fork_target = "idle", None, 0.0
            w.forklift = None
            w.x, w.y = f.x + 0.6, f.y
        return True

    def _do_end_break(self, w):
        w.break_done = True
        return True

    def _do_receive_check(self, w, j):
        job = self.jobs[j]
        p = self.pallets[job.pallet]
        tr = self.trucks[job.truck]
        sku = self.skus[p.sku]
        spec = C.INBOUND_SPEC[sku.zone]
        if p.lot in self.flags.get("recalled_lots", []):
            decision = "reject"                # safety net: a recalled lot is refused at the door
        elif p.temp_c <= spec["accept_max"]:
            decision = "accept"
        elif p.temp_c <= spec["qa_max"]:
            decision = "qa"
        else:
            decision = "reject"
        self.stats["pallets_received"] += 1
        door = self.doors[tr.door]
        self.data.row("fact_pallet_receipts", pallet_id=p.id, sscc=p.sscc, po_number=self.po_no(tr.id),
                      truck_id=tr.id, sku_code=p.sku, lot=p.lot,
                      plant_code=p.plant, cases=p.cases, weight_kg=p.weight_kg,
                      pack_date=self.day_str(int(math.floor(p.pack_day))),
                      best_before=self.day_str(int(math.floor(p.bb_day))), arrival_temp_c=p.temp_c,
                      decision=decision, received_ts=self.ts(), receiver_id=w.id)
        kind = {"accept": "RCV", "qa": "RQA", "reject": "REJ"}[decision]
        to = f"TRL-{tr.id}" if decision == "reject" else self.layout.spot_code[job.target]
        self._txn(kind, p, frm=f"TRL-{tr.id}", to=to, user=w.id, doc_type="PO", doc_no=self.po_no(tr.id),
                  reason="recalled lot" if p.lot in self.flags.get("recalled_lots", []) else f"probe {p.temp_c} C")
        if decision == "reject":
            p.status = "rejected"
            self._cost("rejected_cost", C.REJECT_HANDLING_COST)    # refused at the door: supplier's loss
            self.stats["pallets_rejected"] += 1
            self.fx_text(door.x + 2, door.y, "fx_rejected", "bad", lot=p.lot)
            self.log("log_rejected", "bad", lot=p.lot, sku=p.sku, temp=p.temp_c)
            sp = self.spots[job.target]
            sp.reserved = None
            return True
        tr.__dict__["_unloaded"] = tr.__dict__.get("_unloaded", 0) + 1
        if decision == "qa":
            p.status = "qa_hold"
            p.qa_reason = "inbound"
            self.stats["pallets_qa"] += 1
            self.fx_text(door.x + 2, door.y, "fx_qa_hold", "warn", lot=p.lot)
            self.log("log_qa_hold", "warn", lot=p.lot, sku=p.sku, temp=p.temp_c)
        else:
            p.status = "received"
        sp = self.spots[job.target]
        w.steps[0:0] = [D("take_from_truck", j=j), G(sp.x, sp.y), W(C.DROP_S, "drop"), D("drop_in", j=j)]
        return True

    def _do_take_from_truck(self, w, j):
        job = self.jobs[j]
        p = self.pallets[job.pallet]
        tr = self.trucks.get(job.truck)
        if tr and p.id in tr.pallets:
            tr.pallets.remove(p.id)
        p.loc, p.ref = "worker", w.id
        w.carrying = p.id
        return True

    def _do_drop_in(self, w, j):
        job = self.jobs[j]
        p = self.pallets[job.pallet]
        sp = self.spots[job.target]
        sp.pallet, sp.reserved = p.id, None
        p.loc, p.ref = "spot", sp.id
        p.x, p.y = sp.x + 0.5, sp.y + 0.5
        p.received_t = self.t
        w.carrying = None
        if p.recalled and self.recall and self.recall["pulling"]:
            self._send_to_qa(p, "recall")
        elif p.status == "received":
            self._request_putaway(p)
        else:
            self._new_job("move_qa", pallet=p.id, reason="qa", priority=45)
        return True

    def _do_taxi_load(self, w, j):
        job = self.jobs.get(j)
        p = self.pallets.get(job.pallet) if job else None
        if p is None or p.loc != "spot" or p.status != "received":     # moved, recalled or gone meanwhile
            if job and self.spots[job.target].reserved == job.pallet:
                self.spots[job.target].reserved = None
            return True
        job.from_loc = self.loc_of(p)
        sp = self.spots[p.ref]
        if sp.pallet == p.id:
            sp.pallet = None
        p.loc, p.ref = "worker", w.id
        w.cargo.append(p.id)
        return True

    def _do_taxi_drop(self, w, j):
        job = self.jobs.get(j)
        if job is None or job.pallet not in w.cargo:
            return True
        p = self.pallets[job.pallet]
        sp = self.spots[job.target]
        sp.pallet, sp.reserved = p.id, None
        p.loc, p.ref = "spot", sp.id
        p.x, p.y = sp.x + 0.5, sp.y + 0.5
        w.cargo.remove(p.id)
        self._txn("TXI", p, frm=job.from_loc, to=self.layout.spot_code[sp.id], user=w.id, equip="TAXI")
        if p.recalled and self.recall and self.recall["pulling"]:
            self._send_to_qa(p, "recall")
        else:
            self._request_putaway(p)                 # reach truck takes it up into the rack
        return True

    def _do_lift(self, w, j):
        job = self.jobs.get(j)
        p = self.pallets.get(job.pallet) if job else None
        if p is None or p.loc not in ("slot", "spot") or w.forklift is None:
            self._abort_job(w)
            return True
        f = self.forklifts[w.forklift]
        job.from_loc = self.loc_of(p)
        if p.loc == "slot":
            self._take_from_slot(p)
        else:
            sp = self.spots[p.ref]
            if sp.pallet == p.id:
                sp.pallet = None
        p.loc, p.ref = "forklift", f.id
        f.carrying = p.id
        f.battery = max(0.0, f.battery - C.BATTERY_DRAIN_PER_LIFT)
        return True

    def _do_place_slot(self, w, j):
        job = self.jobs[j]
        p = self.pallets[job.pallet]
        f = self.forklifts[w.forklift]
        slot = self.slots[job.target]
        self._put_in_slot(p, slot)
        f.carrying = None
        f.battery = max(0.0, f.battery - C.BATTERY_DRAIN_PER_LIFT)
        self._txn("PUT", p, frm=job.from_loc, to=self.layout.slot_code[slot.id], user=w.id, equip=f"FLT-{f.id}")
        self.data.row("fact_putaway", pallet_id=p.id, sku_code=p.sku, zone=slot.zone, slot_id=slot.id,
                      level=slot.level, operator_id=w.id, forklift_id=f.id, start_ts=self.ts(job.start_t),
                      end_ts=self.ts(), travel_m=round(w.dist, 1),
                      dock_dwell_min=round((self.t - (p.received_t or self.t)) / 60, 1))
        if p.recalled and self.recall and self.recall["pulling"]:
            self._send_to_qa(p, "recall")
        return True

    def _do_drop_qa(self, w, j):
        job = self.jobs[j]
        p = self.pallets[job.pallet]
        f = self.forklifts[w.forklift]
        sp = self.spots[job.target]
        sp.pallet, sp.reserved = p.id, None
        p.loc, p.ref = "spot", sp.id
        p.x, p.y = sp.x + 0.5, sp.y + 0.5
        f.carrying = None
        self._txn("QAM", p, frm=job.from_loc, to=self.layout.spot_code[sp.id], user=w.id, equip=f"FLT-{f.id}",
                  doc_type="QA", reason=job.reason)
        if job.reason == "recall" or (p.recalled and self.recall and self.recall["pulling"]):
            p.status = "recalled"
            self._schedule(self.t + C.DISPOSE_AFTER_H * 3 * 3600, "dispose", pid=p.id)
            self._check_recall_done()
        elif job.reason == "spoiled":
            p.status = "spoiled"
            self._schedule(self.t + C.DISPOSE_AFTER_H * 3600, "dispose", pid=p.id)
        else:
            p.status = "qa_hold"
            self._new_job("inspect", pallet=p.id, priority=30)
        return True

    def _do_qa_decide(self, w, j):
        job = self.jobs[j]
        p = self.pallets.get(job.pallet)
        if p is None or p.status != "qa_hold":
            return True
        self.qa_decision(p.id, None, w.id)
        return True

    def qa_decision(self, pid, release: bool | None, inspector=None):
        """QA outcome. release=None lets the inspector decide; the player can force True/False."""
        p = self.pallets.get(pid)
        if p is None or p.status != "qa_hold" or p.mixed:
            return
        sku = self.skus[p.sku]
        if release is None:
            spec = C.INBOUND_SPEC[sku.zone]
            near = p.temp_c <= spec["accept_max"] + 1.5 and p.excursion_min < C.EXCURSION_QA_MIN * 2
            release = self.rng.random() < C.QA_RELEASE_PROB["near" if near else "far"]
        self.data.row("fact_events", ts=self.ts(), event_type="qa_decision",
                      detail=json.dumps({"pallet": pid, "lot": p.lot, "sku": p.sku, "release": release,
                                         "inspector": inspector, "temp_c": p.temp_c,
                                         "excursion_min": p.excursion_min}))
        for jid in list(self.open_jobs["inspect"]):
            if self.jobs[jid].pallet == pid:
                self.open_jobs["inspect"].remove(jid)
                del self.jobs[jid]
        for jid in list(self.open_jobs["move_qa"]):
            if self.jobs[jid].pallet == pid:
                job = self.jobs.pop(jid)
                self.open_jobs["move_qa"].remove(jid)
                if job.target is not None:
                    self.spots[job.target].reserved = None
        self._txn("QRL" if release else ("RTV" if p.qa_reason == "inbound" else "QRJ"), p, frm=self.loc_of(p),
                  to=self.loc_of(p), user=inspector or "", doc_type="QA",
                  reason=f"{p.qa_reason or 'excursion'} {p.temp_c} C")
        if release:
            p.status = "received"
            p.excursion_min = 0.0
            self.fx_text(p.x, p.y, "fx_qa_ok", "good", lot=p.lot)
            self.log("log_qa_release", "info", lot=p.lot)
            if p.loc == "slot":
                p.status = "stored"
                if p.id not in self.stock[p.sku]:
                    self.stock[p.sku].append(p.id)
            else:
                self._request_putaway(p)
        else:
            p.status = "rejected"
            if p.qa_reason == "inbound":       # arrived warm: claimed back from the supplier
                self._cost("rejected_cost", C.REJECT_HANDLING_COST)
            else:                              # went out of spec in our building: our loss
                self._cost("rejected_cost", p.cases * sku.value * C.REJECTED_LOAD_COST_SHARE)
            self.stats["pallets_rejected"] += 1
            self.fx_text(p.x, p.y, "fx_rejected", "bad", lot=p.lot)
            self.log("log_rejected", "bad", lot=p.lot, sku=p.sku, temp=p.temp_c)
            if p.loc == "slot":
                self._take_from_slot(p)
                self.slots[p.ref].pallet = None
                del self.pallets[p.id]
            else:
                self._schedule(self.t + C.DISPOSE_AFTER_H * 3600, "dispose", pid=p.id)

    def _do_pick(self, w, j, i):
        job = self.jobs[j]
        pk = job.picks[i]
        o = self.orders.get(job.order)
        if pk["n"] <= 0 or o is None:
            return True
        p = self.pallets.get(pk["p"])
        ln = self._line(o, pk["sku"])
        if p is None or p.status != "stored" or p.recalled or p.loc != "slot":
            if p is not None:
                p.reserved = max(0, p.reserved - pk["n"])
            picks, rem = self._allocate(pk["sku"], pk["n"], self._min_bb(o, pk["sku"]))
            ln["alloc"] -= rem
            new_steps = []
            for pid, n in picks:
                item = self._pick_item(pid, pk["sku"], n)
                job.picks.append(item)
                idx = len(job.picks) - 1
                new_steps += [G(item["ax"], item["ay"]), W(C.PICK_LINE_S + n * C.PICK_CASE_S / w.skill, "pick"),
                              D("pick", j=j, i=idx)]
            pk["n"] = 0
            w.steps[0:0] = new_steps
            return True
        n = pk["n"]
        sku = self.skus[pk["sku"]]
        p.cases -= n
        p.reserved = max(0, p.reserved - n)
        case_kg = [round(self.rng.uniform(sku.weight_min, sku.weight_max), 2) for _ in range(n)]
        kg = round(sum(case_kg), 2)
        if not w.build_sscc:                           # first case on an empty jack: new outbound licence plate
            w.build_sscc = M.sscc(500_000_000 + self._nid("lp"))
        slot_code = self.layout.slot_code[pk["slot"]]
        self._txn("PCK", p, cases=n, kg=kg, sscc=w.build_sscc, from_sscc=p.sscc, frm=slot_code,
                  to=f"JACK-{w.id}", user=w.id, doc_type="SO", doc_no=self.so_no(o.id))
        if C.CASE_SCANS:
            for i, ck in enumerate(case_kg, 1):
                self.data.row("fact_case_scans", ts=self.ts(), sscc=w.build_sscc, from_sscc=p.sscc,
                              sku_code=sku.code, gtin=self.gtin[sku.code], lot=p.lot, case_seq=i,
                              net_kg=ck, order_id=o.id, picker_id=w.id, location=slot_code)
        w.jack_load.append([sku.code, p.lot, n, kg])
        w.cases_picked += n
        ln["picked"] += n
        self.stats["cases_picked"] += n
        self.stats["lines_picked"] += 1
        self.cum["lines"] += 1
        self.picks_this_hour += n
        mispick = self.rng.random() < C.MISPICK_PROB / w.skill
        if mispick:
            self.stats["mispicks"] += 1
            self.cum["mispicks"] += 1
            if self.rng.random() < C.MISPICK_CATCH_PROB:
                w.steps.insert(0, W(60, "recount"))
                mispick = 2
            else:
                o.mispicks_uncaught += 1
        slot = self.slots[pk["slot"]]
        self.data.row("fact_picks", pick_id=self._nid("pick"), order_id=o.id, store_id=o.store, job_id=j,
                      picker_id=w.id, sku_code=sku.code, lot=p.lot, pallet_id=p.id, from_sscc=p.sscc,
                      to_sscc=w.build_sscc, slot_id=slot.id, location=slot_code,
                      zone=slot.zone, level=slot.level, cases=n, weight_kg=kg, start_ts=self.ts(w.mark_t),
                      end_ts=self.ts(), travel_m=round(w.dist, 1), mispick=int(bool(mispick)),
                      mispick_caught=int(mispick == 2), shift=w.shift, picker_skill=w.skill,
                      days_to_expiry=round(p.bb_day - self.t / DAY, 2))
        w.mark_t = self.t
        w.dist = 0.0
        if p.cases <= 0:
            self._take_from_slot(p)
            del self.pallets[p.id]
        return True

    def _do_finish_pick(self, w, j):
        job = self.jobs[j]
        o = self.orders.get(job.order)
        if not w.jack_load:
            if o:
                o.jobs_open -= 1
                if o.jobs_open == 0 and o.status == "released":
                    o.status = "picked"
                self._maybe_close_order(o)
            return True
        door = self._route_door(o.route).id if o else None
        sp = self._free_spot("out", door)
        if sp is None:
            return False
        sp.reserved = -job.id
        job.target = sp.id
        w.steps[0:0] = [G(sp.x, sp.y), W(C.WRAP_S, "wrap"), D("drop_out", j=j)]
        return True

    def _do_drop_out(self, w, j):
        job = self.jobs[j]
        o = self.orders.get(job.order)
        sp = self.spots[job.target]
        pid = self._nid("pallet")
        cases = sum(c[2] for c in w.jack_load)
        kg = round(sum(c[3] for c in w.jack_load), 1)
        if job.temp_class == "frozen":
            temp = self.zones["freezer"].temp
        else:
            temp = (self.zones["fresh"].temp + self.zones["processed"].temp) / 2
        p = Pallet(id=pid, sku=None, lot=0, cases=cases, status="staged_out", loc="spot", ref=sp.id,
                   temp_c=round(temp, 1),
                   mixed=True, store=o.store if o else None, order_id=job.order,
                   contents=[list(c) for c in w.jack_load], temp_class=job.temp_class, weight_kg=kg,
                   x=sp.x + 0.5, y=sp.y + 0.5, received_t=self.t,
                   sscc=w.build_sscc or M.sscc(500_000_000 + self._nid("lp")))
        self.pallets[pid] = p
        sp.pallet, sp.reserved = pid, None
        self._txn("BLD", p, frm=f"JACK-{w.id}", to=self.layout.spot_code[sp.id], user=w.id, doc_type="SO",
                  doc_no=self.so_no(job.order) if job.order else "", reason=f"{len(p.contents)} lines wrapped")
        w.jack_load = []
        w.build_sscc = ""
        if o is None:
            return True
        o.pallets.append(pid)
        o.jobs_open -= 1
        if o.jobs_open == 0 and o.status == "released":
            o.status = "picked"
        if o.departed:
            self._expedite(p, o)
        self._maybe_close_order(o)
        return True

    def _do_take(self, w, j):
        job = self.jobs[j]
        p = self.pallets.get(job.pallet)
        if p is None or p.loc != "spot":
            self._abort_job(w)
            return True
        job.from_loc = self.loc_of(p)
        sp = self.spots[p.ref]
        if sp.pallet == p.id:
            sp.pallet = None
        p.loc, p.ref = "worker", w.id
        w.carrying = p.id
        return True

    def _do_load_truck(self, w, j):
        job = self.jobs[j]
        p = self.pallets.get(job.pallet)
        w.carrying = None
        if p is None:
            return True
        o = self.orders.get(p.order_id)
        tr = self.trucks.get(job.truck)
        if tr is None or tr.state != "docked":
            p.x, p.y = w.x, w.y
            if o:
                self._expedite(p, o)
                self._maybe_close_order(o)
            return True
        tr.pallets.append(p.id)
        p.loc, p.ref, p.status = "truck", tr.id, "loaded"
        self._txn("LOD", p, frm=job.from_loc, to=f"TRL-{tr.id}", user=w.id, doc_type="BOL", doc_no=self.bol_no(tr.id))
        return True

    # ------------------------------------------------------------------ day close & KPIs
    def _close_day(self, day):
        s = self.stats
        cost_keys = ["wages", "energy", "spoilage", "penalties", "rejected_cost", "expedite_cost",
                     "repair_cost", "incident_cost", "fixed_cost"]
        costs = sum(s[k] for k in cost_keys)
        summary = {
            "day": day, "date": self.day_str(day),
            "revenue": s["revenue"], "costs": costs, "profit": s["revenue"] - costs,
            **{k: s[k] for k in cost_keys},
            "cases_shipped": int(s["cases_shipped"]), "cases_picked": int(s["cases_picked"]),
            "orders": int(s["orders_closed"]),
            "on_time": s["orders_on_time"] / s["orders_closed"] if s["orders_closed"] else None,
            "fill_rate": s["cases_shipped_closed"] / s["cases_ordered_closed"] if s["cases_ordered_closed"] else None,
            "accuracy": 1 - s["mispicks"] / s["lines_picked"] if s["lines_picked"] else None,
            "cph": s["cases_picked"] / s["picker_hours"] if s["picker_hours"] else None,
            "compliance": 1 - s["comp_out"] / s["comp_total"] if s["comp_total"] else None,
            "temp_alarms": int(s["temp_alarms"]), "pallets_received": int(s["pallets_received"]),
            "pallets_rejected": int(s["pallets_rejected"]), "pallets_qa": int(s["pallets_qa"]),
            "inbound_trucks": int(s["inbound_trucks"]), "inbound_late": int(s["inbound_late"]),
            "breakdowns": int(s["breakdowns"]), "expedites": int(s["expedites"]),
            "spoiled_cases": int(s["spoiled_cases"]), "sick_calls": int(s["sick_calls"]),
            "injuries_lost_time": int(s["injuries_lost_time"]), "injuries_medical": int(s["injuries_medical"]),
            "forklift_incidents": int(s["forklift_incidents"]), "damaged_cases": int(s["damaged_cases"]),
            "cash": self.money,
        }
        self.history.append(summary)
        row = {k: (round(v, 4) if isinstance(v, float) else ("" if v is None else v))
               for k, v in summary.items() if k != "day"}
        self.data.row("fact_daily_kpi", **row)
        for z in self.zones.values():
            self.data.row("fact_energy_daily", date=summary["date"], zone=z.key, kwh=round(z.kwh_today, 1),
                          cost=round(z.kwh_today * C.ENERGY_PRICE_KWH, 2), door_passes=z.door_passes_today)
            z.kwh_today = 0.0
            z.door_passes_today = 0
        self.data.row("fact_weather", date=summary["date"],
                      ambient_mean_c=round(self.amb_base + self.weather_anom, 1),
                      ambient_max_c=round(self.amb_base + self.weather_anom + C.AMBIENT_DAILY_SWING, 1))
        return summary

    def _prune(self, day):
        for oid in [oid for oid, o in self.orders.items() if o.status == "closed" and o.shipped_t
                    and o.shipped_t < self.t - 2 * DAY]:
            del self.orders[oid]
        for key in [k for k, d in self.departures.items() if d["done"] and d["dep"] < self.t - 2 * DAY]:
            del self.departures[key]
        cutoff = self.t - 60 * DAY
        for lot in list(self.lot_shipments):
            rows = [r for r in self.lot_shipments[lot] if r[2] >= cutoff]
            if rows:
                self.lot_shipments[lot] = rows
            else:
                del self.lot_shipments[lot]
        for code in self.demand_by_day:
            self.demand_by_day[code] = {d: q for d, q in self.demand_by_day[code].items() if d >= day - 14}

    def kpis(self):
        s = self.stats
        cum = self.cum
        fill = {}
        for key, slots in self.slots_by_zone.items():
            used = sum(1 for sl in slots if sl.pallet is not None or sl.reserved_for is not None)
            fill[key] = used / len(slots)
        cph_hours = sum(1 for w in self.workers.values() if w.role == "picker" and w.state != "off")
        return {
            "money": self.money,
            "on_time": cum["on_time"] / cum["orders"] if cum["orders"] else None,
            "fill_rate": cum["shipped"] / cum["ordered"] if cum["ordered"] else None,
            "accuracy": 1 - cum["mispicks"] / cum["lines"] if cum["lines"] else None,
            "cph": self.chart_picks[-1] / cph_hours if cph_hours else None,
            "cph_today": s["cases_picked"] / s["picker_hours"] if s["picker_hours"] else None,
            "compliance": 1 - cum["comp_out"] / cum["comp_total"] if cum["comp_total"] else None,
            "spoilage": s["spoilage"],
            "alarms": int(s["temp_alarms"]),
            "active_alarms": [z.key for z in self.zones.values() if z.alarm],
            "energy": s["energy"],
            "cases_shipped": int(s["cases_shipped"]),
            "profit_today": s["revenue"] - sum(s[k] for k in ("wages", "energy", "spoilage", "penalties",
                                                                "rejected_cost", "expedite_cost",
                                                                "repair_cost", "incident_cost",
                                                                "fixed_cost")),
            "fill": fill,
            "open_orders": sum(1 for o in self.orders.values() if o.status != "closed"),
            "open_jobs": {k: len(v) for k, v in self.open_jobs.items()},
        }

    # ------------------------------------------------------------------ save / load
    def to_state(self):
        rng = self.rng.getstate()
        return {
            "version": 1, "seed": self.seed, "t": self.t, "day": self.day, "money": self.money,
            "rng": [rng[0], list(rng[1]), rng[2]], "ids": self.ids,
            "pallets": [to_dict(p) for p in self.pallets.values()],
            "slots": [[s.pallet, s.reserved_for] for s in self.slots],
            "spots": [[s.pallet, s.reserved] for s in self.spots],
            "doors": [[d.open, d.truck] for d in self.doors],
            "trucks": [to_dict(t) for t in self.trucks.values()],
            "truck_extra": {t.id: t.__dict__.get("_unloaded", 0) for t in self.trucks.values()},
            "orders": [to_dict(o) for o in self.orders.values()],
            "workers": [to_dict(w) for w in self.workers.values()],
            "forklifts": [to_dict(f) for f in self.forklifts.values()],
            "jobs": [to_dict(j) for j in self.jobs.values()],
            "open_jobs": self.open_jobs, "stock": self.stock,
            "zones": [to_dict(z) for z in self.zones.values()],
            "sched": self.sched, "seq": self.seq, "departures": self.departures, "lots": self.lots,
            "lot_shipments": self.lot_shipments, "recall": self.recall, "last_recall": self.last_recall,
            "pending_putaway": self.pending_putaway,
            "demand_by_day": {c: {str(d): q for d, q in v.items()} for c, v in self.demand_by_day.items()},
            "parking": self.parking, "weather_anom": self.weather_anom, "amb_base": self.amb_base,
            "stats": self.stats, "cum": self.cum, "history": self.history, "logbook": list(self.logbook),
            "chart_shipped": self.chart_shipped, "chart_freezer": list(self.chart_freezer),
            "chart_picks": list(self.chart_picks), "picks_this_hour": self.picks_this_hour,
            "flags": self.flags,
        }

    def _restore(self, s):
        self.seed = s["seed"]
        self.rng = random.Random()
        self.rng.setstate((s["rng"][0], tuple(s["rng"][1]), s["rng"][2]))
        self.t, self.day, self.money, self.ids = s["t"], s["day"], s["money"], s["ids"]
        self.pallets = {d["id"]: from_dict(Pallet, d) for d in s["pallets"]}
        for sl, (pid, res) in zip(self.slots, s["slots"]):
            sl.pallet, sl.reserved_for = pid, res
        for sp, (pid, res) in zip(self.spots, s["spots"]):
            sp.pallet, sp.reserved = pid, res
        for d, (op, tr) in zip(self.doors, s["doors"]):
            d.open, d.truck = op, tr
        self.trucks = {d["id"]: from_dict(Truck, d) for d in s["trucks"]}
        for tid, n in s.get("truck_extra", {}).items():
            if int(tid) in self.trucks:
                self.trucks[int(tid)].__dict__["_unloaded"] = n
        self.orders = {d["id"]: from_dict(Order, d) for d in s["orders"]}
        self.workers = {d["id"]: from_dict(Worker, d) for d in s["workers"]}
        self.forklifts = {d["id"]: from_dict(Forklift, d) for d in s["forklifts"]}
        self.jobs = {d["id"]: from_dict(Job, d) for d in s["jobs"]}
        self.open_jobs = s["open_jobs"]
        self.stock = s["stock"]
        self.zones = {d["key"]: from_dict(Zone, d) for d in s["zones"]}
        self.sched = s["sched"]
        heapq.heapify(self.sched)
        self.seq = s["seq"]
        self.departures, self.lots = s["departures"], s["lots"]
        self.lot_shipments, self.recall, self.last_recall = s["lot_shipments"], s["recall"], s["last_recall"]
        self.pending_putaway = s["pending_putaway"]
        self.demand_by_day = {c: {int(d): q for d, q in v.items()} for c, v in s["demand_by_day"].items()}
        self.parking = s["parking"]
        self.weather_anom, self.amb_base = s["weather_anom"], s["amb_base"]
        self.stats, self.cum, self.history = s["stats"], s["cum"], s["history"]
        self.logbook = deque(s["logbook"], maxlen=300)
        self.chart_shipped = s["chart_shipped"]
        self.chart_freezer = deque(s["chart_freezer"], maxlen=96)
        self.chart_picks = deque(s["chart_picks"], maxlen=24)
        self.picks_this_hour = s["picks_this_hour"]
        self.flags = s["flags"]
        for w in self.workers.values():
            w.path = []
            for st in w.steps:
                st.pop("go", None)      # paths are recomputed after loading

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_state(), fh)

    @classmethod
    def load(cls, path, datalog=None):
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        return cls(datalog=datalog, state=state)
