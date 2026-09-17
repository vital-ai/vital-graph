# The Client Name Survives In Two Functional Positions

## Status: FIXED 2026-09-17. Zero occurrences remain in TRACKED files. 28
## documentary ones went in `f458f050`, five went by parameterising the probe,
## and the last one went by deleting the space it named rather than renaming it.
## Two UNTRACKED probes still carry it — out of scope for the rule, in scope for
## whoever commits them; see "What is left".

## The standing rule

The client name is not to appear in tracked files, and is to be removed
wherever found rather than merely not added. A sweep on 2026-09-17 scrubbed 28
comment and docstring references across 12 files. Two remain, both load-bearing.

## 1. A real space name in the maintenance exclusion default

    docker-compose.yml:29
    VG_MAINTENANCE_EXCLUDE_SPACES=${VG_MAINTENANCE_EXCLUDE_SPACES:-...,
        <client>_lead_dataset_test,...}

This is not documentation. It names a space that EXISTS (it is present on dev),
and the value is compared against `space_id` at runtime. Editing the string
silently stops excluding that space from maintenance — which is exactly the
failure `issues/192` recorded, where an unexcluded fixture took maintenance
cycles from 92 s to 625 s.

Renaming the space and then the reference is the fix. The order matters and it
is a live-environment operation.

## 2. A namespace a probe builds URIs from

    test_scripts/perf/measure_merge_bgp_reaches_096.py:25
    NS, KG = "urn:<client>:kg", "http://vital.ai/ontology/haley-ai-kg#"

The probe interpolates `NS` into URIs it queries with, and also carries the
space name in live code (`SPACE, GRAPH = ...`, plus interpolated table names).
Replacing the string makes the probe query URIs that do not exist — it would
still run and report nothing, which is worse than failing.

**This was actually broken by the sweep and reverted** (`f458f050` reverts it
explicitly). Recorded so the next sweep does not repeat it: a blind
search-and-replace across this repo hits live identifiers.

## Correction: (2) never needed a decision

This issue said both items "need a rename or parameterisation, not an edit",
and grouped them as one decision each. That was wrong about (2). A probe that
hardcodes a space name does not need anyone's permission to read it from the
environment instead — the name is an INPUT, and it was only committed because
nobody made it one. Fixed: `SPACE` and `NS` now come from `VG_PROBE_SPACE` and
`VG_PROBE_NS`, the script refuses with a usage line when they are unset rather
than querying URIs that do not exist, and the table names derive from `SPACE`.

The lesson worth keeping is the one from the sweep, not the fix: a blind
search-and-replace across this repo hits live identifiers, and it DID break this
file before being reverted. Distinguish the positions before editing, not after.

## Correction: (1) did not need a rename either

This issue framed `docker-compose.yml` as needing the space renamed first, and
a rename was scoped at 213 objects — 23 tables, 33 indexes, 12 sequences, 145
constraints — plus six catalogue tables. It was planned and then stopped by one
question: why is the space there at all?

It should not have been. Created 2026-05-03 as "Test space for <client> REST
API endpoint testing", 265,085 quads, referenced by NOTHING in the repository —
no test, script or load helper — and untouched for four and a half months. It
reached `docker-compose.yml` on 2026-09-15 via `5b272a4f`, a BULK exclusion
list whose own description targets "multi-GB lead and graph fixtures left over
from benchmarking". At 265k quads it is ~0.5% the size of the fixtures that
list exists for. It was swept in, not judged.

So the name was being preserved by a rename of 213 objects, to keep a space
nothing used, in a list it did not belong in. Dropped instead, via
`SpaceManager.delete_space_with_tables` rather than raw DDL, after a
`pg_dump` (13 MB, verified readable) so the irreversible step is recoverable.
All 213 objects and all six catalogue tables' rows are gone, including 433
`space_analytics` and 102 `query_metrics` rows.

**The general lesson is the one this issue keeps re-learning**: both items here
were filed as decisions needing a rename, and NEITHER did. Ask what the string
is for before planning how to preserve it.

## What is left

Two UNTRACKED probes, `test_scripts/perf/_issue096_remaining.py` and
`_issue096_agree.py`. The rule covers tracked files, so they are compliant
today and would not be if committed as-is. Parameterise them the way
`measure_merge_bgp_reaches_096.py` now is, or leave them local.
