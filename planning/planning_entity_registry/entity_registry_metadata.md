# Entity Registry — Metadata and Tags

Reference for the vocabularies the entity registry uses: what is a real table,
what is free text, which REST endpoints read and write each, and where the
values actually come from.

Written because the distinction is not obvious from the API. `type_key`,
`category_key`, `identifier_namespace` and `alias_type` all look alike in a JSON
payload, but only two of them are backed by a table, and only those two can fail
a write.

---

## The three groups

| Group | Examples | Backed by a table? | FK enforced? | Can a bad value fail a write? |
|---|---|---|---|---|
| **1. Lookup tables** | `entity_type`, `category`, `relationship_type`, `entity_location_type` | ✅ yes | ✅ yes | ✅ yes — FK violation |
| **2. Tags** | `identifier_namespace`, `alias_type`, `entity_same_as.relationship_type` | ❌ no | ❌ no | ❌ no — any string is accepted |
| **3. Status / change_type** | `status` on 8 tables, `entity_change_log.change_type` | ❌ no | ❌ no | `status`: ✅ CHECK constraint per table; `change_type`: ❌ open by design |

All of this is **global per database**. None of these tables carry a `space_id`
or tenant column, unlike the KG side where tables are per-space prefixed
(`sp_*`). Adding a category makes it available to every entity in the database.

---

## Group 1 — Lookup tables

Four tables. Each has a surrogate `*_id` PK, a UNIQUE business key, a label, a
description, and `created_time` / `updated_time`.

| Table | Key column | Referenced by |
|---|---|---|
| `entity_type` | `type_key` (varchar 50) | `entity.entity_type_id` **NOT NULL** |
| `category` | `category_key` (varchar 50) | `entity_category_map.category_id`<br>`entity_location_category_map.category_id` |
| `relationship_type` | `type_key` (varchar 50) | `entity_relationship.relationship_type_id` **NOT NULL** |
| `entity_location_type` | `type_key` (varchar 50) | `entity_location.location_type_id` **NOT NULL** |

Two things to note:

- **`category` is an FK target from two tables**, not one. A category can be
  assigned to an entity *or* to a location. Any "is this category used?" query
  must check both, or it will report a location-only category as unused.
- `relationship_type` additionally has `inverse_key` (varchar 50, nullable), a
  soft self-reference — it holds another row's `type_key` but has **no FK**, so
  nothing prevents an inverse pointing at a type that does not exist.

### Endpoints

Every lookup is **create + list only**. There is no PUT and no DELETE on any of
the four.

| Table | List | Create |
|---|---|---|
| `entity_type` | `GET /api/registry/entity/types` | `POST /api/registry/entity/types` |
| `category` | `GET /api/registry/categories` | `POST /api/registry/categories` |
| `relationship_type` | `GET /api/registry/relationship/types` | `POST /api/registry/relationship/types` |
| `entity_location_type` | `GET /api/registry/location/types` | `POST /api/registry/location/types` |

> `DELETE /api/registry/categories/retract` does **not** delete a category — it
> un-assigns one from an entity. There is no endpoint that removes a row from
> any of these four tables.

**Consequence:** a key created through the API is permanent. It can be left
unassigned, but it will appear in every picker in the UI forever, and removing
it requires direct SQL. Validate keys before creating them.

Assignment endpoints (which rows point at a lookup, rather than the lookup
itself):

| Purpose | Endpoint |
|---|---|
| Entity → category | `POST /api/registry/categories/assign`, `DELETE /api/registry/categories/retract` |
| List an entity's categories | `GET /api/registry/categories/entity` |
| List entities in a category | `GET /api/registry/categories/entities` |
| Location → category | `POST /api/registry/locations/categories/assign`, `DELETE /api/registry/locations/categories/retract` |
| List a location's categories | `GET /api/registry/locations/categories/list` |

Entity type and relationship type are not "assigned" separately — they are
fields on entity creation (`type_key`) and relationship creation
(`relationship_type_key`), resolved to an id server-side.

### Client methods

| Layer | Methods |
|---|---|
| Python (`vitalgraph/client/endpoint/entity_registry_endpoint.py`) | `list_entity_types`, `create_entity_type`, `list_categories`, `create_category`, `list_relationship_types`, `create_relationship_type`, `list_location_types`, `create_location_type` |
| TypeScript (`vitalgraph-client-ts/src/endpoint/EntityRegistryEndpoint.ts`) | `listEntityTypes`, `createEntityType`, `listCategories`, `createCategory`, `listRelationshipTypes`, `createRelationshipType`, `listLocationTypes`, `createLocationType` |

> The frontend consumes the **built** TS client (`dist/`, gitignored via the
> package `module` entry). After adding a client method, run `npm run build` in
> `vitalgraph-client-ts` or the browser will fail with
> `<method> is not a function`.

### Where the values come from

Three distinct origins, which is why deployments diverge:

1. **Built-in seed** — `EntityRegistrySchema.SEED_*` in
   `vitalgraph/entity_registry/entity_registry_schema.py`, applied by
   `apps/entity_registry/migrate.py` via `INSERT … ON CONFLICT DO NOTHING`:

   | Seed | Count | Values |
   |---|---|---|
   | `SEED_ENTITY_TYPES` | 4 | person, business, organization, government |
   | `SEED_ENTITY_CATEGORIES` | 7 | customer, partner, vendor, competitor, prospect, investor, regulator |
   | `SEED_LOCATION_TYPES` | 6 | headquarters, branch, warehouse, mailing, residence, registered |
   | `SEED_RELATIONSHIP_TYPES` | 13 | parent_of/subsidiary_of, employer_of/employee_of, investor_in/funded_by, partner_of, advisor_to/advised_by, supplier_to/customer_of, board_member_of/has_board_member |

2. **Per-deployment additions** — everything beyond the seed. The canonical set
   lives in the test RDS (`vitalgraph-test-db`) and is exported to
   `apps/entity_registry/reference/*.jsonl`:

   | File | Rows | Beyond the seed |
   |---|---|---|
   | `entity_types.jsonl` | 4 | — (seed only) |
   | `categories.jsonl` | 23 | +16: six `lead_*`, `business_owner`, `personal_guarantor`, and the entity-form types (`corporation`, `llc`, `c_corporation`, `s_corporation`, `partnership`, `sole_proprietorship`, `non_profit`, `not_qualified`) |
   | `relationship_types.jsonl` | 17 | +4: `owner_of`/`owned_by`, `guarantor_of`/`guaranteed_by` |
   | `location_types.jsonl` | 6 | — (seed only) |

3. **Runtime creates** — anything POSTed through the API or the Registry
   Metadata UI screen.

### Loading reference data

Two paths, and they are not equivalent:

```bash
# API-based (preferred) — goes through the impl, writes entity_change_log
#   tests/shared/seed_ui_test_data.py :: _seed_registry_reference_types()
python -m tests.shared.seed_ui_test_data --server-url http://localhost:8002

# Direct SQL (bulk migration only) — bypasses the API, no changelog entries
set -a && . ./.env && set +a
export LOCAL_DB_HOST=localhost   # .env value targets the container
python3 apps/entity_registry/entity_import_jsonl.py \
  --entity-types        apps/entity_registry/reference/entity_types.jsonl \
  --categories          apps/entity_registry/reference/categories.jsonl \
  --location-types      apps/entity_registry/reference/location_types.jsonl \
  --relationship-types  apps/entity_registry/reference/relationship_types.jsonl
```

`entity_import_jsonl.py` opens its own asyncpg pool and issues raw
`INSERT … ON CONFLICT DO NOTHING`. It never calls the API, so the
`*_type_created` / `category_created` changelog rows the impl would write are
**not** produced. Prefer the API path unless doing a bulk migration.

> `entity_import_jsonl.py --dry-run` writes nothing at all, including the
> reference type files. It reports the counts that *would* be inserted and
> merges the files' keys into the reference sets in memory, so entities
> referencing a type defined only in the file still validate.
>
> (Before this was fixed, reference types were written before the dry-run guard
> was applied — a "dry run" really did create lookup rows.)

---

## Group 2 — Tags

Three columns with **no lookup table, no FK, and no CHECK constraint**. Any
string is accepted. A value exists only because something wrote it.

| Column | Type | Default |
|---|---|---|
| `entity_identifier.identifier_namespace` | varchar(255) | none |
| `entity_alias.alias_type` | varchar(50) | `'aka'` |
| `entity_same_as.relationship_type` | varchar(50) | `'same_as'` |

> `entity_same_as.relationship_type` is **not** related to the
> `relationship_type` table despite the identical name. It describes the kind of
> same-as assertion.

### Endpoints

There is no endpoint that lists the tag vocabulary directly — a namespace is not
a thing you can create, only a thing you can use. Values are written as fields on
the rows that carry them:

| Purpose | Endpoint |
|---|---|
| Add identifier (writes `identifier_namespace`) | `POST /api/registry/identifiers/add` |
| List an entity's identifiers | `GET /api/registry/identifiers/list` |
| Retract an identifier | `DELETE /api/registry/identifiers/retract` |
| Find entities by identifier | `GET /api/registry/identifiers/lookup?namespace=&value=` |
| Add alias (writes `alias_type`) | `POST /api/registry/aliases/add` |
| List an entity's aliases | `GET /api/registry/aliases/list` |
| Retract an alias | `DELETE /api/registry/aliases/retract` |
| Create same-as (writes its `relationship_type`) | `POST /api/registry/sameas` |

Identifiers and aliases can also be supplied nested inside
`POST /api/registry/entities`, via the `identifiers` and `aliases` arrays on
`EntityCreateRequest`. That is in fact how most existing data was written.

`add_identifier` validates exactly one thing — that the entity exists. The
namespace string is inserted as given.

### Observing the vocabulary

Because there is no table, the only way to know which values are in use is to
aggregate. `GET /api/registry/metadata/summary` does this, returning
`identifier_namespaces` and `alias_types` as `{name, usage_count, applied_to}`,
where `applied_to` lists the entity types the value appears on.

### Salesforce namespace conventions

The identifier vocabulary is **owned outside this repository**. There is no
Salesforce code in vitalgraph. The producer is
`cardiff-resource-rest`, principally `cardiff_rest_api/entity_registry/sync.py`,
which uses **bare inline string literals — no enum, no constants module** —
repeated across ~15 files (`entity_registry/sync.py`, `financials`, `plaid`,
`account/provision`, `celery/actions`, `cer_agent` scripts, tests).

The rule, which exists only in that code:

| Namespace | Entity type | Salesforce source |
|---|---|---|
| `SF_LEAD_ID` | `business` | Lead (carries `Company`) |
| `SF_LEAD_PERSON_ID` | `person` | *same* Lead id, person side of the record |
| `SF_ACCOUNT_ID` | `business` | Account |
| `SF_CONTACT_ID` | `person` | Contact |
| `SF_OPPORTUNITY_ID` | `business` | Opportunity, hung off the business |
| `EMAIL`, `PHONE`, `EIN`, `DUNS` | either | — |

### Why a Lead produces two entities

A Salesforce **Lead conflates a person and a business in one record**. A single
Lead row carries `FirstName`, `LastName`, `Email`, `MobilePhone` alongside
`Company`, `Federal_Tax_ID_No__c` (EIN) and `Phone`. Salesforce only separates
them on conversion, at which point the Lead becomes an **Account** (the
business), a **Contact** (the person), and an **Opportunity** (the deal).

The registry models person and business as distinct entities from the start, so
ingesting one Lead must split it. That is why the same 18-character Lead id
appears under two namespaces — `SF_LEAD_ID` on the business entity and
`SF_LEAD_PERSON_ID` on the person entity. It is not duplication; it is the
un-smooshing, done ahead of the conversion Salesforce would eventually do
itself.

Read as a lifecycle, the namespaces line up in pairs:

| Real-world thing | Pre-conversion | Post-conversion |
|---|---|---|
| The business | `SF_LEAD_ID` | `SF_ACCOUNT_ID` (+ `SF_OPPORTUNITY_ID` per deal) |
| The person | `SF_LEAD_PERSON_ID` | `SF_CONTACT_ID` |

Ideally the same registry entity accumulates both sides of a row as the Lead
converts, so one business entity ends up holding `SF_LEAD_ID` **and**
`SF_ACCOUNT_ID`.

> ⚠️ **The conversion link is never followed.** Two separate gaps:
>
> 1. `sync.py` contains no reference to `IsConverted`, `ConvertedAccountId`,
>    `ConvertedContactId` or `ConvertedOpportunityId`, and never writes a
>    same-as link.
> 2. The pointers themselves are not even fetched. `kg_agent/sf_queries.py`
>    selects `IsConverted` — the boolean — but not `ConvertedAccountId` or
>    `ConvertedContactId`. So the pipeline knows *that* a Lead converted (it is
>    modelled in the KG as `SLOT_IS_CONVERTED`, a boolean slot on the lead
>    frame) but not *what it became*.
>
> Consequently pre- and post-conversion records are matched only by coincidence
> of a shared identifier: business by `SF_ACCOUNT_ID` then `EIN`, person by
> `EMAIL` then `PHONE`. When a Lead has no EIN — or the Account's email differs
> — the converted record creates a *second* entity rather than enriching the
> first.
>
> In the local dataset that reconnection is rare: of businesses carrying either
> namespace, only **2** hold both `SF_LEAD_ID` and `SF_ACCOUNT_ID` against 36
> lead-only and 19 account-only; for people, **3** hold both against 35 and 15.
> That may partly reflect a partial sync rather than pure fragmentation, but the
> mechanism is real — nothing links the two sides except a shared EIN, email or
> phone. `entity_same_as` exists and would be the natural place to record the
> conversion link; it is currently unused by the sync.

Nothing in this schema records or enforces that rule. It cannot be validated
here, and a lookup table would only mirror a vocabulary this system does not
own — so these stay tags by design. The UI offers existing values as
`<datalist>` suggestions while still accepting new ones.

> **Historical note.** Local databases may show `SF_CONTACT_ID` and
> `SF_LEAD_PERSON_ID` on `business` entities, contradicting the table above.
> Businesses carry `EMAIL`/`PHONE` identifiers too, so the person-dedup lookup
> in `sync.py` used to match a business and attach the person namespace to it.
> Fixed upstream (guard in `lookup_person_by_email_or_phone`, committed
> 2026-04-13 22:49); all affected rows predate that. Stale data, not a live bug.

---

## Group 3 — Status and change_type

Also unconstrained, and worth knowing because the vocabularies **disagree
between tables**.

### `status`

Eight tables carry `status varchar(20) DEFAULT 'active'`, each now with a **CHECK
constraint** enforcing its allowed set (derived from `entity_status.STATUS_SETS`,
the single source of truth). The terminal "gone" word was **unified to
`retracted`** by the standardization migration (previously the three map/location
tables used `removed`). So there are two shapes:

| Tables | Allowed statuses |
|---|---|
| `entity` | `active`, `inactive`, `merged`, `deleted` (lifecycle) |
| the other seven (identifier, alias, relationship, same_as, category_map, location, location_category_map) | `active`, `retracted` (binary) |

`entity` has the widest vocabulary: `active`, `inactive`, `merged`, `deleted`.
It is **not** enforced by the schema but it *is* enforced in code —
`update_entity` validates against exactly that tuple and returns HTTP 400 for
anything else. So this is the one status column where a wrong value fails the
write, and `entity_registry_impl.py :: update_entity` is the authoritative list.
`GET /api/registry/entities` defaults to `status=active` and therefore hides
`inactive` / `merged` / `deleted`; pass an empty `status=` to disable the filter.

Deletes across the registry are **soft** — rows are marked, not removed. Any
aggregate query must filter, and must use the right word per table. Getting this
wrong overstates usage badly: on a representative local database, 634 of 885
entities are `deleted` and 21 of 30 relationships are `retracted`.

`entity_relationship` additionally exposes `is_current` through the
`entity_relationship_view`, computed as
`status = 'active' AND (start_datetime IS NULL OR start_datetime <= now())
AND (end_datetime IS NULL OR end_datetime >= now())`.

### `change_type`

`entity_change_log.change_type` is varchar(50) **free text by design** — an audit
log, deliberately open so new change kinds can be recorded without a schema
change or a constraint to keep in sync. This is *not* an inconsistency to fix
(unlike the `status` divergence above); it is the intended shape. The impl writes
~28 values (more since the metadata-management refactor added
`identifier_type_created/updated/deleted` etc.):

```
entity_created  entity_updated  entity_deleted
identifier_added  identifier_retracted
alias_added  alias_retracted
category_created  category_added  category_removed
location_created  location_updated  location_removed
location_type_created  location_category_added  location_category_removed
relationship_type_created  relationship_created  relationship_updated  relationship_removed
same_as_created  same_as_retracted
entity_type_created
```

The vocabulary is open, not closed — existing databases also contain
`bulk_import`, which no current code writes. Treat `change_type` as advisory.

Read via `GET /api/registry/changelog/entity?entity_id=` (one entity) or
`GET /api/registry/changelog?limit=&change_type=` (recent, all entities).

---

## `GET /api/registry/metadata/summary`

> 🚩 **Flagged for refactor / removal.** This endpoint is marked to be reworked
> or taken out; do not build new dependencies on it. Rationale to be confirmed by
> the owner. What a change must account for:
>
> - **Consumers:** the Registry Metadata UI screen (`/registry-metadata`,
>   `RegistryMetadata.tsx`) is the only caller. Removing the endpoint means
>   removing or re-sourcing that screen.
> - **What it uniquely provides:** usage counts and the observed
>   identifier-namespace / alias-type vocabularies. The plain list routes
>   (`/entity/types`, `/categories`, …) return the lookup rows but **not** counts
>   or tag values. Any replacement must either give those up or source them
>   another way.
> - **No external callers:** the only caller is this repo's own UI screen. Other
>   apps (e.g. the Cardiff portal) talk to their own upstream API, not to this
>   endpoint, so removal breaks nothing outside this repo.
> - **Cost of the counting rules:** the soft-delete and dual-FK counting logic
>   (below) lives only here. If the counts move elsewhere, that logic moves with
>   them.

One call returning all six vocabularies with usage counts. Backs the Registry
Metadata UI screen. Deliberately separate from the plain list routes, which stay
light because UI selectors call them on every page load.

```jsonc
{
  "entity_types":       [{ "key", "label", "description", "inverse_key", "created_time", "usage_count" }],
  "categories":         [ /* same shape */ ],
  "relationship_types": [ /* same shape; inverse_key populated */ ],
  "location_types":     [ /* same shape */ ],
  "identifier_namespaces": [{ "name", "usage_count", "applied_to" }],
  "alias_types":           [{ "name", "usage_count", "applied_to" }]
}
```

The four lookups are aliased to a common `key`/`label`/`description` shape so one
UI component renders all of them.

**Counting rules** — every join excludes soft-deleted rows using that table's own
convention (`entity`/`deleted`, identifier+alias+relationship/`retracted`,
category_map+location/`active`), and `category` sums **both** of its referencing
tables. `usage_count = 0` is the only safe signal that a lookup can be retired,
so both rules matter: counting retracted rows makes a dead lookup look live, and
missing the location join makes a live one look dead.

Implementation: `EntityRegistryImpl.get_metadata_summary`
(`vitalgraph/entity_registry/entity_registry_impl.py`); models
`LookupUsageResponse` / `TagUsageResponse` / `MetadataSummaryResponse`
(`vitalgraph/model/entity_registry_model.py`).

---

## UI surfaces

| Screen | Path | Covers |
|---|---|---|
| Registry Metadata | `/registry-metadata` | All six vocabularies. List + add for the four lookups; read-only for the two tag groups. |
| Entity Registry list | `/entity-registry` | Type and status filters from `entity_type` |
| Entity detail | `/entity-registry/:id` | Type/status selectors; category picker; relationship type selector; identifier and alias tag inputs |

The add form on the metadata screen validates keys against
`^[a-z0-9_]{1,50}$` and requires confirmation stating the row is global and
cannot be renamed or deleted — because via the API, it cannot.

Frontend lookups are cached at module scope for the session
(`frontend/src/hooks/useRegistryLookups.ts`). Call `invalidateRegistryLookups()`
after creating a lookup value or selectors elsewhere will not show it until
reload.

---

## Inconsistencies

Consolidated from a review of the registry impl and endpoints. These are cases
where the same concept is handled differently in different places (as distinct
from the missing-capability items in "Known gaps" below). File references are
`vitalgraph/entity_registry/` unless noted.

### 1. `status` — ✅ FIXED (was: three words for "gone")

**Resolved** by `status_vocabulary_standardization_plan.md`. Formerly the terminal
"gone" word differed by table (`deleted` on `entity`; `retracted` on four;
`removed` on three), enforced only in code, so `remove_location`/`remove_entity_category`
set `removed` while `remove_alias`/`remove_relationship` — same "remove" verb —
set `retracted`. That was the root cause of the `metadata/summary` usage-count
bug.

Now: the binary word is unified to **`retracted`** across all seven binary tables
(37 `removed` rows migrated), `entity` keeps its lifecycle set, and every table
has a **CHECK constraint** so a fourth word can't be inserted. The one residue is
cosmetic — impl method names are still mixed (`remove_*` vs `retract_same_as`);
the stored value, which was the substance, is consistent.

### 2. `merged` status is orphaned — valid but unreachable

`update_entity` accepts `merged` in its `valid_statuses` tuple
(`entity_registry_impl.py:521`), but **no code path ever sets it**.
`create_same_as` (the dedup/merge op) does not touch `entity.status`. So a
declared-valid status can only be reached by a caller passing it explicitly to
`update_entity` — never as a result of a registry operation. Latent: either wire
merge to set it, or drop it from the tuple.

### 3. `status` validation differs across the three entrypoints for one field

| Path | Behaviour on a bad status |
|---|---|
| `create_entity` | no `status` param at all — always defaults to `active` |
| `update_entity` (`:521`) | validates against the 4-tuple, raises `ValueError` |
| `search_entities` (`:690`) | accepts any string, no validation — `status='bogus'` silently returns 0 rows |

Same field, three behaviours. The silent-empty search is the practical hazard: a
typo in a filter looks like "no results" rather than an error.

### 4. Endpoint naming is inconsistent three ways

(`vitalgraph/endpoint/entity_registry_endpoint.py`)

- **Soft-delete verb:** ✅ **fixed.** Was three verbs — `/entities/delete`, the
  `…/remove` family (aliases, identifiers, categories, relationships, locations),
  and `/sameas/retract`. The `…/remove` soft-deletes are now `…/retract` (the old
  `/remove` routes were removed outright — no alias); impl methods and route
  handlers are `retract_*` too. `/entities/delete` stays (its `delete` verb
  matches the terminal `deleted` status — it's the lifecycle table).
- **Type-list grouping:** `/entity/types`, `/relationship/types`,
  `/location/types` are entity-prefixed, but categories sit at top level
  (`/categories`). Defensible (categories are shared by entities and locations)
  but reads inconsistently.
- **Read style:** `/entities/get`, `/identifiers/list`, `/relationships/list`
  carry a verb; `/categories/entity` does not.

### 5. Latent-bug summary

| # | Inconsistency | Kind | Fixed? |
|---|---|---|---|
| 1 | `status` terminal word varies by table; verb ≠ word | trap → caused a real bug | ✅ fixed — unified to `retracted` + CHECK constraints (`status_vocabulary_standardization_plan.md`) |
| 2 | `merged` valid but never set | latent | no |
| 3 | status validation differs create/update/search | latent (silent-empty search) | no |
| 4 | delete-verb / type-path / read-style naming | cosmetic | ✅ verb unified to `retract` (`/remove` removed, no alias); type-path/read-style untouched |
| — | UI offered `pending` (not a valid status) | bug | ✅ fixed this session |
| — | `--dry-run` wrote reference types | bug | ✅ fixed this session |
| — | usage counts included soft-deleted + missed 2nd category FK | bug | ✅ fixed this session |

---

## Known gaps

| Gap | Impact |
|---|---|
| No `PUT` on any lookup table | A wrong label cannot be corrected through the API. |
| No `DELETE` on any lookup table | A typo'd key is permanent and appears in every picker. Cleanup requires SQL. |
| No `is_active` on lookups | Nothing can be retired; every value is offered forever. |
| `relationship_type.inverse_key` has no FK | An inverse can point at a nonexistent type. |
| ~~No CHECK constraints on `status`~~ | ✅ Fixed — per-table CHECK constraints added; binary word unified to `retracted`. |
| Tag vocabulary owned externally | `SF_*` namespaces are defined by inline literals in `cardiff-resource-rest`; the entity-type rule is unwritten here. |
| Lead conversion not tracked | `ConvertedAccountId` / `ConvertedContactId` are never fetched from Salesforce, and the sync ignores conversion entirely, so a converted Lead usually yields a second entity instead of enriching the first. `entity_same_as` exists and is unused by the sync. |
