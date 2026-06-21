"""
PostgreSQL schema for Entity Registry vector, FTS, and geo tables.

These are global tables (not per-space) that provide pgvector/PostGIS/FTS
search capabilities for the entity registry, replacing Weaviate.

Table naming: entity_registry_vec_entity, entity_registry_vec_location,
entity_registry_geo, entity_registry_fts_entity, entity_registry_fts_location.
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

ENTITY_VECTOR_TABLE = "entity_registry_vec_entity"
LOCATION_VECTOR_TABLE = "entity_registry_vec_location"
GEO_TABLE = "entity_registry_geo"
FTS_ENTITY_TABLE = "entity_registry_fts_entity"
FTS_LOCATION_TABLE = "entity_registry_fts_location"
VECTOR_INDEX_TABLE = "entity_registry_vector_index"


def create_tables_sql() -> List[str]:
    """Return all DDL statements for entity registry vector/FTS/geo tables."""
    stmts = []

    # ------------------------------------------------------------------
    # Vector index registry (catalog of named indexes)
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
    # Entity vector table
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {ENTITY_VECTOR_TABLE} (
            subject_uuid    UUID NOT NULL PRIMARY KEY,
            entity_id       VARCHAR(50) NOT NULL,
            embedding       vector({DIMENSIONS}) NOT NULL,
            search_text     TEXT,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erve_hnsw
            ON {ENTITY_VECTOR_TABLE}
            USING hnsw (embedding {OPS_CLASS})
            WITH (m = 16, ef_construction = 200)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erve_entity_id
            ON {ENTITY_VECTOR_TABLE} (entity_id)
    ''')

    # ------------------------------------------------------------------
    # Location vector table
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {LOCATION_VECTOR_TABLE} (
            subject_uuid    UUID NOT NULL PRIMARY KEY,
            location_id     INTEGER NOT NULL,
            entity_id       VARCHAR(50) NOT NULL,
            embedding       vector({DIMENSIONS}) NOT NULL,
            search_text     TEXT,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_ervl_hnsw
            ON {LOCATION_VECTOR_TABLE}
            USING hnsw (embedding {OPS_CLASS})
            WITH (m = 16, ef_construction = 200)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_ervl_entity_id
            ON {LOCATION_VECTOR_TABLE} (entity_id)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_ervl_location_id
            ON {LOCATION_VECTOR_TABLE} (location_id)
    ''')

    # ------------------------------------------------------------------
    # Geo table (entities + locations combined)
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {GEO_TABLE} (
            id              BIGSERIAL PRIMARY KEY,
            subject_uuid    UUID NOT NULL,
            source_type     VARCHAR(20) NOT NULL,
            source_id       VARCHAR(50) NOT NULL,
            entity_id       VARCHAR(50) NOT NULL,
            location        geography(Point, 4326) NOT NULL,
            latitude        DOUBLE PRECISION NOT NULL,
            longitude       DOUBLE PRECISION NOT NULL,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (subject_uuid, source_type)
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erg_gist
            ON {GEO_TABLE} USING gist (location)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erg_entity_id
            ON {GEO_TABLE} (entity_id)
    ''')

    # ------------------------------------------------------------------
    # FTS entity table
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {FTS_ENTITY_TABLE} (
            subject_uuid    UUID NOT NULL PRIMARY KEY,
            entity_id       VARCHAR(50) NOT NULL,
            search_text     TEXT,
            tsv             tsvector,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erfe_gin
            ON {FTS_ENTITY_TABLE} USING gin (tsv)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erfe_entity_id
            ON {FTS_ENTITY_TABLE} (entity_id)
    ''')
    # Trigger for auto-computing tsvector
    stmts.append(f'''
        CREATE OR REPLACE FUNCTION entity_registry_fts_entity_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.tsv := to_tsvector('english'::regconfig, COALESCE(NEW.search_text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    ''')
    stmts.append(f'''
        DROP TRIGGER IF EXISTS trg_erfe_tsv ON {FTS_ENTITY_TABLE}
    ''')
    stmts.append(f'''
        CREATE TRIGGER trg_erfe_tsv
            BEFORE INSERT OR UPDATE OF search_text ON {FTS_ENTITY_TABLE}
            FOR EACH ROW EXECUTE FUNCTION entity_registry_fts_entity_tsv_trigger()
    ''')

    # ------------------------------------------------------------------
    # FTS location table
    # ------------------------------------------------------------------
    stmts.append(f'''
        CREATE TABLE IF NOT EXISTS {FTS_LOCATION_TABLE} (
            subject_uuid    UUID NOT NULL PRIMARY KEY,
            location_id     INTEGER NOT NULL,
            entity_id       VARCHAR(50) NOT NULL,
            search_text     TEXT,
            tsv             tsvector,
            updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erfl_gin
            ON {FTS_LOCATION_TABLE} USING gin (tsv)
    ''')
    stmts.append(f'''
        CREATE INDEX IF NOT EXISTS idx_erfl_entity_id
            ON {FTS_LOCATION_TABLE} (entity_id)
    ''')
    stmts.append(f'''
        CREATE OR REPLACE FUNCTION entity_registry_fts_location_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.tsv := to_tsvector('english'::regconfig, COALESCE(NEW.search_text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    ''')
    stmts.append(f'''
        DROP TRIGGER IF EXISTS trg_erfl_tsv ON {FTS_LOCATION_TABLE}
    ''')
    stmts.append(f'''
        CREATE TRIGGER trg_erfl_tsv
            BEFORE INSERT OR UPDATE OF search_text ON {FTS_LOCATION_TABLE}
            FOR EACH ROW EXECUTE FUNCTION entity_registry_fts_location_tsv_trigger()
    ''')

    return stmts


def drop_tables_sql() -> List[str]:
    """Return DDL to drop all entity registry vector/FTS/geo tables."""
    return [
        f"DROP TABLE IF EXISTS {FTS_LOCATION_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {FTS_ENTITY_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {GEO_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {LOCATION_VECTOR_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {ENTITY_VECTOR_TABLE} CASCADE",
        f"DROP TABLE IF EXISTS {VECTOR_INDEX_TABLE} CASCADE",
        "DROP FUNCTION IF EXISTS entity_registry_fts_entity_tsv_trigger() CASCADE",
        "DROP FUNCTION IF EXISTS entity_registry_fts_location_tsv_trigger() CASCADE",
    ]


def seed_default_index_sql() -> str:
    """Insert default vector index row if absent."""
    return f'''
        INSERT INTO {VECTOR_INDEX_TABLE} (index_name, dimensions, distance_metric, provider, model_name, description)
        VALUES ('entity', {DIMENSIONS}, '{DISTANCE_METRIC}', 'vitalsigns_onnx',
                'paraphrase-multilingual-MiniLM-L12-v2', 'Default entity registry vector index')
        ON CONFLICT (index_name) DO NOTHING
    '''
