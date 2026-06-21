"""
KG Type Search Index Setup.

Provides utilities to register the `kgtype_default` vector index,
FTS index, and associated search mappings for a space.
Called during space initialization to ensure every space has
KG Type search infrastructure out of the box.

Follows the same pattern as document/vector_index_setup.py.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default index configuration
KGTYPE_INDEX_NAME = "kgtype_default"
DEFAULT_DIMENSIONS = 384
DEFAULT_DISTANCE_METRIC = "cosine"
DEFAULT_PROVIDER = "vitalsigns"
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DESCRIPTION = "KG Type embeddings for type search (entity, frame, slot types)"

# Property URIs
PROP_NAME = "http://vital.ai/ontology/vital-core#hasName"
PROP_DESCRIPTION = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
PROP_ENTITY_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription"
PROP_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
PROP_SLOT_TYPE_NAME = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeName"
PROP_SLOT_TYPE_LABEL = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeLabel"

# Type URIs for per-type override mappings
TYPE_URI_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntityType"
TYPE_URI_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrameType"
TYPE_URI_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGSlotType"


async def ensure_kgtype_index(
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
    Ensure the kgtype_default vector index exists for the given space.

    Creates the index entry in {space_id}_vector_index if it doesn't exist,
    and creates the corresponding vec_{index_name} table.

    Returns:
        True if created or already exists, False on error.
    """
    vector_index_table = f"{space_id}_vector_index"
    vec_table = f"{space_id}_vec_{KGTYPE_INDEX_NAME}"

    try:
        row = await conn.fetchrow(
            f"SELECT index_name FROM {vector_index_table} WHERE index_name = $1",
            KGTYPE_INDEX_NAME,
        )
        if row:
            logger.debug("kgtype_default index already exists for space %s", space_id)
            return True

        await conn.execute(
            f"""
            INSERT INTO {vector_index_table}
                (index_name, dimensions, distance_metric, provider, model_name, description)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (index_name) DO NOTHING
            """,
            KGTYPE_INDEX_NAME,
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
                updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            "Created kgtype_default vector index for space %s: "
            "dimensions=%d, provider=%s, model=%s",
            space_id, dimensions, provider, model_name,
        )
        return True

    except Exception as e:
        logger.error("Error creating kgtype_default index for %s: %s", space_id, e)
        return False


async def ensure_kgtype_fts_index(conn, space_id: str) -> bool:
    """
    Ensure the kgtype_default FTS index exists for the given space.

    Returns:
        True if created or already exists, False on error.
    """
    try:
        from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index
        return await ensure_fts_index(conn, space_id, KGTYPE_INDEX_NAME)
    except Exception as e:
        logger.error("Error creating kgtype_default FTS index for %s: %s", space_id, e)
        return False


async def ensure_kgtype_mappings(conn, space_id: str) -> bool:
    """
    Ensure search mappings exist for KG Type search.

    Creates:
      - Base mapping (all KGTypes): hasName + hasKGraphDescription
      - KGEntityType override: + hasKGEntityTypeDescription
      - KGFrameType override: + hasKGFrameTypeDescription
      - KGSlotType override: + hasKGSlotTypeName + hasKGSlotTypeLabel

    Returns:
        True if all mappings created/exist, False on error.
    """
    mapping_table = f"{space_id}_search_mapping"
    property_table = f"{space_id}_search_mapping_property"

    mapping_defs = [
        # Base mapping (covers KGRelationType and any type without a specific override)
        {
            "type_uri": None,
            "properties": [PROP_NAME, PROP_DESCRIPTION],
        },
        # KGEntityType
        {
            "type_uri": TYPE_URI_ENTITY,
            "properties": [PROP_NAME, PROP_DESCRIPTION, PROP_ENTITY_TYPE_DESC],
        },
        # KGFrameType
        {
            "type_uri": TYPE_URI_FRAME,
            "properties": [PROP_NAME, PROP_DESCRIPTION, PROP_FRAME_TYPE_DESC],
        },
        # KGSlotType
        {
            "type_uri": TYPE_URI_SLOT,
            "properties": [PROP_NAME, PROP_SLOT_TYPE_NAME, PROP_SLOT_TYPE_LABEL, PROP_DESCRIPTION],
        },
    ]

    try:
        for mdef in mapping_defs:
            type_uri = mdef["type_uri"]

            # Check if this mapping already exists
            if type_uri:
                row = await conn.fetchrow(
                    f"""SELECT mapping_id FROM {mapping_table}
                        WHERE mapping_type = 'kgtype' AND index_name = $1 AND type_uri = $2""",
                    KGTYPE_INDEX_NAME, type_uri,
                )
            else:
                row = await conn.fetchrow(
                    f"""SELECT mapping_id FROM {mapping_table}
                        WHERE mapping_type = 'kgtype' AND index_name = $1 AND type_uri IS NULL""",
                    KGTYPE_INDEX_NAME,
                )

            if row:
                continue

            # Create mapping
            mapping_id = await conn.fetchval(
                f"""
                INSERT INTO {mapping_table}
                    (mapping_type, type_uri, index_name, enabled, source_type,
                     separator, include_pred_name)
                VALUES ('kgtype', $1, $2, TRUE, 'properties', '. ', FALSE)
                RETURNING mapping_id
                """,
                type_uri, KGTYPE_INDEX_NAME,
            )

            # Add properties
            for ordinal, prop_uri in enumerate(mdef["properties"], start=1):
                await conn.execute(
                    f"""
                    INSERT INTO {property_table}
                        (mapping_id, property_uri, property_role, ordinal)
                    VALUES ($1, $2, 'include', $3)
                    """,
                    mapping_id, prop_uri, ordinal,
                )

            label = type_uri.rsplit("#", 1)[-1] if type_uri else "base"
            logger.info(
                "Created kgtype_default mapping for %s: %s (mapping_id=%d, %d props)",
                space_id, label, mapping_id, len(mdef["properties"]),
            )

        return True

    except Exception as e:
        logger.error("Error creating kgtype_default mappings for %s: %s", space_id, e)
        return False


async def setup_kgtype_search(conn, space_id: str) -> bool:
    """
    One-shot setup: create vector index, FTS index, and mappings for KG Type search.

    Call this during space initialization or via admin endpoint.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.

    Returns:
        True if all components are ready.
    """
    index_ok = await ensure_kgtype_index(conn, space_id)
    if not index_ok:
        return False

    fts_ok = await ensure_kgtype_fts_index(conn, space_id)
    if not fts_ok:
        logger.warning("kgtype_default FTS index setup failed for %s (non-critical)", space_id)

    mapping_ok = await ensure_kgtype_mappings(conn, space_id)
    return mapping_ok
