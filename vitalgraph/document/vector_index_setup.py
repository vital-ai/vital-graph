"""
Document Segments Vector Index Setup.

Provides utilities to register the `document_segments` vector index
and its associated mapping for a space. Called during space initialization
or explicitly via admin commands.

The document_segments index is dedicated to document segment embeddings,
separate from the entity_default index.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default index configuration
DOCUMENT_SEGMENTS_INDEX_NAME = "document_segments"
DEFAULT_DIMENSIONS = 384
DEFAULT_DISTANCE_METRIC = "cosine"
DEFAULT_PROVIDER = "vitalsigns"
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DESCRIPTION = "Document segment embeddings for chunk retrieval"

# Mapping config for document segments
SEGMENTS_MAPPING_TYPE = "kgdocument_segment"
SEGMENTS_SOURCE_TYPE = "default"


async def ensure_document_segments_index(
    conn,
    space_id: str,
    *,
    dimensions: int = DEFAULT_DIMENSIONS,
    distance_metric: str = DEFAULT_DISTANCE_METRIC,
    provider: str = DEFAULT_PROVIDER,
    model_name: str = DEFAULT_MODEL,
    description: str = DEFAULT_DESCRIPTION,
) -> bool:
    """
    Ensure the document_segments vector index exists for the given space.

    Creates the index entry in {space_id}_vector_index if it doesn't exist,
    and creates the corresponding vec_{index_name} table.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        dimensions: Embedding dimensions (default 384 for MiniLM).
        distance_metric: Distance metric (cosine, l2, ip).
        provider: Vectorization provider name.
        model_name: Model identifier for the provider.
        description: Human-readable description.

    Returns:
        True if created or already exists, False on error.
    """
    vector_index_table = f"{space_id}_vector_index"
    vec_table = f"{space_id}_vec_{DOCUMENT_SEGMENTS_INDEX_NAME}"

    try:
        # Check if already exists
        row = await conn.fetchrow(
            f"SELECT index_name FROM {vector_index_table} WHERE index_name = $1",
            DOCUMENT_SEGMENTS_INDEX_NAME,
        )
        if row:
            logger.debug(f"document_segments index already exists for space {space_id}")
            return True

        # Create the index entry
        await conn.execute(
            f"""
            INSERT INTO {vector_index_table}
                (index_name, dimensions, distance_metric, provider, model_name, description)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (index_name) DO NOTHING
            """,
            DOCUMENT_SEGMENTS_INDEX_NAME,
            dimensions,
            distance_metric,
            provider,
            model_name,
            description,
        )

        # Create the vector storage table
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {vec_table} (
                subject_uuid    UUID NOT NULL,
                context_uuid    UUID NOT NULL,
                embedding       vector({dimensions}),
                search_text     TEXT,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (subject_uuid, context_uuid)
            )
        """)

        # Create HNSW index for vector similarity search
        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {vec_table}_hnsw_idx
            ON {vec_table}
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)

        logger.info(
            f"Created document_segments vector index for space {space_id}: "
            f"dimensions={dimensions}, provider={provider}, model={model_name}"
        )
        return True

    except Exception as e:
        logger.error(f"Error creating document_segments index for {space_id}: {e}")
        return False


async def ensure_document_segments_mapping(
    conn,
    space_id: str,
    *,
    type_uri: str = "urn:kgdoctype:document_segment",
) -> bool:
    """
    Ensure a vector mapping exists for document segments.

    This maps KGDocuments with kGDocumentType='urn:kgdoctype:document_segment'
    to the document_segments vector index.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        type_uri: The document type URI that identifies segments.

    Returns:
        True if created/exists, False on error.
    """
    mapping_table = f"{space_id}_vector_mapping"
    property_table = f"{space_id}_vector_mapping_property"

    try:
        # Check if mapping already exists
        row = await conn.fetchrow(
            f"""
            SELECT mapping_id FROM {mapping_table}
            WHERE mapping_type = $1 AND index_name = $2
            """,
            SEGMENTS_MAPPING_TYPE,
            DOCUMENT_SEGMENTS_INDEX_NAME,
        )
        if row:
            logger.debug(f"document_segments mapping already exists for space {space_id}")
            return True

        # Create mapping
        mapping_id = await conn.fetchval(
            f"""
            INSERT INTO {mapping_table}
                (mapping_type, type_uri, index_name, enabled, source_type,
                 separator, include_pred_name, include_type_desc)
            VALUES ($1, $2, $3, TRUE, $4, '. ', FALSE, FALSE)
            RETURNING mapping_id
            """,
            SEGMENTS_MAPPING_TYPE,
            type_uri,
            DOCUMENT_SEGMENTS_INDEX_NAME,
            SEGMENTS_SOURCE_TYPE,
        )

        # Add property mapping: kGraphDescription is the source text
        # (segments store their content in kGraphDescription for vectorization)
        kgraph_desc_uri = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
        await conn.execute(
            f"""
            INSERT INTO {property_table}
                (mapping_id, property_uri, property_role, ordinal)
            VALUES ($1, $2, 'include', 1)
            """,
            mapping_id,
            kgraph_desc_uri,
        )

        logger.info(
            f"Created document_segments mapping for space {space_id}: "
            f"mapping_id={mapping_id}, type_uri={type_uri}"
        )
        return True

    except Exception as e:
        logger.error(f"Error creating document_segments mapping for {space_id}: {e}")
        return False


async def setup_document_segments_vectorization(conn, space_id: str) -> bool:
    """
    One-shot setup: create both the index and mapping for document segments.

    Call this during space initialization or via admin endpoint.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.

    Returns:
        True if both index and mapping are ready.
    """
    index_ok = await ensure_document_segments_index(conn, space_id)
    if not index_ok:
        return False

    mapping_ok = await ensure_document_segments_mapping(conn, space_id)
    return mapping_ok
