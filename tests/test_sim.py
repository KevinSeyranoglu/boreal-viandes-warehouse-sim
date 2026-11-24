"""Simulation invariants. Seeded headless runs, no pygame.

    python -m pytest tests/ -q
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402
import i18n  # noqa: E402
from simulation import DAY, Simulation  # noqa: E402


def run(sim, days):
    end = sim.t + days * DAY
    while sim.t < end:
        sim.step(C.HEADLESS_TICK_SECONDS)
    return sim


# ---------------------------------------------------------------- case conservation
class AuditDict(dict):
    """sim.pallets stand-in that remembers the cases on every pallet it drops."""

    def __init__(self, *a):
        super().__init__(*a)
        self.removed = 0

    def __delitem__(self, key):
        p = self[key]
        if p.status != "shipped" and not inbound(p):
            self.removed += p.cases      # disposed, rejected after receipt, recall-pulled …
        super().__delitem__(key)


def inbound(p):
    """Still on an inbound trailer (never received, or rejected at the door)."""
    return p.status == "inbound" or (p.status == "rejected" and p.loc == "truck")


def on_hand(sim):
    cases = sum(p.cases for p in sim.pallets.values() if not inbound(p))
    return cases + sum(c[2] for w in sim.workers.values() for c in w.jack_load)   # taxi cargo is in pallets


def audited(seed):
    sim = Simulation(seed=seed)
    sim.pallets = AuditDict(sim.pallets)
    flows = {"received": 0, "shipped": 0, "recall_cut": 0}

    take = sim._do_take_from_truck

    def take_from_truck(w, j):
        flows["received"] += sim.pallets[sim.jobs[j].pallet].cases
        return take(w, j)

    ship = sim._ship_pallet

    def ship_pallet(p, o):
        cases, rev = ship(p, o)
        flows["shipped"] += cases
        return cases, rev

    pull = sim.recall_pull

    def recall_pull(pid):
        p = sim.pallets.get(pid)
        before = p.cases if p is not None and p.mixed else None
        pull(pid)
        if before is not None and pid in sim.pallets:
            flows["recall_cut"] += before - sim.pallets[pid].cases

    sim._do_take_from_truck, sim._ship_pallet, sim.recall_pull = take_from_truck, ship_pallet, recall_pull
    return sim, flows


@pytest.mark.parametrize("scenario", ["baseline", "chaos"])
def test_cases_are_conserved(scenario, monkeypatch):
    for key, value in C.SCENARIOS[scenario].items():
        monkeypatch.setattr(C, key, value)
    sim, flows = audited(seed=42)
    start = on_hand(sim)
    run(sim, 14)
    assert flows["received"] > 0 and flows["shipped"] > 0
    out = (flows["shipped"] + sim.pallets.removed + flows["recall_cut"] + sim.cum.get("damaged_cases", 0)
           + sim.cum.get("recall_jack_cases", 0))
    assert start + flows["received"] == on_hand(sim) + out


# ---------------------------------------------------------------- reproducibility
def fingerprint(sim):
    return json.dumps({"t": sim.t, "money": round(sim.money, 6), "history": sim.history,
                       "cum": sim.cum, "pallets": len(sim.pallets)}, sort_keys=True, default=str)


def test_same_seed_same_run():
    assert fingerprint(run(Simulation(seed=7), 3)) == fingerprint(run(Simulation(seed=7), 3))


def test_different_seed_different_run():
    assert fingerprint(run(Simulation(seed=7), 3)) != fingerprint(run(Simulation(seed=8), 3))


# ---------------------------------------------------------------- flow health (regressions)
@pytest.fixture(scope="module")
def month():
    return run(Simulation(seed=42), 30)


def test_receiving_never_stalls(month):
    """Regression: blocked QA moves used to starve put-away and deadlock inbound by day 8."""
    for day in month.history[1:]:
        assert day["pallets_received"] > 0, f"no receipts on day {day['day']}"
        assert day["fill_rate"] is None or day["fill_rate"] > 0.9, f"fill rate {day['fill_rate']} on day {day['day']}"


def test_orders_ship_on_time(month):
    k = month.kpis()
    assert k["on_time"] > 0.9 and k["fill_rate"] > 0.95
    assert sum(d["cases_shipped"] for d in month.history) > 30 * 3000


def test_inbound_trucks_are_consolidated(month):
    trucks = sum(d["inbound_trucks"] for d in month.history[1:])
    pallets = sum(d["pallets_received"] + d["pallets_rejected"] for d in month.history[1:])
    assert pallets / trucks >= 0.8 * C.MIN_INBOUND_PALLETS


def test_forklift_fleet_not_stranded(month):
    """Regression: parked forklifts below BATTERY_MIN_TO_TAKE used to drain to 0 % forever."""
    usable = [f for f in month.forklifts.values()
              if f.state == "charging" or f.battery >= C.BATTERY_MIN_TO_TAKE or f.operator is not None]
    assert len(usable) >= len(month.forklifts) // 2


def test_stuck_freezer_door_does_not_flag_frozen_product():
    """Product temperature lags the air: a 60-minute stuck door must not put stock on QA hold."""
    sim = run(Simulation(seed=3), 0.2)
    sim.set_door_stuck("freezer", 60)
    peak = -99.0
    for _ in range(int(3 * 3600 / C.HEADLESS_TICK_SECONDS)):
        sim.step(C.HEADLESS_TICK_SECONDS)
        peak = max(peak, sim.zones["freezer"].temp)
    assert peak > -15                                 # the air did warm up …
    frozen = [p for p in sim.pallets.values() if not p.mixed and p.temp_class == "frozen" and p.loc == "slot"]
    assert frozen and all(p.temp_c < -15 for p in frozen)   # … the product did not
    assert not [j for j in sim.jobs.values() if j.kind == "move_qa" and j.reason == "excursion"]


def test_staffing_moves_service_levels(monkeypatch):
    """The data must carry signal: fewer pickers -> more late orders, more pickers -> fewer."""
    on_time = {}
    for scenario in ("lean_staff", "baseline", "extra_pickers"):
        monkeypatch.setattr(C, "HEADCOUNT", C.SCENARIOS[scenario].get("HEADCOUNT", C.HEADCOUNT))
        on_time[scenario] = run(Simulation(seed=42), 14).kpis()["on_time"]
        monkeypatch.undo()
    assert on_time["lean_staff"] < on_time["baseline"] < on_time["extra_pickers"]


def test_recalled_lot_never_comes_back():
    """Regressions: after a recall the plant shipped the same lot again, and outbound pallets of the lot kept
    shipping during the 1–4 h before the physical pull."""
    sim = run(Simulation(seed=42), 2)
    lot = next(p.lot for p in sim.pallets.values() if not p.mixed and p.status == "stored")
    sim.start_recall(lot)
    # the lot hold is immediate: no outbound pallet or picker jack still carries it
    assert not any(p.mixed and any(c[1] == lot for c in p.contents) for p in sim.pallets.values())
    assert not any(c[1] == lot for w in sim.workers.values() for c in w.jack_load)
    made, picked = [], []
    make, pick = sim._make_pallet, sim._do_pick

    def spy_make(*a, **k):
        p = make(*a, **k)
        made.append(p.lot)
        return p

    def spy_pick(w, j, i):
        pk = sim.jobs[j].picks[i]
        p = sim.pallets.get(pk["p"])
        if p is not None and pk["n"] > 0 and p.status == "stored" and not p.recalled and p.loc == "slot":
            picked.append(p.lot)
        return pick(w, j, i)
    sim._make_pallet, sim._do_pick = spy_make, spy_pick
    run(sim, 5)
    assert made and lot not in made                    # the plant uses new lot numbers
    assert picked and lot not in picked                # and nothing of it is picked again
    key = next(k for k, v in sim.lots.items() if v == lot)
    plant, code, pack_day = key.split("|")[:3]
    assert sim._lot(plant, code, float(pack_day)) != lot   # same plant, product and pack day -> new lot


def test_recall_that_empties_a_staged_pallet_drops_its_load_job():
    """Regression (chaos, seed 23, day 21): a recall emptied a staged mixed pallet and deleted it, but its
    open load job stayed queued; the next loader to claim it crashed on the missing pallet."""
    sim = Simulation(seed=42)
    target = None
    while target is None and sim.t < 3 * DAY:
        sim.step(C.HEADLESS_TICK_SECONDS)
        target = next((p for jid in sim.open_jobs["load"] if (p := sim.pallets.get(sim.jobs[jid].pallet))
                       and p.mixed and len({c[1] for c in p.contents}) == 1), None)
    assert target is not None, "no single-lot staged pallet in 3 days: the sim changed, pick another seed"
    sim.start_recall(target.contents[0][1])
    sim.recall_pull_all()
    assert target.id not in sim.pallets
    assert all(sim.jobs[j].pallet in sim.pallets for j in sim.open_jobs["load"])
    run(sim, 1)                                        # loaders keep claiming jobs without a KeyError


# ---------------------------------------------------------------- save / load
def test_save_load_round_trip(tmp_path):
    sim = run(Simulation(seed=11), 1.3)
    path = tmp_path / "save.json"
    sim.save(path)
    loaded = Simulation.load(path)
    before = json.loads(json.dumps(sim.to_state()))
    after = json.loads(json.dumps(loaded.to_state()))
    for w in before["workers"]:          # paths are recomputed after loading
        w["path"] = []
        for st in w["steps"]:
            st.pop("go", None)
    assert before == after
    run(loaded, 1)                       # and the loaded game keeps running
    assert loaded.history[-1]["cases_shipped"] > 0


# ---------------------------------------------------------------- headless CLI + text
def test_headless_writes_csv_without_pygame(tmp_path):
    out = tmp_path / "data"
    code = ("import sys, main; main.main(['--headless', '--days', '1', '--out', sys.argv[1]]); "
            "assert 'pygame' not in sys.modules")
    subprocess.run([sys.executable, "-c", code, str(out)], cwd=ROOT, check=True, capture_output=True)
    for table in ("dim_sku", "fact_orders", "fact_picks", "fact_temperature", "fact_pallet_receipts"):
        with open(out / f"{table}.csv", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows, table


def test_shared_dock_receives_and_ships_on_the_same_doors(tmp_path):
    """U-flow option: 14 doors on the east wall do both jobs. An inbound trailer never takes a door whose
    outbound trailer leaves within the buffer + loading window, and service holds up."""
    out = tmp_path / "shared"
    subprocess.run([sys.executable, "main.py", "--headless", "--days", "6", "--scenario", "shared_dock",
                    "--out", str(out)], cwd=ROOT, check=True, capture_output=True)

    def rows(table):
        with open(out / f"{table}.csv", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    codes = {r["location"] for r in rows("dim_location")}
    assert sum(c.startswith("DCK-D") for c in codes) == C.SHIPPING_DOORS
    assert not any(c.startswith(("RCV-D", "SHP-D")) for c in codes)
    ts = __import__("datetime").datetime.fromisoformat
    window = (C.INBOUND_DOOR_BUFFER_H + C.OUTBOUND_ARRIVE_BEFORE_H) * 3600
    departures = {}
    for s in rows("fact_shipments"):
        departures.setdefault(s["door"], []).append(ts(s["scheduled_departure_ts"]))
    inbound = rows("fact_inbound_trucks")
    assert len({r["door"] for r in inbound}) >= 4
    for r in inbound:
        docked = ts(r["dock_ts"])
        assert not any(0 <= (d - docked).total_seconds() < window for d in departures.get(r["door"], [])), r
    kpi = rows("fact_daily_kpi")
    assert sum(float(k["on_time"]) for k in kpi[1:]) / len(kpi[1:]) > 0.9


def test_every_sim_message_is_translated():
    src = "".join(open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("simulation.py", "events.py"))
    keys = set(re.findall(r'(?:log|fx_text)\([^"]*"((?:log|ev|fx)_[a-z_]+)"', src))
    assert keys and not keys - set(i18n.TEXT)
    for lang in i18n.LANGS:
        i18n.set_lang(lang)
        assert all(i18n.TEXT[k][i18n.LANGS.index(lang)] for k in keys)
    i18n.set_lang("fr")
