"""
Metrics schema migration script.

Migrates existing query_metrics table to support the PostgreSQL-only metrics system:
- Adds bucket_granularity column (if missing)
- Expands PK to include bucket_granularity
- Backfills existing rows as 'hour' granularity
- Creates slow_query_log table
- Creates necessary indexes

Can be run standalone or called from the admin CLI.

Usage:
    python -m vitalgraph.db.migrations.migrate_metrics_schema --database vitalgraph
    python -m vitalgraph.db.migrations.migrate_metrics_schema --dsn "postgresql://user:pass@host/db"
"""

import asyncio
import logging
import sys
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


async def migrate_metrics_schema(conn: asyncpg.Connection) -> None:
    """Migrate query_metrics and create slow_query_log for PG-only metrics.

    Args:
        conn: Active asyncpg connection.
    """
    logger.info("Starting metrics schema migration...")

    # 1. Check if query_metrics table exists
    table_exists = await conn.fetchval('''
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'query_metrics'
        )
    ''')

    if not table_exists:
        # Fresh install — create the table with the new schema directly
        logger.info("Step 1: Creating query_metrics table (fresh install)...")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS query_metrics (
                space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
                bucket_start TIMESTAMPTZ NOT NULL,
                bucket_granularity VARCHAR(10) NOT NULL DEFAULT 'minute',
                endpoint VARCHAR(100) NOT NULL,
                request_count BIGINT NOT NULL DEFAULT 0,
                error_count BIGINT NOT NULL DEFAULT 0,
                total_ms BIGINT NOT NULL DEFAULT 0,
                max_ms INTEGER NOT NULL DEFAULT 0,
                p95_ms INTEGER,
                PRIMARY KEY (space_id, bucket_start, endpoint, bucket_granularity)
            )
        ''')
    else:
        # Existing table — need to add column and re-key
        logger.info("Step 1: Migrating existing query_metrics table...")

        # Check if bucket_granularity column already exists
        col_exists = await conn.fetchval('''
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'query_metrics' AND column_name = 'bucket_granularity'
            )
        ''')

        if not col_exists:
            logger.info("  Adding bucket_granularity column...")
            await conn.execute('''
                ALTER TABLE query_metrics
                ADD COLUMN bucket_granularity VARCHAR(10) NOT NULL DEFAULT 'minute'
            ''')

            # Backfill existing rows as 'hour' (they came from the old Redis rollup)
            updated = await conn.execute('''
                UPDATE query_metrics SET bucket_granularity = 'hour'
                WHERE bucket_granularity = 'minute'
            ''')
            logger.info(f"  Backfilled existing rows as 'hour': {updated}")
        else:
            logger.info("  bucket_granularity column already exists")

        # Check if PK already includes bucket_granularity
        pk_cols = await conn.fetch('''
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'query_metrics'::regclass AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
        ''')
        pk_col_names = [r['attname'] for r in pk_cols]

        if 'bucket_granularity' not in pk_col_names:
            logger.info("  Expanding PK to include bucket_granularity...")
            await conn.execute('ALTER TABLE query_metrics DROP CONSTRAINT query_metrics_pkey')
            await conn.execute('''
                ALTER TABLE query_metrics
                ADD PRIMARY KEY (space_id, bucket_start, endpoint, bucket_granularity)
            ''')
            logger.info("  PK updated: (space_id, bucket_start, endpoint, bucket_granularity)")
        else:
            logger.info("  PK already includes bucket_granularity")

        # Add p95_ms column if missing
        p95_exists = await conn.fetchval('''
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'query_metrics' AND column_name = 'p95_ms'
            )
        ''')
        if not p95_exists:
            logger.info("  Adding p95_ms column...")
            await conn.execute('ALTER TABLE query_metrics ADD COLUMN p95_ms INTEGER')

    # 2. Create space_analytics table
    logger.info("Step 2: Creating space_analytics table...")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS space_analytics (
            id SERIAL PRIMARY KEY,
            space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            computation_time_ms INTEGER,
            analytics_json JSONB NOT NULL
        )
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_space_analytics_space
            ON space_analytics(space_id)
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_space_analytics_latest
            ON space_analytics(space_id, computed_at DESC)
    ''')

    # 3. Create indexes on query_metrics
    logger.info("Step 3: Creating query_metrics indexes...")
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_query_metrics_time
            ON query_metrics(bucket_start DESC)
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_query_metrics_space_gran
            ON query_metrics(space_id, bucket_granularity, bucket_start DESC)
    ''')

    # 4. Create slow_query_log table
    logger.info("Step 4: Creating slow_query_log table...")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS slow_query_log (
            id BIGSERIAL PRIMARY KEY,
            space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
            endpoint VARCHAR(100) NOT NULL,
            duration_ms INTEGER NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata JSONB
        )
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_slow_query_space_time
            ON slow_query_log(space_id, recorded_at DESC)
    ''')

    logger.info("Metrics schema migration complete.")


async def run_migration(dsn: Optional[str] = None, **kwargs) -> None:
    """Run migration using a DSN or connection parameters.

    Args:
        dsn: PostgreSQL DSN string. If None, uses kwargs for connection params.
        **kwargs: Connection params (host, port, database, user, password).
    """
    if dsn:
        conn = await asyncpg.connect(dsn)
    else:
        conn = await asyncpg.connect(**kwargs)

    try:
        async with conn.transaction():
            await migrate_metrics_schema(conn)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Migrate VitalGraph metrics schema")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="vitalgraph")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--dsn", default=None, help="Full DSN (overrides other params)")
    args = parser.parse_args()

    if args.dsn:
        asyncio.run(run_migration(dsn=args.dsn))
    else:
        asyncio.run(run_migration(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
        ))


if __name__ == "__main__":
    main()
