"""
Vector & Geo schema migration script.

Adds per-space vector/geo tables to existing spaces that were created before
the vector/geo feature was introduced:
- {space_id}_vector_index  — per-space vector index registry
- {space_id}_vector_mapping — KG concept → vector index mapping
- {space_id}_vector_mapping_property — child property list per mapping
- {space_id}_geo_config — per-space geo configuration
- {space_id}_geo — PostGIS geography side-table for spatial queries

Also creates per-index vector data tables ({space_id}_vec_{index_name})
for any indexes already registered in vector_index.

Requires:
- pgvector extension (for vector columns in data tables)
- PostGIS extension (for geography type in geo table)

Can be run standalone or called from the admin CLI.

Usage:
    python -m vitalgraph.db.migrations.migrate_vector_geo_schema --database vitalgraph
    python -m vitalgraph.db.migrations.migrate_vector_geo_schema --dsn "postgresql://user:pass@host/db"
"""

import asyncio
import logging
import sys
from typing import Optional, List

import asyncpg

logger = logging.getLogger(__name__)


async def _ensure_extensions(conn: asyncpg.Connection) -> None:
    """Ensure required PostgreSQL extensions exist."""
    logger.info("Ensuring pgvector and PostGIS extensions...")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")


async def _get_all_space_ids(conn: asyncpg.Connection) -> List[str]:
    """Get all space_ids from the space table."""
    rows = await conn.fetch("SELECT space_id FROM space ORDER BY space_id")
    return [r['space_id'] for r in rows]


async def _table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    """Check if a table exists in the current database."""
    result = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
        table_name,
    )
    return bool(result)


async def _migrate_space(conn: asyncpg.Connection, space_id: str, dry_run: bool = False) -> None:
    """Add vector/geo tables to a single space if they don't already exist."""
    logger.info(f"  Migrating space: {space_id}")
    created = []
    missing = []

    # --- 1. Vector index registry ---
    tbl = f"{space_id}_vector_index"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if dry_run:
            pass
        else:
            await conn.execute(f'''
            CREATE TABLE {tbl} (
                index_id        SERIAL PRIMARY KEY,
                index_name      VARCHAR(255) NOT NULL UNIQUE,
                dimensions      INT NOT NULL,
                provider        VARCHAR(100) NOT NULL DEFAULT 'sentence_transformers',
                model_name      VARCHAR(255) NOT NULL DEFAULT 'all-MiniLM-L6-v2',
                provider_config JSONB DEFAULT '{{}}'::jsonb,
                created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            created.append(tbl)

    # --- 2. Vector mapping ---
    tbl = f"{space_id}_vector_mapping"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    mapping_id          SERIAL PRIMARY KEY,
                    mapping_type        VARCHAR(50) NOT NULL,
                    type_uri            VARCHAR(500),
                    source_type         VARCHAR(50) NOT NULL DEFAULT 'property',
                    index_name          VARCHAR(255) NOT NULL,
                    separator           VARCHAR(20) DEFAULT ' ',
                    include_pred_name   BOOLEAN DEFAULT FALSE,
                    include_type_desc   BOOLEAN DEFAULT TRUE,
                    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (index_name) REFERENCES {space_id}_vector_index(index_name)
                )
            ''')
            created.append(tbl)

    # --- 3. Vector mapping property ---
    tbl = f"{space_id}_vector_mapping_property"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    property_id     SERIAL PRIMARY KEY,
                    mapping_id      INTEGER NOT NULL,
                    property_uri    VARCHAR(500) NOT NULL,
                    property_role   VARCHAR(20) NOT NULL DEFAULT 'include',
                    ordinal         INTEGER DEFAULT 0,
                    UNIQUE (mapping_id, property_uri),
                    FOREIGN KEY (mapping_id) REFERENCES {space_id}_vector_mapping(mapping_id) ON DELETE CASCADE
                )
            ''')
            created.append(tbl)

    # --- 4. Geo config ---
    tbl = f"{space_id}_geo_config"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    config_id       SERIAL PRIMARY KEY,
                    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
                    auto_sync       BOOLEAN NOT NULL DEFAULT FALSE,
                    geo_datatype_uris TEXT[] NOT NULL DEFAULT ARRAY[
                        'http://www.opengis.net/ont/geosparql#wktLiteral',
                        'http://vital.ai/ontology/vital-core#geoLocation'
                    ],
                    lat_predicates  TEXT[] NOT NULL DEFAULT ARRAY[
                        'http://vital.ai/ontology/vital-aimp#hasLatitude'
                    ],
                    lon_predicates  TEXT[] NOT NULL DEFAULT ARRAY[
                        'http://vital.ai/ontology/vital-aimp#hasLongitude'
                    ],
                    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            created.append(tbl)
    else:
        # Add geo_datatype_uris column to existing tables
        if not dry_run:
            try:
                await conn.execute(f'''
                    ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS
                    geo_datatype_uris TEXT[] NOT NULL DEFAULT ARRAY[
                        'http://www.opengis.net/ont/geosparql#wktLiteral',
                        'http://vital.ai/ontology/vital-core#geoLocation'
                    ]
                ''')
            except Exception:
                pass  # Column may already exist

    # --- 5. Geo side-table ---
    tbl = f"{space_id}_geo"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    subject_uuid    UUID NOT NULL,
                    predicate_uuid  UUID,
                    location        geography(Point, 4326) NOT NULL,
                    latitude        DOUBLE PRECISION NOT NULL,
                    longitude       DOUBLE PRECISION NOT NULL,
                    context_uuid    UUID NOT NULL,
                    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (subject_uuid, context_uuid)
                )
            ''')
            # Geo indexes
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_gist ON {space_id}_geo USING gist (location)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_subj ON {space_id}_geo (subject_uuid)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_ctx ON {space_id}_geo (context_uuid)"
            )
            created.append(tbl)

    # --- 6. Seed geo datatypes into the datatype table ---
    dt_tbl = f"{space_id}_datatype"
    if await _table_exists(conn, dt_tbl) and not dry_run:
        geo_datatypes = [
            ('http://www.opengis.net/ont/geosparql#wktLiteral', 'wktLiteral'),
            ('http://vital.ai/ontology/vital-core#geoLocation', 'geoLocation'),
        ]
        await conn.executemany(
            f"INSERT INTO {dt_tbl} (datatype_uri, datatype_name) "
            f"VALUES ($1, $2) ON CONFLICT (datatype_uri) DO NOTHING",
            geo_datatypes,
        )

    # --- 7. Shared search mapping ---
    tbl = f"{space_id}_search_mapping"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    mapping_id          SERIAL PRIMARY KEY,
                    mapping_type        VARCHAR(50) NOT NULL,
                    type_uri            VARCHAR(500),
                    index_name          VARCHAR(255) NOT NULL,
                    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
                    source_type         VARCHAR(20) NOT NULL DEFAULT 'default',
                    separator           VARCHAR(20) DEFAULT '. ',
                    include_pred_name   BOOLEAN DEFAULT FALSE,
                    include_type_desc   BOOLEAN DEFAULT TRUE,
                    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            created.append(tbl)

    # --- 8. Shared search mapping property ---
    tbl = f"{space_id}_search_mapping_property"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    property_id     SERIAL PRIMARY KEY,
                    mapping_id      INTEGER NOT NULL,
                    property_uri    VARCHAR(500) NOT NULL,
                    property_role   VARCHAR(20) NOT NULL DEFAULT 'include',
                    ordinal         INTEGER DEFAULT 0,
                    UNIQUE (mapping_id, property_uri),
                    FOREIGN KEY (mapping_id) REFERENCES {space_id}_search_mapping(mapping_id) ON DELETE CASCADE
                )
            ''')
            created.append(tbl)

    # --- 9. FTS index registry ---
    tbl = f"{space_id}_fts_index"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    index_id        SERIAL PRIMARY KEY,
                    index_name      VARCHAR(255) NOT NULL UNIQUE,
                    languages       VARCHAR(64)[] NOT NULL DEFAULT '{{english}}',
                    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            created.append(tbl)

    # --- 10. Fuzzy mapping ---
    tbl = f"{space_id}_fuzzy_mapping"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    mapping_id      SERIAL PRIMARY KEY,
                    mapping_type    VARCHAR(50) NOT NULL,
                    type_uri        VARCHAR(500),
                    index_name      VARCHAR(255) NOT NULL,
                    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
                    shingle_k       INTEGER NOT NULL DEFAULT 3,
                    num_perm        INTEGER NOT NULL DEFAULT 64,
                    lsh_threshold   FLOAT NOT NULL DEFAULT 0.3,
                    phonetic_bonus  FLOAT NOT NULL DEFAULT 10.0,
                    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            created.append(tbl)

    # --- 11. Fuzzy mapping property ---
    tbl = f"{space_id}_fuzzy_mapping_property"
    if not await _table_exists(conn, tbl):
        missing.append(tbl)
        if not dry_run:
            await conn.execute(f'''
                CREATE TABLE {tbl} (
                    property_id     SERIAL PRIMARY KEY,
                    mapping_id      INTEGER NOT NULL,
                    property_uri    VARCHAR(500) NOT NULL,
                    property_role   VARCHAR(20) NOT NULL DEFAULT 'include',
                    ordinal         INTEGER DEFAULT 0,
                    UNIQUE (mapping_id, property_uri),
                    FOREIGN KEY (mapping_id) REFERENCES {space_id}_fuzzy_mapping(mapping_id) ON DELETE CASCADE
                )
            ''')
            created.append(tbl)

    if dry_run:
        if missing:
            logger.info(f"    Would create: {', '.join(missing)}")
        else:
            logger.info(f"    All tables already exist")
    else:
        if created:
            logger.info(f"    Created: {', '.join(created)}")
        else:
            logger.info(f"    All tables already exist")


async def migrate_vector_geo_schema(conn: asyncpg.Connection, dry_run: bool = False) -> None:
    """Add vector/geo tables to all existing spaces.

    Args:
        conn: Active asyncpg connection.
        dry_run: If True, only report what would be done without making changes.
    """
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info(f"Starting vector/geo schema migration ({mode})...")

    # Ensure extensions
    if not dry_run:
        await _ensure_extensions(conn)
    else:
        logger.info("Would ensure pgvector and PostGIS extensions")

    # Get all existing spaces
    space_ids = await _get_all_space_ids(conn)
    logger.info(f"Found {len(space_ids)} space(s) to migrate")

    if not space_ids:
        logger.info("No spaces found. Nothing to migrate.")
        return

    for space_id in space_ids:
        await _migrate_space(conn, space_id, dry_run=dry_run)

    logger.info(f"Vector/geo schema migration {mode} complete. Processed {len(space_ids)} space(s).")


async def run_migration(dsn: Optional[str] = None, dry_run: bool = False, **kwargs) -> None:
    """Run migration using a DSN or connection parameters.

    Args:
        dsn: PostgreSQL DSN string. If None, uses kwargs for connection params.
        dry_run: If True, only report what would be done.
        **kwargs: Connection params (host, port, database, user, password).
    """
    if dsn:
        conn = await asyncpg.connect(dsn)
    else:
        conn = await asyncpg.connect(**kwargs)

    try:
        if dry_run:
            await migrate_vector_geo_schema(conn, dry_run=True)
        else:
            async with conn.transaction():
                await migrate_vector_geo_schema(conn, dry_run=False)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Migrate VitalGraph vector/geo schema for existing spaces")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="vitalgraph")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--dsn", default=None, help="Full DSN (overrides other params)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done without making changes")
    args = parser.parse_args()

    if args.dsn:
        asyncio.run(run_migration(dsn=args.dsn, dry_run=args.dry_run))
    else:
        asyncio.run(run_migration(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
            dry_run=args.dry_run,
        ))


if __name__ == "__main__":
    main()
