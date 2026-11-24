-- DuckDB examples on data/warehouse.duckdb (python analytics/run_sql.py --engine duckdb --file analytics/duckdb_examples.sql)
-- Each statement is preceded by a title comment. Uses features SQLite lacks: percentiles, PIVOT, QUALIFY, window frames.

-- Life of one inbound pallet: every scan, in order (receiving -> taxi -> put-away -> picks)
SELECT step, ts, txn_type, sku_code, lot, cases, from_loc, to_loc, user_id, equipment_id, doc_no
FROM v_pallet_history
WHERE scenario = 'baseline'
  AND sscc = (SELECT sscc FROM fact_transactions WHERE scenario = 'baseline' AND txn_type = 'RCV' ORDER BY ts LIMIT 1)
ORDER BY step;

-- Dock-to-stock percentiles by hour of arrival (the morning rush)
SELECT received_hour, count(*) AS pallets,
       round(quantile_cont(dock_to_stock_min, 0.5), 1) AS p50_min,
       round(quantile_cont(dock_to_stock_min, 0.9), 1) AS p90_min
FROM v_dock_to_stock WHERE scenario = 'baseline'
GROUP BY ALL ORDER BY received_hour;

-- ABC analysis: items ranked by cases picked, cumulative share (A = top 80 %)
WITH picked AS (
    SELECT sku_code, sum(cases) AS cases FROM fact_transactions
    WHERE scenario = 'baseline' AND txn_type = 'PCK' GROUP BY ALL)
SELECT sku_code, cases,
       round(100 * sum(cases) OVER (ORDER BY cases DESC) / sum(cases) OVER (), 1) AS cumulative_pct,
       CASE WHEN sum(cases) OVER (ORDER BY cases DESC) / sum(cases) OVER () <= 0.8 THEN 'A'
            WHEN sum(cases) OVER (ORDER BY cases DESC) / sum(cases) OVER () <= 0.95 THEN 'B' ELSE 'C' END AS abc
FROM picked ORDER BY cases DESC;

-- Picking productivity by hour of day: cases and active pickers
SELECT hour(ts) AS hour, round(sum(cases) / count(DISTINCT date_trunc('day', ts)), 0) AS cases_per_day,
       round(count(DISTINCT user_id || '@' || CAST(date_trunc('day', ts) AS VARCHAR)) / count(DISTINCT date_trunc('day', ts)), 1) AS pickers
FROM fact_transactions WHERE scenario = 'baseline' AND txn_type = 'PCK'
GROUP BY ALL ORDER BY hour;

-- Busiest picker of each day (QUALIFY filters on a window function)
SELECT CAST(ts AS DATE) AS day, user_id, sum(cases) AS cases_picked
FROM fact_transactions WHERE scenario = 'baseline' AND txn_type = 'PCK'
GROUP BY 1, 2
QUALIFY row_number() OVER (PARTITION BY day ORDER BY cases_picked DESC) = 1
ORDER BY day LIMIT 10;

-- Rack occupancy by room and level on the last day (PIVOT): where do put-aways land?
PIVOT (SELECT split_part(to_loc, '-', 1) AS room, split_part(to_loc, '-', 4) AS level, count(*) AS n
       FROM fact_transactions WHERE scenario = 'baseline' AND txn_type = 'PUT' GROUP BY ALL)
ON level USING sum(n) GROUP BY room ORDER BY room;

-- Recalls: for each recalled lot, how far it had travelled (stores reached, cases shipped before the recall)
WITH recalls AS (
    SELECT CAST(json_extract(detail, '$.lot') AS INTEGER) AS lot, ts AS recalled_ts
    FROM fact_events WHERE scenario = 'baseline' AND event_type = 'ev_recall')
SELECT r.lot, any_value(t.sku_code) AS sku_code, r.recalled_ts,
       count(DISTINCT t.store_id) FILTER (WHERE t.shipped_ts < r.recalled_ts) AS stores_reached,
       coalesce(sum(t.cases) FILTER (WHERE t.shipped_ts < r.recalled_ts), 0) AS cases_at_stores,
       count(*) FILTER (WHERE t.shipped_ts >= r.recalled_ts) AS shipped_after_recall
FROM recalls r LEFT JOIN v_lot_trace t ON t.scenario = 'baseline' AND t.lot = r.lot
GROUP BY r.lot, r.recalled_ts ORDER BY r.recalled_ts;
