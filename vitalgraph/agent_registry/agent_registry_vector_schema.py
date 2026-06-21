"""
PostgreSQL schema for Agent Registry vector and FTS tables.

These are global tables (not per-space) that provide pgvector/FTS
search capabilities for the agent registry.

Table naming: agent_registry_vec_agent, agent_registry_fts_agent.
"""

from typing import List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIMENSIONS = 384  # paraphrase-multilingual-MiniLM-L12-v2
DISTANCE_METRIC = "cosine"
OPS_CLASS = "vector_cosine_ops"


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

AGENT_VECTOR_TABLE = "agent_registry_vec_agent"
FTS_AGENT_TABLE = "agent_registry_fts_agent"
VECTOR_INDEX_TABLE = "agent_registry_vector_index"


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
            model_name      VARCHAR(255) DEFAULT 'paraphrase-multilingual-MiniLM-L12-v2',
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
            embedding       vector({DIMENSIONS}) NOT NULL,
            search_text     TEXT,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_arva_hnsw
            ON {AGENT_VECTOR_TABLE}
            USING hnsw (embedding {OPS_CLASS})
            WITH (m = 16, ef_construction = 200)
    ''')
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
        VALUES ('agent', {DIMENSIONS}, '{DISTANCE_METRIC}', 'vitalsigns_onnx',
                'paraphrase-multilingual-MiniLM-L12-v2', 'Default agent registry vector index')
        ON CONFLICT (index_name) DO NOTHING
    '''
