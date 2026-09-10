# The Happy-Frame CONSTRUCT Loses Half Its Triples And Spends 58s In Generation

## Status: defect 1 FIXED 2026-09-09 (projection guard, pinned by tests).
## Defect 2 BOUNDED at 2s — 58,035ms -> 3,206ms cold — but the precompute layer
## built on top of it was REVERTED as premature; see below. The REAL remaining
## cost is neither: a null-tolerant join predicate from a UNION-bound variable
## that defeats index joins and LIMIT push-down, measured at 1.7M buffers to
## return 10 rows. Carries FOUR retractions, all measured away.

**Raised:** 2026-09-08, running the reference query in
`vitalgraph_sparql_sql_dev/sql_reference/happy_frame_query.sparql` against
space `wordnet_frames`, graph `<urn:wordnet_frames>`.

**Provenance:** the local DEV service on `:8001` — container `vitalgraph-app`,
image `vital-graph-vitalgraph`, sidecar `vitalgraph-sparql-compiler` on `:7070`.
Not the test stack on `:8002`. Everything below is read out of
`docker logs vitalgraph-app` for 2026-09-09 01:54:57–01:59:05, so the timings
are the server's own, not the client's.

**Related:** issues/096 (a rewrite that orders by a variable it never projects —
the same shape as defect 1), issues/048 (the `frame_entity` collapse this query
triggers), issues/060 (`edge_type_uuid`, the precedent for denormalising a
column a rewrite needs), `vitalgraph/db/sparql_sql/rewrite_frame_entity_table.py`,
`vitalgraph/db/sparql_sql/rewrite_edge_table.py`,
`vitalgraph/db/sparql_sql/generator.py:1441`

## Defect 1 — the CONSTRUCT emits 3 of its 6 template triples

The template has six triples. Ten rows came back. The result carries **30
triples, not 60**. Every one of the ten blank nodes has exactly:

    urn:hasEntity
    urn:hasFrame
    urn:hasDestinationSlotEntity

and is missing `urn:hasSourceSlot`, `urn:hasDestinationSlot` and
`urn:hasSourceSlotEntity`. Per SPARQL §16.2 a template triple with an unbound
position is skipped, so those three variables arrived from SQL as NULL.

They should not be. The inner `SELECT` projects all six, and the patterns
*outside* the UNION bind `?sourceSlot`, `?destinationSlot` and
`?sourceSlotEntity` unconditionally for both branches. On every returned row
`hasDestinationSlotEntity` equals `hasEntity`, which is what the second UNION
branch's `BIND(?destinationSlotEntity AS ?entity)` produces — so the surviving
slot-entity binding is the alias, not a value read back from the slot
traversal. The traversal contributed no variables at all.

`construct.py` is not at fault. `instantiate_construct` implements §16.2
correctly and already logs `CONSTRUCT: skipped N template triple(s) with
unbound positions`; that log line is the fastest confirmation of the count
above.

### Why the rewrite is the leading suspect

`rewrite_frame_entity_table` describes itself as detecting "groups of 6 tables
(2 edge + 2 slot_type + 2 slot_value) that form a frame traversal pattern" and
replacing each group "with a single frame_entity table lookup". That is exactly
the six-pattern group this query writes.

The table it rewrites to cannot express what the query projects:

    CREATE TABLE {space}_frame_entity (
        frame_uuid           UUID NOT NULL,
        source_entity_uuid   UUID,
        dest_entity_uuid     UUID,
        context_uuid         UUID NOT NULL,
        frame_type_uuid      UUID,
        PRIMARY KEY (frame_uuid, context_uuid)
    )

There is **no slot column**. The collapse goes frame → (source entity, dest
entity) and discards the slot nodes, so `?sourceSlot` and `?destinationSlot`
are structurally unavailable after the rewrite — the identical situation
issues/096 recorded for the semi-join, where the optimisation "must project the
value a semi-join collapses".

`?sourceSlotEntity` is the one that does not fit that explanation: it
corresponds to `source_entity_uuid`, which the table *does* carry, so a rewrite
that bound its outputs to the query's variables would have filled it. That it
is NULL suggests the collapse binds only what the join needs and not what the
projection needs.

Neither `rewrite_edge_table.py` nor `rewrite_frame_entity_table.py` mentions
projected, needed, or referenced variables anywhere. Neither asks whether a
variable it is about to collapse is still read downstream.

`joins: 2` in 29,872 characters of SQL is consistent with the collapse having
happened, and the log confirms both rewrites fired on this query rather than
leaving it alone:

    01:54:58.001  rewrite_edge_table: var_slots co-ref ?sourceEdge: q6(src) + q7(dst)
    01:54:58.002  rewrite_edge_table: var_slots co-ref ?destinationEdge: q12(src) + q13(dst)
    01:54:58.002  Edge table rewrite: found 2 edge pair(s) to replace
    01:55:55.893  frame_entity: slot type ...#KGEntitySlot excludes nothing in
                  wordnet_frames - dropped rather than checked per row (issues/048)

`?sourceEdge` and `?destinationEdge` are named there as collapsed pairs. Neither
is projected by this template, so their collapse is harmless; the four variables
that ARE projected through the same groups are what needs checking.

### CONFIRMED 2026-09-08 — the generator declares four variables, not six

Reproduced outside the server with `test_scripts/debug/_issue178_varmap.py`,
which drives the server's own path (sidecar compile -> `generate_sql`) against
the same space. It produces **byte-identical SQL, 29,872 chars**, so this is the
same generation, not a lookalike.

    sparql_vars: ['destinationSlotEntity', 'entity', 'frame', 'sourceSlotEntity']

**Four names for a six-variable projection.** `?sourceSlot` and
`?destinationSlot` are not in the result variables at all — not NULL, not
present-and-empty, absent. The inner `SELECT` names them; the generator's output
does not carry them.

Those two are exactly the ones `{space}_frame_entity` has no column for. The
collapse is the cause, as suspected, and this is no longer an inference.

**This particular symptom is specific to the CONSTRUCT form.** Run as a plain
`SELECT`, the same patterns give all six names in `sparql_vars` — and still
return the two slots as NULL on all 425 rows. So `sparql_vars` losing them is a
second-order effect of the CONSTRUCT's subquery wrapping, not the defect itself.
The defect that holds in both forms is the one below: the variable loses its
positions and is emitted as a literal NULL.

They are not missing from `var_map` — they are mapped, and then NULLed:

    var_map: {'v9': 'entity',            'v11': 'frame',
              'v10': 'sourceSlotEntity', 'v8':  'destinationSlotEntity',
              'v14': 'sourceSlot',       'v15': 'destinationSlot',
              'v6':  'description1',     'v7':  'description2'}

and in the generated SQL's outer projection:

    NULL AS v14, NULL AS v14__type, NULL::uuid AS v14__uuid, ...
    NULL AS v15, NULL AS v15__type, NULL::uuid AS v15__uuid, ...

`v14` is `?sourceSlot` and `v15` is `?destinationSlot`. The generator knows their
names, assigns them ids, and then emits a literal NULL for each.

That NULL is `SqlTypeGenerator.null_companions`, whose docstring reads "Rule 5:
NULL companions for **out-of-scope** variables (§10.5) ... Used by UNION
padding". So the generator did not lose these by accident — it concluded they
were out of scope and padded them, correctly, for a scope it had computed
wrongly.

This is the shape of the whole defect: **every layer behaved correctly on a
premise established one layer earlier.** `null_companions` pads an out-of-scope
variable; `instantiate_construct` skips a template triple with an unbound
position (§16.2); both are right. The error is upstream of both, where a
variable bound by the shared BGP *after* the UNION was judged out of scope.

Accounting for all six, which now matches the observed 30 triples exactly:

| template variable | fate | triple emitted |
|---|---|---|
| `?entity` | projected | yes |
| `?frame` | projected | yes |
| `?destinationSlotEntity` | projected | yes |
| `?sourceSlotEntity` | projected as a real column (`p0.v10`), yet NULL on every returned row | no |
| `?sourceSlot` | mapped as `v14`, emitted as literal `NULL`, absent from `sparql_vars` | no |
| `?destinationSlot` | mapped as `v15`, emitted as literal `NULL`, absent from `sparql_vars` | no |

Three emitted x 10 rows = the 30 triples returned instead of 60.

**RETRACTED — `?sourceSlotEntity` is not caused by the rewrite.** This issue
previously suspected the NULL-tolerant join predicate
(`ON (j0.v10__uuid IS NULL OR ...)`) of admitting rows the BGP would not, and
called it a possible wrong-rows bug. Measured, it is neither: the NULL counts for
that variable are **identical with the rewrite on and off** (see below). Reading
a suspicious join predicate out of generated SQL was not evidence, and the A/B
took one run to settle what the reading could not.

Table references in the generated SQL: `frame_entity` x1, `edge` x2, `rdf_quad`
x7.

### The line that drops them — `rewrite_frame_entity_table.py:570`

The scope model is not wrong. `compute_scope` for a BGP returns
`defined = plan.var_slots.keys()`, so once a variable is gone from `var_slots`
every downstream consumer — scope, projection, `sparql_vars`, `null_companions`
— correctly concludes it is unbound. The variable is deleted from the plan
before any of them see it:

```python
# rewrite_frame_entity_table.py:570
plan.var_slots = {k: v for k, v in plan.var_slots.items() if v.positions}
```

A variable each of whose positions maps into `frame_entity` at a column that
does not exist (`col_map.get(col_name) is None`) has every position dropped,
ends with `positions == []`, and is filtered out here.

There **is** a guard immediately above it, and it does not cover this case:

```python
if lost_to_fe and any(ref not in alias_map for ref, _ in new_positions):
    broken.append(_var_name)
```

For `?sourceSlot` every position is in `alias_map` and every one maps to `None`,
so `new_positions` is empty and `any(...)` over an empty list is False. The
variable is not `broken`; it is dropped in silence.

That guard exists for issues/051 — a variable that loses its tie to the frame
*while still being bound by a surviving table*, which "reads as a cross
product". So the rewrite already knows dropping a variable can be unsafe, and
declines when the consequence is **wrong rows**. It has no equivalent check for
the consequence being **a missing output**, because at that point nothing in the
rewrite knows which variables are projected.

The fix is the projection guard both rewrites lack: before pruning, decline (or
keep the slot join) when a variable about to lose all its positions is named in
the projection. The information is available — `plan.project_vars` upstream,
`gen.sparql_vars` downstream — it is simply not consulted here.

### ROW CORRECTNESS: CLEARED, measured 2026-09-09

`test_scripts/debug/_issue178_rowset.py` runs the reference query's inner SELECT
through the same generator twice — as shipped, and with
`rewrite_frame_entity_table` and `rewrite_edge_table` patched to identity — with
no LIMIT, and diffs the full result sets.

    shipped: 425 rows | SQL 29,814 chars | frame_entity x1, edge x2, rdf_quad x7
    plain:   425 rows | SQL 39,018 chars | frame_entity x0, edge x0, rdf_quad x17

    DIFF on the four columns both bind
    (entity, frame, sourceSlotEntity, destinationSlotEntity):
      shipped only : 0
      plain only   : 0
      in both      : 425

**The collapse does not change which rows match.** Identical sets, not merely
identical counts. 425 is also the number issues/051 recorded for this shape with
the rewrite both on and off, from independent work a month earlier.

So defect 1 is a **missing-output** bug, not a wrong-answers bug. That is a
material downgrade from what this issue first claimed, and it is the difference
between "ship it and fix the projection" and "stop the release".

NULL counts per variable, over the same 425 rows:

| variable | rewrite ON | rewrite OFF |
|---|---|---|
| `entity` | 0 | 0 |
| `frame` | 0 | 0 |
| `sourceSlot` | **425** | **0** |
| `destinationSlot` | **425** | **0** |
| `sourceSlotEntity` | 212 | 212 |
| `destinationSlotEntity` | 213 | 213 |

The two slot variables go from fully bound to fully NULL, and *only* they. That
is defect 1, isolated: caused by the rewrite, nothing else is.

### A separate question this turned up — NOT part of defect 1

`sourceSlotEntity` is NULL on 212 rows and `destinationSlotEntity` on 213, and
212 + 213 = 425 — exactly one of the pair is bound per row. **Identical with the
rewrite off**, so the collapse does not cause it.

That is the UNION binding each branch's own entity variable and nothing else.
But the query's shared BGP, which runs *after* the UNION, contains

    ?sourceSlot      <hasEntitySlotValue> ?sourceSlotEntity .
    ?destinationSlot <hasEntitySlotValue> ?destinationSlotEntity .

and those bind both variables on every solution, so a row with either one
unbound should not exist. Either this is a compiler/plan defect older and wider
than this issue, or the reference query means something other than it reads.
Not investigated here, deliberately — it is a different mechanism from the
rewrite, and folding it in would blur an issue that is now precisely scoped.
Worth its own issue once someone confirms which of the two it is.

### On the performance of the collapse here

    run 1 (cold): shipped 29,369 ms | plain  7,262 ms
    run 2 (warm): shipped  4,930 ms | plain  5,810 ms

The first pair is cache-confounded — shipped ran first and paid for warming what
plain then reused — so it should not be read as a 4x regression. The warm pair is
the fair one, and on it the collapse is roughly neutral. Neither resembles the
**25x** issues/051 measured for the happy frame union, but that was a different
query shape (no slot type constraints, no edge type constraint), so this is not
evidence of a regression against it. Recorded only so nobody re-derives the cold
numbers and reports a regression that is not there.

### Why this is the serious half

The row count is not trustworthy either. If the slot joins are not in the
generated SQL, the ten rows are not the ten rows the query asks for — a
`frame_entity` lookup answers "is this frame connected to this entity", which
is a weaker condition than "via a slot of type `urn:hasSourceEntity` carrying
this value". The query returns fewer triples than it should *and* possibly rows
it should not. Silently, with HTTP 200.

`PRIMARY KEY (frame_uuid, context_uuid)` is one row per frame per graph. Whether
a frame with several source or destination slots can be represented at all is
an open question, not a claim — but it is the first thing to check, because if
it cannot, the collapse is lossy for every multi-slot frame.

## The fix for defect 1 — landed 2026-09-09

A projection guard in `rewrite_frame_entity_table`, immediately before the prune
at the (now shifted) `var_slots` line:

```python
emptied = sorted(had_positions - {k for k, v in plan.var_slots.items()
                                  if v.positions})
if emptied and (needed_vars is None or any(v in needed_vars for v in emptied)):
    FE.decline("the collapse would empty a variable the query still reads ...")
    return original_plan
```

`needed_vars` comes from `_needed_vars(root)`, computed once at the top-level
call and threaded down through the recursion, so **no call site changed**. It
collects every `project_vars` in the tree plus every variable named in any
expression, and returns `None` — meaning "assume everything is read" — when it
meets a `SELECT *`, which makes the caller decline.

**Declining cannot regress a query that was correct.** Any query this refuses is
one whose slot variables the collapse would have emptied — that is, one
returning NULL columns today. The optimisation is preserved exactly where it was
already sound.

### Verified on the real query, same probe as the diagnosis

    before:  frame_entity x1 | sourceSlot 425/425 NULL | destinationSlot 425/425 NULL
    after:   frame_entity x0 | sourceSlot     0 NULL   | destinationSlot     0 NULL

             425 rows both ways, and now all SIX columns match the
             rewrites-disabled ground truth exactly:
             shipped only 0 | plain only 0 | in both 425

In the CONSTRUCT form `sparql_vars` goes from four names back to six, and the
generated SQL no longer contains `NULL AS v13` / `NULL AS v16`.

### Tests

`tests/unit/sparql_sql/test_rewrite_tables.py::TestRewriteFrameEntityProjectionGuard`
— four cases, and two of them exist to catch the *opposite* failure:

  * declines when a slot variable is projected;
  * declines for `SELECT *`;
  * **still collapses** when the slots are walked but not read — the
    FRAME_UNION / RELATIONSHIPS shape issues/051 measured at 25x, which a
    blunt always-decline guard would have destroyed silently;
  * still drops an emptied variable that nothing reads.

Verified to FAIL with the guard disabled: the two decline cases fail, the two
preservation cases pass either way, which is what they are for. A check that
cannot fail is not a check.

Existing coverage kept green: 32 in `test_rewrite_tables.py`, 31 in
`tests/integration/test_frame_entity_collapse.py` — the latter being the guard
on the issues/048 collapse win.

## RETRACTED — `rewrite_edge_table` does NOT have this defect

An earlier revision of this issue recorded, as an open follow-up, that
`rewrite_edge_table` "has the identical defect" and needed the same guard. That
was **wrong**, and it was wrong for an embarrassing reason: it rested on grepping
`NULL AS v12` out of the generated SQL without reading the next column along.

The full projection for `?sourceEdge` is:

    NULL AS v12, NULL AS v12__type, sub.v12__uuid AS v12__uuid, ...
                                    ^^^^^^^^^^^^^ bound

Only the **text** is NULL. The `__uuid` is a real column, so the variable is
bound. That is `deferred_text_companions` — "a variable that is bound but whose
text was not materialised" — and not `null_companions`, whose docstring says in
as many words that it "means the variable is **unbound** — every companion
including `__uuid` is NULL". The two cases are one grep apart and mean opposite
things. The genuine defect looked like this:

    NULL AS v14, NULL::uuid AS v14__uuid     <- unbound, the real bug
    NULL AS v12, sub.v12__uuid AS v12__uuid  <- bound, text deferred

In the post-fix CONSTRUCT SQL, none of `v12`/`v13`/`v15`/`v16` has a NULL uuid.

### Measured

`test_scripts/debug/_issue178_edgevar.py` projects `?sourceEdge` — the case the
reference CONSTRUCT never exercises — and runs it with the edge rewrite on and
off:

    shipped: edge x1, rdf_quad x1 | 200 rows | sourceEdge NULLs: 0
    plain:   edge x0, rdf_quad x3 | 200 rows | sourceEdge NULLs: 0
    DIFF: shipped only 0 | plain only 0 | in both 200

The rewrite fires, the projected edge variable survives, the rows are identical.

### Why it is structurally safe, not merely safe here

`{space}_edge` HAS the column, and the rewrite uses it:

    alias_map[src_alias] = (edge_alias, {
        "subject_uuid":   "edge_uuid",        # <- ?sourceEdge lands here
        "object_uuid":    "source_node_uuid",
        "predicate_uuid": None,               # <- the only None
        "context_uuid":   "context_uuid",
    })

`predicate_uuid` is the sole mapping to `None`, i.e. the only position that can
be emptied. A quad is classified into `src_quads`/`dst_quads` only by matching
`qN.predicate_uuid = __CONST_x__` against `hasEdgeSource`/`hasEdgeDestination`,
so its predicate is a **constant** by construction — a variable can never occupy
that position on a quad this rewrite touches.

So `rewrite_edge_table` cannot empty a variable, and needs no guard. That is the
difference from `frame_entity`, which has no slot column at all and therefore
maps a real, variable-occupied position to `None`.

**No fix is required here, and adding the guard would be dead code.** The
follow-up pointer this section previously carried — lift `_needed_vars` to a
shared module and thread it through `rewrite_edge_table` — is withdrawn with it.

The lesson worth keeping: the A/B was demanded before writing the guard
precisely because the mechanism was unproven, and it is what stopped a fix being
written for a bug that does not exist. `frame_entity` was proven by the column
not existing; that argument was never available here, and the symptom alone
looked identical.

## Defect 2 — 57.8s of the 69s is one tautology check

    gen_ms:      58035.12   (84%)
    exec_ms:     10799.00   (16%)
    sidecar_ms:    292.28
    acquire_ms:      5.20
    total_ms:    69140.78
    rows: 10   joins: 2   sql_chars: 29872

The server log brackets the cost to a single call. Generation ran
01:54:57.95 → 01:55:55.98, and inside it:

    01:54:58.010  slot-type tautology: wordnet_frames ...#Edge_hasKGSlot -> ...
                  <- 57.785 s, no log line from this query
    01:55:55.795  slot-type tautology: wordnet_frames ...#KGEntitySlot
                  over ['urn:hasDestinationEntity', 'urn:hasSourceEntity']
                  -> excludes nothing (0 counterexample(s))

`excludes_nothing` in `slot_type_tautology.py`, for `KGEntitySlot`, took
**57.785 s**. That is 84% of the query and 99.6% of generation.

### Why this query and not the other two

This is the only one of the three that types its slots — `?sourceSlot a
haley-ai-kg:KGEntitySlot`. The other two never mention a slot type, so the check
is never reached. Their generation was 591 ms and 214 ms.

### Why the expensive answer is the one the optimisation wants

The anti-join carries `LIMIT 1`, so it stops at the first role slot lacking the
type. That short-circuit only fires when the verdict is **EXCLUDES**. To return
`excludes nothing` it must prove a negative over every role slot in the space —
a full scan, by construction. The cheap outcome is the one that disables the
optimisation; the outcome worth having is the one that costs 58 s to reach.

The module's docstring prices the win at 7.4x (627,418 buffers to 84,573) and
argues at length that the question must be a query and not an argument. Both
hold. What is unpriced is the cost of *asking* on a space where the answer is
yes, which here exceeded the entire rest of the query by 5x.

### It is cached, and the cache is per process

Re-run of the byte-identical query, same process, 3 minutes later:

    01:59:04.929  acquire=0ms sidecar=4ms gen=159ms exec=1811ms total=1979ms
                  (10 rows, 2 joins, 29872 chars SQL)

**gen 58,035 ms -> 159 ms, a 365x drop**, same SQL to the character. So the cost
is once per process per `(space_id, type_uri, roles, type_predicate)` — and
`_CACHE` is a module-level dict, so every restart, deploy and additional worker
process pays it again, and pays it inside a user's query.

Reproduced from outside the server, in three separate cold processes:

| run | cold generation | 2nd call, same process |
|---|---|---|
| server, 01:55 | 58,035 ms | 159 ms |
| probe, run 1 | 25,774 ms | 23 ms |
| probe, run 2 | 3,888 ms | 21 ms |

The warm number is stable at ~20-160 ms; **the cold number is not** — it falls
58s -> 26s -> 3.9s across successive cold processes. The in-process `_CACHE`
cannot explain that, because each of these had an empty one. What is warming is
PostgreSQL's buffer cache for the anti-join's scan.

Two things follow. The in-process cache is real and worth ~1,000x. And the
58 s is the **cold-buffer** cost, not a fixed cost — which means the figure that
matters for production is the worst one here, not the best: a restarted process
on a box whose buffers hold something else. That is precisely the state after a
deploy.

The cache key includes the `rdf_pred_stats` row count for freshness, which is
sound but means any write that changes the slot-type predicate's size re-arms
the 58 s.

### RETRACTED: the cold-build hypothesis

This issue first attributed the 58 s to `ensure_edge_table` /
`ensure_frame_entity_table` populating derived tables inside the generation
window at `generator.py:1441`. That is **wrong**, and the log says so plainly:
there is no populate line for `wordnet_frames` anywhere in it. Those functions
do run a startup sweep across all 40 spaces at 01:39, and they do populate on
first access for other spaces — but not here, and not in this window.

The reasoning was sound and the conclusion was false: a per-process memoized
build inside a read path is a real pattern in this file, it does explain a large
one-time cost, and it was not the one that happened. Recorded because the same
inference is available to anyone reading `generator.py:1441` and seeing a slow
first query.

### Also worth noting

`exec_ms` fell 10,799 ms -> 1,811 ms between the two runs, which is buffer cache
and not attributable to any fix. A ~1.8 s execution for `LIMIT 10` remains
unexplained and is a smaller question hiding behind this one.

## The fix for defect 2 — landed 2026-09-09 (option 1 of 3)

The anti-join is now bounded. `TAUTOLOGY_TIMEOUT_MS = 2000` in
`slot_type_tautology.py`; on expiry `excludes_nothing` returns `None`, which the
function already documents as "keep the check" — the safe direction, since the
whole risk is dropping a constraint that does exclude something. Answers stay
correct; the query is merely slower than it would have been.

Two details the fix depends on, both of them mistakes that were available here:

**Plain `SET` with save/restore, not `SET LOCAL`.** `create_transaction()` can
hand us a connection with a transaction already open, asyncpg nests ours as a
savepoint, and `SET LOCAL` survives the savepoint RELEASE to the end of the
OUTER transaction — silently imposing a 2s statement timeout on the caller's
remaining statements. This is the reasoning `bounded_lock_wait` already carries
in the same codebase, reused rather than rediscovered.

**A transaction wrapper, because a statement_timeout ABORTS the transaction.**
It is enforced server-side. Without a savepoint to roll back to, every later
statement on that connection fails with `InFailedSQLTransactionError` — a bound
that trades a slow query for a broken connection. That is `issues/177` exactly,
reached from the other direction: there a `lock_timeout` made a fallback
unable to fall back.

**The give-up verdict is cached.** Not caching it would re-pay the full 2s on
every query of this shape for the life of the process, which is a worse trade
than losing the 7.4x — the check is an optimisation input, the timeout is not.
It is re-evaluated when the predicate's row count changes or the process
restarts, and it logs a WARNING naming the precompute as the way to get the
optimisation back.

### Tests

`tests/integration/test_slot_type_tautology_is_bounded.py` — four cases:

  * a statement_timeout aborts the transaction (the PostgreSQL property the
    savepoint exists for — if it were false the wrapper would be unnecessary);
  * a 1ms budget leaves the connection USABLE and returns `None`;
  * `statement_timeout` is restored, so it cannot leak to the next user of a
    pooled connection;
  * the give-up verdict is cached rather than re-paid.

Verified to FAIL with the bound removed: cases 2 and 4 fail. Cases 1 and 3 pass
either way by construction — one pins a PostgreSQL fact, the other a restore
path that runs on both branches.

They also **skip rather than pass** when `wordnet_frames` is absent or empty.
The first version did not, and would have passed on an empty database for the
wrong reason: a missing table raises, the same `except` swallows it, and the
function returns `None` — indistinguishable from a successful timeout.

### THE RETRACTION BELOW IS ITSELF WRONG — corrected 2026-09-09

The section that follows claims the slot-type optimisation is backwards on this
query, on the strength of a 13.5x gap between a run with the verdict pinned and
one without. **That was not a controlled comparison** — the two runs were
different processes with different cache states, and the pinning was incidental.

Forcing the verdict each way inside ONE process, three runs each, says the
opposite and says it stably:

    verdict DROPS the constraint     5,722,181 buffers    3.4-3.7 s   0 semi-join nodes
    verdict KEEPS it (expired)     126,593,820 buffers   41-42 s     14 semi-join nodes

**The check is correct and worth 22x.** Dropping the redundant slot-type
constraint is exactly what it is for.

### The real defect was the BUDGET, and it was arithmetic

    check cost, warm, terms resolved   1,805 ms
    budget                             2,000 ms

The budget sat ON TOP OF the cost, so the verdict flipped from run to run and
the plan flipped 22x with it. That is why measurements across this whole issue
and `issues/183` disagreed with each other: they were sampling two plans.

Two fixes:

  * **the terms are resolved to uuids before the anti-join.** It joined
    `{space}_term` by `term_text`, which hides the selectivity from the planner
    — it cannot use the statistics on `(predicate_uuid, object_uuid)` for a
    value it does not know. Resolved: 1,805 ms against 2,149 ms, and estimable.
  * **the budget is 15 s, not 2 s** — clear of the cost rather than sitting on
    it.

Measured after: **5,722,183 to 5,722,186 buffers across six runs**, 3.2-3.9 s.
A variance of three buffers where the same query previously ranged from
15,578,409 to 126,593,820.

**A bimodal plan is worse than a consistently slow one.** It cannot be measured,
and several conclusions in this file and in `issues/183` were wrong because of
it. Anything in either document measured before this date should be re-read with
that in mind.

### (superseded) RETRACTED — the optimisation this bound protects is BACKWARDS on this query

Everything above treats the expired verdict as the degraded case: `None` keeps
the slot-type constraint, the constraint costs semi-joins, and the 7.4x the
check exists to win is lost. Measured on the reference CONSTRUCT, same code,
same query, the only difference being whether the verdict was pinned:

    verdict EXPIRES (2 s bound, what production does)    5,151,495 buffers   3,356 ms
    verdict SUCCEEDS (600 s budget, "stable" harness)   69,639,148 buffers  19,729 ms

**13.5x, and the production path is the FAST one.** Dropping the slot-type
constraint — the entire point of the check — makes this query 13.5x worse. The
`excludes nothing` verdict is not a win here; it is the pathology.

### What this invalidates

Every measurement taken with the verdict PINNED measured a plan production does
not take. That includes, in `issues/183`:

  * the type-constraint class bisection (6,032,427 / 914,457 / 908,057 ...),
  * the `frame_entity` vs `frame_slot` comparison and its "6.6x gap",
  * the collapse-on/off comparison,

and both fixes built on them — the edge-type absorption that timed out and the
frame-type absorption that gained 2% — were aimed at costs that only exist in
the branch production avoids.

It also explains the "instability" recorded there. Variant 2 moving 4.5x between
identical runs was not noise: it was the plan flipping between these two
branches as the 2 s budget expired or did not.

Pinning was introduced to make the measurements trustworthy. It made them
consistent and wrong, which is worse — a bimodal measurement at least announces
that something is unstable.

### What follows

The bound is doing something useful for a reason nobody intended: it usually
expires on a cold cache, which usually keeps the constraint, which is usually
faster. That is not a design.

The open question is no longer "how do we make the verdict cheap and stable".
It is **whether `rewrite_frame_entity_table` should drop a slot-type constraint
at all**, and the 7.4x that justifies the whole mechanism needs re-measuring on
the branch production actually takes. Until that is answered, do not build
anything on the pinned numbers, and do not "fix" the bound.

### A defect INTRODUCED by this fix, found and fixed 2026-09-09

Extracting `_anti_join` left the success-path log line referencing `row`, a
local that had moved into the new helper:

```python
logger.info("... -> %s (%d counterexample(s))",
            ..., "excludes nothing" if verdict else "EXCLUDES", row or 0)
                                                               ^^^ NameError
```

So **every successful verdict raised `NameError`** — and the caller in
`generator.py` wraps the call in a blanket `except Exception`, which swallowed
it and silently disabled the optimisation the whole check exists to enable. The
failure mode was invisible: correct answers, no error surfaced, just a
constraint that was never dropped.

**Why the four tests missed it.** All four force a TIMEOUT to exercise the
bound, so all four take the early `return None` and none of them ever reached
the line after it. The success path had no test at all. It was found by a probe
script that happened to pin the verdict with a long budget.

**The first attempt at a regression test also missed it**, for the same reason:
it called `excludes_nothing` with the default 2 s budget, the anti-join expired
on a cold cache, and it took the same early return. It passed with the bug
deliberately reintroduced. The test now sets a 600 s budget so the verdict
actually computes, and was verified to FAIL with the bug back and pass with it
fixed.

That is twice in one issue that a test for this module could not reach the code
it claimed to cover, both times because the interesting path is the expensive
one. The rule the `issues/177` writeup states — a check that cannot fail is not
a check — needs a corollary here: **a test whose setup makes the code take a
different branch is not testing the branch it names.**

### A side effect of the bound, found 2026-09-09 and NOT yet addressed

The bound makes the QUERY PLAN depend on buffer warmth.

`excludes_nothing` returning `True` lets `rewrite_frame_entity_table` DROP the
slot-type constraint; returning `None` makes it KEEP it. Those are different
plans with materially different costs. With a 2 s budget and no precomputed
verdict, which one a query gets depends on whether the anti-join happened to
finish — i.e. on what else has been through the buffer cache recently.

Observed while bisecting `issues/182`: the same CONSTRUCT that had measured
17,137 ms on one run exceeded a 300 s statement timeout on another, with no code
change between them. The difference was the verdict.

This is not a correctness problem — `None` keeps the check, which is the safe
direction, and every plan returns the same rows. It is a PREDICTABILITY problem,
and arguably a worse one than the 58 s it replaced: a fixed cost can be measured
and planned around, while a bimodal one cannot. Any benchmark of this shape is
now measuring the verdict as much as the query.

**Priced 2026-09-09, and it is the largest single factor in the query.** When
the verdict expires, the slot-type constraint is kept and emitted as a
role-scoped semi-join back through the edge. Per-node attribution of a run where
it expired:

    1,712,352  loops=428,085   st_edgechk1     <- the kept check
    1,712,168  loops=428,038   ty_slotchk...
    1,712,164  loops=428,038   st_slotchk...
    1,284,112  loops=285,348   e_edgechk1
    ... eight such nodes, ~12.4M of the run's 16,456,400 buffers

The same query with the verdict computed measures 5,623,363. **A 2.9x swing on
whether a 2 s budget happened to be enough.**

It also invalidated a measurement in `issues/182`: an "unexplained" 10%-instead-
of-6.8x result for edge-type absorption turned out to be a run where the verdict
expired compared against a baseline where it was pinned. Nothing was wrong with
the absorption; the comparison was between two different plans.

**Nothing in this family can be benchmarked until the verdict is deterministic.**
Every measurement must pin it first, and the fix — whatever form it takes —
has to make the verdict stable, not merely cheap.

The precompute that would remove it was built and reverted (above). Whatever
replaces it should make the verdict deterministic, not merely fast. Until then,
measurements of frame queries on a cold space should pin the verdict explicitly
before timing anything.

### What this does NOT do, and why the rest was REVERTED

The bound stops the bleeding — 58,035 ms cold becomes 3,206 ms — but it LOSES
the 7.4x rather than earning it: after a deploy the first query of this shape
gives up on the optimisation instead of waiting a minute for it.

A precompute-and-persist layer was built to recover that (a `slot_type_tautology`
table, a maintenance step, a migration) and then **reverted the same day**. It
worked — cold generation 527 ms with the optimisation kept — and it was still
the wrong thing to build. It committed a stored schema, keyed on the
source/destination role pair, to a decision that only matters because of how one
rewrite happens to be structured. Persisting a verdict is a heavier commitment
than caching one, and it was made before establishing that this decision is
where the time actually goes. It is not.

Where the time actually goes is below.

## DECLINED — dropping `?e a KGEntity` on slot values

Raised during review: a `KGEntitySlot` points by definition to a `KGEntity` (or
a subclass), so `?e a KGEntity` on a slot value excludes nothing and the pattern
could be dropped, removing a join. The premise checks out on this space and the
optimisation is still not worth building.

**The premise is true here.** Every `KGEntitySlot` value in `wordnet_frames` —
219,490 type triples over 109,745 distinct values — carries type `KGEntity`
exactly. No subclasses, no exceptions, and the same answer whether or not the
slot is a source/destination one.

**The win is noise.** Same query with and without the two type patterns, three
alternating rounds:

    with     rows=425  rdf_quad refs=5  ms=[1340, 1363, 1266]  median 1340
    without  rows=425  rdf_quad refs=3  ms=[1414, 1319, 1084]  median 1319

The joins are genuinely removed — 5 refs to 3 — for **21 ms on 1,300 ms, 1.6%**,
with the ranges overlapping almost entirely.

**Why the analogy that motivated it was wrong.** The 7.4x this issue quotes
elsewhere is the SLOT-type check, evaluated per surviving `frame_entity` row
inside the collapse. The entity-type constraint sits after
`CONTAINS(..., "happy")` has already cut the candidates to a few hundred, so the
same-looking join runs a few hundred times instead of hundreds of thousands.
Position in the plan, not pattern count, is what made the other one worth 7.4x.
"A join is removed" describes a mechanism; it is not evidence of a win.

**And the ontology could not have licensed it anyway.** "Points to a `KGEntity`
or a subclass" and "`a KGEntity` excludes nothing" are different claims. This
store matches SPARQL without RDFS entailment, so an entity typed ONLY as a
subclass does not match `?e a KGEntity` — the constraint would be excluding
something real, and dropping it would add rows. The two coincide only when the
store also asserts the superclass type, which is a fact about the data. That is
the same trap `issues/048` fell into twice, and the reason the check is a query
per space rather than an argument.

## The cost of the projection guard — measured 2026-09-09

The guard fixes the missing triples by making `rewrite_frame_entity_table`
DECLINE whenever a slot variable is projected. That means this query no longer
uses the traversal table at all, which is worth asking about.

Priced by running the reference CONSTRUCT with and without the slot variables in
its projection — the second permits the collapse:

    projects slots (what ships)   10,075 ms   15,736,125 buffers   frame_entity=0  rdf_quad=13
    slots NOT projected            5,279 ms   16,170,210 buffers   frame_entity=1  rdf_quad=11

**The collapse is worth 1.9x on time here, and slightly MORE buffers.** Not the
four orders of magnitude `issues/048` measures for it at depth 3 — this is one
hop with a selective text filter, where the join reduction has much less to
work with.

So the guard costs about half the query's speed for this shape, and buys correct
output. That is the right trade at 1.9x. It would be a much harder call at 100x,
which is worth knowing before anyone widens the guard to other rewrites.

### The fix that would remove the trade entirely

`frame_entity` cannot bind `?sourceSlot` because it has no column for it — but
the SYNC already has the value in hand and discards it. In
`sync_frame_entity_table.py` the slot node IS `emv.dest_node_uuid`, joined on
twice (once for the slot type `st`, once for the slot value `sv`):

```sql
FROM {t_edge} emv
JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid AND st.predicate_uuid = $1
JOIN {t_quad} sv ON sv.subject_uuid = emv.dest_node_uuid AND sv.predicate_uuid = $2
```

Two more columns, built by the same `array_agg(...) FILTER (...)` pattern the
entity columns already use:

```sql
(array_agg(emv.dest_node_uuid) FILTER (WHERE st.object_uuid = $3))[1] AS source_slot_uuid,
(array_agg(emv.dest_node_uuid) FILTER (WHERE st.object_uuid = $4))[1] AS dest_slot_uuid,
```

The rewrite could then map the slot variables instead of emptying them, the
guard would stop declining, and the query would get both correct output and the
collapse.

**DONE 2026-09-09**, once `issues/182` showed the 1.9x was measured in
isolation and the real value is in combination (1,218x with the other two).

`source_slot_uuid` / `dest_slot_uuid` added to the schema, populated by all
three `sync_frame_entity_table` insert sites from `emv.dest_node_uuid`, mapped
by the rewrite in place of the six `None`s that used to empty the slot
variables, and migrated by `scripts/migrate_frame_entity_slot_columns.py`
(285,348 rows on `wordnet_frames`, both columns fully populated).

**The trade is gone.** The reference CONSTRUCT now uses the collapse WHILE
projecting the slots — `frame_entity x1`, where it was `x0` — and the output is
verified against the rewrites-disabled ground truth: 425 rows, zero diff on all
six columns, slot NULL counts 0.

    projects slots, before   10,796 ms   15,736,125 buffers   frame_entity=0
    projects slots, after     8,325 ms   16,456,401 buffers   frame_entity=1

On its own that is a time improvement and a slight buffer INCREASE, exactly as
the isolated 1.9x predicted. It is worth having because it unblocks the
combination, not for its own number.

### A defect this exposed in the issues/051 guard

Enabling the mapping made the frame-entity rewrite decline EVERY frame pattern
that names a slot:

    frame_entity_rewrite declined: a variable would lose the binding that ties
    it to the frame while still being bound by a surviving table (issues/051)
    [broken=['destinationSlot', 'sourceSlot']]

That check asks `ref not in alias_map`, meaning "bound by a table the collapse
did not absorb". `alias_map` is keyed by the OLD aliases, so a position on the
NEWLY CREATED `frame_entity` alias satisfies it — the guard was reading the
collapse's own output as a surviving table. It never fired before because slot
variables had no surviving positions at all; they were emptied.

Fixed by tracking the aliases this pass creates and excluding them. The guard's
real job — catching a variable still bound by a table that genuinely survives —
is unchanged.

## Where the time actually goes — split out to issues/179 and issues/180

Profiling this query after the bound landed showed that NEITHER defect above is
where the cost lives at steady state. Warm generation is 21 ms; execution is
1,464 ms and 1,738,342 buffers to return 10 rows, and it divides almost exactly
in half:

  * **883,066 buffers** — a `CONTAINS(LCASE(...))` filter that cannot use the
    trigram index built for it. **`issues/179`**, priced at 402x in isolation.
  * **855,245 buffers** — a null-tolerant join from a UNION-bound variable,
    which forces the whole traversal to be materialised and stops `LIMIT` from
    pushing down. 16,172 rows built, 16,162 discarded. **`issues/180`**.

They are separate mechanisms with separate fixes and different reach, which is
why they are separate issues rather than more sections here.

Recorded because this issue reached that conclusion in the wrong order, twice.
It first treated the slot-type tautology as the performance problem and built a
precompute layer for it; then it named the null-tolerant join as "the actual
cost" without checking the buffer distribution, which turned out to be half of
it. Both were real mechanisms, correctly described, and neither was established
as dominant before being acted on. The profile was available the whole time.

## What is not established

- **Whether the slot joins are absent from the generated SQL, or present with
  their outputs unprojected.** `joins: 2` hints at the former; only the SQL and
  `gen.var_map` decide it. This is the difference between "the rewrite is wrong"
  and "the rewrite is right and the projection is lost after it".
- **Whether the rewrite also changes which rows match**, not just which columns
  are bound. Compare against the same query with the rewrites disabled; if the
  row sets differ, defect 1 is a wrong-answers bug and not only a missing-output
  bug.
- **Whether a multi-slot frame survives `PRIMARY KEY (frame_uuid, context_uuid)`.**
- **The `CONSTRUCT: skipped N` log line proves nothing by its absence here.** It
  is `logger.debug` and the container logs at INFO, so it was never going to
  appear. Raise the level before treating a quiet log as evidence.

Settled since first writing, and no longer open: the run order (both other
queries ran BEFORE the CONSTRUCT, at 01:54:17 and 01:54:38, so they are not its
warm follow-ups), and the cold-vs-per-call question for `gen_ms` (per process,
not per call — see the 365x drop above).

## Fixes available for defect 2

Not yet decided between, and they are not exclusive:

1. **Bound the check.** A `statement_timeout` or a row cap on the anti-join, with
   the timeout treated as `None` — which the function already documents as "keep
   the check", the safe direction. Turns an unbounded 58 s into a bounded cost
   that merely declines an optimisation.
2. **Precompute it.** The verdict is a property of the space, not of the query.
   The maintenance cycle already audits `rdf_stats`, and this belongs beside it,
   so no user query ever pays for it.
3. **Persist the cache** rather than holding it in a module-level dict, so a
   restart or a second worker does not re-pay.

(1) is the smallest and stops the bleeding; (2) is the one that makes the
optimisation free at the point of use.

## What this is worth writing down for

**A derived-table rewrite is a projection change, not only a join change.**
issues/096 found it for SORT, this found it for CONSTRUCT, and in both cases the
collapse was correct about connectivity and wrong about what the query wanted to
read back. Two instances make it a class. The guard both rewrites lack is the
same one: before collapsing a group, ask whether any variable being discarded is
still referenced downstream, and decline if so.

**A timing field named for a phase can contain a different phase's work.**
`gen_ms` reads as "planning cost" and contained a 58-second anti-join against
`rdf_quad`. The breakdown was honest about the number and silent about the
meaning; the server log, which was there the whole time, cost one grep and
replaced a plausible wrong answer with the right one.

**An optimisation's price is the cost of the win plus the cost of ASKING.** The
tautology check is well argued, correctly conservative about staleness, and
measured at 7.4x — and it was never measured on a space where proving the
negative requires a full scan, which is precisely the case it exists to detect.
A check whose cheap path is the one that finds a counterexample will be cheap in
every test that has one.

## Where the cost actually goes — corrected, on the reference query

### First, a metric error that affects every buffer figure in this file

Buffer counts here were produced by summing `shared hit=` across all lines of
`EXPLAIN (ANALYZE, BUFFERS)`. **That double-counts**: a parent node's buffer
total already includes its children's. On this plan it inflates by 13x —

    reference query   root node 5,022,432      naive sum 65,473,262

Two runs compared with the same flawed metric still rank correctly, so the
DIRECTIONAL conclusions in this file survive. The absolute magnitudes do not.
In particular the "22x" for the slot-type check above is a summed-buffer ratio;
the wall-clock measurement of the same pairs, 3.4-3.7 s against 41-42 s, puts it
nearer **12x**. The check is still clearly worth keeping — that conclusion rested
on the timings, not the buffers.

Correct figures come from the ROOT node, or equivalently from summing per-node
SELF buffers (parent minus children); on this plan the two agree exactly.

### The reference query, attributed

Root: **5,022,432 buffers, 3.6 s, 10 rows** (`ORDER BY ?entity LIMIT 10`).

    self_buf     loops   node
    1,711,847  427,959   Index Only Scan  rdf_quad_pkey
    1,283,982  285,348   Index Scan       idx_..._edge_type_src
    1,141,394  285,348   Index Scan       term_pkey
      856,136  285,348   Index Only Scan  idx_..._fs_cover
        7,610        3   Parallel Seq Scan  ..._edge e_edgechk1

Four per-row probes are 99.4% of the total. **Every one of them runs 285,348 to
427,959 times to produce 10 rows.** That single fact, not any one node, is the
defect.

An earlier revision of this section claimed 99.7% was term lookups. That was
measured on the query with `ORDER BY`/`LIMIT` stripped, which is a different
plan; on the reference query term lookups are 23%. The conclusion that survives
is the loop count, which is the same either way.

### The traversal is not the problem

`frame_slot` and the trigram anchor are the small lines. The anchor finds its 61
entities in 3 ms. The plan I was about to implement — entering `frame_slot` on
`entity_uuid` rather than `frame_uuid` — targets nodes worth well under 1% here.
It would not have been measurable.

### The obstacle is the row estimate, not the join shape

The undistributed join carries the `issues/180` null-tolerant guards:

    Join Filter: ((j0.v8__uuid IS NULL OR j0.v8__uuid = j1.v15__uuid) AND ...)
    Rows Removed by Join Filter: 34,812,031

An `OR` is not hashable, so this looked like the cause, and
`rewrite_distribute_union` looked like the cure: remove the UNION from under the
join, `info.partial` clears, `_always_bound` drops the guards. That was priced
before at "exactly 2.0000x", but on a bimodal plan and before `_maybe_shared`
existed, so it was retested here.

**The mechanism works and the outcome is still much worse.** Generated SQL goes
from two `IS NULL` guards to zero — the join really does become a plain
equality. And:

    distributed    >120 s (statement timeout), both rounds
    not            3.6-4.1 s

Because the equality is still not usable:

    Nested Loop  (cost=19868.57..100424.81 rows=1)
      Join Filter: (fsmv0.entity_uuid = ..._rdf_quad.subject_uuid)

**`rows=1`, against a reality of 95k-285k.** On a 1-row estimate a nested loop is
the correct choice, so the planner picks 20 of them; distribution then pays that
mistake once per arm. Hashability was necessary and nowhere near sufficient.

So the lever is the planner's cardinality estimate for the anchored arm. Until
the anchor's true selectivity is visible, no rewrite that only changes plan
SHAPE will help — which retrospectively explains why five separate shape
rewrites were tried in this issue and every one was reverted.

## The 100ms target is reachable, and the gap decomposes

A faithful hand-written SQL for this exact query, verified to return the same
425 rows:

    13.7 ms    15,172 buffers    425 rows      hand-written
    3,600 ms    5,022,432 buffers   10 rows    generated

263x on time, 331x on buffers. There is headroom under the 100 ms target, so the
question is only which structural differences carry the gap. Isolated one at a
time, same query, same session:

    distributed + MATERIALIZED fence      13.7 ms   15,172 buf
    distributed, fence REMOVED            14.8 ms   16,836 buf
    UNDISTRIBUTED (the `OR` form)       1332.1 ms   24,213 buf

**The fence is worth nothing** — 14.8 against 13.7 ms. This agrees with the
earlier finding that the CTE hoist was unnecessary (33.3 vs 28.7 ms), and both
supersede any suggestion in this file that an optimisation fence is needed.

**Distribution is worth ~90x — in TIME, not buffers.** 1332 ms against 14.8 ms
for a 1.6x buffer difference. The `OR` form is CPU-bound on 34.8M join-filter
comparisons against fully-cached pages, not I/O-bound. Any tuning driven by
buffer counts alone would have missed this entirely.

That resolves the contradiction with the distributed-generator result above
(>120 s). Distribution is correct AND it made the generated query worse, because
the generated arms still carry the other two defects; distributing a bad plan
pays for it twice. Distribution is necessary and not sufficient.

### What the generator is missing, in measured order

  1. **Distribution over the union.** ~90x, but only once the arms enter
     `frame_slot` on `entity_uuid`.
  2. **Type constraints as `EXISTS` semi-joins.** The generated SQL contains
     `EXISTS` exactly ZERO times — every `?x a <Class>` is an inline join, so
     intermediate rows stay at 285,348 instead of collapsing to 425. The hand
     query applies all six as semi-joins AFTER the traversal narrows.
  3. **Late term materialisation.** Term text is resolved inside the join, five
     lookups at 285,348 loops each. The hand query carries uuids throughout and
     never resolves text at all.

None of these is a change to the traversal, which remains under 1% of the plan.

### Not evidence: the `exact4` comparison

An earlier draft cited `exact4` at 12,379 ms as a 900x datapoint. It is
confounded — `exact4` begins with `SET enable_hashjoin=off; enable_mergejoin=off;
enable_seqscan=off` and the measurement harness strips `SET` lines, so it ran
without the settings it was written to require. Disregard it.

## The plan is already close to the hand-written shape

Dumping the actual BGPs (rather than reasoning from the SPARQL) shows the
traversal has already been collapsed almost all the way:

    BGP #2 — 3 tables
      fsmv0  frame_slot        fsmv0.frame_uuid = q4.subject_uuid, role = SRC
      fsmv1  frame_slot        fsmv1.frame_uuid = q4.subject_uuid, role = DST
      q4     rdf_quad          ?frame a KGFrame

    ?sourceSlotEntity      -> fsmv0.entity_uuid
    ?destinationSlotEntity -> fsmv1.entity_uuid

The `frame_slot` rewrite already folded the six edge/slot patterns into two
rows, and the slot type constraints are already gone. This retires the
`EXISTS`-semi-join plan from the previous section: only `q4` would qualify, so
the rewrite that looked like the enabler is worth almost nothing here. That is
the THIRD change in this issue aimed at a part of the plan that was not the
cost — after the `entity_uuid` entry point and after distribution-alone.

**Check the emitted plan before designing a rewrite for it.** Every wrong turn
in this issue came from reasoning about the SPARQL instead of dumping the BGPs,
which takes one script.

### Why `semijoin.py` cannot fire here, for the record

    if child.kind == KIND_BGP and distinct_seen and key:   # _split_anchors
    if (distinct_node is not None and len(shared) == 1 ...) # _walk

It needs a `DISTINCT`/`REDUCED` ancestor AND a `PROJECT` of exactly one
variable. This query has no `DISTINCT` and projects six, so `key` is None and no
split is even attempted — hence `no join rewritten (0 BGP split(s) reverted)`.

Loosening that gate would be WRONG rather than merely risky: the pass collapses
duplicates, which its design justifies by the enclosing `DISTINCT`. A
constant-predicate-and-object triple is safe for an unrelated reason —
`{space}_rdf_quad` has a UNIQUE primary key on
`(subject_uuid, predicate_uuid, object_uuid, context_uuid)` (verified, zero
duplicate groups), so it matches 0-or-1 rows and cannot duplicate. Two different
correctness arguments; they need two passes, not one loosened gate.

### The real blocker: term joins wrap the traversal

Distribution DOES emit the right join —

    Join Filter: (fsmv0.entity_uuid = ..._rdf_quad.subject_uuid)

— but as a filter rather than an index probe, because BGP #2 is wrapped by
`_wrap_with_terms` in an outer SELECT carrying five term joins. The anchor
cannot be pushed through that wrapper into `frame_slot`.

So late term materialisation is not merely 23% of the buffers. It is what
prevents the 61-entity anchor from reaching `frame_slot.entity_uuid`, which is
the whole difference between 3.6 s and the hand query's 13.7 ms.

`compute_text_needed_vars` is not the lever — it decides WHICH variables need
text, and all six here are genuinely projected. The lever is WHERE the term
joins are applied: per-BGP today, versus above the join (ideally above
`ORDER BY … LIMIT`, which would make it 10 rows x 5 lookups instead of 285,348).

## Target design, proven on the faithful query

Hand-written SQL in the shape the generator should emit — same `ORDER BY
?entity`, same `LIMIT 10`, real URIs out, verified row-for-row identical to what
the generator returns today (identical as multisets; order differs only within
tied `?entity` values, which the query does not break):

    target       14.1 ms      17,112 buffers    max loops    425
    generated  3,601.6 ms  5,022,432 buffers    max loops 285,348

**255x on time, 294x on buffers, and 7x under the 100 ms goal.** Nothing runs
285,348 times any more; the deepest loop count is the true result size.

Two ingredients, and they are COUPLED — which is why each failed alone:

  1. **Distribution over the union.** Each arm joins `frame_slot` on
     `entity_uuid` against the 61-entity anchor instead of entering through
     `q4` (every `KGFrame`) on `frame_uuid`.
  2. **Term text resolved after the traversal narrows** — and for the five
     non-sort-key variables, after the `LIMIT`. Only `?entity` needs its text
     inside, because the sort key reads it.

Distribution alone was >120 s because `_wrap_with_terms` puts a subquery
boundary around each BGP; the planner cannot flatten through it, so the
`entity_uuid` equality stays a join filter over the full traversal instead of
becoming an index probe. Removing the term wrapper is what lets the arm flatten
and the probe appear. Late text alone is worth only ~23% — of the four dominant
nodes only one is `term_pkey` (1.14M of 5.02M); the rest is the traversal
running 285,348 times, which only distribution fixes.

That coupling is the answer to why five separate shape rewrites were each tried
alone in this issue and each reverted.

### The machinery mostly exists

`emit_slice._emit_late_text` already does late text, with a measured precedent
(issues/088: 66,589 buffers against 28,336). It declines here on two gates:

    if buried and not _buried_order_is_synthesized(...):  return None
    if len(proj.project_vars or []) != 1:                 return None

Both are all-or-nothing where this query needs partial treatment: `?entity`'s
text must be resolved before the sort, the other five need not be. Generalising
means N term joins instead of one, and ordering the inner page by the REQUESTED
key rather than by uuid.

That function's own comments record five prior defects in this area — including
a paging change that broke fourteen API tests by returning 0 rows for a
`BIND`-bound variable. It is delicate work and should be done against those
tests, not around them.

## Hoisting term resolution above the pattern made it 6.4x WORSE — reverted

The previous section argued that resolving term text once above the reducing
join, instead of at every BGP boundary, was the fix for the full result set. It
was implemented at PROJECT level (`emit_project._emit_late_text`: project uuids
through the pattern, join `{space}_term` at the projection, re-state the lifted
ORDER BY against the resolved columns). Measured on the full set, `ORDER BY
?entity`, no `LIMIT`:

    before   3,103 ms    5,722,181 buffers   max loops     285,348
    after   19,747 ms   52,241,373 buffers   max loops  17,406,440

Rows stayed correct — 425, identical as a multiset to the hand-written answer.
It is 6.4x slower.

`17,406,440` is `285,348 x 61`: the cross product that was previously collapsed
into a single join filter is now enumerated row by row.

**Removing the text columns did not fix the row estimate; it only changed which
bad plan the planner chose.** The traversal is still estimated at `rows=1`
against a reality of 95k-285k, and on that estimate every join order looks
cheap. Making the previously-bad order impossible simply let it find a worse
one.

This is the sixth shape rewrite in this issue to be reverted, and the pattern is
now unambiguous:

    entry column (frame_uuid -> entity_uuid)   aimed at <1% of the plan
    distribution alone                         >120 s
    EXISTS semi-joins for type constraints     nothing left to rewrite
    term-set hoisting (CTE)                    no effect
    join distribution (first attempt)          2.0000x, lost rows
    term resolution above the pattern          6.4x worse (PROJECT level)
    the same, at SLICE level                   5.5x worse

Every one of them changes plan SHAPE. None of them changes what the planner
BELIEVES. Until the anchored arm's cardinality is estimated within orders of
magnitude of the truth, shape rewrites will keep trading one bad plan for
another, and the sign of the trade is not predictable in advance.

The hand-written query at 19.4 ms does not beat the estimate — it removes the
planner's discretion. `happy` is computed as its own CTE and the arm reads
`JOIN frame_slot s ON s.entity_uuid = h.e`: a direct equality from a known-small
set into an indexed column, with no join order left to choose. That, and not
late materialisation, is what the generator has to reproduce.


### The SLICE-level version fails identically

`emit_slice._emit_late_text` was also generalised — it previously handled
exactly one projected variable and declined on any requested `ORDER BY`, so it
never fired on this query. Generalised to defer per-variable (here 3 deferred,
3 kept: `?entity` because the sort reads it, the two slot-entity variables
because the `BIND` extends read them), on `LIMIT 10`:

    baseline                       3,601.6 ms    5,022,432 buffers   285,348 loops
    with SLICE-level late text    19,686.9 ms   52,235,905 buffers 17,406,440 loops

**The same 17,406,440 — the same cross product, the same failure.** Deferring
term text is harmful here regardless of WHICH level does it, which rules out
placement as the variable and confirms the diagnosis above: the term columns
were never the problem, the row estimate is.

Both changes are reverted. The generalisations themselves are sound and their
unit tests pass; they are simply not what this query needs, and they cost 5-6x
where they fire.

## Fixed: distribute over the UNION, then merge each arm's BGPs

    baseline    3,081.7 ms   5,722,185 buffers   425 rows   285,348 loops
    fixed           37.3 ms      14,845 buffers   425 rows       213 loops

**82.6x on time, 386x on buffers, identical as a multiset.** Under the 100 ms
target, and on FEWER buffers than the hand-written query it was modelled on
(14,845 against 25,372).

### What the fix is

Two rewrites, wired as a pair at stage 2a.2d — after the table rewrites, so the
merge sees `frame_slot` already collapsed, and before `mark_semijoins`:

  * `rewrite_distribute_union.distribute_join_over_union` (existing, previously
    shelved)
  * `rewrite_merge_bgp.merge_bgp_joins` (new) — `Join(BGP, BGP)` becomes one
    BGP, with the join's ON equality carried across as a tagged constraint.

Neither works alone, which is why five earlier attempts in this issue failed.
Distribution alone measured >120 s: each arm still emitted the anchor and the
traversal as separate subqueries with INDEPENDENT join orders, so the traversal
ordered itself from `q4` — every `KGFrame` — and entered `frame_slot` by
`frame_uuid`. Merge alone has nothing to merge: under the UNION the shared
variable is bound on only one branch, so the join carries the `issues/180`
null-tolerant guards and is not two plain BGPs.

Together, the trigram leaf that matches 61 entities in 3 ms becomes one of the
candidate anchors `reorder_joins` ALREADY prefers, and `frame_slot` is entered
on `entity_uuid`.

### It is NOT a CTE, and not late materialisation

Anchoring the arm in a `MATERIALIZED` CTE, a `NOT MATERIALIZED` one, and a plain
inline subquery all measured 15,268 buffers — the fence is worth nothing, which
also supersedes the "removes the planner's discretion via a CTE" reasoning that
motivated the prototype. What matters is only that both sets of tables reach ONE
ordering decision.

Deferring term text — the other candidate — was measured and REVERTED: 6.4x
worse at PROJECT level, 5.5x at SLICE level, both landing on the same
17,406,440-loop cross product.

### The rewrite declined SILENTLY, twice, on the query it was written for

Distribution fired and duplicated the pattern while the merge quietly did
nothing: all of the cost, none of the benefit — the >120 s signature. Both
causes were assumptions about plan shape that the plan itself disproved in one
dump:

    join
       filter                 <- the residual text predicate
          extend var=entity   <- BIND(?sourceSlotEntity AS ?entity)
             bgp
       bgp

The gate required both children to be `KIND_BGP`. A UNION branch of this shape
arrives as `Filter(Extend(BGP))`. Both modifiers lift above an inner join — a
FILTER reading only one side's variables commutes, and nothing selective is
deferred because `filter_pushdown` has already pushed the trigram predicate into
the leaf; BIND only ADDS a variable — so they are peeled and re-wrapped above
the merged pattern. An EXTEND binding a variable the other side also binds
declines instead, since lifting that would change which rows match.

**"Wired" and "firing" are different claims, and only the generated SQL settles
which.** Checking for `FROM ..._rdf_quad AS q4` in the emitted traversal took
one grep and would have caught both rounds immediately.

## `join_collapse_limit = 1` is a multiplier on order quality, not a substitute

`reorder_bgp` computes a join order and emits explicit `JOIN ... ON`, but at the
default `join_collapse_limit = 8` PostgreSQL flattens those back into one FROM
list and re-searches — so our order is a suggestion it may discard. Setting the
limit to 1 makes it binding. Measured both ways, three shapes each:

    WITH the BGP merge
      CONSTRUCT full set      jcl=8    43.2 ms   23,854 buffers   425 rows
      CONSTRUCT full set      jcl=1    35.5 ms   23,854 buffers   425 rows
      CONSTRUCT ORDER/LIMIT   jcl=8    41.0 ms   23,854 buffers    10 rows
      CONSTRUCT ORDER/LIMIT   jcl=1    34.4 ms   23,854 buffers    10 rows
      SELECT full set         jcl=8    42.0 ms   23,854 buffers   425 rows
      SELECT full set         jcl=1    34.1 ms   23,854 buffers   425 rows

**Buffers identical to the byte** — the plan does not change. After the merge,
PostgreSQL already picks exactly the order we write, so the consistent ~7 ms is
planning time it no longer spends searching. ~18%, and the real value is
DETERMINISM: it can no longer drift to another order as statistics or cache
state move, which is the failure mode that made most of this issue
unmeasurable.

WITHOUT the merge, the same knob is actively harmful:

      CONSTRUCT full set      jcl=8   3,251.6 ms   5,022,431 buffers
      CONSTRUCT full set      jcl=1   3,970.2 ms   9,788,689 buffers

**1.95x worse.** Unmerged, the order we write IS the bad one — anchor and
traversal in separate subqueries, the traversal opening on `q4`, every
`KGFrame` — so forcing it locks that in and removes PostgreSQL's chance to
escape. Binding works in both directions.

So the emitter fix does the work; the GUC only compounds it. Enable it per
shape, where the cost model is confident, never globally.

### This corrects the planning documents

`planning_sql/sparql_sql_optimization_plan.md` records an adaptive tier that
RAISES the limit (9-14 tables → `N+1` for exhaustive planning), and
`sparql_sql_v2_performance_plan.md` reports it "tested at 8, 16, 20 — no
effect". Every prior experiment widened PostgreSQL's search; **lowering it to 1
was never tried.** The "no effect" result is also explained: it was measured
when BGPs emitted `JOIN ... ON TRUE` with filters applied late, so there was no
real written order for the knob to preserve.

Note the adaptive hints are documented as APPLIED but `join_collapse_limit`
appears nowhere in `vitalgraph/` today — that implementation is gone, and prod
runs plain defaults (`join_collapse_limit=8`, `geqo_threshold=12`,
`default_statistics_target=500` on PostgreSQL 18.4).
