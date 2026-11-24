-- OTIF by route: sales orders (VBAK/VBAP) -> document flow (VBFA) -> deliveries (LIKP/LIPS).
-- On time = left on the route truck (VSART 01, not expedited) at most 15 min after the planned goods
-- issue; in full = delivered quantity >= 99.9 % of the ordered quantity.
WITH ordered AS (
    SELECT VBELN, SUM(KWMENG) AS QTY FROM BOREAL.VBAP GROUP BY VBELN),
delivered AS (
    SELECT VBELN, SUM(LFIMG) AS QTY FROM BOREAL.LIPS GROUP BY VBELN),
orders AS (
    SELECT l.ROUTE,
           CASE WHEN l.VSART = '01'
                 AND SECONDS_BETWEEN(TO_TIMESTAMP(l.WADAT || l.WAUHR, 'YYYYMMDDHH24MISS'),
                                     TO_TIMESTAMP(l.WADAT_IST || l.ZZWAUHR_IST, 'YYYYMMDDHH24MISS')) <= 900
                THEN 1.0 ELSE 0.0 END                                          AS ON_TIME,
           CASE WHEN COALESCE(d.QTY, 0) >= 0.999 * o.QTY THEN 1.0 ELSE 0.0 END AS IN_FULL
    FROM BOREAL.VBFA f
    JOIN BOREAL.LIKP l ON l.VBELN = f.VBELN
    JOIN ordered o     ON o.VBELN = f.VBELV
    LEFT JOIN delivered d ON d.VBELN = f.VBELN
    WHERE f.VBTYP_N = 'J')
SELECT ROUTE,
       COUNT(*)                                     AS ORDERS,
       ROUND(100 * AVG(ON_TIME), 1)                 AS ON_TIME_PCT,
       ROUND(100 * AVG(IN_FULL), 1)                 AS IN_FULL_PCT,
       ROUND(100 * AVG(ON_TIME * IN_FULL), 1)       AS OTIF_PCT
FROM orders
GROUP BY ROUTE
ORDER BY OTIF_PCT, ROUTE;
