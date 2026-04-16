"""
Change Log operations mixin for the Entity Registry.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    import asyncpg


class ChangeLogMixin:
    """Change log and helper methods."""

    pool: asyncpg.Pool

    async def _log_change(
        self, conn, entity_id: Optional[str], change_type: str,
        change_detail: Optional[Dict] = None,
        changed_by: Optional[str] = None,
        comment: Optional[str] = None,
    ):
        """Insert a change log entry within an existing connection/transaction."""
        detail_json = json.dumps(change_detail) if change_detail else None
        await conn.execute(
            "INSERT INTO entity_change_log (entity_id, change_type, change_detail, changed_by, comment) "
            "VALUES ($1, $2, $3::jsonb, $4, $5)",
            entity_id, change_type, detail_json, changed_by, comment
        )

    async def get_change_log(
        self, entity_id: str,
        change_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get change log for a specific entity."""
        conditions = ["entity_id = $1"]
        params: list = [entity_id]
        param_idx = 1

        if change_type:
            param_idx += 1
            conditions.append(f"change_type = ${param_idx}")
            params.append(change_type)

        where = "WHERE " + " AND ".join(conditions)

        async with self.pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM entity_change_log {where}", *params
            )

            param_idx += 1
            params.append(limit)
            limit_p = param_idx
            param_idx += 1
            params.append(offset)
            offset_p = param_idx

            rows = await conn.fetch(
                f"SELECT * FROM entity_change_log {where} "
                f"ORDER BY created_time DESC LIMIT ${limit_p} OFFSET ${offset_p}",
                *params
            )
            return [self._parse_row(dict(r)) for r in rows], total

    async def get_recent_changes(
        self,
        limit: int = 50,
        change_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent changes across all entities."""
        if change_type:
            rows_raw = await self._fetch(
                "SELECT * FROM entity_change_log WHERE change_type = $1 "
                "ORDER BY created_time DESC LIMIT $2",
                change_type, limit
            )
        else:
            rows_raw = await self._fetch(
                "SELECT * FROM entity_change_log ORDER BY created_time DESC LIMIT $1",
                limit
            )
        return [self._parse_row(r) for r in rows_raw]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_row(row_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure JSONB fields are dicts, not strings."""
        cd = row_dict.get('change_detail')
        if isinstance(cd, str):
            row_dict['change_detail'] = json.loads(cd)
        return row_dict

    async def _fetch(self, sql: str, *args) -> List[Dict[str, Any]]:
        """Simple fetch helper."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]
