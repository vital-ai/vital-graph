# Issues

Numbered, append-only, one defect each. Resolved ones move to `archive/` —
69 there, 19 live. An issue is archived only when nothing remains to do:
"FIXED in the converter, existing spaces need reloading" is not resolved, it is
half-done, and it stays here.

The grouping below is by what a fix would touch, not by severity. Most of these
were found while working on something else, which is why the themes are uneven.

## Traversal and derived tables — the current work

`048` is the plan; the rest are its neighbours.

| | status | |
|---|---|---|
| **048** | OPEN | **Frame/entity traversal: three priced performance problems.** The `frame_entity` collapse works (4 orders of magnitude at depth 3); constraining a walk is what costs — a slot-type constraint disables the collapse (~28,000x), and a criterion on the frame costs 150-5,700x even when it does collapse. Start here. |
| **090** | OPEN | Problem 2 of 048 in full: a criterion that SHRINKS a traversal makes it hundreds of times slower, across every datatype. Read before starting the work. |
| 043 | OPEN | KGQuery hardcodes entity/frame attachment — whole datasets unqueryable through KGQuery, silently |
| 041 | detection added | In-place reload leaves derived tables stale; repair is still manual |
| 060 | landed locally | Edge table has no type column; remaining work is non-local spaces |

Fixtures for this work: `scripts/generate_graph_dataset.py` (10k/100k,
scale-free and small-world, six criterion datatypes),
`tests/integration/test_frame_entity_collapse.py`,
`tests/performance/test_graph_traversal_fixture.py`.

## Blank nodes

Found together while writing `planning/planning_sparql_features/blank_nodes.md`;
they are one subject and probably one fix each on the same path.

| | status | |
|---|---|---|
| 065 | OPEN | Prefix convention diverges by write path |
| 066 | OPEN | `VALUES` with a blank node raises AttributeError |
| 067 | OPEN | `BNODE()` returns a constant, not a fresh node |
| 069 | OPEN | No fixture or behavioural coverage — do this one first |
| 076 | OPEN | `INSERT DATA` blank nodes are not fresh; labels are global |

## Query performance

| | status | |
|---|---|---|
| 088 | partially fixed | Absence-defined filters scan every row when the predicate EXISTS. Fast when absent (13.4 s -> 0.76 s cold, 0.03 s warm); still 9.7 s in the 22 of 79 spaces that populate the predicate |
| 081 | OPEN | Performance conclusions measured on an undersized buffer pool — read before trusting an old number |
| 070 | largely fixed | Pushed term subqueries re-execute inside correlated probes; `contains` not fully closed |

## Fixtures and test infrastructure

| | status | |
|---|---|---|
| 055 | OPEN | Loaders and tests target different clusters. Recurred 2026-08-14; needs a decision, not more documentation |
| 084 | OPEN | Load-test setup erases its own fixture list when the space is already seeded |
| 063 | OPEN | Benched spaces have older geo and fuzzy tables |
| 022 | partially resolved | E2E list-visibility flake under parallel load; one class not swept |

## Other

| | status | |
|---|---|---|
| 042 | fixed in the converter | CSV import drops datatypes and diverges on term uuids; existing CSV-loaded spaces still need reloading |
| 032 | deferred | `vitalgraph_service_impl` stranded by a sync interface |

## Conventions worth keeping

**A status line, first heading after the title.** `## Status: OPEN — one line on
what remains`. `055` used a bold `**Status:**` instead and was invisible to
every listing that grepped for the heading.

**Say what is NOT fixed.** Several issues here are half-done, and the half that
remains is the useful part of the document.

**Record the retractions.** `048` carries three: a claim about which query
shapes the rewrite reaches, a 6x figure measured against a traversal the
pipeline does not emit, and a "settled" status that stopped being true. Each was
believed for days. Deleting them would leave the same wrong inference available
to be made again.

**Prefer a measurement to an adjective.** "Slow" is not actionable; "0.7 ms to
4,043 ms at depth 3, returning one row instead of 32" is.
