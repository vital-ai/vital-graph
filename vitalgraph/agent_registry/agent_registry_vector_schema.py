"""
PostgreSQL schema for Agent Registry vector and FTS tables.

These are global tables (not per-space) that provide pgvector/FTS
search capabilities for the agent registry.

Table naming: agent_registry_vec_agent, agent_registry_fts_agent.
"""

from typing import List

from vitalgraph.agent_registry.agent_registry_vector_config import (
    EMBEDDING_COLUMNS,
    OPENAI,
    PARAPHRASE_MULTILINGUAL,
    VITALSIGNS_ONNX,
    get_agent_registry_dimensions,
    get_agent_registry_model_name,
    get_agent_registry_provider_name,
)

# Short, stable suffixes for index names — the column names themselves would
# push some index identifiers past PostgreSQL's 63-character limit.
_INDEX_SUFFIXES = {
    VITALSIGNS_ONNX: "vsonnx",
    PARAPHRASE_MULTILINGUAL: "paraml",
    OPENAI: "oai3s",
}

VECTOR_TABLE_INDEX_PREFIX = {"agent_registry_vec_agent": "arva"}
LEGACY_EMBEDDING_COLUMN = "embedding"
LEGACY_HNSW_INDEXES = {"agent_registry_vec_agent": "idx_arva_hnsw"}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Width of the vector(N) columns, derived from the configured provider so the
# DDL and the provider that fills it cannot diverge.  Read at import time:
# these tables are created by an explicit action, so the value in force when
# that script runs is the one baked into the tables.
DIMENSIONS = get_agent_registry_dimensions()
DISTANCE_METRIC = "cosine"
OPS_CLASS = "vector_cosine_ops"


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

AGENT_VECTOR_TABLE = "agent_registry_vec_agent"
FTS_AGENT_TABLE = "agent_registry_fts_agent"
VECTOR_INDEX_TABLE = "agent_registry_vector_index"


def _embedding_column_ddl() -> str:
    """One nullable vector column per supported model, at its native width.

    Nullable by design: only the configured model's column is populated, and an
    unpopulated column costs nothing (a null-bitmap bit in the heap, and an
    empty HNSW index).
    """
    return ",\n".join(
        f"            {column:<38} vector({dims})"
        for column, dims in EMBEDDING_COLUMNS.values()
    )


def embedding_index_ddl(table: str, prefix: str) -> List[str]:
    """An HNSW index per embedding column."""
    return [
        f'''
        CREATE INDEX IF NOT EXISTS idx_{prefix}_hnsw_{suffix}
            ON {table}
            USING hnsw ({EMBEDDING_COLUMNS[provider][0]} {OPS_CLASS})
            WITH (m = 16, ef_construction = 200)
        '''
        for provider, suffix in _INDEX_SUFFIXES.items()
    ]


def create_tables_sql() -> List[str]:
    """Return all DDL statements for agent registry vector/FTS tables."""
    stmts = []

    # ------------------------------------------------------------------
    # Vector index registry (catalog)
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {VECTOR_INDEX_TABLE} (
            index_id        SERIAL PRIMARY KEY,
            index_name      VARCHAR(255) NOT NULL UNIQUE,
            dimensions      INT NOT NULL DEFAULT {DIMENSIONS},
            distance_metric VARCHAR(20) NOT NULL DEFAULT '{DISTANCE_METRIC}',
            provider        VARCHAR(100) DEFAULT 'vitalsigns_onnx',
            provider_config JSONB DEFAULT '{{}}'::jsonb,
            model_name      VARCHAR(255) DEFAULT 'paraphrase-MiniLM-L3-v2',
            description     TEXT,
            created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ------------------------------------------------------------------
    # Agent vector table
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {AGENT_VECTOR_TABLE} (
            subject_uuid    UUID NOT NULL PRIMARY KEY,
            agent_id        VARCHAR(50) NOT NULL,
{_embedding_column_ddl()},
            search_text     TEXT,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.extend(embedding_index_ddl(AGENT_VECTOR_TABLE, "arva"))
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_arva_agent_id
            ON {AGENT_VECTOR_TABLE} (agent_id)
    ''')

    # ------------------------------------------------------------------
    # FTS agent table
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {FTS_AGENT_TABLE} (
            subject_uuid    UUID NOT NULL PRIMARY KEY,
            agent_id        VARCHAR(50) NOT NULL,
            search_text     TEXT,
            tsv             tsvector,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_arfa_gin
            ON {FTS_AGENT_TABLE} USING gin (tsv)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_arfa_agent_id
            ON {FTS_AGENT_TABLE} (agent_id)
    ''')
    # Trigger for auto-computing tsvector
    stmts.append(f'''
        CREATE OR REPLACE FUNCTION agent_registry_fts_agent_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.tsv := to_tsvector('english'::regconfig, COALESCE(NEW.search_text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    ''')
    stmts.append(f'''
        DROP TRIGGER IF EXISTS trg_arfa_tsv ON {FTS_AGENT_TABLE}
    ''')
    stmts.append(f'''
        CREATE TRIGGER trg_arfa_tsv
            BEFORE INSERT OR UPDATE OF search_text ON {FTS_AGENT_TABLE}
            FOR EACH ROW EXECUTE FUNCTION agent_registry_fts_agent_tsv_trigger()
    ''')

    return stmts


def drop_tables_sql() -> List[str]:
    """Return DDL to drop all agent registry vector/FTS tables."""
    return [
        f"DROP TABLE IF EXISTS {FTS_AGENT_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {AGENT_VECTOR_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {VECTOR_INDEX_TABLE} CASCADE",
        "DROP FUNCTION IF EXISTS agent_registry_fts_agent_tsv_trigger() CASCADE",
    ]


def seed_default_index_sql() -> str:
    """Insert default vector index row if absent."""
    return f'''
        INSERT INTO {VECTOR_INDEX_TABLE} (index_name, dimensions, distance_metric, provider, model_name, description)
        VALUES ('agent', {DIMENSIONS}, '{DISTANCE_METRIC}',
                '{get_agent_registry_provider_name()}',
                '{get_agent_registry_model_name()}',
                'Default agent registry vector index')
        ON CONFLICT (index_name) DO NOTHING
    '''
