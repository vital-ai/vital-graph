"""
Manage PostgreSQL space tables for DAWG test execution.

Creates simplified (non-partitioned) term and rdf_quad tables
for the dawg_test space. DAWG datasets are tiny (~4-50 triples)
so we skip GIN/GiST indexes and partitioning for speed.

All functions are async and accept an asyncpg connection.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

SPACE_ID = "dawg_test"


def get_table_names(space_id: str = SPACE_ID) -> Dict[str, str]:
    return {
        "term": f"{space_id}_term",
        "rdf_quad": f"{space_id}_rdf_quad",
        "datatype": f"{space_id}_datatype",
        "rdf_pred_stats": f"{space_id}_rdf_pred_stats",
        "rdf_stats": f"{space_id}_rdf_stats",
        "edge": f"{space_id}_edge",
        "frame_entity": f"{space_id}_frame_entity",
    }


async def create_space(conn, space_id: str = SPACE_ID):
    """Create the term and rdf_quad tables for the DAWG test space.

    Uses simplified DDL — no partitioning, minimal indexes.
    Safe to call repeatedly (IF NOT EXISTS).
    """
    tables = get_table_names(space_id)

    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['term']} (
            term_uuid  UUID PRIMARY KEY,
            term_text  TEXT NOT NULL,
            term_type  CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
            lang       VARCHAR(20),
            datatype_id BIGINT,
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dataset    VARCHAR(50) NOT NULL DEFAULT 'primary'
        )
    """)

    # Datatype lookup table (matches production schema)
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['datatype']} (
            datatype_id BIGSERIAL PRIMARY KEY,
            datatype_uri VARCHAR(255) NOT NULL UNIQUE,
            datatype_name VARCHAR(100),
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{space_id}_datatype_uri ON {tables['datatype']} (datatype_uri)")

    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['rdf_quad']} (
            subject_uuid   UUID NOT NULL,
            predicate_uuid UUID NOT NULL,
            object_uuid    UUID NOT NULL,
            context_uuid   UUID NOT NULL,
            quad_uuid      UUID NOT NULL DEFAULT gen_random_uuid(),
            dataset        VARCHAR(50) NOT NULL DEFAULT 'primary',
            PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid)
        )
    """)

    # Minimal indexes for SQL generator
    await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_pred ON {tables['rdf_quad']} (predicate_uuid)")
    await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_subj ON {tables['rdf_quad']} (subject_uuid)")
    await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_obj ON {tables['rdf_quad']} (object_uuid)")
    await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_po ON {tables['rdf_quad']} (predicate_uuid, object_uuid)")
    await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_tt ON {tables['term']} (term_text, term_type)")

    # Populate standard XSD datatypes
    _STANDARD_DATATYPES = [
        ('http://www.w3.org/2001/XMLSchema#string', 'string'),
        ('http://www.w3.org/2001/XMLSchema#boolean', 'boolean'),
        ('http://www.w3.org/2001/XMLSchema#decimal', 'decimal'),
        ('http://www.w3.org/2001/XMLSchema#integer', 'integer'),
        ('http://www.w3.org/2001/XMLSchema#double', 'double'),
        ('http://www.w3.org/2001/XMLSchema#float', 'float'),
        ('http://www.w3.org/2001/XMLSchema#date', 'date'),
        ('http://www.w3.org/2001/XMLSchema#time', 'time'),
        ('http://www.w3.org/2001/XMLSchema#dateTime', 'dateTime'),
        ('http://www.w3.org/2001/XMLSchema#long', 'long'),
        ('http://www.w3.org/2001/XMLSchema#int', 'int'),
        ('http://www.w3.org/2001/XMLSchema#short', 'short'),
        ('http://www.w3.org/2001/XMLSchema#byte', 'byte'),
        ('http://www.w3.org/2001/XMLSchema#unsignedLong', 'unsignedLong'),
        ('http://www.w3.org/2001/XMLSchema#unsignedInt', 'unsignedInt'),
        ('http://www.w3.org/2001/XMLSchema#unsignedShort', 'unsignedShort'),
        ('http://www.w3.org/2001/XMLSchema#unsignedByte', 'unsignedByte'),
        ('http://www.w3.org/2001/XMLSchema#positiveInteger', 'positiveInteger'),
        ('http://www.w3.org/2001/XMLSchema#nonNegativeInteger', 'nonNegativeInteger'),
        ('http://www.w3.org/2001/XMLSchema#negativeInteger', 'negativeInteger'),
        ('http://www.w3.org/2001/XMLSchema#nonPositiveInteger', 'nonPositiveInteger'),
        ('http://www.w3.org/2001/XMLSchema#duration', 'duration'),
        ('http://www.w3.org/2001/XMLSchema#dayTimeDuration', 'dayTimeDuration'),
        ('http://www.w3.org/2001/XMLSchema#yearMonthDuration', 'yearMonthDuration'),
        ('http://www.w3.org/2001/XMLSchema#hexBinary', 'hexBinary'),
        ('http://www.w3.org/2001/XMLSchema#base64Binary', 'base64Binary'),
        ('http://www.w3.org/2001/XMLSchema#anyURI', 'anyURI'),
        ('http://www.w3.org/2001/XMLSchema#language', 'language'),
        ('http://www.w3.org/2001/XMLSchema#normalizedString', 'normalizedString'),
        ('http://www.w3.org/2001/XMLSchema#token', 'token'),
        ('http://www.w3.org/2001/XMLSchema#gYear', 'gYear'),
        ('http://www.w3.org/2001/XMLSchema#gMonth', 'gMonth'),
        ('http://www.w3.org/2001/XMLSchema#gDay', 'gDay'),
        ('http://www.w3.org/2001/XMLSchema#gYearMonth', 'gYearMonth'),
        ('http://www.w3.org/2001/XMLSchema#gMonthDay', 'gMonthDay'),
        ('http://www.w3.org/1999/02/22-rdf-syntax-ns#XMLLiteral', 'XMLLiteral'),
        ('http://www.w3.org/1999/02/22-rdf-syntax-ns#HTML', 'HTML'),
        ('http://www.w3.org/1999/02/22-rdf-syntax-ns#langString', 'langString'),
    ]
    await conn.executemany(
        f"INSERT INTO {tables['datatype']} (datatype_uri, datatype_name) "
        f"VALUES ($1, $2) ON CONFLICT (datatype_uri) DO NOTHING",
        _STANDARD_DATATYPES,
    )

    # Empty stats tables — the SQL generator queries these during
    # generate_sql(). Without them, the query fails.
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['rdf_pred_stats']} (
            predicate_uuid UUID PRIMARY KEY,
            row_count      BIGINT NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['rdf_stats']} (
            predicate_uuid UUID NOT NULL,
            object_uuid    UUID NOT NULL,
            row_count      BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY (predicate_uuid, object_uuid)
        )
    """)

    # Edge table (maintained by app-level sync; replaces old edge MV)
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['edge']} (
            edge_uuid        UUID NOT NULL,
            source_node_uuid UUID NOT NULL,
            dest_node_uuid   UUID NOT NULL,
            context_uuid     UUID NOT NULL,
            PRIMARY KEY (edge_uuid, context_uuid)
        )
    """)

    # Frame-entity table (maintained by app-level sync; replaces frame_entity MV)
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {tables['frame_entity']} (
            frame_uuid           UUID NOT NULL,
            source_entity_uuid   UUID,
            dest_entity_uuid     UUID,
            context_uuid         UUID NOT NULL,
            PRIMARY KEY (frame_uuid, context_uuid)
        )
    """)

    logger.info("Created space tables: %s", list(tables.values()))


async def truncate_space(conn, space_id: str = SPACE_ID):
    """Truncate both tables to prepare for new test data."""
    tables = get_table_names(space_id)
    await conn.execute(f"TRUNCATE {tables['rdf_quad']}")
    await conn.execute(f"TRUNCATE {tables['term']}")


async def drop_space(conn, space_id: str = SPACE_ID):
    """Drop the space tables entirely."""
    tables = get_table_names(space_id)
    await conn.execute(f"DROP TABLE IF EXISTS {tables['frame_entity']} CASCADE")
    await conn.execute(f"DROP TABLE IF EXISTS {tables['edge']} CASCADE")
    await conn.execute(f"DROP TABLE IF EXISTS {tables['rdf_stats']} CASCADE")
    await conn.execute(f"DROP TABLE IF EXISTS {tables['rdf_pred_stats']} CASCADE")
    await conn.execute(f"DROP TABLE IF EXISTS {tables['rdf_quad']} CASCADE")
    await conn.execute(f"DROP TABLE IF EXISTS {tables['term']} CASCADE")
    await conn.execute(f"DROP TABLE IF EXISTS {tables['datatype']} CASCADE")
    logger.info("Dropped space tables: %s", list(tables.values()))


async def space_exists(conn, space_id: str = SPACE_ID) -> bool:
    """Check if the space tables exist."""
    tables = get_table_names(space_id)
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name IN ($1, $2)",
        tables['term'], tables['rdf_quad'],
    )
    return count == 2
