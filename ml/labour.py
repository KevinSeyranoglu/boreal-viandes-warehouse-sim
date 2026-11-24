"""Model 2 – labour planning: how many picker-hours to schedule each day.

1. Capacity curve: share of late orders as a function of picking load (cases per scheduled
   picker-hour), fitted by logistic regression on the three staffing scenarios (train days only).
2. Plan: tomorrow's picker-hours = demand forecast / load at the target late rate, plus a buffer.
Baseline: the fixed crew (same picker-hours every day). Both policies are costed on the test days as
wages + expected late fines (from the fitted curve) – lower is better.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

try:
    from . import common as cm, demand
except ImportError:
    import common as cm
    import demand

TARGET_LATE = 0.02            # plan for ≈ 98 % on time
BUFFER = 0.05                 # extra hours for forecast error and absences


def daily(con, scenarios=("baseline", "lean_staff", "extra_pickers")):
    k = cm.q(con, f"""
        SELECT k.scenario, k.date, k.cases_picked, k.orders, k.on_time,
               (SELECT SUM(hours) FROM fact_labor l
                WHERE l.scenario = k.scenario AND l.date = k.date AND l.role = 'picker') AS picker_hours,
               (SELECT AVG(penalty / 1.0) FROM fact_orders o
                WHERE o.scenario = k.scenario AND date(o.scheduled_departure_ts) = k.date AND o.on_time = 0) AS fine
        FROM fact_daily_kpi k WHERE k.scenario IN ({",".join("'" + s + "'" for s in scenarios)})""")
    k = k[(k["orders"] > 0) & k["picker_hours"].notna()].copy()
    k["load"] = k["cases_picked"] / k["picker_hours"]
    k["late"] = ((1 - k["on_time"]) * k["orders"]).round()
    return k


def capacity_curve(train):
    rows = pd.concat([train.assign(y=1, w=train["late"]), train.assign(y=0, w=train["orders"] - train["late"])])
    rows = rows[rows["w"] > 0]
    lr = LogisticRegression(C=100.0).fit(rows[["load"]], rows["y"], sample_weight=rows["w"])
    a, b = lr.intercept_[0], lr.coef_[0][0]
    target_load = (np.log(TARGET_LATE / (1 - TARGET_LATE)) - a) / b
    return lr, float(target_load)


def run(con, scenario="baseline", plot=True, demand_res=None):
    test_start = cm.split_date(con, scenario)
    k = daily(con)
    lr, target_load = capacity_curve(k[k["date"] < test_start])
    late_rate = lambda load: lr.predict_proba(pd.DataFrame({"load": np.asarray(load, float).ravel()}))[:, 1]

    dres = demand_res or demand.run(con, scenario, plot=False)
    fc = dres["by_day"].set_index("date")
    base = k[(k["scenario"] == scenario)].set_index("date")
    train_ratio = (base.loc[base.index < test_start, "cases_picked"].sum()
                   / dres_ordered_train(con, scenario, test_start))       # picked vs non-rush ordered
    test = base.loc[base.index >= test_start].join(fc, how="inner")
    test["forecast_picked"] = test["pred"] * train_ratio
    wage = cm.C.WAGES["picker"] * np.mean(list(cm.C.SHIFT_PREMIUM.values()))
    fine = float(k.loc[k["date"] < test_start, "fine"].mean())

    fixed_h = test["picker_hours"]
    plan_h = test["forecast_picked"] / target_load * (1 + BUFFER)
    out = {}
    for name, hours in (("fixed", fixed_h), ("plan", plan_h)):
        load = test["cases_picked"] / hours
        exp_late = late_rate(load) * test["orders"]
        out[name] = {"hours_per_day": float(hours.mean()), "wages_per_day": float((hours * wage).mean()),
                     "expected_late_orders_per_day": float(exp_late.mean()),
                     "expected_fines_per_day": float((exp_late * fine).mean()),
                     "days_over_capacity": int((load > target_load * 1.10).sum())}
        out[name]["total_cost_per_day"] = out[name]["wages_per_day"] + out[name]["expected_fines_per_day"]
    res = {
        "model": "logistic capacity curve + demand forecast", "baseline": "fixed crew",
        "test_days": len(test), "target_load_cases_per_picker_hour": target_load,
        "late_rate_at_baseline_load": float(late_rate([k.loc[k.scenario == scenario, "load"].mean()])[0]),
        "fixed": out["fixed"], "plan": out["plan"],
        "value_per_day": out["fixed"]["total_cost_per_day"] - out["plan"]["total_cost_per_day"],
        "plan_vs_fixed_hours": test.assign(plan=plan_h, fixed=fixed_h)[["plan", "fixed", "cases_picked"]].reset_index(),
    }
    if plot:
        fig, ax, path = cm.figure("labour_plan.png")
        x = pd.to_datetime(test.index)
        ax.step(x, fixed_h, where="mid", color=cm.BASE_COLOR, linestyle="--", linewidth=1.5, label="fixed crew")
        ax.step(x, plan_h, where="mid", color=cm.MODEL_COLOR, label="forecast-driven plan")
        ax.set_ylabel("picker-hours per day")
        cm.date_axis(ax)
        ax.legend(loc="upper left", ncol=2, fontsize=9)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        res["figure"] = path
        fig, ax, path = cm.figure("labour_capacity_curve.png")
        loads = np.linspace(40, 120, 200)
        ax.scatter(k["load"], 1 - k["on_time"], s=10, color=cm.ACTUAL_COLOR, alpha=0.35, label="days (3 staffing scenarios)")
        ax.plot(loads, late_rate(loads), color=cm.MODEL_COLOR, label="fitted late-order rate")
        ax.axvline(target_load, color=cm.BASE_COLOR, linestyle="--", linewidth=1.5, label=f"plan load {target_load:.0f}")
        ax.set_xlabel("cases per scheduled picker-hour")
        ax.set_ylabel("share of orders late")
        ax.legend(loc="upper left", fontsize=9)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        res["figure_curve"] = path
    return res


def dres_ordered_train(con, scenario, test_start):
    return float(cm.q(con, """
        SELECT SUM(l.cases_ordered) c FROM fact_order_lines l
        JOIN fact_orders o ON o.scenario = l.scenario AND o.order_id = l.order_id
        WHERE l.scenario = :s AND o.rush = 0 AND date(o.scheduled_departure_ts) < :d""", s=scenario, d=test_start)["c"][0])


if __name__ == "__main__":
    r = run(cm.connect())
    for key, v in r.items():
        if not isinstance(v, pd.DataFrame):
            print(key, v)
