# E2E: intermittent "X appears in the list" failures under full parallel load

## Status: PARTIALLY RESOLVED — root causes identified, four fixed, two open

**Resolution (2026-08-04).** With traces finally being captured (see below),
the "read-after-write visibility" framing turned out to be wrong. Neither cache
invalidation nor request sequencing was involved in any failure examined. Three
distinct causes were found and fixed, plus one unrelated product bug:

| # | Cause | Evidence | Fix |
|---|---|---|---|
| 1 | **Traces were never captured locally** — `trace: 'on-first-retry'` with `retries: 0` | config read | `trace: 'retain-on-failure'` (`playwright.config.ts`) |
| 2 | **Shared list + paging, not a stale read** — the seeded space/graph is shared with the frame sorting specs (~30 fixture frames); with a 25-row page the created frame is simply not on page 1 | trace: list `total_count: 51` without the frame, `search` for the same frame `total_count: 1` — **the server had it all along** | search-scoped lookup in `kgframes-crud.spec.ts`, `search-ui.spec.ts` |
| 3 | **A vacuous assertion hid a lost write** — `expect(page).toHaveURL(/\/kg-types/)` is satisfied by the create page's own URL (`/kg-types/new?mode=create`), so the create test passed with no POST ever issued; the failure surfaced one test later as an empty list | trace: list returned `total_count: 0`; server logs show no `POST /api/graphs/kgtypes` in the run window | anchored URL + `waitForResponse` on the create POST in `kgtypes-crud.spec.ts` |
| 4 | **`networkidle` waits** in `indexes-crud.spec.ts` (six of them) | Playwright guidance; run-A failure sat directly after one | `selectSpaceAndSettle()` waits on the three actual list responses |
| — | **Product bug, unrelated to load:** agent edit form seeded `agent_type` from `agent_type_label` but submits it as `agent_type_key` | trace: `PUT /api/agents/agent` → 200 `{"success": false, "message": "Unknown agent type: E2E Bot"}` | `AgentRegistryDetail.tsx` now seeds from the key, and `handleSave` inspects the `success` envelope instead of treating HTTP 200 as success |

Section B — the request-sequencing bug — was then **confirmed with trace
evidence and fixed**; see "Section B confirmed" below. Full-suite results
progressed 7 failed → 4 → 1 → **273/273 green**, with a later run showing 2
failures in two previously-unexamined specs (listed under "Still open").

**What this rules out.** No evidence was found for cause 1 (entity/count cache
`NOTIFY` timing) or cause 2 (fast-path/`rdf_stats` lag) in any failure examined.
The "created object does not appear" symptom was, in every traced case, either
paging over a shared list or a write that never happened.

## Summary

Full local runs of the Playwright suite fail intermittently — roughly one test
per run, in a *different* spec each time. Every observed failure is the same
shape: **create an object via the UI or API, then assert it shows up in a list
view**. Each failing test passes reliably when its spec is run alone.

This predates the frame/slot sorting work (it was first seen before those specs
existed) and rotates through specs unrelated to any recent change.

## Observed failures

Four consecutive full runs (`npx playwright test`, 260–266 tests, local, all
workers):

| run | failing test | spec |
|---|---|---|
| A | `Vector index appears in the list` | `indexes-crud.spec.ts:145` |
| B | `sorting by list index ascending is numeric…` | `kgrelations-sorting.spec.ts:177` |
| C | `the fixture is fully visible on one page` + `new type appears in the types list` | `kgframes-sorting.spec.ts:147`, `kgtypes-crud.spec.ts:79` |
| D | `triple appears in the list via filter` | `triples-crud.spec.ts:64` |

Other full runs in the same session passed 260/260 outright.

Run B and C's sorting-spec failures had two causes local to those specs, both
since fixed (shared-space page contention, and fixed `waitForTimeout` sleeps —
see `planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md`
step 9). After those fixes the sorting specs pass 3/3 consecutive runs on their
own, yet the suite-wide flake continued in *other* specs — which is what
separates the two problems.

## The pattern worth chasing

All failing tests assert **list visibility shortly after a write**:

- `kgtypes-crud.spec.ts:79` — "new type appears in the types list"
- `triples-crud.spec.ts:64` — "triple appears in the list via filter"
- `indexes-crud.spec.ts:61,145` — "FTS/Vector index appears in the list"

That is a read-after-write visibility question, not a UI-rendering question.

**Caveat on the framing (added on review):** treating these as *one* failure
with *one* cause is an assumption, not a finding. The four failures read
through different server paths — the indexes list reads index-registry
metadata, `kgtypes` reads `sp_kg_types` quads via `list_objects`, `triples`
reads the quad table. A cause that explains all four has to be generic
(contention, or a test-side pattern shared across specs); a cause specific to
the entity/count cache cannot explain the indexes failure. Expect two or three
causes here, not one.

Candidate causes:

1. **Cache invalidation timing.** The entity/count cache is invalidated via
   PostgreSQL `NOTIFY` (`vitalgraph/signal/signal_manager.py`, handled in
   `vitalgraphapp_impl.py:707-718`). If a list read races the notification, it
   can serve a pre-write cached result. Under parallel load the window widens.
   *Scope limit:* that handler invalidates `_entity_graph_cache` and
   `_count_cache`, both keyed on `(space_id, graph_id, entity_uri)`. It is not
   on the path for the indexes list, and probably not for the kgtypes list.
2. **List paths with their own caches or fast paths** — e.g.
   `fast_typed_subject_page`, `rdf_stats`-derived counts — that may lag a
   just-committed write.
3. **Debounced search inputs** (400 ms in `KGFrames`/`KGEntities`) firing a
   fetch that resolves out of order under load, so a later response overwrites
   an earlier, more correct one. *None of the four observed failures does this*
   — each navigates fresh and issues a single list fetch — so this is a real
   bug (see section B) but not an explanation for them.
4. Plain resource contention: the suite runs unbounded workers alongside
   Docker + PostgreSQL on the same machine.
5. **`networkidle` waits.** `indexes-crud.spec.ts` calls
   `waitForLoadState('networkidle')` six times (lines 37, 66, 75, 105, 150,
   159), including immediately before the assertion at line 152 that failed in
   run A. `networkidle` is explicitly discouraged by Playwright and is
   unreliable whenever anything polls in the background; under load it can
   resolve at the wrong moment. This is the most specific available
   explanation for run A.
6. **Asymmetric timeout budgets.** `kgtypes-crud.spec.ts:84` allows 10 s for
   the first row to appear but line 87 allows only 5 s for the target row.
   Under unbounded workers next to Docker + PostgreSQL, 5 s is thin.
   Rebalancing that to 10 s is not the same thing as papering over a
   read-after-write bug (see the closing section) — it is correcting an
   inconsistency within one test.
7. **Page-1 membership.** `frontend/src/pages/KGTypes.tsx:60` pages at 25 with
   no user-facing sort, and the underlying query orders by `q.subject_uuid`
   (`vitalgraph/db/sparql_sql/sparql_sql_db_objects.py:331`) — stable, but
   effectively arbitrary. If `sp_kg_types` holds ≳25 types, whether the new
   type lands on page 1 depends on residue from earlier runs. Cheap to check:
   `GET /api/graphs/kgtypes?space_id=sp_kg_types` and compare `total_count`
   against 25.

Cause 1 or 2 would be a **product** bug worth fixing; 3 is a UI bug; 4, 5, 6
and 7 are test-infrastructure issues. They are distinguishable — see below.

## Why it is not currently visible in CI

`e2e/playwright.config.ts:13-14`:

```ts
retries: process.env.CI ? 2 : 0,
workers: process.env.CI ? 2 : undefined,
```

CI retries twice and caps at 2 workers, so it both masks the failure and
reduces the contention that triggers it. Local runs use unbounded workers and
no retries, which is why this surfaces locally. **A green CI run is therefore
not evidence the problem is absent.**

## Note on "N did not run"

Failing runs also report "2–6 did not run". Those are the remaining tests of a
`test.describe.configure({ mode: 'serial' })` block, which Playwright skips
after a failure in the block. They are a consequence of the failure, not
additional failures.

## Two concrete causes found (and one fixed)

Investigated while stabilising `kgframes-sorting` / `kgrelations-sorting`.
Both are worth checking in the other affected specs.

### A. Per-row DOM reads race React re-renders — TEST side, FIXED

The sorting specs collected rows with

```ts
for (let i = 0; i < await rows.count(); i++) {
  const text = await rows.nth(i).innerText();   // re-queries the DOM per row
}
```

`nth(i)` re-resolves against the live DOM on every iteration, so a re-render
mid-loop can hit a **detached node**. Under `toPass` this retries, but when the
list is refetching continuously it can keep losing for the full timeout — which
presented as "row count never reached N" even though the page had settled.

Fixed by reading every row in one call: `locator(...).allInnerTexts()`. That
alone took the two sorting specs from failing most full runs to passing 3/3 in
isolation and most full runs.

**Other specs use the same `nth(i)` pattern** and are candidates for the same
fix. Confirmed still outstanding: `graph-objects-crud.spec.ts:109` (per-row
`inputValue()` inside a `for` loop over `rows.count()`) — the exact pattern
above. (`graph-visualization-crud.spec.ts:107` also uses `nth`, but to pick a
single `<select>`, not in a loop; it is not affected.)

### B. Rapid control changes can leave a stale list — PRODUCT side, NOT fixed

`KGRelations` (and the other list pages) fire a fetch per control change with
**no request sequencing or cancellation**. Changing the source filter and then
the page size in quick succession issues two overlapping requests; if the
FIRST response lands last it overwrites the second, and the table then shows a
stale page and never refetches — there is no further trigger.

Reproduced indirectly: the paging test only became reliable once it waited for
the filter's fetch to settle before touching the page-size control.

This is the same shape as cause 3 in the list above. It is a real bug a user
can hit — type and immediately click, and you can be left looking at a
pre-write response — but on review it does **not** explain any of the four
observed failures, each of which navigates fresh and issues a single list
fetch. It should be **split into its own product issue** rather than tracked
here, where it makes the diagnosis look better-supported than it is. A fix
would tag requests with a sequence number (or an `AbortController`) and drop
responses older than the newest in flight.

## Blocker: traces are not being captured locally

`e2e/playwright.config.ts:19` sets `trace: 'on-first-retry'` and line 13 sets
`retries: 0` outside CI. **There is no first retry locally, so no trace is
captured on a local failure.** Every "investigate on the next failure" step
below is a no-op until this changes.

Fix before the next full run — either flip the config to
`trace: 'retain-on-failure'`, or run with `--trace on`. Four failures have
already been spent producing no network evidence; do not spend a fifth.

## Suggested investigation

1. **Turn traces on** (above). Nothing else in this list works without it.
2. **Check `sp_kg_types` size** — one API call, may close out the kgtypes
   failure outright (cause 7).
3. **Replace the `networkidle` waits** in `indexes-crud.spec.ts` with
   assertions on the actual list state (cause 5), and rebalance the
   `kgtypes-crud.spec.ts:87` timeout to 10 s (cause 6).
4. **Apply the `allInnerTexts` fix** to `graph-objects-crud.spec.ts:109`.
5. **Instrument rather than guess.** With traces on, capture whether the API
   returns the missing object at the moment of failure. If the API response
   omits it, the bug is server-side (causes 1/2). If the response contains it
   but the table does not render it, the bug is client-side.
6. **Bisect the contention.** Re-run the full suite with `--workers=2` (traces
   on). If the flake disappears, contention is a necessary trigger; if it
   persists, there is a genuine ordering bug.
7. **Retry-to-reproduce.** Note `--repeat-each` is NOT a valid probe for specs
   whose fixture is created in `beforeAll` and torn down in `afterAll` — later
   repeats then run against deleted data and fail for that reason alone.
   Re-running the whole spec repeatedly is the honest probe.
8. If it proves to be cache invalidation, the fix belongs in the notification
   path, not in the tests — adding waits to the specs would hide a real
   read-after-write bug that users could hit.

## Do not "fix" by enabling local retries

Setting `retries` locally would make the suite green while leaving cause 1/2 —
a genuine stale-read — undiagnosed. Retries are appropriate only once the cause
is known to be environmental.

This is not an argument against every timing change: correcting an unbalanced
timeout within a single test (cause 6), or replacing `networkidle` with a real
assertion (cause 5), removes test-side noise rather than hiding a product bug.
The line is whether the change makes the test wait for *the thing it is
asserting* or merely wait *longer in general*.

## Section B confirmed — and fixed

The overlapping-request bug hypothesised in section B was reproduced with a
trace, from `kgframes-sorting.spec.ts:193`. Request timeline (same page, ms
resolution):

| started | duration | page_size | search | sort_by |
|---|---|---|---|---|
| 47.786 | 45 ms | 100 | yes | — |
| 47.794 | 34 ms | 100 | yes | `hasFrameSequence` |

The **sorted** response completed at 47.828; the older **unsorted** one at
47.831 — 3 ms later — and overwrote it. The table then showed unsorted rows
with no trigger for another fetch, so the test waited the full 20 s for a row
order that could never arrive. This is a user-visible bug, not a test artifact:
type a search and immediately pick a sort and you can be left looking at the
unsorted list.

Fixed with a fetch sequence number in `KGFrames.tsx`, `KGRelations.tsx` and
`KGEntities.tsx`: each fetch takes a ticket, and a response whose ticket is no
longer current is discarded instead of being written to state (`loading` is
likewise only cleared by the newest fetch).

Two test-side paging loops had the matching defect and were fixed with them:
`kgframes-sorting.spec.ts:223` and `kgrelations-sorting.spec.ts:306` clicked
"next" and then waited on ROW COUNT, which is identical on every full page — so
the assertion passed instantly against the stale page and collected the same
page twice. They now wait for the first row to change, the same rule
`entity-graph-paging` already documented.

## Resolved since

- **`entity-graph-paging.spec.ts:238`** — not a product bug. The loop paging to
  the last frame page used `waitForLoadState('networkidle')`, which returned
  before React re-rendered; the card selector then took `.last()` of the STALE
  page. Traced: the app requested slots for `…:f005` (last card of page 1)
  instead of `…:f000` (the only frame with 40 slots), so the slot pager never
  appeared. Also, every card renders `frame-slot-count` (it shows "0 slots"),
  so filtering on it narrowed nothing. Now waits for the rendered page to
  change and addresses frame 0 by `data-frame-uri`. 3/3 consecutive passes.
- **`entity-lifecycle.spec.ts:23` / `kg-objects.spec.ts:17`** (`toHaveCount(3)`
  got 4) — stale data, not a bug: `urn:e2e:probe:e1` ("Probe", created
  2026-08-04T03:15) was residue in the seeded space and nothing in this repo
  creates it. Deleted; the space is back to its 3 seeded entities. Still worth
  deciding whether the seeded-space fixture should assert its own preconditions
  rather than trusting the stack's state.

## Second pass — the five "still open" items

All five were investigated. Four had identifiable causes; a fifth did not
reproduce. Two more were found in the process. The recurring theme is
**cleanup helpers that silently do nothing** and **assertions that pass
without the write happening**.

### Fixed

1. **`entity-registry-lookups.spec.ts:118`** — not a flake at all; by this
   point it failed 3/3. `cleanup()` passed `limit: 50`, but the endpoint's
   parameter is `page_size` (default 20, max 100), so `limit` was ignored.
   Delete is a SOFT delete: the row survives with `status: 'deleted'` and keeps
   matching the search. Once 20 tombstones accumulated ahead of the live row
   (measured: 30 rows per fixture name, the first 20 all deleted), cleanup's
   window held only tombstones, deleted nothing, and each run added another
   LIVE duplicate — so `getByText(SOURCE_NAME)` eventually matched two rows and
   failed strict mode. Cleanup now pages through all results and skips
   already-deleted rows. 3/3 green, and it self-heals the accumulated
   duplicates.
2. **`search-execution.spec.ts:58`** — the test switched to FTS mode and
   searched without waiting for the index list, so the search ran with an empty
   index name. The generated SPARQL interpolates that into the table name,
   producing `e2e_test_space_fts_` — the server log shows
   `relation "e2e_test_space_fts_" does not exist`. Fixed on both sides:
   `SemanticSearch.tsx` now refuses an index-backed search with no index (and
   disables Search while indexes load) instead of issuing a query that cannot
   work, and the test waits for `#indexName` to be populated.
3. **`graph-visualization-crud.spec.ts:60`** — `waitForTimeout(500)` after
   changing the space. The select reflects the ACTIVE SESSION's space, updated
   asynchronously, so under load the search ran against the previous space.
   All four fixed sleeps in that spec replaced with
   `expect(spaceSelect).toHaveValue(SPACE_ID)`.
4. **`graph-visualization-crud.spec.ts:177`** — `handleNewSession` returns
   early when no space is known, so clicking "New session" before the default
   session exists is a SILENT no-op and "Session 2" never appears. The two
   sibling tests already guarded against this; this one did not. The button is
   now `disabled={!spaceId}` (so the click waits rather than vanishing) and the
   test waits for Session 1 first.
5. **`data-import-export-crud.spec.ts:90`** — did not reproduce in repeated
   runs, in isolation or under full load. Consistent with the original guess of
   a cold-start timeout right after a stack rebuild. Left as-is; it now
   captures a trace if it recurs.

### Found while verifying

6. **`spaces-crud.spec.ts:38`** — `cleanupCrudSpace()` called
   `DELETE /api/spaces/{id}`, which is not a route: it returned **405** every
   time, so cleanup never ran. When a prior run left `e2e_crud_space` behind,
   the create test failed with
   `500 {"detail": "Error adding space: 400: Failed to add space with tables"}`.
   Now uses `DELETE /api/spaces?space_id=…` (the form `space-fixtures.ts`
   already used) and throws on 405 rather than silently skipping.
7. **`triples-crud.spec.ts:43`** — another vacuous assertion, same class as
   cause 3 above. In one full run the server log contains **no insert request
   for that space at all**, yet "add a triple via the UI" passed and the next
   test then found an empty list. The test now waits for the insert POST and
   asserts its `success`.

### Convention notes (not fixed)

- `POST /api/spaces` returns **500** when the space already exists, and
  `DELETE /api/spaces` returns **404** for a missing space. Both are domain
  outcomes and, per the project's convention, belong in a 200 body. Tracked
  separately in `issues/034_spaces_endpoint_raises_for_domain_outcomes.md`,
  which also documents why the intended 400 surfaces as a 500.

### Third pass — `Indexes.tsx` had the same stale-overwrite bug

On the first clean-stack full run, `indexes-mappings.spec.ts:34` failed: the
seeded vector index was missing from the list. The trace shows the same
overlapping-request defect as section B, in a page that had not been patched:

| started | duration | request |
|---|---|---|
| 41.364 | 62 ms | `vector-indexes?space_id=e2e_test_space` (the selected space) |
| 41.356 | 80 ms | `vector-indexes?space_id=apitest_8360d4c5` (the default) |

The selected space's response completed at 41.426; the previous space's at
41.436 — 10 ms later — and overwrote it. The table then showed the wrong
space's indexes with no trigger for another fetch. Same `fetchSeq` guard
applied to `Indexes.tsx`.

Note the default space was `apitest_8360d4c5`, a leftover from the API test
suite; it sorts first and so becomes the initial selection, which is what made
the race reachable here.

**This class is not fully swept.** The guard is now on `KGFrames`,
`KGRelations`, `KGEntities` and `Indexes` — the four with direct trace
evidence. Other list pages fetch on control change without sequencing and are
candidates if a similar failure appears: `GraphObjects`, `Triples`, `KGTypes`,
`KGDocuments`, `Graphs`, `Files`, `FtsIndexes`, `VectorIndexes`,
`FuzzyMappings`, `SearchMappings`, `IndexMappings`, `GeoShapes`,
`EntityRegistry`, `AgentRegistry`. The real remedy is a shared
fetch-sequencing hook rather than repeating the guard per page.

### Result

Three consecutive full runs on an idle stack after the `Indexes.tsx` fix:
**273/273, 273/273** (the run before the fix was 272/273, failing only
`indexes-mappings.spec.ts:34`).

### Environment warning

A `pytest tests/api` run against the same stack (`localhost:8002`) was found
running concurrently with some of these suite runs, started outside this work.
It writes into shared spaces including `sp_kg_types` and pushed the app
container to 98% CPU. **Full-suite results are not trustworthy while it runs** —
one run taken during that window showed mass failures (234 passed, 14 not run)
in basic page-load specs. Check for it (`ps aux | grep pytest`, or
`docker logs --since 60s vitalgraph-test-app | grep -c apitest_`) before
reading anything into a red run. The three green runs above were taken after it
finished, on an idle stack.

It also leaves `apitest_*` spaces behind, and those sort ahead of `e2e_*`
alphabetically — which is how they became the default selection that exposed
the `Indexes.tsx` race above.

## Note on shared fixtures

Two of the three fixed causes trace back to the same structural choice: specs
share `e2e_test_space` / `urn:e2e:graph:main` and assert against page 1 of a
list other specs are concurrently filling. Search-scoping the lookups fixes the
symptom. The structural fix — per-spec spaces, as `indexes-crud` already does —
would remove the class. `tests/api` also writes into the shared `sp_kg_types`
space, so a concurrent pytest run against the same stack can perturb the e2e
suite.
