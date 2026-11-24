-- Service level per customer: which stores get hurt when things go wrong?
SELECT s.store_id, s.name, s.kind, s.route_id, s.stop,
       COUNT(*)                                                         AS orders,
       ROUND(100 * AVG(CASE WHEN o.on_time = 1 AND o.fill_rate >= 0.999 THEN 1.0 ELSE 0 END), 1) AS otif_pct,
       ROUND(100.0 * SUM(o.cases_shipped) / SUM(o.cases_ordered), 2)    AS fill_rate_pct,
       SUM(1 - o.on_time)                                               AS late_orders,
       ROUND(AVG(CASE WHEN o.on_time = 0 THEN o.late_min END), 0)       AS avg_late_min,
       SUM(o.expedited)                                                 AS expedited,
       ROUND(SUM(o.penalty), 0)                                         AS penalties
FROM fact_orders o
JOIN dim_store s USING (store_id)
WHERE o.scenario = :scenario
GROUP BY s.store_id
ORDER BY otif_pct, penalties DESC;
