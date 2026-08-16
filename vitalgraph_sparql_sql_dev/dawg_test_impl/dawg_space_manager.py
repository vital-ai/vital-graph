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
    """Create the DAWG scratch space using the CANONICAL schema.

    This used to carry its own "simplified DDL" — a second copy of the term,
    quad, datatype and stats tables. It drifted, as second copies do, and the
    drift was invisible until a generated query happened to use a column the
    copy lacked:

        DELETE { ?s ex:salary ?o } INSERT { ?s ex:salary ?v }
        WHERE { ?s ex:salary ?o FILTER(?o < 1500) BIND(?o + 100 AS ?v) }

    The generator pushes that FILTER down to `num_val < 1500.0`, using the
    STORED GENERATED column on the term table. The real schema has it; this
    copy did not, so the DAWG delete-insert/Halloween-Problem case failed with
    `column "num_val" does not exist` — a conformance failure that was not a
    conformance problem at all.

    The copy had also missed the (s,p,o,c) primary key, so this space still
    permitted duplicate quads after the real schema stopped doing so.

    Building from `create_space_tables_sql` means the suite tests the schema
    that ships. Everything is IF NOT EXISTS, so it stays safe to call
    repeatedly, and the datatype seeding below is DATA rather than schema and
    stays here.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    schema = SparqlSQLSchema()
    for stmt in schema.create_space_tables_sql(space_id):
        await conn.execute(stmt)
    # Indexes are best-effort: a failure here costs speed, not correctness, and
    # must not stop the suite from running.
    for stmt in schema.create_space_indexes_sql(space_id):
        try:
            await conn.execute(stmt)
        except Exception:
            pass

    tables = get_table_names(space_id)

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

    # The stats, edge and frame_entity tables come from the canonical schema
    # above. They used to be re-declared here, and those copies had drifted:
    # rdf_pred_stats was missing `pruned`, and edge was missing
    # `edge_type_uuid`. Being IF NOT EXISTS they were already dead once the
    # real DDL ran first — but a dead wrong copy is what the next person reads.

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
