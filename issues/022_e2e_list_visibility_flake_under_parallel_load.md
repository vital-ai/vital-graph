# E2E: intermittent "X appears in the list" failures under full parallel load

## Status: OPEN

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
