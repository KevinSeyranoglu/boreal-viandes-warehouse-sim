-- Vendor quality from inventory postings: cases received (101), refused or returned to the vendor (122),
-- scrapped from quality inspection (553), and shelf life left at receipt. The vendor comes from the
-- batch master (MCH1), so every posting of a batch is attributed to the plant that made it.
WITH posted AS (
    SELECT b.LIFNR, d.EBELN, d.BWART, d.MENGE,
           CASE WHEN d.BWART = '101'
                THEN DAYS_BETWEEN(TO_DATE(d.BUDAT, 'YYYYMMDD'), TO_DATE(b.VFDAT, 'YYYYMMDD')) END AS DAYS_LEFT
    FROM BOREAL.MATDOC d
    JOIN BOREAL.MCH1 b ON b.MATNR = d.MATNR AND b.CHARG = d.CHARG
    WHERE d.BWART IN ('101', '122', '553') AND d.ZEILE = '0001')
SELECT v.LIFNR, v.NAME1,
       COUNT(DISTINCT p.EBELN)                                                   AS PURCHASE_ORDERS,
       SUM(CASE WHEN p.BWART = '101' THEN p.MENGE ELSE 0 END)                    AS RECEIVED_CASES,
       SUM(CASE WHEN p.BWART = '122' THEN p.MENGE ELSE 0 END)                    AS RETURNED_CASES,
       SUM(CASE WHEN p.BWART = '553' THEN p.MENGE ELSE 0 END)                    AS SCRAPPED_CASES,
       ROUND(100 * SUM(CASE WHEN p.BWART = '122' THEN p.MENGE ELSE 0 END)
             / SUM(CASE WHEN p.BWART IN ('101', '122') THEN p.MENGE ELSE 0 END), 2) AS RETURN_PCT,
       ROUND(AVG(p.DAYS_LEFT), 1)                                                AS AVG_DAYS_LEFT_AT_RECEIPT
FROM posted p
JOIN BOREAL.LFA1 v ON v.LIFNR = p.LIFNR
GROUP BY v.LIFNR, v.NAME1
ORDER BY RETURN_PCT DESC;
