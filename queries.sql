-- 1) Defect rate by line and shift
SELECT line, shift,
       COUNT(*)                         AS parts,
       SUM(defect)                      AS defects,
       ROUND(100.0 * AVG(defect), 3)    AS defect_rate_pct
FROM parts
GROUP BY line, shift
ORDER BY defect_rate_pct DESC;

-- 2) Defect rate per 6h block with a 4-period rolling average
WITH p AS (
    SELECT period, COUNT(*) AS n, SUM(defect) AS d
    FROM parts GROUP BY period
)
SELECT period, n, d,
       ROUND(100.0 * d / n, 3) AS rate_pct,
       ROUND(100.0 * AVG(1.0 * d / n) OVER (
             ORDER BY period ROWS BETWEEN 3 PRECEDING AND CURRENT ROW), 3) AS rolling_rate_pct
FROM p
ORDER BY period;

-- 3) Station risk ranking (parts passing the station that later failed), with lift vs. overall
WITH overall AS (SELECT AVG(defect) AS base FROM parts),
s AS (
    SELECT e.station, COUNT(*) AS parts, AVG(p.defect) AS rate
    FROM station_events e JOIN parts p USING (part_id)
    GROUP BY e.station
    HAVING COUNT(*) >= 500
)
SELECT station, parts,
       ROUND(100.0 * rate, 3)           AS defect_rate_pct,
       ROUND(rate / base, 2)            AS lift,
       RANK() OVER (ORDER BY rate DESC) AS risk_rank
FROM s, overall
ORDER BY risk_rank
LIMIT 15;

-- 4) Worst shift per line (ROW_NUMBER over partition)
WITH x AS (
    SELECT line, shift, AVG(defect) AS rate,
           ROW_NUMBER() OVER (PARTITION BY line ORDER BY AVG(defect) DESC) AS rn
    FROM parts GROUP BY line, shift
)
SELECT line, shift, ROUND(100.0 * rate, 3) AS defect_rate_pct
FROM x WHERE rn = 1;