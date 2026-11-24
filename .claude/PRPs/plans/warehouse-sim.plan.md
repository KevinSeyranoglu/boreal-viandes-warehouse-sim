# Plan: Boréal Viandes – Warehouse Simulation + Data Science Portfolio

**Source spec**: `SPEC.md`
**Complexity**: Large

## Summary
An animated pygame-ce simulation of a cold-chain meat distribution center in Québec. **The main goal is a data science portfolio that impresses warehouse, logistics and supply-chain employers.** The simulation produces realistic operational data (receipts, put-aways, picks, shipments, temperatures, spoilage, labor). That data feeds Power BI dashboards and ML models that answer questions a real distribution-center manager has: how many pickers tomorrow, which pallets will spoil, which orders will ship late, is the freezer drifting, what happens if we cut staff.

## Why this impresses warehouse employers
- It speaks their language: OTIF, fill rate, FEFO, cases/hour, cold-chain compliance, catch weight, lot traceability.
- It shows the whole pipeline: event logging → star-schema database → SQL → dashboard → model → business recommendation.
- Every model is compared against the naive method a real site uses today ("same as last week", fixed headcount), with the gain in $ and hours.
- What-if scenarios (lean staff vs extra pickers) show cost/service trade-off analysis, which is exactly what operations managers do.
- There's a live demo: the animated simulation, plus a dashboard, plus an optional in-game panel showing model recommendations.

## Current state (2026-11-23)
- `config.py` is written: 274 lines with all tuning numbers, SKUs, stores, demand mix, seasons, data export settings and `SCENARIOS` + `apply_scenario()`.
- `requirements.txt` is written (`pygame-ce>=2.4`).
- Every other `.py` file, `README.md` and `DATA_DICTIONARY.md` is a 1-line placeholder.
- The folder is not a git repo yet. Run `git init` before Phase 1 (needed for GitHub anyway).

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Naming / constants | `config.py` | UPPER_CASE module constants grouped under `# ---- section` banners, units in comments, times in sim-seconds unless the name says `_H`/`_MIN` |
| Errors | `config.py:apply_scenario` | Bad CLI input → `SystemExit` with a clear message; gameplay states never raise, they log an event |
| Logging | (to build) | Every state change goes through one `sim.log_event(type, **fields)`, which feeds the in-game event log and `datalog.py` |
| Data access | (to build) | `simulation.py` has no pygame import; `datalog.py` subscribes to events, and the sim doesn't know about SQLite |
| Tests | (to build) | pytest in `tests/`; deterministic seeded headless runs |

## Files to Change
| File | Action | Why |
|---|---|---|
| `config.py` | UPDATE (small) | Only add constants as later phases need them |
| `requirements-analytics.txt` | CREATE | pandas, scikit-learn, streamlit, plotly, jupyter, pytest |
| `i18n.py`, `models.py`, `pathfinding.py`, `simulation.py`, `events.py`, `renderer.py`, `ui.py`, `main.py` | FILL placeholder | The game |
| `datalog.py` | FILL placeholder | SQLite star schema + CSV export |
| `DATA_DICTIONARY.md` | FILL placeholder | Every table and column, with units and meaning |
| `dashboard/app.py` | CREATE | Streamlit multi-page dashboard |
| `analytics/sql/*.sql` | CREATE | KPI queries, so the SQL skills are visible to employers |
| `ml/*.py`, `notebooks/*.ipynb` | CREATE | Feature building, training, evaluation, model cards |
| `tests/test_*.py` | CREATE | Simulation invariants, FEFO, pathfinding, datalog |
| `README.md` | FILL placeholder | Portfolio write-up with screenshots and results |

## Tasks

### Phase 1: Window, layout, camera, zones
- **Action**: `i18n.py`, a grid layout built from the `config.py` map constants, `renderer.py` camera and zone drawing, `main.py` loop with pause, speed keys and L.
- **Validate**: `python main.py` opens a window; pan, zoom and Home work; zones are labeled with temperatures. `python -c "import simulation"` works without pygame.

### Phase 2: Clock and the end-to-end flow
- **Action**: models, A*, inbound schedule, temperature check, put-away, FEFO picking, wrapping and staging, loading last stop first, departure. Truck, door, forklift and pallet animations with interpolation.
- **Validate**: `pytest tests/test_flow.py`. A seeded 1-day headless run ships at least one order, and cases are conserved (received = in stock + shipped + spoiled + rejected).

### Phase 3: Staff, orders, events, economy
- **Action**: shifts, roles, hiring, batteries and charging, stores and orders with cutoffs, all random and seasonal events, recall trace, money and the compliance KPI.
- **Validate**: `pytest tests/` passes. A 30-day headless run doesn't crash, and the KPIs fall in plausible ranges.

### Phase 4: Game polish
- **Action**: sidebar charts, floating text, day/night, fog, alarm flashes, tooltips, popups, manual actions, end-of-day screen, F5/F9 save/load.
- **Validate**: save → load → identical state (round-trip test). The game holds 60 fps at 20x speed.

### Phase 5: Data layer (portfolio core)
- **Action**: `datalog.py` writes `data/warehouse_<scenario>_<seed>.db` plus CSVs.
  - **Dimensions:** `dim_sku`, `dim_store`, `dim_worker`, `dim_date`, `dim_zone`.
  - **Facts:** `fact_receipt` (pallet, temp on arrival, accepted/hold/rejected), `fact_putaway`, `fact_pick` (worker, SKU, cases, catch weight, seconds), `fact_shipment` (order, promised/actual time, cases ordered/shipped), `fact_temperature` (zone, every `TEMP_LOG_EVERY_MIN` minutes, °C), `fact_spoilage`, `fact_event`, `fact_labor_shift`.
  - CLI: `--headless --days N --seed S --scenario NAME`. Fill in `DATA_DICTIONARY.md`.
- **Validate**: `python main.py --headless --days 180 --seed 42` finishes in about a minute or less. The same seed gives an identical DB. Each `analytics/sql/*.sql` query returns rows.

### Phase 6: Dashboards (Power BI first)
- **Action**: Power BI is the main tool, since it's what warehouse/logistics employers use.
  - `datalog.py` exports a Power BI-ready star schema as CSVs (`data/powerbi/dim_*.csv`, `fact_*.csv`): clean keys, ISO dates, a `dim_date` with French month and day names.
  - `dashboard/POWERBI_GUIDE.md`: relationships to create, DAX measures written out (OTIF %, Fill Rate %, Cases/Hour, Spoilage $, Compliance %), and a layout for each report page.
  - Power BI Desktop is Windows-only. On Linux, use a Windows VM or PC, or Power BI Service (web).
  - Optional mirror that runs on Linux: a Streamlit app (`streamlit run dashboard/app.py`) with the same pages.
- **Pages:**
  1. **Operations overview:** OTIF, fill rate, cases/hour, orders by status, daily trend.
  2. **Cold chain:** temperature per zone over time, excursions, compliance %, inbound rejects by plant.
  3. **Inventory & expiry:** stock by zone, days-to-expiry histogram, spoilage $ by SKU, FEFO violations.
  4. **Labor:** picks/hour per worker and shift, overtime, headcount vs volume.
  5. **Recall trace:** enter a lot number to see every pallet's location and which stores received it.
  6. **Scenario comparison:** baseline vs lean_staff vs extra_pickers vs chaos, comparing cost, OTIF and spoilage side by side.
  7. **ML insights:** forecasts and risk scores from Phase 7.
- **Validate**: the CSVs load into Power BI with no type errors and the relationships auto-detect, and every DAX measure in the guide is checked against the same number from SQL. If built, the Streamlit mirror renders every page.

### Phase 7: ML models (each compared against a baseline, with business impact)
| Model | Target | Method | Baseline | Business framing |
|---|---|---|---|---|
| Demand forecast | Cases per store × SKU × day | HistGradientBoosting with calendar/lag/season/temperature features | Same weekday last week | Less spoilage, better inbound ordering |
| Labor planning | Picks needed per shift → headcount | Uses the forecast + productivity rates | Fixed headcount | Overtime $ saved, fewer late trucks |
| Spoilage risk | Pallet expires before shipping (yes/no) | Logistic regression / gradient boosting, calibrated | Days-to-expiry rule | Markdown or prioritize pallets early |
| Late shipment risk | Order misses its window | Gradient boosting + feature importances | No prediction | Re-sequence picks before cutoff |
| Temperature anomaly | Zone drifting toward an alarm | IsolationForest / rolling z-score | Fixed threshold alarm | Earlier warning, protects product |

- Time-based train/test split (no leakage). Report metrics: WAPE/MAPE, ROC-AUC, precision@k, and $ impact.
- One notebook per model, plus a short model card in `ml/README.md`.
- **Stretch:** an in-game "Recommandations IA" panel showing tomorrow's suggested headcount and the at-risk pallets.
- **Validate**: `python ml/train_all.py` trains every model from the DB, and each one beats its baseline on the test period.

### Phase 8: Portfolio packaging
- **Action**: README with a GIF of the sim, dashboard screenshots, an architecture diagram, results tables, "what I'd do in a real warehouse", and how to reproduce. Push to GitHub.
- **Validate**: a fresh clone → install → headless run → dashboard → train works by following the README.

## Validation
```bash
pip install -r requirements.txt -r requirements-analytics.txt
python -m pytest tests/ -q
python main.py --headless --days 180 --seed 42
streamlit run dashboard/app.py
python ml/train_all.py
python main.py
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Scope is very large (8 phases) | High | One phase per session, with a working checkpoint at each |
| The data is too "clean" or random, so the ML looks fake | High | Build cause-and-effect into the sim (seasonality, skill, equipment age, heat) and add noise; document the data-generating process honestly |
| Data leakage in the ML | Medium | Time-based splits only; features use only information available at prediction time |
| Headless run too slow for 180 days | Medium | `HEADLESS_TICK_SECONDS` step; agents move along paths without animation detail |
| A* cost with many agents | Medium | Small grid, path cache, replan limit per tick |
| Employers can't tell it's simulated data | Low | State it clearly in the README; it's a strength (a controlled ground truth to validate models against) |

## Acceptance
- [ ] The game runs with `python main.py`, and the whole flow is animated
- [ ] A seeded headless run produces a reproducible SQLite DB, documented in `DATA_DICTIONARY.md`
- [ ] Power BI-ready CSVs + guide (DAX measures, 7 pages, including the scenario comparison)
- [ ] 5 models trained, each beating its baseline, with $ impact stated
- [ ] README tells the story for a warehouse/logistics hiring manager
- [ ] `pytest` is green
