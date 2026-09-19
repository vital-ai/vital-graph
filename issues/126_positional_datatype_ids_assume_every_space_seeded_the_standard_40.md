# Positional datatype ids assume every space seeded the standard 40, and three did not

## Status: RESOLVED 2026-09-18 — found 2026-08-23 while fixing `issues/121`

    A. a query predicate              RESOLVED 2026-08-23
    B. STORED generated columns       step 1 done, step 2 done,
                                      step 3 (repair) done 2026-09-18
    production exposure "unknown"     ANSWERED 2026-09-18: ZERO

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


## RESOLVED 2026-09-18 — production is clean, and the repair was small

### The open question first: production exposure

"**Production exposure is unknown** — no access from here" has been the header
finding since 2026-08-23. It is now measured, and the answer is **zero**. All
six prod spaces hold the standard ids:

    lead_prod         40 rows   positions 1..40 intact
    sp_kg_types       40 rows   positions 1..40 intact
    wordnet_frames    40 rows   positions 1..40 intact
    cardiff_kg        38 rows   positions 1..38 intact, 39/40 absent
    lead_data         38 rows   positions 1..38 intact, 39/40 absent
    testspace         38 rows   positions 1..38 intact, 39/40 absent

Checked two ways — the checker, and an independent positional comparison
written against `STANDARD_DATATYPES` directly — because "38 rows, not 40" is
exactly the shape that could be either harmless or the worst case, and a count
cannot tell them apart. It is TAIL truncation: the two missing entries are
positions 39 and 40, `geosparql#wktLiteral` and `vital-core#geoLocation`,
added to the list after those spaces were created. Nothing reads them
positionally — the geo path matches by URI through
`geo_datatype_uris TEXT[]` — and the numeric array stops at 21. So prod is
correct and has no latent id collision in the range anything uses.

One residue, NOT repaired because it is a production write: those three
spaces' sequences sit at 38, so whichever geo datatype is loaded first takes
39. If that is `geoLocation` the two end up transposed relative to
`STANDARD_DATATYPES`, which no code would notice and the checker would then
report as off. See "incomplete is not the same as correct" below — nothing
handles this, including the tooling above as first written.

### Step 3, the repair — deferred on a constraint that does not exist

The issue deferred this on:

    Backfilling ids is not possible in place — they are referenced by
    `term.datatype_id` — so a repair means rewriting the datatype table AND
    remapping every term, or recreating the space.

The second half is right. The first half is not: there is **no foreign key**
from `{space}_term.datatype_id` to `{space}_datatype`. The remap is an UPDATE.
And "every term" was three orders of magnitude off —

    sp_dedup_test   140 terms,   0 carrying a datatype_id
    sp_vgeo_e2e      15 terms,   0 carrying a datatype_id
    sp_geo_test     187 terms,  45 carrying a datatype_id, all id 1

— so two of the three needed no remap at all and the third needed 45 rows. The
3m16s/10.4M-row figure that made this look expensive is the cost of ADDING a
generated column (`sparql_sql_schema.py:136`). This adds none: the columns
exist and their definitions are already right. The DATA under them was wrong.

`scripts/repair_space_datatypes.py` does it: remap the ids terms actually use,
rewrite the table to the canonical 40, `setval` the sequence past the block.
All three repaired, and verified by resolving all 45 `sp_geo_test` terms
through the join to their datatype URI before and after — byte-identical, so
`geoLocation` moved from id 1 to its canonical 40 and every term moved with it.
`num_val`/`dt_val` stayed 0/0 as they must, since geoLocation is in neither
array.

The sequence reset is the part that matters, and is why "leave it, they are
test spaces" was the wrong call. `sp_geo_test` sat at 2, so the next datatype
loaded there would have taken **id 3 — `xsd:decimal`, which IS in the numeric
array** — and the next 19 after it. That is this issue's predicted failure, one
ingest away. It is now at 41.

### What the sweep found that this issue had not: inert spaces

Running the checker across every local cluster turned up six more spaces off —
`vitalgraph2__*` on the host `vitalgraphdb`, 29 differing ids each, one with
3.4M terms. They are a LEGACY schema: partitioned term tables with **no
`num_val`/`dt_val` at all**. Their ids are wrong and nothing reads them, because
the generated columns are the only positional consumer left after category A.

Repairing them would have rewritten millions of rows to correct a value no code
reads. So the checker now measures exposure per space from
`pg_attribute.attgenerated` and reports those as `off-inert` WITHOUT setting
exit 1, and the repair script skips them. A gate that fails where there is no
defect is a gate someone switches off, and then it is not watching the space
that is actually broken.

That check is measured per space rather than inferred from the schema version
or the space name, so a space that gains the columns later is caught the next
sweep.

Also recorded, not acted on: 3,388,296 terms in `vitalgraph2__part_7271_` carry
`datatype_id = 0`, an id with no row in that space's datatype table — that
schema's sentinel for "no datatype" where the current one uses NULL. The repair
script REFUSES a space in that state rather than guessing what an unrecoverable
id meant, which is how it was noticed.

### Final state

    prod (6 spaces)                0 off
    docker test stack (19)         0 off
    host sparql_sql_graph (40)     0 off   (3 repaired)
    host vitalgraphdb (6)          0 off   (6 inert, correctly not repaired)


## 2026-09-19 — INCOMPLETE is not the same as CORRECT, and nothing handled it

Asked whether the migration scripts cover the production residue above. They do
not, and neither did the checker or the repair script as written the day
before. Worth recording as its own finding, because the gap was invisible for
the same reason the original bug was: everything present was correct.

### Nothing seeds a space after it is created

One seeding site exists, inside `create_space_tables`
(`sparql_sql_schema.py:2062`), and it runs once at creation. Then:

  * `migrate_space_schema.py` excludes this table BY NAME — line 85 lists
    `rdf_quad, term, datatype` as "primary data; a change needs a real
    backfill".
  * `ensure_space_indexes.py` only WARNS, through the checker (step 2 above).
  * the three write paths that meet an unknown datatype —
    `data_import_impl.py:85`, `emit_update.py:92`,
    `kg_server_properties.py:316` — all do
    `INSERT (datatype_uri) VALUES ($1) ON CONFLICT DO NOTHING`, taking the next
    serial id.

So a space created before an entry was appended to `STANDARD_DATATYPES` never
gets it, and the id it eventually takes is decided by ARRIVAL ORDER. For the
three prod spaces that is `wktLiteral`/`geoLocation` at 39/40, transposed if
`geoLocation` is stored first.

### The tooling had the same blind spot

`check_space` compared only the ids that were THERE, so 38 correct rows out of
40 passed as `ok` — and because the repair script skips anything `ok`, running
it against production did nothing at all. A space CORRECT BUT INCOMPLETE was
invisible to both. Now reported as `incomplete`, distinguishing a missing TAIL
from a GAP inside the standard range, which are different risks: an append
lands in standard space only in the second case.

Not counted toward the exit status. Neither `off-inert` nor `incomplete` is
wrong today, and a gate that fails where there is no defect is a gate somebody
switches off — at which point it is not watching the space that IS broken.

Reported regardless of whether the space has `num_val`/`dt_val`: the
`off-inert` downgrade is about WRONGNESS, which only matters if something reads
the ids, while incompleteness is about the table and its SEQUENCE and the
append hazard is the same either way.

### The top-up had to be a second path, not a flag

`plan_repair` renumbers non-standard URIs to sit immediately after the standard
block. That is right when rewriting a table and wrong here, and reusing it
would have been silently destructive: on the test stack `dawg_test` holds seven
non-standard datatypes at 11302-11308, and `plan_repair` proposed relocating
them to 41-47 — as an INSERT-only top-up, re-inserting all seven as duplicates.

`plan_topup` adds only the missing STANDARD rows, touches no existing row, sets
the sequence past every id present (standard or not, so 11308 rather than 40),
and REFUSES when a missing position is occupied by a different URI, because
seeding it would need a remap and a remap is the other path's job.

Found by reproducing the production shape on the test stack and running against
that, rather than against production.

### The check immediately found two more

Two host spaces nobody had looked at — `dawg_test` and `kgquery_perf` — were in
the same state and had been passing as `ok`. Both topped up.

### State

    prod (6)                 3 incomplete — NOT applied, a production write
    docker test stack (19)   0
    host sparql_sql_graph    0  (3 repaired 09-18, 2 topped up 09-19)
    host vitalgraphdb (6)    0  (inert)

The prod top-up is two INSERTs and a `setval` per space, adds no row any term
references, and is shown by `--all` without `--apply`. It has not been run.
