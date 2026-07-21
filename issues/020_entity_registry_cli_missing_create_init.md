# 020 — Registry base tables must be created by an explicit script/CLI, never by the app

## Status: 🔴 OPEN (product gap + design correction — app team)

## Principle

**Tables must never be created as a side effect in the app.** No `ensure_tables()`,
no schema-create at startup — for **any** case, including the **entity registry**
and the **agent registry**. Base tables are created **only** by an explicit
script / CLI command that an operator runs deliberately. (Same philosophy as
spaces: schema/DDL is explicitly provisioned and managed, never auto-created by a
data/app code path.)

## Current state (violates the principle)

- The entity-registry CLI
  (`vitalgraph/entity_registry_cmd/vitalgraph_entity_registry_cmd.py`) can create
  and manage *records* — types, entities, aliases, identifiers, categories,
  relationships — but has **no command to create the base tables**.
- Instead, base tables are created **as an app side effect** at startup:
  - `vitalgraph/impl/vitalgraphapp_impl.py:247-250` — instantiates
    `EntityRegistrySchema()` and runs `create_tables_sql()`.
  - `vitalgraph/impl/vitalgraphapp_impl.py:385` — `await self.entity_registry.ensure_tables()`.
- The **agent registry** has the same shape (schema-create reachable from the app
  rather than an explicit provisioning command).

## Required change

Two parts, both registries (entity **and** agent):

1. **Remove app-side table creation.** Delete the startup schema-create /
   `ensure_tables()` side effects (`vitalgraphapp_impl.py:247-250` and `:385`,
   and the equivalent agent-registry path). The app should assume its tables
   already exist and fail clearly (not silently create) if they don't.
2. **Add an explicit `create` / `init` CLI command** to each registry CLI that
   provisions the base tables (core + vector/FTS), idempotently
   (`CREATE TABLE IF NOT EXISTS` is already used, so re-running is safe). This
   becomes the *only* sanctioned way to create the base.

Suggested shape (mirror the existing `cmd_*` handlers):

- `vitalgraph-entity-registry create` / `vitalgraph-agent-registry create` —
  create/ensure the base tables, then exit; report clearly if already present.
- Optional flags to match setup needs (include/skip vector + FTS tables; target
  space/DB selection consistent with the other subcommands).

## Why it matters

- **Explicit provisioning**: creation is a deliberate, auditable operator step —
  not something that happens implicitly on app boot (which hides drift, races
  DDL against a live app, and blurs who owns schema).
- **Consistency**: every other registry lifecycle op is already CLI-driven; base
  creation is the one step that isn't. Do entity and agent registries together
  with a shared pattern.

## Pointers

- Entity CLI: `vitalgraph/entity_registry_cmd/vitalgraph_entity_registry_cmd.py`
- Agent CLI: `vitalgraph/agent_registry_cmd/vitalgraph_agent_registry_cmd.py`
- Entity schema: `vitalgraph/entity_registry/entity_registry_schema.py`,
  `entity_registry_vector_schema.py`; ensure path
  `entity_registry/entity_registry_impl.py::ensure_tables()`
- App side effects to remove: `vitalgraph/impl/vitalgraphapp_impl.py:247-250, 385`
