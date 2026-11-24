"""Model 1 – demand forecast: cases each store will order of each SKU for a departure day.

Decision: how much to order from the plants (and how many pickers to plan) the day before.
Features use only what is known the day before: past orders (lags >= 1 day), calendar, season,
store and product attributes, and the weather forecast (the simulation's actual temperature
stands in for a next-day forecast).
Baseline: "same weekday last week" – what most buyers do by hand.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

try:
    from . import common as cm
except ImportError:
    import common as cm

FEATURES = ["store_id", "sku_code", "kind", "category", "size_index", "weekday", "is_weekend",
            "xmas", "post_xmas", "bbq", "temp_max", "lag_1", "lag_7", "lag_14", "same_wd_mean_4",
            "mean_7", "mean_28", "store_sku_mean_train"]
CATEGORICAL = ["store_id", "sku_code", "kind", "category"]


def load(con, scenario="baseline"):
    ol = cm.q(con, """
        SELECT l.store_id, l.sku_code, date(o.scheduled_departure_ts) AS date, SUM(l.cases_ordered) AS cases
        FROM fact_order_lines l JOIN fact_orders o ON o.scenario = l.scenario AND o.order_id = l.order_id
        WHERE l.scenario = :s AND o.rush = 0 GROUP BY 1, 2, 3""", s=scenario)
    days = cm.q(con, "SELECT date FROM fact_daily_kpi WHERE scenario = :s ORDER BY date", s=scenario)["date"]
    stores = cm.q(con, "SELECT store_id, kind, size_index FROM dim_store")
    skus = cm.q(con, "SELECT sku_code, category FROM dim_sku")
    grid = pd.MultiIndex.from_product([stores.store_id, skus.sku_code, days], names=["store_id", "sku_code", "date"])
    df = ol.set_index(["store_id", "sku_code", "date"]).reindex(grid, fill_value=0).reset_index()
    df = df.merge(stores, on="store_id").merge(skus, on="sku_code")
    weather = cm.q(con, "SELECT date, ambient_max_c AS temp_max FROM fact_weather WHERE scenario = :s", s=scenario)
    cal = cm.q(con, "SELECT date, weekday, is_weekend, season FROM dim_date")
    df = df.merge(weather, on="date", how="left").merge(cal, on="date", how="left")
    d = pd.to_datetime(df["date"])
    df["xmas"] = (df["season"] == "xmas").astype(int)
    df["bbq"] = (df["season"] == "bbq").astype(int)
    df["post_xmas"] = ((d.dt.month == 12) & (d.dt.day >= 26)).astype(int)
    df = df.sort_values(["store_id", "sku_code", "date"]).reset_index(drop=True)
    g = df.groupby(["store_id", "sku_code"])["cases"]
    df["lag_1"] = g.shift(1)
    df["lag_7"] = g.shift(7)
    df["lag_14"] = g.shift(14)
    df["same_wd_mean_4"] = pd.concat([g.shift(7 * i) for i in (1, 2, 3, 4)], axis=1).mean(axis=1)
    df["mean_7"] = g.transform(lambda s: s.shift(1).rolling(7).mean())
    df["mean_28"] = g.transform(lambda s: s.shift(1).rolling(28, min_periods=7).mean())
    return df


def run(con, scenario="baseline", plot=True):
    df = load(con, scenario)
    test_start = cm.split_date(con, scenario)
    df = df[df["lag_14"].notna() & df["mean_28"].notna()].copy()
    train, test = df[df["date"] < test_start].copy(), df[df["date"] >= test_start].copy()
    means = train.groupby(["store_id", "sku_code"])["cases"].mean().rename("store_sku_mean_train")
    train, test = train.join(means, on=["store_id", "sku_code"]), test.join(means, on=["store_id", "sku_code"])
    for c in CATEGORICAL:
        cats = pd.Categorical(df[c]).categories
        train[c] = pd.Categorical(train[c], categories=cats)
        test[c] = pd.Categorical(test[c], categories=cats)
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                          categorical_features="from_dtype", random_state=cm.SEED)
    model.fit(train[FEATURES], train["cases"])
    test["pred"] = model.predict(test[FEATURES])
    test["naive"] = test["lag_7"]

    by_sku = test.groupby(["date", "sku_code"])[["cases", "pred", "naive"]].sum()
    by_day = test.groupby("date")[["cases", "pred", "naive"]].sum()
    res = {
        "model": "HistGradientBoosting (Poisson)", "baseline": "same weekday last week",
        "train_rows": len(train), "test_rows": len(test), "test_start": test_start,
        "wape_store_sku": cm.wape(test["cases"], test["pred"]),
        "wape_store_sku_baseline": cm.wape(test["cases"], test["naive"]),
        "wape_sku_day": cm.wape(by_sku["cases"], by_sku["pred"]),
        "wape_sku_day_baseline": cm.wape(by_sku["cases"], by_sku["naive"]),
        "wape_network_day": cm.wape(by_day["cases"], by_day["pred"]),
        "wape_network_day_baseline": cm.wape(by_day["cases"], by_day["naive"]),
        "bias": float(test["pred"].sum() / test["cases"].sum() - 1),
    }
    # $ impact (conservative): only under-forecast cases are valued, at the short-shipment penalty per case;
    # over-forecast cases (excess stock, spoilage risk) are counted in cases but not in dollars.
    days = by_day.shape[0]
    under = lambda f: float((by_sku["cases"] - by_sku[f]).clip(lower=0).sum()) / days
    res["error_cases_per_day"] = float((by_sku["cases"] - by_sku["pred"]).abs().sum()) / days
    res["error_cases_per_day_baseline"] = float((by_sku["cases"] - by_sku["naive"]).abs().sum()) / days
    res["under_cases_per_day"], res["under_cases_per_day_baseline"] = under("pred"), under("naive")
    res["value_per_day"] = (under("naive") - under("pred")) * cm.C.SHORT_PENALTY_PER_CASE
    res["by_day"] = by_day.reset_index()
    res["predictions"] = test[["store_id", "sku_code", "date", "cases", "pred", "naive"]]
    if plot:
        fig, ax, path = cm.figure("demand_forecast.png")
        bd = res["by_day"]
        x = pd.to_datetime(bd["date"])
        ax.plot(x, bd["cases"], color=cm.ACTUAL_COLOR, linewidth=1.5, label="actual")
        ax.plot(x, bd["pred"], color=cm.MODEL_COLOR, label=f"model (WAPE {res['wape_network_day']:.1%})")
        ax.plot(x, bd["naive"], color=cm.BASE_COLOR, linestyle="--", linewidth=1.5,
                label=f"same weekday last week ({res['wape_network_day_baseline']:.1%})")
        ax.set_ylabel("cases ordered per day")
        cm.date_axis(ax)
        ax.legend(loc="upper left", ncol=3, fontsize=9)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        res["figure"] = path
    return res


if __name__ == "__main__":
    r = run(cm.connect())
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if not isinstance(v, pd.DataFrame)})
