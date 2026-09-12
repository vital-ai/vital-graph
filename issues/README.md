# Issues

Numbered, append-only, one defect each. Resolved ones move to `archive/` —
76 there, 116 live. An issue is archived only when nothing remains to do:
"FIXED in the converter, existing spaces need reloading" is not resolved, it is
half-done, and it stays here.

The grouping below is by what a fix would touch, not by severity. Most of these
were found while working on something else, which is why the themes are uneven.

## Traversal and derived tables — the current work

`048` is the plan; the rest are its neighbours.

| | status | |
|---|---|---|
| **048** | P1+P2 FIXED, P3 DECLINED | **RESOLVED 2026-08-17/22 — no longer the starting point.** **Frame/entity traversal: three priced performance problems.** The `frame_entity` collapse works (4 orders of magnitude at depth 3); constraining a walk is what costs — a URI constraint on the SLOT disables the collapse (~28,000x), the same constraint on the FRAME survives it and still costs ~160x, and value criteria cost 150-950x. The goal is that adding a criterion is never a cliff, not that redundant ones are detected. Start here. |
| **090** | FIXED | **FIXED 2026-08-17.** Problem 2 of 048 in full: a criterion that SHRINKS a traversal makes it hundreds of times slower, across every datatype. Read before starting the work. |
| 043 | FIXED | **FIXED 2026-08-18 — attachment topology is a criteria option.** KGQuery hardcodes entity/frame attachment — whole datasets unqueryable through KGQuery, silently |
| 096 | worked case | Not traversal work itself, but carries a tail-only pin priced BOTH ways on real data: selective-end-first is **2.9x**, the same form is **87x WORSE** when the entity is pinned. Win, regression, separating statistic and formulation all measured. `traversal_decision` needs only to count a type-constrained end as pinned, and something to read its answer. **2026-09-11, measured:** both rows reproduce at HEAD (421,010 buf / 311.8 ms vs 49 buf / 0.1 ms) and it is NOT superseded by `rewrite_merge_bgp` — that never runs here, the plan is a single BGP. But the separating statistic does not exist: restricted to the entity type the query asks for, both ends are 2,863, a TIE (the 5,726 counted both entity types). The discriminator is the SORT, and both tests are syntactic. **The gate's value case does not survive: its 2.9x arm is SERVED by the table (users never pay it) and the arm that does reach the pipeline is already 0.1 ms.** **Multi-key sorts now SERVED** (`560dda08`): the declined two-key sort was 1,405,617 buf / 778.5 ms and is 165 buf / 3.6 ms as N conditional aggregates over one index-only scan — 215x, flat in the key count, no new table. **URI-valued entity property filters now SERVED** (`11d628e5`): 1,007,597 buf / 548.9 ms → ~15 ms. The earlier claim that this was blocked on a bad `(predicate,object)` estimate was a PROBE ARTEFACT — inline sub-SELECTs are opaque at plan time; with literals the estimate is 8,666 vs 8,755 actual. The real hazard was the generic plan on the 6th execution (~10 ms → ~1,180 ms), so the constants are inlined. The no-frame-hop shape has NO DATA in any space, **so the direction gate has no measured case left at all.** Chasing this found `entity_slot_sort` was never ANALYZEd (`562d111a`) |
| 041 | detection + repair | In-place reload leaves derived tables stale. Repair is no longer manual: `scripts/repair_derived_tables.py` rebuilds frame_entity/entity_fanout/value_stats, and the maintenance cycle audits rdf_stats counts every run (2026-08-16) |
| 060 | landed locally | Edge table has no type column; remaining work is non-local spaces |
| 176 | record | **The prop-sort tables — `entity_prop_sort`, `frame_prop_sort` — and what keeps them current.** Read before debugging a slow listing: population, per-write maintenance and the coverage marker are three different mechanisms, and an empty `prop_sort_coverage` means something is wrong rather than unknown. Also indexes the four defects found getting there, and names what commit `9756865e` carries beyond its subject line.  **Superseded in part by `194`:** its claim that these tables are "maintained per-write" was aspirational — seven write paths maintained neither — and its coverage marker is now counted in PAIRS, not per subject |

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
| 092 | CLOSED | **CLOSED 2026-08-21.** A grouping target with no type at all; no server-property path can create it, and one exists |

## Blank nodes — RESOLVED 2026-08-16, all five archived

`065`, `066`, `067`, `069`, `076`. Worked in the order `069`'s own advice gave —
fixture first — and that ordering earned its keep: two existing unit tests
*asserted* the defects, so both fixes would have read as regressions to anyone
trusting a green suite.

Scoping was decided as deterministic skolemisation over `(document, label)`:
RDF 1.1 §3.5 recommends skolemisation directly, and RDF4J's `PRESERVE_BNODE_IDS`
defaults to false, so fresh-per-parse is the industry default and this store did
the opposite. Determinism is what gives RDF scoping *and* idempotent reload,
which neither listed option gave alone.

Two assumptions recorded as settled turned out to be wrong when measured: the
edge table DOES project blank-node endpoints, and `BNODE(expr)` per-execution
scoping was never actually blocked by the compile cache. Both are written up in
`planning/planning_sparql_features/blank_nodes.md` §4.7 and §4.2.

## Conformance coverage — found 2026-08-16

The DAWG suite ran 19 of 34 `sparql11` categories. The other 15 had manifests and
query files sitting in the tree that nothing executed, so "conformance is green"
meant "green on the categories someone remembered to add" — and nothing in the
repo would tell you the difference, because the failure mode is ABSENCE.

All 15 are now run or declined in writing. 705 → **907 executed cases**.

| | status | |
|---|---|---|
| 093 | FIXED | **A missing term used only to EXCLUDE emptied the whole query.** Not subqueries — any `GRAPH ?g` with a `default_graph` whose URI had no term returned zero rows, silently. Two passes disagreed on what an absent term means |
| 094 | FIXED | `xsd:float` rendered `33.33` as `33.33000183105469` — a binary32 value printed at binary64 width. All six cast cases pass; the "canonical form" second half I recorded turned out not to exist |
| 095 | 3 of 4 FIXED | Grammar restrictions Jena parses but SPARQL forbids. `SELECT *` with `GROUP BY` has no defined answer, so accepting it returned something undefined. The fourth is declined with a reason |
| 097 | FIXED | A non-JSON request body returned HTTP 500 on every endpoint |
| 100 | OPEN | KGType search finds nothing on the test stack — 6 cases, including keyword which needs no embeddings. Provenance not established: the dev app is stopped, so there is no before/after comparison |
| 099 | FIXED | **The fixture loader and the perf tests default to different clusters.** `VG_TEST_PG_PORT` defaults to 5433 in the seeders and 5432 in the tests, so fixtures were seeded into one and read from the other — which held a stale same-named space, so tests got plausible wrong answers instead of an error |
| 098 | FIXED | **Search input was interpolated into SPARQL unescaped — confirmed filter bypass.** Previously carried as "quotes break the query"; a balanced payload does not break it, it disables the FILTER and returns everything. Eight sites, including three that escaped the quote but not the backslash |

Verified PASSING rather than assumed: `property-path` 33/33, `project-expression`
7/7, and 166 of 170 syntax cases. The feature tracker had listed property paths
as implemented-but-unverified; they are now verified.

Fixed in the same pass, all found by the harness rather than by the categories:

- a malformed user query returned **HTTP 500** from the sidecar (`SparqlCompiler`
  let a post-parse `QueryException` escape to a blanket handler)
- the oracle xfail table was suppressing `test_sql_v2` too, switching off **14
  passing tests of our own backend**
- the DAWG loader silently dropped user-defined datatype IRIs — harness only;
  production registers them

`tests/conformance/test_dawg_coverage.py` now fails if a category is neither run
nor declined with a reason, so a new manifest cannot land unnoticed.

`protocol` (34 cases) was then wired too, because it was the one declined
category testing something we actually ship. First run: 2 passed and **22
returned HTTP 500** — every one through a single un-encoded validation handler
that made ANY non-JSON request body a server fault on ANY endpoint. See 097.
Now 12 pass, zero 5xx, and the remaining 22 are honest gaps: 17 need the
Protocol's body content types, 3 need `application/sparql-results+json`, and 2
need a decision on 200-vs-4xx that conflicts with this project's convention.

Declined deliberately: `entailment`, `service`, `service-description` (out of
scope) and `http-rdf-update` (deferred).

## KGQuery construction

| | status | |
|---|---|---|
| **096** | fixed; direction gate still open | **Frame/slot sort orders by a variable it never projects.** The 500 and the duplicate-row defect under it are fixed and tested; the one-line fix the report recommended was WRONG (many-per-anchor → needs `GROUP BY`+`MIN`/`MAX`). Then **869 ms → 8 ms end to end** via `{space}_entity_slot_sort`, a new STRUCTURAL MIRROR: incremental on all 8 write paths, drift-detected, repairable, and READ by `fast_slot_sort`. Eliminated on evidence first: extended stats (already present, aimed at scan not join estimates) and the semi-join (**structurally unavailable to a SORT** — it must project the value a semi-join collapses). Left open: the direction gate (2.9x general, 87x worse pinned) and the shapes the reader declines |

`043` (above) is the other `kg_query_builder.py` defect — both are silent to the
caller, which is what makes that file worth a sweep rather than two point fixes.

## Query performance

| | status | |
|---|---|---|
| 088 | RESOLVED | **RESOLVED 2026-08-19 — 1,744 buffers, 43.4 ms.** The "still 9.7 s in 22 of 79 spaces" this row used to carry were the PRE-FIX numbers and stayed here after the fix landed. Absence-defined filters scan every row when the predicate EXISTS. Fast when absent (13.4 s -> 0.76 s cold, 0.03 s warm); still 9.7 s in the 22 of 79 spaces that populate the predicate |
| 081 | SAFEGUARD CLOSED | Perf conclusions measured on a 1 GB pool. The three re-measurements are done; the comparison gate skipped ABSENT values, so an unstamped baseline disabled it rather than failing it — a disabled gate reports what a satisfied one reports |
| 070 | largely fixed | Pushed term subqueries re-execute inside correlated probes; `contains` not fully closed |
| **178** | 1 FIXED, 1 bounded | **The happy-frame CONSTRUCT returned 30 of 60 triples, and 84% of its 69s was ONE tautology check.** (1) FIXED: `rewrite_frame_entity_table` pruned projected variables into literal `NULL`; row correctness cleared first (425 = 425, zero diff), so missing OUTPUT not wrong answers. (2) BOUNDED: `excludes_nothing` capped at 2s, 58,035ms → 3,206ms cold. A precompute/persist layer built on top worked (527ms) and was **REVERTED as premature** — stored schema committed before establishing where the cost was. Neither defect is where the time goes; see 179 and 180. **Read for four retractions** — including why "a join is removed" is not evidence of a win, and why `NULL AS v` means nothing until you read the `__uuid` beside it |
| **179** | RESOLVED 2026-09-11 | **RESOLVED — the trigram index IS the entry point now** (`Bitmap Index Scan on idx_..._term_trgm`, 23,854 buffers, 341 loops, 425 rows). Its "one open question" is answered and the question was wrong: the push-down produced a cheap anchor THE PLAN THREW AWAY, because nothing let it drive. `rewrite_merge_bgp` made it drive; they compose. **`CONTAINS(LCASE(STR(?x)),"s")` is never pushed, so the trigram index that exists for it is never used.** `_text_search_operands` declines the shape on two gates, both relaxable without losing what they guard. Worth **324x on the simplified traversal (1,153,015 → 3,561 buffers)**, reaching the pinned-set floor — it gives the planner an entry point from the selective end and the 285,348-frame enumeration vanishes. Still REGRESSES the reference CONSTRUCT (15.7M → 28.4M); why is the one open question. Implemented and reverted 3x |
| **180** | correctness CONFIRMED, performance REFUTED | **A UNION-bound variable's join merges solutions in its CONDITION but not its PROJECTION.** The generated SQL has **no `COALESCE` anywhere**: the join is `(v IS NULL OR v = x)` and then projects the UNION side, so the bound value is discarded — 212/213 rows return NULL for a variable the query bound, and this is also the third missing CONSTRUCT triple in 178 that the projection guard never explained. The PERFORMANCE claim is refuted: deleting the UNION removes the disjunction and makes the query **6x SLOWER, 11x the buffers**. What governs cost is whether `ORDER BY` + `LIMIT` can stop early — both perturbations tried so far destroyed that path and cost 10-20x by unrelated routes |
| **181** | CLOSED — superseded | **CLOSED 2026-09-11.** Defect still real; the outcome it wanted is achieved by `rewrite_merge_bgp`, and its own measurement remains the reason not to build what it proposed. Reopen only for a traversal with NO mergeable anchor. **The traversal gate cannot see a text FILTER as a driving set** — `_constrained` needs a constant `(predicate, object)` pair, and `FILTER(CONTAINS(?d,"happy"))` has a variable object, so the end reads as open. Real defect, but the fix is unjustified: priced at 312x on a SIMPLIFIED query and **re-measured on the reference CONSTRUCT it is 8.6x WORSE with ORDER BY+LIMIT and 6% better on buffers for the full set**. The CONSTRUCT spends ~15M buffers regardless of how its entity set is obtained — with the filter, with a pinned set, or with the `frame_entity` collapse on. That unexplained 15M is where the cost lives. Fifth intuition in this family to fail a measurement; see the rule recorded at the end |
| **182** | RESOLVED 2026-09-11 | **RESOLVED — 285,348 frames enumerated before, 341 loops now**, same 425 rows. NOT by the mechanism proposed here: edge-type absorption was built then REVERTED for returning zero rows. The fix is `rewrite_distribute_union` + `rewrite_merge_bgp`. **The frame CONSTRUCT enumerated every frame and applied the selective filter LAST.** Bisected per type-constraint class: EDGE types were 6.8x of it, FRAME 1.5x, ENTITY ~0, SLOT already handled. **Built:** `frame_entity.source_slot_uuid`/`dest_slot_uuid` (removes the projection-guard trade — the collapse now fires while slots are projected) and **edge-type absorption into `edge.edge_type_uuid`**, a column 060 added and the edge rewrite never used, gated by a per-space `rdf:type`-vs-`vitaltype` agreement check. **6,185,137 → 914,457 buffers, verified identical output** (425 rows, zero diff, 6 columns). Remaining: **179** on top. **Blocker: the 2s tautology bound swings the plan 2.9x**, which already invalidated one measurement here — pin the verdict before benchmarking anything |
| **183** | LANDED; target ACHIEVED | **The 339x target is no longer a target — it is measured in PRODUCTION** (2550 triples = 425 x 6, 258 ms warm, via the deployed service). **`frame_entity` hardcoded two `hasKGSlotType` VALUES as if they were schema** (four modules, shipped since 2026-03-09, and 26 of 29 spaces use other values). Replaced by `{space}_frame_slot`, which holds the role as data; the rewrite reads role constants from the QUERY. `frame_entity` retired and dropped — a census found it EMPTY in 38 of 41 spaces. **Also carries the achievable plan for the reference CONSTRUCT: 15,175 buffers / 108 ms against the generator's 5,151,495 / 3,356 ms — 339x.** The shape is trigram CTE → entity set → frame_slot walk → EXISTS type probes. Read for why two earlier hand-written attempts lost: constants resolved in a CTE are unknown at plan time, so PostgreSQL estimated 3 rows where there were 570,696 |
| **184** | RESOLVED — deleted | **RESOLVED 2026-09-10 by DELETING the fast path.** No correct fast path exists: `frame_slot` does not record frame ownership, so the plausible repoint returns the entity FILLING THE SLOT where the caller needs the one that OWNS THE FRAME. **The geo slot handler's `frame_entity` fast path has never executed.** It selects `entity_uuid`, a column `frame_entity` does not have, so it raises on every call — and a bare `except Exception: pass` commented "table might not exist" swallows it, falling through to edge traversal every time on every space since it was written. Confirmed against a real space (`ERROR: column fe_slot.entity_uuid does not exist`). The `except` now logs. NOT repaired: it has never returned anything, so there is no behaviour to preserve and no way to tell from the code what "the owning entity for a slot" was meant to mean |
| **185** | FIXED | **FIXED 2026-09-11 — now 12 write paths across 4 modules, verified by falsification (53 failures when the calls are deleted; previously green).** **The write-path matrix enforces "every write path must maintain every derived table" over ONE file.** `_IMPL` is just `sparql_sql_space_impl.py`; quad-changing paths in `kg_backend_utils.py`, `resync_all.py`, `bulk_export.py` and `data_import_impl.py` are invisible to it — not exempt, not known gaps. **Demonstrated: deleting all three maintenance calls from `kg_backend_utils.py` leaves the suite green.** The test exists because a production edge table went ~25% incomplete when "only ONE of many write paths" maintained it; a guard against that which scans one module reproduces the failure shape one level up. It let a real gap through during the issues/183 retirement |

| **187** | FIXED | **`entity_slot_sort` is unmaintained by six write paths** — three in `kg_backend_utils`, three incremental importers. Each syncs `edge` and `frame_slot` in the same function and skips this one, with no stated reason. A stale row here is a WRONG SORT ORDER (`issues/096`: the sort reads its value straight off the table), not a slow query. Found by widening the `issues/185` matrix — the question that issue listed as NOT ESTABLISHED. **Measured 2026-09-11: NO shortfall on any production space** — the maintenance job repairs this table on an independent probe (one batch of one short type per cycle), so the gap is real in code and invisible in the data. Not urgent. The open question is whether a write burst can outrun a one-batch-per-cycle repair; if it cannot, these paths are arguably EXEMPT rather than broken. Use `coverage`, never `drift` — drift checks the table against the walk that filled it and reported converged on a 1%-full table  **FIXED 2026-09-12** (`78b316b8`): all six wired. Only the DELETE side was ever missing — `add_rdf_quads_batch_bulk` already maintained every derived table — and it must run BEFORE the delete, since the rows are reached through the edge table the delete invalidates. Wired not because the headroom question was answered (it was not) but because `194` found the same defect in both prop tables and the fix touched these same call sites |

## CI and the build environment

| | status | |
|---|---|---|
| **186** | FIXED | **CI restores locally-built wheels across runners, and they SIGILL.** `hnswlib` compiles from source; `~/.cache/pip/wheels` was cached with a PREFIX `restore-keys`, so a binary built on one runner ran on another. Surfaced as `Illegal instruction` (exit 132) **on a docs-only commit**, passed locally, and hit an unrelated branch the same hour. No new release was involved — hnswlib 0.8.0 is from 2023, so version-bisecting could not have found it. **Read this before debugging any CI crash that a code diff cannot explain.** |

## Fixtures and test infrastructure

| | status | |
|---|---|---|
| 055 | FIXED | **FIXED 2026-08-17, re-fixed 2026-08-19.** Loaders and tests target different clusters. Recurred 2026-08-14; needs a decision, not more documentation |
| 084 | FIXED | Load-test setup wrote an empty entity list over a TRACKED file when the space was already seeded, printed it as success, and told you to re-run the command that did it |

| 022 | RESOLVED | **RESOLVED 2026-08-18 — the last class is swept.** E2E list-visibility flake under parallel load; one class not swept |

## The performance suite's own coverage — found 2026-09-12

Six gaps in the measurement apparatus, not in the database. Survey and
sequencing: `planning/planning_performance/perf_coverage_gaps_plan.md`. The
ordering is load-bearing — `190` must come after `188` and `189`, or a fresh
baseline bakes both in.

| | status | |
|---|---|---|
| **188** | PARTLY FIXED | **The gate that was disabled rather than failing.** A metric with no rule in `thresholds.toml` was dropped at a bare `continue` — 106 of 121 recorded names, and 37/108 query cells had no gating metric and no plan shape. The absence is now reported; the rules are still unwritten. Read for the `issues/081` shape repeating  **2026-09-12:** `flips_within_range` — the page-size cliff, and the only unruled cell needing no noise band — is now GATED (`1834b857`). The 91 numeric rules are BLOCKED: sampling 3-4 times is impossible on a suite where one bench ran 15 min and the whole run reached 23% in 25 min. A suite that cannot be run four times cannot have measured thresholds |
| 189 | FIXED | `runner.class` is stamped from an env var, so the committed baseline says `vg-test-docker-clean` and was measured on a seeded 105 GB stack. Also: the aggregate tuple count is the wrong stat — per-fixture size is what decides whether a plan is representative  **FIXED 2026-09-12** (`7ddf8312`, `bd1dbe1f`): class derived from the database, per-space bytes recorded, residency asserted, incomparable pairs refused in ONE line instead of 103 cells. Found two corrections — `lead_nurture_grouped` is 45.7 GB so TWO gated fixtures exceed shared_buffers, and `fixture_live_tuples` reads **0** on the live seeded stack (never ANALYZEd), so my first fix called it clean. **Makes `190` blocking: both committed baselines are now refused** |
| 190 | OPEN | Both baselines promoted 2026-08-22 from a DIRTY tree; 126 commits to `vitalgraph/` since. Blocked on 188 and 189 by design |
| 191 | PARTLY FIXED | The test stack matches production's `shared_buffers` and `effective_cache_size` exactly and diverges on `random_page_cost` (4 vs 1.1) — the right-sized server with the wrong cost model. README corrected; the setting changes plan shapes, so it lands with 190 |
| 192 | OPEN | Whole subsystems with no bench: SPARQL UPDATE/DELETE, vector, geo, text search, export, entity-graph. Writes are 3 cells. R6 re-counted |
| 193 | OPEN | **No bench anywhere touches OPTIONAL, MINUS, BIND, a sub-SELECT or a property path.** `178`-`182` are all shape defects and none is benched. The harness (`query_shape_audit.py`) and the shape enumeration (1,120 DAWG `.rq`) both already exist |
| 194 | FIXED | **Both prop-sort tables are unmaintained by 7 write paths, and were ABSENT from the maintenance matrix** — `185` one level down: the matrix reports only on tables it lists. Worse than `187` because these are read by a FILTER and their gate is a BLOCK-LIST, so a short table serves a plausible SUBSET with a matching count. Prod: cardiff_kg / lead_data / lead_prod all exactly complete, but `wordnet_frames` is missing 3 of 5 properties (329,235 rows) unblocked and unverified. Also: NO local space has the table, and `prop_sort_blocked` fails closed, so `fast_prop_sort` has been inert in dev since it shipped. **Why the backfill missed it:** `backfill_entity_prop_sort` exists but is wired only to the migration — the maintenance job's prop task MEASURES and never repairs — and the coverage probe tests PER-SUBJECT presence, so it reports 0 gaps / all types COMPLETE on the table missing 329,235 rows and would have CERTIFIED it. All three probes share that blindness. **FIXED for the entity side** (`c00a5f83`): coverage counts PAIRS (wordnet_frames now reads 219,490/548,725 SHORT while the three live spaces stay exactly complete, so nothing is newly blocked) and the maintenance loop backfills in bounded, PAIR-SEEDED batches — seeding per entity selects nothing on exactly the spaces that need repair. **Frame side also FIXED** (`82a9e5eb`) — both reasons for deferring it were wrong: the 2-minute limit was a command timeout, and the Assertion-scope mismatch came from a STALE migration docstring (the derivation indexes every frame and resolves form type to a column). All four prod frame tables measured exactly pair-complete, so nothing is newly blocked. `entity_slot_sort`'s probe ADDRESSED too (`00adfc70`) as an ALARM not a gate: counting at the table's key (slot_uuid, context_uuid) costs ~6.5k buffers against ~34M for the exact form, and all three local spaces measured exactly complete so the blindness is latent. Not gated, because a missing slot has no row to attribute to an entity type and the cheap number is an upper bound (value-less slots). **and REPAIRED** (`c6716b0f`) by seeding on the ABSENT SLOTS and resolving their entities via `frame_slot` — the per-entity batch could never close a slot-type gap, so the alarm alone would have been permanent and unactionable. **and GATED** (`44b1a215`): calling it a threshold decision was wrong — the block-list serves on absence, so a detected-but-unblocked shortfall is a wrong answer, not a slow one. The number enters the SAME decision as the entity counts (a separate blocker would be released by the next per-entity sweep, which cannot see it) and both release paths hold while it is nonzero. Space-wide, self-limiting via the repair, and zero-cost on current data. **Write paths wired too** (`78b316b8`), closing all 19 gaps — all of them DELETE-side, since the bulk insert already maintained everything; the slot table drops BEFORE the delete (its rows are found via the edge table the delete invalidates) and the prop tables re-derive AFTER (a delete is a MIN recompute). Hardening `_maintains` to require a CALL rather than a mention then exposed that `bulk_export` truncated only `entity_slot_sort`, leaving both prop tables serving PRE-RESTORE rows once the block lifted |
| 195 | OPEN | **An unfiltered depth-2 traversal plans at 19 TRILLION and hangs the perf suite.** Same query on `sp_graph_synth_10k`: depth 1 costs 741,337, depth 2 costs 19,282,929,239,712 — 26 million times, for one more hop, with 12 nested loops. `traversal_decision` reports "depth 1" for BOTH, so the chain detector does not see the second hop and the rest is emitted flat. Blocks `188` (cannot sample) and `190` (cannot promote). Also: killing pytest does NOT cancel the query — one ran 24 min orphaned  **ROOT CAUSE TRACED:** the detector links two hops when one's DEST var is the next's SOURCE, but `frame_hop` points both edges OUT of the frame, so hops share a source and NOTHING ever links — 2/4/6 single hops at depth 1/2/3. And `_TRAVERSAL_KINDS` still names `frame_entity`, retired in `b94484a9`, whose replacement `frame_slot` was never added |

## Other

| | status | |
|---|---|---|
| 042 | fixed in the converter | CSV import drops datatypes and diverges on term uuids; existing CSV-loaded spaces still need reloading |
| 032 | deferred | `vitalgraph_service_impl` stranded by a sync interface |
| 177 | fixed 2026-09-08 | The `issues/174` grouping-lock degradation could not degrade: a `lock_timeout` aborts the transaction server-side, so "proceeding UNSERIALISED" logged reassurance and then died on `InFailedSQLTransactionError`. Fixed with a savepoint. Read for the shape of the mistake — a fallback path that never ran, whose failure looked like success in the logs |

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
