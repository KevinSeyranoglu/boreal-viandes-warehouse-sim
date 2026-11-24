-- Dock-to-stock by storage room: minutes from goods receipt at the dock to the pallet's rack bin.
-- LTAP holds every confirmed warehouse task; a pallet (storage unit = SSCC) is received (RCV) and
-- later put away (PUT, first time only). SAP stores dates and times as YYYYMMDD / HHMMSS text.
WITH rcv AS (
    SELECT NLENR AS SU, MATNR, MIN(TO_TIMESTAMP(QDATU || QZEIT, 'YYYYMMDDHH24MISS')) AS T
    FROM BOREAL.LTAP WHERE ZZSCAN = 'RCV' GROUP BY NLENR, MATNR),
put AS (
    SELECT NLENR AS SU, MIN(TO_TIMESTAMP(QDATU || QZEIT, 'YYYYMMDDHH24MISS')) AS T
    FROM BOREAL.LTAP WHERE ZZSCAN = 'PUT' GROUP BY NLENR),
dwell AS (
    SELECT m.RAUBE AS ROOM, SECONDS_BETWEEN(r.T, p.T) / 60.0 AS MINUTES
    FROM rcv r JOIN put p ON p.SU = r.SU JOIN BOREAL.MARA m ON m.MATNR = r.MATNR)
SELECT ROOM,
       COUNT(*)                                                              AS PALLETS,
       ROUND(AVG(MINUTES), 1)                                                AS AVG_MIN,
       ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY MINUTES), 1)        AS P90_MIN
FROM dwell
GROUP BY ROOM
ORDER BY ROOM;
