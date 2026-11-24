-- Latest stock position per SKU: days of cover and cases close to expiry.
WITH last_day AS (
    SELECT MAX(date) AS date FROM fact_inventory_daily WHERE scenario = :scenario
),
shipped_7d AS (
    SELECT l.sku_code, SUM(l.cases) / 7.0 AS cases_per_day
    FROM fact_shipment_lots l, last_day
    WHERE l.scenario = :scenario
      AND julianday(date(l.shipped_ts)) > julianday(last_day.date) - 7     -- the last 7 days
      AND julianday(date(l.shipped_ts)) <= julianday(last_day.date)
    GROUP BY l.sku_code
)
SELECT i.date, k.sku_code, k.name_fr, i.zone, k.shelf_life_days,
       i.pallets, i.cases_on_hand,
       ROUND(s.cases_per_day, 0)                           AS shipped_per_day_7d,
       ROUND(i.cases_on_hand / NULLIF(s.cases_per_day, 0), 1) AS days_of_cover,
       ROUND(i.avg_days_to_expiry, 1)                      AS avg_days_to_expiry,
       i.cases_expiring_2d,
       ROUND(i.cases_expiring_2d * k.value_per_case, 0)    AS value_at_risk
FROM fact_inventory_daily i
JOIN last_day USING (date)
JOIN dim_sku k USING (sku_code)
LEFT JOIN shipped_7d s USING (sku_code)
WHERE i.scenario = :scenario
ORDER BY value_at_risk DESC, days_of_cover;
