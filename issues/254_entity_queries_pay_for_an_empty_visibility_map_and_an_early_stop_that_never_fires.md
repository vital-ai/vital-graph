# 254 — Entity fuzzy queries pay for an empty visibility map, and for an early stop that never fires

## Status: OPEN, measured on production 2026-09-29. Neither finding is a
## correctness defect — the numbers are simply higher than they need to be, and
## the two causes are independent. The VACUUM is the cheap one and is already
## recorded as an unactioned item in `issues/251`; this issue is what makes it
## worth doing. **Nothing here is fixed.**

**Related:** `issues/251` (found the empty visibility map, recorded the VACUUM as
outstanding — this is the evidence that it matters), `issues/136` (prod
`statement_timeout` kills VACUUMs, which is why it is still outstanding),
`issues/249` (placeholder names — they turn up here as latency outliers, not just
bad recall), `issues/248` (the level-walk this issue must not break)

Scripts: `test_scripts/perf/entity_query_latency.py`,
`test_scripts/perf/entity_query_roundtrips.py`.

## What a query costs today

`find_similar_by_name`, production, 5 runs each, min / med / max in ms:

| shape | min | med | max | results |
|---|---|---|---|---|
| exact name | 278.8 | 299.9 | 312.7 | 10 |
| exact name | 282.7 | 298.3 | 920.0 | 10 |
| exact name | 611.4 | 647.0 | 852.1 | 10 |
| typo, 1 char | 290.8 | 324.5 | 1,600.8 | 10 |
| typo, 1 char | 383.0 | 441.1 | 605.2 | 10 |
| long / rare | 266.7 | 334.4 | 627.5 | 10 |
| long / rare | 297.9 | 320.8 | 1,873.5 | 10 |
| placeholder (`249`) | 461.9 | 535.1 | **10,569.6** | 10 |
| placeholder (`249`) | 798.7 | 962.0 | **36,355.7** | 10 |

Cold first query in a fresh process: **1,567 ms**.

**MEASUREMENT CAVEAT, and it is most of the number.** These were taken from a
laptop against RDS. Baseline RTT is 26.4 / 28.3 / 32.6 ms over 10 runs, and every
query makes **exactly 7 band-query round trips**, so ~198 ms of a ~287 ms query is
network the server does not pay. Network-adjusted, a typical query is
**~88 ms server-side**, about 12.6 ms per band batch. Quote 90 ms, not 300 ms.
Production was also live throughout, not quiet.

## Cause 1 — the visibility map is empty, so nothing is index-only

Band lookups on **distinct** hashes, so each is not simply re-reading the page the
last one warmed:

| heap fetches | disk reads | time |
|---|---|---|
| 1 | 1 | 0.080 ms |
| 13 | 2 | 0.743 ms |
| 18 | 13 | 8.665 ms |
| 502 | 160 | **83.958 ms** |
| 31,399 | 0 (25,940 cached) | 26.904 ms |

Time tracks **disk reads**, not fetch count — the 31,399-fetch row is faster than
the 502-fetch row because it was fully cached. And the heap fetches exist only
because `relallvisible` is 0:

    entity_fuzzy_band            0 of 232,204 pages all-visible   (0.0%)
    entity_fuzzy_hash            0 of  14,195 pages all-visible   (0.0%)
    entity_fuzzy_phonetic_band   236,209 of 254,213               (92.9%)

Every plan says `Index Only Scan` and then reports `Heap Fetches: 152` for 152
rows. With the map populated these touch no heap at all.

**The asymmetry is the confirmation.** The phonetic table has been vacuumed
(2026-08-20) and is 92.9% visible; the primary table was last vacuumed
2026-07-29 and sits at 0% — and the primary table is the one in the hot path,
queried first on every request. `entity_fuzzy_hash` takes 7,067,663 index scans,
the most of any index in the registry, and is also at 0%.

A single band lookup costing 84 ms is the entire query budget spent in one of
twenty-one bands. **This is the cheapest available win on the read path.**

It will not self-heal: `autovacuum_vacuum_insert_scale_factor` is 0.2, so the band
table needs ~5.4M inserts to trigger an insert-vacuum and is at 2.86M. A manual
`VACUUM` needs `SET statement_timeout = 0` or the instance's 60 s cap kills it
(`issues/136`).

## Cause 2 — the progressive early stop cannot fire for a normal query

`query_bands_progressive` queries bands in batches of 3 and checks after each:

    if bands_queried >= 3:
        min_hits = max(2, bands_queried // 2)
        strong = sum(1 for cnt in band_hits.values() if cnt >= min_hits)
        if strong >= min_candidates:   # 20
            break

So stopping requires **20 candidates that each hit at least half the bands queried
so far**. That does not happen for an ordinary name search, and it was observed
not to happen: every measured query ran **7 of 7 batches**, for an exact match, a
typo, a long rare name and a placeholder alike. The optimisation is dead code in
practice and every query pays all 21 bands.

The bar is also stricter than what the caller needs. `_extract_entity_ids` walks
hit levels *downward* and stops at the first level yielding 20 candidates at
**any** level, while the early stop demands 20 at the `>= bands/2` level
specifically.

**Do not just lower the threshold.** Stopping earlier means fewer bands
contribute, which changes the hit counts `_extract_entity_ids` ranks on and
therefore the candidate set — a recall change, not a free speedup, in exactly the
area `issues/248` measures. Any change here needs the recall check from `248`
(the 8 real duplicate clusters) run before and after.

Upper bound if it worked: stopping after 2 batches instead of 7 is ~3.5x on the
dominant cost. Do cause 1 first — it is free of recall risk, and it may move
enough that this stops mattering.

## The placeholder outliers belong to `issues/249`

The two `company-NNNNNNN` names measured 535 and 962 ms median with maxima of
10.6 s and 36.4 s. The mechanism is visible in the table above: a placeholder
matches tens of thousands of band rows, and with no visibility map every one is a
heap fetch, so an uncached run reads tens of thousands of pages.

**The maxima did not reproduce.** A re-run of the same two names measured
402-564 ms across 5 runs. So they are real in mechanism and cache-dependent in
practice — record them as observed outliers, not as a reproducible figure. That
also means cause 1 is most of this: `249` collapses the candidate set, and the
empty map is what makes a large candidate set expensive.

## Is it acceptable

~90 ms server-side for a fuzzy dedup search over 1.27M entities is defensible.
The placeholder case is not — seconds, unpredictably. Neither number needs a
redesign; cause 1 is a maintenance command.

## What is NOT done

* The `VACUUM`. Still unrun, on `entity_fuzzy_band` and `entity_fuzzy_hash`.
* Any re-measurement after it, which is the whole point — the figures above are
  the "before" column.
* The early-stop threshold. Deliberately untouched pending `248`'s recall check.
* An in-region measurement. Everything here is network-adjusted by subtracting a
  measured RTT, which is an estimate, not a measurement. Running the same script
  from inside the VPC would settle the server-side number properly.
