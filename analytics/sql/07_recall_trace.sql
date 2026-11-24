-- Recall trace for one lot: where it came from and every store that received it.
SELECT 'received' AS step, r.received_ts AS ts, r.plant_code AS party,
       pl.name_fr AS name, r.pallet_id, r.cases, r.pack_date, r.best_before, r.decision AS detail
FROM fact_pallet_receipts r
JOIN dim_plant pl USING (plant_code)
WHERE r.scenario = :scenario AND r.lot = :lot
UNION ALL
SELECT 'shipped', l.shipped_ts, l.store_id, s.name, NULL, l.cases, NULL, NULL, s.city
FROM fact_shipment_lots l
JOIN dim_store s USING (store_id)
WHERE l.scenario = :scenario AND l.lot = :lot
ORDER BY ts;
