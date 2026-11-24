"""Closed-loop test of the labour model: run the warehouse with its crew plan and measure what happens.

    python ml/closed_loop.py            # needs the multi-seed data (analytics/multiseed.py run, build)

For each seed the labour model is trained exactly as in train_all (first 2/3 of the baseline run) and
plans picker-hours for the last 60 days. The same seed is then simulated again, with each day's picker
shifts scaled to the plan, and those 60 days are compared with the baseline run: real wages, on-time,
fines and profit instead of the curve's expectation. Demand in the new run is a fresh draw of the same
process, so the plan meets its forecast error as it would in a real building.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import common as cm  # noqa: E402
import labour  # noqa: E402
import labour_shift  # noqa: E402
import multiseed as ms  # noqa: E402

C = cm.C
OUT = os.path.join(ROOT, "docs", "CLOSED_LOOP.md")


BUFFERS = (0.05, 0.10, 0.15, 0.20)    # labour.BUFFER (0.05) is the published plan; larger = more hours
_PLAN_LOCK = threading.Lock()         # labour.BUFFER is a module setting: one plan at a time


# labour.py (one figure a day), labour_shift.py (one per shift), or the same shift curves without a
# forecast: one rebalanced crew per shift, every day ("static", the no-ML comparison)
POLICIES = ("daily", "shift", "static")


def plan_for(seed, policy, buffer):
    """{date: {shift: pickers}} from the labour model trained on this seed's baseline run."""
    with _PLAN_LOCK:
        con = cm.connect(os.path.join(ms.SEED_DIR, f"warehouse_seed{seed}.db"))
        if policy in ("shift", "static"):
            res = labour_shift.run(con, buffer=buffer)
            con.close()
            return res["plan" if policy == "shift" else "static_plan"], {"value_per_day": float("nan")}
        labour.BUFFER = buffer
        res = labour.run(con, plot=False)
        con.close()
    days = res["plan_vs_fixed_hours"]
    plan = {}
    for _, r in days.iterrows():
        ratio = r["plan"] / r["fixed"]
        plan[r["date"]] = {sh: max(1, round(roles["picker"] * ratio)) for sh, roles in C.HEADCOUNT.items()}
    return plan, res


def simulate(seed, plan, policy, buffer):
    out = os.path.join(ms.SEED_DIR, f"closedloop_{policy}_b{round(buffer * 100):02d}_seed{seed}")
    path = out + "_plan.json"
    text = json.dumps(plan, indent=1)
    if ms.complete(out) and os.path.exists(path) and open(path, encoding="utf-8").read() == text:
        return out                                    # same plan already simulated
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--headless", "--days", str(ms.DAYS),
                    "--seed", str(seed), "--picker-plan", path, "--out", out],
                   cwd=ROOT, check=True, capture_output=True)
    return out


def measure(run, dates):
    k = pd.read_csv(os.path.join(run, "fact_daily_kpi.csv"))
    k = k[k["date"].isin(dates)]
    lab = pd.read_csv(os.path.join(run, "fact_labor.csv"))
    hours = lab[(lab["role"] == "picker") & lab["date"].isin(dates)]["hours"].sum() / len(dates)
    return {"picker_hours_per_day": hours, "wages_per_day": k["wages"].mean(),
            "on_time_pct": 100 * (k["on_time"].fillna(0) * k["orders"]).sum() / k["orders"].sum(),
            "fines_expedites_per_day": (k["penalties"] + k["expedite_cost"]).mean(),
            "profit_per_day": k["profit"].mean()}


def one(job):
    seed, policy, buffer = job
    plan, res = plan_for(seed, policy, buffer)
    run = simulate(seed, plan, policy, buffer)
    dates = sorted(plan)
    base, loop = measure(ms.run_dir("baseline", seed), dates), measure(run, dates)
    row = {"seed": seed, "policy": policy, "buffer": buffer, "days": len(dates),
           "promised_saving_per_day": res["value_per_day"]}
    for k in base:
        row[f"base_{k}"], row[f"loop_{k}"] = base[k], loop[k]
    print(f"{policy} plan, buffer {buffer:.0%}, seed {seed}: on-time {base['on_time_pct']:.1f} -> {loop['on_time_pct']:.1f} %, "
          f"wages {base['wages_per_day']:,.0f} -> {loop['wages_per_day']:,.0f} $/day", flush=True)
    return row


METRICS = [("picker_hours_per_day", "Picker-hours / day", "{:,.0f} h", False),
           ("wages_per_day", "Wages / day", "${:,.0f}", False),
           ("fines_expedites_per_day", "Late fines and expedites / day", "${:,.0f}", False),
           ("on_time_pct", "On-time", "{:.1f} %", True),
           ("profit_per_day", "Profit / day", "${:,.0f}", True)]


def paired_table(df):
    n = len(df)
    L = ["| Test days, per day | Fixed crew (baseline) | Plan (simulated) | Difference | 95 % interval | Plan better in |",
         "|---|---|---|---|---|---|"]
    for key, label, spec, higher in METRICS:
        d = df[f"loop_{key}"] - df[f"base_{key}"]
        m, _, h = ms.ci(d)
        better = int(((d > 0) if higher else (d < 0)).sum())
        b = "" if m - h <= 0 <= m + h else "**"
        L.append(f"| {label} | {ms.fmt(spec, df[f'base_{key}'].mean())} | {ms.fmt(spec, df[f'loop_{key}'].mean())} | "
                 f"{b}{ms.signed(spec, m)}{b} | {ms.signed(spec, m - h)} to {ms.signed(spec, m + h)} | {better} of {n} |")
    return L


def staffing_cost(df):
    """Wages plus fines and expedites: the two cost lines staffing drives (profit also carries the
    spoilage and revenue noise of a different run)."""
    return (df["loop_wages_per_day"] - df["base_wages_per_day"]
            + df["loop_fines_expedites_per_day"] - df["base_fines_expedites_per_day"])


def report(all_df, path=OUT):
    daily = all_df[(all_df["policy"] == "daily") & (all_df["buffer"] == BUFFERS[0])]
    shift = all_df[(all_df["policy"] == "shift") & (all_df["buffer"] == BUFFERS[0])]
    n = len(daily)
    m, sd, _ = ms.ci(daily["promised_saving_per_day"])
    L = ["# Closed-loop test of the labour model", "",
         "Generated by `python ml/closed_loop.py`: never edit the numbers by hand. For each seed the model is "
         "trained on the first 2/3 of the baseline run and plans pickers for the last "
         f"{int(daily['days'].iloc[0])} days. The warehouse is then simulated again with that plan (picker shifts set "
         "by it, every other role unchanged) and the same days are compared with the baseline run of the same "
         f"seed. {n} seeds; the interval is the 95 % t interval of the paired difference.", "",
         "## Daily plan (`labour.py`)", "",
         "One figure of picker-hours a day, every shift scaled alike.", ""]
    L += paired_table(daily)
    L += ["", f"The model promised a saving of **{ms.fmt('${:,.0f}', m)} ± {ms.fmt('${:,.0f}', sd).lstrip('$')} a day** "
          "(wages saved minus the late fines its capacity curve expects). Simulated, wages plus fines changed by "
          f"**{ms.signed('${:,.0f}', staffing_cost(daily).mean())} a day**.", "",
          "## Per-shift plan (`labour_shift.py`)", "",
          "Each shift planned from its own forecast volume and capacity curve; a shift that picks little "
          f"(the evening: waves are released for departures 03:00–18:00) keeps {labour_shift.MIN_CREW} pickers for rush orders.", ""]
    L += paired_table(shift)
    mc, _, hc = ms.ci(staffing_cost(shift))
    L += ["", f"Wages plus fines changed by **{ms.signed('${:,.0f}', mc)} a day** "
          f"({ms.signed('${:,.0f}', mc - hc)} to {ms.signed('${:,.0f}', mc + hc)}).", "",
          "## Does the forecast add value?", "",
          "Most of the gain comes from one finding a shift report would also show: the evening shift had 18 "
          "pickers for about 5 % of the picking. The no-ML comparison keeps the same shift curves but uses "
          "one rebalanced crew per shift every day, sized from the training average (no forecast).", ""]
    static = all_df[(all_df["policy"] == "static") & (all_df["buffer"] == BUFFERS[0])]
    L += paired_table(static)
    pair = shift.set_index("seed")
    st = static.set_index("seed")
    gain = (staffing_cost(st) - staffing_cost(pair)).dropna()
    mg, _, hg = ms.ci(gain)
    ot = (pair["loop_on_time_pct"] - st["loop_on_time_pct"]).dropna()
    mo, _, ho = ms.ci(ot)
    L += ["", f"Same picker-hours, but the forecast puts them on the days that need them: the per-shift plan "
          f"saves **{ms.fmt('${:,.0f}', mg)} a day more** than the static crew ({ms.signed('${:,.0f}', mg - hg)} to "
          f"{ms.signed('${:,.0f}', mg + hg)}) and keeps **{ms.signed('{:.1f} %', mo)}** more orders on time "
          f"({ms.signed('{:.1f} %', mo - ho)} to {ms.signed('{:.1f} %', mo + ho)}), paired by seed.", "",
          "## Safety buffer", "",
          "Each plan with more pickers on top of the forecast. Paired differences vs the fixed crew, "
          f"mean over {n} seeds (95 % interval for wages + fines and on-time).", "",
          "| Plan | Buffer | Picker-hours / day | Wages | Fines and expedites | Wages + fines | On-time | Profit |",
          "|---|---|---|---|---|---|---|---|"]
    for (pol, buf), g in all_df.groupby(["policy", "buffer"]):
        d = {k: g[f"loop_{k}"] - g[f"base_{k}"] for k, *_ in METRICS}
        mn, _, hn = ms.ci(staffing_cost(g))
        mo, _, ho = ms.ci(d["on_time_pct"])
        L.append(f"| {pol} | {buf:.0%} | {g['loop_picker_hours_per_day'].mean():,.0f} | {ms.signed('${:,.0f}', d['wages_per_day'].mean())} | "
                 f"{ms.signed('${:,.0f}', d['fines_expedites_per_day'].mean())} | {ms.signed('${:,.0f}', mn)} "
                 f"({ms.signed('${:,.0f}', mn - hn)} to {ms.signed('${:,.0f}', mn + hn)}) | "
                 f"{ms.signed('{:.1f} %', mo)} ({ms.signed('{:.1f} %', mo - ho)} to {ms.signed('{:.1f} %', mo + ho)}) | "
                 f"{ms.signed('${:,.0f}', d['profit_per_day'].mean())} |")
    L += ["", "## Per seed (5 % buffer)", "",
          "| Seed | Plan | Picker-hours / day (fixed crew) | On-time (fixed → plan) | Wages + fines change | Profit change |",
          "|---|---|---|---|---|---|"]
    for _, r in pd.concat([daily, shift]).sort_values(["seed", "policy"]).iterrows():
        cost = r.loop_wages_per_day - r.base_wages_per_day + r.loop_fines_expedites_per_day - r.base_fines_expedites_per_day
        L.append(f"| {int(r.seed)} | {r.policy} | {r.loop_picker_hours_per_day:,.0f} ({r.base_picker_hours_per_day:,.0f}) | "
                 f"{r.base_on_time_pct:.1f} % → {r.loop_on_time_pct:.1f} % | {ms.signed('${:,.0f}', cost)} | "
                 f"{ms.signed('${:,.0f}', r.loop_profit_per_day - r.base_profit_per_day)} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {path}")


def main():
    jobs = [(seed, p, b) for p in POLICIES for b in BUFFERS for seed in ms.SEEDS
            if p != "static" or b == BUFFERS[0]]
    with ThreadPoolExecutor(len(jobs)) as pool:
        df = pd.DataFrame(list(pool.map(one, jobs)))
    df.to_csv(os.path.join(ms.SEED_DIR, "closed_loop.csv"), index=False)
    report(df)


if __name__ == "__main__":
    main()
