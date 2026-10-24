-- The library is preloaded; a statement without advice is untouched.
CREATE EXTENSION vg_planner;
SELECT vg_planner_info();
SHOW vg_planner.enabled;
SHOW vg_planner.on_mismatch;
SELECT vg_planner_last_report() IS NULL AS no_report_yet;

CREATE TABLE q (s int, p int, o int);
INSERT INTO q SELECT g % 97, g % 7, g FROM generate_series(1, 5000) g;
CREATE INDEX q_ps ON q (p, s);
ANALYZE q;

EXPLAIN (COSTS OFF)
SELECT * FROM q a JOIN q b ON a.s = b.s WHERE a.p = 1 AND b.p = 2;

-- An ordinary comment is not advice.
EXPLAIN (COSTS OFF)
/* some comment */ SELECT * FROM q a JOIN q b ON a.s = b.s WHERE a.p = 1 AND b.p = 2;

SET vg_planner.on_mismatch = 'bogus';
DROP TABLE q;
