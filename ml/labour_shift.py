"""Model 2b – labour planning per shift: how many pickers each shift needs tomorrow.

The daily plan (labour.py) failed its closed-loop test: it scaled every shift alike, but the work is
not spread alike. Departures run 03:00–18:00 and waves are released 5 h before, so the night and day
shifts do nearly all the picking while the evening shift has rush orders and little else. Here:

1. Volume: tomorrow's forecast (demand model) split by shift with each weekday's training share.
2. Capacity: per shift, a logistic curve of the late-order rate against load (cases per picker-hour),
   orders assigned to the shift that picked most of their cases; fitted on the training days of the
   three staffing scenarios. The plan load is where the curve reaches TARGET_LATE.
3. Crew: forecast cases / plan load / hours a scheduled picker works in that shift, plus a buffer;
   a shift that picks little keeps a minimum crew for rush orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

try:
    from . import common as cm, demand, labour
except ImportError:
    import common as cm
    import demand
    import labour

TARGET_LATE = 0.02
BUFFER = 0.05
MIN_CREW = 3                    # pickers kept on a shift that picks little (rush orders, short picks)
MIN_SHARE = 0.15                # below this share of the day's cases a shift gets the minimum crew
SCENARIOS = ("baseline", "lean_staff", "extra_pickers")


def _shift_date(ts, shift):
    """A night shift starts at 22:00: picks after midnight belong to the previous day's night shift."""
    ts = pd.to_datetime(ts)
    return (ts - pd.to_timedelta(np.where((shift == "night") & (ts.dt.hour < 12), 1, 0), unit="D")).dt.date.astype(str)


def shift_days(con, scenarios=SCENARIOS):
    """One row per scenario, shift-start date and shift: cases picked, picker-hours, orders and late orders."""
    s = ",".join(f"'{x}'" for x in scenarios)
    picks = cm.q(con, f"SELECT scenario, order_id, shift, start_ts, cases FROM fact_picks WHERE scenario IN ({s})")
    picks["date"] = _shift_date(picks["start_ts"], picks["shift"])
    vol = picks.groupby(["scenario", "date", "shift"], as_index=False)["cases"].sum()
    by_order = picks.groupby(["scenario", "order_id", "date", "shift"], as_index=False)["cases"].sum()
    main = by_order.sort_values("cases").groupby(["scenario", "order_id"]).tail(1)
    orders = cm.q(con, f"SELECT scenario, order_id, on_time FROM fact_orders WHERE scenario IN ({s})")
    main = main.merge(orders, on=["scenario", "order_id"])
    late = main.groupby(["scenario", "date", "shift"]).agg(orders=("on_time", "size"),
                                                          late=("on_time", lambda x: int((1 - x).sum())))
    hrs = cm.q(con, f"""SELECT scenario, date, shift, SUM(hours) AS hours FROM fact_labor
                        WHERE role = 'picker' AND scenario IN ({s}) GROUP BY 1, 2, 3""")
    d = vol.merge(hrs, on=["scenario", "date", "shift"]).merge(late.reset_index(), how="left",
                                                               on=["scenario", "date", "shift"])
    d[["orders", "late"]] = d[["orders", "late"]].fillna(0)
    d["load"] = d["cases"] / d["hours"]
    return d


def capacity(train):
    """Plan load per shift at TARGET_LATE, or None for a shift too small to need one."""
    out = {}
    share = train.groupby("shift")["cases"].sum() / train["cases"].sum()
    for sh, g in train.groupby("shift"):
        if share[sh] < MIN_SHARE:
            out[sh] = None
            continue
        rows = pd.concat([g.assign(y=1, w=g["late"]), g.assign(y=0, w=g["orders"] - g["late"])])
        rows = rows[rows["w"] > 0]
        lr = LogisticRegression(C=100.0).fit(rows[["load"]], rows["y"], sample_weight=rows["w"])
        a, b = lr.intercept_[0], lr.coef_[0][0]
        load = (np.log(TARGET_LATE / (1 - TARGET_LATE)) - a) / b if b > 0 else g["load"].quantile(0.9)
        out[sh] = float(min(load, g["load"].quantile(0.95)))      # never plan beyond what was observed
    return out, share.to_dict()


def run(con, scenario="baseline", demand_res=None, buffer=BUFFER):
    """Plan {date: {shift: pickers}} for the test days, with the inputs that produced it."""
    test_start = cm.split_date(con, scenario)
    sd = shift_days(con)
    train = sd[sd["date"] < test_start]
    loads, share = capacity(train)
    base = train[train["scenario"] == scenario].copy()
    base["weekday"] = pd.to_datetime(base["date"]).dt.day_of_week
    day_tot = base.groupby("date")["cases"].transform("sum")
    wshare = (base.assign(s=base["cases"] / day_tot).groupby(["weekday", "shift"])["s"].mean())
    head = {sh: roles["picker"] for sh, roles in cm.C.HEADCOUNT.items()}
    per_head = (base.groupby("shift")["hours"].mean() / pd.Series(head)).to_dict()   # hours a rostered picker works

    dres = demand_res or demand.run(con, scenario, plot=False)
    fc = dres["by_day"].set_index("date")["pred"]
    ratio = (sd[(sd["scenario"] == scenario) & (sd["date"] < test_start)]["cases"].sum()
             / labour.dres_ordered_train(con, scenario, test_start))
    static_cases = base.groupby("date")["cases"].sum().mean()       # no forecast: the training average
    plan, static = {}, {}
    for date in sorted(d for d in fc.index if d >= test_start):
        cases = fc[date] * ratio
        wd = pd.Timestamp(date).weekday()
        static[date] = {sh: MIN_CREW if loads.get(sh) is None else
                        max(MIN_CREW, int(np.ceil(static_cases * share[sh] / loads[sh] / per_head[sh] * (1 + buffer))))
                        for sh in head}
        plan[date] = {}
        for sh in head:
            if loads.get(sh) is None:
                plan[date][sh] = MIN_CREW
            else:
                need = cases * wshare.get((wd, sh), share[sh]) / loads[sh] / per_head[sh] * (1 + buffer)
                plan[date][sh] = max(MIN_CREW, int(np.ceil(need)))
    return {"plan": plan, "static_plan": static, "plan_load": loads, "shift_share": share, "hours_per_rostered_picker": per_head,
            "fixed_crew": head,
            "planned_pickers": {sh: float(np.mean([p[sh] for p in plan.values()])) for sh in head}}


if __name__ == "__main__":
    r = run(cm.connect())
    for k, v in r.items():
        if k != "plan":
            print(k, v)
