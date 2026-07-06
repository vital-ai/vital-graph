"""
Segmentation Job Manager.

Manages the segmentation_jobs table which tracks background document
segmentation work. Uses PostgreSQL as a durable job queue with
SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent dequeuing.

Table: {space_id}_segmentation_jobs
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class SegmentationJobDTO:
    """Represents a row in the segmentation_jobs table."""

    job_id: int
    space_id: str
    graph_id: str
    document_uri: str
    status: str  # pending | in_progress | vectorizing | completed | failed
    attempt_count: int = 0
    segment_count: Optional[int] = None
    segment_method_uri: Optional[str] = None
    max_segment_tokens: Optional[int] = None
    error_message: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("created_at", "updated_at"):
            if d.get(k):
                d[k] = str(d[k])
        return d


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    job_id             SERIAL PRIMARY KEY,
    space_id           VARCHAR(200) NOT NULL,
    graph_id           TEXT NOT NULL,
    document_uri       TEXT NOT NULL,
    status             VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempt_count      INTEGER NOT NULL DEFAULT 0,
    segment_count      INTEGER,
    segment_method_uri VARCHAR(500),
    max_segment_tokens INTEGER,
    error_message      TEXT,
    content_hash       VARCHAR(64),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_INDEXES_SQL = [
    """CREATE INDEX IF NOT EXISTS {table_name}_status_idx
       ON {table_name} (status, created_at) WHERE status IN ('pending', 'failed', 'vectorizing');""",
    """CREATE INDEX IF NOT EXISTS {table_name}_document_idx
       ON {table_name} (document_uri, created_at DESC);""",
    """CREATE INDEX IF NOT EXISTS {table_name}_space_idx
       ON {table_name} (space_id, status);""",
]


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SegmentationJobManager:
    """
    CRUD operations on the segmentation_jobs table.

    ``conn`` must be an asyncpg Connection (or pool-acquired connection).
    All public methods are async.
    """

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self.space_id = space_id
        self._table = f"{space_id}_segmentation_jobs"

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    async def ensure_table(self) -> None:
        """Create the jobs table if it doesn't exist."""
        sql = CREATE_TABLE_SQL.format(table_name=self._table)
        await self.conn.execute(sql)
        for idx_sql in CREATE_INDEXES_SQL:
            await self.conn.execute(idx_sql.format(table_name=self._table))
        logger.debug(f"Ensured segmentation jobs table: {self._table}")

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        graph_id: str,
        document_uri: str,
        segment_method_uri: Optional[str] = None,
        max_segment_tokens: Optional[int] = None,
        content_hash: Optional[str] = None,
    ) -> Optional[int]:
        """
        Enqueue a new segmentation job.

        If a pending/in_progress job already exists for the same document,
        it is superseded: the old one is marked 'cancelled' and a new one
        is created.

        If *content_hash* is provided and the most recent completed job for
        this document already has an identical hash, the enqueue is skipped
        (content unchanged) and ``None`` is returned.

        Returns the new job_id, or None if skipped.
        """
        # Skip if content hasn't changed since last completed segmentation
        if content_hash:
            last_hash = await self.conn.fetchval(
                f"SELECT content_hash FROM {self._table} "
                f"WHERE document_uri = $1 AND status = 'completed' "
                f"ORDER BY created_at DESC LIMIT 1",
                document_uri,
            )
            if last_hash and last_hash == content_hash:
                logger.info(
                    "Skipping segmentation for %s: content unchanged (hash=%s)",
                    document_uri, content_hash[:12],
                )
                return None

        # Cancel any existing pending/in_progress jobs for this document
        cancel_sql = f"""
            UPDATE {self._table}
            SET status = 'cancelled', updated_at = NOW()
            WHERE document_uri = $1 AND status IN ('pending', 'in_progress')
        """
        await self.conn.execute(cancel_sql, document_uri)

        sql = f"""
            INSERT INTO {self._table}
                (space_id, graph_id, document_uri, status,
                 segment_method_uri, max_segment_tokens, content_hash)
            VALUES ($1, $2, $3, 'pending', $4, $5, $6)
            RETURNING job_id
        """
        job_id = await self.conn.fetchval(
            sql, self.space_id, graph_id, document_uri,
            segment_method_uri, max_segment_tokens, content_hash,
        )

        # Wake any LISTEN-ing workers immediately
        try:
            await self.conn.execute(
                f"SELECT pg_notify($1, $2)",
                self._notify_channel,
                str(job_id),
            )
        except Exception as ne:
            logger.debug("pg_notify after enqueue failed (non-critical): %s", ne)

        logger.info(f"Enqueued segmentation job {job_id} for {document_uri}")
        return job_id

    @property
    def _notify_channel(self) -> str:
        """PostgreSQL NOTIFY channel name for this space's jobs."""
        return f"{self.space_id}_seg_jobs"

    @staticmethod
    def compute_content_hash(doc_properties: dict) -> str:
        """Compute a SHA-256 hash over the content fields of a document.

        Uses the same priority order as ``extract_content`` — the hash
        covers whichever content field would actually be segmented.
        """
        parts: list[str] = []
        for key in (
            "kGDocumentExtractedContent",
            "kGDocumentHTMLContent",
            "kGDocumentContent",
        ):
            val = doc_properties.get(key)
            if val and str(val).strip():
                parts.append(str(val).strip())
                break  # same priority as extract_content
        if not parts:
            return ""
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Dequeue (claim next job)
    # ------------------------------------------------------------------

    async def claim_next(self) -> Optional[SegmentationJobDTO]:
        """
        Claim the next pending job using SELECT ... FOR UPDATE SKIP LOCKED.

        Also re-claims failed jobs with attempt_count < 3 that have waited
        long enough (exponential backoff: 1min * 2^attempts).

        Returns the claimed job, or None if no work available.
        """
        sql = f"""
            UPDATE {self._table}
            SET status = 'in_progress', attempt_count = attempt_count + 1, updated_at = NOW()
            WHERE job_id = (
                SELECT job_id FROM {self._table}
                WHERE (
                    status = 'pending'
                    OR (
                        status = 'failed'
                        AND attempt_count < 3
                        AND updated_at + (interval '1 minute' * power(2, attempt_count)) < NOW()
                    )
                )
                ORDER BY
                    CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
                    created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        """
        row = await self.conn.fetchrow(sql)
        if row:
            dto = self._row_to_dto(row)
            logger.info(f"Claimed job {dto.job_id} for {dto.document_uri} (attempt {dto.attempt_count})")
            return dto
        return None

    # ------------------------------------------------------------------
    # Complete / fail
    # ------------------------------------------------------------------

    async def complete(
        self, job_id: int, segment_count: int,
        *, content_hash: Optional[str] = None,
    ) -> None:
        """Mark a job as completed, optionally storing the content hash."""
        if content_hash:
            sql = f"""
                UPDATE {self._table}
                SET status = 'completed', segment_count = $2,
                    content_hash = $3, updated_at = NOW()
                WHERE job_id = $1
            """
            await self.conn.execute(sql, job_id, segment_count, content_hash)
        else:
            sql = f"""
                UPDATE {self._table}
                SET status = 'completed', segment_count = $2, updated_at = NOW()
                WHERE job_id = $1
            """
            await self.conn.execute(sql, job_id, segment_count)
        logger.info(f"Completed job {job_id}: {segment_count} segments")

    async def mark_vectorizing(
        self, job_id: int, segment_count: int,
        *, content_hash: Optional[str] = None,
    ) -> None:
        """Mark a job as 'vectorizing' — segmentation done, embeddings in progress."""
        if content_hash:
            sql = f"""
                UPDATE {self._table}
                SET status = 'vectorizing', segment_count = $2,
                    content_hash = $3, updated_at = NOW()
                WHERE job_id = $1
            """
            await self.conn.execute(sql, job_id, segment_count, content_hash)
        else:
            sql = f"""
                UPDATE {self._table}
                SET status = 'vectorizing', segment_count = $2, updated_at = NOW()
                WHERE job_id = $1
            """
            await self.conn.execute(sql, job_id, segment_count)
        logger.info(f"Job {job_id} → vectorizing ({segment_count} segments)")

    async def vectorization_complete(self, job_id: int) -> None:
        """Transition a 'vectorizing' job to 'completed'."""
        sql = f"""
            UPDATE {self._table}
            SET status = 'completed', updated_at = NOW()
            WHERE job_id = $1 AND status = 'vectorizing'
        """
        await self.conn.execute(sql, job_id)
        logger.info(f"Job {job_id} → completed (vectorization done)")

    async def vectorization_failed(self, job_id: int, error_message: str) -> None:
        """Record vectorization failure but keep 'vectorizing' → 'completed' (non-fatal).

        Vectorization failures are logged but don't fail the job since
        segments are already stored and searchable via FTS/CONTAINS.
        """
        sql = f"""
            UPDATE {self._table}
            SET status = 'completed', error_message = $2, updated_at = NOW()
            WHERE job_id = $1
        """
        await self.conn.execute(sql, job_id, error_message[:2000])
        logger.warning(f"Job {job_id} → completed (vectorization failed: {error_message[:200]})")

    async def fail(self, job_id: int, error_message: str) -> None:
        """Mark a job as failed."""
        sql = f"""
            UPDATE {self._table}
            SET status = 'failed', error_message = $2, updated_at = NOW()
            WHERE job_id = $1
        """
        await self.conn.execute(sql, job_id, error_message[:2000])
        logger.warning(f"Failed job {job_id}: {error_message[:200]}")

    # ------------------------------------------------------------------
    # Status queries
    # ------------------------------------------------------------------

    async def get_job_status(self, document_uri: str) -> Optional[SegmentationJobDTO]:
        """Get the most recent job for a document URI."""
        sql = f"""
            SELECT * FROM {self._table}
            WHERE document_uri = $1
            ORDER BY created_at DESC
            LIMIT 1
        """
        row = await self.conn.fetchrow(sql, document_uri)
        return self._row_to_dto(row) if row else None

    async def get_space_summary(self) -> Dict[str, int]:
        """Get aggregate status counts for all jobs in this space."""
        sql = f"""
            SELECT status, COUNT(*) as cnt
            FROM {self._table}
            WHERE space_id = $1
            GROUP BY status
        """
        rows = await self.conn.fetch(sql, self.space_id)
        return {row["status"]: row["cnt"] for row in rows}

    async def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SegmentationJobDTO]:
        """List jobs with optional status filter."""
        if status:
            sql = f"""
                SELECT * FROM {self._table}
                WHERE space_id = $1 AND status = $2
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
            """
            rows = await self.conn.fetch(sql, self.space_id, status, limit, offset)
        else:
            sql = f"""
                SELECT * FROM {self._table}
                WHERE space_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            rows = await self.conn.fetch(sql, self.space_id, limit, offset)
        return [self._row_to_dto(row) for row in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dto(row) -> SegmentationJobDTO:
        """Convert an asyncpg Record to DTO."""
        return SegmentationJobDTO(
            job_id=row["job_id"],
            space_id=row["space_id"],
            graph_id=row["graph_id"],
            document_uri=row["document_uri"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            segment_count=row.get("segment_count"),
            segment_method_uri=row.get("segment_method_uri"),
            max_segment_tokens=row.get("max_segment_tokens"),
            error_message=row.get("error_message"),
            content_hash=row.get("content_hash"),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
            updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        )
