# 020 — Registry provisioning: already script-only; close two small gaps

## Status: 🟢 MOSTLY COMPLIANT — two minor open items (app team)

## Principle

Tables are created only by an **explicit action** (a provisioning script/CLI, or
`create-space` via the space manager), **never as an implicit app side effect**
(no `ensure_tables()`/schema-create firing on app boot). The app assumes its
tables exist and fails clearly if they don't.

## Finding (corrects the original note)

The codebase **already follows the principle** — contrary to the first draft of
this issue, `ensure_tables()` does NOT create tables:

- `EntityRegistryImpl.ensure_tables()` and `AgentRegistryImpl.ensure_tables()`
  are **verify-only**: they check `information_schema` and raise
  "tables not found → run the migrate script" if missing. No DDL.
- Base tables are provisioned **only by explicit scripts**:
  `apps/entity_registry/migrate.py` and `apps/agent_registry/migrate_agents.py`
  (both `CREATE TABLE IF NOT EXISTS …`, idempotent, with `main()`).
- App startup creates **no** registry tables in production:
  - entity — `vitalgraphapp_impl.py:385` calls `ensure_tables()` (verify-only);
  - agent — startup only constructs `AgentRegistryImpl(pool)`; no table op.

So the `:247-250 / :385` "app creates tables" claim in the first draft was wrong.

## Remaining open items

1. **`VG_AUTO_INIT=true` still creates tables at app startup (test-only).**
   `vitalgraphapp_impl.py::_auto_init_entity_registry` (via `_auto_init_tables`,
   gated by the env var, set in `docker-compose.test.yml:69`) creates admin +
   entity-registry tables on boot. This is the **only** app-side creation left,
   and it's the one thing that doesn't fit the principle.
   - **Decision needed:** either (a) accept it as an explicit, env-gated,
     documented **test-only opt-in** (setting `VG_AUTO_INIT` *is* a deliberate
     action), or (b) remove the table-creation from `_auto_init_*` and have the
     test stack provision by running `apps/*/migrate*.py` (e.g. in the container
     entrypoint or the seed step) — the fully principle-pure option.
   - If (b): route the SQL through the existing `migrate*.py` provisioning so
     there's a single source of truth, and drop `VG_AUTO_INIT` table creation.

2. **No CLI subcommand for provisioning (convenience gap).**
   Base creation lives only in the standalone `apps/*/migrate*.py` scripts, not
   in the registry CLIs (`vitalgraph/entity_registry_cmd/`,
   `vitalgraph/agent_registry_cmd/`). Optional: add a `create` subcommand that
   delegates to the same schema provisioning, so operators use one tool. Purely
   ergonomic — the script path already satisfies the principle.

## Pointers

- Verify-only: `entity_registry/entity_registry_impl.py::ensure_tables()` (:89),
  `agent_registry/agent_registry_impl.py::ensure_tables()` (:70)
- Provisioning scripts: `apps/entity_registry/migrate.py`,
  `apps/agent_registry/migrate_agents.py`
- Test-only startup creation: `vitalgraph/impl/vitalgraphapp_impl.py`
  `_auto_init_tables` / `_auto_init_entity_registry` (gated by `VG_AUTO_INIT`)
