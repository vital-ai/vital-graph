"""
General-purpose vector index lifecycle helpers.

Provides setup, teardown, and swap operations for any named vector index.
Callers supply index configuration (name, dimensions, provider, etc.)
and mapping definitions as plain data — no class-specific logic lives here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

logger = logging.getLogger(__name__)


# ── Type alias for mapping definitions ────────────────────────────────

# Each mapping definition is a dict with keys:
#   mapping_type: str          — e.g. "kgtype", "kgentity"
#   type_uri: Optional[str]    — None for class-level, URI for override
#   source_type: str           — e.g. "properties", "default"
#   properties: List[str]      — ordered property URIs to include
#   (optional) enabled, separator, include_pred_name
MappingDef = Dict[str, Any]


# =====================================================================
# Public API
# =====================================================================

async def ensure_index(
    conn,
    space_id: str,
    index_name: str,
    config: Dict[str, Any],
) -> bool:
    """Ensure a vector index exists (registry row + data table).

    *config* must contain: ``dimensions``, ``distance_metric``,
    ``provider``, ``model_name``.  Optional: ``provider_config``,
    ``description``.

    Returns True if created or already exists, False on error.
    """
    vector_index_table = f"{space_id}_vector_index"
    try:
        row = await conn.fetchrow(
            f"SELECT index_name FROM {vector_index_table} WHERE index_name = $1",
            index_name,
        )
        if row:
            logger.debug("Index '%s' already exists for space %s", index_name, space_id)
            return True

        await conn.execute(
            f"""
            INSERT INTO {vector_index_table}
                (index_name, dimensions, distance_metric, provider,
                 model_name, provider_config, description)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            ON CONFLICT (index_name) DO NOTHING
            """,
            index_name,
            config["dimensions"],
            config["distance_metric"],
            config["provider"],
            config["model_name"],
            _jsonb(config.get("provider_config")),
            config.get("description", ""),
        )

        schema = SparqlSQLSchema()
        for stmt in schema.create_vector_data_table_sql(
            space_id, index_name,
            config["dimensions"], config["distance_metric"],
        ):
            await conn.execute(stmt)

        logger.info(
            "Created vector index '%s' for space %s: dims=%d, provider=%s",
            index_name, space_id, config["dimensions"], config["provider"],
        )
        return True

    except Exception as e:
        logger.error("Error creating index '%s' for %s: %s", index_name, space_id, e)
        return False


async def ensure_mappings(
    conn,
    space_id: str,
    index_name: str,
    mapping_defs: List[MappingDef],
) -> bool:
    """Ensure vector mapping rules exist for *index_name*.

    Each entry in *mapping_defs* describes one mapping row and its child
    properties.  Skips creation if any mapping already exists for the
    given ``(index_name, mapping_type)`` pair.

    Returns True on success, False on error.
    """
    mgr = SearchMappingManager(conn, space_id)
    try:
        for mdef in mapping_defs:
            mapping_type = mdef["mapping_type"]
            type_uri = mdef.get("type_uri")

            existing = await mgr.list_mappings(
                index_name=index_name, mapping_type=mapping_type,
            )
            # If override-level: check if this exact type_uri already exists
            if type_uri:
                if any(m.type_uri == type_uri for m in existing):
                    continue
            elif existing:
                continue

            mid = await mgr.create_mapping(
                index_name=index_name,
                mapping_type=mapping_type,
                type_uri=type_uri,
                source_type=mdef.get("source_type", "default"),
                enabled=mdef.get("enabled", True),
                separator=mdef.get("separator", ". "),
                include_pred_name=mdef.get("include_pred_name", False),
            )
            for ordinal, prop_uri in enumerate(mdef.get("properties", []), start=1):
                await mgr.add_property(mid, prop_uri, ordinal=ordinal)

        logger.info(
            "Ensured %d mapping rule(s) for index '%s' in space %s",
            len(mapping_defs), index_name, space_id,
        )
        return True

    except Exception as e:
        logger.error(
            "Error creating mappings for index '%s' in %s: %s",
            index_name, space_id, e,
        )
        return False


async def setup_index(
    conn,
    space_id: str,
    index_name: str,
    config: Dict[str, Any],
    mapping_defs: List[MappingDef],
) -> bool:
    """One-shot: create index + mappings.

    Returns True when both the index and all mappings are ready.
    """
    if not await ensure_index(conn, space_id, index_name, config):
        return False
    return await ensure_mappings(conn, space_id, index_name, mapping_defs)


async def teardown_index(conn, space_id: str, index_name: str) -> bool:
    """Clean-slate removal: drop data table, delete mappings, delete registry row.

    Returns True on success.
    """
    try:
        vec_table = f"{space_id}_vec_{index_name}"
        mapping_table = f"{space_id}_search_mapping"
        vector_index_table = f"{space_id}_vector_index"

        await conn.execute(f"DROP TABLE IF EXISTS {vec_table} CASCADE")
        await conn.execute(
            f"DELETE FROM {mapping_table} WHERE index_name = $1", index_name,
        )
        await conn.execute(
            f"DELETE FROM {vector_index_table} WHERE index_name = $1", index_name,
        )
        logger.info("Torn down index '%s' for space %s", index_name, space_id)
        return True

    except Exception as e:
        logger.error("Error tearing down index '%s' for %s: %s", index_name, space_id, e)
        return False


async def swap_index(
    conn,
    space_id: str,
    index_name: str,
    new_config: Dict[str, Any],
    mapping_defs: List[MappingDef],
) -> bool:
    """Clean-slate swap: teardown then setup with new provider config.

    Does **not** repopulate — call ``populate_index()`` separately.
    """
    if not await teardown_index(conn, space_id, index_name):
        return False
    return await setup_index(conn, space_id, index_name, new_config, mapping_defs)


# ── helpers ───────────────────────────────────────────────────────────

def _jsonb(value) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)
