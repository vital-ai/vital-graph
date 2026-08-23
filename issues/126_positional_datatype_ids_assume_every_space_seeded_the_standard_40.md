# Positional datatype ids assume every space seeded the standard 40, and three did not

## Status: OPEN — found 2026-08-23 while fixing `issues/121`

Four helpers in `sparql_sql_schema.py` derive `datatype_id` values by
enumerating `STANDARD_DATATYPES` in order:

    ids = {uri: i for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)}

`numeric_datatype_ids` (:73), `boolean_datatype_ids` (:91),
`datetime_datatype_ids` (:104), and a fourth at :122. This is correct only if
every space seeded those 40 rows, in that order, at creation.

## Measured — 164 per-space datatype tables, both clusters

* **161** hold `xsd:string` at id 1. The assumption holds.
* **3** do not hold `xsd:string` at all:

      sp_geo_test_datatype    2 rows:  1 -> vital-core#geoLocation
                                       2 -> geosparql#wktLiteral
      sp_dedup_test_datatype  0 rows
      sp_vgeo_e2e_datatype    0 rows

All three are on the host dev cluster, oldest row 2026-06-14, and predate the
seeding block now at `sparql_sql_schema.py:1440`. **Production exposure is
unknown** — no access from here, same open question as `issues/121`.

## Two categories, and only one is cheap

### A. A query predicate — RESOLVED 2026-08-23

`filter_pushdown.py:797` emits

    term_text IN ('true','1') AND datatype_id IN ({boolean_datatype_ids()})

into a WHERE clause. In `sp_geo_test` that pins "boolean" to ids that mean
geoLocation and wktLiteral. This is exactly the bug fixed for the string guard
in `0571abe`, and the fix is now trivial: `_ne_equality_cond` already takes
`ctx` as of that commit, so it can call `ctx.dt_ids_for_uris(_BOOLEAN_DATATYPES)`
the way `_plain_string_datatype_guard` does.

**Done.** It resolves through `ctx.dt_ids_for_uris` now, and
`boolean_datatype_ids` is deleted rather than left as a second, wrong source
of truth — the same disposal `string_datatype_ids` got.

One constraint made this less mechanical than it looked. `_ne_equality_cond`
is called with NO context by `_inequality_var`/`_in_var`, which are the
semijoin GATE. Declining there would have been the obvious way to avoid
emitting an unguarded condition, and it would have been wrong: the gate and
the push-down must recognise exactly the same expressions, or semijoin marks a
join whose filter then fails to push. That is `issues/054`, where `gt` became
uniquely slow. So the no-context path drops the guard and keeps the shape —
safe because those two callers read `ops[0]` and discard the SQL.

### B. STORED generated columns — materialized on disk, needs a rewrite

`num_val` and `dt_val` are `GENERATED ALWAYS AS (...) STORED`, and the id list
is baked into the column definition. Both a healthy space and the broken one
carry the identical array:

    datatype_id = ANY (ARRAY[4,11,10,12,3,6,5,19,18,20,21,15,14,16,17,13])

In `sp_geo_test` those ids do not exist yet — the datatype table stops at 2.
That is not harmless, because the loader appends unknown datatypes with the
next serial id (`sparql_sql_space_impl.py:1342`,
`INSERT INTO ..._datatype (datatype_uri) VALUES ($1) ON CONFLICT DO NOTHING`).
**The next 19 datatypes stored in that space take ids 3..21 and are silently
treated as numeric by a STORED column**, whatever they actually are. Wrong
values are then materialized and indexed, and numeric range filters match them.

Repairing a space already in that state is not a metadata change: the existing
comment at `sparql_sql_schema.py:136` records that
`ALTER TABLE ... ADD COLUMN ... STORED` rewrote 10.4M rows in 3m16s.

## Why it stayed invisible

Nothing compares a space's datatype table against `STANDARD_DATATYPES`. A
space created without seeding looks normal: queries run, terms round-trip, and
the generated column simply never matches until the ids collide, at which
point it matches the wrong things. The `numeric_datatype_ids` docstring already
warns that a differently-ordered list makes the partial index "stop matching
the push-down's predicate — silently"; it treats the ORDER as the risk and does
not consider that the rows might not be there at all.

## Exposure query

Cheap, per space:

    SELECT count(*) FROM <space>_datatype
    WHERE datatype_uri = 'http://www.w3.org/2001/XMLSchema#string';

Zero means that space's ids are not the standard ones and both categories above
are wrong for it. A cluster-wide sweep is in this issue's history.

## Suggested order

1. ~~Fix the boolean guard (category A)~~ — done.
2. ~~Add a check that flags a space whose datatype table does not match
   `STANDARD_DATATYPES`~~ — **done**. `scripts/check_space_datatypes.py`
   sweeps a cluster (`--all`) or one space, exits 1 if any is off, and
   `ensure_space_indexes.py` now warns through the same function. It
   reproduces the finding independently:

       test stack (:5433)   56 spaces, 0 off
       host (:5432)          100 spaces, 3 off
                             sp_geo_test    id 1 is vital-core#geoLocation
                             sp_dedup_test  0 rows
                             sp_vgeo_e2e    0 rows

   It compares against the POSITIONAL ids the generated columns assume, not
   merely that the table is non-empty — a space could be populated and still
   have every id shifted, which is the case the column definitions cannot
   survive.
3. Only then decide about repair. **Still open, and deliberately not
   attempted.** Backfilling ids is not possible in place —
   they are referenced by `term.datatype_id` — so a repair means rewriting the
   datatype table AND remapping every term, or recreating the space.

Do not "fix" this by reordering `STANDARD_DATATYPES`: the ids are already
persisted in `term.datatype_id` across 161 healthy spaces, and any reordering
silently reinterprets all of them.
