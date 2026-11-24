# Boréal Viandes – Centre de distribution (spec)

**Purpose:** a data science portfolio project aimed at warehouse, logistics and supply-chain employers. The animated simulation produces realistic operational data. That data feeds **dashboards** and **ML models** that answer real distribution-center questions. The game is the showcase and the data generator, not the end goal.

## Tech
- Python 3.11+. The game's only dependency is **pygame-ce** (`requirements.txt`). Run it with `pip install -r requirements.txt`, then `python main.py`.
- The analytics layer uses its own `requirements-analytics.txt` (pandas, scikit-learn, jupyter, pytest; streamlit/plotly only for the optional mirror) so the game stays light.
- No image or sound files. Everything is drawn with pygame shapes and text.
- Files: `main.py` (window, loop, input, CLI), `config.py` (every tuning number + scenarios), `models.py` (dataclasses SKU, Pallet, RackSlot, Truck, Order, Store, Worker, Forklift), `simulation.py` (fixed-step logic, no drawing), `pathfinding.py` (A*), `events.py` (random events), `renderer.py` (drawing and animation), `ui.py` (sidebar, buttons, tooltips, popups, end-of-day), `i18n.py` (FR/EN), `datalog.py` (data export).
- The simulation is separate from rendering: the sim runs up to 20x while drawing stays at 60 fps with interpolation. At 1x, 1 in-game hour ≈ 1 real minute (configurable).
- Save/load to JSON with F5/F9.

## Concept
A cold-chain meat **distribution** center in Québec. It does NOT produce, cut or process meat. Packaged product arrives by reefer truck from plants, is stored at the right temperature, then picked and shipped to grocery stores and restaurants. Fictional company, no real brands.

## Layout (top-down 2D)
Yard with road, truck parking and dock aprons. 4 receiving doors and 6 shipping doors. Refrigerated dock/staging (~2 °C). Fresh cooler (-1 to 2 °C: fresh pork, poultry). Processed meats cooler (0 to 4 °C: ham, bacon, sausages, deli). Freezer (-20 °C: frozen pork, poultry). QA/hold area, forklift charging, break room, office. Rack aisles in each cold zone. Zones are color-coded and show their live temperature.

## Animation
Smooth 60 fps with interpolated positions. Reefer trucks drive in, turn and back up to a door. The door rolls up and down, and the reefer unit blinks. Forklifts and reach trucks pathfind, slow down at corners, raise and lower forks, carry pallets and show a battery bar; they go to charge when low. Workers are circles colored by role. Pickers push pallet jacks that fill case by case. Pallets are colored by product, and rack slots fill and empty. The freezer has a frosty tint and fog when its door opens. Zones flash red during a temperature alarm. Day/night cycle with yard lights. Camera: drag or arrows to pan, wheel to zoom, Home to recenter. Floating text appears for key moments. Sidebar line charts show cases shipped today and freezer temperature over 24 h.

## Products
10–15 fictional SKUs (fresh pork, fresh poultry, processed, frozen). Each has a temperature zone, catch-weight case weight (e.g. 9.2–10.8 kg), shelf life and cases per pallet. Every pallet has a lot number, pack date and best-before date.

## Flow
1. **Inbound:** scheduled reefers (some early, some late) and a temperature check on arrival. Out-of-spec pallets go to QA hold or are rejected.
2. **Put-away** to rack slots in the correct zone. Capacity is limited.
3. **Storage:** product ages, and anything past its best-before date becomes spoilage ($).
4. **Orders:** 8–12 fictional stores order daily with cutoff times.
5. **Picking:** FEFO, mixed pallets per store, actual case weights recorded.
6. **Shipping:** pallets are wrapped, labeled, staged by route and loaded last stop first. Trucks have departure windows.

## Staff & equipment
Day/evening/night shifts. Roles: receiver, forklift operator, picker, loader, QA. Forklift batteries need recharging. The player can hire, assign roles and set headcount per shift.

## Random events
Late inbound truck, reefer failure, freezer door left open, forklift breakdown, sick call, rush order, lot recall (find and pull every pallet of the lot and see which stores already received it), holiday peaks (Christmas ham, summer BBQ).

## Controls
Space to pause, keys 1–5 for speed (1/2/5/10/20x) plus buttons. Click anything to inspect it, with hover tooltips. Prioritize orders, accept or reject inbound pallets, move pallets manually, assign dock doors. End-of-day summary.

## Dashboard (sidebar)
Clock and day, money, on-time %, fill rate, picking accuracy, cases/hour, % full per zone, spoilage $, temperature alarms, energy cost, scrolling event log.

## Economy
Revenue per case. Penalties for late or short deliveries. Costs: wages, energy (freezer costs the most), spoilage, rejected loads. Goal: stay profitable with cold-chain compliance above 98%.

## Language
French (Québec) by default. L switches to English.

## Data, dashboards & ML (portfolio layer)
- `datalog.py` logs every operational event to `data/` (SQLite star schema + CSV), and every column is documented in `DATA_DICTIONARY.md`.
- **Headless mode:** `python main.py --headless --days 180 --seed 42 [--scenario NAME]` generates months of data quickly and reproducibly. The scenarios in `config.py` (baseline, lean_staff, extra_pickers, summer_bbq, chaos) enable what-if / A/B comparisons.
- The data needs real signal for models to learn: weekday and seasonal demand, holiday peaks, store kind mix, BBQ heat sensitivity, worker skill spread, equipment failures.
- **Power BI dashboards** (Power BI-ready star-schema CSVs + a guide with DAX measures; optional Streamlit mirror for Linux) with operations KPIs, cold-chain compliance, inventory and expiry risk, labor productivity, recall traceability, a scenario comparison and ML insights.
- **ML models**, each compared against a simple baseline: demand forecasting, labor planning, spoilage risk, late-shipment risk, and temperature anomaly detection.
- A README framed in business terms (what each model would save, in $ and hours).
