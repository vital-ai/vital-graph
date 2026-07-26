# Entity Registry — Lookup-Driven UI Plan

Wire the Entity Registry screens to the registry's lookup tables (entity types,
categories, relationship types) instead of free-text fields.

---

## Problem

The Entity Registry UI never consumed the registry's lookup endpoints. Before this
work, `frontend/src` contained zero references to `/api/registry/entity/types`,
`/api/registry/categories`, or `/api/registry/relationship/types`, and neither
`EntityRegistry.tsx` nor `EntityRegistryDetail.tsx` contained a single `<Select>`.

Type was a free-text `<TextInput>`. That is not cosmetic — it is enforced
server-side:

- `entity.entity_type_id` is `NOT NULL REFERENCES entity_type(type_id)`, so entity
  creation resolves the submitted `type_key` against `entity_type` and fails on an
  unknown value.
- `entity_relationship.relationship_type_id` → `relationship_type` behaves the same
  way.

So a typo in the type field produced a server-side FK failure at save time, with no
way for the user to discover the valid set. The same gap is why the replicated
`owner_of` / `guarantor_of` relationship types and `lead_*` categories matter on
test/staging: without them, prod-shaped API writes and Salesforce ingest reject.

The backing endpoints and the TS client methods already existed — only the
`ApiService` wrappers and the UI were missing.

### What already existed

| Layer | Entity types | Categories | Relationship types |
|---|---|---|---|
| FastAPI route | ✅ `GET /api/registry/entity/types` | ✅ `GET /api/registry/categories` | ✅ `GET /api/registry/relationship/types` |
| TS client (`EntityRegistryEndpoint.ts`) | ✅ `listEntityTypes()` | ✅ `listCategories()` | ✅ `listRelationshipTypes()` |
| `ApiService` | ❌ | ❌ | ❌ |
| UI | ❌ | ❌ | ❌ |

Category assignment (`addEntityCategory` / `removeEntityCategory`) had the same
shape: client methods present, no `ApiService` wrapper, no UI.

---

## Phase 1 — `ApiService` wrappers ✅ COMPLETE

**File**: `frontend/src/services/ApiService.ts` (line 470+)

Added, delegating to the existing `vgClient.entityRegistry` methods:

- `listRegistryEntityTypes()`, `listRegistryCategories()`,
  `listRegistryRelationshipTypes()`, `listRegistryLocationTypes()`
- `addEntityCategory(entityId, categoryKey)`,
  `removeEntityCategory(entityId, categoryKey)`

`BaseEndpoint.request()` returns the parsed JSON body directly, and these routes
respond with bare arrays (`List[EntityTypeResponse]` etc.), so the wrappers return
arrays rather than an envelope.

---

## Phase 2 — Shared lookup hook ✅ COMPLETE

**File**: `frontend/src/hooks/useRegistryLookups.ts` (new)

`useEntityTypes()` / `useCategories()` / `useRelationshipTypes()`, plus exported
option types matching the Pydantic response models in
`model/entity_registry_model.py`:

- `EntityTypeOption` — `type_id`, `type_key`, `type_label`
- `CategoryOption` — `category_id`, `category_key`, `category_label`
- `RelationshipTypeOption` — `relationship_type_id`, `type_key`, `type_label`,
  `inverse_key`

Lookup tables change rarely, so the in-flight promise is cached at module scope and
shared across both pages — the list page and the detail page do not each refetch. A
rejected fetch deletes its cache entry so the next mount retries rather than
latching the error for the session. `invalidateRegistryLookups()` is exported for
use after a type/category is created.

---

## Phase 3 — List page filters ✅ COMPLETE

**File**: `frontend/src/pages/EntityRegistry.tsx`

Added a type `<Select>` (populated from `useEntityTypes`) and a status `<Select>`
beside the search box, both wired to the already-supported `entity_type` / `status`
params of `listRegistryEntities`.

This also closes a real blind spot. `EntityRegistryEndpoint.searchEntities()`
defaults `status` to `'active'` when the caller passes nothing, and the page passed
nothing — so **the list silently hid every inactive, merged and deleted entity, with no UI
to reveal them**. "All statuses" sends `status=` (empty string), which survives
`buildQueryParams` and is falsy in `search_entities()`, producing no status
predicate.

Test IDs: `entity-type-filter`, `entity-status-filter`.

---

## Phase 4 — Detail page selectors ✅ COMPLETE

**File**: `frontend/src/pages/EntityRegistryDetail.tsx`

- Type is a `<Select>` over `entity_type`, labelled `Type *`, and the Create button
  is gated on it — matching `EntityCreateRequest.type_key` being required and the
  `NOT NULL` FK.
- Status is a `<Select>` over `active` / `inactive` / `merged` — the values
  `update_entity` accepts. An earlier revision offered `pending`, which is not
  in the server's `valid_statuses` tuple and fails the save with HTTP 400; the
  value was inherited from a pre-existing `statusBadge` case in the list page.
  `deleted` is deliberately absent from the editor (terminal, set via the delete
  endpoint) but present in the list filter so deleted rows can be found.
- Both selects render an extra option when the entity's current value is absent
  from the lookup list (`"foo (unregistered)"`). Without this, opening an entity
  whose type was created before the lookup row existed would snap the select to the
  first option and silently rewrite the type on the next save.

Test IDs: `entity-type-select`, `entity-status-select`.

---

## Phase 5 — Category assignment ✅ COMPLETE

**File**: `frontend/src/pages/EntityRegistryDetail.tsx` (Categories tab)

The tab was read-only. It now has a picker over registry categories not already
assigned (`availableCategories` = all categories minus assigned keys) with an Add
button, and a per-row remove button. Both refetch sub-data on success and surface
failures through the page-level error alert.

Test ID: `add-category-select`.

---

## Phase 6 — Canonical reference data ✅ COMPLETE

The lookup selectors are only as good as the reference rows behind them, and the
database the local app actually serves (`sparql_sql_graph`, per `LOCAL_DB_NAME`)
was missing the prod-shaped values:

| Table | Was missing |
|---|---|
| `relationship_type` | `guarantor_of`, `owner_of` (and their inverses) |
| `category` | all six `lead_*`, `business_owner`, `personal_guarantor`, `corporation`, `llc`, `c_corporation`, `s_corporation`, `partnership`, `sole_proprietorship`, `non_profit`, `not_qualified` |

**Do not seed from `fuseki_sql_graph`.** It is a stale local database nothing
serves. It looks tempting because it contains `owner_of` / `guarantor_of` and the
`lead_*` categories, but its `owner_of` and `guarantor_of` rows have a NULL
`inverse_key`, and it carries `test_*` / `regtest_*` junk. The authoritative
source is the test RDS, which has clean 4/23/17/6 lookup
tables and zero entities.

Exported from the test RDS to `apps/entity_registry/reference/`:

| File | Rows |
|---|---|
| `entity_types.jsonl` | 4 — person, business, organization, government |
| `categories.jsonl` | 23 — incl. all six `lead_*` |
| `relationship_types.jsonl` | 17 — incl. `owner_of`/`owned_by`, `guarantor_of`/`guaranteed_by` |
| `location_types.jsonl` | 6 |

Load into any target DB with the existing importer (idempotent —
`ON CONFLICT DO NOTHING`):

```bash
set -a && . ./.env && set +a
export LOCAL_DB_HOST=localhost   # .env value is host.docker.internal, for the container
python3 apps/entity_registry/entity_import_jsonl.py \
  --entity-types        apps/entity_registry/reference/entity_types.jsonl \
  --categories          apps/entity_registry/reference/categories.jsonl \
  --location-types      apps/entity_registry/reference/location_types.jsonl \
  --relationship-types  apps/entity_registry/reference/relationship_types.jsonl
```

`tests/shared/seed_ui_test_data.py` now loads these same files via
`_seed_registry_reference_types()` before `_seed_entity_registry()`. Previously
the seed created an entity with `type_key='person'` and merely logged
"Entity-registry seed skipped" if that type did not exist — so a fresh e2e stack
could silently come up with an empty registry.

> ~~`entity_import_jsonl.py --dry-run` is not read-only.~~ **Fixed.** Reference
> types were written before the dry-run guard was applied, so a dry run created
> entity types, categories, location types and relationship types for real.
> `_import_reference_file` now takes `dry_run` and, when set, diffs the file's
> keys against the table instead of inserting — returning the would-be count
> and the key set, which the orchestrator merges into the in-memory reference
> sets so validation still resolves types the file would create.

---

## Phase 7 — Relationships tab ✅ COMPLETE

**Files**: `frontend/src/components/EntityPicker.tsx` (new),
`frontend/src/pages/EntityRegistryDetail.tsx`

- `EntityPicker` — debounced (250 ms) typeahead over `searchEntities` that
  resolves a real `entity_id`. Both relationship endpoints are FKs, so a
  hand-typed ID field would reintroduce exactly the failure this plan removes.
  Closes on outside click; the selected entity renders as a clearable badge.
- Relationship type `<Select>` shows `inverse_key` in each option label
  (`Owner Of (inverse: owned_by)`).
- Direction filter: both / outgoing / incoming, passed to the endpoint's existing
  `direction` param.
- Incoming edges display the **label** of `inverse_key`, resolved through the
  relationship-type lookup. Showing `r.inverse_key` directly renders a bare key
  (`advised_by`) next to properly-labelled rows (`Employer Of`) — caught by
  screenshotting the running app, not by the type checker.
- `listRelationships` returns endpoint IDs only, so counterpart names are resolved
  via a batched `Promise.allSettled` over unique IDs and cached in `relNames`,
  falling back to the raw ID.
- Fetches are guarded by a monotonic request id (`relReqIdRef`). Changing the
  direction filter starts a request while the previous one may still be in
  flight; without the guard a slow earlier response lands last and overwrites the
  filtered result. This showed up as a genuine e2e failure under parallel load.

Test IDs: `relationships-tab`, `relationship-type-select`,
`relationship-target-picker`, `relationship-direction-filter`,
`add-relationship-button`, `remove-relationship-button`, `remove-category-button`.

---

## Phase 8 — E2E coverage ✅ COMPLETE

**New**: `e2e/tests/entity-registry-lookups.spec.ts` — 11 tests, three blocks:
lookup selectors, relationships tab, category assignment. Verified green 3× in a
row against the dev stack.

**Fixed in `e2e/tests/entity-registry-crud.spec.ts`**: the create test called
`page.locator('#type').fill('person')`, which cannot work against a `<select>` —
Phase 4 would have broken this spec. Now `selectOption`.

Two conventions the new spec relies on, both learned the hard way:

1. **Names must be unique per describe block.** `playwright.config.ts` sets
   `fullyParallel: true`, so describes run concurrently; a shared fixture name
   means one block's `cleanup()` deletes another block's entities mid-run. Hence
   the `names('Sel' | 'Rel' | 'Cat')` helper.
2. **Search before asserting on the list.** It paginates at 25 rows, so on a
   populated registry a newly created entity is not on page 1. This was already
   latent in the CRUD spec and only hidden by the e2e stack's small database.

Assertions worth keeping: the status-filter test is the regression guard for the
default-`active` blind spot, and the relationships tests assert Add stays disabled
until the typeahead resolves an entity — i.e. that an ID can never be hand-typed.

---

## Phase 9 — Registry metadata management screens ✅ COMPLETE

Everything above *consumes* the registry's metadata. Nothing lets a user *manage*
it — the only ways to add a category or relationship type today are a raw SQL
insert or a direct API call.

### What is actually manageable

Two different kinds of thing, and conflating them is the trap:

**Real lookup tables** — `entity_type`, `category`, `relationship_type`,
`entity_location_type`. Each is a table with a UNIQUE key, a label and a
description, and each is an FK target. They are **global**: no `space_id`, no
tenant column, one shared set per database (unlike the KG side, where tables are
per-space prefixed `sp_*`). Adding a row here makes it available to every entity
in that database.

**Tag-style vocabularies** — `entity_identifier.identifier_namespace` and
`entity_alias.alias_type`. These are plain `VARCHAR` columns with **no lookup
table and no FK**. The values in use are conventions, nothing more:

| namespace | count | | alias_type | count |
|---|---|---|---|---|
| `EMAIL` | 437 | | `aka` | 72 |
| `PHONE` | 435 | | `abbreviation` | 19 |
| `SF_LEAD_ID` | 341 | | `legal` | 7 |
| `SF_LEAD_PERSON_ID` | 341 | | `nickname` | 4 |
| `EIN` | 197 | | `dba` | 1 |
| `SF_ACCOUNT_ID` | 125 | | | |
| `DUNS` | 9 | | | |

A later full audit of every text column in the registry schema found a **third**
tag-like column that the table above missed, and a third category of thing
entirely:

- `entity_same_as.relationship_type` — `VARCHAR(50)` default `'same_as'`, no
  table, no FK. Confusingly named: unrelated to the `relationship_type` *table*.
  3 rows today, all `same_as`.

- **`status` columns are unmodelled enums.** Seven tables carry
  `status VARCHAR(20)` with no CHECK constraint and no lookup table, and the
  vocabularies disagree on the word for "gone": `entity` uses `deleted`;
  identifier / alias / relationship / same_as use `retracted`; category_map /
  location / location_category_map use `removed`. Nothing prevents a fourth
  appearing. This is why the usage-count query needs three different filters.
  `entity_change_log.change_type` is likewise unconstrained free text. Not in
  scope here, but worth knowing before anyone builds status filtering generically.

Also from the audit: **`category` is an FK target from two tables**, not one —
`entity_category_map` and `entity_location_category_map`. The first version of
the usage count only summed the former, which would have reported a
location-only category as "unused" — the single signal this screen offers for
deciding something is safe to retire. Fixed to sum both; verified by seeding a
location-category assignment and watching `vendor` go 0 → 1.

**Decision: treat these as tags.** Adding one suggests the existing values and
allows defining a new one inline. No schema change, no FK, no migration.

The reason not to model them as a lookup table: the vocabulary is owned outside
this system. There is no Salesforce code in this repo — `grep -ri salesforce`
over `.py`/`.ts` returns nothing — yet 341 `SF_LEAD_ID` rows exist, written by an
external producer that chose that literal string and called the API. A table here
could only be a mirror that drifts, or a gate that starts rejecting writes the
moment the producer adds a namespace. Tags are the honest model.

Worth recording for later: the namespaces are applied inconsistently.
`SF_CONTACT_ID` splits 29 business / 56 person and `SF_LEAD_PERSON_ID` splits
296 business / 45 person, in opposite proportions. That is either an ingest bug
or an unwritten modelling rule. The metadata screen surfaces these counts, which
is the cheapest way to make the drift visible without committing to enforcement.

### Constraint: create + list only

The four lookup tables have **GET and POST only — no PUT, no DELETE**.
(`/categories/remove` un-assigns a category from an entity; it does not delete
the category.) So a lookup row added through the UI is permanent as far as the
API is concerned: it can be left unassigned, but it will appear in every picker
forever, and removing it means direct SQL.

Building on today's API and accepting that, rather than growing the backend
first. The add form therefore needs a confirm step stating the key is permanent
and immutable. Adding PUT (editable label/description, immutable key) and a
soft-delete `is_active` flag is the natural follow-up — logged under Remaining
work.

### Built

**Backend** — `GET /api/registry/metadata/summary`
(`EntityRegistryImpl.get_metadata_summary`, models `LookupUsageResponse` /
`TagUsageResponse` / `MetadataSummaryResponse`). Additive: the four existing list
routes are untouched, so the selectors and the `useRegistryLookups` cache keep
their light payloads while the admin screen gets counts in one call. The four
lookups are aliased to a common `key`/`label`/`description` shape so the UI
renders them with one component.

> 🚩 **`/metadata/summary` is flagged for refactor / removal.** Do not extend it.
> See the impact checklist in
> `planning/planning_entity_registry/entity_registry_metadata.md` (the endpoint's
> own section). The Registry Metadata screen built below is its only consumer.

> **Usage counts must exclude soft-deleted rows.** The first version counted
> everything and was badly wrong — this database holds 634 deleted entities
> against 251 live, and 21 retracted relationships against 9 live, so `owner_of`
> reported 19 uses when the real figure is 4. Each table uses a different
> convention and the query now matches each one: `entity`/`deleted`,
> identifier+alias+relationship/`retracted`, category_map+location/`active`.
> Totals reconcile exactly against direct SQL (9 relationships, 251 entities,
> 356 identifiers, 16 aliases, 65 locations).

**Screen** — `/registry-metadata`, `RegistryMetadata.tsx`, linked in the sidebar
under Registries. Six tabs. The four lookup tabs list every row with its usage
count (`unused` rendered distinctly, since that is the only safe thing to retire)
and offer an add form. The two tag tabs are read-only and explain why.

Because a created key can never be removed through the API, the add form:
- validates the key against `^[a-z0-9_]{1,50}$` before enabling submit;
- routes through `ConfirmDialog` stating the row is available to every entity in
  the database and cannot be renamed or deleted afterwards;
- calls `invalidateRegistryLookups()` on success, so selectors elsewhere pick the
  new value up without a reload.

**Tag inputs** — `TagInput.tsx` wraps a `TextInput` with a `<datalist>`:
suggestions without constraint, which is the whole point for a vocabulary this
system does not own. The Identifiers and Aliases tabs on the entity detail page
are now editable (add + remove) with the namespace / alias-type field as a tag
input, fed by `useIdentifierNamespaces()` / `useAliasTypes()` off the same
summary call.

### Verified against the running app

Endpoint totals reconciled against direct SQL. Screen driven with Playwright:
tab counts (8/27/20/10/9/4), relationship-type inverse column, key validation
(rejects `Bad Key!`, accepts `e2e_probe_cat`), create round-trip through the
confirm dialog (27→28 rows), datalist offering all 9 observed namespaces, and
add/remove round-trips on both Identifiers and Aliases. No console errors.

Two things this exposed, both fixed before they could mislead:
- The frontend consumes a **built** copy of the TypeScript client package
  (`dist/index.js` via the package `module` entry), so adding a client method
  requires `npm run build` in that package. Without it the screen fails with
  `getMetadataSummary is not a function`.
- The backend container has no source mount — code is baked into the image, so
  local edits need `docker cp` + restart, or an image rebuild.

### Not covered by e2e yet

`entity-registry-lookups.spec.ts` does not touch this screen. Tests worth adding:
tab counts non-zero, key validation gating, the confirm dialog's permanence
warning, and the identifier/alias add-remove round-trips. Deliberately **not** a
create test — every run would leave an undeletable row in the test database until
soft-delete exists.

> When writing those, do not target rows with `.last()`. A throwaway check here
> did, and removed a pre-existing `EIN` identifier instead of the probe row,
> because `E2E_PROBE_NS` sorts before `EIN`. The list is ordered by namespace,
> not insertion. Target by testid or by the row's own text.

---

## Remaining work

### Location types (not started)

`listRegistryLocationTypes` is wrapped but unused; the Locations tab is read-only.
Adding a location would need the same treatment (type `<Select>` from
`/api/registry/locations/types`, plus lat/long and address fields).

### PUT / soft-delete for lookup tables (not started)

The four lookup tables are create-only via the API (see Phase 9). Two additions
would make the management screens complete:

- `PUT` on each — label and description editable, key immutable since it is the
  FK target.
- An `is_active` column plus soft-delete, so a lookup can be retired without
  breaking rows that already reference it. Every list endpoint and selector would
  then need to filter to active by default — with the same "show all" escape
  hatch the entity list needed for `status`.

Until then a typo'd key is permanent through the API.

### Inline create-from-selector (not started)

With Phase 9's screens in place, an inline "create new…" option in the entity
form's type/category selectors would call the same POST endpoints and then
`invalidateRegistryLookups()`. Deferred deliberately: creating a global lookup
row is an administrative act, and burying it in an entity form is how typo'd keys
get created — exactly the thing that cannot be undone.

### Entity URI field

`EntityRegistryDetail`'s create form renders `Entity URI *`, but
`EntityCreateRequest` has no `entity_uri` field — the value is silently dropped on
create and the URI is server-assigned. The required marker is misleading. Left
as-is here; needs a decision on whether to hide the field on create or accept a
caller-supplied URI server-side.

---

## Verification status

- `tsc --noEmit` passes for both `frontend/` and `e2e/`.
- `eslint` clean on all touched frontend files. (One pre-existing unrelated error
  remains at `ApiService.ts:84`, `_silent` unused.)
- Exercised against the running dev stack (vite 5173 → app backend 8001 →
  local `sparql_sql_graph`): lookup endpoints serve the imported reference data,
  and the relationships tab was driven end-to-end (add via typeahead, direction
  filter, remove).
- Both registry specs together: 15/15 passing, three consecutive runs (after the
  stale-response fix below).
- `RegistryMetadata` screen and the Identifiers/Aliases tabs driven manually with
  Playwright; endpoint totals reconciled against direct SQL.

### Stale-response race (fixed) — was misdiagnosed as flakiness

An earlier revision of this document blamed intermittent CRUD-spec failures
(~1 run in 3) on dev-box backend latency. That was wrong. The cause was a real
bug: `EntityRegistry.fetchEntities` refetches on every keystroke with no
cancellation, so the initial unfiltered request could resolve *after* the
search-filtered one and overwrite the list with page 1. With 764 entities the
searched-for row is never on page 1, so the test could not find it.

User-visible symptom, independent of tests: typing a search can silently revert
to the unfiltered first page.

Fixed with the same monotonic request-id guard used in `fetchRelationships`
(Phase 7) — which is where the pattern was first needed, and should have been
the clue. Both registry specs now pass 15/15 three consecutive runs.

Worth remembering: an intermittent test failure blamed on the environment is
worth one round of disconfirmation before being written off. The endpoint timing
here (12–22 ms) ruled out the latency theory in a single measurement.

### Not yet done

- Nothing has been run against the port-8002 e2e stack. Before pushing, run
  `e2e/run-tests.sh` so the new reference-type seeding path and both registry
  specs are exercised in the environment CI actually uses.
- The Playwright specs have only been run with `VG_TEST_URL=http://localhost:5173`.
