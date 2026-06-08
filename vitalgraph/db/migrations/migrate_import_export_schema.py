"""
Import/Export job schema migration script.

Creates the ``import_export_job`` table used by ImportExportJobManager to
persist import and export job lifecycle state.

Can be run standalone or called programmatically.

Usage:
    python -m vitalgraph.db.migrations.migrate_import_export_schema --database vitalgraph
    python -m vitalgraph.db.migrations.migrate_import_export_schema --dsn "postgresql://user:pass@host/db"
"""

import asyncio
import logging
import sys
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


async def migrate_import_export_schema(conn: asyncpg.Connection) -> None:
    """Create the import_export_job table if it does not already exist.

    Args:
        conn: Active asyncpg connection (inside a transaction).
    """
    logger.info("Starting import_export schema migration...")

    # 1. Create import_export_job table
    table_exists = await conn.fetchval('''
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'import_export_job'
        )
    ''')

    if table_exists:
        logger.info("import_export_job table already exists — skipping creation.")
    else:
        logger.info("Creating import_export_job table...")
        await conn.execute('''
            CREATE TABLE import_export_job (
                job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_type        TEXT NOT NULL CHECK (job_type IN ('import', 'export')),
                space_id        VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
                graph_uri       TEXT,
                status          TEXT NOT NULL DEFAULT 'created'
                                CHECK (status IN ('created','pending','running','completed','failed','cancelled')),
                mode            TEXT NOT NULL DEFAULT 'append'
                                CHECK (mode IN ('append', 'replace')),
                progress_pct    REAL NOT NULL DEFAULT 0,
                records_done    BIGINT NOT NULL DEFAULT 0,
                records_total   BIGINT,
                file_s3_key     TEXT,
                file_name       TEXT,
                file_size       BIGINT,
                file_format     TEXT,
                config          JSONB,
                checkpoint_offset BIGINT DEFAULT 0,
                checkpoint_batch  INT DEFAULT 0,
                error_message   TEXT,
                log_entries     JSONB DEFAULT '[]'::jsonb,
                created_by      TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at      TIMESTAMPTZ,
                completed_at    TIMESTAMPTZ,
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        ''')
        logger.info("  ✅ import_export_job table created.")

    # 2. Create indexes (match init-sparql-sql.sql)
    logger.info("Creating indexes...")
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_iej_space_status
            ON import_export_job(space_id, status)
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_iej_created
            ON import_export_job(created_at DESC)
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_iej_type_status
            ON import_export_job(job_type, status)
    ''')

    logger.info("Import/export schema migration complete.")


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
            await migrate_import_export_schema(conn)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        description="Create VitalGraph import_export_job table")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="vitalgraph")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--dsn", default=None,
                        help="Full DSN (overrides other params)")
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
