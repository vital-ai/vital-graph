"""
PostgreSQL schema for the sparql_sql backend.

Defines DDL for:
- Admin tables: install, space, graph, user, process, agent registry
- Per-space data tables: term, rdf_quad, datatype
- Per-space auxiliary tables: rdf_pred_stats, rdf_stats, edge
- Indexes optimized for the V2 SPARQL-to-SQL pipeline
- Standard XSD datatype seed data

Unlike the fuseki_postgresql backend (which relies on Fuseki for query
indexing), this backend queries PostgreSQL directly, so proper indexes
on term and rdf_quad are essential.
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

    Owns all DDL for this backend:
    - Admin tables: install, space, graph, user, process, agent registry
    - Per-space data tables: term, rdf_quad, datatype
    - Per-space auxiliary tables: rdf_pred_stats, rdf_stats, edge, frame_entity
    """

    # ==================================================================
    # Admin tables
    # ==================================================================

    ADMIN_TABLE_DDL: List[Tuple[str, str]] = [
        ("install", '''
            CREATE TABLE IF NOT EXISTS install (
                id SERIAL PRIMARY KEY,
                install_datetime TIMESTAMP,
                update_datetime TIMESTAMP,
                active BOOLEAN
            )
        '''),
        ("space", '''
            CREATE TABLE IF NOT EXISTS space (
                space_id VARCHAR(255) PRIMARY KEY,
                space_name VARCHAR(255),
                space_description TEXT,
                tenant VARCHAR(255),
                update_time TIMESTAMP
            )
        '''),
        ("graph", '''
            CREATE TABLE IF NOT EXISTS graph (
                graph_id SERIAL PRIMARY KEY,
                space_id VARCHAR(255) NOT NULL,
                graph_uri VARCHAR(500),
                graph_name VARCHAR(255),
                created_time TIMESTAMP,
                FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE,
                UNIQUE (space_id, graph_uri)
            )
        '''),
        ('"user"', '''
            CREATE TABLE IF NOT EXISTS "user" (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255),
                email VARCHAR(255),
                tenant VARCHAR(255),
                update_time TIMESTAMP
            )
        '''),
        ("process", '''
            CREATE TABLE IF NOT EXISTS process (
                process_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                process_type VARCHAR(64) NOT NULL,
                process_subtype VARCHAR(128),
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                instance_id VARCHAR(128),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                progress_percent REAL DEFAULT 0.0,
                progress_message TEXT,
                error_message TEXT,
                result_details JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        '''),
        # --- Agent Registry tables ---
        ("agent_type", '''
            CREATE TABLE IF NOT EXISTS agent_type (
                type_id SERIAL PRIMARY KEY,
                type_key VARCHAR(500) UNIQUE NOT NULL,
                type_label VARCHAR(255) NOT NULL,
                type_description TEXT,
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        '''),
        ("agent", '''
            CREATE TABLE IF NOT EXISTS agent (
                agent_id VARCHAR(50) PRIMARY KEY,
                agent_type_id INTEGER NOT NULL REFERENCES agent_type(type_id),
                entity_id VARCHAR(50),
                agent_name VARCHAR(500) NOT NULL,
                agent_uri VARCHAR(500) UNIQUE NOT NULL,
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
        ("agent_endpoint", '''
            CREATE TABLE IF NOT EXISTS agent_endpoint (
                endpoint_id SERIAL PRIMARY KEY,
                agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
                endpoint_uri VARCHAR(500) NOT NULL,
                endpoint_url VARCHAR(1000) NOT NULL,
                protocol VARCHAR(20) NOT NULL DEFAULT 'websocket',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                UNIQUE (agent_id, endpoint_uri)
            )
        '''),
        ("agent_change_log", '''
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

    ADMIN_TABLE_NAMES: List[str] = [name.strip('"') for name, _ in ADMIN_TABLE_DDL]

    ADMIN_INDEX_DDL: List[str] = [
        # Core admin indexes
        "CREATE INDEX IF NOT EXISTS idx_space_tenant ON space(tenant)",
        "CREATE INDEX IF NOT EXISTS idx_space_update_time ON space(update_time)",
        "CREATE INDEX IF NOT EXISTS idx_graph_space_id ON graph(space_id)",
        "CREATE INDEX IF NOT EXISTS idx_graph_uri ON graph(graph_uri)",
        'CREATE INDEX IF NOT EXISTS idx_user_tenant ON "user"(tenant)',
        'CREATE INDEX IF NOT EXISTS idx_user_username ON "user"(username)',
        "CREATE INDEX IF NOT EXISTS idx_process_type_status ON process(process_type, status)",
        "CREATE INDEX IF NOT EXISTS idx_process_created ON process(created_at DESC)",
        # Agent registry indexes
        "CREATE INDEX IF NOT EXISTS idx_agent_type_id ON agent(agent_type_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_entity ON agent(entity_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_name ON agent(agent_name)",
        "CREATE INDEX IF NOT EXISTS idx_agent_uri ON agent(agent_uri)",
        "CREATE INDEX IF NOT EXISTS idx_agent_status ON agent(status)",
        "CREATE INDEX IF NOT EXISTS idx_agent_protocol ON agent(protocol_format_uri)",
        "CREATE INDEX IF NOT EXISTS idx_agent_auth_service ON agent(auth_service_uri)",
        "CREATE INDEX IF NOT EXISTS idx_agent_created ON agent(created_time)",
        "CREATE INDEX IF NOT EXISTS idx_agent_ep_agent ON agent_endpoint(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_ep_uri ON agent_endpoint(agent_id, endpoint_uri)",
        "CREATE INDEX IF NOT EXISTS idx_agent_ep_protocol ON agent_endpoint(protocol)",
        "CREATE INDEX IF NOT EXISTS idx_agent_ep_status ON agent_endpoint(status)",
        "CREATE INDEX IF NOT EXISTS idx_agent_log_agent ON agent_change_log(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_log_type ON agent_change_log(change_type)",
        "CREATE INDEX IF NOT EXISTS idx_agent_log_time ON agent_change_log(created_time)",
    ]

    ADMIN_SEED_STATEMENTS: List[str] = [
        # Install record
        "INSERT INTO install (install_datetime, update_datetime, active) "
        "SELECT NOW(), NOW(), true "
        "WHERE NOT EXISTS (SELECT 1 FROM install)",
        # Default agent type
        "INSERT INTO agent_type (type_key, type_label, type_description) "
        "SELECT 'urn:vital-ai:agent-type:chat', 'Chat', 'Conversational chat agent' "
        "WHERE NOT EXISTS (SELECT 1 FROM agent_type WHERE type_key = 'urn:vital-ai:agent-type:chat')",
    ]

    # Reverse-dependency order for truncate / drop operations
    ADMIN_DROP_ORDER: List[str] = [
        'agent_change_log', 'agent_endpoint', 'agent', 'agent_type',
        'process', 'graph', '"user"', 'space', 'install',
    ]

    # ------------------------------------------------------------------
    # Admin DDL helpers
    # ------------------------------------------------------------------

    def create_admin_tables_sql(self) -> List[str]:
        """Get SQL statements to create all admin tables."""
        return [ddl.strip() for _, ddl in self.ADMIN_TABLE_DDL]

    def create_admin_indexes_sql(self) -> List[str]:
        """Get SQL statements to create all admin table indexes."""
        return list(self.ADMIN_INDEX_DDL)

    def get_admin_seed_sql(self) -> List[str]:
        """Get SQL statements to seed initial admin data."""
        return list(self.ADMIN_SEED_STATEMENTS)

    def drop_admin_tables_sql(self) -> List[str]:
        """Get SQL statements to drop all admin tables (reverse dependency order)."""
        return [f"DROP TABLE IF EXISTS {t} CASCADE" for t in self.ADMIN_DROP_ORDER]

    def truncate_admin_tables_sql(self) -> List[str]:
        """Get SQL statements to truncate all admin tables (reverse dependency order)."""
        return [f"TRUNCATE TABLE {t} CASCADE" for t in self.ADMIN_DROP_ORDER]

    # ==================================================================
    # Per-space tables
    # ==================================================================

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

