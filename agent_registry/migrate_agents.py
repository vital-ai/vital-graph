#!/usr/bin/env python3
"""
Agent Registry Schema Migration Script.

Creates agent registry tables, indexes, and seed data in PostgreSQL
for the sparql_sql backend.

This is a standalone script — run it directly against PostgreSQL.
The running service never modifies the database schema.

Usage:
    python agent_registry/migrate_agents.py                  # Full setup
    python agent_registry/migrate_agents.py --dry-run        # Show what would run
    python agent_registry/migrate_agents.py --status         # Show current table status
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

from vitalgraph.config.config_loader import VitalGraphConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

LINE = '─' * 60

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

TABLES = [
    ('agent_type', '''
        CREATE TABLE IF NOT EXISTS agent_type (
            type_id SERIAL PRIMARY KEY,
            type_key VARCHAR(500) UNIQUE NOT NULL,
            type_label VARCHAR(255) NOT NULL,
            type_description TEXT,
            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    '''),
    ('agent', '''
        CREATE TABLE IF NOT EXISTS agent (
            agent_id VARCHAR(50) PRIMARY KEY,
            agent_type_id INTEGER NOT NULL REFERENCES agent_type(type_id),
            entity_id VARCHAR(50),
            agent_name VARCHAR(500) NOT NULL,
            agent_uri VARCHAR(500) NOT NULL,
            description TEXT,
            version VARCHAR(50),
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            protocol_format_uri VARCHAR(500),
            auth_service_uri VARCHAR(500),
            auth_service_config JSONB DEFAULT '{}',
            capabilities JSONB DEFAULT '[]',
            metadata JSONB DEFAULT '{}',
            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(255),
            notes TEXT
        )
    '''),
    ('agent_endpoint', '''
        CREATE TABLE IF NOT EXISTS agent_endpoint (
            endpoint_id SERIAL PRIMARY KEY,
            agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
            endpoint_uri VARCHAR(500) NOT NULL,
            endpoint_url VARCHAR(1000) NOT NULL,
            protocol VARCHAR(20) NOT NULL DEFAULT 'websocket',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    '''),
    ('agent_function', '''
        CREATE TABLE IF NOT EXISTS agent_function (
            function_id SERIAL PRIMARY KEY,
            agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
            function_uri VARCHAR(500) NOT NULL,
            function_name VARCHAR(255) NOT NULL,
            description TEXT,
            parameters JSONB DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    '''),
    ('agent_change_log', '''
        CREATE TABLE IF NOT EXISTS agent_change_log (
            log_id BIGSERIAL PRIMARY KEY,
            agent_id VARCHAR(50) REFERENCES agent(agent_id) ON DELETE SET NULL,
            change_type VARCHAR(50) NOT NULL,
            change_detail JSONB,
            changed_by VARCHAR(255),
            comment TEXT,
            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    '''),
]

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

INDEXES = [
    # agent table
    'CREATE INDEX IF NOT EXISTS idx_agent_type_id ON agent(agent_type_id)',
    'CREATE INDEX IF NOT EXISTS idx_agent_entity ON agent(entity_id)',
    'CREATE INDEX IF NOT EXISTS idx_agent_name ON agent(agent_name)',
    'CREATE INDEX IF NOT EXISTS idx_agent_uri ON agent(agent_uri)',
    'CREATE INDEX IF NOT EXISTS idx_agent_status ON agent(status)',
    'CREATE INDEX IF NOT EXISTS idx_agent_protocol ON agent(protocol_format_uri)',
    'CREATE INDEX IF NOT EXISTS idx_agent_auth_service ON agent(auth_service_uri)',
    'CREATE INDEX IF NOT EXISTS idx_agent_created ON agent(created_time)',
    'CREATE INDEX IF NOT EXISTS idx_agent_capabilities ON agent USING GIN(capabilities)',
    'CREATE INDEX IF NOT EXISTS idx_agent_metadata ON agent USING GIN(metadata)',
    # agent_endpoint table
    'CREATE INDEX IF NOT EXISTS idx_agent_ep_agent ON agent_endpoint(agent_id)',
    'CREATE INDEX IF NOT EXISTS idx_agent_ep_uri ON agent_endpoint(agent_id, endpoint_uri)',
    'CREATE INDEX IF NOT EXISTS idx_agent_ep_protocol ON agent_endpoint(protocol)',
    'CREATE INDEX IF NOT EXISTS idx_agent_ep_status ON agent_endpoint(status)',
    # agent_function table
    'CREATE INDEX IF NOT EXISTS idx_agent_fn_agent ON agent_function(agent_id)',
    'CREATE INDEX IF NOT EXISTS idx_agent_fn_key ON agent_function(agent_id, function_uri)',
    'CREATE INDEX IF NOT EXISTS idx_agent_fn_uri ON agent_function(function_uri)',
    'CREATE INDEX IF NOT EXISTS idx_agent_fn_status ON agent_function(status)',
    'CREATE INDEX IF NOT EXISTS idx_agent_fn_params ON agent_function USING GIN(parameters)',
    # Partial unique indexes — only enforce uniqueness on non-deleted rows
    # so that soft-deleted agents/endpoints/functions don't block re-creation.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_uri_active ON agent(agent_uri) WHERE status != 'deleted'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_ep_active ON agent_endpoint(agent_id, endpoint_uri) WHERE status != 'deleted'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_fn_active ON agent_function(agent_id, function_uri) WHERE status != 'deleted'",
    # agent_change_log table
    'CREATE INDEX IF NOT EXISTS idx_agent_log_agent ON agent_change_log(agent_id)',
    'CREATE INDEX IF NOT EXISTS idx_agent_log_type ON agent_change_log(change_type)',
    'CREATE INDEX IF NOT EXISTS idx_agent_log_time ON agent_change_log(created_time)',
]

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_AGENT_TYPES = [
    ('urn:vital-ai:agent-type:chat', 'Chat', 'Conversational chat agent'),
]

# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

VIEWS = [
    ('agent_active_view', '''
    CREATE OR REPLACE VIEW agent_active_view AS
        SELECT a.*, at.type_key, at.type_label
        FROM agent a
        JOIN agent_type at ON a.agent_type_id = at.type_id
        WHERE a.status = 'active'
    '''),
    ('agent_function_view', '''
    CREATE OR REPLACE VIEW agent_function_view AS
        SELECT af.*, a.agent_name, a.agent_uri, a.status AS agent_status
        FROM agent_function af
        JOIN agent a ON af.agent_id = a.agent_id
        WHERE af.status = 'active' AND a.status = 'active'
    '''),
]

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

async def get_pool() -> asyncpg.Pool:
    config = VitalGraphConfig()
    db_config = config.get_database_config()
    return await asyncpg.create_pool(
        host=db_config.get('host', 'localhost'),
        port=int(db_config.get('port', 5432)),
        database=db_config.get('database', 'vitalgraph'),
        user=db_config.get('username', 'postgres'),
        password=db_config.get('password', ''),
        min_size=1,
        max_size=3,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def run_create(pool: asyncpg.Pool, dry_run: bool):
    """Create tables, indexes, seed data, and views."""
    print("\n📋 CREATE: Agent registry tables, indexes, seeds, views")
    print(LINE)

    # Tables
    for table_name, ddl in TABLES:
        label = f"table: {table_name}"
        if dry_run:
            print(f"  [DRY RUN] {label}")
        else:
            await pool.execute(ddl)
            print(f"  ✅ {label}")

    # Indexes
    for idx_sql in INDEXES:
        idx_name = idx_sql.split('IF NOT EXISTS ')[1].split(' ON')[0]
        if dry_run:
            print(f"  [DRY RUN] index: {idx_name}")
        else:
            await pool.execute(idx_sql)
            print(f"  ✅ index: {idx_name}")

    # Seed data
    for type_key, type_label, type_desc in SEED_AGENT_TYPES:
        if dry_run:
            print(f"  [DRY RUN] seed: {type_key}")
        else:
            await pool.execute(
                "INSERT INTO agent_type (type_key, type_label, type_description) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT (type_key) DO NOTHING",
                type_key, type_label, type_desc,
            )
            print(f"  ✅ seed: {type_key}")

    # Views
    for view_name, view_sql in VIEWS:
        if dry_run:
            print(f"  [DRY RUN] view: {view_name}")
        else:
            await pool.execute(view_sql)
            print(f"  ✅ view: {view_name}")

    total = len(TABLES) + len(INDEXES) + len(SEED_AGENT_TYPES) + len(VIEWS)
    if dry_run:
        print(f"\nDRY RUN — {total} statements would be executed.")
    else:
        print(f"\n✅ {total} statements executed.")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

AGENT_TABLES = ['agent_type', 'agent', 'agent_endpoint', 'agent_function', 'agent_change_log']

async def check_status(pool: asyncpg.Pool):
    """Show current agent registry schema status."""
    print("\n📋 AGENT REGISTRY STATUS")
    print(LINE)

    for table in AGENT_TABLES:
        exists = await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
            table,
        )
        if exists:
            count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  ✅ {table:<25} ({count:,} rows)")
        else:
            print(f"  ❌ {table:<25} (missing)")

    # Check view
    has_view = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = $1)",
        'agent_active_view',
    )
    print(f"  {'agent_active_view':<25} {'✅ exists' if has_view else '❌ missing'}")

    # Check indexes
    print()
    idx_rows = await pool.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename IN ('agent', 'agent_type', 'agent_endpoint', 'agent_function', 'agent_change_log') ORDER BY indexname"
    )
    if idx_rows:
        print(f"  Indexes ({len(idx_rows)}):")
        for row in idx_rows:
            print(f"    ✅ {row['indexname']}")
    else:
        print("  ❌ No indexes found")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        prog='migrate_agents',
        description='Agent Registry schema migration tool (sparql_sql backend)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Show what would run without executing')
    parser.add_argument('--status', action='store_true', help='Show current agent registry table status')
    args = parser.parse_args()

    pool = await get_pool()

    try:
        if args.status:
            await check_status(pool)
        else:
            await run_create(pool, args.dry_run)
            if not args.dry_run:
                print()
                await check_status(pool)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
