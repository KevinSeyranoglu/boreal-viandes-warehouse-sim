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
        self._incidents(sim)

    # ------------------------------------------------------------ injuries and forklift accidents
    @staticmethod
    def _pick(rng, weights):
        return rng.choices(list(weights), weights=list(weights.values()))[0]

    def _incidents(self, sim):
        """One draw per worker-hour and per driven forklift-hour, at the rates in config.py
        (lost-time injuries: 1.30 per 100 workers per year)."""
        mult = C.INCIDENT_RATE_MULT
        lost = C.LOST_TIME_INJURY_RATE * mult
        aid = lost * C.MEDICAL_AID_PER_LOST_TIME
        for w in list(sim.workers.values()):
            if w.state != "active" or w.injured_until > sim.t:
                continue
            r = sim.rng.random()
            if r < lost + aid:
                sim.injure(w, self._pick(sim.rng, C.INJURY_TYPES), lost_time=r < lost)
        hurt = C.FORKLIFT_INJURY_RATE * mult
        damage = hurt * C.FORKLIFT_DAMAGE_PER_INJURY
        for f in list(sim.forklifts.values()):
            if f.state != "busy" or f.operator is None:
                continue
            r = sim.rng.random()
            if r < hurt:
                sim.forklift_accident(f, self._pick(sim.rng, C.FORKLIFT_INJURY_TYPES), injury=True)
            elif r < hurt + damage:
                sim.forklift_accident(f, self._pick(sim.rng, C.FORKLIFT_DAMAGE_TYPES), injury=False)

    def sick_call(self, sim, worker) -> bool:
        return sim.rng.random() < C.SICK_PROB

    # ------------------------------------------------------------ triggers
    @staticmethod
    def _upcoming_inbound(sim):
        return [tr for tr in sim.trucks.values()
                if tr.kind == "in" and tr.state == "scheduled" and tr.planned_t > sim.t + 1800]

    @staticmethod
    def _not_yet_delayed(sim, trucks):
        """A truck is hit by at most one delay event (its own lateness is already in planned_t)."""
        cap = C.LATENESS_CLIP_MIN[1] * 60
        return [tr for tr in trucks if tr.planned_t - tr.sched_t <= cap]

    def _late_truck(self, sim):
        trucks = self._not_yet_delayed(sim, self._upcoming_inbound(sim))
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
