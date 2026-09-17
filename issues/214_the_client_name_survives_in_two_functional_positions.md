# The Client Name Survives In Two Functional Positions

## Status: PARTLY FIXED 2026-09-17. The 28 DOCUMENTARY occurrences went in
## `f458f050`; the probe script's five went by PARAMETERISING it, which was
## available all along and wrongly written up here as needing a decision. ONE
## occurrence remains, in `docker-compose.yml`, and that one really is a rename.

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

## What remains

`docker-compose.yml:29` only. The value is compared against `space_id` at
runtime, so it cannot be edited without renaming the space it names — on dev,
where that space lives. Renaming first and updating the reference second is the
order; doing it the other way round stops excluding the space in between, which
is the `issues/192` failure (92 s -> 625 s cycles).

Not urgent. One decision, not two.
