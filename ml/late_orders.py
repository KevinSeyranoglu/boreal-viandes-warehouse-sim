"""Model 4 – late-order risk: at wave release (4 h before departure), which orders will leave late?

Features known at release: the order (cases, lines, rush, departure hour, stop on the route, store kind),
the workload released for the same departure window, and the pickers actually clocked in at that moment
(so sick calls and injuries count). Pooled over every scenario, split by time in each.
Baseline: flag the largest orders (same number of flags) – the supervisor's rule of thumb.
Action valued: a flagged order gets one hour of overtime picking (OT_COST); assumed to save SAVE_RATE of the
flagged orders that would have been late, i.e. their OTIF fine (assumptions, stated in the model card).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

try:
    from . import common as cm
except ImportError:
    import common as cm

SCENARIOS = ("baseline", "lean_staff", "extra_pickers", "chaos", "summer_bbq")
OT_COST = 40.0                  # one overtime picker-hour (wage x 1.5)
SAVE_RATE = 0.5
FEATURES = ["cases_ordered", "lines", "rush", "dep_hour", "stop", "kind", "weekday", "xmas", "bbq",
            "window_cases", "window_orders", "pickers_in", "load_ratio"]
CATEGORICAL = ["kind"]


def load(con, scenario):
    o = cm.q(con, """
        SELECT o.order_id, o.store_id, o.cases_ordered, o.lines, o.rush, o.on_time, o.penalty,
               o.cutoff_ts, o.scheduled_departure_ts, s.kind, s.stop, d.weekday, d.season
        FROM fact_orders o JOIN dim_store s USING (store_id)
        JOIN dim_date d ON d.date = date(o.scheduled_departure_ts)
        WHERE o.scenario = :s""", s=scenario)
    o["dep"] = pd.to_datetime(o["scheduled_departure_ts"])
    o["cut"] = pd.to_datetime(o["cutoff_ts"])
    o["dep_hour"] = o["dep"].dt.hour
    o["xmas"] = (o["season"] == "xmas").astype(int)
    o["bbq"] = (o["season"] == "bbq").astype(int)
    # workload released for departures within ±2 h of this one (all known at release)
    o = o.sort_values("dep").reset_index(drop=True)
    t = o["dep"].values.astype("datetime64[s]").astype(np.int64)
    cs = np.concatenate([[0], np.cumsum(o["cases_ordered"].values)])
    lo = np.searchsorted(t, t - 7200, "left")
    hi = np.searchsorted(t, t + 7200, "right")
    o["window_cases"] = cs[hi] - cs[lo]
    o["window_orders"] = hi - lo
    # pickers clocked in at release time
    lab = cm.q(con, """SELECT start_ts, end_ts FROM fact_labor WHERE scenario = :s AND role = 'picker'""", s=scenario)
    st = np.sort(pd.to_datetime(lab["start_ts"]).values.astype("datetime64[s]").astype(np.int64))
    en = np.sort(pd.to_datetime(lab["end_ts"]).values.astype("datetime64[s]").astype(np.int64))
    c = o["cut"].values.astype("datetime64[s]").astype(np.int64)
    o["pickers_in"] = np.searchsorted(st, c, "right") - np.searchsorted(en, c, "right")
    o["load_ratio"] = o["window_cases"] / np.maximum(o["pickers_in"], 1)
    o["late"] = 1 - o["on_time"]
    o["date"] = o["dep"].dt.strftime("%Y-%m-%d")
    return o


def run(con, plot=True):
    have = set(cm.q(con, "SELECT DISTINCT scenario FROM fact_daily_kpi")["scenario"])
    parts = []
    for s in [x for x in SCENARIOS if x in have]:
        d = load(con, s)
        d["scenario"] = s
        d["is_test"] = d["date"] >= cm.split_date(con, s)
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df["kind"] = pd.Categorical(df["kind"])
    train, test = df[~df["is_test"]].copy(), df[df["is_test"]].copy()
    if train["late"].sum() < 10 or test["late"].sum() < 5:
        return {"skipped": "too few positive cases in this run (generate more days)"}
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, categorical_features="from_dtype",
                                           random_state=cm.SEED)
    model.fit(train[FEATURES], train["late"])
    train["score"] = model.predict_proba(train[FEATURES])[:, 1]
    test["score"] = model.predict_proba(test[FEATURES])[:, 1]
    fine = float(train.loc[train["late"] == 1, "penalty"].mean())

    def net(d, flag):          # fines avoided on flagged late orders minus overtime on every flag
        return float((flag * (d["late"] * SAVE_RATE * fine - OT_COST)).sum())
    cands = np.unique(np.quantile(train["score"], np.linspace(0.5, 0.9999, 300)))
    t_best = max(cands, key=lambda t: net(train, train["score"] >= t))
    test["flag"] = (test["score"] >= t_best).astype(int)
    k = int(test["flag"].sum())
    test["rule"] = 0
    if k:
        test.loc[test["cases_ordered"].nlargest(k).index, "rule"] = 1
    days = test.groupby("scenario")["date"].nunique().sum()
    res = {
        "model": "HistGradientBoosting classifier", "baseline": "flag the largest orders (same count)",
        "train_orders": len(train), "test_orders": len(test),
        "late_rate_test": float(test["late"].mean()),
        "roc_auc": float(roc_auc_score(test["late"], test["score"])),
        "pr_auc": float(average_precision_score(test["late"], test["score"])),
        "pr_auc_rule": float(average_precision_score(test["late"], test["cases_ordered"])),
        "threshold": float(t_best), "flags": k,
        "precision_model": float(test.loc[test.flag == 1, "late"].mean()) if k else 0.0,
        "precision_rule": float(test.loc[test.rule == 1, "late"].mean()) if k else 0.0,
        "recall_model": float(test.loc[test.late == 1, "flag"].mean()),
        "recall_rule": float(test.loc[test.late == 1, "rule"].mean()),
        "avg_fine": fine,
        "net_per_day_model": net(test, test["flag"]) / days,
        "net_per_day_rule": net(test, test["rule"]) / days,
    }
    res["value_per_day"] = res["net_per_day_model"] - res["net_per_day_rule"]
    imp = pd.Series(dict(zip(FEATURES, permutation_importance(model, test))), name="importance")
    res["importance"] = imp.sort_values(ascending=False)
    if plot:
        fig, ax, path = cm.figure("late_orders_importance.png")
        top = res["importance"].head(8)[::-1]
        ax.barh(top.index, top.values, color=cm.MODEL_COLOR, height=0.6)
        ax.set_xlabel("drop in PR-AUC when the feature is shuffled")
        ax.grid(axis="y", visible=False)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        res["figure"] = path
    return res


def permutation_importance(model, test, repeats=3):
    rng = np.random.default_rng(cm.SEED)
    base = average_precision_score(test["late"], model.predict_proba(test[FEATURES])[:, 1])
    out = []
    for f in FEATURES:
        drops = []
        for _ in range(repeats):
            x = test[FEATURES].copy()
            x[f] = rng.permutation(x[f].values)
            drops.append(base - average_precision_score(test["late"], model.predict_proba(x)[:, 1]))
        out.append(float(np.mean(drops)))
    return out


if __name__ == "__main__":
    r = run(cm.connect())
    for key, v in r.items():
        print(key, v if not isinstance(v, float) else round(v, 4))
