-- Picker productivity: cases per paid hour, accuracy and travel, by worker.
WITH hours AS (
    SELECT worker_id, SUM(hours) AS hours, COUNT(*) AS shifts_worked
    FROM fact_labor
    WHERE scenario = :scenario AND role = 'picker'
    GROUP BY worker_id
),
picks AS (
    SELECT picker_id AS worker_id, COUNT(*) AS lines, SUM(cases) AS cases,
           SUM(mispick) AS mispicks, AVG(travel_m) AS travel_m_per_line
    FROM fact_picks
    WHERE scenario = :scenario
    GROUP BY picker_id
)
SELECT w.worker_id, w.name, w.shift, ROUND(w.skill, 2) AS skill,
       h.shifts_worked, ROUND(h.hours, 0) AS hours,
       p.cases,
       ROUND(p.cases / h.hours, 1)                          AS cases_per_hour,
       ROUND(100.0 * (1 - p.mispicks * 1.0 / p.lines), 2)   AS accuracy_pct,
       ROUND(p.travel_m_per_line, 0)                         AS travel_m_per_line
FROM dim_worker w
JOIN hours h USING (worker_id)
JOIN picks p USING (worker_id)
WHERE w.scenario = :scenario
ORDER BY cases_per_hour DESC;
