-- Daily operations: volume, OTIF, productivity and profit for one scenario.
-- OTIF = order left on time AND shipped complete (fill rate >= 99.9 %).
WITH o AS (
    SELECT date(scheduled_departure_ts) AS date,
           COUNT(*)                                             AS orders,
           AVG(on_time)                                         AS on_time,
           AVG(CASE WHEN on_time = 1 AND fill_rate >= 0.999 THEN 1.0 ELSE 0 END) AS otif,
           SUM(cases_shipped) * 1.0 / SUM(cases_ordered)        AS fill_rate
    FROM fact_orders
    WHERE scenario = :scenario
    GROUP BY 1
)
SELECT k.date, d.weekday_fr, d.season,
       o.orders,
       ROUND(100 * o.otif, 1)       AS otif_pct,
       ROUND(100 * o.on_time, 1)    AS on_time_pct,
       ROUND(100 * o.fill_rate, 2)  AS fill_rate_pct,
       k.cases_shipped,
       ROUND(k.cph, 1)              AS cases_per_picker_hour,
       k.spoiled_cases,
       ROUND(k.profit, 0)           AS profit
FROM fact_daily_kpi k
JOIN dim_date d USING (date)
LEFT JOIN o USING (date)
WHERE k.scenario = :scenario
ORDER BY k.date;
