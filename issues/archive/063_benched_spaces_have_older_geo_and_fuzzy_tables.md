# Three Benched Spaces Carry an Older Geo Table and No Fuzzy Tables

## Status: RESOLVED 2026-08-16 — all 77 spaces carry the current geo and fuzzy tables

Fixed as a side effect of reconciling every space against the schema
(`scripts/migrate_space_schema.py --all`), which drops and recreates DERIVED
tables at the current definition; `geo`, `fuzzy_band` and `fuzzy_phonetic_band`
are all on that allowlist.

Verified across the whole cluster, not just the three spaces named below:

    spaces=77  geo missing source_slot_uuid=0  missing fuzzy_band=0

and `test_fixture_indexes_match_schema` passes.

The question the Fix section raises — the semantics of `source_slot_uuid`
versus `subject_uuid`/`predicate_uuid` — did NOT need settling, because these
tables held nothing: they are rebuilt from geo-typed quads, so recreating them
at the current shape loses nothing and the older shape was simply discarded.
That is why this closed without the decision it asked for.

`test_fixture_indexes_match_schema` fails for `wordnet_frames`,
`sp_sql_lead_dataset` and `sp_lead_dup`:

    <space>_geo: no column(s) ['source_slot_uuid'] — the table is an older
    schema version, so idx_<space>_geo_slot cannot be created

    tables the schema indexes but this space lacks:
    ['<space>_fuzzy_band', '<space>_fuzzy_phonetic_band']

The geo tables have

    subject_uuid, predicate_uuid, location, latitude, longitude,
    context_uuid, updated_time

where the current schema indexes `source_slot_uuid`. These spaces were created
before that change and nothing migrated them, so the index is not merely absent —
it **cannot exist**. Creating it fails with `column "source_slot_uuid" does not
exist`, which is what `ensure_space_indexes.py` reported.

## Not a regression

Pre-existing, and unrelated to the edge-type work that was in flight when it
appeared. It became visible because the guard was widened from two indexes on
one table to every index the schema creates across every table it targets
(`issues/055`). Before that, nothing compared these tables to anything.

The failure is correct. A benchmark measures a configuration, and this is not
the configuration the schema produces.

## Why the message matters

The guard first reported this as `idx_..._geo_slot: MISSING (schema creates
it)`, which invites the wrong repair — run the index script, watch it fail,
repeat. It now distinguishes an index that is absent from one whose column does
not exist, because those need different fixes: the first is repairable by
creating the index, the second means the table itself is an older version.

## Fix

Migrate the geo tables, or drop and recreate them where they hold nothing worth
keeping. Neither has been done here because the geo schema change is outside
what this work touched and the semantics of `source_slot_uuid` versus
`subject_uuid`/`predicate_uuid` should be settled by whoever made that change.

Worth checking whether any deployed space is in the same state — the same
migration gap would apply, and geo queries against an old table shape presumably
fail or return nothing rather than erroring loudly.

## Related

- `issues/055` — the guard widening that exposed this
- `issues/041` — the general pattern: derived or versioned structures drifting
  from the schema with nothing comparing them
