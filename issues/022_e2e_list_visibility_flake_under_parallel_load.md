# E2E: intermittent "X appears in the list" failures under full parallel load

## Status: RESOLVED 2026-08-18 — the last class is swept

The writer-isolation follow-on under "Remaining work" is done:
`kgframes-sorting`, `kgrelations-sorting`, `kgrelations-crud` and `files-crud`
now create and drop their own spaces via `tests/space-fixtures.ts`. Readers keep
sharing the seeded fixture, per the rule the evidence supported.

Verified all four use only `ADMIN_USER`/`ADMIN_PASS`/`SPACE_ID`/`GRAPH_ID` from
seed-constants and none of the seeded entities or frames, so the "cheap to
isolate" claim held.

**`files-crud` needed a space PER DESCRIBE.** Its two blocks are `serial`
internally but run in separate workers under `fullyParallel`, and a file-level
`beforeAll` runs once per worker — so one worker's `createSpace` dropped the
space the other was using, surfacing as `400 Failed to add space with tables`,
which names nothing about the race. `indexes-crud` documents this exact hazard
and it was reproduced anyway.

Three full runs, measured rather than assumed:

    baseline          3 failed / 270 passed
    with the change   3 failed / 270 passed   (twice)

**One intermittent, recorded not claimed.** An earlier run showed a fourth
failure — `spaces-crud` "create a new space via the UI" — which did not recur in
two subsequent full runs and passes both alone and alongside all four isolated
specs. If it returns, the suspect is the isolated spaces appearing and
disappearing in the spaces list under load, which is this issue's shape moved
from object lists to the spaces list.

**The three constant failures are environmental, not this issue.** `global-setup`
warns that 15 foreign spaces are present (this machine's perf fixtures) and that
`apitest_37a59eb5` sorts before `e2e_test_space` — which is what pushes it off
the dashboard summary the two dashboard tests assert on. The guard added under
item 3 did its job; it named the cause on line 3 of the run log.

**278/278 twice, including on a cold build.** Every *observed* failure has been
traced and fixed across four passes; the header below is the first pass only,
kept for the narrative.

The recurring shape, across every pass: **a cleanup or a check that silently did
nothing** — a delete missing a required parameter, a lookup using a parameter
name the API ignores, a route form that 405s, an assertion satisfied by the page
it started on. Each hid a second problem until it was fixed. When something here
looks impossible, check whether the thing you assume is running actually runs.

**What remains is one unswept class, not a live flake** — see "Remaining work"
at the end.

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
fix. `graph-objects-crud.spec.ts:109` was the one confirmed outstanding; it has
since been fixed (verified 2026-08-04 — it now reads every row in one
`rows.evaluateAll()` and cites this section). (`graph-visualization-crud.spec.ts:107` also uses `nth`, but to pick a
single `<select>`, not in a loop; it is not affected.)

### B. Rapid control changes can leave a stale list — PRODUCT side, FIXED on 4 pages

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

**Latest (after the fourth pass and the issues/018 work): 278/278, twice**,
including on a *cold* build — the case that used to fail. Container start time
unchanged across both runs, so neither was disturbed.

### Environment warning — how to tell a real red run from a disturbed one

Several runs during this work were invalidated by the stack changing underneath
them. The failure signature is unmistakable once you know it: **dozens of
"did not run"** plus failures in trivial page-load specs (234/14, 205/19,
125/79 across three such runs). No product bug looks like that.

**The reliable check is the container's start time**, before and after a run:

```
docker inspect vitalgraph-test-app --format '{{.State.StartedAt}}'
```

If it moved, the app was recreated mid-run and the result means nothing. Two
runs were invalidated exactly this way (`20:20:54`, then `20:25:11`).

**⚠️ Do NOT use `docker logs … | grep -c apitest_` as that check** — an earlier
version of this section recommended it, and it is wrong. Those log lines are
overwhelmingly `GET /api/graphs/graphs?space_id=apitest_X`,
`GET /api/fuzzy-mappings?space_id=apitest_X` and similar: **reads issued by the
e2e suite itself**, because leftover `apitest_*` spaces sit in the space
selector and every page that lists spaces fetches against them. 97 such
requests appeared during a run with no API suite running at all. Verify by
looking for writes (`POST`/`DELETE`) rather than counting hits, or just use
`ps aux | grep pytest`.

A genuine concurrent `pytest tests/api` run *is* disruptive when it happens — it
writes into shared spaces including `sp_kg_types` and drove the app container to
98% CPU — but it was present for fewer of these runs than first reported.

Separately, those leftover `apitest_*` spaces sort ahead of `e2e_*`
alphabetically, which is how one became the default selection that exposed the
`Indexes.tsx` race above.

### Fourth pass — two more silent-cleanup failures (files) and the cold-start test

Introducing document uploads (issues/018) surfaced three more, all of the same
family as everything above: **a cleanup that silently did nothing**.

1. **`DELETE /api/files` without `graph_id` is a no-op.** It returns
   `success:true, status:"no_op"` — "File node not found — no deletion needed" —
   while the object plainly exists in another graph. `files-crud.spec.ts`
   omitted the parameter, so its cleanup had *never* deleted anything: **103
   orphaned FileNodes** had accumulated in the shared graph, eventually pushing
   that spec's own fixture off page 1 of the Files list. Same visible symptom as
   the original flake, different root cause. Fixed, residue purged.

2. **Fixing that cleanup exposed a latent shared-fixture bug it had been
   masking.** `files-crud` has two `describe` blocks that ran in parallel and
   shared one `cleanupAll()` sweeping everything matching `"E2E"`. While the
   delete was a no-op this was invisible; the moment it worked, each block began
   deleting the other's fixtures mid-run. Each block now tracks and cleans only
   its own URIs — the partitioning `entity-registry-lookups.spec.ts` already
   documents. *A dead cleanup can hide a second bug; expect one when you fix
   one.*

3. **Uploads orphan FileNodes.** Deleting a KGDocument does not remove the
   FileNode holding its original bytes, and a document deleted through the UI is
   gone before per-test cleanup can look up its URI. The spec now sweeps by URI
   shape (`urn:kgdocument:…:source`), which covers every path. Verified by
   count: 2 → 0 across two consecutive runs, stable.

**The post-rebuild segmentation failure is also resolved** — and it was a real
product inefficiency, not test flake. `kgdocuments-crud.spec.ts` "trigger
segmentation" failed on the first run after a rebuild three separate times and
passed on every warm run. Cause: `_get_tokenizer()` called `get_provider(...)`
with **no cache key**, building a fresh tokenizer and ONNX `InferenceSession` on
*every* segmentation, then checking an attribute the provider does not have and
returning `None` — full model-load cost, no benefit, per job. The model is now
warmed once at startup before the worker starts, and both call sites share the
cached instance. The spec passes 17/17 on the first cold run.

## Note on shared fixtures

Two of the three fixed causes trace back to the same structural choice: specs
share `e2e_test_space` / `urn:e2e:graph:main` and assert against page 1 of a
list other specs are concurrently filling. Search-scoping the lookups fixes the
symptom. **Sharing itself is not the problem — writing into a shared fixture
is;** see "Remaining work" item 2 for why per-spec spaces would be the wrong
remedy and what to do instead. `tests/api` also writes into the shared `sp_kg_types`
space, so a concurrent pytest run against the same stack can perturb the e2e
suite.

## Remaining work (2026-08-04)

Verified against the code, not taken from the notes above.

### 1. ~~The overlapping-fetch race is guarded on 4 pages of ~18~~ ✅ DONE (2026-08-04)

Extracted `useLatestRequest` (`frontend/src/hooks/useLatestRequest.ts`) and
applied it to **all 18 list pages**. Zero hand-rolled guards remain.

Two things the sweep turned up:

- `EntityRegistry.tsx` and `EntityRegistryDetail.tsx` **already had their own**
  guards (`fetchIdRef`/`relReqIdRef`), with a comment describing the same bug —
  someone hit this independently and solved it locally. The table above listed
  `EntityRegistry` as unguarded; that was wrong. Seven hand-rolled copies
  existed in total, which is the strongest argument for the shared hook.
- The hook deliberately discards the response rather than aborting the request.
  Aborting would mean threading an `AbortSignal` through every service call and
  does not fix the bug — discarding is what makes the newest write win.

Pages now covered: `KGFrames`, `KGRelations`, `KGEntities`, `Indexes`,
`IndexMappings`, `EntityRegistry`, `EntityRegistryDetail`, `Triples`, `KGTypes`,
`KGDocuments`, `AgentRegistry`, `Files`, `FtsIndexes`, `VectorIndexes`,
`FuzzyMappings`, `SearchMappings`, `GeoShapes`, `GraphObjects`.

### 2. Structural: writers should isolate; readers should keep sharing

Two of the three first-pass causes trace to specs sharing `e2e_test_space` /
`urn:e2e:graph:main` and asserting against page 1 of a list other specs are
concurrently filling. Search-scoping fixed the symptom.

**Revised 2026-08-05 — "per-spec spaces" is the wrong prescription.** The
earlier note here recommended giving every spec its own space, as
`indexes-crud` does. Checking what the specs actually do says otherwise:

| | count |
|---|---|
| Specs using the shared seeded space | ~20 |
| Of those, specs that **write objects** into it | **5** |
| Specs already owning an isolated space | 2 (`indexes-crud`, `triples-crud`) |

Most specs are **readers of a read-only fixture**. Isolating them means seeding
each one — including the FTS and vector indexes, whose ONNX population is the
slowest thing in the suite — multiplying the expensive part by ~20 to fix a
problem caused by 5. Worse, some specs are *inherently* about shared state
(dashboard counts, the spaces list, page navigation); isolating those changes
what they test rather than stabilising it.

Note what is **not** an objection: cross-page workflows. A spec can own one
space and drive Entities → Frames → Documents against it — per-*spec* is not
per-*page*, and `entity-graph-paging` already works this way with its own graph.

Every failure attributed to "sharing" was in fact **a writer polluting the
shared graph**:

- `kgframes-sorting` adds ~30 fixture frames → pushed `kgframes-crud`'s frame
  off page 1
- `files-crud` leaked FileNodes (the upload work added more) → pushed its own
  fixture off page 1
- `kgrelations-sorting` — same shape

So the rule that fits the evidence is **writers isolate, readers share**.

#### Follow-on step (not yet done)

Give an isolated space to the writers that are cheap to isolate — they need only
plain objects, nothing seeded:

- `kgframes-sorting.spec.ts`
- `kgrelations-sorting.spec.ts`
- `kgrelations-crud.spec.ts`
- `files-crud.spec.ts`

Leave `kgdocuments-crud.spec.ts` sharing: it depends on the seeded FTS/vector
indexes, so isolating it means paying ONNX population per run.

Use the existing `createSpace`/`dropSpace` helpers in `tests/space-fixtures.ts`,
as `indexes-crud` and `triples-crud` already do.

**Priority: low.** The symptoms this prevents are already handled from three
directions — search-scoped lookups, the `useLatestRequest` guard, and the
seeded-fixture precondition check (item 3), which turns residue into a clear
up-front failure instead of a confusing one. This is tidiness and future-proofing
now, not a live defect.

### 3. ~~Undecided: should the seeded-space fixture assert its own preconditions?~~ ✅ DONE (2026-08-05)

Yes — added to `e2e/global-setup.ts`, which now verifies the seeded fixture
after the health check and before any spec runs.

- **Fails** when the seeded graph has missing or unexpected entities, naming the
  offending URIs and how to clear them.
- **Warns** about foreign spaces, flagging any that sort ahead of
  `e2e_test_space` and could become a page's default selection.

Verified by planting the exact residue that caused the original failure. What
previously surfaced as `expected 3, received 4` in two unrelated specs now
fails once, up front, as:

```
Seeded space e2e_test_space/urn:e2e:graph:main has 1 unexpected entity:
urn:e2e:probe:e1 ("Probe").
Specs assert exact counts against this graph, so leftovers surface as
"expected 3, received 4" in unrelated tests.
Delete them, or reset the stack:
  docker compose -f docker-compose.test.yml down
  docker compose -f docker-compose.test.yml up -d --build --wait
```

Cheap, and it would have saved time on both occasions it was needed.

### Not remaining

- `graph-objects-crud.spec.ts:109` — fixed.
- `data-import-export-crud.spec.ts:90` — never reproduced; tracing is on if it
  recurs.
- The concurrent-`pytest` interference is an environment caveat, not a defect.
