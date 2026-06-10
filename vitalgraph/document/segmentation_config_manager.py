"""
Segmentation Config Manager.

Manages the document_segmentation_config table which maps document types
to automatic segmentation configurations. When a KGDocument is inserted
or updated with a matching kGDocumentType, segmentation is auto-triggered.

Table: {space_id}_document_segmentation_config
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class SegmentationConfigDTO:
    """Represents a row in the document_segmentation_config table."""

    config_id: int
    document_type_uri: str
    segment_method_uri: str
    max_segment_tokens: int = 512
    min_segment_tokens: int = 50
    overlap_tokens: int = 0
    enabled: bool = True
    auto_vectorize: bool = True
    created_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("created_time"):
            d["created_time"] = str(d["created_time"])
        return d


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    config_id SERIAL PRIMARY KEY,
    document_type_uri VARCHAR(500) NOT NULL,
    segment_method_uri VARCHAR(500) NOT NULL,
    max_segment_tokens INTEGER NOT NULL DEFAULT 512,
    min_segment_tokens INTEGER NOT NULL DEFAULT 50,
    overlap_tokens INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    auto_vectorize BOOLEAN NOT NULL DEFAULT TRUE,
    created_time TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (document_type_uri, segment_method_uri)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS {table_name}_doc_type_idx
    ON {table_name} (document_type_uri) WHERE enabled = TRUE;
"""


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SegmentationConfigManager:
    """
    CRUD operations on the document_segmentation_config table.

    ``conn`` must be an asyncpg Connection (or pool-acquired connection).
    All public methods are async.
    """

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self.space_id = space_id
        self._table = f"{space_id}_document_segmentation_config"

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    async def ensure_table(self) -> None:
        """Create the config table if it doesn't exist."""
        sql = CREATE_TABLE_SQL.format(table_name=self._table)
        await self.conn.execute(sql)
        idx_sql = CREATE_INDEX_SQL.format(table_name=self._table)
        await self.conn.execute(idx_sql)
        logger.info(f"Ensured segmentation config table: {self._table}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_config(
        self,
        document_type_uri: str,
        segment_method_uri: str,
        *,
        max_segment_tokens: int = 512,
        min_segment_tokens: int = 50,
        overlap_tokens: int = 0,
        enabled: bool = True,
        auto_vectorize: bool = True,
    ) -> int:
        """
        Create a new segmentation config.

        Returns the new config_id.
        """
        sql = f"""
            INSERT INTO {self._table}
                (document_type_uri, segment_method_uri, max_segment_tokens,
                 min_segment_tokens, overlap_tokens, enabled, auto_vectorize)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (document_type_uri, segment_method_uri)
            DO UPDATE SET
                max_segment_tokens = EXCLUDED.max_segment_tokens,
                min_segment_tokens = EXCLUDED.min_segment_tokens,
                overlap_tokens = EXCLUDED.overlap_tokens,
                enabled = EXCLUDED.enabled,
                auto_vectorize = EXCLUDED.auto_vectorize
            RETURNING config_id
        """
        config_id = await self.conn.fetchval(
            sql, document_type_uri, segment_method_uri,
            max_segment_tokens, min_segment_tokens, overlap_tokens,
            enabled, auto_vectorize
        )
        logger.info(
            f"Created/updated segmentation config {config_id}: "
            f"doc_type={document_type_uri}, method={segment_method_uri}"
        )
        return config_id

    async def get_config(self, config_id: int) -> Optional[SegmentationConfigDTO]:
        """Get a single config by ID."""
        sql = f"SELECT * FROM {self._table} WHERE config_id = $1"
        row = await self.conn.fetchrow(sql, config_id)
        if row:
            return self._row_to_dto(row)
        return None

    async def get_config_for_document_type(
        self, document_type_uri: str
    ) -> List[SegmentationConfigDTO]:
        """
        Get all enabled configs for a given document type.

        Returns list of configs (may be multiple if multiple methods configured).
        """
        sql = f"""
            SELECT * FROM {self._table}
            WHERE document_type_uri = $1 AND enabled = TRUE
            ORDER BY config_id
        """
        rows = await self.conn.fetch(sql, document_type_uri)
        return [self._row_to_dto(row) for row in rows]

    async def list_configs(self, enabled_only: bool = False) -> List[SegmentationConfigDTO]:
        """List all configs, optionally filtered to enabled only."""
        if enabled_only:
            sql = f"SELECT * FROM {self._table} WHERE enabled = TRUE ORDER BY config_id"
        else:
            sql = f"SELECT * FROM {self._table} ORDER BY config_id"
        rows = await self.conn.fetch(sql)
        return [self._row_to_dto(row) for row in rows]

    async def update_config(
        self,
        config_id: int,
        *,
        max_segment_tokens: Optional[int] = None,
        min_segment_tokens: Optional[int] = None,
        overlap_tokens: Optional[int] = None,
        enabled: Optional[bool] = None,
        auto_vectorize: Optional[bool] = None,
    ) -> bool:
        """Update specific fields of a config. Returns True if updated."""
        updates = []
        params = []
        param_idx = 1

        if max_segment_tokens is not None:
            updates.append(f"max_segment_tokens = ${param_idx}")
            params.append(max_segment_tokens)
            param_idx += 1
        if min_segment_tokens is not None:
            updates.append(f"min_segment_tokens = ${param_idx}")
            params.append(min_segment_tokens)
            param_idx += 1
        if overlap_tokens is not None:
            updates.append(f"overlap_tokens = ${param_idx}")
            params.append(overlap_tokens)
            param_idx += 1
        if enabled is not None:
            updates.append(f"enabled = ${param_idx}")
            params.append(enabled)
            param_idx += 1
        if auto_vectorize is not None:
            updates.append(f"auto_vectorize = ${param_idx}")
            params.append(auto_vectorize)
            param_idx += 1

        if not updates:
            return False

        params.append(config_id)
        sql = f"""
            UPDATE {self._table}
            SET {', '.join(updates)}
            WHERE config_id = ${param_idx}
        """
        result = await self.conn.execute(sql, *params)
        updated = result.endswith("1") if isinstance(result, str) else False
        if updated:
            logger.info(f"Updated segmentation config {config_id}")
        return updated

    async def delete_config(self, config_id: int) -> bool:
        """Delete a config by ID. Returns True if deleted."""
        sql = f"DELETE FROM {self._table} WHERE config_id = $1"
        result = await self.conn.execute(sql, config_id)
        deleted = result.endswith("1") if isinstance(result, str) else False
        if deleted:
            logger.info(f"Deleted segmentation config {config_id}")
        return deleted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dto(row) -> SegmentationConfigDTO:
        """Convert an asyncpg Record to DTO."""
        return SegmentationConfigDTO(
            config_id=row["config_id"],
            document_type_uri=row["document_type_uri"],
            segment_method_uri=row["segment_method_uri"],
            max_segment_tokens=row["max_segment_tokens"],
            min_segment_tokens=row["min_segment_tokens"],
            overlap_tokens=row["overlap_tokens"],
            enabled=row["enabled"],
            auto_vectorize=row["auto_vectorize"],
            created_time=str(row["created_time"]) if row.get("created_time") else None,
        )
