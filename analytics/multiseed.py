"""Run every scenario with several random seeds and report each KPI as mean ± sd.

    python analytics/multiseed.py run --jobs 10   # headless runs -> data/seeds/<scenario>_seed<seed>/
    python analytics/multiseed.py build           # data/seeds/multiseed.duckdb + one SQLite per seed for the ML
    python analytics/multiseed.py ml              # the 5 models on each seed -> data/seeds/ml_seed<seed>/
    python analytics/multiseed.py report          # docs/MULTISEED.md + data/seeds/multiseed_*.csv

Seed 42 is the published run already in data/, so it is reused. One run is one draw: with a single
seed, baseline vs extra_pickers flipped between regenerations. Scenario differences are paired (same
seed in both scenarios, so the weather, plant delays and order noise they share cancel out), with a
95 % t interval over the seeds. The KPIs use the same definitions as analytics/sql/08_scenario_comparison.sql.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analytics"))

import config as C  # noqa: E402

SEEDS = (42, 7, 11, 23, 99)
DAYS = 180
DATA = os.path.join(ROOT, C.DATA_DIR)
SEED_DIR = os.path.join(DATA, "seeds")
DUCKDB = os.path.join(SEED_DIR, "multiseed.duckdb")
REPORT = os.path.join(ROOT, "docs", "MULTISEED.md")

# per run (scenario, seed): same definitions as sql/08_scenario_comparison.sql
KPI_SQL = """
SELECT k.scenario, k.seed,
       100 * AVG(k.on_time)                   AS on_time_pct,
       100 * AVG(k.fill_rate)                 AS fill_rate_pct,
       AVG(k.wages)                           AS wages_per_day,
       AVG(k.penalties + k.expedite_cost)     AS service_failure_per_day,
       AVG(k.spoilage)                        AS spoilage_per_day,
       AVG(k.revenue)                         AS revenue_per_day,
       AVG(k.profit)                          AS profit_per_day,
       100 * AVG(k.compliance)                AS compliance_pct
FROM fact_daily_kpi k
GROUP BY ALL
"""
OTIF_SQL = """
SELECT scenario, seed, 100 * AVG(CASE WHEN on_time = 1 AND fill_rate >= 0.999 THEN 1.0 ELSE 0 END) AS otif_pct
FROM fact_orders GROUP BY ALL
"""
# label, format, higher is better
KPIS = {
    "on_time_pct": ("On-time", "{:.1f} %", True),
    "otif_pct": ("OTIF", "{:.1f} %", True),
    "fill_rate_pct": ("Fill rate", "{:.2f} %", True),
    "wages_per_day": ("Wages / day", "${:,.0f}", False),
    "service_failure_per_day": ("Late fines and expedites / day", "${:,.0f}", False),
    "spoilage_per_day": ("Spoilage / day", "${:,.0f}", False),
    "profit_per_day": ("Profit / day", "${:,.0f}", True),
}
# ML headline metrics: (model, key, label, format)
ML = [
    ("demand", "wape_store_sku", "Demand WAPE, store × SKU (model)", "{:.1%}"),
    ("demand", "wape_store_sku_baseline", "Demand WAPE, store × SKU (same weekday last week)", "{:.1%}"),
    ("demand", "value_per_day", "Demand: value of fewer short cases / day", "${:,.0f}"),
    ("labour", "value_per_day", "Labour plan: saving vs fixed crew / day", "${:,.0f}"),
    ("late_orders", "pr_auc", "Late orders PR-AUC (model)", "{:.2f}"),
    ("late_orders", "pr_auc_rule", "Late orders PR-AUC (largest orders)", "{:.2f}"),
    ("late_orders", "late_rate_test", "Late orders: late rate in test period", "{:.1%}"),
    ("late_orders", "net_per_day_model", "Late orders: net value / day", "${:,.0f}"),
    ("late_orders", "value_per_day", "Late orders: value vs largest-orders rule / day", "${:,.0f}"),
    ("spoilage", "net_per_day_model", "Spoilage: net / day (model)", "${:,.0f}"),
    ("spoilage", "net_per_day_rule", "Spoilage: net / day (rule days left < 3)", "${:,.0f}"),
    ("temperature", "lead_min_model", "Cold room warning lead, min (model)", "{:.0f}"),
    ("temperature", "lead_min_rule", "Cold room warning lead, min (pre-alarm)", "{:.0f}"),
]


def run_dir(scenario, seed):
    """Seed 42 is the published run in data/; the other seeds live in data/seeds/."""
    base = DATA if seed == C.RANDOM_SEED else SEED_DIR
    return os.path.join(base, f"{scenario}_seed{seed}")


def all_runs():
    return [run_dir(s, seed) for seed in SEEDS for s in C.SCENARIOS]


def complete(run):
    """A crashed run leaves partial CSVs behind: done means one KPI row per simulated day."""
    path = os.path.join(run, "fact_daily_kpi.csv")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh) - 1 >= DAYS


def cmd_run(args):
    todo = [(s, seed) for seed in SEEDS for s in C.SCENARIOS if args.force or not complete(run_dir(s, seed))]
    os.makedirs(os.path.join(SEED_DIR, "logs"), exist_ok=True)
    print(f"{len(todo)} runs to do, {args.jobs} at a time", flush=True)

    def one(job):
        s, seed = job
        t0 = time.time()
        log = os.path.join(SEED_DIR, "logs", f"{s}_seed{seed}.log")
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.call([sys.executable, os.path.join(ROOT, "main.py"), "--headless", "--days", str(DAYS),
                                  "--seed", str(seed), "--scenario", s, "--out", run_dir(s, seed)],
                                 cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
        status = "ok" if rc == 0 else f"FAILED ({rc}), see {log}"
        print(f"{s} seed {seed}: {status} in {(time.time() - t0) / 60:.1f} min", flush=True)
        return rc

    with ThreadPoolExecutor(args.jobs) as pool:
        failed = sum(rc != 0 for rc in pool.map(one, todo))
    if failed:
        raise SystemExit(f"{failed} runs failed")


def cmd_build(args):
    import build_db
    import build_duckdb
    build_duckdb.build(all_runs(), DUCKDB, None)
    for seed in SEEDS:
        build_db.build([run_dir(s, seed) for s in C.SCENARIOS], os.path.join(SEED_DIR, f"warehouse_seed{seed}.db"))


def cmd_ml(args):
    sys.path.insert(0, os.path.join(ROOT, "ml"))
    import train_all
    for seed in SEEDS:
        print(f"--- seed {seed}", flush=True)
        train_all.run_all(db=os.path.join(SEED_DIR, f"warehouse_seed{seed}.db"),
                          out_dir=os.path.join(SEED_DIR, f"ml_seed{seed}"), plot=False)


def run_kpis(db=DUCKDB):
    import duckdb
    con = duckdb.connect(db, read_only=True)
    kpi = con.execute(KPI_SQL).df().merge(con.execute(OTIF_SQL).df(), on=["scenario", "seed"])
    con.close()
    return kpi.sort_values(["scenario", "seed"]).reset_index(drop=True)


def ci(values):
    """mean, sd and half-width of the 95 % t interval."""
    v = pd.Series(values, dtype=float).dropna()
    n = len(v)
    if n < 2:
        return float(v.mean()) if n else float("nan"), float("nan"), float("nan")
    sd = float(v.std(ddof=1))
    return float(v.mean()), sd, float(stats.t.ppf(0.975, n - 1)) * sd / n ** 0.5


def summarise(kpi):
    """Mean ± sd per scenario, and the paired difference to the baseline."""
    rows, diffs = [], []
    base = kpi[kpi.scenario == "baseline"].set_index("seed")
    for s, g in kpi.groupby("scenario"):
        g = g.set_index("seed")
        for col in KPIS:
            m, sd, _ = ci(g[col])
            rows.append({"scenario": s, "kpi": col, "mean": m, "sd": sd, "min": g[col].min(), "max": g[col].max(),
                         "seeds": len(g)})
            if s != "baseline" and not base.empty:
                d = (g[col] - base[col]).dropna()
                m, sd, h = ci(d)
                better = (d > 0) if KPIS[col][2] else (d < 0)
                diffs.append({"scenario": s, "kpi": col, "diff": m, "sd": sd, "ci_low": m - h, "ci_high": m + h,
                              "seeds_better": int(better.sum()), "seeds": len(d)})
    return pd.DataFrame(rows), pd.DataFrame(diffs)


def ml_table():
    rows = []
    for seed in SEEDS:
        path = os.path.join(SEED_DIR, f"ml_seed{seed}", "metrics.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            m = json.load(fh)
        for model, key, _, _ in ML:
            rows.append({"seed": seed, "model": model, "metric": key, "value": m.get(model, {}).get(key)})
    return pd.DataFrame(rows)


def fmt(spec, v):
    if v is None or pd.isna(v):
        return "–"
    return ("−" if v < 0 else "") + spec.format(abs(v))


def signed(spec, v):
    """A difference: explicit sign, and percentage points rather than percent."""
    return ("+" if v >= 0 else "") + fmt(spec, v).replace(" %", " pts")


def write_report(kpi, summ, diff, ml, path=REPORT):
    seeds = sorted(kpi.seed.unique())
    order = [s for s in C.SCENARIOS if s in set(kpi.scenario)]
    L = ["# Multi-seed results", "",
         f"Generated by `python analytics/multiseed.py report`: never edit the numbers by hand. "
         f"Every scenario was run for {DAYS} simulated days with seeds {', '.join(map(str, seeds))}. "
         "Values are the mean over the seeds ± one standard deviation (the spread between runs).", "",
         "## Scenarios", "",
         "| Scenario | " + " | ".join(KPIS[c][0] for c in KPIS) + " |",
         "|---|" + "---|" * len(KPIS)]
    for s in order:
        cells = []
        for col, (_, spec, _) in KPIS.items():
            r = summ[(summ.scenario == s) & (summ.kpi == col)].iloc[0]
            cells.append(f"{fmt(spec, r['mean'])} ± {fmt(spec, r['sd']).lstrip('$').replace(' %', ' pts')}")
        L.append(f"| `{s}` | " + " | ".join(cells) + " |")
    L += ["", "## Difference to the baseline (paired by seed)", "",
          "Each scenario minus the baseline run with the same seed. The interval is the 95 % t interval of the "
          f"mean difference over {len(seeds)} seeds; when it excludes 0 the effect is larger than the run-to-run noise. "
          "\"Better in\" counts the seeds where the scenario beats the baseline on that KPI.", "",
          "| Scenario | KPI | Mean difference | 95 % interval | Better in |", "|---|---|---|---|---|"]
    for s in (x for x in order if x != "baseline" and x in set(diff.get("scenario", []))):
        for col, (label, spec, _) in KPIS.items():
            r = diff[(diff.scenario == s) & (diff.kpi == col)].iloc[0]
            b = "" if r.ci_low <= 0 <= r.ci_high else "**"
            L.append(f"| `{s}` | {label} | {b}{signed(spec, r['diff'])}{b} | "
                     f"{signed(spec, r.ci_low)} to {signed(spec, r.ci_high)} | {r.seeds_better} of {r.seeds} |")
    L += ["", "Bold: the interval excludes 0."]
    other_season = [s for s in order if "START_DATE" in C.SCENARIOS.get(s, {})]
    if other_season:
        L += ["", "Not like for like: " + ", ".join(f"`{s}`" for s in other_season) + " starts on another date, "
              "so it does not share the baseline's season or weather even with the same seed. Its difference "
              "mixes the season effect with run-to-run noise; read it as a comparison of seasons, not a paired test."]
    L += [""]
    L += ["## Per run", "", "| Scenario | Seed | On-time | OTIF | Profit / day |", "|---|---|---|---|---|"]
    for _, r in kpi.set_index("scenario").loc[order].reset_index().iterrows():
        L.append(f"| `{r.scenario}` | {r.seed} | {r.on_time_pct:.1f} % | {r.otif_pct:.1f} % | ${r.profit_per_day:,.0f} |")
    if not ml.empty:
        L += ["", "## Machine learning, per seed", "",
              "Each seed's 5 scenarios were loaded into their own database and the 5 models retrained "
              "(same time split: first 2/3 of the days train, the last 1/3 test).", "",
              "| Metric | " + " | ".join(f"Seed {s}" for s in sorted(ml.seed.unique())) + " | Mean ± sd |",
              "|---|" + "---|" * (ml.seed.nunique() + 1)]
        for model, key, label, spec in ML:
            v = ml[(ml.model == model) & (ml.metric == key)].sort_values("seed")
            m, sd, _ = ci(v["value"])
            L.append(f"| {label} | " + " | ".join(fmt(spec, x) for x in v["value"]) +
                     f" | {fmt(spec, m)} ± {fmt(spec, sd).lstrip('$')} |")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {path}")


def cmd_report(args):
    kpi = run_kpis()
    summ, diff = summarise(kpi)
    ml = ml_table()
    for name, df in {"runs": kpi, "summary": summ, "vs_baseline": diff, "ml": ml}.items():
        df.to_csv(os.path.join(SEED_DIR, f"multiseed_{name}.csv"), index=False)
    write_report(kpi, summ, diff, ml)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="headless runs for every scenario and seed")
    r.add_argument("--jobs", type=int, default=5)
    r.add_argument("--force", action="store_true", help="redo runs that already exist")
    for name in ("build", "ml", "report"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    {"run": cmd_run, "build": cmd_build, "ml": cmd_ml, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
