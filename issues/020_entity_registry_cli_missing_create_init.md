# 020 — Entity-registry CLI has no create/init command for the base registry

## Status: 🔴 OPEN (product gap — app team)

## Summary

Product note for the app team: the entity-registry CLI
(`vitalgraph/entity_registry_cmd/vitalgraph_entity_registry_cmd.py`) can create
and manage *records* — types, entities, aliases, identifiers, categories,
relationships — but it has **no command to create/initialize the registry base
itself** (its tables/schema). Today, standing up a fresh registry base requires
either the app startup path or calling the schema class directly.

## Current state

- The CLI exposes record-level `create_*` commands: `cmd_create_type`,
  `cmd_create_entity`, `cmd_create_relationship`, alias/identifier/category
  management, search, stats, export, fuzzy/vector status — but **nothing to
  create the base tables**.
- Base creation exists only in code, reached two ways:
  - **Schema class**: `vitalgraph/entity_registry/entity_registry_schema.py`
    (`EntityRegistrySchema`, `CREATE TABLE ...`), plus the vector/FTS tables in
    `entity_registry_vector_schema.py::create_tables_sql()`, applied via
    `entity_registry/entity_registry_impl.py::ensure_tables()`.
  - **App ("apps script") path**: `vitalgraph/impl/vitalgraphapp_impl.py:247`
    instantiates `EntityRegistrySchema()` during app init.
- So an operator can't initialize a registry from the CLI — they must run the
  app or hand-invoke the schema class.

## Requested change

Add a `create` / `init` subcommand to the entity-registry CLI that provisions
the base registry (core tables + vector/FTS tables), i.e. calls the same path
the app uses (`ensure_tables()` / `EntityRegistrySchema`), idempotently
(`CREATE TABLE IF NOT EXISTS` is already used, so re-running is safe).

Suggested shape (mirror the existing `cmd_*` handlers):

- `vitalgraph-entity-registry create` — create/ensure the base tables; exit
  cleanly if they already exist.
- Optional flags to match the app's setup (e.g. include/skip vector + FTS
  tables, target space/DB selection consistent with the other subcommands).

## Why it matters

- **Provisioning parity**: every other lifecycle op is CLI-driven; base creation
  is the one step that isn't, so ops/onboarding scripts have to reach into app
  internals or the schema class.
- **Consistency**: the agent-registry CLI
  (`vitalgraph/agent_registry_cmd/`) has the same gap — worth doing both with a
  shared pattern.

## Pointers

- CLI: `vitalgraph/entity_registry_cmd/vitalgraph_entity_registry_cmd.py`
- Base schema: `vitalgraph/entity_registry/entity_registry_schema.py`,
  `entity_registry_vector_schema.py`
- Ensure path: `entity_registry/entity_registry_impl.py::ensure_tables()`
- Current invocation: `vitalgraph/impl/vitalgraphapp_impl.py:247`
