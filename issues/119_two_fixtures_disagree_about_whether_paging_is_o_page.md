# Two Fixtures Disagree About Whether a Page Costs O(page)

> **Re-measured 2026-08-25: the filed symptom no longer reproduces, and
> the estimate problem is on the OTHER fixture. See section 8.**

## Status: OPEN — observed 2026-08-22 while re-promoting the query baseline.
## Not caused by a code change. Confirmed reproducing, and now encoded in the
## baseline, which is why it needs a home outside a commit message.

`query.kgquery.growth_curve.eq` runs the same equality page against the 10k and
100k lead fixtures. After the fixtures were ANALYZEd on 2026-08-22, the two
swapped plans — Hash Join and Nested Loop traded ends — on **unmodified code**:

    bench       execution        rows examined       plan
    IL-100k   7,503 -> 2,934 ms  100,000 -> 3,713    Hash Join -> Nested Loop
    IL-10k      184 ->   512 ms      365 -> 10,000   Nested Loop -> Hash Join

Re-measured after promotion and still there: IL-10k examines **10,000** rows,
IL-100k examines **3,713**.

## Why this is worth recording rather than shrugging at

The trade is net positive in wall-clock — the large fixture gained 2.5x, the
small one lost 2.8x, and 512 ms is not alarming on its own. That is the reading
that would file this under "the planner made a reasonable choice".

The problem is what the numbers say about the PROPERTY the bench exists to
measure. A page of 25 rows should cost about a page, not about the fixture.

* **IL-10k now examines every entity it has** — 10,000 rows for a 25-row page.
  That is O(fixture), and it is cheap only because the fixture is small.
* **IL-100k examines 3,713** for the same page, which is not O(fixture) at all.

So the two scales now DISAGREE about whether paging is O(page), and the one
that looks healthy is the big one. A property that holds at 100k and fails at
10k is the awkward direction: it means the small fixture — the one used in
edit-loop runs, because it is fast — is the one no longer measuring the thing.

## What it is NOT

Not a code change: the swap happened across an ANALYZE with nothing else
touched. Not noise either, and the distinction matters after
`issues/112`-adjacent confusion the same day: **plan shape changed and rows
examined moved 27x**. Both are structural. A timing ratio moving on its own is
noise; a plan changing which rows it visits is not.

Not caught by the bench's own assertions, which passed throughout.

## Where it now lives

`baselines/query.json`, promoted 2026-08-22, encodes the post-swap state. So a
future run comparing clean does NOT mean the property holds — it means nothing
has changed since the swap. That is the specific hazard of promoting a baseline
over a real difference, and it is why this is filed rather than left in the
promotion commit.

## What would settle it

Establish which side is right, rather than which is faster:

1. Does IL-10k's Hash Join examine 10,000 rows because the planner costs it
   correctly for a 10k table, or because a selectivity estimate is wrong at
   that scale? The fixture has ground truth — `actual_matches` in the manifest.
2. If the estimate is right, then O(page) simply does not hold below some
   size and the bench should say so at 10k rather than implying it does.
3. If the estimate is wrong, it is the same family as `issues/111` — a
   criterion the planner misprices — and the fix belongs there.

Cheap first step: `EXPLAIN` both fixtures' plans side by side and compare
estimated against actual rows at the driving scan. A large gap answers (1)
immediately.


---

## 8. Re-measured 2026-08-25 — the disagreement is gone, the misestimate is not

Ran the diagnostic this issue asks for: `EXPLAIN (ANALYZE)` both fixtures on
`CompanyStateCode = IL`, under the executor's `enable_sort = off` fence,
comparing estimated against actual rows at every scan.

### The filed symptom does not reproduce

| | filed 2026-08-22 | measured 2026-08-25 |
|---|---|---|
| 10k plan | Hash Join, **10,000** rows examined | Nested Loop, **365** |
| 100k plan | Nested Loop, 3,713 | Nested Loop, **3,713** |

`actual_matches` for IL is **365** on 10k and **3,713** on 100k. So both
fixtures now examine **exactly their match count** — not one row more.

The two scales no longer disagree, and the 10k fixture is no longer O(fixture).
Whatever ANALYZE produced the swap on 2026-08-22 has been undone or superseded.

**They agree on O(matches), not on O(page).** A 25-row page still costs the
full match count on both. That was the aspiration behind this issue's title,
and it is not what either fixture does — but it is now a consistent, honest
property rather than a discrepancy, and the bench that records it is called
`page_cost_vs_match_count` for that reason.

### The live finding, on the fixture this issue did not suspect

    100k   Index Only Scan on rdf_quad   est=81  actual=3,713   -> 46x UNDER
           Index Cond: (context_uuid = … AND predicate_uuid = … AND object_uuid = …)
           Index: idx_sp_lead_synth_100k_quad_ctx_pred

    10k    no under-estimated scan anywhere in the plan

§7 asked whether the 10k estimate was wrong. It is not — 10k's estimates are
accurate. **The 46x error is on 100k**, and it is the predicate/object
correlation family: PostgreSQL multiplies P(predicate) by P(object) as though
independent, when a given object value occurs almost exclusively with one
predicate.

### Why the standard remedy is already applied and cannot work

Extended statistics for exactly this correlation exist on both fixtures:

    stat_sp_lead_synth_100k_quad_po   ON (predicate_uuid, object_uuid)
    kinds: n-distinct + MCV, populated, stxstattarget = 1000

So someone reached this conclusion before and tuned it — the target is 1000,
not the default 100. It still does not help, and the reason is structural:

    distinct (predicate, object) pairs   16,644,618
    MCV entries at target 1000           ~1,000        (0.006%)

An MCV over pairs cannot cover a 16.6M-row value space. The IL pair holds
3,713 rows against an average of ~3 per pair, so it is a heavy hitter — but
the top 1,000 slots go to pairs heavier still (type predicates, enums,
booleans), and IL is crowded out. Raising to the maximum target of 10,000
moves 0.006% to 0.06%.

**n-distinct does not apply here.** Extended n-distinct informs GROUP BY
cardinality, not equality-conjunction selectivity, so the `d` half of that
statistic was never going to affect this plan.

### So the answer to §7

1. The estimate IS wrong — 46x — but on **100k**, not 10k.
2. It is `issues/111`'s family, and the usual fix has already been applied and
   is insufficient for a reason that will not change with tuning.
3. More statistics is not the next move. Either the plan has to be robust to
   the misestimate — which is what the `needs_ordered_scan` fence already does
   elsewhere — or the estimate has to come from somewhere other than a
   pair-MCV.

### Do not ANALYZE these fixtures to "fix" this

`docker-compose.test.yml` exempts benchmark fixtures from the maintenance job
for `issues/112` reasons: a cycle re-ANALYZEd them mid-session and a bench read
+91% worse on identical code. Re-ANALYZE is what produced the swap this issue
was filed about. `last_analyze` and `last_autoanalyze` are both NULL and
`n_mod_since_analyze` is 0, so nothing has drifted; the stats are as loaded.

### The baseline

`baselines/query.json` encodes the post-swap state from 2026-08-22. The 10k
plan has since changed back, so **the baseline is now stale in the other
direction** and a clean comparison no longer means what it did. Worth
re-promoting deliberately, with this measurement attached, rather than letting
the next run promote it silently.
