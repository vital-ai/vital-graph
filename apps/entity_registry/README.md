# Entity Registry Admin Scripts

Admin and migration scripts for the Entity Registry. Run from the project root.

For full documentation, see [docs/entity_registry.md](../docs/entity_registry.md).

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
python entity_registry/entity_admin.py dedup status                   # Dedup index status
python entity_registry/entity_admin.py dedup sync                     # Rebuild dedup index
python entity_registry/entity_admin.py weaviate status                # Weaviate collection info
python entity_registry/entity_admin.py weaviate sync                  # Full Weaviate sync
python entity_registry/entity_admin.py export --format json -o out.json
python entity_registry/entity_admin.py types list
python entity_registry/entity_admin.py migrate
```

## Environment

All scripts use the same `.env` file and database configuration as the main app.

**Required for Weaviate:** `ENTITY_WEAVIATE_ENABLED=true` + `WEAVIATE_*` env vars.

**Required for Redis dedup:** `ENTITY_DEDUP_BACKEND=redis` + `ENTITY_DEDUP_REDIS_*` env vars.
