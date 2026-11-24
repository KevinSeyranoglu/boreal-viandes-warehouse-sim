# Power BI guide: Boréal Viandes operations report

This builds the report from the simulated data in about an hour. Power BI Desktop runs on Windows
(or use Power BI Service in a browser). On Linux, the same pages are in the Streamlit mirror:
`streamlit run dashboard/app.py`.

## 1. Prepare the data

```bash
python main.py --headless --days 180 --seed 42 --scenario baseline    # repeat for each scenario
python analytics/build_db.py                                          # -> data/warehouse.db
python analytics/export_powerbi.py                                    # -> data/powerbi/*.csv
```

`data/powerbi/` then holds 9 dimension tables, 17 fact tables and `_expected_measures.csv`, the
value every measure below must show (section 6).

## 2. Load and type the tables

**Get data → Text/CSV** for each file in `data/powerbi/` (or **Folder** and combine). In Power Query, set:

| Columns | Type |
|---|---|
| `date`, `pack_date`, `best_before` | Date |
| every `*_ts` and `ts` | Date/Time |
| `*_key`, `*_code`, `*_id` used as keys, `scenario`, `zone`, `route_id`, `store_id` | Text |
| everything else numeric | Decimal or Whole number |

Mark **`dim_date`** as the date table (*Table tools → Mark as date table → `date`*).
Apply the theme: **View → Themes → Browse** → `dashboard/boreal_theme.json`. It holds the
colour-blind-checked palette, with scenarios always in the same colour order.

## 3. Relationships (star schema, single direction, many-to-one)

| From (many) | To (one) |
|---|---|
| every fact `[date]` | `dim_date[date]` |
| every fact `[scenario]` | `dim_scenario[scenario]` |
| `fact_orders`, `fact_order_lines`, `fact_picks`, `fact_shipment_lots` `[store_id]` | `dim_store[store_id]` |
| `fact_order_lines`, `fact_picks`, `fact_shipment_lots`, `fact_pallet_receipts`, `fact_putaway`, `fact_inventory_daily`, `fact_spoilage` `[sku_code]` | `dim_sku[sku_code]` |
| `fact_inbound_trucks`, `fact_pallet_receipts` `[plant_code]` | `dim_plant[plant_code]` |
| `fact_orders`, `fact_shipments` `[route_id]` | `dim_route[route_id]` |
| `fact_temperature_hourly`, `fact_energy_daily` `[zone]` | `dim_zone[zone]` |
| `fact_picks`, `fact_labor`, `fact_incidents`, `fact_pallet_receipts`, `fact_putaway` `[worker_key]` | `dim_worker[worker_key]` |

Tables like `fact_orders` and `fact_order_lines` both relate to `dim_store`. Keep the filter
direction single (dimension → fact) to avoid ambiguous paths.

Every page has a **scenario slicer** (`dim_scenario[label_en]`, single select, default *Baseline*).
All measures assume one scenario is selected, except page 8, which compares them.

## 4. Measures

Create a table `_Measures` and add:

```dax
Orders = COUNTROWS ( fact_orders )

On-Time % = DIVIDE ( SUM ( fact_orders[on_time] ), [Orders] )

OTIF % = DIVIDE ( SUM ( fact_orders[otif] ), [Orders] )          -- on time AND in full

Fill Rate % = DIVIDE ( SUM ( fact_orders[cases_shipped] ), SUM ( fact_orders[cases_ordered] ) )

Cases Shipped = SUM ( fact_orders[cases_shipped] )

Cases per Picker Hour =
DIVIDE (
    SUM ( fact_picks[cases] ),
    CALCULATE ( SUM ( fact_labor[hours] ), fact_labor[role] = "picker" )
)

Spoilage $ = SUM ( fact_spoilage[value] )

Spoilage % = DIVIDE ( SUM ( fact_spoilage[cases] ), [Cases Shipped] )

Air Temp In Spec % =
DIVIDE ( SUM ( fact_temperature_hourly[readings_in_spec] ), SUM ( fact_temperature_hourly[readings] ) )

Cold-Chain Compliance % = AVERAGE ( fact_daily_kpi[compliance] )   -- product temperature, per pallet-reading

Avg Yard Wait (min) = AVERAGE ( fact_inbound_trucks[yard_wait_min] )

Supplier On-Time % =
DIVIDE (
    COUNTROWS ( FILTER ( fact_inbound_trucks, fact_inbound_trucks[late_min] <= 15 ) ),
    COUNTROWS ( fact_inbound_trucks )
)

Short-Ship % = 1 - DIVIDE ( SUM ( fact_inbound_trucks[pallets] ), SUM ( fact_inbound_trucks[pallets_ordered] ) )

Profit $ = SUM ( fact_daily_kpi[profit] )

Profit per Day $ = DIVIDE ( [Profit $], DISTINCTCOUNT ( fact_daily_kpi[date] ) )

Lost-Time Injuries = CALCULATE ( COUNTROWS ( fact_incidents ), fact_incidents[severity] = "lost_time" )

LTI Rate per 100 FTE =                                   -- same unit as the Canadian 1.30 benchmark
DIVIDE ( [Lost-Time Injuries] * 2000 * 100, SUM ( fact_labor[hours] ) )
```

Formats: the `%` measures as Percentage with 1 decimal place (2 for Fill Rate and Spoilage), `$`
measures as Currency with 0 decimal places, and the rest as Whole number or 1 decimal place.

## 5. Pages

Every page has a title, the scenario slicer and a date slicer (`dim_date[date]`, *Between*) in a
row along the top, then a row of 3–4 cards, then the charts. One y-axis per chart.

| # | Page | Cards | Visuals |
|---|---|---|---|
| 1 | **Operations overview** | OTIF %, Fill Rate %, Cases Shipped, Profit per Day $ | Line: `OTIF %` by `dim_date[date]`. Clustered column: `Cases Shipped` by `dim_date[weekday_en]` (sort by `weekday`). Table: `dim_store[name]`, Orders, OTIF %, Fill Rate %, `SUM(fact_orders[penalty])`, sorted by OTIF ascending. |
| 2 | **Cold chain** | Cold-Chain Compliance %, Air Temp In Spec %, temperature alarms (`SUM(fact_daily_kpi[temp_alarms])`) | Line: `AVERAGE(avg_temp_c)` by date, small multiples by `zone`, with a constant line at `dim_zone[max_c]`. Column: rejected pallets (`SUM(fact_inbound_trucks[pallets_rejected])`) by `dim_plant[name_en]`. |
| 3 | **Inventory & expiry** | Spoilage $, Spoilage %, cases expiring in 2 days (`SUM(fact_inventory_daily[cases_expiring_2d])`, last date) | Stacked area: `cases_on_hand` by date and `zone`. Bar: Spoilage $ by `dim_sku[name_en]`. Table: spoiled pallets with plant and aged-load flag (relate `fact_spoilage[pallet_id]` → `fact_pallet_receipts`). |
| 4 | **Labour** | Cases per Picker Hour, `SUM(fact_labor[hours])`, Lost-Time Injuries | Scatter: per picker, x = `dim_worker[skill]`, y = Cases per Picker Hour, legend = `shift`. Column: hours by `role`. Line: cases picked by `date` (from `fact_picks`). |
| 5 | **Suppliers & yard** | Supplier On-Time %, Short-Ship %, Avg Yard Wait (min) | Table: supplier scorecard by plant (trucks, Supplier On-Time %, Short-Ship %, `AVERAGE(aged_load)`, rejected %). Column: `Avg Yard Wait (min)` by `fact_inbound_trucks[gate_hour]` (the morning rush). |
| 6 | **Safety** | Lost-Time Injuries, LTI Rate per 100 FTE (benchmark 1.30 as a reference line), forklift incidents | Table: `fact_incidents` (date, type, severity, role, days lost, cost). Column: incidents by `incident_type`, legend `severity`. |
| 7 | **Recall trace** | Stores reached (`DISTINCTCOUNT(fact_shipment_lots[store_id])`), cases shipped of the lot | Slicer: `lot` (search box). Table: `fact_pallet_receipts` rows for the lot (plant, pack date, pallets). Table: `fact_shipment_lots` rows (store, city, cases, shipped_ts). |
| 8 | **Scenario comparison** | (none: multi-select slicer, all scenarios) | Clustered bar, one per measure: On-Time %, OTIF %, Profit per Day $, Spoilage $ by `dim_scenario[label_en]` (sort by `sort`). Separate charts, not a dual axis, because the measures have different scales. |

## 6. Check the numbers

With the scenario slicer on *Baseline* and no date filter, the cards must show the values in
`data/powerbi/_expected_measures.csv`. These are computed in Python from the same CSVs, with the
same formulas. For the run in this repository (seed 42, 180 days):

| Measure | Baseline | Lean staff | Extra pickers | Chaos | Summer BBQ | Shared dock |
|---|---|---|---|---|---|---|
| On-Time % | 98.4 % | 93.1 % | 99.4 % | 97.5 % | 96.5 % | 99.2 % |
| OTIF % | 95.0 % | 90.1 % | 95.0 % | 89.8 % | 93.3 % | 95.2 % |
| Fill Rate % | 99.68 % | 99.75 % | 99.61 % | 99.26 % | 99.70 % | 99.62 % |
| Cases per Picker Hour | 72.6 | 81.3 | 59.9 | 75.7 | 78.8 | 72.7 |
| Spoilage % | 0.42 % | 0.39 % | 0.45 % | 0.44 % | 0.39 % | 0.48 % |
| Avg Yard Wait (min) | 17.0 | 17.9 | 18.0 | 20.7 | 20.3 | 25.8 |
| Profit per Day $ | 196 | -4,808 | 720 | -4,804 | -4,162 | 1,044 |
| LTI Rate per 100 FTE | 1.83 | 1.98 | 1.62 | 0.00 | 1.83 | 1.83 |

If a card differs, check the relationship directions and that exactly one scenario is selected.

These numbers are one run each. Over five seeds ([docs/MULTISEED.md](../docs/MULTISEED.md)) baseline
profit is $2,667 ± 1,632 a day (seed 42 is a low one), and extra pickers earn less than the baseline with
4 seeds out of 5. If
you add a scenario-comparison page, show the multi-seed range from `data/seeds/multiseed_summary.csv`
rather than ranking scenarios from a single run.
