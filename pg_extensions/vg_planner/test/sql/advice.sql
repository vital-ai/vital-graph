-- Parsing, aliases, row estimates, methods, order, and the report.
CREATE TABLE quad (s int, p int, o int);
INSERT INTO quad SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE INDEX quad_ps ON quad (p, s);
CREATE INDEX quad_po ON quad (p, o);
ANALYZE quad;

-- Malformed advice is an error, never skipped.
/*vg:plan 2
bgp b0 steps(a b)
*/ SELECT 1;
/*vg:plan 1
bgp b0 steps(a)
*/ SELECT 1;
/*vg:plan 1
bgp b0 rows(a:1)
*/ SELECT 1;
/*vg:plan 1
bgp b0 steps(a b) rows(a:10)
*/ SELECT 1;
/*vg:plan 1
bgp b0 steps(a b) join(b:spiral)
*/ SELECT 1;
/*vg:plan 1
bgp b0 steps(a b) rows(c:5)
*/ SELECT 1;
/*vg:plan 1
bgp b0 steps(a b) bogus
*/ SELECT 1;
/*vg:plan 1
bgp b0 steps(a b)
bgp b1 steps(b c)
*/ SELECT 1;
/*vg:plan 1 bgp b0 steps(a b) rows(b:1e999) */ SELECT 1;
/*vg:plan 1 bgp b0 steps(A b) */ SELECT 1;

-- An advised alias the statement does not have: a mismatch.
/*vg:plan 1
bgp b0 steps(a zz) rows(zz:5)
*/ SELECT count(*) FROM quad a WHERE a.p = 1;
SET vg_planner.on_mismatch = warning;
/*vg:plan 1
bgp b0 steps(a zz) rows(zz:5)
*/ SELECT count(*) FROM quad a WHERE a.p = 1;
RESET vg_planner.on_mismatch;

-- An advised alias naming two relations: always an error.
/*vg:plan 1
bgp b0 steps(a b)
*/ SELECT count(*) FROM quad a JOIN quad b ON b.s = a.s
   WHERE a.p = 1 AND b.p = 2 AND EXISTS (SELECT 1 FROM quad a WHERE a.p = 3);

-- rows: the prefix's estimate is the model's.
EXPLAIN (COSTS ON)
SELECT * FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
EXPLAIN (COSTS ON)
/*vg:plan 1
bgp b0 steps(a b) rows(b:77777)
*/ SELECT * FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
SELECT vg_planner_last_report();

-- ...and what is joined around it is scaled by the same correction.
EXPLAIN (COSTS ON)
/*vg:plan 1
bgp b0 steps(a b) rows(b:77777)
*/ SELECT * FROM quad a JOIN quad b ON b.s = a.s JOIN quad t ON t.s = b.o AND t.p = 5
   WHERE a.p = 1 AND b.p = 2;

-- join: the method of the join that adds a step.
EXPLAIN (COSTS OFF)
/*vg:plan 1
bgp b0 steps(a b) join(b:hash)
*/ SELECT * FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
SELECT vg_planner_last_report();
EXPLAIN (COSTS OFF)
/*vg:plan 1
bgp b0 steps(b a) join(a:nl)
*/ SELECT * FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
SELECT vg_planner_last_report();
EXPLAIN (COSTS OFF)
/*vg:plan 1
bgp b0 steps(a b) join(b:merge)
*/ SELECT * FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;

-- order: the steps join in the advised order; other relations may interleave.
EXPLAIN (COSTS OFF)
/*vg:plan 1
bgp b0 steps(c b a) order
*/ SELECT * FROM (VALUES (5), (6)) v(k)
   JOIN quad a ON a.o = v.k JOIN quad b ON b.s = a.s JOIN quad c ON c.s = b.s
   WHERE a.p = 1 AND b.p = 2 AND c.p = 3;
SELECT vg_planner_last_report();

-- Advice inside an EXISTS SubPlan is applied there.
EXPLAIN (COSTS OFF)
/*vg:plan 1
bgp b0 steps(x y) join(y:hash)
*/ SELECT count(*) FROM quad a WHERE a.p = 1 AND EXISTS (
     SELECT 1 FROM quad x JOIN quad y ON y.s = x.s
     WHERE x.o = a.o AND x.p = 4 AND y.p = 5 OFFSET 0);
SELECT vg_planner_last_report();

-- Advice that cannot be followed is reported, not assumed.
SET enable_hashjoin = off;
/*vg:plan 1
bgp b0 steps(a b) join(b:hash)
*/ SELECT count(*) FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
RESET enable_hashjoin;

-- The kill switch.
SET vg_planner.enabled = off;
/*vg:plan 1
bgp b0 steps(a zz)
*/ SELECT count(*) FROM quad a WHERE a.p = 1;
RESET vg_planner.enabled;

-- Results are the same with and without advice.
SELECT count(*), sum(a.o + b.o) FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
/*vg:plan 1
bgp b0 steps(b a) rows(a:5) join(a:hash)
*/ SELECT count(*), sum(a.o + b.o) FROM quad a JOIN quad b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;

DROP TABLE quad;

-- A correction is applied once: a join built on the corrected prefix keeps
-- PostgreSQL's own step on top of it, never the ratio a second time.
CREATE TABLE q3 (s int, p int, o int);
INSERT INTO q3 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE INDEX q3_ps ON q3 (p, s);
ANALYZE q3;
-- PostgreSQL alone: the 3-way join estimate.
EXPLAIN (COSTS ON)
SELECT * FROM q3 a JOIN q3 b ON b.s = a.s JOIN q3 c ON c.s = b.s
 WHERE a.p = 1 AND b.p = 2 AND c.p = 3;
-- Only the 2-step prefix advised: the 3-way estimate moves by exactly the
-- prefix's ratio (model / PostgreSQL for {a,b}), once.
EXPLAIN (COSTS ON)
/*vg:plan 1
bgp b0 steps(a b) rows(b:340)
*/ SELECT * FROM q3 a JOIN q3 b ON b.s = a.s JOIN q3 c ON c.s = b.s
 WHERE a.p = 1 AND b.p = 2 AND c.p = 3;
SELECT vg_planner_last_report();
-- Every prefix advised: the full join comes out at the model's number.
EXPLAIN (COSTS ON)
/*vg:plan 1
bgp b0 steps(a b c) rows(b:340 c:12)
*/ SELECT * FROM q3 a JOIN q3 b ON b.s = a.s JOIN q3 c ON c.s = b.s
 WHERE a.p = 1 AND b.p = 2 AND c.p = 3;
-- size: an exact join relation the bgp lines do not cover gets the stated rows,
-- and what is built on it is sized from them (no ratio applied twice).
EXPLAIN (COSTS ON)
/*vg:plan 1
bgp b0 steps(a b) rows(b:340)
size s1 25 a b c
*/ SELECT * FROM q3 a JOIN q3 b ON b.s = a.s JOIN q3 c ON c.s = b.s
 WHERE a.p = 1 AND b.p = 2 AND c.p = 3;
SELECT vg_planner_last_report();
/*vg:plan 1
size s1 25 a zz
*/ SELECT count(*) FROM q3 a WHERE a.p = 1;
DROP TABLE q3;

-- A size over an OUTER join: the join relation's relids include the outer
-- join's own index (PG 16+); the size still matches on its base relations.
CREATE TABLE q4 (s int, p int, o int);
INSERT INTO q4 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
ANALYZE q4;
EXPLAIN (COSTS ON)
/*vg:plan 1
size s1 77 a b
*/ SELECT * FROM q4 a LEFT JOIN q4 b ON b.s = a.s AND b.p = 2 WHERE a.p = 1;
SELECT vg_planner_last_report();
DROP TABLE q4;

-- Corrections travel between join problems: under join_collapse_limit = 1 a
-- written JOIN tree is planned as nested problems, and a corrected join
-- relation from one is an input to the next. Its estimate must not be
-- corrected a second time there.
CREATE TABLE q5 (s int, p int, o int);
INSERT INTO q5 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
ANALYZE q5;
SET join_collapse_limit = 1;
EXPLAIN (COSTS ON)
/*vg:plan 1
bgp b0 steps(a b) rows(b:340)
*/ SELECT * FROM (q5 a JOIN q5 b ON b.s = a.s AND b.p = 2) JOIN q5 c ON c.s = b.s AND c.p = 3 WHERE a.p = 1;
RESET join_collapse_limit;
DROP TABLE q5;

-- A one-alias size: the base relation's scan estimate, which the joins above
-- are built on.
CREATE TABLE q6 (s int, p int, o int);
INSERT INTO q6 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE INDEX q6_po ON q6 (p, o);
ANALYZE q6;
EXPLAIN (COSTS ON) SELECT * FROM q6 a WHERE a.p = 1 AND a.o = 5;
EXPLAIN (COSTS ON)
/*vg:plan 1
size s1 1159 a
*/ SELECT * FROM q6 a WHERE a.p = 1 AND a.o = 5;
SELECT vg_planner_last_report();
DROP TABLE q6;

-- method: the planner's choice of join for an exact join relation.
CREATE TABLE q7 (s int, p int, o int);
INSERT INTO q7 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE INDEX q7_ps ON q7 (p, s);
ANALYZE q7;
EXPLAIN (COSTS OFF)
/*vg:plan 1
method m1 nl a b
*/ SELECT * FROM q7 a JOIN q7 b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
SELECT vg_planner_last_report();
EXPLAIN (COSTS OFF)
/*vg:plan 1
method m1 hash a b
*/ SELECT * FROM q7 a LEFT JOIN q7 b ON b.s = a.s AND b.p = 2 WHERE a.p = 1;
SELECT vg_planner_last_report();
DROP TABLE q7;

-- A relation the advice never names is transparent: a sub-select pulled up into
-- a semi-join (the generator's range criteria) joins with its leaf, and the
-- sizes and methods above it still match.
CREATE TABLE q8 (s int, p int, o int);
CREATE TABLE q8t (u int, v int);
INSERT INTO q8 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
INSERT INTO q8t SELECT g, g % 100 FROM generate_series(1, 1013) g;
CREATE INDEX q8_ps ON q8 (p, s);
ANALYZE q8; ANALYZE q8t;
EXPLAIN (COSTS OFF)
/*vg:plan 1
size k1 77 a b
method m1 hash a b
*/ SELECT * FROM q8 a JOIN q8 b ON b.s = a.s
   WHERE a.p = 1 AND b.p = 2 AND a.o IN (SELECT u FROM q8t WHERE v >= 65);
SELECT vg_planner_last_report();
DROP TABLE q8, q8t;

-- A grouped sub-query inside the pattern stays one relation of the join problem
-- (GROUP BY keeps PostgreSQL from flattening it): advice names it by its alias,
-- sizes it and chooses the join with it.
CREATE TABLE q9 (s int, p int, o int);
INSERT INTO q9 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE INDEX q9_ps ON q9 (p, s);
ANALYZE q9;
EXPLAIN (COSTS OFF)
/*vg:plan 1
size s1 997 g
size k1 77 a g
method m1 hash a g
*/ SELECT * FROM q9 a
   JOIN (SELECT b.s, max(b.o) AS m FROM q9 b WHERE b.p = 2 GROUP BY b.s) g ON g.s = a.s
   WHERE a.p = 1;
SELECT vg_planner_last_report();
EXPLAIN (COSTS OFF)
/*vg:plan 1
method m1 nl g a
*/ SELECT * FROM q9 a
   JOIN (SELECT b.s, max(b.o) AS m FROM q9 b WHERE b.p = 2 GROUP BY b.s) g ON g.s = a.s
   WHERE a.p = 1;
SELECT vg_planner_last_report();
-- Items inside the sub-query name its own relations; items outside name it.
EXPLAIN (COSTS OFF)
/*vg:plan 1
bgp b0 steps(a g) join(g:hash)
method m1 nl b c
*/ SELECT * FROM q9 a
   JOIN (SELECT b.s, max(c.o) AS m FROM q9 b JOIN q9 c ON c.s = b.s
         WHERE b.p = 2 AND c.p = 3 GROUP BY b.s) g ON g.s = a.s
   WHERE a.p = 1;
SELECT vg_planner_last_report();
-- A UNION ALL sub-query is pulled up into an append relation, each branch a
-- child sub-query: a branch's scans map to the UNION, so a join of the outer
-- query with it is named by the UNION's alias.
EXPLAIN (COSTS OFF)
/*vg:plan 1
size k1 50 a un
method m1 hash a un
*/ SELECT * FROM q9 a
   JOIN ((SELECT b.s AS k FROM q9 b JOIN q9 c ON c.s = b.s WHERE b.p = 2 AND c.p = 3)
         UNION ALL
         (SELECT d.s AS k FROM q9 d JOIN q9 e ON e.s = d.s WHERE d.p = 4 AND e.p = 5)) un ON un.k = a.s
   WHERE a.p = 1;
SELECT vg_planner_last_report();
-- The same UNION inside a fenced sub-query: its branches are in the fence's range
-- table as well, and map to the UNION, the innermost.
EXPLAIN (COSTS OFF)
/*vg:plan 1
method m1 hash a un
*/ SELECT * FROM (SELECT a.s, un.k FROM q9 a
   JOIN ((SELECT b.s AS k FROM q9 b JOIN q9 c ON c.s = b.s WHERE b.p = 2 AND c.p = 3)
         UNION ALL
         (SELECT d.s AS k FROM q9 d JOIN q9 e ON e.s = d.s WHERE d.p = 4 AND e.p = 5)) un ON un.k = a.s
   WHERE a.p = 1 OFFSET 0) f;
SELECT vg_planner_last_report();
DROP TABLE q9;
-- A one-alias size is the scan's: a semi-join of that relation with an EXISTS
-- body (transparent to the advice) keeps PostgreSQL's semi-join estimate. It
-- took the scan's 2,000 rows when the body reduced the join to that relation.
CREATE TABLE q10 (s int, p int, o int);
INSERT INTO q10 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
ANALYZE q10;
EXPLAIN (COSTS ON)
/*vg:plan 1
size k0 2000 a
*/ SELECT * FROM q10 a WHERE a.p = 1
   AND EXISTS (SELECT 1 FROM q10 x WHERE x.s = a.s AND x.p = 4 AND x.o < 20);
SELECT vg_planner_last_report();
DROP TABLE q10;
-- An early decode's term row (alias vgd_<var>) is transparent: LEFT JOINed inside the
-- unit that binds the variable, the join the advice names (a b) holds it too.
CREATE TABLE q11 (s int, p int, o int);
INSERT INTO q11 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE TABLE t11 (u int PRIMARY KEY, txt text);
INSERT INTO t11 SELECT g, 'x' || g FROM generate_series(0, 1100) g;
ANALYZE q11; ANALYZE t11;
EXPLAIN (COSTS OFF)
/*vg:plan 1
size k0 1846 a b
method m0 hash a b
*/ SELECT * FROM (q11 a LEFT JOIN t11 vgd_s ON vgd_s.u = a.s)
   JOIN q11 b ON b.s = a.s WHERE a.p = 1 AND b.p = 2;
SELECT vg_planner_last_report();
DROP TABLE q11; DROP TABLE t11;
-- A decode relation joined ABOVE the advised join: the method item (hash a b) is the
-- join of a and b, not the term lookup on top of it, which stays free to probe the
-- key (a nested loop); constrained, it merge-joined the whole term table.
CREATE TABLE q12 (s int, p int, o int);
INSERT INTO q12 SELECT g % 997, g % 13, (g * 7) % 1013 FROM generate_series(1, 24000) g;
CREATE TABLE t12 (u int PRIMARY KEY, txt text);
INSERT INTO t12 SELECT g, 'x' || g FROM generate_series(0, 400000) g;
ANALYZE q12; ANALYZE t12;
EXPLAIN (COSTS OFF)
/*vg:plan 1
size k0 40 a b
method m0 hash a b
*/ SELECT * FROM ((q12 a JOIN q12 b ON b.s = a.s AND b.o = a.o)
   LEFT JOIN t12 vgd_o ON vgd_o.u = a.o * 397) WHERE a.p = 1 AND b.p = 1;
SELECT vg_planner_last_report();
DROP TABLE q12; DROP TABLE t12;
-- A decode relation is never merge-joined, in a sub-problem no advice item names too
-- (a fenced level's term rows): the merge reads the whole term table by its key index.
-- The same statement with a plain alias (x) is the control: PostgreSQL merges it.
CREATE TABLE q13 (s int, o int);
INSERT INTO q13 SELECT g, g % 300000 FROM generate_series(1, 200000) g;
CREATE INDEX ON q13 (o);
CREATE TABLE t13 (u int PRIMARY KEY, txt text);
INSERT INTO t13 SELECT g, 'x' || g FROM generate_series(0, 400000) g;
ANALYZE q13; ANALYZE t13;
EXPLAIN (COSTS OFF)
/*vg:plan 1
size k0 200000 f
*/ SELECT * FROM (SELECT a.s, x.txt FROM q13 a LEFT JOIN t13 x ON x.u = a.o ORDER BY a.o OFFSET 0) f;
EXPLAIN (COSTS OFF)
/*vg:plan 1
size k0 200000 f
*/ SELECT * FROM (SELECT a.s, vgd_x.txt FROM q13 a LEFT JOIN t13 vgd_x ON vgd_x.u = a.o ORDER BY a.o OFFSET 0) f;
DROP TABLE q13; DROP TABLE t13;
