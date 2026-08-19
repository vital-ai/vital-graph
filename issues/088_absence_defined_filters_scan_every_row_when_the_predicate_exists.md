# Absence-Defined Filters Scan Every Row Once the Predicate Actually Exists

## Status: the late-text work SHIPPED and is not clean — restated 2026-08-18

The old status said "not yet closed" with the outer term join listed as still
open. That was stale in a way that misled twice over: the work was implemented
the same day (`af10e5f`), and it shipped **two correctness regressions** that took
a container rebuild to notice. Anyone reading the previous status would have
thought the change was pending and the code sound.

### What shipped, and what it cost

`af10e5f` moved text resolution after the LIMIT. On the Assertion shape it is a
large win — measured today on `sp_graph_forms_20k`, `LIMIT 25`:

    af10e5f~1  (before)       16,098 buffers   206.6 ms
    af10e5f    (as shipped)    1,744 buffers    56.9 ms      ~9x fewer buffers

It reached that by emptying `text_needed_vars` for the whole child, which
suppresses text for EVERY variable in it — including ones the child still reads.

**Regression 1 — a BIND-projected variable returned nothing** (`f3068d8`). The
child emits `NULL::uuid AS v0__uuid` for an expression-bound variable, so the
guard that checks the uuid COLUMN exists passed, and the text join then matched
nothing. `_frame_exists_in_backend` asks exactly that shape, so every frame
looked absent, DELETE answered "Frame not found", and 14 API tests failed.

**Regression 2 — a FILTER over text stopped generating at all** (`9d9b071`). With
the text suppressed, a `FILTER(CONTAINS(...))` compiled against a column that was
never materialised. The scope guard caught it and REFUSED the query
(`issues/023`, `issues/027`) — correct, and invisible: the frames list count
query is a simpler shape and kept working, so the endpoint answered
`total_count: 3, objects: []`. The search box said "3 results" above an empty
table.

Both were live for a day and neither was caught by a suite. The test-stack
container was 43 hours old, so no request had executed the new code; a green
`tests/api` says nothing about code the running image does not contain.

### RESOLVED 2026-08-18 — the demand was traced and removed

The section below described this as open, with three narrowings tried and none
working. Instrumenting the call instead of reasoning about it found the answer
immediately, and the guesses had missed it because they were aimed at the wrong
nodes.

`compute_late_text_vars` asks only what an EXPRESSION reads. Two sources were
demanding the projected variable's text:

  1. **`var_scope:475` — DISTINCT/REDUCED mark every visible variable.** They do
     not need to. A term's uuid is `uuid5` of the term including its type, so
     deduplicating on uuid is the same partition as deduplicating on the value —
     which `af10e5f` had already demonstrated by returning identical rows with
     all text suppressed.

  2. **`vars_in_expr` descends into an EXISTS body.** The emitted probe
     correlates on `__uuid`, so a variable mentioned there needs no text. The
     Assertion shape is two `FILTER NOT EXISTS` over the projected variable, so
     this alone was enough.

    HEAD before   16,043 buffers   195.9 ms
    HEAD after     1,744 buffers    43.4 ms
    af10e5f         1,744 buffers    45.2 ms   (the reference)

Both regressions stay fixed. Unit, integration, conformance and performance
suites at 0 failures.

**The saving now has a guard, and never had one** — which is why it was lost
twice with every test green. It asserts the SHAPE (exactly one term join,
outside the LIMIT) rather than a buffer count, and was verified to fail against
the previous computation. A paired test asserts a FILTER over text still gets
it, so the two cannot both be satisfied by never resolving text at all.

### Superseded: "the fix costs the saving"

`9d9b071` keeps text for variables an expression reads, which is what makes the
FILTER case correct. It also asks for the PROJECTED variable's text, and moving
exactly that outside the LIMIT is the entire optimisation. Measured at HEAD, same
query and fixture as above:

    HEAD (both fixes)         ~16-18k buffers   ~210 ms

i.e. back at the pre-optimisation number. The Assertion shape currently gets
correctness and no speed.

Three narrowings were tried and none restored it: excluding EXISTS bodies (an
EXISTS correlates on uuid, not text), excluding the synthesized `ORDER BY`
(it orders by a uuid column), and excluding a bare `GROUP`/`DISTINCT` variable
(the uuid is `uuid5` of the term, so it is the same partition). The demand for
`?frame`'s text survives all three and its source was not identified. Reverted
rather than left in — unmeasured complexity in a path that has already produced
two silent wrong answers is worse than a slow query.

**So what is open is no longer "implement late text". It is: make late text keep
the projected variable's text OUT of the page while a filter that reads other
variables still works.** That needs the demand traced properly rather than
narrowed by guesswork.

### Superseded status, kept because the measurements are still good

The `fold_dead_not_exists` fix only reached spaces where the predicates are
ABSENT. Where they exist — 22 of 79 production spaces — the anti-join runs, and
that path had **no fixture at all**: every generated space omits both predicates,
so every fixture took the folded path and the remaining half of this issue was
unreachable. `--form-type-fraction` now emits them; `sp_graph_forms_20k` (91,631
frames, 30% carrying an explicit form type or a frame-graph URI) reproduces it.

Reproduced, then fixed one layer of it. On that space, `LIMIT 25`:

    predicates ABSENT  (already fast)        991 buffers    17.9 ms
    predicates PRESENT (the open case)   639,843 buffers   536.7 ms
    after the fix below                   66,589 buffers   9.6x fewer

### An EXISTS body was resolving term text nothing reads

`NOT EXISTS (SELECT 1 FROM (SELECT t_ex_v0.term_text, t_ex_v0.term_type,
t_ex_v0.lang, ... ))` — the body projects `SELECT 1` and the subquery beneath it
resolved four term columns per variable, inside an anti-join that discards all of
them.

The cause is a rule that inverts between the two positions.
`compute_text_needed_vars` treats "no PROJECT node" as `SELECT *` — everything is
projected, everything needs text. For an EXISTS body the same absence means the
opposite: the output is discarded, so only a variable an expression INSIDE the
body reads needs its text. It now takes `projection_discarded=True` and the
EXISTS emitter passes it.

Computed rather than blanked, because a body carrying
`FILTER(STRSTARTS(?ft, "http"))` genuinely needs `?ft` — verified, that shape
still resolves text and still answers.

Ordering is why it was missed: `prepare_exists_subplans` builds the bodies at
stage 2a.3 and `compute_text_needed_vars` runs at 2c, so a prepared body never
saw the outer pass.

### What is still open

The remaining cost is the OUTER term join. Every one of them sits BEFORE the
`LIMIT`, so a page of 25 still resolves URI text for every candidate frame — the
plan shows a `Parallel Seq Scan` over 442,167 term rows for 25 output rows. That
is the late-materialisation shape `emit_slice` already reasons about for deep
pages. **Implemented 2026-08-17**, after one reverted attempt whose hazards are
recorded below because they are what the design had to answer.

### The prize, priced by hand

The ideal plan, written directly against the tables: page the uuids, resolve text
for the page only.

    text resolved BEFORE the LIMIT (ships)   66,589 buffers   578 ms
    hand-written, text after                  3,215 buffers   277 ms   20.7x

`_emit_two_phase` cannot reach it: it needs a semi-join or a foldable EXISTS over
a two-child JOIN, and a DISTINCT over a UNION is neither.

### The attempt

A general `_emit_late_text` in the `emit_slice` strategy chain — emit the child
with `text_needed_vars` empty, LIMIT it, join the term table outside. It reached
**28,336 buffers, 169 ms**: 2.35x, not 20.7x, because the child still computes
the whole DISTINCT UNION and only the text moved.

### Two hazards, both of which it hit

1. **The synthesized ORDER BY is not the caller's.** Declining every buried order
   made the path never fire — an unordered SLICE always carries the pipeline's
   synthesized `ORDER BY <anchor>__uuid`, which is the whole population this
   targets. `_buried_order_is_synthesized` is the discriminator, and that order
   must go INSIDE the subquery before the LIMIT or consecutive pages overlap.

2. **The registry then describes a projection that is not emitted.** The child
   registers every BGP variable it binds, so `var_map` advertised
   `{e0, f, se, ss}` where the final SELECT carries one column — `issues/083`
   with the sign flipped: not an empty var_map naming nothing, but a full one
   naming what is not there.

   Pruning `ctx.types` to the projected variable fixed that and **broke five
   paging tests** in `test_kgquery_deep_paging` and `test_kgquery_sorted_paging`.
   `ctx.types` is shared; clearing it is not local to this emission. Reverted
   there.

### What shipped

`ctx.child(types=TypeRegistry(...))` — a child context with its own registry, as
`emit_expressions` already does for an EXISTS body. Aliases stay SHARED, because
the constants the child references live there and a fresh generator would not
have them. The parent registry is never touched, so nothing needs pruning.

    text resolved BEFORE the LIMIT   66,589 buffers   578 ms
    after                            40,781 buffers   146 ms    4.0x on time

Pinned by `TestLateTextPagingPartitions`: three pages partition 75 of 75, and
`var_map` names exactly the projected variable on both the late-text page and the
ordinary one.

### A correction: the five paging failures were never this

They were blamed on the pruning and prompted the revert. They fail with the
change STASHED, in a full-suite run, and pass when their own files run alone —
`ModuleNotFoundError: No module named 'scripts.perf_shape_matrix'`.
`tests/unit/test_perf_baseline_stamping` inserts `<repo>/scripts` at
`sys.path[0]`, which binds `scripts` to a namespace rooted inside that directory,
and every later `from scripts.X import ...` looks for `scripts/scripts/X.py`.
Adding `scripts/__init__.py` fixes it: 5 failures to 1, and the survivor is a
known-flaky index-only-scan assertion that passes on re-run.

So the first attempt was probably sound and was reverted for the wrong reason.
The child-registry design is better regardless — pruning a SHARED registry is
wrong whether or not a test catches it — but the reasoning that reached it was
not.

Those tests only RUN because `sp_lead_synth_10k` was loaded on 2026-08-17. Before
that they skipped, which is also why an order-dependent import failure had gone
unnoticed.

The frames "Assertion" tab took **13.4 seconds** on a 1.1M-frame graph. It is now
**0.76 s cold, 0.03 s warm**. But the fix only reaches the case where the predicates are
missing from the space entirely, and **22 of 79 spaces on this database do have
them**. In those spaces the same shape is still measured at 9.7 s.

## What "Assertion" asks for

A KGFrame is an Assertion if `hasKGFormType` says so explicitly, OR if it has
**neither** `hasKGFormType` **nor** `hasFrameGraphURI`. The endpoint compiles
that second half to two `FILTER NOT EXISTS` clauses, which is a faithful
translation and the root of the cost: **the class is defined by absence**, and
absence cannot be looked up in an index. Every candidate frame must be probed.

## What was fixed

Both fixes are in the SQL pipeline, not the endpoint, and both were chosen by
measurement — several plausible-looking culprits turned out to cost nothing.

**1. A `NOT EXISTS` over a body that can never match is now folded away**
(`prune_union.fold_dead_not_exists`). If the body REQUIRES a term absent from
the term table, it matches nothing for any outer row, so the filter is a
tautology. Left in, the absent constant compiles to a scalar subquery over an
empty `_const` CTE, every comparison is NULL, the planner cannot fold it, and it
builds the correlated anti-join and runs it per candidate row:

    anchor + re-anchor                          0.4 ms
    anchor + re-anchor + 2 dead NOT EXISTS  4,506.1 ms

**2. An unrequested `ORDER BY` is no longer invented** (`build_sort_clauses`).
With no `sort_by`, the query carried `ORDER BY ?frame` — the anchor's URI TEXT,
which lives in the term table — so the backend resolved every candidate's URI
and sorted all 1.1M before LIMIT threw the sort away. Paging stays stable
because the pipeline synthesizes `ORDER BY <anchor>__uuid` for an unordered
SLICE; verified that ten consecutive pages partition with no overlap and that a
given page is repeatable.

    ORDER BY ?frame     5,571 ms
    no ORDER BY           611 ms

**3. `COUNT(?v)` no longer requests text for `?v`** — **REVERTED the same day,
it was wrong.** See below.

    count with the term JOIN   2,180 ms
    without it                   542 ms

End to end over HTTP, `sp_lead_synth_100k`, 1.1M frames:

| | before | after |
|---|---|---|
| Assertions tab, cold | 13,366 ms | 756 ms |
| Assertions tab, warm | 11,466 ms | 29 ms |
| Aspects tab | 84 ms | 44 ms |

## Fix 3 was reverted, the real cause found, and then RE-APPLIED

**Resolved 2026-08-13.** The account below is what happened first and why; the
underlying defect is now fixed in `emit_union` and fix 3 is back in place, with
`tests/integration/test_count_over_union.py` guarding it.

A UNION's output column never claimed term identity — `ColumnInfo.simple_output`
defaults `from_triple` and `uuid_materialized` to False — so `emit_join` fell
through to comparing the sides as TEXT even though the branches carried real
term UUIDs. That was true independently of fix 3 and cost 1.2x on every such
join (2,172 -> 1,816 ms on 570,696 rows). `emit_union` now propagates term
identity from its branches on the same terms it already propagated
`text_materialized`, so the join compares UUIDs and no longer depends on text
existing.

Two more counts were added on top: the frames count now goes through
`_count_cache` like `kgentities`/`kgquery`/`graphs` already did.

    Assertions tab, cold   2,333 ms -> 756 ms
    Assertions tab, warm   1,883 ms ->  29 ms

### The original account



`var_scope` was taught to skip text resolution for a variable that is only ever
COUNTed, because COUNT aggregates the UUID column. That is true of the
aggregate and false of the JOIN feeding it. `emit_join` compares the sides on
their TEXT columns:

    ON CAST(j0.v0 AS TEXT) = CAST(j1.v3 AS TEXT)

With text withheld both sides are NULL, `NULL = NULL` never holds, the join
matches nothing, and the count is 0. An interlock was added in `emit_group` so
the aggregate reads the UUID column when text is absent — it covered the
aggregate and missed the join predicate entirely, which is the narrower mistake
inside the wrong one.

Found while fixing the frames slot panel: the same pattern returned 4 rows as
`SELECT DISTINCT ?slot` and 0 as `COUNT(DISTINCT ?slot)`. Confirmed against
`e4e4536~1` — pre-change 3, post-change 0 — so it was this change and not a
pre-existing defect.

The cost of reverting is real and worth naming: the assertion count goes back
from 542 ms to 2,877 ms. It is still far better than the 5,965 ms it started at,
because the `NOT EXISTS` fold does the heavy lifting and is unaffected. A count
that is fast and silently zero is not a faster count.

**Why no test caught it.** A count over a plain BGP was correct throughout; only
a count over a UNION broke, and nothing exercised that. There is now
`tests/integration/test_count_over_union.py`, verified to FAIL against the
reverted code (2 of 3 cases) and pass with it.

**If this is attempted again**, the variable must be proven not to be a join
key, or `emit_join` must compare UUIDs when text is unavailable. Joining on
UUID is arguably better anyway — it is narrower and already what COUNT and the
synthesized paging order use — but it is a change to the core join emitter and
wants its own differential test rather than being smuggled in as an
optimisation.

## What is NOT fixed

Fix 1 fires only when the predicate is absent. Make the `NOT EXISTS` live and
the cost comes straight back — measured on the same 1.1M-frame graph by pointing
the filter at a predicate that space really has:

    LIST with a LIVE NOT EXISTS    9,654.5 ms

So **any space that actually populates `hasKGFormType` still has a slow
Assertions tab**, and that is 22 of the 79 spaces here. The largest is ~5.1M
quads. This has not been measured on those spaces directly — the tab was
reported slow on the synthetic one — so the size of the real-world exposure is
known in shape but not in number.

## Where a real fix would go

Roughly in order of how much they change:

* **Materialise the classification on write.** If every frame carried an
  explicit `hasKGFormType`, "assertion" becomes a positive indexed lookup and
  the anti-joins disappear. This is the only option that makes the query cheap
  rather than merely cheaper, and it is a write-path plus backfill change.
  Note the default is not a constant: an unset frame is an Assertion only when
  it also has no `hasFrameGraphURI`, so a backfill has to evaluate both.
* **A partial index or a derived column** for "has neither predicate",
  maintained like the other derived tables. Same family as `issues/041`, and
  inherits its staleness problem.
* **Teach the planner the anti-join is selective.** When almost every frame
  lacks the predicate, the anti-join returns almost everything, and a plan that
  streams the anchor and probes lazily would let LIMIT stop early. That is the
  shape `emit_slice` already reasons about for deep pages.

## Things to be careful about

* **The UNION arm and the re-anchor are NOT the problem**, despite looking like
  the obvious culprits. Measured: dropping the dead arm changed nothing
  (5,586 ms vs 5,571 ms), and the self-join the re-anchor creates costs 0.4 ms
  because PostgreSQL collapses it. The re-anchor is there for correctness — a
  filter-only UNION branch mistranslates to a global anti-join — and removing it
  measures fast for that reason, not because it is redundant.
* **Do not "fix" this by dropping the DISTINCT.** It is what makes the UNION
  arms not double-count, and `issues/046` records the elision being wrong before.
* A non-negated `EXISTS` over a dead body is constant-FALSE, which would make
  the enclosing pattern empty. That is a larger rewrite than dropping a conjunct
  and is deliberately not done; `query_is_provably_empty` covers the
  outer-constant form of the same idea.

## Related

- `issues/073` — provably-empty queries, the same "constant absent from the term
  table" reasoning applied to the outer plan
- `issues/046` — why the DISTINCT above a semi-join may not be elided
- `issues/041` — derived tables going stale, the risk any materialisation here
  would inherit
