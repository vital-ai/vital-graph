# Entity Registry — Metadata Management Refactor Plan

Refactor the registry's metadata (the vocabularies: entity types, categories,
relationship types, location types, and the currently table-less identifier and
alias types) into a uniform set of managed tables with full, UI-friendly REST
endpoints — while preserving today's "new types appear as records are added"
behavior and adding referential safety so a type in use cannot be deleted.

This **removes** `GET /api/registry/metadata/summary` (flagged for removal) and
replaces it with targeted per-kind endpoints. It also folds in **some** of the
inconsistencies catalogued in `entity_registry_metadata.md` — the endpoint and
validation ones. It deliberately does **not** fix the `status`-vocabulary
inconsistency (three terminal words across seven tables); that is a separate,
riskier migration tracked in `status_vocabulary_standardization_plan.md`. See
"Folding in the review inconsistencies" for the honest per-item breakdown.

Companion docs:
- `entity_registry_metadata.md` — current state: the three groups (lookup tables,
  tags, status) and the Inconsistencies section this plan resolves.
- `../planning_fuseki/entity_registry_url_refactor.md` — the standing convention:
  **no IDs or keys in URL path segments**; everything is a query parameter. All
  new routes here follow it.

---

## Goals

1. **One table pattern for every vocabulary.** Promote the two table-less tag
   vocabularies (`identifier_namespace`, `alias_type`) to real tables, so all six
   are managed the same way.
2. **Full CRUD REST for each**, uniform in shape, following the no-path-IDs
   convention.
3. **Delete safety.** A type/namespace that records reference cannot be deleted —
   e.g. `DELETE …/identifier-types/delete?key=SSN` returns 409 while any
   identifier row uses `SSN`.
4. **Preserve auto-registration.** New types still come into existence by being
   used, exactly as they do now for tags — no pre-declaration required for
   ingest.
5. **Retire without breaking.** An `is_active` flag hides a value from dropdowns
   without invalidating rows that already reference it.
6. **UI-friendly reads.** A light list call per kind returns exactly what a
   dropdown needs; usage counts are opt-in, not bundled into every call.
7. **Remove `metadata/summary`** in favor of the above.

Non-goal: changing the query-param URL convention. Non-goal: making identifiers
themselves unique (they intentionally are not — same EIN can map to many
entities).

---

## The unified metadata model

Every vocabulary becomes a table with the same shape:

```sql
<name> (
  <name>_id       SERIAL PRIMARY KEY,
  key             VARCHAR(...) UNIQUE NOT NULL,   -- machine key (immutable)
  label           VARCHAR(255) NOT NULL,          -- human label (editable)
  description     TEXT,                            -- editable
  inverse_key     VARCHAR(...),                    -- relationship_type only
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,   -- NEW: retire without delete
  created_time    TIMESTAMPTZ DEFAULT now(),
  updated_time    TIMESTAMPTZ DEFAULT now()
)
```

| Kind | Table | Status today |
|---|---|---|
| Entity types | `entity_type` | exists (FK target); add `is_active` |
| Categories | `category` | exists (FK target ×2); add `is_active` |
| Relationship types | `relationship_type` | exists (FK target); add `is_active` |
| Location types | `entity_location_type` | exists (FK target); add `is_active` |
| **Identifier types** | **`identifier_type`** (new) | **currently a free-text column** |
| **Alias types** | **`alias_type`** (new) | **currently a free-text column** |

> The underlying key columns keep their existing names (`type_key`,
> `category_key`, …). The API normalizes them to `key` / `label` / `description`
> in responses — the same normalization `metadata/summary` already does — so one
> client type and one dropdown component serve every kind.

`entity_same_as.relationship_type` is a third table-less tag but is low-volume
(one value, `same_as`) and semantically separate; promoting it is **optional**,
tracked under Open decisions rather than this plan's core.

---

## Promoting the two tag vocabularies

Today `entity_identifier.identifier_namespace` and `entity_alias.alias_type` are
bare `VARCHAR` columns with no table. Promotion:

1. **Create** `identifier_type` and `alias_type` with the shape above.
2. **Backfill** from the data that exists:
   ```sql
   INSERT INTO identifier_type (key, label)
   SELECT DISTINCT identifier_namespace, identifier_namespace
   FROM entity_identifier
   ON CONFLICT (key) DO NOTHING;
   ```
   (label defaults to the key; a human can rename later via PUT.) Same for
   `alias_type` from `entity_alias.alias_type`.
3. **Referential link — a decision, see below.**

### FK vs app-enforced registration

The column already holds the value on `entity_identifier`; the question is whether
to add a database FK from it to the new table.

| | App-enforced (recommended) | Hard FK |
|---|---|---|
| New table | yes | yes |
| Write path | `add_identifier` upserts the type (`ON CONFLICT DO NOTHING`) then inserts the identifier | same upsert, in one transaction, then FK-checked insert |
| Orphan namespace possible via direct SQL? | yes | no |
| Migration risk | none (column unchanged) | must guarantee every existing value is backfilled first, then `ALTER TABLE … ADD FOREIGN KEY` |
| Ingest friction | none | none if upsert is in the same tx; a hard failure if a producer ever races the upsert |

**Decision: hard FK, added now** (step 7). The original recommendation was
app-enforced first, hard FK later; the team chose to add the FK immediately. The
auto-register upsert already lands the parent row in the same transaction as the
identifier/alias insert, so ingest stays FK-safe, and the FK adds DB-level
delete protection on top of the app guard. Either way, **auto-registration is
preserved** — a namespace the producer has never used before still comes into
existence the first time it is written.

---

## Auto-registration — the mechanic that must not break

The single most important behavior to keep: **a new type appears by being used**,
no pre-declaration. Today that is implicit (free text). After the refactor it
becomes an explicit upsert on the write path:

```python
async def add_identifier(entity_id, identifier_namespace, identifier_value, ...):
    async with conn.transaction():
        # register the namespace if first-seen — same effect as the old free text,
        # but now it lands in the managed table and shows up in dropdowns
        await conn.execute(
            "INSERT INTO identifier_type (key, label) VALUES ($1, $1) "
            "ON CONFLICT (key) DO NOTHING",
            identifier_namespace)
        await self._insert_identifier(conn, entity_id, identifier_namespace, ...)
```

Same treatment in `add_alias` (alias_type) and — for the existing FK tables —
`create_entity` / `create_relationship` already require a pre-existing type, so
those keep failing on unknown keys (unchanged; that is the intended behavior for
FK-enforced kinds). The auto-register-on-use path applies to the two promoted tag
kinds, matching their current semantics.

> **Interaction with `is_active`:** auto-register uses `ON CONFLICT DO NOTHING`,
> so a value that was deactivated but is then written again stays deactivated —
> it is not silently reactivated. Deactivation is a **UI-visibility** signal
> (keep it out of dropdowns), not a write gate; ingest is never rejected. See
> Open decisions if a write gate is wanted.

---

## Delete safety and retirement

Two levers, both new:

**`is_active` (soft retire).** `PUT …/update?key=X` with `is_active=false` hides a
value from the default dropdown list without touching any referencing row. This
is the everyday "stop offering this, keep what exists" path and satisfies the
existing Known-gap "nothing can be retired."

**In-use delete guard (hard safety).** `DELETE …/delete?key=X`:
- counts referencing rows using that kind's own soft-delete rule (see below),
- if the count is > 0 → **409 Conflict**, body `{ "error": "in_use",
  "usage_count": N, "key": "SSN" }`, no delete,
- if 0 → deletes the row.

So `DELETE …/identifier-types/delete?key=SSN` fails with the count while any
identifier references SSN; it succeeds only once none do. This is the "can't
delete SSN when many records use it" requirement, and it works whether or not the
hard FK is added.

> **Usage counting reuses the rules from `metadata_summary`** (which this plan
> deletes): exclude soft-deleted rows per table (`entity`/`deleted`,
> identifier+alias+relationship/`retracted`, category_map+location/`active`), and
> **count both** of `category`'s referencing tables. That logic moves from the
> summary endpoint into a shared `usage_count(kind, key)` helper.

---

## Unified REST surface

For each `{kind}` ∈ `entity-types`, `categories`, `relationship-types`,
`location-types`, `identifier-types`, `alias-types` — all under
`/api/registry/metadata/`, all query-param keyed:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/metadata/{kind}` | **Dropdown list.** Active only by default. Query: `?include_inactive=true`, `?include_usage=true`, `?q=` (prefix filter) |
| `GET` | `/metadata/{kind}/get?key=X` | One record, with `usage_count` |
| `POST` | `/metadata/{kind}` | Create (body: `key`, `label`, `description`, `inverse_key?`) |
| `PUT` | `/metadata/{kind}/update?key=X` | Edit `label` / `description` / `is_active` / `inverse_key`. **`key` is immutable.** |
| `DELETE` | `/metadata/{kind}/delete?key=X` | Delete; 409 if in use |

Notes:
- The default `GET /metadata/{kind}` is the **dropdown-friendly** call: light,
  active-only, no counts. Selectors poll this on page load.
- `?include_usage=true` adds `usage_count` per row — the management screen uses
  this; it is opt-in so the common path stays cheap.
- Response rows are the normalized `{ key, label, description, inverse_key?,
  is_active, usage_count? }`, identical across kinds.
- The two promoted kinds (`identifier-types`, `alias-types`) also gain
  `GET /metadata/{kind}/values?include_usage=true` if we want the "observed with
  usage + applied_to entity types" view the tag tabs showed — or that view is
  simply `?include_usage=true` on the list. One shape, decided in Open decisions.

### Back-compat with existing routes

The current list/create routes stay as thin aliases during migration:

| Existing | New canonical |
|---|---|
| `GET /entity/types`, `POST /entity/types` | `GET/POST /metadata/entity-types` |
| `GET /categories`, `POST /categories` | `GET/POST /metadata/categories` |
| `GET /relationship/types`, `POST /relationship/types` | `GET/POST /metadata/relationship-types` |
| `GET /location/types`, `POST /location/types` | `GET/POST /metadata/location-types` |
| `GET /api/registry/metadata/summary` | **removed** — replaced by per-kind list `?include_usage=true` |

Removing `metadata/summary`: its only caller is the Registry Metadata UI screen.
That screen changes from one aggregate call to one `GET /metadata/{kind}
?include_usage=true` per active tab (or a small parallel fan-out) — targeted
calls, as requested. The soft-delete/dual-FK counting logic moves into the shared
`usage_count` helper; nothing is lost.

---

## Folding in the review inconsistencies

From `entity_registry_metadata.md` → Inconsistencies. Being honest about what this
refactor actually resolves vs. only encapsulates vs. leaves untouched — this is a
metadata-management refactor, not a status-model refactor, so it does **not** fix
the most structural item (#1).

| # | Inconsistency | This refactor | Status |
|---|---|---|---|
| 1 | Three terminal status words (`deleted`/`retracted`/`removed`); verb ≠ word | Does **not** rename any status column. Only moves the per-table counting rule into one shared `usage_count` helper — the divergence still exists in the schema, just written once. | **Not fixed — encapsulated.** Real fix is a separate migration: see `status_vocabulary_standardization_plan.md`. |
| 2 | `merged` valid but never set | `create_same_as` now sets the source (duplicate) `active → merged`; `retract_same_as` reverses it to `active`, but only when no other active same-as remains. Verified over HTTP incl. the multi-mapping guard. | ✅ **Fixed** (wired). |
| 3 | status validation asymmetric (create/update/search) | Centralized `VALID_ENTITY_STATUSES` + `_validate_entity_status`; `search_entities` (which `list_entities` delegates to) now rejects an unknown status with a `ValueError` → **400** instead of returning silently empty; `update_entity` uses the same constant. Verified over HTTP. | ✅ **Fixed.** |
| 4 | delete-verb / path-grouping / read-style naming | **Fixed (verb).** Soft-delete impl methods, route handlers, and endpoint paths unified to `retract` — `/remove` routes removed outright (no alias); `/retract` is the only path; both clients updated. (Path-grouping and read-style sub-issues untouched.) | ✅ **verb fixed.** |
| 5 | `relationship_type.inverse_key` no FK | Hard self-FK added, `DEFERRABLE INITIALLY DEFERRED` (mutual pairs); importer batched into one transaction; create/update catch the commit-time violation → 400. See step 7. | ✅ **Fixed** (hard FK). |
| 7 | `change_type` is open free text | **By design — not an inconsistency.** `entity_change_log.change_type` is an audit log, deliberately open so new change kinds record without a schema/constraint change. The metadata CRUD does add new values (`*_type_updated`/`*_type_deleted`), which is exactly the intended behavior. Left unconstrained on purpose. | **N/A** (intended). |

---

## Phased rollout

1. ✅ **Schema** — `is_active` on the four existing tables (all already had
   `updated_time`); `identifier_type` + `alias_type` created and backfilled from
   DISTINCT (10 / 5 rows). Applied via `migrate.py`, idempotent. Also fixed
   `migrate.py`'s `sys.path` so the local source wins over the stale installed
   `vitalgraph` in site-packages.
2. ✅ **Impl** — new `entity_metadata_ops.py :: MetadataMixin`: shared
   `metadata_usage_count(kind, key)` (counting rules lifted from
   `get_metadata_summary`), per-kind `list/get/create/update/delete`, and
   `register_metadata` upsert wired into `_insert_identifier` / `_insert_alias`.
   Verified against the DB: list, usage (SF_LEAD_ID=341), create, update+
   deactivate, delete-unused, delete-in-use blocked, auto-register.
3. ✅ **Endpoints** — uniform `/metadata/{kind}` surface (list/get/create/update/
   delete) with 404 on unknown kind, 409 on create-conflict and delete-in-use.
   Verified over HTTP incl. auto-register through the identifier write path.
   `metadata/summary` kept but marked `deprecated=True` — **removed in step 5**
   once the UI migrates, to avoid a broken tree mid-flight.
4. ✅ **Clients** — TS client `listMetadata/getMetadata/createMetadata/
   updateMetadata/deleteMetadata` (rebuilt to `dist/`); `ApiService`
   `listRegistryMetadata` etc.; `useIdentifierNamespaces`/`useAliasTypes`
   repointed from the summary call to `GET /metadata/identifier-types` (active).
5. ✅ **UI** — `RegistryMetadata` rebuilt on six per-kind
   `?include_usage=true` calls; all tabs uniform; identifier/alias types now
   fully managed (create / deactivate / delete) rather than read-only; delete is
   disabled/blocked when in use. `metadata/summary` + `MetadataSummaryResponse`
   / `LookupUsageResponse` / `TagUsageResponse` + `get_metadata_summary` all
   removed. Verified over HTTP and driven through the UI; 15/15 registry e2e
   still pass.
6. ✅ **Consistency fixes** — #3 done (centralized status validation; unknown
   status → 400 on search/list/update, verified). #4 resolved as "won't fix" for
   the existing routes (cross-repo blast radius); the new metadata surface is
   uniform.
7. 🔶 **Hard FKs — done (decision reversed).** The team chose to add them now
   rather than defer. `entity_identifier.identifier_namespace →
   identifier_type.type_key` and `entity_alias.alias_type → alias_type.type_key`,
   via `migrate.py` (idempotent `DO`-block guards; a defensive re-backfill runs
   immediately before each `ADD CONSTRAINT`). Verified: (a) auto-register keeps
   ingest FK-safe — writing a brand-new namespace over HTTP still returns 200
   because `_insert_identifier` upserts the parent in the same transaction; (b)
   `RESTRICT` (default) now blocks a direct `DELETE` of an in-use type at the DB
   level, backing up the app-layer guard; (c) an orphan raw insert is rejected.

   **`relationship_type.inverse_key` — hard self-FK, done.** Also a hard FK
   (not just validation), `DEFERRABLE INITIALLY DEFERRED` because inverse pairs
   are mutually referential (`owner_of`↔`owned_by`). Sequencing handled:
   - Deferred check runs at **commit**, so both sides of a pair inserted in one
     transaction validate together.
   - The bulk JSONL importer inserted reference types per-row with autocommit;
     wrapped its loop in one transaction so a mutual pair loads. Verified.
   - The single-row `create_metadata`/`update_metadata` can't forward-reference a
     not-yet-created inverse — the deferred violation surfaces at commit (**not**
     at `execute`), so the `try` wraps the whole transaction; caught → **400**
     with a "create the pair in two steps" message. Two-step pair workflow
     (create A no-inverse → create B→A → update A→B) verified over HTTP;
     duplicate key still 409; existing data protected (direct delete of a
     referenced type blocked); failed update rolls back. 15/15 e2e pass.

   **`merged` status (#2) — wired.** `create_same_as` sets the source
   (the duplicate; `resolve_entity` follows source→target) from `active` to
   `merged`; `retract_same_as` sets it back to `active`, guarded so it only
   un-merges when the source has no other active same-as. `deleted`/`inactive`
   sources are left untouched. Verified over HTTP: merge→merged, retract→active,
   and retracting one of two mappings keeps it merged until the last is retracted.

   **Step 7 complete.**

---

## Open decisions

- ~~**Hard FK now or later**~~ — **decided: added now** (step 7).
- **Deactivation as a write gate?** Should writing a deactivated type be rejected,
  or allowed (current recommendation: allowed — UI-only signal)? Rejecting would
  break Salesforce ingest if a namespace is ever retired while still arriving.
- **`identifier-types` list shape** — is the "applied_to entity types" column
  (from the old summary) worth keeping, and as `?include_usage` or a separate
  `/values` route?
- ~~**`merged` status**~~ — **decided: `create_same_as` sets it** (step 7).
- **Promote `entity_same_as.relationship_type`** to a seventh managed kind, or
  leave as-is?
- **Delete vs deactivate default** — should `DELETE` on an in-use type offer
  `?deactivate=true` to fall back to a soft retire in one call, or keep them
  strictly separate?
