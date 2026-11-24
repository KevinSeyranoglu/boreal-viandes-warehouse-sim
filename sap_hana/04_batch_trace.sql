-- Recall: every customer that received a batch, with the cases and the first and last goods issue.
-- Change the batch in the first line (lot 6370, frozen ground pork, recalled on 2027-05-29 in the
-- baseline run, seed 42).
WITH p AS (SELECT '6370' AS CHARG FROM DUMMY)
SELECT c.KUNNR, c.NAME1, c.ORT01, c.ZZROUTE  AS ROUTE,
       i.MATNR,
       SUM(i.LFIMG)                          AS CASES,
       MIN(l.WADAT_IST)                      AS FIRST_GI,
       MAX(l.WADAT_IST)                      AS LAST_GI
FROM BOREAL.LIPS i
JOIN p              ON i.CHARG = p.CHARG
JOIN BOREAL.LIKP l  ON l.VBELN = i.VBELN
JOIN BOREAL.KNA1 c  ON c.KUNNR = l.KUNNR
GROUP BY c.KUNNR, c.NAME1, c.ORT01, c.ZZROUTE, i.MATNR
ORDER BY CASES DESC, c.KUNNR;
