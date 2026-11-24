-- What drives spoilage? Spoiled pallets by SKU, split by whether they came on an aged load.
SELECT sp.sku_code, k.name_fr, r.plant_code,
       COUNT(*)                                            AS pallets_spoiled,
       SUM(sp.cases)                                       AS cases_spoiled,
       ROUND(SUM(sp.value), 0)                             AS value_spoiled,
       SUM(t.aged_load)                                    AS from_aged_loads,
       ROUND(100.0 * SUM(t.aged_load) / COUNT(*), 0)       AS aged_share_pct,
       ROUND(AVG(julianday(r.best_before) - julianday(date(r.received_ts))), 1) AS avg_days_left_at_receipt
FROM fact_spoilage sp
JOIN fact_pallet_receipts r ON r.scenario = sp.scenario AND r.pallet_id = sp.pallet_id
JOIN fact_inbound_trucks t  ON t.scenario = r.scenario AND t.truck_id = r.truck_id
JOIN dim_sku k ON k.sku_code = sp.sku_code
WHERE sp.scenario = :scenario
GROUP BY sp.sku_code, r.plant_code
ORDER BY value_spoiled DESC;
