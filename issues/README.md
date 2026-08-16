# Issues

Numbered, append-only, one defect each. Resolved ones move to `archive/` —
70 there, 20 live. An issue is archived only when nothing remains to do:
"FIXED in the converter, existing spaces need reloading" is not resolved, it is
half-done, and it stays here.

The grouping below is by what a fix would touch, not by severity. Most of these
were found while working on something else, which is why the themes are uneven.

## Traversal and derived tables — the current work

`048` is the plan; the rest are its neighbours.

| | status | |
|---|---|---|
| **048** | OPEN | **Frame/entity traversal: three priced performance problems.** The `frame_entity` collapse works (4 orders of magnitude at depth 3); constraining a walk is what costs — a URI constraint on the SLOT disables the collapse (~28,000x), the same constraint on the FRAME survives it and still costs ~160x, and value criteria cost 150-950x. The goal is that adding a criterion is never a cliff, not that redundant ones are detected. Start here. |
| **090** | OPEN | Problem 2 of 048 in full: a criterion that SHRINKS a traversal makes it hundreds of times slower, across every datatype. Read before starting the work. |
| 043 | OPEN | KGQuery hardcodes entity/frame attachment — whole datasets unqueryable through KGQuery, silently |
| 041 | detection + repair | In-place reload leaves derived tables stale. Repair is no longer manual: `scripts/repair_derived_tables.py` rebuilds frame_entity/entity_fanout/value_stats, and the maintenance cycle audits rdf_stats counts every run (2026-08-16) |
| 060 | landed locally | Edge table has no type column; remaining work is non-local spaces |

Fixtures for this work: `scripts/generate_graph_dataset.py` (10k/100k,
scale-free and small-world, six criterion datatypes),
`tests/integration/test_frame_entity_collapse.py`,
`tests/performance/test_graph_traversal_fixture.py`.

## Grouping URIs — found 2026-08-16

Both surfaced while making entity-graph reads depend on the self-link. The data
is repaired and watched; what remains is the cause in each case.

| | status | |
|---|---|---|
| 091 | OPEN | 619 grouping URIs lost their self-link; repaired, but the writer was never identified — and reads now return EMPTY when it happens |
| 092 | OPEN | A grouping target with no type at all; no server-property path can create it, and one exists |

## Blank nodes

Found together while writing `planning/planning_sparql_features/blank_nodes.md`.
Worked 2026-08-16, starting with 069 as advised — and the fixture was the right
first move: every fix that held was one where the measurement came first.

| | status | |
|---|---|---|
| 069 | fixture added | Fixture + tests 3-8 done; 9-12 outstanding, and 9-10 need no fixture |
| 065 | RESOLVED | One convention, enforced at term identity. 0 blank-node terms on 85 spaces, so no migration |
| 066 | RESOLVED | `.label`, not `.value`; the test that hid it rewritten to describe the type |
| 067 | RESOLVED | Fresh per solution. One gap left in place: `BNODE(expr)` is not scoped per execution, because the compile cache reuses SQL |
| 076 | RESOLVED | Fresh `INSERT DATA` labels; `DELETE DATA` rejects them; scoping DECIDED as deterministic skolemisation |

The scoping decision is the one worth reading: RDF 1.1 §3.5 recommends
skolemisation directly, and RDF4J's `PRESERVE_BNODE_IDS` defaults to false — so
fresh-per-parse is the industry default and this store did the opposite.
Deterministic over `(document, label)` gives RDF scoping AND idempotent reload,
which neither listed option gave alone.

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
