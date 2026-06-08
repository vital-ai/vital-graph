"""
Background job manager for import/export operations.

Manages job lifecycle:  create → submit → run → complete/fail/cancel.

Jobs are persisted in the ``import_export_job`` PostgreSQL table and
progress is broadcast via ``SignalManager`` on ``CHANNEL_PROCESS``.

Concurrency is capped (default 2) so the service stays responsive
while long-running I/O tasks are in flight.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Channel used for SignalManager notifications
CHANNEL_IMPORT_EXPORT = "vitalgraph_process"

# Default concurrency limit
DEFAULT_MAX_CONCURRENT = 2


@dataclass
class JobRecord:
    """In-memory mirror of an import_export_job row."""
    job_id: str
    job_type: str              # 'import' | 'export'
    space_id: str
    graph_uri: Optional[str] = None
    status: str = "created"
    mode: str = "append"
    progress_pct: float = 0.0
    records_done: int = 0
    records_total: Optional[int] = None
    file_s3_key: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_format: Optional[str] = None
    config: Optional[Dict] = None
    checkpoint_offset: int = 0
    checkpoint_batch: int = 0
    error_message: Optional[str] = None
    created_by: Optional[str] = None


class ImportExportJobManager:
    """Manages background import/export jobs.

    Usage (inside the FastAPI app)::

        manager = ImportExportJobManager(pool, signal_manager)
        job_id = await manager.create_job("import", space_id, ...)
        await manager.start_job(job_id)
        status = await manager.get_job(job_id)
        await manager.cancel_job(job_id)
    """

    def __init__(
        self,
        pool,
        signal_manager=None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ):
        self._pool = pool
        self._signal = signal_manager
        self._max_concurrent = max_concurrent
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Job CRUD (DB)
    # ------------------------------------------------------------------

    async def create_job(
        self,
        job_type: str,
        space_id: str,
        graph_uri: Optional[str] = None,
        mode: str = "append",
        file_s3_key: Optional[str] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_format: Optional[str] = None,
        config: Optional[Dict] = None,
        created_by: Optional[str] = None,
    ) -> str:
        """Insert a new job row and return its UUID."""
        job_id = str(uuid.uuid4())
        config_json = json.dumps(config) if config else None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO import_export_job
                    (job_id, job_type, space_id, graph_uri, mode,
                     file_s3_key, file_name, file_size, file_format,
                     config, created_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                job_id, job_type, space_id, graph_uri, mode,
                file_s3_key, file_name, file_size, file_format,
                config_json, created_by,
            )

        logger.info("Created %s job %s for space=%s graph=%s",
                     job_type, job_id, space_id, graph_uri)
        return job_id

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single job as a dict (or None)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM import_export_job WHERE job_id = $1", job_id)
        if row is None:
            return None
        return dict(row)

    async def list_jobs(
        self,
        space_id: Optional[str] = None,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        clauses = []
        params: List[Any] = []
        idx = 1

        if space_id:
            clauses.append(f"space_id = ${idx}")
            params.append(space_id)
            idx += 1
        if status:
            clauses.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if job_type:
            clauses.append(f"job_type = ${idx}")
            params.append(job_type)
            idx += 1

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = (
            f"SELECT * FROM import_export_job {where} "
            f"ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}"
        )
        params.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job row. Cancels first if running."""
        if job_id in self._running_tasks:
            await self.cancel_job(job_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM import_export_job WHERE job_id = $1", job_id)
        return result == "DELETE 1"

    # ------------------------------------------------------------------
    # Job status updates (DB)
    # ------------------------------------------------------------------

    # Columns that should use NOW() instead of a parameter value
    _TIMESTAMP_COLS = frozenset({'started_at', 'completed_at'})

    async def _update_status(self, job_id: str, status: str, **kwargs) -> None:
        """Update job status and optional extra fields.

        Timestamp columns (started_at, completed_at) are set to NOW()
        automatically when included in kwargs (value is ignored).
        """
        sets = ["status = $2", "updated_at = NOW()"]
        params: List[Any] = [job_id, status]
        idx = 3

        for key, val in kwargs.items():
            if key in self._TIMESTAMP_COLS:
                sets.append(f"{key} = NOW()")
            else:
                sets.append(f"{key} = ${idx}")
                params.append(val)
                idx += 1

        sql = f"UPDATE import_export_job SET {', '.join(sets)} WHERE job_id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

        # Broadcast progress via SignalManager
        await self._notify(job_id, status)

    async def _update_progress(
        self,
        job_id: str,
        progress_pct: float,
        records_done: int,
        records_total: Optional[int] = None,
        checkpoint_offset: int = 0,
        checkpoint_batch: int = 0,
    ) -> None:
        """Update progress columns without changing status."""
        sets = [
            "progress_pct = $2",
            "records_done = $3",
            "checkpoint_offset = $4",
            "checkpoint_batch = $5",
            "updated_at = NOW()",
        ]
        params: List[Any] = [job_id, progress_pct, records_done,
                             checkpoint_offset, checkpoint_batch]
        if records_total is not None:
            sets.append("records_total = $6")
            params.append(records_total)

        sql = f"UPDATE import_export_job SET {', '.join(sets)} WHERE job_id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def _notify(self, job_id: str, status: str) -> None:
        """Send a SignalManager notification for this job."""
        if self._signal is None:
            return
        try:
            payload = json.dumps({
                "type": "import_export",
                "job_id": job_id,
                "status": status,
                "timestamp": str(time.time()),
            })
            await self._signal._send_notification(CHANNEL_IMPORT_EXPORT, payload)
        except Exception as e:
            logger.warning("Failed to send job notification: %s", e)

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------

    async def start_job(self, job_id: str, file_path: Optional[str] = None) -> bool:
        """Start a job in the background.

        Args:
            job_id: UUID of the job.
            file_path: Local path to the import file (for import jobs).
                       For REST-driven imports, this is the path where the
                       S3 file was downloaded to.

        Returns:
            True if the job was started, False if at capacity or invalid.
        """
        if len(self._running_tasks) >= self._max_concurrent:
            logger.warning("Cannot start job %s: at max concurrency (%d)",
                           job_id, self._max_concurrent)
            return False

        job = await self.get_job(job_id)
        if job is None:
            logger.error("Job %s not found", job_id)
            return False
        if job['status'] not in ('created', 'cancelled', 'failed'):
            logger.warning("Job %s has status %s, cannot start",
                           job_id, job['status'])
            return False

        cancel_event = asyncio.Event()
        self._cancel_events[job_id] = cancel_event

        task = asyncio.create_task(
            self._run_job(job_id, job, file_path, cancel_event))
        self._running_tasks[job_id] = task

        # Remove from tracking when done
        task.add_done_callback(lambda t: self._cleanup_task(job_id))

        await self._update_status(job_id, "pending")
        return True

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        if job_id in self._cancel_events:
            self._cancel_events[job_id].set()
            logger.info("Cancel signal sent to job %s", job_id)
            return True

        # Not running — just mark as cancelled if eligible
        job = await self.get_job(job_id)
        if job and job['status'] in ('created', 'pending'):
            await self._update_status(job_id, "cancelled")
            return True
        return False

    async def restart_job(self, job_id: str, file_path: Optional[str] = None) -> bool:
        """Restart a cancelled/failed job from its last checkpoint."""
        job = await self.get_job(job_id)
        if job is None:
            return False
        if job['status'] not in ('cancelled', 'failed'):
            logger.warning("Job %s has status %s, cannot restart",
                           job_id, job['status'])
            return False
        return await self.start_job(job_id, file_path)

    def _cleanup_task(self, job_id: str) -> None:
        """Remove task and cancel event from tracking."""
        self._running_tasks.pop(job_id, None)
        self._cancel_events.pop(job_id, None)

    # ------------------------------------------------------------------
    # Internal: run a job
    # ------------------------------------------------------------------

    async def _run_job(
        self,
        job_id: str,
        job: Dict[str, Any],
        file_path: Optional[str],
        cancel_event: asyncio.Event,
    ) -> None:
        """Execute an import or export job."""
        try:
            await self._update_status(job_id, "running", started_at=True)

            if job['job_type'] == 'import':
                result = await self._run_import(job_id, job, file_path, cancel_event)
            elif job['job_type'] == 'export':
                result = await self._run_export(job_id, job, file_path, cancel_event)
            else:
                raise ValueError(f"Unknown job type: {job['job_type']}")

            if result.get("cancelled"):
                await self._update_status(
                    job_id, "cancelled",
                    checkpoint_offset=result.get("checkpoint_offset", 0),
                    checkpoint_batch=result.get("checkpoint_batch", 0),
                )
            elif result.get("success"):
                await self._update_status(
                    job_id, "completed",
                    progress_pct=100.0,
                    records_done=result.get("quads", result.get("records", 0)),
                    completed_at=True,
                )
            else:
                await self._update_status(
                    job_id, "failed",
                    error_message=result.get("error", "Unknown error"),
                )

        except Exception as e:
            logger.exception("Job %s failed with exception", job_id)
            await self._update_status(
                job_id, "failed",
                error_message=str(e),
            )

    async def _run_import(
        self,
        job_id: str,
        job: Dict[str, Any],
        file_path: Optional[str],
        cancel_event: asyncio.Event,
    ) -> Dict[str, Any]:
        """Execute an import job."""
        from vitalgraph.endpoint.impl.data_import_impl import ImportEngine

        if not file_path:
            return {"success": False, "error": "No file_path provided for import"}

        engine = ImportEngine(self._pool)
        config = job.get('config') or {}
        if isinstance(config, str):
            config = json.loads(config)
        batch_size = config.get('batch_size', 5_000)
        mode = job.get('mode', 'append')
        checkpoint_offset = job.get('checkpoint_offset', 0) or 0

        def progress_cb(p):
            # Fire-and-forget progress update
            asyncio.create_task(self._update_progress(
                job_id,
                progress_pct=min(
                    (p.records_done / p.records_total * 100) if p.records_total else 0,
                    99.9,
                ),
                records_done=p.records_done,
                records_total=p.records_total if p.records_total else None,
                checkpoint_offset=p.bytes_done,
                checkpoint_batch=p.batch_number,
            ))

        # Dispatch by file format
        fmt = job.get('file_format', 'nt')
        common_kwargs = dict(
            space_id=job['space_id'],
            graph_uri=job.get('graph_uri') or f"urn:{job['space_id']}",
            file_path=file_path,
            batch_size=batch_size,
            mode=mode,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            checkpoint_offset=checkpoint_offset,
        )

        if fmt == 'jsonl':
            return await engine.import_jsonl_quads_incremental(**common_kwargs)
        elif fmt == 'vital':
            return await engine.import_vital_block_incremental(**common_kwargs)
        else:
            return await engine.import_ntriples_incremental(**common_kwargs)

    async def _run_export(
        self,
        job_id: str,
        job: Dict[str, Any],
        file_path: Optional[str],
        cancel_event: asyncio.Event,
    ) -> Dict[str, Any]:
        """Execute an export job."""
        from vitalgraph.endpoint.impl.data_export_impl import ExportEngine

        if not file_path:
            return {"success": False, "error": "No output file_path provided for export"}

        engine = ExportEngine(self._pool)
        config = job.get('config') or {}
        if isinstance(config, str):
            config = json.loads(config)
        batch_size = config.get('batch_size', 50_000)
        fmt = job.get('file_format', 'nt')
        compress = config.get('compress', False)

        def progress_cb(p):
            asyncio.create_task(self._update_progress(
                job_id,
                progress_pct=min(
                    (p.records_done / p.records_total * 100) if p.records_total else 0,
                    99.9,
                ),
                records_done=p.records_done,
                records_total=p.records_total if p.records_total else None,
            ))

        common_kwargs = dict(
            space_id=job['space_id'],
            output_path=file_path,
            graph_uri=job.get('graph_uri'),
            batch_size=batch_size,
            compress=compress,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

        if fmt == 'jsonl':
            return await engine.export_jsonl_quads(**common_kwargs)
        elif fmt == 'vital':
            entity_type_uri = config.get('entity_type_uri')
            return await engine.export_vital_block(
                **common_kwargs, entity_type_uri=entity_type_uri)
        elif fmt == 'nq':
            return await engine.export_nquads(**common_kwargs)
        else:
            return await engine.export_ntriples(**common_kwargs)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel all running jobs and wait for them to finish."""
        for job_id in list(self._cancel_events):
            self._cancel_events[job_id].set()

        tasks = list(self._running_tasks.values())
        if tasks:
            logger.info("Waiting for %d jobs to finish...", len(tasks))
            await asyncio.gather(*tasks, return_exceptions=True)

        self._running_tasks.clear()
        self._cancel_events.clear()
        logger.info("ImportExportJobManager shut down")
