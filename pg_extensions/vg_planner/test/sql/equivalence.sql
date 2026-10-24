-- The copied join search, run with no advice, must plan exactly as core does.
-- vg_planner.force_own_search sends every join problem through the copy.
CREATE TABLE quad (s int, p int, o int, c int);
INSERT INTO quad SELECT g % 997, g % 13, (g * 7) % 1013, g % 3
  FROM generate_series(1, 40000) g;
CREATE INDEX quad_ps ON quad (p, s);
CREATE INDEX quad_po ON quad (p, o);
CREATE TABLE term (id int PRIMARY KEY, txt text);
INSERT INTO term SELECT g, 't' || g FROM generate_series(0, 1100) g;
ANALYZE quad; ANALYZE term;

CREATE FUNCTION plan_of(q text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE r record; out text := '';
BEGIN
  FOR r IN EXECUTE 'EXPLAIN (COSTS ON, VERBOSE) ' || q LOOP
    out := out || r."QUERY PLAN" || E'\n';
  END LOOP;
  RETURN out;
END $$;

CREATE TABLE shapes (name text, q text);
INSERT INTO shapes VALUES
 ('star3', 'SELECT * FROM quad a JOIN quad b ON b.s = a.s JOIN quad c ON c.s = a.s WHERE a.p = 1 AND b.p = 2 AND c.p = 3 AND c.o = 5'),
 ('chain5', 'SELECT * FROM quad a JOIN quad b ON b.s = a.o JOIN quad c ON c.s = b.o JOIN quad d ON d.s = c.o JOIN quad e ON e.s = d.o WHERE a.p = 1 AND b.p = 2 AND c.p = 3 AND d.p = 4 AND e.p = 5'),
 ('terms', 'SELECT ta.txt, tb.txt FROM quad a JOIN quad b ON b.s = a.s JOIN term ta ON ta.id = a.o JOIN term tb ON tb.id = b.o WHERE a.p = 1 AND b.p = 2'),
 ('left', 'SELECT * FROM quad a JOIN quad b ON b.s = a.s LEFT JOIN quad c ON c.s = a.s AND c.p = 3 WHERE a.p = 1 AND b.p = 2'),
 ('exists', 'SELECT * FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2 AND EXISTS (SELECT 1 FROM quad x JOIN quad y ON y.s = x.s WHERE x.s = a.s AND x.p = 4 AND y.p = 5)'),
 ('not_exists', 'SELECT * FROM quad a WHERE a.p = 1 AND NOT EXISTS (SELECT 1 FROM quad x WHERE x.s = a.s AND x.p = 6)'),
 ('values', 'SELECT * FROM (VALUES (1),(2)) v(k) JOIN quad a ON a.o = v.k JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2'),
 ('lateral', 'SELECT * FROM quad a CROSS JOIN LATERAL (SELECT b.o FROM quad b WHERE b.s = a.s AND b.p = 2 OFFSET 0) l WHERE a.p = 1'),
 ('full', 'SELECT * FROM quad a FULL JOIN quad b ON b.s = a.s AND b.p = 2 WHERE a.p = 1 OR a.p IS NULL'),
 ('agg', 'SELECT a.o, count(*) FROM quad a JOIN quad b ON b.s = a.s JOIN quad c ON c.s = b.s WHERE a.p = 1 AND b.p = 2 AND c.p = 3 GROUP BY a.o ORDER BY 2 DESC LIMIT 5');

CREATE TABLE core_plans AS SELECT name, plan_of(q) AS plan FROM shapes;
SET vg_planner.force_own_search = on;
SELECT s.name, plan_of(s.q) = c.plan AS identical
  FROM shapes s JOIN core_plans c USING (name) ORDER BY s.name;
RESET vg_planner.force_own_search;

DROP FUNCTION plan_of(text);
DROP TABLE shapes, core_plans, quad, term;
