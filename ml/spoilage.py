"""Model 3 – spoilage risk: will this pallet expire in the building before it ships?

Scored at receipt, from what the receiver knows: the label (days of shelf life left), the product,
the plant, the probe temperature, and how much stock of that SKU is already on hand versus recent
shipments (days of cover, and the selling slack left once that stock is gone). The simulation's hidden "aged load" flag is NOT a feature.
Baseline: the receiver's rule "flag if fewer than N days are left" (N tuned on the training period).
Action valued: flagged pallets are allocated first or sold through a discount channel, recovering
RECOVERY of their value instead of losing it all (assumption, stated in the model card).
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

RECOVERY = 0.5
FEATURES = ["sku_code", "plant_code", "category", "days_left", "frac_left", "shelf_life_days", "cases",
            "arrival_temp_c", "days_of_cover", "slack_days", "weekday"]
CATEGORICAL = ["sku_code", "plant_code", "category"]


def load(con, scenario="baseline"):
    r = cm.q(con, """
        SELECT r.pallet_id, r.sku_code, r.plant_code, r.cases, r.arrival_temp_c, r.best_before,
               date(r.received_ts) AS date, k.shelf_life_days, k.category, k.value_per_case,
               CASE WHEN s.pallet_id IS NULL THEN 0 ELSE 1 END AS spoiled, d.weekday
        FROM fact_pallet_receipts r
        JOIN dim_sku k USING (sku_code)
        JOIN dim_date d ON d.date = date(r.received_ts)
        LEFT JOIN fact_spoilage s ON s.scenario = r.scenario AND s.pallet_id = r.pallet_id
        WHERE r.scenario = :s AND r.decision != 'reject'""", s=scenario)
    r["days_left"] = (pd.to_datetime(r["best_before"]) - pd.to_datetime(r["date"])).dt.days
    r["frac_left"] = r["days_left"] / r["shelf_life_days"]
    inv = cm.q(con, "SELECT date, sku_code, cases_on_hand FROM fact_inventory_daily WHERE scenario = :s", s=scenario)
    ship = cm.q(con, """SELECT date(shipped_ts) AS date, sku_code, SUM(cases) AS shipped FROM fact_shipment_lots
                        WHERE scenario = :s GROUP BY 1, 2""", s=scenario)
    ship = ship.sort_values("date")
    ship["ship_7d"] = ship.groupby("sku_code")["shipped"].transform(lambda x: x.shift(1).rolling(7, min_periods=3).mean())
    r = r.merge(inv, on=["date", "sku_code"], how="left").merge(ship[["date", "sku_code", "ship_7d"]],
                                                               on=["date", "sku_code"], how="left")
    r["days_of_cover"] = r["cases_on_hand"] / r["ship_7d"]
    # days of selling time left after the stock ahead of this pallet (and the pallet itself) is sold,
    # before stores stop accepting it (best-before minus their minimum remaining shelf life)
    zone = cm.q(con, "SELECT sku_code, zone FROM dim_sku").set_index("sku_code")["zone"]
    min_left = r["sku_code"].map(zone).map(cm.C.MIN_REMAINING_DAYS)
    r["slack_days"] = r["days_left"] - min_left - (r["cases_on_hand"] + r["cases"]) / r["ship_7d"]
    return r


SCENARIOS = ("baseline", "lean_staff", "extra_pickers", "chaos", "summer_bbq")


def run(con, scenario="baseline", plot=True):
    """Pooled over every scenario run in the database (5x more spoiled pallets), split by time in each."""
    have = set(cm.q(con, "SELECT DISTINCT scenario FROM fact_daily_kpi")["scenario"])
    parts = []
    for s in [x for x in SCENARIOS if x in have]:
        d = load(con, s)
        d["scenario"] = s
        d["is_test"] = d["date"] >= cm.split_date(con, s)
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    for c in CATEGORICAL:
        df[c] = pd.Categorical(df[c])
    train, test = df[~df["is_test"]], df[df["is_test"]].copy()
    if train["spoiled"].sum() < 10 or test["spoiled"].sum() < 5:
        return {"skipped": "too few positive cases in this run (generate more days)"}
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, categorical_features="from_dtype",
                                           random_state=cm.SEED)        # unweighted: scores stay probabilities
    model.fit(train[FEATURES], train["spoiled"])
    test["score"] = model.predict_proba(test[FEATURES])[:, 1]

    # Decision: send a flagged pallet to the discount channel at RECOVERY of its value. A pallet that would
    # have spoiled recovers RECOVERY x value; one that would have sold normally loses (1 - RECOVERY) x value.
    # Rule and model each pick the threshold that maximises this net value on the TRAINING period.
    train = train.copy()
    train["score"] = model.predict_proba(train[FEATURES])[:, 1]
    def net(d, flag):
        v = d["cases"] * d["value_per_case"]
        return float((v * flag * np.where(d["spoiled"] == 1, RECOVERY, -(1 - RECOVERY))).sum())
    best_n = max(range(0, 15), key=lambda n: net(train, train["days_left"] < n))
    cands = np.unique(np.quantile(train["score"], np.linspace(0.95, 0.99999, 300)))
    best_t = max(cands, key=lambda t: net(train, train["score"] >= t))
    # hybrid: keep the rule, and let the model add the pallets the rule misses (threshold tuned on train)
    rest = train["days_left"] >= best_n
    cands = np.unique(np.quantile(train.loc[rest, "score"], np.linspace(0.95, 0.99999, 300)))
    add_t = max(cands, key=lambda t: net(train, (train["days_left"] < best_n) | (train["score"] >= t)))
    if net(train, train["days_left"] < best_n) >= net(train, (train["days_left"] < best_n) | (train["score"] >= add_t)):
        add_t = 2.0                                    # adding model flags never helped on train: add none
    test["rule"] = (test["days_left"] < best_n).astype(int)
    test["model_flag"] = (test["score"] >= best_t).astype(int)
    test["hybrid_flag"] = ((test["days_left"] < best_n) | (test["score"] >= add_t)).astype(int)
    days = test.groupby("scenario")["date"].nunique().sum()        # scenario-days
    value = test["cases"] * test["value_per_case"]
    res = {
        "model": "HistGradientBoosting classifier", "baseline": f"days left < {best_n}",
        "threshold": float(best_t),
        "train_pallets": len(train), "test_pallets": len(test),
        "train_spoiled": int(train["spoiled"].sum()), "test_spoiled": int(test["spoiled"].sum()),
        "roc_auc": float(roc_auc_score(test["spoiled"], test["score"])),
        "pr_auc": float(average_precision_score(test["spoiled"], test["score"])),
        "pr_auc_rule": float(average_precision_score(test["spoiled"], -test["days_left"])),
        "flags_model": int(test["model_flag"].sum()), "flags_rule": int(test["rule"].sum()),
        "precision_model": float(test.loc[test.model_flag == 1, "spoiled"].mean()),
        "precision_rule": float(test.loc[test.rule == 1, "spoiled"].mean()),
        "recall_model": float(test.loc[test.spoiled == 1, "model_flag"].mean()),
        "recall_rule": float(test.loc[test.spoiled == 1, "rule"].mean()),
        "spoiled_value_per_day": float((value * test["spoiled"]).sum() / days),
        "net_per_day_model": net(test, test["model_flag"]) / days,
        "net_per_day_rule": net(test, test["rule"]) / days,
    }
    res["net_per_day_hybrid"] = net(test, test["hybrid_flag"]) / days
    res["flags_hybrid"] = int(test["hybrid_flag"].sum())
    res["recall_hybrid"] = float(test.loc[test.spoiled == 1, "hybrid_flag"].mean())
    res["value_per_day"] = res["net_per_day_model"] - res["net_per_day_rule"]
    res["value_per_day_hybrid"] = res["net_per_day_hybrid"] - res["net_per_day_rule"]
    if plot:
        from sklearn.metrics import precision_recall_curve
        fig, ax, path = cm.figure("spoilage_pr_curve.png")
        p, r_, _ = precision_recall_curve(test["spoiled"], test["score"])
        ax.plot(r_, p, color=cm.MODEL_COLOR, label=f"model (PR-AUC {res['pr_auc']:.2f})")
        p, r_, _ = precision_recall_curve(test["spoiled"], -test["days_left"])
        ax.plot(r_, p, color=cm.BASE_COLOR, linestyle="--", linewidth=1.5, label=f"days-left rule ({res['pr_auc_rule']:.2f})")
        ax.set_xlabel("recall (share of spoiling pallets caught)")
        ax.set_ylabel("precision")
        ax.legend(loc="lower left", fontsize=9)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        res["figure"] = path
    return res



if __name__ == "__main__":
    r = run(cm.connect())
    for key, v in r.items():
        print(key, round(v, 4) if isinstance(v, float) else v)
