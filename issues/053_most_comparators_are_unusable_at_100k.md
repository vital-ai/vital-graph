# Twenty-One Comparator Shapes Time Out at 100k for a 25-Row Page

## Status: OPEN — 16 of 21 original cells closed; 9 cells still exceed 1s — 2026-08-10

| cells | status |
|---|---|
| `gt` x2 | fixed — `issues/054`, the XSD cast defeated the push-down |
| `lt` / `lte` x4 (numeric) | fixed — `issues/056`, `num_val` too sparse for ANALYZE to sample |
| `not_has` / `not_has_any` x4 | fixed — `issues/057`, negation folded into the probe |
| `not_exists` x2 | fixed — `issues/059`, candidate-driven emission |
| `ne` x4 | fixed — `issues/058`, `!=` pushed as a negated equality set |
| **`ne`/Boolean** | **declined** — `"true"` and `"1"` are one value and there is no `bool_val` column to say so. Slow and correct beats fast and wrong |
| `contains` | improved, not closed — timeout -> 1.3 s. `issues/070` |
| `has_any` x2 | improved, not closed — timeout -> ~13 s. `issues/070` |
| **datetime x3** (`eq`, `gt`, `gte`) | **open** — near-empty or near-total match sets; the typed column landed and cannot help a query whose cost is its match set |

### Do not read "closed" as "under 1s"

`056` and the `dt_val` column moved cells from *timeout* to *seconds*, and an
earlier revision of this file recorded that as closed. Against a 25-row page it
is not. Nine cells still exceed 1s on the verified sweep, and four of them are
in rows this table calls fixed:

    eq/DateTime          TIMED OUT (>60s)
    ne/Boolean           TIMED OUT (>60s)     declined, see above
    gt/DateTime          TIMED OUT (>60s)
    gte/DateTime         TIMED OUT (>60s)
    is_empty/Text           52,374 ms         never tracked here — see below
    has_any/Choice          13,269 ms         issues/070
    has_any/Text            12,684 ms         issues/070
    lte/DateTime            11,029 ms         "fixed" by dt_val, still 11 s
    lt/DateTime              9,527 ms         "fixed" by dt_val, still 9.5 s
    eq/Integer               2,015 ms         consistent across 3 runs, uninvestigated
    contains/Text            1,284 ms         issues/070

`is_empty`/Text at ~52 s has never appeared in this issue's accounting at all.
It is not a regression — it measures the same at HEAD — it was simply never
counted, which is its own finding about how this list was maintained.

### Measurement note: only claim a cell you can name a mechanism for

The three-way sweep (HEAD / change / change+guard) showed `eq`/Text at
1,124 -> 1,045 -> 107 ms and `has_all`/Text at 2,401 -> 551 -> 1,099 ms. Neither
compiles to a FILTER at all, so no push-down change can touch them: that spread
is cache and run-to-run variance, not an improvement. A sweep is a coarse
instrument and a single run of one arm cannot tell a 2x change from noise —
claim a cell only when a mechanism explains it AND repeated runs agree.

## Original status: narrowed from 21 cells to 17 with three causes

Final sweep on a verified environment (complete indexes, idle cluster, raised
statistics targets, all three fixtures on matching schemas):

| cause | cells | issue |
|---|---|---|
| blocking sort over the whole match set; needs the two-phase gate extended to correlated `NOT EXISTS` | 6 — `not_exists` x2, `not_has` x2, `not_has_any` x2 | `057` + `two_phase_kgquery_paging_plan.md` |
| `!=` is not pushable, so `?val` stays live, the semi-join declines and paging reverts to a blocking sort | 5 — `ne`, all slot classes | `058` |
| datetime: near-empty or near-total match sets | 3 — `eq`, `gt`, `gte` | here |
| no push-down path exists at all | 3 — `contains`, `has_any` x2 | here |

`issues/057` (EXISTS bodies bypassing the pipeline) is **fixed** — the probe
went 435 ms -> 0.11 ms — but closes none of these, because the blocking sort
makes cost `100,000 x probe` whatever the probe costs. It is what makes the gate
work worth doing: 25 probes now cost 2.75 ms.

Closed since the first measurement:

| cell | first | final | by |
|---|---|---|---|
| `gt`/Double, `gt`/Integer | TIMED OUT | 663 ms, 91 ms | `054` (cast defect) |
| `lt`/Double, `lt`/Integer | TIMED OUT | 245 ms, 258 ms | `056` (statistics) |
| `lte`/Double, `lte`/Integer | TIMED OUT | 227 ms, 1,628 ms | `056` (statistics) |

**Read those figures as cold first executions, not as costs.** The sweep runs
each cell once with no warmup. `lt`/Double reads 245 ms here and **7 ms** when
measured warm with median-of-3 — a 35x gap on the same query. The sweep is sound
for "completes vs times out at 60s for a 25-row page" and unreliable for
comparing two fast cells; see `folding_query_timing_tests_into_the_framework.md`
§4.5.

## Status: OPEN, narrowed — first measured 2026-08-09, re-measured 2026-08-10

`gt` on double and integer is **fixed** (`issues/054`): both went from timing out
at 60 s to 470 ms and 136 ms, matching their `gte` siblings at 457 / 125 ms.

The rest is now understood as **one** problem rather than the three below. See
"What the re-measurement changed", which supersedes cause 1 and reframes 2 and 3.

The original analysis is kept as written because two of its conclusions were
wrong in instructive ways.

Every comparator the API accepts, swept against `sp_lead_synth_100k`
(100,000 entities), page of 25, 60s budget per cell, executor fence applied:

| result | cells |
|---|---|
| under 1s | 14 |
| 1-3s | 4 |
| **timed out at 60s** | **21** |

A 25-row page. Not a count, not an export.

## What times out

| comparator | slot classes |
|---|---|
| `ne` | **all five** — text, double, boolean, integer, choice |
| `gt` | double, integer, datetime |
| `gte`, `lt`, `lte` | **datetime only** (numeric ones are 273-361ms) |
| `contains` | text |
| `not_exists` | text, double |
| `is_empty` | text |
| `has_any`, `not_has`, `not_has_any` | text, choice |

And what does not:

| | |
|---|---|
| `eq` | 1.9s text, 2.6s integer, faster elsewhere |
| `gt`/`lt`/`lte` on double, integer | 273-361 ms |
| `exists` | 140-161 ms |
| `has`, `has_all` | 252 ms - 1.2s |

## Three causes, not twenty-one

**1. No typed column for datetimes — and PostgreSQL will not allow the obvious
one.** `num_val` is a STORED generated column on the term table with its own
index, added so numeric ranges could be indexed and *estimated*. There is no
equivalent for datetimes, so a datetime range compares a CAST expression. That
is the whole difference between `lte/KGDoubleSlot` at 273ms and
`lte/KGDateTimeSlot` timing out. Term table columns today:

    term_uuid, term_text, term_type, lang, datatype_id, created_time,
    dataset, num_val

An earlier revision of this issue said "the fix is the one already taken for
numerics, applied again". **That is wrong, and worth recording.** A generated
column's expression must be IMMUTABLE, and text-to-timestamp conversion is not:

    text -> numeric              provolatile = i   (immutable)
    to_timestamp(text, text)     provolatile = s   (stable)
    text -> timestamp cast       not immutable

`ALTER TABLE ... ADD COLUMN dt_val TIMESTAMP GENERATED ALWAYS AS
(CAST(term_text AS TIMESTAMP)) STORED` fails outright with *generation
expression is not immutable*. Timestamp parsing depends on `DateStyle`, so
PostgreSQL refuses to store a value that a session setting could change.
`num_val` works only because `text -> numeric` happens to be immutable — that
was luck, not a pattern to copy.

Real options, none free:

  * a generated **TEXT** column holding the ISO string (a CASE over
    `term_text` is immutable) and lexicographic comparison, which is correct
    for ISO-8601 only while every value is written in the same form —
    inconsistent precision or timezone suffixes break the ordering;
  * an ordinary column maintained by the write path or a trigger, giving real
    timestamp semantics at the cost of a maintenance surface, which is the
    class of thing `issues/041` and `043` are about;
  * a partial index on `term_text` restricted to the datetime datatypes, with
    the same lexicographic caveat.

Choosing needs to know whether datetime literals are canonically formatted on
ingest. They are in the fixtures; whether that holds for real data is unknown.

**2. Negation and anti-joins.** `ne`, `not_exists`, `is_empty`, `not_has`,
`not_has_any` all time out. `is_empty` was improved from >120s to 1.5s at 10k by
`issues/052`, and still times out at 100k, so that fix helped without being
sufficient. The semi-join rewrite explicitly declines LEFT JOINs, so none of
this family gets the O(page) treatment `issues/040` built.

**3. `contains` and `has_any`.** Text matching and multi-value membership.
Neither has a leaf push-down path, so both evaluate above the join.

## The first two re-measurements were contaminated — read this first

Two sweeps were run on 2026-08-10 against a fixture that was **missing six
indexes** (`quad_sp`, `quad_subj`, `term_num`, `term_trgm`, `term_tt`,
`term_type`) while **three queries had been running for 20h48m** on the same
cluster. Both were reported as results before either problem was noticed. Treat
any 100k figure from those runs as void; `issues/055` covers why nothing caught
it.

The third sweep — complete indexes, idle cluster, freshly analyzed — is the one
below. It changed the conclusions materially rather than cosmetically:

| cell | contaminated | clean |
|---|---|---|
| `lt`/Double | 190 ms | **TIMED OUT** |
| `lte`/Double | 156 ms | **TIMED OUT** |
| `lt`/Integer | 198 ms | **TIMED OUT** |
| `lte`/Integer | 170 ms | **TIMED OUT** |
| `gt`/Double | 470 ms | 1,914 ms |

Those four became *worse* once the fixture was repaired, which is the opposite
of the expected direction and turned out to be a finding in its own right —
`idx_*_term_num` is a pessimization at this scale (`issues/056`).

## What the re-measurement changed (2026-08-10)

The sweep was re-run at 100k after the datetime column and `issues/052` landed,
and every cell's `needs_ordered_scan` was recorded alongside its timing.

**Whether two-phase paging engages predicts the timing almost perfectly:**

| | cells | timings |
|---|---|---|
| two-phase engaged | 18 | 99–857 ms, one exception |
| two-phase declined | 21 | every timeout and every multi-second cell, one exception |

Twenty-one declined. Twenty-one slow. The chain is short:

    mark_semijoins declines
      -> _emit_two_phase declines        (emit_slice.py:69, `_has_semijoin`)
        -> blocking Sort on term_text
          -> cost O(match set), not O(page)

Both exceptions confirm it. `eq`/Double declines yet runs in 297 ms — a blocking
sort over a small match set is cheap. `eq`/DateTime engages yet times out — every
datetime term in this fixture is distinct (409,017 of 409,017, `issues/050`), so
it matches ~nothing and paging in index order scans the whole index to find 25.
Cost is `min(work to find a page, work to materialise all matches)`.

### Cause 1 above was wrong — the typed column was not the whole story

The `dt_val` column shipped, is populated for all 409,017 datetime terms, has its
index, and **is used**. It moved `lt` and `lte` from timeout to 6.1 s and 8.3 s.
It did nothing for `gt` and `gte`, which still time out.

That is not a push-down failure. The `gte` and `lte` plans are structurally
identical — cost 21,185 vs 20,944, both scanning `dt_val`. The 13.3x timing gap
tracks a 13.3x *match-set* gap exactly: 380,493 terms at or above the threshold
against 28,524 below it. A blocking sort makes cost proportional to matches, so
the same plan is fast on the selective side and hopeless on the broad one.

The lesson worth keeping: "`lte`/Double is 273 ms and `lte`/DateTime times out,
therefore the missing typed column is the cause" was a reasonable inference from
one axis of variation, and it was still only half right. The datatype and the
match-set size were confounded.

### So the remaining work is not per-comparator — but not for the reason first given

An earlier revision of this section said the negation family was slow because
`mark_semijoins` does not produce a semi-join for an anti-join, so two-phase
paging declines and cost reverts to a blocking sort — and that the fix was to
generalize the gate to accept negative probes.

**That was wrong, and measuring it is what showed why.** A single correlated
`NOT EXISTS` probe costs 435 ms, so even a perfectly early-terminating plan
would need 11 seconds for a 25-row page. The gate was never the binding
constraint.

The actual cause is that `_exists_to_sql` builds the EXISTS body by calling
`collect()` at **emit** time, after the whole optimization pipeline has run on
the outer plan. The body therefore gets no constant materialization, no
edge-table rewrite, no semi-join marking and no text pruning — it walks raw
quads and resolves every predicate URI at runtime. That is `issues/057`, and it
covers ten of the twenty-one cells (`ne` x5, `not_exists` x2, `not_has`,
`not_has_any`).

There was also nothing for the proposed gate change to attach to: `not_exists`
produces `filter -> join -> (bgp, bgp)` with the negation inside a filter
*expression*, not a negated join node.

## Why this was not visible

`eq` and `gte` are the only comparators with any test coverage, on any slot
class — and they are two of the fast ones. The shape matrix
(`scripts/perf_shape_matrix.py`) classifies plans at 10k, where an O(matches)
plan over a small match set still returns quickly; classification alone reported
these as `set-based` rather than broken. Only timing at scale separates the two.

## Reproduce

Sweep with timing rather than plan classification:

    TSPACE=sp_lead_synth_100k TGRAPH=urn:sp_lead_synth_100k \
      python scripts/perf_comparator_timing.py

## Suggested order

Superseded by the re-measurement. Item 1 is done and did not deliver what this
issue predicted; items 2 and 3 turn out to be the same problem.

1. ~~**Datetime typed column**~~ — **DONE.** Fixed `lt`/`lte` (timeout → 6–8 s),
   did nothing for `gt`/`gte`. Worth having; not the cause.
2. ~~**`gt` on double/integer**~~ — **DONE**, `issues/054`.
3. **Run the optimization passes on EXISTS bodies** (`issues/057`). Ten cells,
   one cause: `ne` x5, `not_exists` x2, `not_has`, `not_has_any`. A probe that
   walks raw quads and resolves URIs at runtime costs 435 ms; no paging strategy
   recovers from that.
4. **Density, not just plan shape** — now supported by two independent findings,
   which is why it has moved up. `eq`/DateTime shows two-phase engaging and still
   scanning everything when the match set is near-empty; `idx_*_term_num`
   (`issues/056`) shows the planner driving from a tiny, cheap-looking index
   into a nested loop across a broad match set. Both are decisions made without
   match density. This is D3 in `two_phase_kgquery_paging_plan.md`.
5. **Re-validate `issues/040` at 100k.** Its range push-down was certified at
   10k on `idx_*_term_num`, and that index inverts sign between the two scales.
6. **`contains` / `has_any`** — still genuinely separate. `contains` has no
   indexable push-down path; `has_any` is a disjunction over probes.

Note that the 100k fixture's datetimes are unique per row (`issues/050`), which
makes `eq`/DateTime pathological in a way real data may not be. Rebuilding the
SYNTH fixtures on the day-grid sampler should come before drawing conclusions
from that cell.

## Related

- `issues/052` — the OPTIONAL join fix; helped `is_empty` without closing it
- `issues/040` — the O(page) work, which covers only the shapes the semi-join
  rewrite accepts
- `issues/054` — the `gt` cast defect; closes two of the cells counted here
- `issues/055` — why this went unnoticed: the suite that covers these
  comparators was reporting 26 silent skips because its fixture had been built
  into a different cluster
- `issues/050` — the SYNTH fixtures' unique-per-row datetimes, which make
  `eq`/DateTime here unrepresentative
- `two_phase_kgquery_paging_plan.md` — the engagement measurement and what it
  implies for the gate
