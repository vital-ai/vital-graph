"""
Process Tracker — CRUD operations on the global `process` table.

Tracks long-running operations (ANALYZE, VACUUM, import, export, etc.)
with status, progress, timing, and error information.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProcessTracker:
    """CRUD interface for the global ``process`` table.

    All methods are async and expect an asyncpg-compatible connection or pool.
    """

    def __init__(self, pool):
        """
        Args:
            pool: asyncpg connection pool.
        """
        self._pool = pool

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_process(
        self,
        process_type: str,
        process_subtype: Optional[str] = None,
        instance_id: Optional[str] = None,
        status: str = "pending",
    ) -> str:
        """Insert a new process record and return its UUID.

        Args:
            process_type: E.g. 'analyze', 'vacuum', 'import', 'export'.
            process_subtype: E.g. space_id or 'space_id/graph_id'.
            instance_id: ECS task ID or hostname of the owning instance.
            status: Initial status (default 'pending').

        Returns:
            The generated process_id as a string.
        """
        process_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO process
                    (process_id, process_type, process_subtype, status, instance_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, now(), now())
                """,
                uuid.UUID(process_id),
                process_type,
                process_subtype,
                status,
                instance_id,
            )
        logger.debug("Created process %s type=%s subtype=%s", process_id, process_type, process_subtype)
        return process_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_process(self, process_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single process record by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM process WHERE process_id = $1",
                uuid.UUID(process_id),
            )
        return dict(row) if row else None

    async def list_processes(
        self,
        process_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List process records with optional filters.

        Args:
            process_type: Filter by process type.
            status: Filter by status.
            limit: Max records to return.
            offset: Pagination offset.

        Returns:
            List of process record dicts.
        """
        conditions = []
        params: list = []
        idx = 1

        if process_type is not None:
            conditions.append(f"process_type = ${idx}")
            params.append(process_type)
            idx += 1
        if status is not None:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        params.append(limit)
        params.append(offset)

        query = f"""
            SELECT * FROM process
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def mark_running(
        self,
        process_id: str,
        instance_id: Optional[str] = None,
    ) -> None:
        """Transition a process to 'running'."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE process
                SET status = 'running', started_at = now(), updated_at = now(),
                    instance_id = COALESCE($2, instance_id)
                WHERE process_id = $1
                """,
                uuid.UUID(process_id),
                instance_id,
            )

    async def mark_completed(
        self,
        process_id: str,
        result_details: Optional[Dict[str, Any]] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        """Transition a process to 'completed'."""
        import json
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE process
                SET status = 'completed', completed_at = now(), updated_at = now(),
                    progress_percent = 100.0,
                    progress_message = COALESCE($2, progress_message),
                    result_details = COALESCE($3::jsonb, result_details)
                WHERE process_id = $1
                """,
                uuid.UUID(process_id),
                progress_message,
                json.dumps(result_details) if result_details else None,
            )

    async def mark_failed(
        self,
        process_id: str,
        error_message: str,
        result_details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Transition a process to 'failed'."""
        import json
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE process
                SET status = 'failed', completed_at = now(), updated_at = now(),
                    error_message = $2,
                    result_details = COALESCE($3::jsonb, result_details)
                WHERE process_id = $1
                """,
                uuid.UUID(process_id),
                error_message,
                json.dumps(result_details) if result_details else None,
            )

    async def update_progress(
        self,
        process_id: str,
        progress_percent: float,
        progress_message: Optional[str] = None,
    ) -> None:
        """Update progress on a running process."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE process
                SET progress_percent = $2, updated_at = now(),
                    progress_message = COALESCE($3, progress_message)
                WHERE process_id = $1
                """,
                uuid.UUID(process_id),
                progress_percent,
                progress_message,
            )

    # ------------------------------------------------------------------
    # Delete / cleanup
    # ------------------------------------------------------------------

    async def cleanup_old_processes(self, retention_days: int = 30) -> int:
        """Delete process records older than retention_days.

        Args:
            retention_days: Delete records with created_at older than this many days.

        Returns:
            Number of rows deleted.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM process WHERE created_at < now() - $1::interval",
                timedelta(days=retention_days),
            )
        # asyncpg returns 'DELETE N'
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.info("Cleaned up %d process records older than %d days", count, retention_days)
        return count
