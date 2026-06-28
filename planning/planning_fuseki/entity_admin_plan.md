# Entity Registry: Admin CLI Plan

## Overview

A unified CLI application at `entity_registry/` (project root) for administering the Entity Registry. Covers:

1. **Stats & reporting** — table counts, type breakdowns, index health
2. **MemoryDB sync** — full/incremental MinHash LSH index sync
3. **Weaviate sync** — full/incremental vector index sync
4. **Data maintenance** — export, import, orphan cleanup, type management

All commands share a common database connection setup (reads `.env` or env vars) and produce structured output suitable for logging or piping.

---

## CLI Structure

Single entry point: `entity_registry/entity_admin.py`

```bash
python entity_registry/entity_admin.py <command> [options]
```

### Commands

| Command | Description |
|---------|-------------|
| **stats** | Entity table stats and breakdowns |
| **stats types** | Entity counts per type |
| **stats aliases** | Alias counts and coverage |
| **stats categories** | Category assignment breakdown |
| **stats identifiers** | Identifier namespace breakdown |
| **stats changelog** | Recent change activity summary |
| **dedup status** | MinHash LSH index health and stats |
| **dedup sync** | Sync MinHash LSH index to MemoryDB |
| **dedup check** | Verify MemoryDB index matches PostgreSQL |
| **weaviate status** | Weaviate EntityIndex collection health |
| **weaviate sync** | Sync entities to Weaviate |
| **weaviate check** | Verify Weaviate index matches PostgreSQL |
| **search sql** | Search entities via SQL (name, type, location filters) |
| **search similar** | Find near-duplicates via MinHash LSH + RapidFuzz |
| **search topic** | Semantic topic search via Weaviate vectors |
| **export** | Export entities to JSON/CSV |
| **types list** | List all entity types |
| **types add** | Add a new entity type |

---

## Command Details

### `stats`

```bash
# Full summary
python entity_registry/entity_admin.py stats

# Output:
# Entity Registry Stats
# ─────────────────────────────────────
# Entities:      1,247 active / 23 deleted / 1,270 total
# Entity Types:  4
# Categories:    7 defined / 2,134 assignments
# Aliases:       3,891 active / 45 retracted
# Identifiers:   2,156 active
# Same-As:       89 active / 12 retracted
# Change Log:    15,432 entries
# Last Change:   2026-02-25 12:30:00 UTC
```

```bash
# Type breakdown
python entity_registry/entity_admin.py stats types

# Output:
# Entity Counts by Type
# ─────────────────────────────────────
# business       842  (67.4%)
# person         231  (18.5%)
# organization   148  (11.9%)
# government      26   (2.1%)
# ─────────────────────────────────────
# Total        1,247
```

```bash
# Alias coverage
python entity_registry/entity_admin.py stats aliases

# Output:
# Alias Stats
# ─────────────────────────────────────
# Entities with aliases:  892 / 1,247  (71.5%)
# Total active aliases:   3,891
# Avg aliases per entity: 3.1
# Alias types:  aka=2,891  trade_name=645  abbreviation=355
```

```bash
# Category breakdown
python entity_registry/entity_admin.py stats categories

# Output:
# Category Stats
# ─────────────────────────────────────
# Entities with categories: 1,067 / 1,247  (85.6%)
# Total active assignments: 2,134
# Avg categories per entity: 1.7
#
# Category Breakdown:
# customer       542  (43.5%)
# vendor         389  (31.2%)
# partner        245  (19.6%)
# prospect       198  (15.9%)
# competitor     112   (9.0%)
# investor        56   (4.5%)
# regulator       22   (1.8%)
```

```bash
# Identifier breakdown
python entity_registry/entity_admin.py stats identifiers

# Output:
# Identifier Stats
# ─────────────────────────────────────
# Entities with identifiers: 456 / 1,247  (36.6%)
# Total active identifiers:  2,156
# Namespaces:  duns=412  ein=389  lei=201  sec_cik=156  ...
```

```bash
# Changelog activity
python entity_registry/entity_admin.py stats changelog [--days 7]

# Output:
# Change Log (last 7 days)
# ─────────────────────────────────────
# entity_created:    45
# entity_updated:    123
# entity_deleted:    3
# alias_added:       67
# alias_retracted:   8
# identifier_added:  34
# same_as_created:   12
```

### `dedup status`

```bash
python entity_registry/entity_admin.py dedup status

# Output:
# MinHash LSH Dedup Index
# ─────────────────────────────────────
# Enabled:        true
# Backend:        redis (MemoryDB)
# Host:           my-cluster.xxx.memorydb.us-east-1.amazonaws.com:6379
# SSL:            true
# Entities:       1,247
# LSH Entries:    4,138  (multiple per entity due to per-variant indexing)
# Num Perm:       128
# Threshold:      0.3
# Cache Size:     1,247
```

### `dedup sync`

```bash
# Full sync: clear and rebuild from PostgreSQL
python entity_registry/entity_admin.py dedup sync --full

# Single entity
python entity_registry/entity_admin.py dedup sync --entity-id e_abc123

# Dry run
python entity_registry/entity_admin.py dedup sync --full --dry-run

# Output:
# Dedup Sync: Full
# ─────────────────────────────────────
# PostgreSQL entities: 1,247
# Clearing existing index...  done (4,138 keys removed)
# Indexing entities...  1,247 / 1,247  [████████████████████] 100%
# LSH entries created: 4,152
# Duration: 12.3s
```

### `dedup check`

```bash
python entity_registry/entity_admin.py dedup check

# Output:
# Dedup Index Consistency Check
# ─────────────────────────────────────
# PostgreSQL entities:  1,247
# Index entities:       1,245
# Missing from index:   2  (e_abc123, e_def456)
# Extra in index:       0
# ─────────────────────────────────────
# Status: DRIFT DETECTED — run 'dedup sync --full' to fix
```

### `weaviate status`

```bash
python entity_registry/entity_admin.py weaviate status

# Output:
# Weaviate EntityIndex
# ─────────────────────────────────────
# Enabled:        true
# Host:           weaviate.example.com
# Collection:     EntityIndex
# Object Count:   1,247
# Vectorizer:     text2vec-transformers
# Vector Dim:     384
# Properties:     15
```

### `weaviate sync`

```bash
# Full sync: clear and rebuild from PostgreSQL
python entity_registry/entity_admin.py weaviate sync --full

# Single entity
python entity_registry/entity_admin.py weaviate sync --entity-id e_abc123

# Dry run
python entity_registry/entity_admin.py weaviate sync --full --dry-run

# Batch size override
python entity_registry/entity_admin.py weaviate sync --full --batch-size 200

# Output:
# Weaviate Sync: Full
# ─────────────────────────────────────
# PostgreSQL entities: 1,247
# Ensuring collection...  EntityIndex exists (15 properties)
# Deleting stale objects...  done (3 removed)
# Upserting entities...  1,247 / 1,247  [████████████████████] 100%
# Duration: 45.2s
```

### `weaviate check`

```bash
python entity_registry/entity_admin.py weaviate check

# Output:
# Weaviate Index Consistency Check
# ─────────────────────────────────────
# PostgreSQL entities:  1,247
# Weaviate objects:     1,244
# Missing from Weaviate: 3  (e_abc123, e_def456, e_ghi789)
# Extra in Weaviate:     0
# ─────────────────────────────────────
# Status: DRIFT DETECTED — run 'weaviate sync --full' to fix
```

### `search sql`

Direct PostgreSQL search using ILIKE on name/alias fields with optional type and location filters.

```bash
# Search by name
python entity_registry/entity_admin.py search sql --name "Acme"

# Filter by type and location
python entity_registry/entity_admin.py search sql --name "plumbing" --type-key business --country US --region NJ

# Filter by category
python entity_registry/entity_admin.py search sql --name "acme" --category-key customer

# Search aliases too
python entity_registry/entity_admin.py search sql --name "IBM" --include-aliases

# Limit results
python entity_registry/entity_admin.py search sql --name "bank" --limit 20

# Output:
# SQL Search: "plumbing" (type=business, country=US, region=NJ)
# ─────────────────────────────────────────────────────────────
# e_abc123  ABC Plumbing LLC          business   US  NJ  Newark
# e_def456  Garden State Plumbing     business   US  NJ  Trenton
# e_ghi789  NJ Plumbing Supply Co     business   US  NJ  Edison
# ─────────────────────────────────────────────────────────────
# 3 results
```

**Options:**
| Flag | Description |
|------|-------------|
| `--name` | Name pattern (ILIKE, supports `%` wildcards) |
| `--type-key` | Filter by entity type key |
| `--category-key` | Filter by category (entities assigned to this category) |
| `--country` | Filter by country |
| `--region` | Filter by region/state |
| `--locality` | Filter by city |
| `--include-aliases` | Also search alias names |
| `--status` | Entity status filter (default: `active`) |
| `--limit` | Max results (default: 50) |
| `--format` | Output format: `table` (default), `json`, `csv` |

### `search similar`

Find near-duplicate entities using the MinHash LSH dedup index with RapidFuzz scoring. Uses the same engine as the `/similar` API endpoint.

```bash
# Find entities similar to a name
python entity_registry/entity_admin.py search similar --name "Acme Corporation"

# With location context (influences scoring)
python entity_registry/entity_admin.py search similar --name "Acme Corp" --country US

# Adjust score threshold
python entity_registry/entity_admin.py search similar --name "IBM" --min-score 70

# Find duplicates of an existing entity (excludes self)
python entity_registry/entity_admin.py search similar --entity-id e_abc123

# Show detailed scoring breakdown
python entity_registry/entity_admin.py search similar --name "Acme" --verbose

# Output:
# Similar Entities: "Acme Corporation" (min_score=50.0)
# ─────────────────────────────────────────────────────────────
# Score  Level   Entity ID     Name                      Country
# 100.0  high    e_abc123      Acme Corporation          US
#  92.5  high    e_def456      Acme Corp International   US
#  78.3  likely  e_ghi789      ACME Industries Ltd       UK
#  63.1  possible e_jkl012     Acme Holdings             US
# ─────────────────────────────────────────────────────────────
# 4 results (backend: memory, index: 1,247 entities)

# Verbose output adds score detail per result:
#   e_abc123  Acme Corporation
#     ratio=100.0  partial=100.0  token_sort=100.0  token_set=100.0
#     matched variant: primary_name
```

**Options:**
| Flag | Description |
|------|-------------|
| `--name` | Query name (required unless `--entity-id`) |
| `--entity-id` | Find duplicates of existing entity (excludes self) |
| `--country` | Location context for scoring |
| `--region` | Location context for scoring |
| `--locality` | Location context for scoring |
| `--min-score` | Minimum RapidFuzz score 0-100 (default: 50.0) |
| `--limit` | Max results (default: 10) |
| `--verbose` | Show per-metric score breakdown |
| `--format` | Output format: `table` (default), `json` |

**Requires:** `ENTITY_DEDUP_ENABLED=true`. If dedup is disabled, prints an error and exits.

### `search topic`

Semantic topic search using Weaviate vector similarity. Finds entities whose description, type, or name are semantically related to the query.

```bash
# Basic topic search
python entity_registry/entity_admin.py search topic --query "plumbing contractor"

# With type and location filters
python entity_registry/entity_admin.py search topic --query "plumbing" --type-key business --country US --region NJ

# Filter by category
python entity_registry/entity_admin.py search topic --query "software consulting" --category-key vendor

# Adjust certainty threshold
python entity_registry/entity_admin.py search topic --query "environmental regulation" --type-key government --min-certainty 0.8

# Use hybrid search (BM25 + vector)
python entity_registry/entity_admin.py search topic --query "plumbing" --hybrid --alpha 0.5

# Show distance scores
python entity_registry/entity_admin.py search topic --query "disaster relief" --verbose

# Output:
# Topic Search: "plumbing contractor" (type=business, country=US, region=NJ)
# ─────────────────────────────────────────────────────────────
# Score  Entity ID     Name                      Type       Location
# 0.94   e_abc123      ABC Plumbing LLC          business   Newark, NJ, US
# 0.91   e_def456      Garden State Plumbing     business   Trenton, NJ, US
# 0.87   e_ghi789      NJ Plumbing Supply Co     business   Edison, NJ, US
# 0.82   e_jkl012      Pro Pipe Services         business   Camden, NJ, US
# ─────────────────────────────────────────────────────────────
# 4 results (collection: EntityIndex, 1,247 objects)

# Verbose output adds distance and search_text snippet:
#   e_abc123  ABC Plumbing LLC  (certainty=0.94, distance=0.06)
#     "ABC Plumbing LLC. Business: A business or company. Licensed plumbing
#      contractor serving residential and commercial clients. Newark, NJ, US"
```

**Options:**
| Flag | Description |
|------|-------------|
| `--query`, `-q` | Free-text query (required, vectorized) |
| `--type-key` | Filter by entity type key |
| `--category-key` | Filter by category key |
| `--country` | Filter by country |
| `--region` | Filter by region/state |
| `--locality` | Filter by city |
| `--min-certainty` | Minimum Weaviate certainty 0-1 (default: 0.7) |
| `--limit` | Max results (default: 10) |
| `--hybrid` | Use hybrid search (BM25 + vector) |
| `--alpha` | Hybrid alpha: 0=pure BM25, 1=pure vector (default: 0.5) |
| `--verbose` | Show distance and search_text snippet |
| `--format` | Output format: `table` (default), `json` |

**Requires:** `ENTITY_WEAVIATE_ENABLED=true`. If Weaviate is disabled, prints an error and exits.

### `export`

```bash
# Export all active entities to JSON
python entity_registry/entity_admin.py export --format json --output entities.json

# Export specific type to CSV
python entity_registry/entity_admin.py export --format csv --type-key business --output businesses.csv

# Include aliases and identifiers
python entity_registry/entity_admin.py export --format json --include-aliases --include-identifiers
```

### `types`

```bash
# List types
python entity_registry/entity_admin.py types list

# Output:
# Entity Types
# ─────────────────────────────────────
# person         Person                An individual person             (231 entities)
# business       Business              A business or company            (842 entities)
# organization   Organization          A non-commercial organization    (148 entities)
# government     Government            A government body or agency       (26 entities)

# Add type
python entity_registry/entity_admin.py types add --key contractor --label Contractor --description "A licensed contractor or tradesperson"
```

---

## Architecture

```python
# entity_registry/entity_admin.py

import argparse
import asyncio
import sys

class EntityAdmin:
    """CLI application for Entity Registry administration."""

    def __init__(self):
        self.pool = None        # asyncpg pool
        self.registry = None    # EntityRegistryImpl
        self.dedup = None       # EntityDedupIndex (optional)
        self.weaviate = None    # EntityWeaviateIndex (optional)

    async def connect(self):
        """Connect to PostgreSQL and optional backends."""

    async def disconnect(self):
        """Clean up connections."""

    # Stats commands
    async def cmd_stats(self, args): ...
    async def cmd_stats_types(self, args): ...
    async def cmd_stats_aliases(self, args): ...
    async def cmd_stats_categories(self, args): ...
    async def cmd_stats_identifiers(self, args): ...
    async def cmd_stats_changelog(self, args): ...

    # Dedup commands
    async def cmd_dedup_status(self, args): ...
    async def cmd_dedup_sync(self, args): ...
    async def cmd_dedup_check(self, args): ...

    # Weaviate commands
    async def cmd_weaviate_status(self, args): ...
    async def cmd_weaviate_sync(self, args): ...
    async def cmd_weaviate_check(self, args): ...

    # Search commands
    async def cmd_search_sql(self, args): ...
    async def cmd_search_similar(self, args): ...
    async def cmd_search_topic(self, args): ...

    # Data commands
    async def cmd_export(self, args): ...
    async def cmd_types_list(self, args): ...
    async def cmd_types_add(self, args): ...


def main():
    parser = argparse.ArgumentParser(
        prog='entity_admin',
        description='Entity Registry administration CLI',
    )
    subparsers = parser.add_subparsers(dest='command')

    # stats
    stats_parser = subparsers.add_parser('stats')
    stats_sub = stats_parser.add_subparsers(dest='sub')
    stats_sub.add_parser('types')
    stats_sub.add_parser('aliases')
    stats_sub.add_parser('categories')
    stats_sub.add_parser('identifiers')
    changelog_p = stats_sub.add_parser('changelog')
    changelog_p.add_argument('--days', type=int, default=7)

    # dedup
    dedup_parser = subparsers.add_parser('dedup')
    dedup_sub = dedup_parser.add_subparsers(dest='sub')
    dedup_sub.add_parser('status')
    sync_p = dedup_sub.add_parser('sync')
    sync_p.add_argument('--full', action='store_true')
    sync_p.add_argument('--entity-id')
    sync_p.add_argument('--dry-run', action='store_true')
    dedup_sub.add_parser('check')

    # weaviate
    weav_parser = subparsers.add_parser('weaviate')
    weav_sub = weav_parser.add_subparsers(dest='sub')
    weav_sub.add_parser('status')
    wsync_p = weav_sub.add_parser('sync')
    wsync_p.add_argument('--full', action='store_true')
    wsync_p.add_argument('--entity-id')
    wsync_p.add_argument('--dry-run', action='store_true')
    wsync_p.add_argument('--batch-size', type=int, default=100)
    weav_sub.add_parser('check')

    # search
    search_parser = subparsers.add_parser('search')
    search_sub = search_parser.add_subparsers(dest='sub')

    sql_p = search_sub.add_parser('sql')
    sql_p.add_argument('--name', required=True)
    sql_p.add_argument('--type-key')
    sql_p.add_argument('--category-key')
    sql_p.add_argument('--country')
    sql_p.add_argument('--region')
    sql_p.add_argument('--locality')
    sql_p.add_argument('--include-aliases', action='store_true')
    sql_p.add_argument('--status', default='active')
    sql_p.add_argument('--limit', type=int, default=50)
    sql_p.add_argument('--format', choices=['table', 'json', 'csv'], default='table')

    sim_p = search_sub.add_parser('similar')
    sim_p.add_argument('--name')
    sim_p.add_argument('--entity-id')
    sim_p.add_argument('--country')
    sim_p.add_argument('--region')
    sim_p.add_argument('--locality')
    sim_p.add_argument('--min-score', type=float, default=50.0)
    sim_p.add_argument('--limit', type=int, default=10)
    sim_p.add_argument('--verbose', action='store_true')
    sim_p.add_argument('--format', choices=['table', 'json'], default='table')

    topic_p = search_sub.add_parser('topic')
    topic_p.add_argument('--query', '-q', required=True)
    topic_p.add_argument('--type-key')
    topic_p.add_argument('--category-key')
    topic_p.add_argument('--country')
    topic_p.add_argument('--region')
    topic_p.add_argument('--locality')
    topic_p.add_argument('--min-certainty', type=float, default=0.7)
    topic_p.add_argument('--limit', type=int, default=10)
    topic_p.add_argument('--hybrid', action='store_true')
    topic_p.add_argument('--alpha', type=float, default=0.5)
    topic_p.add_argument('--verbose', action='store_true')
    topic_p.add_argument('--format', choices=['table', 'json'], default='table')

    # export
    export_p = subparsers.add_parser('export')
    export_p.add_argument('--format', choices=['json', 'csv'], default='json')
    export_p.add_argument('--output', '-o')
    export_p.add_argument('--type-key')
    export_p.add_argument('--include-aliases', action='store_true')
    export_p.add_argument('--include-identifiers', action='store_true')

    # types
    types_parser = subparsers.add_parser('types')
    types_sub = types_parser.add_subparsers(dest='sub')
    types_sub.add_parser('list')
    add_p = types_sub.add_parser('add')
    add_p.add_argument('--key', required=True)
    add_p.add_argument('--label', required=True)
    add_p.add_argument('--description', default='')

    args = parser.parse_args()
    admin = EntityAdmin()
    asyncio.run(admin.run(args))


if __name__ == '__main__':
    main()
```

---

## Environment Variables

The CLI reads the same env vars as the main app:

```bash
# PostgreSQL (required)
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=vitalgraph
DATABASE_USERNAME=vitalgraph_user
DATABASE_PASSWORD=vitalgraph_pass

# Dedup / MemoryDB (optional, for dedup commands)
ENTITY_DEDUP_ENABLED=true
ENTITY_DEDUP_BACKEND=redis
ENTITY_DEDUP_REDIS_HOST=...
ENTITY_DEDUP_REDIS_PORT=6379
ENTITY_DEDUP_REDIS_SSL=true
ENTITY_DEDUP_REDIS_USERNAME=...
ENTITY_DEDUP_REDIS_PASSWORD=...

# Weaviate (optional, for weaviate commands)
ENTITY_WEAVIATE_ENABLED=true
WEAVIATE_REST_URL=...
WEAVIATE_HTTP_HOST=...
WEAVIATE_GRPC_HOST=...
WEAVIATE_GRPC_PORT=50051
WEAVIATE_KEYCLOAK_URL=...
WEAVIATE_CLIENT_ID=...
WEAVIATE_CLIENT_SECRET=...
WEAVIATE_USERNAME=...
WEAVIATE_PASSWORD=...
```

Commands that don't need a specific backend gracefully skip it if not configured (e.g. `stats` only needs PostgreSQL).

---

## File Layout

```
entity_registry/                        # Admin scripts (project root)
  entity_admin.py                       # Main CLI entry point
  README.md                             # Documentation
```

The CLI imports from `vitalgraph.entity_registry` for shared logic:

```
vitalgraph/
  entity_registry/
    entity_registry_impl.py             # Shared: queries, CRUD
    entity_dedup.py                     # Shared: MinHash LSH index
    entity_weaviate.py                  # Shared: Weaviate sync/query (future)
```

---

## Implementation Phases

### Phase 6a: Plan
- This document

### Phase 6b: Core CLI Framework
1. Create `entity_registry/entity_admin.py` with argparse structure
2. Database connection setup (reads .env, creates asyncpg pool)
3. Implement `stats` command (summary + sub-commands)

### Phase 6c: Dedup Admin Commands
1. `dedup status` — read index stats from MemoryDB or in-memory
2. `dedup sync --full` — bulk sync from PostgreSQL
3. `dedup sync --entity-id` — single entity sync
4. `dedup check` — consistency verification

### Phase 6d: Weaviate Admin Commands
1. `weaviate status` — collection info from Weaviate API
2. `weaviate sync --full` — bulk sync from PostgreSQL
3. `weaviate sync --entity-id` — single entity sync
4. `weaviate check` — consistency verification

### Phase 6e: Data Commands
1. `export` — JSON/CSV export with filtering
2. `types list` / `types add` — entity type management

---

## SQL Queries for Stats

```sql
-- Summary stats
SELECT
  COUNT(*) FILTER (WHERE status = 'active') AS active,
  COUNT(*) FILTER (WHERE status = 'deleted') AS deleted,
  COUNT(*) AS total
FROM entity;

-- By type
SELECT et.type_key, et.type_label, COUNT(e.entity_id) AS count
FROM entity_type et
LEFT JOIN entity e ON et.type_id = e.entity_type_id AND e.status = 'active'
GROUP BY et.type_key, et.type_label
ORDER BY count DESC;

-- Alias coverage
SELECT
  COUNT(DISTINCT ea.entity_id) AS entities_with_aliases,
  COUNT(*) FILTER (WHERE ea.status = 'active') AS active_aliases,
  COUNT(*) FILTER (WHERE ea.status = 'retracted') AS retracted_aliases
FROM entity_alias ea;

-- Alias types
SELECT alias_type, COUNT(*) AS count
FROM entity_alias WHERE status = 'active'
GROUP BY alias_type ORDER BY count DESC;

-- Category coverage
SELECT
  COUNT(DISTINCT ecm.entity_id) AS entities_with_categories,
  COUNT(*) FILTER (WHERE ecm.status = 'active') AS active_assignments,
  (SELECT COUNT(*) FROM entity_category) AS categories_defined
FROM entity_category_map ecm;

-- Category breakdown
SELECT ec.category_key, ec.category_label, COUNT(ecm.entity_id) AS count
FROM entity_category ec
LEFT JOIN entity_category_map ecm ON ec.category_id = ecm.category_id AND ecm.status = 'active'
GROUP BY ec.category_key, ec.category_label
ORDER BY count DESC;

-- Identifier namespaces
SELECT identifier_namespace, COUNT(*) AS count
FROM entity_identifier WHERE status = 'active'
GROUP BY identifier_namespace ORDER BY count DESC;

-- Changelog activity (last N days)
SELECT change_type, COUNT(*) AS count
FROM entity_change_log
WHERE created_time >= NOW() - INTERVAL '7 days'
GROUP BY change_type ORDER BY count DESC;

-- Last change
SELECT MAX(created_time) AS last_change FROM entity_change_log;
```
