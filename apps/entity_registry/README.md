# Entity Registry Admin Scripts

Admin and migration scripts for the Entity Registry. Run from the project root.

## Scripts

| Script | Purpose |
|--------|---------|
| `entity_admin.py` | CLI admin tool: stats, search, dedup, weaviate, export, types, migrate |
| `migrate.py` | Schema migration: create tables, indexes, seed data, apply ALTER TABLE migrations |

## Schema Migration

The running service **never** modifies the database schema. Use `migrate.py` to apply changes.

```bash
python entity_registry/migrate.py                  # Full setup (create + migrate)
python entity_registry/migrate.py --dry-run        # Show what would run
python entity_registry/migrate.py --migrate-only   # Only run ALTER TABLE migrations
python entity_registry/migrate.py --create-only    # Only create tables/indexes/seeds
```

## Admin CLI

```bash
python entity_registry/entity_admin.py stats                          # Overview
python entity_registry/entity_admin.py stats types                    # Entities per type
python entity_registry/entity_admin.py search sql --name "Acme"       # PostgreSQL search
python entity_registry/entity_admin.py search similar --name "Acme"   # Dedup search
python entity_registry/entity_admin.py search topic --query "plumbing" # Weaviate search
python entity_registry/entity_admin.py fuzzy status                   # Fuzzy index status
python entity_registry/entity_admin.py fuzzy sync                     # Rebuild fuzzy index
python entity_registry/entity_admin.py fuzzy check                    # Index vs PostgreSQL
python entity_registry/entity_admin.py weaviate status                # Weaviate collection info
python entity_registry/entity_admin.py weaviate sync                  # Full Weaviate sync
python entity_registry/entity_admin.py export --format json -o out.json
python entity_registry/entity_admin.py types list
python entity_registry/entity_admin.py migrate
```

## Environment

All scripts use the same `.env` file and database configuration as the main app.

**Required for Weaviate:** `ENTITY_WEAVIATE_ENABLED=true` + `WEAVIATE_*` env vars.

**Fuzzy / dedup index:** `ENTITY_FUZZY_BACKEND` — `memory` (default), `postgresql`
(what production runs), or `redis` (legacy, also needs `ENTITY_FUZZY_REDIS_*`).
`ENTITY_DEDUP_*` is read by nothing; it is not an alias.

`entity_admin.py` selects the backend the same way the server does, through
`get_scoped_env`, so a profile-prefixed setting works. The index is built on
first use, not on connect — `stats`, `export` and `types list` do not pay for one.

What the `fuzzy` subcommands do per backend (`issues/251`):

| Command | `postgresql` | `memory` |
|---|---|---|
| `fuzzy status` | Entities hashed / banded, name variants, phonetic variants, from the band tables | The index built in this process, which is discarded on exit |
| `fuzzy check` | Compares the band tables against entities **and active aliases** | Says outright that it is not a check — the index was just built from the same query |
| `fuzzy sync` | `--since-hours N` or `--entity-id` only; a full rebuild is refused and points at `migrate_fuzzy_redis_to_pg.py` | `--full`, `--since-hours`, `--entity-id` all rebuild in-process |
| `search similar` | Queries the band tables directly, no build | Builds the whole index first |

The count grain matters if you read these numbers: `entity_key` is
`entity_id::variant_index`, so an entity contributes one key per name variant —
its primary name plus each active alias. Variants legitimately exceed entities by
the alias count, which is why `fuzzy check` prints both and compares each against
its own expectation.

A full rebuild of the PostgreSQL index lives in one place, deliberately:

```bash
python apps/fuzzy_index/migrate_fuzzy_redis_to_pg.py --status
python apps/fuzzy_index/migrate_fuzzy_redis_to_pg.py --rebuild
```
