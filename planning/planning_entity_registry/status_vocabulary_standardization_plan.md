# Entity Registry — `status` Vocabulary Standardization Plan

> ✅ **DONE.** Implemented in a single pass (the team opted to fix the values
> rather than stage Phase 1 then Phase 2). Terminal binary word unified to
> **`retracted`**; 37 `removed` rows migrated; per-table CHECK constraints added
> (8); a shared constants module (`entity_status.py`) is the single source of
> truth; `search`/`update` validation and the `merged` wiring were already done
> in the metadata refactor. Verified: CHECK blocks a fourth word, both soft-delete
> paths write `retracted` and hide correctly, 15/15 registry e2e pass.

Resolve inconsistency #1 from `entity_registry_metadata.md`: the registry used
**three different terminal words for "gone"** across eight `status` columns, with
no CHECK constraint, and the impl **verb did not predict the word**. This is the
most structural of the catalogued inconsistencies and the one the metadata-
management refactor deliberately did *not* fix (it only encapsulated the counting
rule in a helper). It got its own plan because the fix is a data migration across
soft-deleted rows plus a sweep of every status-filtering query — riskier than
adding endpoints, and independently sequenced.

Companion:
- `entity_registry_metadata.md` → "Group 3 — Status and change_type" and
  "Inconsistencies #1".
- `metadata_management_refactor_plan.md` — the endpoint refactor; assumes this
  plan handles status separately.

---

## The problem, with current data

Eight tables carry `status VARCHAR(20) DEFAULT 'active'`, **no CHECK constraint**.
Distribution in a representative local DB (`sparql_sql_graph`):

| Table | Values in use | Terminal word | Semantics |
|---|---|---|---|
| `entity` | `active:251`, `deleted:672` | `deleted` | multi-state lifecycle (also `inactive`, `merged` — validated in code) |
| `entity_identifier` | `active:2088`, `retracted:7` | `retracted` | binary active/gone |
| `entity_alias` | `active:98`, `retracted:5` | `retracted` | binary |
| `entity_relationship` | `active:9`, `retracted:26` | `retracted` | binary (+ temporal `is_current` via view) |
| `entity_same_as` | `retracted:3` | `retracted` | binary |
| `entity_category_map` | `removed:27` | `removed` | binary assignment |
| `entity_location` | `active:65`, `removed:5` | `removed` | binary |
| `entity_location_category_map` | (empty) | `removed` | binary assignment |

Three problems compound:

1. **Three words for one concept:** `deleted` (entity), `retracted` (4 child
   tables), `removed` (3 map/location tables).
2. **Verb ≠ word:** `remove_alias` and `remove_relationship` set `retracted`, but
   `remove_location` and `remove_entity_category` — same "remove" verb — set
   `removed`. A reader cannot predict the stored value from the method name.
3. **No enforcement:** nothing prevents a fourth word. `entity` alone already
   carries `active`/`inactive`/`merged`/`deleted`, enforced only by a code check
   in `update_entity` (and not at all in `search_entities`).

Consequence already realized: the `metadata/summary` usage counts had to filter
soft-deletes with a *different word per table*, and getting it wrong silently
over- or under-counted. Every future aggregate inherits that trap.

---

## Design — separate the two kinds of `status`

`entity.status` is genuinely multi-state (a lifecycle: active → inactive/merged →
deleted). The other seven are **binary** (active vs. soft-removed). Treat them
differently:

- **`entity.status`** — keep as a lifecycle enum. Standardize its *allowed set*
  and enforce it; do not collapse it to binary. (Also resolves inconsistency #2 —
  `merged` — and #3 — validation asymmetry — see below.)
- **The seven binary tables** — pick **one** terminal word and use it everywhere,
  so verb → word is total and every filter reads identically.

### Which single word for the binary tables?

| Candidate | Tables already using it | For | Against |
|---|---|---|---|
| `retracted` | 4 (identifier, alias, relationship, same_as) | most tables; matches the design doc's "reversible withdrawal" language | odd for an assignment ("category retracted") |
| `removed` | 3 (category_map, location, location_category_map) | natural for assignments | fewer tables |
| `inactive` | 0 | symmetrical with `active` | net-new value everywhere; collides with `entity`'s non-terminal `inactive` |

**Recommendation: `retracted`.** It already covers four of seven tables and the
schema's own design note calls soft-delete "a reversible withdrawal, not
destruction." Migration touches the three `removed` tables only.

> Open to `removed` instead if "retracted category" reads too strangely — this is
> the one genuine bikeshed. Decide before Phase 2.

---

## Phasing — low-risk first

### Phase 1 — Enforce and centralize, **no value changes** (low risk) — ✅ done (folded into the single pass)

Do this regardless of the Phase 2 decision; it stops the bleeding without
migrating any data.

1. **One source of truth** — a module defining the allowed set and the terminal
   word per table:
   ```python
   ENTITY_STATUSES = ('active', 'inactive', 'merged', 'deleted')
   BINARY_ACTIVE, BINARY_GONE = 'active', 'retracted'   # or 'removed' pre-migration
   TERMINAL = {'entity': 'deleted', 'entity_identifier': 'retracted', ...}
   ```
   Impl filters and the `usage_count` helper import from here instead of
   hardcoding the word per query.
2. **CHECK constraints** encoding today's *actual* per-table allowed set (via
   `migrate.py`), so a fourth word can never be inserted:
   ```sql
   ALTER TABLE entity_category_map
     ADD CONSTRAINT chk_status CHECK (status IN ('active','removed'));
   -- etc., per table, matching current reality
   ```
3. **Validation symmetry (inconsistency #3)** — `search_entities` /
   `list_entities` validate `status` against `ENTITY_STATUSES` and reject unknown
   values (400) instead of returning silently empty, matching `update_entity`.
4. **`merged` decision (inconsistency #2)** — either drop `merged` from
   `ENTITY_STATUSES` (nothing sets it) or wire `create_same_as` to set the losing
   entity to `merged`. Recommendation: wire it, since a merged-away entity is a
   real state the registry otherwise can't express.

### Phase 2 — Unify the binary word (higher risk, optional) — ✅ done

Only if the team wants one word everywhere.

1. **Data migration** (`migrate.py`, explicit — never at runtime):
   ```sql
   UPDATE entity_category_map          SET status = 'retracted' WHERE status = 'removed';
   UPDATE entity_location              SET status = 'retracted' WHERE status = 'removed';
   UPDATE entity_location_category_map SET status = 'retracted' WHERE status = 'removed';
   ```
2. **Code sweep** — every `status = 'removed'` / `status != 'removed'` /
   `= 'active'` write and filter in `entity_location_ops.py`,
   `entity_category_ops.py`, and the impl's list/summary queries → the shared
   constant. Grep surface today (verify before editing):
   - writes: `remove_location` (`entity_location_ops.py:222`),
     `remove_entity_category` (`entity_category_ops.py:102`),
     `remove_location_category` (`entity_location_ops.py:335`)
   - filters: `WHERE ... status = 'active'` across `entity_category_ops.py`,
     `entity_location_ops.py`, `entity_registry_impl.py` (the `usage_count`
     helper), and the `entity_location_view`/`entity_relationship_view` defs.
3. **Tighten CHECK constraints** to the unified set.
4. **Rename the impl verbs** so verb → word is total: if all binary tables use
   `retracted`, the methods that set it should read consistently (either all
   `retract_*` or all `remove_*` — pick one; currently mixed `remove_*` /
   `retract_same_as`).

---

## What this does NOT change

- `entity_change_log.change_type` free text — intentionally open (an audit log),
  not a `status` column and not an inconsistency to fix.
- Soft-delete-only policy — rows are still marked, never physically deleted. This
  plan standardizes the *marker*, not the policy.
- The `is_current` temporal computation on `entity_relationship` /
  `entity_location` views — those derive from `status = 'active'` plus date
  ranges; they follow the constant automatically once it is centralized.

---

## Risk and sequencing

- **Phase 1 is safe** — additive constraints matching current data, plus code that
  reads a constant instead of a literal. No row changes. Do it independently of
  the metadata refactor.
- **Phase 2 is a data migration** touching soft-deleted rows across three tables
  and every query that filters them. The failure mode is a missed filter that
  now excludes (or includes) the wrong rows — the same class of bug that already
  bit `metadata/summary`. Requires a full grep sweep and a count-reconciliation
  check (row counts per status before/after must match modulo the rename) before
  it lands.
- Sequence: Phase 1 any time; Phase 2 only after the metadata refactor's shared
  `usage_count` helper exists, so there is one place — not many — to update.

---

## Decisions (resolved)

- ~~`retracted` vs `removed`~~ → **`retracted`** (all 7 binary tables).
- ~~`merged`~~ → **wired** in `create_same_as` (done in the metadata refactor).
- ~~Do Phase 2 at all~~ → **yes**, done in one pass with Phase 1.
- **Verb rename — done.** All soft-delete impl methods are now `retract_*`
  (`retract_location`, `retract_entity_category`, …, matching `retract_same_as`),
  their route-handler functions are `retract_*_route`, and the endpoint paths are `/retract` — the legacy `/remove` routes were **removed
  outright** (no alias); both clients point at `/retract`. So method verb → route
  → stored word are all `retract`.

## Filters centralized on the constants

Every runtime status filter across the 14 registry files now references the
`entity_status` constants (`ACTIVE`, `RETRACTED`, `DELETED`, …) via f-string
rather than a bare literal — 89 sites, done with a token-based transform gated by
an AST check that the rendered SQL is byte-identical (and py3.12 f-string tokens
handled). Not swept: `entity_registry_schema.py`, whose remaining literals are
DDL (the view definition) and the one-time `removed → retracted` migration, where
`removed` is intentionally a literal.
