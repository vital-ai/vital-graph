# 272 — An index left invalid by a failed concurrent build counted as present

## Status: FIXED 2026-10-17 (not yet released). Found in production on v0.0.86.

**Related:** `issues/156` (the missing-index check and the schema-based
restore this corrects), `issues/270`/`271` (the index migration whose cancelled
drop produced the second case).

## What production showed (2026-10-17)

After the 0.0.48 deploy, `idx_testspace_term_dt` on production was
`indisvalid = false` — the only invalid index of the nine `term_dt` indexes,
all with the same definition. Separately, the release's index migration had a
`DROP INDEX CONCURRENTLY` on the main KG space cancelled by `lock_timeout`, which
left `idx_<main KG>_quad_ctx` invalid until the re-run dropped it.

An invalid index is what a failed or cancelled `CREATE INDEX CONCURRENTLY`,
`REINDEX CONCURRENTLY` or `DROP INDEX CONCURRENTLY` leaves behind. The planner
never uses it; if it is still `indisready`, every write maintains it. The space
is effectively without that index while paying to maintain it.

Nothing reported it, and nothing could repair it:

* `space_indexes.missing_space_indexes` (`issues/156`) matched schema indexes
  against `pg_indexes` BY NAME, so an invalid index counted as present and the
  maintenance check called the space complete.
* Every repair replays `CREATE INDEX IF NOT EXISTS`, which skips an existing
  name, valid or not — `restore_space_indexes`, the bulk import's `finally`,
  `scripts/ensure_space_indexes.py`.

The production case is harmless (the test space's term table has 0 rows). The
same state on a real space would be a permanently missing index that every
check reports as healthy.

## Fixed

* `space_indexes._present` reads `pg_index` and splits the space's indexes into
  valid (`indisvalid AND indisready`) and invalid; `missing_space_indexes`
  counts only valid ones as present; new `invalid_space_indexes` names the
  invalid ones.
* `restore_space_indexes` drops an invalid index before recreating it.
* The maintenance index check reports invalid indexes with their own WARNING
  (cause: a failed concurrent build; repair: drop concurrently, recreate) and
  not as "MISSING".
* `scripts/ensure_space_indexes.py` counts only valid indexes, marks the
  invalid ones, and drops them before its replay.

## Verification (vg test stack)

`tests/integration/test_an_invalid_index_is_a_missing_index.py` (3) makes the
invalid index the way production's was made — a concurrent UNIQUE build that
fails on duplicate values, not a catalog edit — and checks that the check
reports it as missing and names it invalid; that the restore rebuilds it valid,
with the schema's definition; and that maintenance warns "INVALID" and not
"MISSING". All three fail on the previous code. The `issues/156` tests
(`test_interrupted_bulk_import_keeps_indexes.py`) and
`test_new_space_matches_schema.py` pass.

## Not done

* ~~Production repair of `idx_testspace_term_dt`~~ — DONE 2026-10-17 by the
  deploy session; verified: `indisvalid = t`, schema definition (`btree
  (dt_val)`), 0 invalid or not-ready indexes left on production.
* The index migration script itself should set `lock_timeout = 0` and
  `statement_timeout = 0` for its session (`issues/271` deploy lesson).
