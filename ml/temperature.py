"""Model 5 – cold-room early warning: will this room go over its upper spec in the next 30 minutes?

Every 5-minute reading while the room is still in spec. Features: temperature margin to the limit,
its slope over 5/15/30 min, recent door traffic, hour, zone. Pooled over scenarios, split by time.
Baseline: a fixed pre-alarm setpoint ("warn when within d °C of the limit"), d tuned so both raise the
same number of warnings per day on the training period. Compared on breaches warned in time and lead time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score

try:
    from . import common as cm
except ImportError:
    import common as cm

SCENARIOS = ("baseline", "lean_staff", "extra_pickers", "chaos", "summer_bbq")
ZONES = ("freezer", "fresh", "processed")
HORIZON = 6                      # readings (30 min)
FEATURES = ["margin", "slope_5", "slope_15", "slope_30", "door_30", "door_now", "std_30", "hour", "zone_code"]


def load(con, scenario):
    t = cm.q(con, f"""SELECT ts, zone, temp_c, max_c, door_open_s FROM fact_temperature
                      WHERE scenario = :s AND zone IN ({",".join("'" + z + "'" for z in ZONES)}) ORDER BY zone, ts""",
             s=scenario)
    t["zone_code"] = t["zone"].map({z: i for i, z in enumerate(ZONES)})
    g = t.groupby("zone")["temp_c"]
    t["margin"] = t["max_c"] - t["temp_c"]
    t["slope_5"] = g.diff(1)
    t["slope_15"] = g.diff(3)
    t["slope_30"] = g.diff(6)
    t["std_30"] = g.transform(lambda s: s.rolling(6).std())
    t["door_now"] = t["door_open_s"]
    t["door_30"] = t.groupby("zone")["door_open_s"].transform(lambda s: s.rolling(6).sum())
    t["hour"] = pd.to_datetime(t["ts"]).dt.hour
    over = (t["temp_c"] > t["max_c"]).astype(int)
    fut = over.groupby(t["zone"]).transform(lambda s: s[::-1].rolling(HORIZON, min_periods=1).max()[::-1].shift(-1))
    t["breach_soon"] = fut.fillna(0).astype(int)
    t["in_spec"] = over == 0
    # breach onsets (first reading over the limit) and the minutes since the warning, for lead time
    t["onset"] = (over == 1) & (over.groupby(t["zone"]).shift(1) == 0)
    t["date"] = t["ts"].str[:10]
    return t.dropna(subset=["slope_30", "std_30", "door_30"])


def lead_times(d, flag):
    """For each breach onset: was a warning raised in the 30 min before, and how many minutes ahead."""
    leads = []
    for z, g in d.groupby("zone"):
        f = flag.loc[g.index].values
        onsets = np.where(g["onset"].values)[0]
        for i in onsets:
            window = f[max(0, i - HORIZON):i]
            hits = np.where(window)[0]
            leads.append((len(window) - hits[0]) * 5 if len(hits) else 0)
    leads = np.array(leads)
    return float((leads > 0).mean()) if len(leads) else 0.0, float(leads[leads > 0].mean()) if (leads > 0).any() else 0.0, len(leads)


def run(con, plot=True):
    have = set(cm.q(con, "SELECT DISTINCT scenario FROM fact_daily_kpi")["scenario"])
    parts = []
    for s in [x for x in SCENARIOS if x in have]:
        d = load(con, s)
        d["scenario"] = s
        d["is_test"] = d["date"] >= cm.split_date(con, s)
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    train = df[~df["is_test"] & df["in_spec"]]
    if train["breach_soon"].sum() < 10 or df.loc[df["is_test"], "onset"].sum() < 3:
        return {"skipped": "too few positive cases in this run (generate more days)"}
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=cm.SEED)
    model.fit(train[FEATURES], train["breach_soon"])
    df["score"] = model.predict_proba(df[FEATURES])[:, 1]
    df.loc[~df["in_spec"], "score"] = 0.0                     # already in alarm: no early warning needed
    tr, te = df[~df["is_test"]], df[df["is_test"]]
    tr_days = tr.groupby("scenario")["date"].nunique().sum()
    te_days = te.groupby("scenario")["date"].nunique().sum()

    # model threshold: best training PR trade-off at <= WARN_PER_DAY warnings per zone-day
    WARN_PER_DAY = 3.0
    cap = int(WARN_PER_DAY * tr_days * len(ZONES))
    t_model = float(np.sort(tr["score"].values)[::-1][min(cap, len(tr) - 1)])
    # baseline: margin threshold raising the same number of warnings on train
    m_sorted = np.sort(tr.loc[tr["in_spec"], "margin"].values)
    d_rule = float(m_sorted[min(cap, len(m_sorted) - 1)])
    flag_m = (df["score"] > t_model) & df["in_spec"]
    flag_r = (df["margin"] < d_rule) & df["in_spec"]
    caught_m, lead_m, n = lead_times(te, flag_m)
    caught_r, lead_r, _ = lead_times(te, flag_r)
    res = {
        "model": "HistGradientBoosting classifier", "baseline": f"pre-alarm {d_rule:.2f} °C below the limit",
        "test_breaches": n,
        "pr_auc": float(average_precision_score(te.loc[te.in_spec, "breach_soon"], te.loc[te.in_spec, "score"])),
        "pr_auc_rule": float(average_precision_score(te.loc[te.in_spec, "breach_soon"], -te.loc[te.in_spec, "margin"])),
        "warnings_per_day_model": float(flag_m[te.index].sum() / te_days),
        "warnings_per_day_rule": float(flag_r[te.index].sum() / te_days),
        "breaches_warned_model": caught_m, "breaches_warned_rule": caught_r,
        "lead_min_model": lead_m, "lead_min_rule": lead_r,
        "value_per_day": None,
    }
    if plot:
        fig, ax, path = cm.figure("temperature_early_warning.png")
        x = np.arange(2)
        ax.bar(x - 0.18, [caught_r * 100, lead_r], width=0.34, color=cm.BASE_COLOR, label="pre-alarm setpoint")
        ax.bar(x + 0.18, [caught_m * 100, lead_m], width=0.34, color=cm.MODEL_COLOR, label="model")
        ax.set_xticks(x, ["breaches warned in time (%)", "average warning lead (min)"])
        ax.grid(axis="x", visible=False)
        ax.legend(loc="upper right", fontsize=9)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        res["figure"] = path
    return res


if __name__ == "__main__":
    r = run(cm.connect())
    for key, v in r.items():
        print(key, v if not isinstance(v, float) else round(v, 4))
