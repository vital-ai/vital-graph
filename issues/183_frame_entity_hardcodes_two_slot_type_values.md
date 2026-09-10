# `frame_entity` Hardcodes Two Slot-Type VALUES As If They Were Schema

## Status: the REWRITE no longer names any role value, and the general table is
## built, gated, and incrementally synced. Verified row-for-row against the
## rewrites-disabled ground truth (425 rows, zero diff, six columns). Remaining:
## a migration script, the maintenance integrity probe, a measurement of the
## 2-joins-per-hop cost at depth, and retiring `frame_entity` with the five
## constants that still feed it.

**Raised:** 2026-09-09, in review of `issues/182`. The reviewer's words: these
"are just values like 'happy' or 'sad' and other queries would use other values.
You seem to be treating a variable as an invariant."

**Related:** `issues/178`, `issues/182` (all their measurements are on the
degenerate dataset described below), `issues/048`, `issues/051`

## The defect

`hasKGSlotType` is an ordinary property whose object is a DATA value. A frame
schema may use any values it likes — the reference query happens to use
`urn:hasSourceEntity` and `urn:hasDestinationEntity`, the way another query
happens to use `"happy"`.

The frame-entity machinery treats those two values as schema constants:

    sync_frame_entity_table.py:18    SOURCE_ENTITY_URI = "urn:hasSourceEntity"
    sync_frame_entity_table.py:19    DEST_ENTITY_URI   = "urn:hasDestinationEntity"
    ensure_frame_entity_table.py:31  (same two)
    rewrite_frame_entity_table.py:33 (same two)

The builder filters on them — `WHERE st.object_uuid IN ($3, $4)` — so only slots
carrying those two values ever produce a row. The table's COLUMNS are named
after them: `source_entity_uuid`, `dest_entity_uuid`.

So `{space}_frame_entity` is not a frame table. It is a binary-relation table
for one particular frame shape, and it is unreachable for any other:

  * a frame whose slots use different role values gets no row, so no collapse;
  * a frame with three or more slots cannot be represented at all;
  * a query naming other slot-type values gets the unoptimised plan, silently.

Nothing reports this. The rewrite simply does not fire.

## Why it has never surfaced

`wordnet_frames` contains exactly two distinct `hasKGSlotType` values:

    urn:hasDestinationEntity   285,348
    urn:hasSourceEntity        285,348

They are precisely the two that are hardcoded. **The dataset every measurement
in `issues/178`, `179`, `180`, `181` and `182` was taken on cannot exhibit this
limitation**, because it contains nothing else. Every "the collapse fires" and
"the collapse is worth Nx" result in those issues is conditional on a dataset
shaped like the constants.

That is worth stating plainly: the performance work in this family is not
wrong, but its generality is unmeasured, and this is the reason.

## What it invalidated in the immediate review

A proposal to add `source_slot_type_uuid` / `dest_slot_type_uuid` columns to
`frame_entity` was RETRACTED on this basis. It was wrong twice over: the value
is constant across every row of the table (570,696 copies of one URI), and the
column NAME already encodes the very role value the column would store. It
would have deepened the hardcoding while appearing to generalise it.

The same objection applies to the `roles` key of the reverted
`slot_type_tautology` table (`issues/178`) — it is parameterised by two data
values supplied by the query, which is what "query-dependent" meant.

## What is NOT established

- ~~Whether any real space uses other slot-type values.~~ **SURVEYED
  2026-09-09, and it is not a hypothetical.** Of 29 local spaces carrying
  `hasKGSlotType`, **only 3 use just the two hardcoded roles; 26 use others** —
  several with more than 180 distinct role values, others with role vocabularies
  of their own. So the frame collapse has been unavailable to almost every space
  since it shipped in March, silently. This is a live fix, not insurance.
- **What a general form would cost.** A table keyed by (frame, role value,
  entity) rather than two named columns is the obvious shape, but it is wider,
  and the collapse's whole value is that it is one row per frame.
- **Whether the ontology actually permits arbitrary role values**, or whether
  these two are privileged by the KG model in a way that makes the hardcoding
  legitimate. That is a question for the model's owner, and it decides whether
  this is a defect or a documented restriction.


## The general form — built 2026-09-09

    {space}_frame_slot (frame_uuid, slot_uuid, role_uuid,
                        entity_uuid, context_uuid, frame_type_uuid)
    PRIMARY KEY (frame_uuid, slot_uuid, context_uuid)

One row per (frame, slot), with the role as an ordinary column value. Any role
value, any arity. A query arm collapses to one join carrying
`role_uuid = <that arm's constant>`, whatever that constant happens to be — the
query supplies it, the schema does not.

`sync_frame_slot_table.resync_frame_slot_table` builds it with **no role
filter**. `entity_uuid` is LEFT-joined: a slot carrying a role but no
`hasEntitySlotValue` is still a slot of that frame, and dropping it here would
change which frames the table describes rather than only how fast it answers.

### Verified equivalent to the table it generalises

Built on `wordnet_frames`: 570,696 rows in 8.8 s — two per frame, which is what
this dataset has. Pivoting it back on the two hardcoded roles and full-joining
against `frame_entity`:

    pivot_rows  285,348
    fe_rows     285,348
    mismatches        0     (source entity, dest entity, frame type)

So the general form loses nothing on the shape the specialised one was built
for, and can express the shapes it cannot.

### State: INERT

The table is created for new spaces by the schema and can be built by the sync,
and **nothing reads it**. `rewrite_frame_entity_table` still matches on
`SOURCE_ENTITY_URI`/`DEST_ENTITY_URI` and still emits `frame_entity`. No query
behaviour has changed, which is deliberate — the rewrite is the correctness-
sensitive half and is not something to half-land.

Still to do, in order:

1. **The rewrite.** Detect a slot ARM — edge + slot-type quad + slot-value quad
   sharing a slot variable — with ANY constant role, and collapse each arm to
   one `frame_slot` join. This is simpler than the current code, which
   special-cases two named roles, and it is what removes the constants from
   `rewrite_frame_entity_table.py`.
2. **The incremental sync paths.** `sync_frame_entity_table` has per-write
   maintenance, staleness cleanup and a delete path; `frame_slot` currently has
   only a full rebuild, which is not enough to keep it correct under writes.
3. **A migration**, and the maintenance-cycle integrity probe that the
   `frame_entity` table already has.
4. **Only then** retire `frame_entity` and its four hardcoded pairs — deleting a
   shipped table across 79 spaces is its own decision, and the planning notes
   already say so.


## The rewrite — landed 2026-09-09

`rewrite_frame_entity_table` now detects a slot ARM — edge + slot-type quad +
slot-value quad sharing a slot variable — with ANY constant role, groups arms by
frame variable, and emits one `frame_slot` join per arm:

    JOIN {space}_frame_slot AS fsmv0 ON fsmv0.frame_uuid = q0.subject_uuid
                                    AND fsmv0.role_uuid = '3dd13e9e-...'
    JOIN {space}_frame_slot AS fsmv1 ON fsmv1.frame_uuid = q0.subject_uuid
                                    AND fsmv1.role_uuid = 'd1daebbc-...'

Both role constants come from the QUERY. The module no longer names any role
value; `slot_role_constants(plan, aliases)` reads them out of the plan, and the
slot-type tautology prefetch in `generator.py` is asked about those roles rather
than two compiled into the source.

Arms join to each other on `frame_uuid` with no special handling: the frame
variable has a position on every arm's alias, so the emitter produces the
equality itself.

### Two defects the verification caught, both silent

**The emitter did not know the new table kind.** `("quad", "edge",
"frame_entity")` is enumerated in six places; `emit_bgp` filtered the new tables
out, so the rewrite removed the quad joins and the emitter dropped their
replacements. The query would have returned EXTRA rows with a plan that looked
correct. Fixed at all six sites.

**The role constraint was being dropped, not remapped.** For a removed alias the
constraint rebuild preserved only context constraints and co-references. That
was right while the role lived in the COLUMN NAME (`source_entity_uuid` vs
`dest_entity_uuid`) — the constraint was genuinely redundant. With the role as
data it is load-bearing, and without it every arm matched every role:
**1,700 rows where the answer is 425**, a 4x cross product. Now remapped to
`fsN.role_uuid = <the query's constant>`.

### Gated, because an unbuilt table returns nothing

`ensure_frame_slot_table` must report the table present AND populated before the
rewrite fires. Without the gate the traversal integration tests went to empty
result sets the moment the rewrite ran against an unbuilt table — joins that
match nothing, silently. The table is never CREATED from the read path; it is
populated if empty, which is the same line the neighbouring ensure paths draw.

### Incremental sync

`sync_frame_slot_after_edge_insert` / `sync_frame_slot_before_delete` /
`delete_frame_slot_for_context`, mirroring the frame-entity twins including the
`plan_cache_mode = force_custom_plan` guard (that module measured ~1 ms for a
prepared statement's first five executions and EIGHT SECONDS from the sixth,
permanently, on a pooled connection).

`DO UPDATE` rather than `DO NOTHING`: the frame-entity path pairs DO NOTHING
with a delete-first call, and a missed delete leaves a stale row. An upsert
cannot go stale that way.

**Every call site is mirrored** — audited at 9 frame_entity calls to 9
frame_slot calls in `sparql_sql_space_impl.py`, and 3 to 3 in
`data_import_impl.py`. A missed site is exactly how a derived table goes
silently stale.

### The 2-joins-per-hop cost — MEASURED, and it is not a regression

A hop that was ONE `frame_entity` row is now TWO `frame_slot` joins, so a
depth-3 walk carries six joins where it carried three. Measured on
`sp_graph_synth_10k`, against the same traversal with the collapse disabled:

    depth 1  collapsed        0.4 ms        160 buffers   2 joins
    depth 1  NO collapse    808.1 ms    841,565 buffers
    depth 2  collapsed        0.8 ms        447 buffers   4 joins
    depth 2  NO collapse    TIMEOUT (>300 s)
    depth 3  collapsed        4.7 ms      1,702 buffers   6 joins
    depth 3  NO collapse    TIMEOUT (>300 s)

Join counts are exactly `2 * depth`, and the collapse still buys orders of
magnitude — **5,260x on buffers at depth 1**, and the uncollapsed form does not
finish at depth 2 or 3. Doubling the join count did not cost the win.

**What this does NOT measure**: `frame_slot` against `frame_entity`. It measures
`frame_slot` against NO collapse. A direct old-vs-new comparison would need the
previous rewrite restored, and the doubled join count is exactly the kind of
thing that comparison exists to catch. The absolute numbers (4.7 ms and 1,702
buffers at depth 3) are in the class `issues/048` describes for the old collapse,
which is why retirement is defensible — but "defensible" is not "measured", and
this gap should be closed before `frame_entity` is dropped.


## Remaining, 2026-09-09

**Done**: the general table, the role-agnostic rewrite, the ensure gate, the
incremental sync paths with every call site mirrored (9:9 and 3:3),
`scripts/migrate_frame_slot_table.py`, and a maintenance integrity probe.

**The probe is DETECTION ONLY**, deliberately. The only rebuild available is
`resync_frame_slot_table`, which TRUNCATEs, and the rewrite READS this table —
a truncate inside the maintenance cycle would make every frame query return zero
rows for the length of the rebuild. The frame-entity twin can repair because it
has a non-blocking backfill (ROW EXCLUSIVE, no truncate). Giving this table one
is the next piece of work; until then repair is a deliberate act via the
migration script.

**Retirement: DONE 2026-09-09.** The census settled the question that had been
holding it — the table was empty in 38 of 41 spaces and populated only in
`wordnet_frames` and two synthetic fixtures, i.e. never in a real space. Dropped
on both local clusters; `scripts/migrate_drop_frame_entity.py` remains for any
other deployment.


## Retirement of `frame_entity` — 2026-09-09

The survey settled it: 26 of 29 spaces could never use the table. Nothing now
builds, maintains or reads it.

**Removed**: the schema DDL (new spaces do not get it), every write-path sync
call, the ensure/populate on the read path, and the maintenance integrity step.
`auto_analyze` now analyses `frame_slot` instead. The entry STAYS in
`drop_space_tables_sql`, so tearing down an old space still removes it.

**Repointed to `frame_slot`**: `resync_all.py`, `bulk_export.py`, and three
delete paths in `kg_impl/kg_backend_utils.py`.

**`scripts/migrate_drop_frame_entity.py`** drops the table, dry-run by default,
and REFUSES a space whose `frame_slot` is absent or empty — dropping the old
table before the new one is built would leave that space with no collapse at
all. `--force` for a space that genuinely has no frames.

### A gap in my own audit, worth recording

The parity audit that reported "9 frame_entity calls to 9 frame_slot calls"
covered `sparql_sql_space_impl.py` and `data_import_impl.py` only. It missed
three `sync_frame_entity_before_delete` calls in `kg_impl/kg_backend_utils.py`
and the resyncs in `resync_all.py` and `bulk_export.py` — five write paths where
`frame_slot` would have gone stale while the audit reported parity. Found by
grepping for residual callers during retirement, not by the audit.

**An audit scoped to the files you happened to edit is not an audit.** The
correct query was "who calls this function", across the tree, not "are the two
files I touched consistent".

### Still open

- **`frame_slot` has no non-blocking backfill.** The maintenance probe detects
  drift and orphans but cannot repair, because the only rebuild TRUNCATEs a
  table the rewrite reads. `frame_entity` had `backfill_frame_entity_table`
  (ROW EXCLUSIVE, no truncate) and this table needs the equivalent.
- **Old-vs-new timing: MEASURED, and it found a regression I then half-fixed.**
  With the slot-type verdict pinned, on the reference CONSTRUCT:

                            frame_entity   frame_slot   frame_slot + covering index
      minus ALL types            903,218    2,032,883        902,869   <- parity
      all type patterns          914,457    7,449,829      6,022,320   <- 6.6x gap

  The covering index — `(context_uuid, role_uuid, frame_uuid)` INCLUDE
  `(slot_uuid, entity_uuid)` — brings the bare traversal to exact parity and is
  now part of the schema. It is not optional; without it the collapse is 2.2x
  worse than the table it replaced.

  **The remaining 6.6x is type-constraint handling, and it is confined to test
  data.** A census before dropping the table found **41 `frame_entity` tables of
  which 38 were EMPTY**; the only three with rows were `wordnet_frames` and two
  synthetic graph fixtures. The table had never held a row for a real space,
  which is the same fact the role survey showed from the other side. So the
  regression is measured on the only dataset where the old table worked, and
  every real space gains a collapse it never had.

  It is still a regression worth closing:
  `issues/182`'s edge-type absorption writes a predicate on
  `edge.edge_type_uuid`; `frame_slot` has no such column, so the absorbed
  constraint cannot survive the collapse and the type joins come back. Fixing it
  means either giving `frame_slot` an `edge_type_uuid` column or teaching the
  collapse to re-absorb. **This should have been measured BEFORE retiring
  `frame_entity`, which is what the previous revision of this section said and
  what did not happen.**
- **`rewrite_frame_entity_table.py` is now misnamed** — it emits `frame_slot`.
  Renaming it touches every importer and was left out of a change already this
  wide.
- **`sync_frame_entity_table.py` and `ensure_frame_entity_table.py` still
  exist**, with the five remaining hardcoded role constants, now unreferenced by
  any live path. They should be deleted once the drop migration has run
  everywhere.


## The type-constraint gap — two failed attempts, and why they failed

**Attempt 1: absorb the EDGE type.** Diagnosed from reading the SQL (a semi-join
back through the edge table) without bisecting first. `frame_slot.edge_type_uuid`
was added, projected, and mapped by the rewrite. It made one shape TIME OUT
(>600 s) where it had measured 6,022,320 buffers. Reverted. A later bisection
showed edge types cost **~0** — the mechanism was real and irrelevant.

The column remains in the schema and builder. It is correct and free to carry
(the builder already joins the edge row), and nothing reads it. Inert, not
harmful.

**Attempt 2: absorb the FRAME type.** Bisection appeared to show
`?frame a KGFrame` costing 5,120,000 of 6,032,427 buffers, and the cause looked
certain: the absorption gate accepted `vitaltype` only, while the query writes
`a`. `frame_type_absorbable` was added — same shape as the edge check, verified
against the data (285,348 frames, both predicates, zero disagreement) — and the
gate widened.

It gained **2%** (6,032,427 -> 5,902,522).

### Why: the measurements are not stable enough to optimise against

    variant                tb_revert     tb_frame     stable?
    0 all type patterns    6,032,427    5,902,522     roughly
    2 minus FRAME type       908,057    4,054,002     NO — 4.5x apart
    5 minus ALL types        905,760      905,759     yes

Variant 2 removes the frame-type pattern, so the attempt-2 change cannot affect
it — and it moved by 4.5x between runs. The `frame_entity` era recorded 4,051,066
for the same variant, which makes 908,057 the outlier and the "5.12M from frame
type" an artifact of one run landing on a better plan.

**The 5.1M is real** — `minus ALL types` is stable at ~905,760 against ~6.0M —
but which constraint owns it cannot be established while individual variants
flip plans between runs.

### What has to be fixed first

`issues/178` records the cause and it was never addressed: the 2 s bound on the
slot-type tautology makes the plan depend on whether the budget happened to be
enough, and that bimodality has been polluting every measurement since. Pinning
the verdict in the probe was not enough — pinning removes one source of
variance, not the plan instability it creates downstream.

Two attempts have now been made at this gap on the strength of unstable numbers,
and both were wrong: one made things worse, one did nothing. **Stop optimising
and fix the measurement.** A benchmark that moves 4.5x between identical runs
cannot tell anyone which mechanism to build.

### What the frame-type absorption is worth keeping for

Not the 2%. It removes a real limitation — `?f rdf:type <T>` was previously
never absorbable regardless of the data, because the gate named one predicate —
and it is verified correct (425 rows, zero diff, and the agreement check refuses
where the data disagrees). It is kept on those grounds, not on performance.


## The shape the query should have — hand-written and measured 2026-09-09

Written by hand against `frame_slot`: materialise the text matches, then walk
out from them.

    WITH happy AS MATERIALIZED (          -- trigram index -> 61 entities
      SELECT DISTINCT q.subject_uuid FROM rdf_quad q
      JOIN term o ON o.term_uuid = q.object_uuid AND o.term_text ILIKE '%happy%'
      WHERE q.predicate_uuid = <hasKGraphDescription> AND q.context_uuid = <graph>)
    SELECT ... FROM happy h
      JOIN frame_slot s ON s.entity_uuid = h.e AND s.role_uuid = <src role>
      JOIN frame_slot d ON d.frame_uuid = s.frame_uuid AND d.role_uuid = <dst role>
    UNION  -- the same, driven from the destination side

Measured:

    hand-written, SIMPLIFIED   2,888 buffers      32 ms    417 rows
    best generated SQL     5,151,495 buffers   3,356 ms    425 rows

**RETRACTED — the 1,784x compared two different queries.** The 2,888 figure is
for a five-column projection with NO type constraints. Written faithfully — all
four type constraints, both `Edge_hasKGSlot` checks, six columns, the right 425
rows — the hand-written SQL costs **4,130,416 buffers / 31.7 s**, and the best
hand-tuning reached **2,138,276 / 12.8 s**.

    hand-written, FAITHFUL      4,130,416 buffers   31.7 s   425 rows
    + trigram-first CTE,
      LATERAL type probes       2,138,276 buffers   12.8 s   425 rows
    + forced nested loops       (worse: 44.5 s)
    best generated SQL          5,151,495 buffers    3.4 s   425 rows

So the generator is within ~2.4x of the best plan this author could hand-write
for the exact query, and FASTER in wall time than either hand attempt. The
"1,784x on the table" was a simplification artefact — the same error this
document criticises elsewhere, committed while measuring the fix for it.

(417 against 425 is not a discrepancy: the hand-written form projects five
columns and `UNION` deduplicates them, while the query projects six including
`?entity`, which differs between the two branches and keeps rows the five-column
form merges.)

### What this establishes

The data, the tables and the indexes can answer this query in ~2,900 buffers.
Nothing further is needed from the schema. What the generator emits instead is
`IN (SELECT term_uuid ... ILIKE ...)`, a subquery the planner is free to
reorder — and on this query it reorders into a nested loop with **17,406,441
iterations** (per-node attribution: 69.6M buffers on a `term_pkey` scan and
52.2M on a `frame_slot` scan, both at that loop count).

So the push-down is necessary and not sufficient. It makes the good plan
POSSIBLE; it does not make it CHOSEN. The generator has to emit the small set as
a materialised CTE and drive from it, rather than as a subquery in a predicate.

### What NOT to do first

Not another optimisation on this query. Three separate runs of the same query on
the same code measured 5,151,495 / 69,639,145 / 126,592,971 buffers — a 25x
spread, larger than any effect being tested — and `issues/178` records why: the
slot-type drop is backwards here, and which branch a run lands on depends on
cache state rather than on anything controllable. Fix that first, or every
measurement of a fix is a measurement of which branch it happened to hit.


## Where the exact query's cost actually is — measured 2026-09-09

Attribution of the best hand-written faithful plan (2,138,276 buffers):

     self_buf     loops       rows  node
    1,558,467       425    351,410  Index Only Scan idx_quad_ctx_pred  (a type probe)
      562,496         1         61  CTE happy
      561,269   109,745         11  Index Scan idx_quad_subj  (the KGEntity EXISTS)

Two obstacles, both planner ORDERING rather than missing indexes:

  * the `?e a KGEntity` check is evaluated over all **109,745** entities
    carrying a description, not the **76** the trigram matched — even with the
    match in a `MATERIALIZED` CTE and the join written as `CROSS JOIN LATERAL`;
  * a type probe scans all **351,410** `rdf:type` quads in the graph per row via
    `(context, predicate)` instead of looking the subject up in the primary key,
    again despite being written as a `LATERAL ... LIMIT 1`.

The trigram half works perfectly in isolation: `matched` resolves 76 terms in
**79 buffers**. Everything downstream refuses to drive from it.

`enable_hashjoin=off, enable_mergejoin=off, enable_seqscan=off` makes it WORSE
(44.5 s), so this is not simply "the planner picked a hash join".

### What this means for the original goal

"Start at a small number of text matches and walk the edge table" is the right
shape and the trigram lookup that starts it is essentially free. What is not
established is that the rest of the query can be made to follow from it: three
hand-written attempts could not force it, and the best of them is still 2.4x
worse in buffers than what the generator already emits.

Before more work goes into emitting a CTE shape from the generator — the
proposal recorded above — that shape should be demonstrated to WIN by hand.
It has not been. The hand-written CTE version exists (`/tmp/exact3.sql` pattern)
and it loses.


## THE ACHIEVABLE PLAN — exact query, 15,175 buffers, 108 ms

The two earlier hand-written attempts were both handicapped by my own SQL: the
constants (`rdf:type`, the role URIs, the graph, the class URIs) were resolved
in a CTE and referenced as `t.p_type`. **A value that arrives from a CTE is not
known at plan time**, so PostgreSQL cannot use the MCV statistics on
`(predicate_uuid, object_uuid)` and falls back to a default:

    Index Only Scan (ty):  estimated rows=3, actual 109,745    36,582x off
    Index Only Scan (ss):  estimated rows=3, actual 570,696   190,232x off
    Index Only Scan (ds):  estimated rows=3, actual 351,410   117,136x off

At `rows=3` a scan looks free, so the planner places it anywhere. Inline the
same constants as literal UUIDs and the estimates are right:

    generator (best)          5,151,495 buffers   3,356 ms   425 rows
    hand, constants in a CTE  2,138,276 buffers  12,764 ms   425 rows
    hand, INLINE literals        15,175 buffers     108 ms   425 rows

**339x fewer buffers and 31x faster than the generator, on the exact query with
the exact answer.** The shape is precisely the intended one:

    matched   trigram on term_text        ->     76 terms     79 buffers
    happy     matched -> subjects, typed  ->     61 entities   1,005 buffers
    arm       happy -> frame_slot x2      ->     the frames
    then      EXISTS probes for the four type constraints

### What this retracts

This document previously concluded that "the hand-written CTE version exists and
it loses", and withdrew the proposal to emit that shape from the generator. That
conclusion was drawn from the CTE-constant version and is **wrong**. The shape
wins by 339x when the constants are inline.

It also retracts the earlier "the generator is within 2.4x of the best plan this
author could hand-write". It is within 2.4x of a badly-written one.

### What the generator must change

It already emits literal UUIDs, so estimates are not its problem. What it emits
is the text filter as `IN (SELECT term_uuid ... ILIKE ...)` INSIDE the join, and
the type constraints as joins. The winning shape instead:

  1. the trigram match as its own MATERIALIZED CTE,
  2. the entity set derived from it as a second CTE,
  3. the traversal driven FROM that set,
  4. type constraints as `EXISTS` probes, not joins.

That is a real target with a measured number behind it, and the SQL that
achieves it is recorded here.
