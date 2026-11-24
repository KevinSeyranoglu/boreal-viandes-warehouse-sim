-- What-if comparison across every scenario loaded: service vs cost per day.
SELECT k.scenario,
       COUNT(*)                                  AS days,
       ROUND(100 * AVG(k.on_time), 1)            AS on_time_pct,
       ROUND(100 * AVG(k.fill_rate), 2)          AS fill_rate_pct,
       ROUND(AVG(k.cases_shipped), 0)            AS cases_per_day,
       ROUND(AVG(k.wages), 0)                    AS wages_per_day,
       ROUND(AVG(k.penalties + k.expedite_cost), 0) AS service_failure_cost_per_day,
       ROUND(AVG(k.spoilage), 0)                 AS spoilage_per_day,
       ROUND(AVG(k.energy), 0)                   AS energy_per_day,
       ROUND(AVG(k.profit), 0)                   AS profit_per_day,
       ROUND(100 * AVG(k.compliance), 2)         AS cold_chain_compliance_pct
FROM fact_daily_kpi k
GROUP BY k.scenario
ORDER BY profit_per_day DESC;
