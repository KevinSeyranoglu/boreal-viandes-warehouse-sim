# Case study: staffing and dock decisions in a cold-chain distribution center

*Kevin Seyranoglu · [github.com/KevinSeyranoglu/boreal-viandes-warehouse-sim](https://github.com/KevinSeyranoglu/boreal-viandes-warehouse-sim) · [Version française](ETUDE_DE_CAS.md)*

## The question

A Québec meat distributor ships about 25,000 cases a day from three cold rooms to 48 stores. Every day
its managers decide how many pickers to schedule, how to run the dock and which pallets to discount
before they expire. A wrong staffing decision costs either wages or late-delivery fines (3 % of the
order value, as in retailer OTIF programs).

Real warehouse data is private, so I built the warehouse: a simulation of the whole building (trailers,
dock, put-away, picking, loading, shifts, breakdowns, recalls) that writes the same records a warehouse
system does, about 700,000 scan events per 180-day run. Because the generating process is known, every
model can be checked against the truth, and every policy can be tested before anyone tries it on a real
floor.

## What I built

- **Data:** a star schema of 27 tables per run, an IBM i (AS/400)-style fixed-width extract with SAS
  programs, SQLite, DuckDB and Parquet.
- **Analytics:** 9 SQL KPI queries (OTIF, cold chain, supplier scorecard, lot recall trace), a Power BI
  export with 17 DAX measures and a check value for each, and a bilingual Streamlit dashboard.
- **Machine learning:** five models, each scored in dollars against the method a distribution center
  uses today: demand forecast, labour plan, late-order risk, spoilage risk, cold-room early warning.
- **Method:** time-based splits (no random shuffling), leakage checks, 5 random seeds with paired
  comparisons and 95 % intervals, and closed-loop tests that rerun the warehouse with a model in charge.
- **Engineering:** Python, 72 automated tests run by GitHub Actions on every push.

## Five findings

**1. A per-shift crew plan saves about $3,500 a day, with service unchanged.** In closed loop over
5 seeds and 60 test days: picker-hours fell from 351 to 227 a day, wages and late fines fell by
**$3,498 a day** (95 % interval −$4,853 to −$2,143), and on-time went from 99.3 % to 99.7 %.

**2. It started as a failure.** My first labour model planned one figure per day and promised $815 a
day on paper. When I ran the warehouse with it, it **lost money**: on-time fell 3.9 points and fines
rose more than the wages saved, with every safety buffer I tried. The model scored itself with its own
capacity curve, fitted on daily averages. Looking per shift explained it: waves for 03:00–18:00
departures fall on the night and day shifts, while the evening shift had 18 pickers for 5 % of the
picking. Cutting every shift alike also cut the busy ones. Most of the final gain is that rebalancing;
the forecast then keeps 1.7 more points of orders on time than a static rebalanced crew with the same
hours.

**3. One run is not evidence.** With a single simulation, adding pickers looked profitable. Over five
seeds it was profitable with only one of them (−$2,815 a day on average), because profit swings by
±$1,632 a day between runs. Cutting staff was a clear loss with every seed (−$3,209 a day).

**4. Process timing beat extra staff.** When each trailer was given one owner (one receiver unloads it,
one loader loads it, as on a real dock), on-time dropped 3–4 points: the scan log showed loading took
22 minutes after the last pallet instead of 3. Adding loaders recovered little for about $1,000 a day;
releasing pick waves one hour earlier restored service for free.

**5. Sometimes a rule is the right model.** A one-line rule ("fewer than 3 days of shelf life at
receipt") beat the spoilage model with every seed, and every spoiled pallet traced to aged poultry
loads: the fix is a supplier contract clause. Where the signal is real, ML earned its place: the
late-order model reached a PR-AUC of 0.44 against 0.05 for the simple rule.

## What I would tell a manager

- Staff by shift from the forecast, starting with a pilot on some days against a control group.
- Do not trust a model's offline value: test the decision it drives.
- Fix spoilage with the supplier, not with a model.
- A one-wall dock (U-flow) works with 6 fewer doors, at the cost of trailers waiting 8 minutes longer
  at the gate.

## What I learned

The most useful result came from a model that failed: testing it in the loop, then asking why, found
the real problem. Reporting uncertainty (seeds, paired differences, intervals) changed two conclusions
that a single run would have got wrong. And the simplest method that works should be the one that ships.

*Tools: Python (pandas, scikit-learn, DuckDB), SQL, Power BI and DAX, SAS, Streamlit, pygame, pytest,
GitHub Actions. The company, plants and stores are fictional; the data is simulated on purpose.*
