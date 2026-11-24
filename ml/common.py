"""Shared helpers for the ML models: database access, the time split, metrics and figure style.

Every model trains on the first TRAIN_DAYS of a run and is evaluated on the days after
(time-based split, never random), using only information available when the decision is made.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402

DB = os.environ.get("WAREHOUSE_DB", os.path.join(ROOT, "data", "warehouse.db"))
FIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
TRAIN_FRACTION = 2 / 3                       # first 2/3 of the days train, the last 1/3 test
SEED = 42

# validated palette (same as the dashboards): model vs baseline always in these two colours
MODEL_COLOR, BASE_COLOR, ACTUAL_COLOR = "#2a78d6", "#eb6834", "#52514e"
INK2, MUTED, GRID, SURFACE = "#52514e", "#898781", "#e1e0d9", "#fcfcfb"


def connect(db=None):
    path = db or DB
    if not os.path.exists(path):
        raise SystemExit(f"{path} not found. Generate data and run: python analytics/build_db.py")
    return sqlite3.connect(path)


def q(con, sql, **params):
    return pd.read_sql_query(sql, con, params=params)


def split_date(con, scenario="baseline"):
    """First date of the test period."""
    days = q(con, "SELECT date FROM fact_daily_kpi WHERE scenario = :s ORDER BY date", s=scenario)["date"]
    return days.iloc[int(len(days) * TRAIN_FRACTION)]


def wape(actual, pred):
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    return float(np.abs(actual - pred).sum() / max(actual.sum(), 1e-9))


def precision_at_k(y, score, k):
    order = np.argsort(-np.asarray(score))[:k]
    return float(np.asarray(y)[order].mean()) if k else 0.0


def figure(name):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 10, "axes.edgecolor": "#c3c2b7",
                         "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.grid": True, "grid.color": GRID, "axes.facecolor": SURFACE,
                         "figure.facecolor": SURFACE, "axes.spines.top": False, "axes.spines.right": False,
                         "lines.linewidth": 2, "legend.frameon": False})
    fig, ax = plt.subplots(figsize=(8, 3.6))
    os.makedirs(FIG_DIR, exist_ok=True)
    return fig, ax, os.path.join(FIG_DIR, name)


def date_axis(ax):
    import matplotlib.dates as mdates
    loc = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
