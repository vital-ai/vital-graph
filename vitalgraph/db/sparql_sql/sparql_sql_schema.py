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


def numeric_datatype_ids() -> str:
    """Comma-separated datatype_ids for the XSD numeric types, in emit order.

    Mirrors `EmitContext.dt_ids_for_uris(_NUMERIC_DATATYPES)`, which preserves
    the order of the URI list it is given. The order is not cosmetic: the id
    list becomes an array constant inside the indexed expression, so a
    differently-ordered list produces a different expression tree and the
    partial index below stops matching the push-down's predicate — silently.
    """
    from .emit_bgp import _NUMERIC_DATATYPES
    ids = {uri: i for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)}
    return ", ".join(str(ids[u]) for u in _NUMERIC_DATATYPES if u in ids)


NUMERIC_TERM_COLUMN = "num_val"
DATETIME_TERM_COLUMN = "dt_val"


def boolean_datatype_ids() -> str:
    """Comma-separated datatype_ids for xsd:boolean.

    Same positional derivation as `numeric_datatype_ids`. Unlike those, this
    backs no generated column: booleans need no typed column because their
    value set has exactly two members, so the equality set is expressible as a
    lexical IN over the canonical spellings — and the term table's hash index on
    `term_text` serves it with two probes.
    """
    ids = {uri: i for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)}
    return str(ids['http://www.w3.org/2001/XMLSchema#boolean'])



def datetime_datatype_ids() -> str:
    """Comma-separated datatype_ids for xsd:dateTime and xsd:date, in emit order.

    Mirrors ``EmitContext.dt_ids_for_uris(_DATETIME_DATATYPES)``. The order is
    part of the generated column's expression tree, so it must match the emit
    side exactly for the index to be usable.
    """
    from .emit_bgp import _DATETIME_DATATYPES
    ids = {uri: i for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)}
    return ", ".join(str(ids[u]) for u in _DATETIME_DATATYPES if u in ids)


def numeric_term_column() -> str:
    """The generated column that makes numeric range push-down estimable.

    A STORED generated column, deliberately, rather than an index on the
    equivalent expression. PostgreSQL does not consult statistics for an
    indexed *expression* when estimating this predicate: measured on a
    10.4M-term space the estimate was 3,489,209 rows against 99 actual —
    exactly 1/3 of the table, the hardcoded default for a comparison it cannot
    estimate. Raising the statistics target built an 88-bucket histogram that
    nothing read. This is not a partial-vs-full index issue; no expression
    index's statistics were used.

    An ordinary column gets ordinary statistics. Measured after the change:
    n_distinct -0.00012 (~1,256 distinct, correct), null_frac 0.9999
    (correct), estimate 160 against 99 actual. That accuracy is what lets the
    planner drive from the selective term leaf instead of hashing the whole
    entity population — 36,483 buffers/470ms became 7,802/57ms, and cost per
    matched row fell to 53.8 against an equality baseline of 52.0.

    Cost: one numeric column per term row, NULL for the ~96% that are not
    numeric literals. On an existing space `ALTER TABLE ... ADD COLUMN ...
    STORED` rewrites the table — 3m16s for 10.4M rows.
    """
    from .sql_type_generation import numeric_term_expr
    expr = numeric_term_expr(numeric_datatype_ids())
    return (f"{NUMERIC_TERM_COLUMN} NUMERIC "
            f"GENERATED ALWAYS AS ({expr}) STORED")


def datetime_term_column() -> str:
    """The generated column that makes datetime range push-down estimable.

    Same purpose as num_val, reached differently. A CAST cannot be used here —
    it is not immutable — so this leans on `vitalgraph_iso_to_utc`, which
    assembles the timestamp from parsed components and therefore is. See
    sparql_sql_admin._VITALGRAPH_ISO_TO_UTC_DDL.

    Being a generated column rather than one the write path maintains is the
    point: it cannot drift. The alternative was an ordinary column set on
    insert, which is the shape of every derived-data defect in this codebase
    (issues/041, 043, and an edge table that was 25% incomplete in production).

    Cost: one timestamp per term row, NULL for every term that is not a date
    literal. Adding it to an existing space rewrites the table, so it belongs
    in a migration.
    """
    from .sql_type_generation import datetime_term_expr
    expr = datetime_term_expr(datetime_datatype_ids())
    return (f"{DATETIME_TERM_COLUMN} TIMESTAMP "
            f"GENERATED ALWAYS AS ({expr}) STORED")


def numeric_term_index_sql(space_id: str, term_table: str) -> str:
    """Partial expression index for numeric range push-down (issues/040 W4).

    Without it the semi-join the push-down emits has to scan the term table by
    value. Measured on sp_lead_synth (1.05M terms, `MQLRating >= 99.9`, 16
    matches): 24,575 buffers before, 4,396 after, for a **48 kB** index.

    NOT partial, and that is deliberate — an earlier version was.

    PostgreSQL collects statistics for an indexed *expression* only from a
    NON-partial expression index. A partial one is 48 kB instead of 23 MB on a
    1.05M-term space, but leaves the planner with no idea what the expression
    selects: it estimated 350,288 rows against 99 actual. At that estimate a
    server with room to hash the imagined 350k rows chooses a hash semi-join
    over a full term-table scan and never touches the index — measured 183,388
    buffers, against 1,325 once the statistics existed, a 138x difference on
    identical data.

    The plan choice was therefore config-dependent: the same query used the
    index on a small-work_mem instance and ignored it on a larger one. An index
    exists to make the plan good, so paying 23 MB to make the planner reliably
    choose it is the right trade.

    This index is inert on its own. It only pays off in combination with the
    push-down (W2) that creates a value-ordered scan for it to serve; before
    that, the range predicate was applied above the join and never touched the
    term table by value at all.
    """
    from .sql_type_generation import numeric_term_expr
    expr = numeric_term_expr(numeric_datatype_ids())
    return (f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_num "
            f"ON {term_table} (({expr}))")


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
                active BOOLEAN,
                vitalgraph_version VARCHAR(64),
                git_commit VARCHAR(40),
                deployed_datetime TIMESTAMP
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
                protocol_config JSONB DEFAULT '{}',
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
                transport_config JSONB DEFAULT '{}',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                UNIQUE (agent_id, endpoint_uri)
            )
        '''),
        ("agent_function", '''
            CREATE TABLE IF NOT EXISTS agent_function (
                function_id SERIAL PRIMARY KEY,
                agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
                function_uri VARCHAR(500) NOT NULL,
                function_name VARCHAR(255) NOT NULL,
                description TEXT,
                parameters JSONB DEFAULT '{}',
                output_schema JSONB DEFAULT '{}',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
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
        ("backfill_state", '''
            CREATE TABLE IF NOT EXISTS backfill_state (
                space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
                graph_uri TEXT NOT NULL,
                completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                quad_inserts BIGINT,
                stats_reset TIMESTAMPTZ,
                PRIMARY KEY (space_id, graph_uri)
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
            'rdf_value_stats': f'{space_id}_rdf_value_stats',
            'edge': f'{space_id}_edge',
            'edge_fanout': f'{space_id}_edge_fanout',
            'entity_fanout': f'{space_id}_entity_fanout',
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
            'segmentation_jobs': f'{space_id}_segmentation_jobs',
            'document_segmentation_config': f'{space_id}_document_segmentation_config',
        }

    # ------------------------------------------------------------------
    # Per-space DDL generators
    # ------------------------------------------------------------------

    @staticmethod
    def _partition_children(table_fqn: str, n: int) -> List[str]:
        """CREATE TABLE ... PARTITION OF statements for n HASH partitions."""
        base = table_fqn.split(".")[-1]
        return [
            f"CREATE TABLE IF NOT EXISTS {base}_p{i} PARTITION OF {table_fqn} "
            f"FOR VALUES WITH (MODULUS {n}, REMAINDER {i})"
            for i in range(n)
        ]

    def create_space_tables_sql(self, space_id: str,
                                partition_quads: int = 0) -> List[str]:
        """Return SQL statements to create all per-space tables.

        ``partition_quads`` > 0 builds a HASH(context_uuid)-partitioned rdf_quad
        with that many partitions, a slim 4-col PK, and a UUIDv7 quad_uuid
        default (requires PostgreSQL 18). 0 = the classic non-partitioned table.
        """
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
                dataset      VARCHAR(50) NOT NULL DEFAULT 'primary',
                {numeric_term_column()},
                {datetime_term_column()}
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
        if partition_quads > 0:
            # Partitioned variant (P3): HASH(context_uuid) so graph-scoped
            # queries prune to one partition; slim 4-col PK (context_uuid is the
            # partition key, so it MUST be in the PK) which also gives true
            # (s,p,o,c) dedup; quad_uuid becomes a non-key UUIDv7 identity column
            # (PG18) for insert locality.
            stmts.append(f'''
                CREATE TABLE IF NOT EXISTS {t['rdf_quad']} (
                    subject_uuid   UUID NOT NULL,
                    predicate_uuid UUID NOT NULL,
                    object_uuid    UUID NOT NULL,
                    context_uuid   UUID NOT NULL,
                    quad_uuid      UUID NOT NULL DEFAULT uuidv7(),
                    dataset        VARCHAR(50) NOT NULL DEFAULT 'primary',
                    PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                ) PARTITION BY HASH (context_uuid)
            ''')
            stmts += self._partition_children(t['rdf_quad'], partition_quads)
        else:
            # Slim 4-col PK, matching the partitioned variant above. An RDF
            # graph is a SET of triples: SPARQL 1.1 Update says a triple "MAY be
            # considered to be processed with no action if that triple already
            # exists in the graph", so (s,p,o,c) is unique BY THE DATA MODEL and
            # the key should say so.
            #
            # It used to include quad_uuid, which defaults to a random UUID — so
            # an identical quad got a fresh key and never conflicted, and every
            # `ON CONFLICT DO NOTHING` on this table was a no-op. Verified by
            # re-inserting an existing quad: INSERT 0 1, row count 1 -> 2. Found
            # 1,323 duplicate quads across 6 spaces that way, one of them in a
            # 5.1M-quad space.
            #
            # quad_uuid stays as a non-key identity column, as in the
            # partitioned branch.
            stmts.append(f'''
                CREATE TABLE IF NOT EXISTS {t['rdf_quad']} (
                    subject_uuid   UUID NOT NULL,
                    predicate_uuid UUID NOT NULL,
                    object_uuid    UUID NOT NULL,
                    context_uuid   UUID NOT NULL,
                    quad_uuid      UUID NOT NULL DEFAULT gen_random_uuid(),
                    dataset        VARCHAR(50) NOT NULL DEFAULT 'primary',
                    PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                )
            ''')

        # 4. Predicate statistics (used by generator for join reordering)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['rdf_pred_stats']} (
                predicate_uuid UUID PRIMARY KEY,
                row_count      BIGINT NOT NULL DEFAULT 0,
                -- TRUE once prune_stats_tables has removed any (predicate,
                -- object) row for this predicate.
                --
                -- It makes ABSENCE from rdf_stats mean something. Without it,
                -- absence is ambiguous between "this pair has no quads" and
                -- "this pair was pruned", and the incremental sync resolves the
                -- ambiguity the wrong way: it upserts `row_count = row_count +
                -- delta`, so a pruned pair reappears holding ONLY its
                -- post-prune delta. Measured at 100,000 -> 1 after a single
                -- write (issues/062), and it looks authoritative.
                --
                -- Per PREDICATE rather than per pair, so it costs one boolean
                -- on a table with one row per distinct predicate — about 21
                -- rows in a real space — instead of tracking tombstones for
                -- the pairs pruning exists to remove.
                pruned         BOOLEAN NOT NULL DEFAULT FALSE
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

        # 5b. Value quantiles, for RANGE selectivity on high-cardinality values.
        #
        # rdf_stats is a frequent-value list capped per predicate, so it answers
        # equality on a small value set exactly and a range over a large one not
        # at all. Measured coverage: score 100/100 distinct objects and category
        # 8/8, against occurred 196/68,502 and weight 2,000/64,525 — so
        # `occurred >= X` estimated 244 where the answer was 53,455.
        #
        # This is an EQUI-DEPTH histogram: bucket i holds the same number of
        # rows as every other, so only the boundaries need storing and the
        # selectivity of a range is (buckets above the value) / (buckets), with
        # interpolation inside the straddled bucket. Bounded by construction —
        # a few hundred rows per space, not one row per distinct value.
        stmts.append(f"""
            CREATE TABLE IF NOT EXISTS {t['rdf_value_stats']} (
                predicate_uuid UUID    NOT NULL,
                lane           TEXT    NOT NULL,
                bucket         INT     NOT NULL,
                lower_num      DOUBLE PRECISION,
                lower_dt       TIMESTAMP,
                total_rows     BIGINT  NOT NULL DEFAULT 0,
                -- The predicate's rdf_pred_stats count AS OF this build. The
                -- freshness reference, and deliberately NOT total_rows:
                -- total_rows counts quads with a value in THIS LANE, pred_stats
                -- counts every quad for the predicate, and the two diverge
                -- permanently on a mixed-type predicate — which would read as
                -- permanently stale. Comparing like with like means storing the
                -- pred_stats value here.
                --
                -- NULL means "built before this column existed": unknown, so no
                -- scaling and no staleness verdict, which is the behaviour
                -- before this existed.
                pred_rows      BIGINT,
                updated_time   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (predicate_uuid, lane, bucket)
            )
        """)

        # 6. Edge table (maintained by app-level sync; replaces edge MV).
        # Co-partitioned by HASH(context_uuid) with rdf_quad so edge-rewrite
        # joins are partition-wise; context_uuid is already in the PK.
        _part = " PARTITION BY HASH (context_uuid)" if partition_quads > 0 else ""
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['edge']} (
                edge_uuid        UUID NOT NULL,
                source_node_uuid UUID NOT NULL,
                dest_node_uuid   UUID NOT NULL,
                context_uuid     UUID NOT NULL,
                -- The edge node's vitaltype. Without it, telling
                -- Edge_hasKGSlot from Edge_hasEntityKGFrame needs a join back
                -- to rdf_quad on edge_uuid, which hands back the join
                -- reduction this table exists to provide. Measured on a
                -- three-hop traversal: 700ms untyped, 22s typed via quad
                -- joins (issues/060).
                --
                -- NULLABLE on purpose. An edge with hasEdgeSource and
                -- hasEdgeDestination but no vitaltype triple is still an edge,
                -- and populating this with an inner join would silently drop
                -- it — changing which rows the table describes rather than
                -- only how fast it answers.
                edge_type_uuid   UUID,
                PRIMARY KEY (edge_uuid, context_uuid)
            ){_part}''')
        if partition_quads > 0:
            stmts += self._partition_children(t['edge'], partition_quads)


        # 6b. Edge fan-out: how many rows one traversal step produces, per edge
        # kind and per direction.
        #
        # The metric no existing statistic expresses. rdf_stats and PostgreSQL's
        # stat_*_quad_po both describe single-table selectivity; the errors that
        # matter here are JOIN cardinality -- measured at 305x and 4,761x
        # underestimates on multi-hop traversals (issues/059). Fan-out is what
        # multiplies through those hops, and PostgreSQL cannot infer it from
        # column statistics.
        #
        # Keyed by relation type as well as edge type, because pooling loses the
        # answer. Measured on sp_kg_rel, all four Edge_hasKGRelation:
        #
        #     reportsTo  forward 1.00/1     backward 4.77/5      a tree
        #     worksFor   forward 1.00/1     backward 39.00/886   a hub
        #
        # Per edge type those average to something describing neither, and per
        # space (1.80/1.51) hides both.
        #
        # p99 and max are stored, not just avg, because the distribution is
        # skewed enough that a mean is unusable: wordnet's slot-value in-degree
        # averages 5.20 with a maximum of 1,342, so a plan chosen on the mean can
        # be 250x off.
        #
        # Bounded by (edge types x relation types x 2), so tens of rows.
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['edge_fanout']} (
                edge_type_uuid     UUID NOT NULL,
                -- The all-zero uuid means "not a relation", because a NULL
                -- cannot participate in a primary key and a containment edge
                -- genuinely has no relation type. A sentinel keeps ON CONFLICT
                -- simple; the alternative is a unique index over COALESCE and
                -- an inference clause that has to match it exactly.
                relation_type_uuid UUID NOT NULL
                    DEFAULT '00000000-0000-0000-0000-000000000000'::uuid,
                direction          TEXT NOT NULL CHECK (direction IN ('forward','backward')),
                avg_fanout         DOUBLE PRECISION NOT NULL DEFAULT 0,
                p99_fanout         BIGINT NOT NULL DEFAULT 0,
                max_fanout         BIGINT NOT NULL DEFAULT 0,
                sample_nodes       BIGINT NOT NULL DEFAULT 0,
                updated_time       TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (edge_type_uuid, relation_type_uuid, direction)
            )''')

        # 8b. Entity fan-out — the HUB LIST.
        #
        # How wide a traversal gets from one entity, which `edge_fanout` cannot
        # say: that is keyed on (edge type, relation type, direction) and is an
        # aggregate over the whole space, built to choose a traversal DIRECTION.
        # Every traversal question that stays open comes back to "how wide does
        # the walk get from THIS entity" — see traversal_chain_plan.md GAP 7b.
        #
        # A LIST of hubs rather than a row per entity, because the distribution
        # is scale-free and only the tail costs anything: measured on
        # wordnet_frames, 80 entities of 109,734 have an out-degree >= 100
        # (0.073%) against a mean of 2.60 and a p99 of 20. Storing the top N
        # captures the whole cost profile in hundreds of rows instead of
        # millions, and an entity absent from the list is by construction not a
        # hub.
        #
        # Both directions, because a traversal can be pinned at either end.
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['entity_fanout']} (
                entity_uuid   UUID NOT NULL,
                context_uuid  UUID NOT NULL,
                direction     TEXT NOT NULL,        -- 'forward' | 'backward'
                fanout        BIGINT NOT NULL,      -- DISTINCT neighbours, one hop
                updated_time  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (entity_uuid, context_uuid, direction)
            )''')

        # 7. Frame-entity table (maintained by app-level sync; replaces frame_entity MV)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['frame_entity']} (
                frame_uuid           UUID NOT NULL,
                source_entity_uuid   UUID,
                dest_entity_uuid     UUID,
                context_uuid         UUID NOT NULL,
                -- The frame's rdf:type / vitaltype, denormalised for the same
                -- reason as `edge.edge_type_uuid` (issues/060): without it a
                -- typed hop joins back to rdf_quad per row, handing back the
                -- join reduction this table exists to provide. Measured on
                -- wordnet_frames depth 3, the type probe was 79% of all buffers
                -- (2,006,247 of 2,543,685) and the walk went 53 ms -> 9 ms once
                -- it became a column predicate.
                --
                -- NULLABLE on purpose, matching edge: a frame reachable through
                -- its slots but carrying no type triple is still a frame, and
                -- populating this with an inner join would silently drop it —
                -- changing which rows the table describes rather than only how
                -- fast it answers.
                frame_type_uuid      UUID,
                PRIMARY KEY (frame_uuid, context_uuid)
            ){_part}''')
        if partition_quads > 0:
            stmts += self._partition_children(t['frame_entity'], partition_quads)

        # 8. Vector index registry (per-space catalog of named vector indexes)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['vector_index']} (
                index_id        SERIAL PRIMARY KEY,
                index_name      VARCHAR(255) NOT NULL UNIQUE,
                dimensions      INT NOT NULL,
                distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',
                provider        VARCHAR(50) NOT NULL DEFAULT 'vitalsigns_onnx',
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
                -- Recognition lists, matched against predicates already in the
                -- data. W3C Basic Geo (wgs84_pos) first: it is the standard
                -- vocabulary for point coordinates and what most third-party
                -- RDF uses. The namespace is http://, not https:// — the https
                -- URL serves the document, the http one appears in the data.
                -- Keep in step with DEFAULT_LAT_PREDICATES in geo_config_manager.
                lat_predicates  TEXT[] NOT NULL DEFAULT ARRAY[
                    'http://www.w3.org/2003/01/geo/wgs84_pos#lat',
                    'http://vital.ai/ontology/vital-aimp#hasLatitude'
                ],
                lon_predicates  TEXT[] NOT NULL DEFAULT ARRAY[
                    'http://www.w3.org/2003/01/geo/wgs84_pos#long',
                    'http://vital.ai/ontology/vital-aimp#hasLongitude'
                ],
                updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 11. Geo side-table (PostGIS geography for spatial queries)
        #     Uses serial PK to allow multiple rows per subject_uuid
        #     (entity with N geo slots → N entity-keyed rows + N slot-keyed rows)
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['geo']} (
                geo_id          SERIAL PRIMARY KEY,
                subject_uuid    UUID NOT NULL,
                source_slot_uuid UUID,
                predicate_uuid  UUID,
                location        geography(Point, 4326) NOT NULL,
                latitude        DOUBLE PRECISION NOT NULL,
                longitude       DOUBLE PRECISION NOT NULL,
                context_uuid    UUID NOT NULL,
                updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (subject_uuid, source_slot_uuid, context_uuid)
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

        # 17. Document segmentation job queue.
        # 18. Document segmentation config.
        #
        # These two were created ON DEMAND by SegmentationJobManager and
        # SegmentationConfigManager at first use, so a space's schema depended on
        # which features had been exercised against it. That is the thing this
        # DDL is supposed to be the single answer to, and it cost twice: the
        # drop path had to grow a self-healing sweep because "on-demand tables
        # keep being added without anyone updating it", and one of the two was
        # missed there anyway and leaked an orphan table per space ever created
        # (116 on one local stack).
        #
        # Neither holds a denormalisation of rdf_quad and no query reads them,
        # so they are outside the derived-table contract
        # (planning_sql/derived_table_maintenance.md). They are here on the
        # simpler rule: every space gets the same schema at creation, and schema
        # is never a side effect of a data path.
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['segmentation_jobs']} (
                job_id             SERIAL PRIMARY KEY,
                space_id           VARCHAR(200) NOT NULL,
                graph_id           TEXT NOT NULL,
                document_uri       TEXT NOT NULL,
                status             VARCHAR(20) NOT NULL DEFAULT 'pending',
                attempt_count      INTEGER NOT NULL DEFAULT 0,
                segment_count      INTEGER,
                segment_method_uri VARCHAR(500),
                max_segment_tokens INTEGER,
                error_message      TEXT,
                content_hash       VARCHAR(64),
                created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        ''')
        stmts.append(f'''
            CREATE TABLE IF NOT EXISTS {t['document_segmentation_config']} (
                config_id          SERIAL PRIMARY KEY,
                document_type_uri  VARCHAR(500) NOT NULL,
                segment_method_uri VARCHAR(500) NOT NULL,
                max_segment_tokens INTEGER NOT NULL DEFAULT 512,
                min_segment_tokens INTEGER NOT NULL DEFAULT 50,
                overlap_tokens     INTEGER NOT NULL DEFAULT 0,
                enabled            BOOLEAN NOT NULL DEFAULT TRUE,
                auto_vectorize     BOOLEAN NOT NULL DEFAULT TRUE,
                created_time       TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (document_type_uri, segment_method_uri)
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
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_tt ON {t['term']} USING hash (term_text)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_type ON {t['term']} (term_type)",
            # GIN trigram index for REGEX/CONTAINS/LIKE text filters (requires pg_trgm)
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_trgm ON {t['term']} USING gin (term_text gin_trgm_ops)",
            # Numeric range push-down support (issues/040 W2/W4). A plain
            # index on the generated column, NOT an expression index — see
            # numeric_term_column for why that distinction decides everything.
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_num "
            f"ON {t['term']} ({NUMERIC_TERM_COLUMN})",
            # Same rationale as idx_*_term_num: without it the datetime
            # push-down's semi-join scans the term table by value.
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_dt "
            f"ON {t['term']} ({DATETIME_TERM_COLUMN})",

            # Quad table indexes — essential for V2 SQL generation
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_pred ON {t['rdf_quad']} (predicate_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_subj ON {t['rdf_quad']} (subject_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_obj ON {t['rdf_quad']} (object_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_ctx ON {t['rdf_quad']} (context_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_po ON {t['rdf_quad']} (predicate_uuid, object_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_ps ON {t['rdf_quad']} (predicate_uuid, subject_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_sp ON {t['rdf_quad']} (subject_uuid, predicate_uuid)",
            # Graph-scoped COVERING index (Tier 1 — billion_scale_strategy.md §5/§14).
            # Serves graph-scoped predicate scans (WHERE context=? AND predicate=?)
            # index-only — no heap. Measured ~3x fewer buffers vs the pre-existing
            # predicate index on 100K rows (Index-Only 984 vs Index Scan 2938),
            # and the page-count advantage grows cold/at scale (each page = a
            # potential random heap read into a ~120GB heap at 1B).
            #
            # NOTE: a (context_uuid, subject_uuid) covering index was evaluated and
            # dropped as redundant — the 5-column PK (subject, predicate, object,
            # context, quad_uuid) already serves subject-scoped-within-graph
            # lookups index-only (measured identical: 4 buffers, 0 heap fetches).
            # object_uuid is a KEY column, not INCLUDE payload. In INCLUDE it can
            # only ever be a filter, so a graph+predicate+object query — every
            # typed-entity listing, every slot-value filter — scanned the whole
            # (context, predicate) range and discarded almost all of it. Measured
            # on wordnet_frames (8.58M quads), 25-row page: 14,876 buffers /592ms
            # as a filter vs 5 buffers /0.21ms as an index condition, ~1,850x.
            #
            # Not a cardinality problem — the row estimate was already accurate
            # (111,113 est vs 109,745 actual), so extended statistics do not help
            # (tried). It is the LIMIT cost model assuming matching rows are
            # spread uniformly through the index range when they are clustered.
            #
            # Keeping subject_uuid in INCLUDE preserves the covering property:
            # the object-unbound graph-scoped scan is unchanged — Index Only
            # Scan, 0 heap fetches, identical buffers. Index size +0.24%.
            # See issues/039.
            #
            # It was briefly promoted to a trailing KEY column, to give the
            # paging LIMIT of issues/047 an ordered scan to stop on. Reverted:
            # it made wordnet multi-hop frame traversal ~2x slower —
            # frame_union 66ms -> 135ms, relationships 38ms -> 71ms — and the
            # 047 fence (SET LOCAL enable_sort = off) turns out not to need it,
            # holding at every page size on both anchors with this form. The
            # ordering it wanted is available from the primary key.
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_quad_ctx_pred ON {t['rdf_quad']} (context_uuid, predicate_uuid, object_uuid) INCLUDE (subject_uuid)",

            # Stats: support the capped stats load (ORDER BY row_count LIMIT).
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_rdf_stats_rc ON {t['rdf_stats']} (row_count)",

            # Planner statistics (Tier 0 — high_cardinality_slot_value_query_plan.md).
            # predicate_uuid and object_uuid are strongly correlated for slot-value
            # triples (a value only ever appears as the object of one predicate), but
            # Postgres assumes independence and multiplies selectivities -> ~380x
            # UNDER-estimate of the driving rows -> it seeds an 8-way join at that leaf
            # and picks all nested loops -> 60s timeouts. Extended (mcv, ndistinct)
            # stats at a raised target teach it the correlation -> correct estimate ->
            # hash joins. Stats-only, non-destructive; takes effect on ANALYZE.
            f"CREATE STATISTICS IF NOT EXISTS stat_{space_id}_quad_po (mcv, ndistinct) "
            f"ON predicate_uuid, object_uuid FROM {t['rdf_quad']}",
            f"ALTER STATISTICS stat_{space_id}_quad_po SET STATISTICS 1000",
            # Per-column targets for the heavily-skewed UUID columns (mitigation §5).
            f"ALTER TABLE {t['rdf_quad']} "
            f"ALTER COLUMN predicate_uuid SET STATISTICS 1000, "
            f"ALTER COLUMN subject_uuid SET STATISTICS 1000, "
            f"ALTER COLUMN context_uuid SET STATISTICS 500, "
            f"ALTER COLUMN object_uuid SET STATISTICS 500",
            # num_val and dt_val are EXTREMELY sparse, and that breaks range
            # estimation at scale in a way that inverts with table size.
            #
            # Terms are deduplicated, so 100,000 entities sharing ~1,000 distinct
            # one-decimal ratings produce ~1,000 non-NULL num_val rows in a 10.4M
            # row term table — null_frac 0.99993. The default target samples
            # ~30,000 rows and therefore catches about TWO non-NULL values, which
            # is not a histogram. `num_val <= 65.0` then estimates rows=1 against
            # 809 actual, the planner drives a nested loop from that leaf, and a
            # 25-row page times out at 60s. The same index at 10k has 46 buckets,
            # estimates correctly, and makes the same query 4x FASTER — so the
            # index looked validated at the only scale where it works
            # (issues/056).
            #
            # A high target is cheap here precisely because the column is sparse:
            # ANALYZE on 10.4M rows took 8.3s and produced 356 buckets, which
            # turned two timeouts into 61ms and 229ms.
            f"ALTER TABLE {t['term']} "
            f"ALTER COLUMN {NUMERIC_TERM_COLUMN} SET STATISTICS 10000, "
            f"ALTER COLUMN {DATETIME_TERM_COLUMN} SET STATISTICS 10000",

            # Datatype lookup index
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_datatype_uri ON {t['datatype']} (datatype_uri)",

            # Edge table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_src_dst ON {t['edge']} (source_node_uuid, dest_node_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_dst_src ON {t['edge']} (dest_node_uuid, source_node_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_edge ON {t['edge']} (edge_uuid)",
            # Typed traversal in each direction. A hop is normally "these
            # destinations, of this edge type", so the type leads and the
            # endpoint follows; without these the type predicate is a filter
            # applied after the endpoint lookup rather than part of the seek.
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_type_dst "
            f"ON {t['edge']} (edge_type_uuid, dest_node_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_type_src "
            f"ON {t['edge']} (edge_type_uuid, source_node_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_edge_ctx ON {t['edge']} (context_uuid)",

            # Frame-entity table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_src_frame ON {t['frame_entity']} (source_entity_uuid, frame_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_dst_frame ON {t['frame_entity']} (dest_entity_uuid, frame_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_frame ON {t['frame_entity']} (frame_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_ctx ON {t['frame_entity']} (context_uuid)",
            # Type-leading, mirroring idx_*_edge_type_src/_dst. A typed
            # traversal filters on the type and then walks by source or dest,
            # so the type has to lead for the scan to start there.
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_type_src ON {t['frame_entity']} (frame_type_uuid, source_entity_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_type_dst ON {t['frame_entity']} (frame_type_uuid, dest_entity_uuid)",
            # Document segmentation job queue and config. These indexes lived in
            # SegmentationJobManager / SegmentationConfigManager and were created
            # on demand with their tables, so a space had them only if the
            # feature had run against it. Schema comes from one place now.
            f"CREATE INDEX IF NOT EXISTS {t['segmentation_jobs']}_status_idx "
            f"ON {t['segmentation_jobs']} (status, created_at) "
            f"WHERE status IN ('pending', 'failed', 'vectorizing')",
            f"CREATE INDEX IF NOT EXISTS {t['segmentation_jobs']}_document_idx "
            f"ON {t['segmentation_jobs']} (document_uri, created_at DESC)",
            f"CREATE INDEX IF NOT EXISTS {t['segmentation_jobs']}_space_idx "
            f"ON {t['segmentation_jobs']} (space_id, status)",
            f"CREATE INDEX IF NOT EXISTS "
            f"{t['document_segmentation_config']}_doc_type_idx "
            f"ON {t['document_segmentation_config']} (document_type_uri) "
            f"WHERE enabled = TRUE",

            # Geo table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_gist ON {t['geo']} USING gist (location)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_subj ON {t['geo']} (subject_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_slot ON {t['geo']} (source_slot_uuid)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_ctx ON {t['geo']} (context_uuid)",

            # Fuzzy band table indexes
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_band_lookup ON {t['fuzzy_band']} (band_id, band_hash)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_band_entity ON {t['fuzzy_band']} (entity_key)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_pband_lookup ON {t['fuzzy_phonetic_band']} (band_id, band_hash)",
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fuzzy_pband_entity ON {t['fuzzy_phonetic_band']} (entity_key)",

            # "who are the hubs, widest first" — the only query this table has.
            f"CREATE INDEX IF NOT EXISTS idx_{space_id}_entity_fanout_top ON {t['entity_fanout']} (direction, fanout DESC)",
        ]

    def drop_space_tables_sql(self, space_id: str) -> List[str]:
        """Return SQL statements to drop all per-space tables/views."""
        t = self.get_table_names(space_id)
        return [
            f"DROP TABLE IF EXISTS {t['frame_entity']} CASCADE",
            f"DROP TABLE IF EXISTS {t['edge']} CASCADE",
            f"DROP TABLE IF EXISTS {t['rdf_stats']} CASCADE",
            f"DROP TABLE IF EXISTS {t['rdf_pred_stats']} CASCADE",
            # Added later than the rest and missed here, so every drop_space
            # logged them as orphans and relied on the fallback sweep.
            f"DROP TABLE IF EXISTS {t['rdf_value_stats']} CASCADE",
            f"DROP TABLE IF EXISTS {t['edge_fanout']} CASCADE",
            f"DROP TABLE IF EXISTS {t['entity_fanout']} CASCADE",
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
            f"DROP TABLE IF EXISTS {t['search_mapping_index']} CASCADE",
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
            f"DROP INDEX IF EXISTS idx_{space_id}_term_num",
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
    async def create_space(conn, space_id: str, partition_quads: int = 0,
                           strict: bool = True) -> None:
        """Create all per-space tables, indexes, and seed datatypes.

        ``partition_quads`` > 0 creates a HASH(context_uuid)-partitioned rdf_quad
        (slim 4-col PK + UUIDv7, PG18) — see create_space_tables_sql.

        Space creation is all-or-nothing: with ``strict`` (the default) a failure
        in any step — including the vector/FTS bootstraps — propagates, so a
        caller running this inside a transaction gets a complete space or none
        at all. Pass ``strict=False`` only to tolerate bootstrap failures and
        leave a space without its vector/FTS infrastructure.
        """
        await SparqlSQLSchema.create_space_core(conn, space_id, partition_quads)
        await SparqlSQLSchema.bootstrap_space_extras(conn, space_id, strict=strict)
        logger.info("Created space tables for: %s", space_id)

    @staticmethod
    async def create_space_core(conn, space_id: str, partition_quads: int = 0) -> None:
        """Create per-space tables, indexes and seed datatypes.

        Contains only the critical DDL, so it is safe to run inside an explicit
        transaction — every statement here raises on failure rather than being
        swallowed.
        """
        schema = SparqlSQLSchema()

        for stmt in schema.create_space_tables_sql(space_id, partition_quads):
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

    @staticmethod
    async def bootstrap_space_extras(conn, space_id: str,
                                     strict: bool = True) -> None:
        """Bootstrap the per-space vector/FTS infrastructure.

        With ``strict`` (the default) any failure propagates, so a caller
        running this inside a transaction gets all-or-nothing space creation.
        ``strict=False`` restores the older tolerant behaviour, which logs and
        continues — only safe outside a transaction, since a swallowed error
        would otherwise leave the enclosing transaction in an aborted state.
        """
        # Bootstrap document_segments vector index + mapping
        try:
            from vitalgraph.document.vector_index_setup import (
                setup_document_segments_vectorization,
            )
            ok = await setup_document_segments_vectorization(conn, space_id)
            if ok:
                logger.info("Bootstrapped document_segments vector index for: %s", space_id)
            elif strict:
                raise RuntimeError(
                    f"document_segments vector bootstrap returned failure for {space_id}"
                )
            else:
                logger.warning("Could not bootstrap document_segments index for: %s", space_id)
        except Exception as ve:
            if strict:
                raise
            logger.warning(
                "document_segments vector bootstrap failed (non-critical): %s", ve
            )

        # NOTE: kgtype_default search infra is NOT bootstrapped per-space.
        # KG Types live in the centralized sp_kg_types system space only.

        # Bootstrap FTS indexes for any registered vector indexes
        try:
            from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index
            vi_table = f"{space_id}_vector_index"
            rows = await conn.fetch(
                f"SELECT index_name FROM {vi_table}"
            )
            for row in rows:
                await ensure_fts_index(conn, space_id, row['index_name'])
        except Exception as fe:
            if strict:
                raise
            logger.warning(
                "FTS index bootstrap failed (non-critical): %s", fe
            )

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
            # Skip the registry table (handled by drop_space_tables_sql)
            if tbl == f"{space_id}_fts_index":
                continue
            await conn.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
            logger.debug("Dropped dynamic table: %s", tbl)

        # segmentation_jobs is created on demand by SegmentationJobManager
        # (not by create_space_tables_sql), so it is not in the static drop
        # list and would otherwise be left behind on every drop.
        await conn.execute(
            f"DROP TABLE IF EXISTS {space_id}_segmentation_jobs CASCADE"
        )

        # Same for document_segmentation_config, created on demand by
        # SegmentationConfigManager (segmentation_config_manager.py:85). It was
        # missed here, so every space ever created left one behind: a local test
        # stack had 116 orphans (7.4 MB) belonging to spaces long deleted.
        await conn.execute(
            f"DROP TABLE IF EXISTS {space_id}_document_segmentation_config CASCADE"
        )

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

        # Final sweep: anything still named for this space.
        #
        # Everything above is a hand-maintained list, and on-demand tables keep
        # being added without anyone updating it — segmentation_jobs was caught
        # once, document_segmentation_config was missed and leaked one table per
        # space ever created (116 orphans on one local stack). This makes the
        # drop self-healing: a new on-demand table is removed automatically, and
        # the warning names it so the explicit list can be updated.
        all_tables = [
            r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        ]
        other_space_ids = [
            r["space_id"] for r in await conn.fetch("SELECT space_id FROM space")
            if r["space_id"] != space_id
        ]
        leftovers = SparqlSQLSchema.orphan_tables_for_space(
            all_tables, space_id, other_space_ids,
        )
        if leftovers:
            logger.warning(
                "drop_space(%s): %d table(s) not in the explicit drop list — "
                "dropping and worth adding there: %s",
                space_id, len(leftovers), ", ".join(sorted(leftovers)),
            )
            for tbl in leftovers:
                await conn.execute(f'DROP TABLE IF EXISTS "{tbl}" CASCADE')

        logger.info("Dropped space tables for: %s", space_id)

    @staticmethod
    def orphan_tables_for_space(
        all_tables: List[str], space_id: str, other_space_ids: List[str],
    ) -> List[str]:
        """
        Tables named for ``space_id`` that survived the explicit drops.

        Prefix matching is done in Python rather than SQL ``LIKE`` on purpose:
        ``_`` is a LIKE wildcard, so ``LIKE 'my_space_%'`` also matches
        ``myXspace_...``. More importantly, one space id can be a prefix of
        another — dropping ``e2e_test`` must never take ``e2e_test_extra``'s
        tables with it — so any table belonging to a longer space id is excluded.
        """
        prefix = f"{space_id}_"
        # Space ids that would themselves match our prefix, longest first.
        shadowing = sorted(
            (sid for sid in other_space_ids if sid.startswith(prefix)),
            key=len, reverse=True,
        )
        out = []
        for tbl in all_tables:
            if not tbl.startswith(prefix):
                continue
            if any(tbl.startswith(f"{sid}_") or tbl == sid for sid in shadowing):
                continue  # belongs to a different, longer-named space
            out.append(tbl)
        return out

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

