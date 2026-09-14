# Seven Lead Fixtures Predate The Grouping-URI Fix

## Status: OPEN — the generator is CORRECT; the generated DATA on disk is stale.
## Found 2026-09-14 while choosing a fixture for the entity-graph fan-out bench.

## The invariant

Every object in a grouping graph carries `hasKGGraphURI -> <root>`, and objects
belonging to a frame also carry `hasFrameGraphURI -> <frame>`. The write path
sets both — `KGGroupingURIManager.set_dual_grouping_uris_with_frame_separation`,
called from the entity and frame endpoints — so ANY data lacking them could not
have been produced by the application. Twelve-plus modules read the predicate,
including `grouping_uri_queries.py`, `entity_graph_cache.py` and the document
segmentation worker. It is a core invariant, not a decoration.

`issues/171` already found this once and FIXED THE GENERATOR
(`generate_lead_dataset.py:388-412`, and the URI-derived injection at 545-575).
Its own note records the measurement: "`hasKGGraphURI` appeared ZERO times in
the 53M-quad `lead_nurture_100k` term table, so
`build_complete_entity_graph_query` returned 0 rows in 1ms. A load test using
the production query would have passed beautifully while measuring nothing."

## What is actually on disk

The generator was fixed. The DATA was never regenerated. Counted in
`internal_data/*/lead_syn_0001.nt`:

    lead_synth              hasKGGraphURI 0     hasFrameGraphURI 0     1.0G
    lead_synth_100k         0                   0                       10G
    lead_types              0                   0                      212M
    lead_dup                0                   0                       53M
    lead_depth1             0                   0                       46M
    lead_empty              0                   0                      106M
    lead_nurture_100k       0                   0                       11G
    lead_nurture_grouped    57,419              55,802                  27G

Seven of eight. Only `lead_nurture_grouped` was regenerated after the fix —
which is what its name records, and why it is the only fixture in the test
stack with the predicate at scale (10.65M quads of it, against 0 everywhere
else except three tiny inttest spaces and `kg_load_test`).

## Why it went unnoticed, and what it nearly cost

`get_entity_graph` and `_fetch_entity_graphs` are BOTH a two-branch UNION: one
branch pins the entity's own URI, the other collects members by grouping URI.
Branch 1 papers over the missing data — the query still returns the entity's
own triples, so it looks like it worked. `repair_grouping_self_link.py` says
this plainly: "619 broken URIs across 12 spaces produced no visible symptom."

Measured on `sp_lead_synth_100k` (50.5M quads) through the real endpoint: the
flag returns 8 quads per entity. On `lead_nurture_grouped` the same call
returns ~745. Not an error, not a warning — a fast, green, empty answer.

The entity-graph fan-out bench was one fixture choice away from being written
against it and reporting the fan-out at ~100ms forever.

## Scope of the damage

NOT every bench on these fixtures. The lead criteria benches ask frame/slot
questions that never touch the grouping predicate, so their numbers remain
valid for what they measure. What is affected is anything that retrieves an
entity GRAPH — the `include_entity_graph` flag, `get_entity_graph`,
`GroupingURIQueryBuilder` — where these fixtures silently answer with branch 1
only.

The standing risk is recurrence: `sp_lead_synth_100k` is the obvious big
fixture to reach for, and reaching for it produces a plausible number that
means nothing.

## Remediation options, with cost

1. REGENERATE and reload each stale fixture. Most correct, and re-imports
   ~22GB across the two 100k sets alone.
2. POST-PROCESS the existing `.nt` files. The injection at
   `generate_lead_dataset.py:545-575` is purely URI-derived — every subject
   starting with the entity URI gets the link, and the frame URI is the subject
   truncated at `:frame:{name}:{n}`. So it can be applied to emitted triples
   without regenerating them. Still requires a reload.
3. INJECT into the loaded spaces with SQL, deriving the same links from the
   existing subject URIs. Cheapest — no reload — but writes derived data into a
   fixture and must reproduce the generator's semantics exactly or the fixture
   becomes subtly its own thing.

Not chosen here; the cost differs by hours and the decision is not this issue's
to make.

## What regeneration actually does — measured 2026-09-14

**It is not "the same data plus grouping quads".** Regenerating `lead_types`
with its recorded parameters (2,000 entities, seed 20260806, trim) gave:

    n_triples       1,005,150 -> 1,483,310   (502.6 -> 741.7 per entity, +48%)
    expected_matches  IDENTICAL
    actual_matches    DIFFERS   mqlv2_true 1002 -> 983; CA 176 -> 181; ...

Same seed, different realised draw. The statistical expectation is unchanged,
so the fixture still means what it meant, but the exact counts move. This is
survivable ONLY because the manifest is rewritten alongside the data and the
assertions read the manifest — the design note in `lead_fixtures.py` ("the
manifest must be the one written alongside THIS space's data") is load-bearing,
not decorative. Any test that hardcodes a count instead would break here.

Two consequences:
  - Every baseline measured against these fixtures must be re-promoted after
    regeneration. The data is ~48% larger and no longer the same draw.
  - `expected_matches` being identical is the check that regeneration was
    faithful rather than a different dataset wearing the same name.

## Two fixtures that are NOT part of this work, and why

**`lead_nurture_100k` is superseded, not stale.** `lead_nurture_grouped`
(seed 7, 741.7 triples/entity, 74.5M quads) IS the regenerated nurture fixture
— `load_lead_nurture_grouped.sh` says so in its header, and it was built for
`issues/171` precisely because "the existing `lead_nurture_100k` carries zero
`hasKGGraphURI`". Regenerating `lead_nurture_100k` would produce a second copy
of a 27G dataset that already exists under another name. It is also not loaded
as a space. Left alone deliberately.

**`sp_sql_lead_dataset` (REAL) cannot be regenerated.** It is the only
non-generated fixture — 100 entities of real production-shaped data with no
generator and no manifest. It lacks the grouping URIs like the rest, but there
is nothing to re-run. Fixing it needs either a re-export from a source that
sets the grouping URIs, or the SQL injection path (option 3). Still open.

## Parameters must come from the manifest, not the load scripts

The load scripts and the recorded provenance DISAGREE, and following the
scripts would have quietly changed what the fixtures are:

    load_lead_types_dataset.sh   omits `--trim`      manifest records trim=True
    generate_depth_mix_dataset   defaults to 2000    manifest records 500

Untrimmed generation emits full graphs rather than the criteria frames, which
is a different fixture, not a regenerated one. The regeneration used the
manifest values.

## Do not let it recur silently

Whatever path is taken, the fixtures that DO carry the invariant should be
distinguishable in code rather than by counting quads, so the next bench that
needs a production-shaped entity graph picks one by name instead of by luck.
