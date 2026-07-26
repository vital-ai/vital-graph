# Entity Registry — Prod Migration Readiness

Read-only assessment of the current/old prod DB against the recent entity-registry
schema and data changes (metadata-management refactor + status-vocabulary
standardization). Purpose: confirm whether prod data needs migrating, and how.

**Verdict: prod data is compatible. Exactly 2 rows need transformation, and
`migrate.py` does it automatically.** No manual fixes, no blockers.

Assessed by querying `cardiff-postgres-prod` (`PROD_DB_*` in `.env`) read-only on
2026-07-25. Nothing was modified.

Companion plans:
- `metadata_management_refactor_plan.md` — the new tables / FKs / `is_active`.
- `status_vocabulary_standardization_plan.md` — the `removed → retracted` unification + CHECK constraints.

---

## Migration model

The move is: **old instance → new instance running updated vitalgraph.** Load the
data into the new DB, run `apps/entity_registry/migrate.py` against it, then cut
over. The migration is idempotent and additive (plus one 2-row `UPDATE`).

Old/current: `cardiff-postgres-prod` (`vitalgraphdb`).
New: `vitalgraph-pg18-prod` (`NEW_PROD_DB_*`).

---

## Current/old prod state

Old schema — the pre-refactor registry. Present: all base tables. **Absent:**
`identifier_type`, `alias_type`, and `is_active` on the four lookup tables.

Volume (why the lock note below matters):

| Table | Rows |
|---|---|
| `entity` | 1,156,756 active + 341 deleted |
| `entity_identifier` | 3,121,293 |
| `entity_category_map` | 1,087,740 |
| `entity_location` | 809,553 |
| `entity_relationship` | 591,336 |
| `entity_alias` | 7,784 |
| `entity_same_as` | 0 |

---

## Per-change readiness

| Recent change | Prod state | Migration does | Clean? |
|---|---|---|---|
| New `identifier_type` table | absent; **9** distinct namespaces, 0 NULL | create + backfill from `DISTINCT` → 9 rows | ✅ |
| New `alias_type` table | absent; **2** distinct, 0 NULL | create + backfill → 2 rows | ✅ |
| `is_active` on 4 lookup tables | absent | `ADD COLUMN … DEFAULT TRUE` (metadata-only on PG11+) | ✅ |
| **`removed` → `retracted`** | **2 rows only** — `entity_location` ids `1597278`, `1597281`. `entity_category_map` and `entity_location_category_map`: none | `UPDATE … SET status='retracted' WHERE status='removed'` | ✅ |
| Per-table CHECK constraints (8) | every table's status values already conform post-`UPDATE` (see below) | `ADD CONSTRAINT … CHECK (status IN …)` after the UPDATE | ✅ no stray values |
| Hard FK: `entity_identifier.identifier_namespace → identifier_type` | 0 NULL namespaces | validate after backfill | ✅ no orphans |
| Hard FK: `entity_alias.alias_type → alias_type` | 0 NULL | validate | ✅ |
| Hard FK: `relationship_type.inverse_key` self-ref | **0 orphans** | validate | ✅ |

### Status values in prod (the CHECK-constraint concern)

Every table's distinct `status` values already fall inside the post-migration
allowed set — the only out-of-set value anywhere is the 2 `removed` rows, which
the `UPDATE` fixes *before* the CHECK is added:

| Table | Distinct status in prod | Post-migration allowed |
|---|---|---|
| `entity` | active, deleted | active, inactive, merged, deleted ✅ |
| `entity_identifier` | active, retracted | active, retracted ✅ |
| `entity_alias` | active, retracted | active, retracted ✅ |
| `entity_relationship` | active, retracted | active, retracted ✅ |
| `entity_same_as` | (empty) | active, retracted ✅ |
| `entity_category_map` | active | active, retracted ✅ |
| `entity_location` | active, **removed** | active, retracted (removed→retracted first) ✅ |
| `entity_location_category_map` | (empty) | active, retracted ✅ |

No `pending` / `archived` / `merged`-on-a-child-table or other surprises.

### What `identifier_type` will contain (backfill)

9 rows, keyed by the namespaces already in use (label defaults to the key; rename
later via the management API if desired):

`PHONE` (1.0M), `EMAIL` (598K), `SF_LEAD_ID` (573K), `SF_LEAD_PERSON_ID` (502K),
`EIN` (226K), `SF_OPPORTUNITY_ID` (113K), `SF_ACCOUNT_ID` (89K),
`SF_CONTACT_ID` (12K), `TEST_VG_ID` (3).

---

## Caveat: constraint validation at scale

The CHECK and FK `ADD CONSTRAINT` statements do **full-table validation scans and
take `ACCESS EXCLUSIVE` locks** — most significantly the FK on `entity_identifier`
(3.1M rows) and the CHECKs on `entity` / `entity_identifier` / `entity_category_map`.

- Run these on the **new DB before it goes live** (during the move). That is the
  planned sequence, so no issue.
- Do **not** run `migrate.py` against the live old instance — the locks would
  block reads/writes on multi-million-row tables.
- If a future need arises to add these to a *live* large table, use
  `ADD CONSTRAINT … NOT VALID` then `VALIDATE CONSTRAINT` (which takes a weaker
  lock). Not needed for the cold-load path here.

---

## Runbook (new DB)

1. Load/restore the old prod data into `vitalgraph-pg18-prod`.
2. Run the migration against it (see the schema-created-by-scripts rule — never at
   runtime):
   ```bash
   set -a && . ./.env && set +a
   export LOCAL_DB_HOST=<new-host> LOCAL_DB_NAME=vitalgraphdb \
          LOCAL_DB_USERNAME=postgres LOCAL_DB_PASSWORD=<pw>
   python3 apps/entity_registry/migrate.py        # --dry-run first to preview
   ```
   This creates `identifier_type`/`alias_type` + backfills, adds `is_active`, runs
   the `removed→retracted` UPDATE, and adds the 8 CHECK constraints + 3 FKs.
3. Sanity-check post-migration:
   ```sql
   -- no removed left, binary tables unified:
   SELECT status, count(*) FROM entity_location GROUP BY 1;      -- active + retracted
   SELECT count(*) FROM pg_constraint WHERE conname LIKE 'chk_%_status';   -- 8
   SELECT count(*) FROM identifier_type;   -- 9
   SELECT count(*) FROM alias_type;        -- 2
   ```
4. Point the updated vitalgraph app at the new DB; cut over.

> `migrate.py` loads the local `vitalgraph` source; ensure the repo root is on
> `PYTHONPATH` or run from the repo (the stale site-packages copy was removed, and
> `migrate.py`'s `sys.path` was fixed, so this now resolves correctly).
