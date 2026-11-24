-- Cold-chain compliance per zone and month: share of 5-minute sensor readings in spec.
SELECT z.zone,
       substr(t.ts, 1, 7)                                                 AS month,
       z.min_c, z.max_c,
       COUNT(*)                                                           AS readings,
       ROUND(100.0 * AVG(CASE WHEN t.temp_c BETWEEN z.min_c AND z.max_c THEN 1.0 ELSE 0 END), 2) AS in_spec_pct,
       SUM(CASE WHEN t.temp_c > z.max_c THEN 5 ELSE 0 END)                AS minutes_above_max,
       ROUND(MAX(t.temp_c), 1)                                            AS warmest_c,
       ROUND(AVG(t.temp_c), 2)                                            AS mean_c
FROM fact_temperature t
JOIN dim_zone z USING (zone)
WHERE t.scenario = :scenario
GROUP BY z.zone, month
ORDER BY z.zone, month;
