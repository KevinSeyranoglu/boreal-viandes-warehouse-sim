# Data dictionary

Every headless run writes one CSV per table to `data/<scenario>_seed<seed>/`:

```bash
python main.py --headless --days 180 --seed 42 --scenario baseline
```

`python analytics/build_db.py` loads every run folder into **`data/warehouse.db`** (SQLite), and
`python analytics/build_duckdb.py` into **`data/warehouse.duckdb`** (DuckDB: same tables, with `TIMESTAMP`/`DATE`
types, the views `v_pallet_history`, `v_dock_to_stock`, `v_lot_trace`, `v_order_service`, and optional Parquet). In
the database, every fact table and `dim_worker` start with two extra columns, `scenario` and
`seed`, and a generated `dim_date` is added. The columns below are the data contract
(`datalog.FACT_COLUMNS`). A table with no rows in a run is still written with its header, and
`tests/test_analytics.py` fails if the simulation and this contract drift apart.

## Conventions

| Item | Rule |
|---|---|
| Timestamps (`*_ts`, `ts`) | Text `YYYY-MM-DD HH:MM:SS`, warehouse local time, no daylight saving. They sort and compare as text, and SQLite `date()` / `julianday()` work on them. |
| Dates (`date`, `pack_date`, `best_before`) | Text `YYYY-MM-DD` |
| Money | Canadian dollars, product value or cost (not selling price) unless stated |
| Temperatures | °C |
| Distances | metres (1 floor tile = 1 m) |
| Flags | `0` / `1` integers |
| Doors | Numbers painted on the building: receiving doors 1–6 (west wall), shipping doors 1–14 (east wall) |
| Keys | `sku_code`, `store_id`, `route_id`, `plant_code`, `zone` are text codes. Numeric IDs (`order_id`, `pallet_id`, `truck_id`, `worker_id`, `lot`) are unique within one run (use them with `scenario` and `seed` in the database). |
| Scope | Fictional company, products, plants and stores. The data is simulated (see "How the data is generated"). |

---

## Dimensions

### dim_sku: one row per product (15)
| Column | Type | Meaning |
|---|---|---|
| sku_code | text | Product code. `P` pork, `V` poultry, `T` processed, `C` frozen. |
| name_fr / name_en | text | Product name |
| category | text | `pork`, `poultry`, `processed`, `frozen` |
| zone | text | Storage room: `fresh`, `processed`, `freezer` |
| temp_class | text | `chilled` or `frozen` |
| case_kg_min / case_kg_max | real | Catch-weight range of one case (kg). Actual case weights are random in this range. |
| shelf_life_days | int | Days from pack date to best-before |
| cases_per_pallet | int | Cases on a full supplier pallet |
| value_per_case | real | Product value of one case ($). Used for spoilage and rejection losses. |
| base_demand_cases_day | real | Average network demand per day, before weekday, season and store effects |
| plant_code | text | Supplying plant (→ `dim_plant`) |
| season | text | `xmas`, `bbq`, or empty for year-round products |
| gtin_case / gtin_each | text | GS1 GTIN-14 on the case label, GTIN-13 on the retail piece (valid check digits, fictional prefix 754 1234) |
| brand, supplier_item | text | Brand on the pack, the supplier's own item number |
| pieces_per_case, piece_desc_fr / _en | int / text | Retail units in a case (e.g. 10 trays of 4 chops) |
| uom_base | text | Base unit of measure (`CS` = case) |
| catch_weight | int | 1 if each case is weighed (variable weight), 0 for fixed-weight packs |
| net_kg_nominal, tare_kg, gross_kg_nominal | real | Nominal net weight, box tare and gross weight of a case |
| case_length_cm, case_width_cm, case_height_cm, case_cube_l | int / real | Case dimensions and cube (litres) |
| ti, hi | int | Cases per layer × layers per pallet (`ti × hi = cases_per_pallet`) on a 48 × 40 in pallet |
| pallet_gross_kg_nominal | real | Full pallet weight including the 25 kg wooden pallet |
| storage_min_c / storage_max_c | real | Storage temperature range |
| country_of_origin, lot_controlled | text / int | `CA`; 1 = lot tracked on every scan |

### dim_store: one row per customer (48)
| Column | Type | Meaning |
|---|---|---|
| store_id | text | Customer code (`S` grocery, `C` club, `H` restaurant, from the HRI channel) |
| name, city | text | Fictional customer name and city in Québec |
| kind | text | `grocery`, `club`, `restaurant`. Changes the product mix. |
| size_index | real | Relative order volume (1.0 = average grocery store) |
| route_id | text | Delivery route (→ `dim_route`) |
| stop | int | Stop number on the route (1 = delivered first, so loaded last) |

### dim_route: one row per delivery route (16)
| Column | Type | Meaning |
|---|---|---|
| route_id | text | `R01` … `R16`, one departure per hour from 03:00 to 18:00 |
| departure_hour | int | Scheduled departure hour every day (0–23) |
| shipping_door | int | Shipping door used (1–14) |

### dim_plant: one row per supplier (4)
| Column | Type | Meaning |
|---|---|---|
| plant_code | text | `PORC`, `VOLA`, `TRAN`, `SURG` |
| name_fr / name_en | text | Plant name |
| late_mean_min / late_sd_min | int | Parameters of the plant's arrival lateness (minutes) |

### dim_zone: one row per temperature zone (5)
| Column | Type | Meaning |
|---|---|---|
| zone | text | `dock`, `fresh`, `processed`, `freezer`, `qa` |
| setpoint_c | real | Refrigeration setpoint |
| min_c / max_c | real | Air temperature spec. Outside it, an alarm is raised. |
| kw_at_rest | real | Refrigeration power draw with doors closed, at 0 °C outside |

### dim_worker: one row per employee (per run)
| Column | Type | Meaning |
|---|---|---|
| worker_id | int | Employee ID |
| name | text | Fictional name |
| role | text | `receiver` (unloads trailers), `taxi` (moves pallets from the dock to the drop points, 2 at a time), `forklift` (reach-truck driver, puts pallets away up to 5 levels), `picker`, `loader`, `qa` |
| shift | text | `day` (06–14), `evening` (14–22), `night` (22–06) |
| skill | real | Hidden productivity factor, about N(1, 0.15), clipped to 0.6–1.4. Faster picking, fewer mispicks. |

### dim_location: one row per WMS location (5,224)
| Column | Type | Meaning |
|---|---|---|
| location | text | Location code. Rack slots are `ROOM-ROW-BAY-LEVEL`: `FR` fresh, `TR` processed (transformés), `CG` freezer (congélateur), level `A` = floor … `E` = top beam, e.g. `FR-03-17-C`. Floor spots: `STG-R01-05` receiving staging at door 1, `STG-S09-12` shipping staging at door 9, `PD-FR-03` drop point, `QA-07` QA cage. Doors: `RCV-D01`, `SHP-D14`; in the `shared_dock` scenario every door both receives and ships, `DCK-D01` … `DCK-D14` (its staging keeps `STG-R` for inbound and `STG-S` for outbound). |
| loc_type | text | `RACK`, `STAGE_IN`, `STAGE_OUT`, `PD_POINT`, `QA_CAGE`, `DOOR` |
| zone | text | Temperature zone |
| room_row, bay, level, level_code | int / text | Rack coordinates (empty for floor spots) |
| pick_face | int | 1 for floor-level rack slots (level A) |
| reach_truck_required | int | 1 for levels B–E |

Scan locations that are not in this table: `TRL-<truck>` (a trailer), `JACK-<employee>` (on a pallet
jack), `FLT-<forklift>`, `CUST-<store>` (delivered), `DISPOSAL`, `QUARANTINE`.

### dim_date: one row per calendar day (database only)
| Column | Type | Meaning |
|---|---|---|
| date | text | `YYYY-MM-DD` |
| year, month, day | int | Calendar parts |
| month_fr / month_en | text | `décembre` / `December` |
| weekday | int | 1 = Monday … 7 = Sunday |
| weekday_fr / weekday_en | text | `lundi` / `Monday` |
| iso_week | int | ISO week number |
| is_weekend | int | 1 on Saturday and Sunday |
| season | text | `xmas` (Dec 1–24), `bbq` (Jun 1–Sep 7) or empty |

---

## Facts

### fact_orders: one row per customer order, written when the order closes
| Column | Type | Meaning |
|---|---|---|
| order_id | int | Order ID |
| store_id, route_id | text | Customer and route |
| created_ts | ts | When the store placed the order (8–14 h before departure, or anytime for rush orders) |
| cutoff_ts | ts | When the order was released for picking (5 h before departure) |
| scheduled_departure_ts | ts | Planned truck departure |
| closed_ts | ts | When the order was closed (truck left and nothing outstanding) |
| lines | int | Number of SKU lines |
| cases_ordered / cases_allocated / cases_shipped | int | Order totals. Allocation can be short when stock is missing. |
| fill_rate | real | `cases_shipped / cases_ordered` |
| on_time | int | 1 if the order left on its own truck, at most 15 min late, and was not expedited |
| late_min | real | Minutes the order left after its scheduled departure (0 if on time) |
| rush | int | 1 for a same-day rush order (random event) |
| expedited | int | 1 if part of the order missed the truck and went by courier (costs $380) |
| mispicks_uncaught | int | Wrong cases that reached the customer |
| revenue | real | Distribution fee earned (6 % of product value shipped) |
| penalty | real | 3 % of the order's product value if late (as in retailer OTIF fine programs), + $12 per short case, + $35 per uncaught mispick |

**OTIF** (on time in full) = `on_time = 1 AND fill_rate >= 0.999`.

### fact_order_lines: one row per order × SKU
| Column | Type | Meaning |
|---|---|---|
| order_id, store_id, sku_code | | Keys |
| cases_ordered | int | Quantity the store asked for |
| cases_allocated | int | Quantity reserved from stock at release (FEFO, respecting minimum remaining shelf life) |
| cases_picked | int | Picked onto mixed pallets |
| cases_shipped | int | Delivered (on the truck or expedited) |

### fact_picks: one row per pick line (one SKU, one source pallet)
| Column | Type | Meaning |
|---|---|---|
| pick_id | int | Pick ID |
| from_sscc / to_sscc | text | Licence plate of the source pallet and of the outbound pallet being built |
| location | text | Rack slot code picked from (→ `dim_location`) |
| order_id, store_id, job_id | | Order picked for, and the pick job (one mixed pallet) |
| picker_id | int | Worker (→ `dim_worker`) |
| sku_code, lot, pallet_id | | What was picked, and from which source pallet |
| slot_id, zone, level | | Rack location (level 0 = floor, 1 = upper) |
| cases | int | Cases picked |
| weight_kg | real | Actual catch weight of those cases |
| start_ts / end_ts | ts | Line start (end of the previous line) and end |
| travel_m | real | Walking distance for this line |
| mispick | int | 1 if a wrong item was picked |
| mispick_caught | int | 1 if the mispick was caught and recounted at the pick face |
| shift | text | Picker's shift |
| picker_skill | real | Hidden skill factor of the picker (ground truth for analysis) |
| days_to_expiry | real | Days left before the picked pallet's best-before (FEFO check) |

### fact_shipments: one row per outbound truck
| Column | Type | Meaning |
|---|---|---|
| shipment_id, truck_id | int | Truck ID |
| bol_number | text | Bill of lading `BL0000123` |
| route_id | text | Route |
| door | int | Shipping door 1–14 |
| scheduled_departure_ts / actual_departure_ts | ts | Planned and real departure. The truck waits at most 60 min. |
| orders, pallets, cases | int | Load |
| revenue | real | Fee earned on the load |
| late_min | real | `actual − scheduled` (minutes, ≥ 0) |
| load_sequence_violations | int | Pallets loaded out of stop order (last-stop-first rule broken) |

### fact_shipment_lots: one row per lot × order shipped (traceability)
| Column | Type | Meaning |
|---|---|---|
| order_id, store_id, sku_code, lot | | What went where |
| cases | int | Cases of that lot |
| shipped_ts | ts | When it left |

The sum of `cases` equals the sum of `fact_order_lines.cases_shipped` (tested). Use this table for recall traces.

### fact_inbound_trucks: one row per inbound reefer, written when it leaves
| Column | Type | Meaning |
|---|---|---|
| truck_id | int | Truck ID |
| po_number | text | Purchase order `PO0000123` (one per inbound trailer) |
| plant_code | text | Supplier |
| scheduled_ts | ts | Planned arrival slot |
| gate_ts | ts | Arrival at the gate. The trailer then waits in the yard until a door and a dock worker are free. |
| dock_ts | ts | Backed onto a receiving door. Unloading starts after a 15-minute check-in (paperwork, seal, first probe). `dock_ts − gate_ts` is the yard wait. |
| unload_end_ts | ts | Last pallet off |
| door | int | Receiving door 1–6 |
| pallets_ordered | int | What we ordered on this truck (26–30 pallets on a 53' reefer) |
| pallets | int | What arrived (the plant may short-ship) |
| pallets_rejected | int | Refused at the door for temperature |
| aged_load | int | 1 if the plant shipped older-than-usual product on this truck |
| late_min | real | `gate − scheduled` (negative = early). The tail beyond 8 h comes from rare stacked delays. |
| reefer_failure | int | 1 if the trailer's refrigeration unit failed on the road |

### fact_pallet_receipts: one row per pallet unloaded
| Column | Type | Meaning |
|---|---|---|
| pallet_id, truck_id | int | Keys |
| sscc | text | Licence plate on the pallet label (SSCC-18) |
| po_number | text | Purchase order |
| sku_code, lot, plant_code | | Product, lot and supplier |
| cases | int | Cases on the pallet |
| weight_kg | real | Net pallet weight |
| pack_date / best_before | date | From the label |
| arrival_temp_c | real | Product probe temperature at the door |
| decision | text | `accept` (in spec), `qa` (QA hold) or `reject` (refused, supplier liable) |
| received_ts | ts | Scan time |
| receiver_id | int | Worker |

The opening stock (pallets in racks at the start of the run) has no receipt row.

### fact_putaway: one row per pallet moved into a rack slot
| Column | Type | Meaning |
|---|---|---|
| pallet_id, sku_code, zone | | Pallet and destination room |
| slot_id, level | int | Rack slot and level (0 = floor … 4 = top beam) |
| operator_id, forklift_id | int | Driver and truck |
| start_ts / end_ts | ts | Move duration |
| travel_m | real | Distance driven |
| dock_dwell_min | real | Minutes from receipt to rack (dock wait, taxi trip, drop-point wait, reach-truck move). A cold-chain risk. |

### fact_inventory_daily: snapshot at 00:00, one row per date × SKU
| Column | Type | Meaning |
|---|---|---|
| date | date | Snapshot date |
| sku_code, zone | | Product and room |
| pallets | int | Pallets in racks |
| cases_on_hand | int | Cases in racks |
| cases_reserved | int | Cases allocated to open orders |
| cases_expiring_2d | int | Cases within 2 days of best-before |
| avg_days_to_expiry | real | Case-weighted average days to best-before. **Empty when the SKU has no stock.** |

### fact_spoilage: one row per pallet that expired in the building
| Column | Type | Meaning |
|---|---|---|
| ts | ts | When it was found expired |
| pallet_id, sku_code, lot | | Keys (→ `fact_pallet_receipts` via `pallet_id` for supplier and aged-load analysis) |
| cases | int | Cases thrown out |
| value | real | Product value lost ($) |
| reason | text | `expired` |

### fact_temperature: one row per zone every 5 minutes
| Column | Type | Meaning |
|---|---|---|
| ts | ts | Reading time |
| zone | text | Zone |
| temp_c | real | Air temperature with sensor noise (σ 0.15 °C) |
| setpoint_c / max_c | real | Zone setpoint and upper spec |
| alarm | int | 1 while the zone alarm is active (with 0.3 °C hysteresis) |
| door_open_s | real | Seconds a room door is still open from recent traffic (0–25). Spikes show door traffic. |

Product temperature follows the air with a lag (8 h for frozen, 4 h for chilled). A short door
event warms the air, but rarely the product. Cold-chain compliance in `fact_daily_kpi` is
measured on the product.

### fact_energy_daily: one row per date × zone
| Column | Type | Meaning |
|---|---|---|
| date, zone | | Keys |
| kwh | real | Refrigeration energy used. It rises with outdoor temperature, door openings and recovery after warm-ups. |
| cost | real | At $0.075 per kWh |
| door_passes | int | Times a door of that room was opened |

### fact_labor: one row per worker shift
| Column | Type | Meaning |
|---|---|---|
| date | date | Date the shift started |
| worker_id, role, shift | | Keys |
| start_ts / end_ts | ts | Clock in and out. The first night of a run starts at 05:30. |
| hours | real | Paid hours |
| tasks | int | Jobs completed |
| cases_picked | int | Pickers only |
| break_taken | int | 1 if the 30-minute meal break was taken |
| skill | real | Hidden skill factor (same as `dim_worker`) |

Sick calls show as missing shifts and as `ev_sick` events.

### fact_equipment: forklift events
| Column | Type | Meaning |
|---|---|---|
| ts | ts | Event time |
| forklift_id | int | 1–4 counterbalance, 5–18 reach trucks |
| event | text | `plug`, `unplug`, `breakdown`, `repaired` |
| battery_pct | real | Battery at the event |

### fact_events: operational event log
| Column | Type | Meaning |
|---|---|---|
| ts | ts | Event time |
| event_type | text | e.g. `ev_late_truck`, `ev_reefer`, `ev_door_stuck`, `ev_breakdown`, `ev_sick`, `ev_rush`, `ev_recall`, `log_rejected`, `log_qa_hold`, `log_spoiled`, `log_alarm`, `log_short`, `log_expedite`, `qa_decision`, `log_recall_*` |
| detail | text | JSON with the event's fields, e.g. `{"lot": 4251, "sku": "C401", "pallets": 4}`. Read it in SQLite with `json_extract(detail, '$.lot')`. |

### fact_transactions: one row per scan (the WMS transaction history)
Every time a pallet or case is scanned: received, moved, put away, picked, loaded, shipped or written off.
About 4,000 rows a day.

| Column | Type | Meaning |
|---|---|---|
| ts | ts | Scan time |
| txn_id | int | Transaction number |
| txn_type | text | `RCV` received at the door · `RQA` received to QA hold · `REJ` refused at the door · `TXI` taxi moved it dock → drop point · `PUT` reach truck put it away in a rack slot · `QAM` moved to the QA cage · `QRL` QA release · `QRJ` QA reject (scrap) · `RTV` return to vendor · `PCK` cases picked onto an outbound pallet · `BLD` outbound pallet wrapped and labelled · `LOD` loaded on a trailer · `SHP` goods issue (left the building) · `SPL` expired, written off · `ADJ` damage adjustment · `RCL` recalled lot removed from a pallet · `DSP` disposed |
| mvt_type | text | The SAP movement type with the same meaning (101 receipt, 122 return to vendor, 321 QA release, 553 scrap from QA, 601 goods issue, 551 scrap, 344 to blocked stock, 999 internal move) |
| sscc | text | Licence plate scanned (for `PCK`: the outbound pallet the cases go onto) |
| from_sscc | text | `PCK` only: the source pallet the cases come from |
| sku_code, gtin, lot | text | Item, its case GTIN, lot (`MIXED` and empty for outbound pallets) |
| cases | int | Cases (negative when removed: `ADJ`, `RCL`) |
| weight_kg | real | Net weight; actual catch weight for picks |
| from_loc / to_loc | text | Location codes (→ `dim_location`, plus `TRL-`, `JACK-`, `FLT-`, `CUST-`) |
| user_id | int | Employee who scanned |
| equipment_id | text | `FLT-<id>` forklift, `TAXI` rider jack |
| doc_type / doc_no | text | `PO` purchase order, `SO` sales order (`SO0000123`), `BOL` bill of lading, `EXP` expedite, `QA`, `ADJ`, `RCL` |
| reason | text | Probe temperature at receipt, QA reason, "dropped pallet"… |

A pallet's whole life is `WHERE sscc = '...' ORDER BY ts`. For a recall, follow the lot through the
`PCK` rows to the outbound licence plates, then their `SHP` row to the customer.

### fact_case_scans: one row per case picked (optional, `--case-scans`)
| Column | Type | Meaning |
|---|---|---|
| ts, sscc, from_sscc | | Scan time, outbound pallet, source pallet |
| sku_code, gtin, lot | text | Item scanned |
| case_seq | int | 1…n within the pick line |
| net_kg | real | Catch weight read from that case's label |
| order_id, picker_id, location | | Order, employee, rack slot |

Off by default (about 25,000 rows a day).

### fact_incidents: one row per injury or forklift accident
| Column | Type | Meaning |
|---|---|---|
| ts | ts | When it happened |
| incident_id | int | ID |
| category | text | `injury` (a person was hurt) or `forklift` (property damage only) |
| incident_type | text | Injuries: `overexertion`, `slip_trip_fall`, `struck_by_object`, `caught_in`, `cold_stress_cut`, or forklift injuries `pedestrian_struck`, `tip_over`, `crushed_by_load`, `other`. Damage: `rack_strike`, `dropped_pallet`, `equipment_damage`. |
| severity | text | `lost_time` (days off work), `medical_aid` (treated, home for the shift), `property_damage` |
| worker_id, role | | Person injured, or the driver for damage incidents (empty if none) |
| forklift_id | int | Forklift involved (empty for other injuries) |
| zone | text | Where it happened |
| days_lost | real | Calendar days off (lost-time only). The worker misses every shift until then, and nobody replaces them. |
| cases_damaged | int | Cases destroyed (dropped pallet) |
| cost | real | Income replacement (90 % of wages, CNESST-style), first aid ($150), rack repair ($900) or product destroyed |

Rates (`config.py`, incidents section): lost-time injuries 1.30 per 100 workers per year
(Ontario transportation & warehousing, 2022), applied per worker-hour on shift, with 2.5 treated
injuries per lost-time one (assumption). Forklift accidents are applied per hour a forklift is
driven; the injury types follow the IRSST split of serious Québec forklift accidents (struck pedestrian
31 %, tip-over 28 %, crushed by the load 22 %, other 19 %). Property damage is 30 per forklift
injury (Bird's safety triangle, an assumption). The `chaos` scenario triples all rates. At real rates,
incidents are rare: a handful in 180 days at baseline (1 lost-time injury and 2 forklift damage incidents in the current run).

### fact_weather: one row per day
| Column | Type | Meaning |
|---|---|---|
| date | date | |
| ambient_mean_c / ambient_max_c | real | Outdoor temperature. It drives energy use and BBQ demand. |

### fact_daily_kpi: one row per day, the management summary
| Column | Type | Meaning |
|---|---|---|
| date | date | |
| revenue, costs, profit | real | Day P&L ($) |
| wages, energy, spoilage, penalties, rejected_cost, expedite_cost, repair_cost, incident_cost, fixed_cost | real | Cost breakdown. `rejected_cost` is handling ($45 per pallet) when the supplier is liable, or full product value for pallets that went out of spec in our building. |
| cases_shipped, cases_picked | int | Volume |
| orders | int | Orders closed that day |
| on_time, fill_rate | real | Share of orders on time and cases shipped ÷ ordered, for orders closed that day |
| accuracy | real | `1 − mispicks / pick lines` |
| cph | real | Cases picked per paid picker hour |
| compliance | real | Share of pallet-readings with product in temperature spec |
| temp_alarms | int | Zone alarms raised |
| pallets_received, pallets_rejected, pallets_qa | int | Inbound |
| inbound_trucks, inbound_late | int | Inbound trucks arrived, and those more than 15 min late |
| breakdowns, expedites, spoiled_cases, sick_calls | int | Operational incidents |
| injuries_lost_time, injuries_medical, forklift_incidents, damaged_cases | int | Safety incidents that day (see `fact_incidents`) |
| cash | real | Closing cash balance |

---

## How the data is generated (ground truth)

The data is simulated, so the causes are known. These are the effects built in on purpose, so
that dashboards and models have real signal to find:

| Effect | Where it shows |
|---|---|
| Weekday pattern (Thu–Fri peak, Sunday low) | `fact_order_lines`, `fact_daily_kpi` |
| Christmas peak for ham and turkey (Dec 1–24) and a post-Christmas lull | demand by SKU and date |
| Summer BBQ peak for ribs and sausages, stronger on hot days | demand vs `fact_weather` |
| Store kind changes the mix (clubs buy frozen, restaurants buy fresh pork and poultry) | `fact_order_lines` × `dim_store.kind` |
| Picker skill drives speed and mispicks | `fact_picks`, `fact_labor` × `skill` |
| Staffing drives lateness (see the scenarios) | `fact_orders.on_time` by scenario |
| Plants differ in punctuality, short-shipping and aged loads (the poultry plant is worst) | `fact_inbound_trucks` |
| Spoilage comes from aged loads of short-shelf-life poultry | `fact_spoilage` ⋈ `fact_pallet_receipts` ⋈ `fact_inbound_trucks` |
| Freezer door events warm the air, and energy use rises afterwards | `fact_temperature`, `fact_energy_daily` |
| Outdoor heat raises refrigeration energy | `fact_energy_daily` × `fact_weather` |
| Random incidents: late trucks, reefer failures, breakdowns, sick calls, rush orders, recalls | `fact_events` |
| Inbound trailers arrive in an early-morning rush and wait in the yard for a door and a dock worker | `fact_inbound_trucks.dock_ts − gate_ts` |
| Injuries and forklift accidents at Canadian rates. A lost-time injury leaves its shift short-staffed for days. | `fact_incidents`, `fact_labor` |

Scenarios (`config.SCENARIOS`) change only the listed settings, so the differences between runs
with the same seed are caused by that change, plus the random paths that diverge from it.

## Example queries

Nine ready-made KPI queries are in `analytics/sql/`. Run them with
`python analytics/run_sql.py [number] [--scenario NAME] [--lot N]`:

| File | Question |
|---|---|
| `01_daily_operations.sql` | Daily OTIF, fill rate, productivity, profit |
| `02_otif_by_store.sql` | Which customers get the worst service? |
| `03_cold_chain_compliance.sql` | Readings in spec per zone and month |
| `04_inventory_expiry_risk.sql` | Days of cover and value at risk per SKU |
| `05_labor_productivity.sql` | Cases per hour and accuracy per picker |
| `06_supplier_scorecard.sql` | Punctuality, short shipments, aged loads, rejects, spoilage per plant |
| `07_recall_trace.sql` | Where a lot came from and every store that received it |
| `08_scenario_comparison.sql` | Service versus cost across scenarios |
| `09_spoilage_drivers.sql` | Spoilage by SKU and plant, and the share from aged loads |
