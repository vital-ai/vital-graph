"""
PostgreSQL schema for the sparql_sql backend.

Defines DDL for:
- Per-space data tables: term, rdf_quad, datatype
- Per-space auxiliary tables: rdf_pred_stats, rdf_stats, edge
- Indexes optimized for the V2 SPARQL-to-SQL pipeline
- Standard XSD datatype seed data

Unlike the fuseki_postgresql backend (which relies on Fuseki for query
indexing), this backend queries PostgreSQL directly, so proper indexes
on term and rdf_quad are essential.

Admin tables (install, space, graph, user) are shared with the
fuseki_postgresql backend and reused from its schema.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standard XSD datatypes (seeded into {space_id}_datatype on creation)
# ---------------------------------------------------------------------------

STANDARD_DATATYPES: List[Tuple[str, str]] = [
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


class SparqlSQLSchema:
    """
    PostgreSQL schema for the sparql_sql backend.

    Reuses the same admin tables as fuseki_postgresql (install, space,
    graph, user). Per-space tables include data tables (term, rdf_quad),
    the datatype lookup table, and auxiliary tables for the V2 pipeline
    (rdf_pred_stats, rdf_stats, edge).
    """

    # ------------------------------------------------------------------
    # Table name helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_table_names(space_id: str) -> Dict[str, str]:
        """Return all per-space table names."""
        return {
            'term': f'{space_id}_term',
            'rdf_quad': f'{space_id}_rdf_quad',
            'datatype': f'{space_id}_datatype',
            'rdf_pred_stats': f'{space_id}_rdf_pred_stats',
            'rdf_stats': f'{space_id}_rdf_stats',
            'edge': f'{space_id}_edge',
            'frame_entity': f'{space_id}_frame_entity',
        }

    # ------------------------------------------------------------------
    # Per-space DDL generators
    # ------------------------------------------------------------------

    def create_space_tables_sql(self, space_id: str) -> List[str]:
        """Return SQL statements to create all per-space tables."""
        t = self.get_table_names(space_id)
        stmts: List[str] = []

        # 1. Term dictionary
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['term']} (
                term_uuid    UUID PRIMARY KEY,
                term_text    TEXT NOT NULL,
                term_type    CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
                lang         VARCHAR(20),
                datatype_id  BIGINT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                dataset      VARCHAR(50) NOT NULL DEFAULT 'primary'
            )
        ''')

        # 2. Datatype lookup
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['datatype']} (
                datatype_id   BIGSERIAL PRIMARY KEY,
                datatype_uri  VARCHAR(255) NOT NULL UNIQUE,
                datatype_name VARCHAR(100),
                created_time  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 3. RDF quad table
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['rdf_quad']} (
                subject_uuid   UUID NOT NULL,
                predicate_uuid UUID NOT NULL,
                object_uuid    UUID NOT NULL,
                context_uuid   UUID NOT NULL,
                quad_uuid      UUID NOT NULL DEFAULT gen_random_uuid(),
                dataset        VARCHAR(50) NOT NULL DEFAULT 'primary',
                PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid)
            )
        ''')

        # 4. Predicate statistics (used by generator for join reordering)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['rdf_pred_stats']} (
                predicate_uuid UUID PRIMARY KEY,
                row_count      BIGINT NOT NULL DEFAULT 0
            )
        ''')

        # 5. Predicate-object statistics
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['rdf_stats']} (
                predicate_uuid UUID NOT NULL,
                object_uuid    UUID NOT NULL,
                row_count      BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (predicate_uuid, object_uuid)
            )
        ''')

        # 6. Edge table (maintained by app-level sync; replaces edge MV)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['edge']} (
                edge_uuid        UUID NOT NULL,
                source_node_uuid UUID NOT NULL,
                dest_node_uuid   UUID NOT NULL,
                context_uuid     UUID NOT NULL,
                PRIMARY KEY (edge_uuid, context_uuid)
            )
        ''')

        # 7. Frame-entity table (maintained by app-level sync; replaces frame_entity MV)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['frame_entity']} (
                frame_uuid           UUID NOT NULL,
                source_entity_uuid   UUID,
                dest_entity_uuid     UUID,
                context_uuid         UUID NOT NULL,
                PRIMARY KEY (frame_uuid, context_uuid)
            )
        ''')

        return stmts

    def create_space_indexes_sql(self, space_id: str) -> List[str]:
        """Return SQL statements to create indexes on per-space tables.

        These are critical for the V2 pipeline which queries PostgreSQL
        directly (unlike fuseki_postgresql which relies on Fuseki).
        """
        t = self.get_table_names(space_id)
        return [
            # Term table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_tt ON {t['term']} (term_text, term_type)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_type ON {t['term']} (term_type)",
            # GIN trigram index for REGEX/CONTAINS/LIKE text filters (requires pg_trgm)
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_trgm ON {t['term']} USING gin (term_text gin_trgm_ops)",

            # Quad table indexes — essential for V2 SQL generation
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_pred ON {t['rdf_quad']} (predicate_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_subj ON {t['rdf_quad']} (subject_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_obj ON {t['rdf_quad']} (object_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_ctx ON {t['rdf_quad']} (context_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_po ON {t['rdf_quad']} (predicate_uuid, object_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_ps ON {t['rdf_quad']} (predicate_uuid, subject_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_sp ON {t['rdf_quad']} (subject_uuid, predicate_uuid)",

            # Datatype lookup index
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_datatype_uri ON {t['datatype']} (datatype_uri)",

            # Edge table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_src_dst ON {t['edge']} (source_node_uuid, dest_node_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_dst_src ON {t['edge']} (dest_node_uuid, source_node_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_edge ON {t['edge']} (edge_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_ctx ON {t['edge']} (context_uuid)",

            # Frame-entity table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_src_frame ON {t['frame_entity']} (source_entity_uuid, frame_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_dst_frame ON {t['frame_entity']} (dest_entity_uuid, frame_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_frame ON {t['frame_entity']} (frame_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_ctx ON {t['frame_entity']} (context_uuid)",
        ]

    def drop_space_tables_sql(self, space_id: str) -> List[str]:
        """Return SQL statements to drop all per-space tables/views."""
        t = self.get_table_names(space_id)
        return [
            f"DROP TABLE IF EXISTS {t['frame_entity']} CASCADE",
            f"DROP TABLE IF EXISTS {t['edge']} CASCADE",
            f"DROP TABLE IF EXISTS {t['rdf_stats']} CASCADE",
            f"DROP TABLE IF EXISTS {t['rdf_pred_stats']} CASCADE",
            f"DROP TABLE IF EXISTS {t['rdf_quad']} CASCADE",
            f"DROP TABLE IF EXISTS {t['term']} CASCADE",
            f"DROP TABLE IF EXISTS {t['datatype']} CASCADE",
        ]

    def drop_space_indexes_sql(self, space_id: str) -> List[str]:
        """Return SQL to drop per-space indexes (for bulk load optimization)."""
        t = self.get_table_names(space_id)
        return [
            f"DROP INDEX IF EXISTS idx_{space_id}_term_tt",
            f"DROP INDEX IF EXISTS idx_{space_id}_term_type",
            f"DROP INDEX IF EXISTS idx_{space_id}_term_trgm",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_pred",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_subj",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_obj",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_ctx",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_po",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_ps",
            f"DROP INDEX IF EXISTS idx_{space_id}_quad_sp",
            f"DROP INDEX IF EXISTS idx_{space_id}_datatype_uri",
        ]

    # ------------------------------------------------------------------
    # Async helpers (execute against a connection)
    # ------------------------------------------------------------------

    @staticmethod
    async def create_space(conn, space_id: str) -> None:
        """Create all per-space tables, indexes, and seed datatypes."""
        schema = SparqlSQLSchema()

        for stmt in schema.create_space_tables_sql(space_id):
            await conn.execute(stmt)

        for stmt in schema.create_space_indexes_sql(space_id):
            await conn.execute(stmt)

        # Seed standard datatypes
        t = schema.get_table_names(space_id)
        await conn.executemany(
            f"INSERT INTO {t['datatype']} (datatype_uri, datatype_name) "
            f"VALUES ($1, $2) ON CONFLICT (datatype_uri) DO NOTHING",
            STANDARD_DATATYPES,
        )

        logger.info("Created space tables for: %s", space_id)

    @staticmethod
    async def drop_space(conn, space_id: str) -> None:
        """Drop all per-space tables and views."""
        schema = SparqlSQLSchema()
        for stmt in schema.drop_space_tables_sql(space_id):
            await conn.execute(stmt)
        logger.info("Dropped space tables for: %s", space_id)

    @staticmethod
    async def space_tables_exist(conn, space_id: str) -> bool:
        """Check if the core data tables exist for a space."""
        t = SparqlSQLSchema.get_table_names(space_id)
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN ($1, $2)",
            t['term'], t['rdf_quad'],
        )
        return count == 2

