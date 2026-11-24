"""Random and seasonal events. Rates come from config.EVENT_RATES (expected per day).

Every draw uses sim.rng so a seeded run is fully reproducible.
"""
from __future__ import annotations

import config as C


class EventManager:
    def day_start(self, sim):
        season = sim.season_on(sim.date())
        if season != sim.flags.get("season"):
            sim.flags["season"] = season
            if season:
                sim.log("ev_season", "event", season=season)

    def hourly(self, sim):
        for kind, per_day in C.EVENT_RATES.items():
            if sim.rng.random() < per_day / 24:
                getattr(self, "_" + kind)(sim)

    def sick_call(self, sim, worker) -> bool:
        return sim.rng.random() < C.SICK_PROB

    # ------------------------------------------------------------ triggers
    @staticmethod
    def _upcoming_inbound(sim):
        return [tr for tr in sim.trucks.values()
                if tr.kind == "in" and tr.state == "scheduled" and tr.planned_t > sim.t + 1800]

    def _late_truck(self, sim):
        trucks = self._upcoming_inbound(sim)
        if not trucks:
            return
        tr = sim.rng.choice(trucks)
        minutes = sim.rng.uniform(*C.LATE_TRUCK_EXTRA_MIN)
        tr.planned_t += minutes * 60      # the old arrival event reschedules itself
        sim.log("ev_late_truck", "event", plant=tr.origin, minutes=int(minutes))

    def _reefer_failure(self, sim):
        trucks = [tr for tr in self._upcoming_inbound(sim) if not tr.reefer_fail]
        if not trucks:
            return
        tr = sim.rng.choice(trucks)
        tr.reefer_fail = True
        sim.log("ev_reefer", "event", plant=tr.origin)

    def _freezer_door(self, sim):
        if not sim.zones["freezer"].stuck_open:
            sim.set_door_stuck("freezer", sim.rng.uniform(*C.FREEZER_DOOR_STUCK_MIN))

    def _forklift_breakdown(self, sim):
        ok = [f for f in sim.forklifts.values() if f.state != "broken"]
        if len(ok) > 1:
            sim.break_forklift(sim.rng.choice(ok).id)

    def _rush_order(self, sim):
        stores = list(sim.stores.values())
        s = sim.rng.choices(stores, weights=[st.size for st in stores])[0]
        sim.create_rush_order(s.id)

    def _recall(self, sim):
        if sim.recall is not None:
            return
        lots = sorted({p.lot for p in sim.pallets.values() if not p.mixed and p.status == "stored"})
        if lots:
            sim.start_recall(sim.rng.choice(lots))
