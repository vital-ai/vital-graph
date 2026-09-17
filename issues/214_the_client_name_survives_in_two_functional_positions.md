# The Client Name Survives In Two Functional Positions

## Status: OPEN, 2026-09-17. The 28 DOCUMENTARY occurrences are gone
## (`f458f050`). These two are not comments — they name things the code
## resolves, so removing them is a RENAME, not an edit, and needs a decision
## rather than a commit.

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

## What to do

* For (1): rename the space, then the reference. Not a code change alone.
* For (2): parameterise `NS`/`SPACE` from the environment, so the probe keeps
  working against real data without the name being committed. Or accept that
  this file is a local probe and untrack it.

Neither is urgent; both are one decision each.
