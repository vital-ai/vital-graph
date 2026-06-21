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
    # Geo datatypes (OGC GeoSPARQL + VitalSigns)
    ('http://www.opengis.net/ont/geosparql#wktLiteral', 'wktLiteral'),
    ('http://vital.ai/ontology/vital-core#geoLocation', 'geoLocation'),
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
                password_hash VARCHAR(255),
                email VARCHAR(255),
                full_name VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                is_active BOOLEAN NOT NULL DEFAULT true,
                token_version INTEGER NOT NULL DEFAULT 0,
                tenant VARCHAR(255),
                created_time TIMESTAMPTZ DEFAULT now(),
                last_login TIMESTAMPTZ,
                update_time TIMESTAMP
            )
        '''),
        ("user_space_access", '''
            CREATE TABLE IF NOT EXISTS user_space_access (
                user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
                space_id VARCHAR(255) NOT NULL,
                access_level VARCHAR(2) NOT NULL CHECK (access_level IN ('rw', 'r')),
                granted_by VARCHAR(255),
                granted_time TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (user_id, space_id)
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
        ("space_analytics", '''
            CREATE TABLE IF NOT EXISTS space_analytics (
                id SERIAL PRIMARY KEY,
                space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
                computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                computation_time_ms INTEGER,
                analytics_json JSONB NOT NULL
            )
        '''),
        ("query_metrics", '''
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
        '''),
        ("slow_query_log", '''
            CREATE TABLE IF NOT EXISTS slow_query_log (
                id BIGSERIAL PRIMARY KEY,
                space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
                endpoint VARCHAR(100) NOT NULL,
                duration_ms INTEGER NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                metadata JSONB
            )
        '''),
        ("import_export_job", '''
            CREATE TABLE IF NOT EXISTS import_export_job (
                job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_type TEXT NOT NULL CHECK (job_type IN ('import', 'export')),
                space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
                graph_uri TEXT,
                status TEXT NOT NULL DEFAULT 'created'
                    CHECK (status IN ('created','pending','running','completed','failed','cancelled')),
                mode TEXT NOT NULL DEFAULT 'append'
                    CHECK (mode IN ('append', 'replace')),
                progress_pct REAL NOT NULL DEFAULT 0,
                records_done BIGINT NOT NULL DEFAULT 0,
                records_total BIGINT,
                file_s3_key TEXT,
                file_name TEXT,
                file_size BIGINT,
                file_format TEXT,
                config JSONB,
                checkpoint_offset BIGINT DEFAULT 0,
                checkpoint_batch INT DEFAULT 0,
                error_message TEXT,
                log_entries JSONB DEFAULT '[]'::jsonb,
                created_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        # Space analytics indexes
        "CREATE INDEX IF NOT EXISTS idx_space_analytics_space ON space_analytics(space_id)",
        "CREATE INDEX IF NOT EXISTS idx_space_analytics_latest ON space_analytics(space_id, computed_at DESC)",
        # Query metrics indexes
        "CREATE INDEX IF NOT EXISTS idx_query_metrics_time ON query_metrics(bucket_start DESC)",
        "CREATE INDEX IF NOT EXISTS idx_query_metrics_space_gran ON query_metrics(space_id, bucket_granularity, bucket_start DESC)",
        # Slow query log indexes
        "CREATE INDEX IF NOT EXISTS idx_slow_query_space_time ON slow_query_log(space_id, recorded_at DESC)",
        # Import/export job indexes
        "CREATE INDEX IF NOT EXISTS idx_iej_space_status ON import_export_job(space_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_iej_created ON import_export_job(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_iej_type_status ON import_export_job(job_type, status)",
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
        'import_export_job', 'slow_query_log', 'query_metrics', 'space_analytics', 'agent_change_log', 'agent_endpoint', 'agent', 'agent_type',
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
            'vector_index': f'{space_id}_vector_index',
            'geo': f'{space_id}_geo',
            'geo_config': f'{space_id}_geo_config',
            'fuzzy_mapping': f'{space_id}_fuzzy_mapping',
            'fuzzy_mapping_property': f'{space_id}_fuzzy_mapping_property',
            'fuzzy_band': f'{space_id}_fuzzy_band',
            'fuzzy_phonetic_band': f'{space_id}_fuzzy_phonetic_band',
            'search_mapping': f'{space_id}_search_mapping',
            'search_mapping_index': f'{space_id}_search_mapping_index',
            'search_mapping_property': f'{space_id}_search_mapping_property',
            'fts_index': f'{space_id}_fts_index',
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

        # 8. Vector index registry (per-space catalog of named vector indexes)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['vector_index']} (
                index_id        SERIAL PRIMARY KEY,
                index_name      VARCHAR(255) NOT NULL UNIQUE,
                dimensions      INT NOT NULL,
                distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',
                provider        VARCHAR(50) NOT NULL DEFAULT 'vitalsigns',
                model_name      VARCHAR(255),
                provider_config JSONB,
                description     TEXT,
                created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')


        # 10. Geo config (lightweight per-space config for geo population)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['geo_config']} (
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

        # 11. Geo side-table (PostGIS geography for spatial queries)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['geo']} (
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

        # 12. Fuzzy mapping (KG concept → fuzzy index association)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['fuzzy_mapping']} (
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

        # 12b. Fuzzy mapping properties (child: predicate URIs per mapping)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['fuzzy_mapping_property']} (
                property_id     SERIAL PRIMARY KEY,
                mapping_id      INTEGER NOT NULL,
                property_uri    VARCHAR(500) NOT NULL,
                property_role   VARCHAR(20) NOT NULL DEFAULT 'include',
                ordinal         INTEGER DEFAULT 0,
                UNIQUE (mapping_id, property_uri),
                FOREIGN KEY (mapping_id) REFERENCES {t['fuzzy_mapping']}(mapping_id) ON DELETE CASCADE
            )
        ''')

        # 13. Shared search mapping (used by both FTS and vector indexes)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['search_mapping']} (
                mapping_id          SERIAL PRIMARY KEY,
                mapping_type        VARCHAR(50) NOT NULL,
                type_uri            VARCHAR(500),
                index_name          VARCHAR(255) NOT NULL,
                enabled             BOOLEAN NOT NULL DEFAULT TRUE,
                source_type         VARCHAR(20) NOT NULL DEFAULT 'default',
                separator           VARCHAR(20) DEFAULT '. ',
                include_pred_name   BOOLEAN DEFAULT FALSE,
                created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 13b. Shared search mapping properties (child predicates)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['search_mapping_property']} (
                property_id     SERIAL PRIMARY KEY,
                mapping_id      INTEGER NOT NULL,
                property_uri    VARCHAR(500) NOT NULL,
                property_role   VARCHAR(20) NOT NULL DEFAULT 'include',
                ordinal         INTEGER DEFAULT 0,
                UNIQUE (mapping_id, property_uri),
                FOREIGN KEY (mapping_id) REFERENCES {t['search_mapping']}(mapping_id) ON DELETE CASCADE
            )
        ''')

        # 13c. Search mapping index junction table (links mappings to concrete indexes)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['search_mapping_index']} (
                id              SERIAL PRIMARY KEY,
                mapping_id      INTEGER NOT NULL,
                index_type      VARCHAR(10) NOT NULL CHECK (index_type IN ('vector', 'fts')),
                index_name      VARCHAR(255) NOT NULL,
                created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (mapping_id, index_type, index_name),
                FOREIGN KEY (mapping_id) REFERENCES {t['search_mapping']}(mapping_id) ON DELETE CASCADE
            )
        ''')

        # 14. FTS index registry (per-space catalog of named FTS indexes)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['fts_index']} (
                index_id        SERIAL PRIMARY KEY,
                index_name      VARCHAR(255) NOT NULL UNIQUE,
                languages       VARCHAR(64)[] NOT NULL DEFAULT '{{english}}',
                created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 15. Fuzzy band table (MinHash LSH primary bands)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['fuzzy_band']} (
                band_id     INTEGER NOT NULL,
                band_hash   BYTEA NOT NULL,
                entity_key  VARCHAR(500) NOT NULL
            )
        ''')

        # 16. Fuzzy phonetic band table (MinHash LSH phonetic bands)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['fuzzy_phonetic_band']} (
                band_id     INTEGER NOT NULL,
                band_hash   BYTEA NOT NULL,
                entity_key  VARCHAR(500) NOT NULL
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

            # Geo table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_gist ON {t['geo']} USING gist (location)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_subj ON {t['geo']} (subject_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_ctx ON {t['geo']} (context_uuid)",

            # Fuzzy band table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_band_lookup ON {t['fuzzy_band']} (band_id, band_hash)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_band_entity ON {t['fuzzy_band']} (entity_key)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_pband_lookup ON {t['fuzzy_phonetic_band']} (band_id, band_hash)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_pband_entity ON {t['fuzzy_phonetic_band']} (entity_key)",
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
            f"DROP TABLE IF EXISTS {t['geo']} CASCADE",
            f"DROP TABLE IF EXISTS {t['geo_config']} CASCADE",
            f"DROP TABLE IF EXISTS {t['vector_index']} CASCADE",
            f"DROP TABLE IF EXISTS {t['fuzzy_phonetic_band']} CASCADE",
            f"DROP TABLE IF EXISTS {t['fuzzy_band']} CASCADE",
            f"DROP TABLE IF EXISTS {t['fuzzy_mapping_property']} CASCADE",
            f"DROP TABLE IF EXISTS {t['fuzzy_mapping']} CASCADE",
            f"DROP TABLE IF EXISTS {t['fts_index']} CASCADE",
            f"DROP TABLE IF EXISTS {t['search_mapping_property']} CASCADE",
            f"DROP TABLE IF EXISTS {t['search_mapping']} CASCADE",
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
            f"DROP INDEX IF EXISTS idx_{space_id}_fuzzy_band_lookup",
            f"DROP INDEX IF EXISTS idx_{space_id}_fuzzy_band_entity",
            f"DROP INDEX IF EXISTS idx_{space_id}_fuzzy_pband_lookup",
            f"DROP INDEX IF EXISTS idx_{space_id}_fuzzy_pband_entity",
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

        # Bootstrap document_segments vector index + mapping (non-critical)
        try:
            from vitalgraph.document.vector_index_setup import (
                setup_document_segments_vectorization,
            )
            ok = await setup_document_segments_vectorization(conn, space_id)
            if ok:
                logger.info("Bootstrapped document_segments vector index for: %s", space_id)
            else:
                logger.warning("Could not bootstrap document_segments index for: %s", space_id)
        except Exception as ve:
            logger.warning(
                "document_segments vector bootstrap failed (non-critical): %s", ve
            )

        # NOTE: kgtype_default search infra is NOT bootstrapped per-space.
        # KG Types live in the centralized sp_kg_types system space only.

        # Bootstrap FTS indexes for any registered vector indexes (non-critical)
        try:
            from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index
            vi_table = f"{space_id}_vector_index"
            rows = await conn.fetch(
                f"SELECT index_name FROM {vi_table}"
            )
            for row in rows:
                await ensure_fts_index(conn, space_id, row['index_name'])
        except Exception as fe:
            logger.warning(
                "FTS index bootstrap failed (non-critical): %s", fe
            )

        logger.info("Created space tables for: %s", space_id)

    @staticmethod
    async def drop_space(conn, space_id: str) -> None:
        """Drop all per-space tables and views.

        In addition to the well-known tables, dynamically discovers and drops
        any ``_vec_*`` and ``_fts_*`` data tables that were created by
        vector/FTS index lifecycle operations.
        """
        # First drop dynamically-named data tables (_vec_*, _fts_*)
        # so foreign-key references don't block registry table drops.
        dynamic_rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' "
            "  AND (table_name LIKE $1 OR table_name LIKE $2)",
            f"{space_id}_vec_%",
            f"{space_id}_fts_%",
        )
        for row in dynamic_rows:
            tbl = row["table_name"]
            # Skip the registry tables (handled by drop_space_tables_sql)
            if tbl in (f"{space_id}_fts_index", f"{space_id}_fts_document_segments"):
                continue
            await conn.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
            logger.debug("Dropped dynamic table: %s", tbl)

        # Also drop any trigger functions left by FTS data tables
        fn_rows = await conn.fetch(
            "SELECT routine_name FROM information_schema.routines "
            "WHERE routine_schema = 'public' "
            "  AND routine_name LIKE $1",
            f"{space_id}_fts_%_tsv_trigger",
        )
        for row in fn_rows:
            await conn.execute(f"DROP FUNCTION IF EXISTS {row['routine_name']}() CASCADE")

        # Drop legacy vector_mapping tables (superseded by search_mapping)
        await conn.execute(f"DROP TABLE IF EXISTS {space_id}_vector_mapping_property CASCADE")
        await conn.execute(f"DROP TABLE IF EXISTS {space_id}_vector_mapping CASCADE")

        # Drop well-known tables
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

    # ==================================================================
    # Vector index data tables (created dynamically per registered index)
    # ==================================================================

    @staticmethod
    def vec_table_name(space_id: str, index_name: str) -> str:
        """Return the table name for a specific vector index."""
        return f"{space_id}_vec_{index_name}"

    def create_vector_data_table_sql(
        self, space_id: str, index_name: str, dimensions: int,
        distance_metric: str = "cosine",
    ) -> List[str]:
        """Return SQL to create a vector data table + indexes for a named index.

        Each registered vector index gets its own table with the correct
        dimension and appropriate HNSW index.
        """
        table = self.vec_table_name(space_id, index_name)

        # Map distance metric to pgvector ops class
        ops_map = {
            "cosine": "vector_cosine_ops",
            "l2": "vector_l2_ops",
            "inner_product": "vector_ip_ops",
        }
        ops_class = ops_map.get(distance_metric, "vector_cosine_ops")

        stmts = [
            f'''CREATE TABLE IF NOT EXISTS {table} (
                subject_uuid    UUID NOT NULL,
                context_uuid    UUID NOT NULL,
                embedding       vector({dimensions}) NOT NULL,
                updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (subject_uuid, context_uuid)
            )''',
            # HNSW index for ANN vector search
            f'''CREATE INDEX IF NOT EXISTS idx_{space_id}_vec_{index_name}_hnsw
                ON {table}
                USING hnsw (embedding {ops_class})
                WITH (m = 16, ef_construction = 200)''',
            # Context index for graph-scoped queries
            f'''CREATE INDEX IF NOT EXISTS idx_{space_id}_vec_{index_name}_ctx
                ON {table} (context_uuid)''',
            # Subject index for joins to rdf_quad
            f'''CREATE INDEX IF NOT EXISTS idx_{space_id}_vec_{index_name}_subj
                ON {table} (subject_uuid)''',
        ]
        return stmts

    def drop_vector_data_table_sql(self, space_id: str, index_name: str) -> List[str]:
        """Return SQL to drop a vector data table."""
        table = self.vec_table_name(space_id, index_name)
        return [f"DROP TABLE IF EXISTS {table} CASCADE"]

    # ==================================================================
    # FTS data tables (created dynamically per registered FTS index)
    # ==================================================================

    @staticmethod
    def fts_table_name(space_id: str, index_name: str) -> str:
        """Return the table name for a specific FTS index."""
        return f"{space_id}_fts_{index_name}"

    def create_fts_data_table_sql(
        self, space_id: str, index_name: str, languages: List[str],
    ) -> List[str]:
        """Return SQL to create an FTS data table, indexes, and trigger.

        The trigger automatically computes the ``tsv`` column by concatenating
        ``to_tsvector(lang, search_text)`` for each configured language.
        """
        table = self.fts_table_name(space_id, index_name)
        trigger_fn = f"{space_id}_fts_{index_name}_tsv_trigger"
        trigger_name = f"trg_{space_id}_fts_{index_name}_tsv"

        stmts = [
            # Data table
            f'''CREATE TABLE IF NOT EXISTS {table} (
                subject_uuid    UUID NOT NULL,
                context_uuid    UUID NOT NULL,
                search_text     TEXT,
                tsv             tsvector,
                updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (subject_uuid, context_uuid)
            )''',
            # GIN index for full-text search
            f'''CREATE INDEX IF NOT EXISTS idx_{space_id}_fts_{index_name}_tsv
                ON {table} USING gin (tsv)''',
            # Context index for graph-scoped queries
            f'''CREATE INDEX IF NOT EXISTS idx_{space_id}_fts_{index_name}_ctx
                ON {table} (context_uuid)''',
            # Subject index for joins
            f'''CREATE INDEX IF NOT EXISTS idx_{space_id}_fts_{index_name}_subj
                ON {table} (subject_uuid)''',
        ]

        # Trigger function: concatenate tsvectors from all languages
        tsv_expr = self._build_tsv_concat_expr(languages)
        stmts.append(f'''CREATE OR REPLACE FUNCTION {trigger_fn}() RETURNS trigger AS $$
BEGIN
    NEW.tsv := {tsv_expr};
    RETURN NEW;
END
$$ LANGUAGE plpgsql''')

        stmts.append(
            f'''DROP TRIGGER IF EXISTS {trigger_name} ON {table}'''
        )
        stmts.append(
            f'''CREATE TRIGGER {trigger_name}
                BEFORE INSERT OR UPDATE OF search_text ON {table}
                FOR EACH ROW EXECUTE FUNCTION {trigger_fn}()'''
        )

        return stmts

    def drop_fts_data_table_sql(self, space_id: str, index_name: str) -> List[str]:
        """Return SQL to drop an FTS data table and its trigger function."""
        table = self.fts_table_name(space_id, index_name)
        trigger_fn = f"{space_id}_fts_{index_name}_tsv_trigger"
        return [
            f"DROP TABLE IF EXISTS {table} CASCADE",
            f"DROP FUNCTION IF EXISTS {trigger_fn}() CASCADE",
        ]

    @staticmethod
    def _build_tsv_concat_expr(languages: List[str]) -> str:
        """Build a SQL expression that concatenates tsvectors for all languages.

        Example for ['english', 'spanish']:
            to_tsvector('english'::regconfig, COALESCE(NEW.search_text, ''))
         || to_tsvector('spanish'::regconfig, COALESCE(NEW.search_text, ''))
        """
        if not languages:
            languages = ["english"]
        parts = [
            f"to_tsvector('{lang}'::regconfig, COALESCE(NEW.search_text, ''))"
            for lang in languages
        ]
        return "\n         || ".join(parts)

    @staticmethod
    def build_tsv_batch_expr(languages: List[str], text_col: str = "search_text") -> str:
        """Build a SQL expression for batch tsvector computation (no NEW. prefix).

        Used by the FTS populator for batch UPDATE after bulk insert.
        Example: to_tsvector('english'::regconfig, COALESCE(search_text, ''))
              || to_tsvector('spanish'::regconfig, COALESCE(search_text, ''))
        """
        if not languages:
            languages = ["english"]
        parts = [
            f"to_tsvector('{lang}'::regconfig, COALESCE({text_col}, ''))"
            for lang in languages
        ]
        return " || ".join(parts)

