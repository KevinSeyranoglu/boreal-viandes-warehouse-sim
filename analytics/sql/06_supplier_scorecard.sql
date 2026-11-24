-- Supplier scorecard: punctuality, short shipments, aged loads, temperature rejects, spoilage.
WITH spoiled AS (
    SELECT r.plant_code, COUNT(*) AS pallets_spoiled, SUM(sp.value) AS spoiled_value
    FROM fact_spoilage sp
    JOIN fact_pallet_receipts r ON r.scenario = sp.scenario AND r.pallet_id = sp.pallet_id
    WHERE sp.scenario = :scenario
    GROUP BY r.plant_code
)
SELECT p.plant_code, p.name_fr,
       COUNT(*)                                                         AS trucks,
       ROUND(100 * AVG(CASE WHEN t.late_min <= 15 THEN 1.0 ELSE 0 END), 1) AS on_time_arrival_pct,
       ROUND(AVG(t.late_min), 0)                                        AS avg_late_min,
       ROUND(100.0 * (1 - SUM(t.pallets) * 1.0 / SUM(t.pallets_ordered)), 2) AS short_ship_pct,
       ROUND(100 * AVG(t.aged_load), 1)                                 AS aged_load_pct,
       SUM(t.reefer_failure)                                            AS reefer_failures,
       ROUND(100.0 * SUM(t.pallets_rejected) / SUM(t.pallets), 2)       AS rejected_pct,
       COALESCE(s.pallets_spoiled, 0)                                   AS pallets_spoiled,
       ROUND(COALESCE(s.spoiled_value, 0), 0)                           AS spoiled_value
FROM fact_inbound_trucks t
JOIN dim_plant p USING (plant_code)
LEFT JOIN spoiled s USING (plant_code)
WHERE t.scenario = :scenario
GROUP BY p.plant_code, p.name_fr, s.pallets_spoiled, s.spoiled_value
ORDER BY spoiled_value DESC;
