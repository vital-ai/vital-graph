"""Vector Indexes REST Endpoint

REST API for managing per-space vector indexes (the ``{space}_vector_index``
registry) and their backing data tables (``{space}_vec_{index_name}``).

Routes (all under /api/vector-indexes):
    GET    /          — list indexes (or get single if index_name provided)
    POST   /          — create index (registers + creates data table)
    DELETE /          — delete index (drops data table + registry row)
    POST   /reindex   — trigger full re-population of an index
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..auth.role_dependencies import require_space_read, require_space_write
from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from ..model.vector_indexes_model import (
    VectorIndexOut, VectorIndexListResponse,
    CreateVectorIndexRequest, ReindexRequest, ReindexResponse,
    VectorEntry, VectorUpsertRequest, VectorUpsertResponse,
    VectorGetOut, VectorGetResponse,
    ReindexJobStatus, ReindexJobListResponse,
)

logger = logging.getLogger(__name__)

VALID_DISTANCE_METRICS = {"cosine", "l2", "inner_product"}
VALID_PROVIDERS = {"vitalsigns", "openai", "cohere"}

# Maximum number of completed/failed reindex jobs to keep in memory per instance
_MAX_REINDEX_HISTORY = 100


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

class VectorIndexesEndpoint:
    """REST endpoint for vector index management."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.schema = SparqlSQLSchema()
        self.router = APIRouter()
        # In-memory reindex job registry: job_id → ReindexJobStatus
        self._reindex_jobs: OrderedDict[str, ReindexJobStatus] = OrderedDict()
        self._setup_routes()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    async def _acquire(self):
        """Acquire a connection from the pool."""
        db_impl = self.app_impl.db_impl
        if db_impl is None or not getattr(db_impl, "connection_pool", None):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not available",
            )
        return await db_impl.connection_pool.acquire()

    async def _release(self, conn):
        """Release the connection back to the pool."""
        try:
            db_impl = self.app_impl.db_impl
            if db_impl and db_impl.connection_pool:
                await db_impl.connection_pool.release(conn)
        except Exception:
            logger.exception("Error releasing connection")

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    async def list_indexes(self, space_id: str, current_user: Dict):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            table = f"{space_id}_vector_index"
            rows = await conn.fetch(
                f"SELECT * FROM {table} ORDER BY index_name"
            )
            indexes = []
            for row in rows:
                idx_name = row["index_name"]
                vec_table = self.schema.vec_table_name(space_id, idx_name)
                try:
                    count_row = await conn.fetchrow(
                        f"SELECT COUNT(*) AS cnt FROM {vec_table}"
                    )
                    count = count_row["cnt"] if count_row else 0
                except Exception:
                    count = None

                indexes.append(VectorIndexOut(
                    index_id=row["index_id"],
                    index_name=idx_name,
                    dimensions=row["dimensions"],
                    distance_metric=row["distance_metric"],
                    provider=row["provider"],
                    model_name=row.get("model_name"),
                    provider_config=_parse_provider_config(row.get("provider_config")),
                    description=row.get("description"),
                    created_time=str(row["created_time"]) if row.get("created_time") else None,
                    embedding_count=count,
                ))
            return VectorIndexListResponse(indexes=indexes, total_count=len(indexes))
        finally:
            await self._release(conn)

    async def create_index(
        self, space_id: str, body: CreateVectorIndexRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)

        if body.distance_metric not in VALID_DISTANCE_METRICS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid distance_metric '{body.distance_metric}'. "
                       f"Must be one of: {', '.join(sorted(VALID_DISTANCE_METRICS))}",
            )

        conn = await self._acquire()
        try:
            table = f"{space_id}_vector_index"

            # Check for duplicate
            existing = await conn.fetchrow(
                f"SELECT index_id FROM {table} WHERE index_name = $1",
                body.index_name,
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Vector index '{body.index_name}' already exists",
                )

            # Insert registry row
            row = await conn.fetchrow(
                f"""INSERT INTO {table}
                    (index_name, dimensions, distance_metric, provider,
                     model_name, provider_config, description)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                    RETURNING *""",
                body.index_name,
                body.dimensions,
                body.distance_metric,
                body.provider,
                body.model_name,
                _jsonb(body.provider_config),
                body.description,
            )

            # Drop any stale data table (e.g. from a previous partially-failed delete)
            # before creating the new one — prevents IF NOT EXISTS from keeping
            # an old table with the wrong vector dimensions.
            drop_stmts = self.schema.drop_vector_data_table_sql(space_id, body.index_name)
            for stmt in drop_stmts:
                await conn.execute(stmt)

            # Create the backing data table + indexes
            stmts = self.schema.create_vector_data_table_sql(
                space_id, body.index_name, body.dimensions, body.distance_metric,
            )
            for stmt in stmts:
                await conn.execute(stmt)

            logger.info(
                "Created vector index '%s' for space '%s' (%d dims, %s, %s)",
                body.index_name, space_id, body.dimensions,
                body.distance_metric, body.provider,
            )

            return VectorIndexOut(
                index_id=row["index_id"],
                index_name=row["index_name"],
                dimensions=row["dimensions"],
                distance_metric=row["distance_metric"],
                provider=row["provider"],
                model_name=row.get("model_name"),
                provider_config=_parse_provider_config(row.get("provider_config")),
                description=row.get("description"),
                created_time=str(row["created_time"]) if row.get("created_time") else None,
                embedding_count=0,
            )
        finally:
            await self._release(conn)

    async def get_index(self, space_id: str, index_name: str, current_user: Dict):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            table = f"{space_id}_vector_index"
            row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE index_name = $1",
                index_name,
            )
            if row is None:
                raise HTTPException(status_code=404, detail=f"Vector index '{index_name}' not found")

            vec_table = self.schema.vec_table_name(space_id, index_name)
            try:
                count_row = await conn.fetchrow(f"SELECT COUNT(*) AS cnt FROM {vec_table}")
                count = count_row["cnt"] if count_row else 0
            except Exception:
                count = None

            return VectorIndexOut(
                index_id=row["index_id"],
                index_name=row["index_name"],
                dimensions=row["dimensions"],
                distance_metric=row["distance_metric"],
                provider=row["provider"],
                model_name=row.get("model_name"),
                provider_config=_parse_provider_config(row.get("provider_config")),
                description=row.get("description"),
                created_time=str(row["created_time"]) if row.get("created_time") else None,
                embedding_count=count,
            )
        finally:
            await self._release(conn)

    async def delete_index(self, space_id: str, index_name: str, current_user: Dict):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            table = f"{space_id}_vector_index"

            # Verify exists
            row = await conn.fetchrow(
                f"SELECT index_id FROM {table} WHERE index_name = $1",
                index_name,
            )
            if row is None:
                raise HTTPException(status_code=404, detail=f"Vector index '{index_name}' not found")

            # Drop backing data table first
            drop_stmts = self.schema.drop_vector_data_table_sql(space_id, index_name)
            for stmt in drop_stmts:
                await conn.execute(stmt)

            # Delete dependent search mappings
            search_mapping_table = f"{space_id}_search_mapping"
            search_mapping_prop_table = f"{space_id}_search_mapping_property"
            try:
                # Delete mapping properties first, then mappings
                await conn.execute(
                    f"DELETE FROM {search_mapping_prop_table} WHERE mapping_id IN "
                    f"(SELECT mapping_id FROM {search_mapping_table} WHERE index_name = $1)",
                    index_name,
                )
                await conn.execute(
                    f"DELETE FROM {search_mapping_table} WHERE index_name = $1",
                    index_name,
                )
            except Exception as e:
                logger.warning("Could not clean search mappings for '%s': %s", index_name, e)

            # Delete registry row
            await conn.execute(
                f"DELETE FROM {table} WHERE index_name = $1",
                index_name,
            )

            # Evict cached provider instance so a re-created index with a
            # different provider doesn't reuse the old embedder.
            from ..vectorization.registry import _provider_cache
            cache_key = f"{space_id}:{index_name}"
            _provider_cache.pop(cache_key, None)

            logger.info("Deleted vector index '%s' for space '%s'", index_name, space_id)

            return {"message": "Vector index deleted", "index_name": index_name}
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Direct vector upsert / get
    # ------------------------------------------------------------------

    async def upsert_vectors(
        self, space_id: str, index_name: str, body: VectorUpsertRequest, current_user: Dict,
    ):
        """Upsert pre-computed vectors into a vector index."""
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            # Verify index exists and check dimensions
            table = f"{space_id}_vector_index"
            idx_row = await conn.fetchrow(
                f"SELECT dimensions FROM {table} WHERE index_name = $1", index_name,
            )
            if idx_row is None:
                raise HTTPException(status_code=404, detail=f"Vector index '{index_name}' not found")

            expected_dims = idx_row["dimensions"]
            vec_table = self.schema.vec_table_name(space_id, index_name)
            term_table = f"{space_id}_term"

            ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
            upserted = 0
            errors = []

            for entry in body.vectors:
                if len(entry.embedding) != expected_dims:
                    errors.append(
                        f"{entry.subject_uri}: expected {expected_dims} dims, got {len(entry.embedding)}"
                    )
                    continue

                subject_uuid = uuid.uuid5(ns, f"{entry.subject_uri}\x00U")
                context_uuid = uuid.uuid5(ns, f"{entry.graph_uri}\x00U")
                vec_str = "[" + ",".join(str(v) for v in entry.embedding) + "]"

                try:
                    # Ensure URIs are in the term table so get_vectors can
                    # resolve UUIDs back to human-readable URIs (issue #008)
                    await conn.execute(
                        f"INSERT INTO {term_table} (term_uuid, term_text, term_type) "
                        f"VALUES ($1, $2, 'U') ON CONFLICT DO NOTHING",
                        subject_uuid, entry.subject_uri,
                    )
                    await conn.execute(
                        f"INSERT INTO {term_table} (term_uuid, term_text, term_type) "
                        f"VALUES ($1, $2, 'U') ON CONFLICT DO NOTHING",
                        context_uuid, entry.graph_uri,
                    )
                    await conn.execute(
                        f"""INSERT INTO {vec_table}
                            (subject_uuid, context_uuid, embedding, updated_time)
                            VALUES ($1, $2, $3::vector, CURRENT_TIMESTAMP)
                            ON CONFLICT (subject_uuid, context_uuid)
                            DO UPDATE SET embedding = EXCLUDED.embedding,
                                          updated_time = CURRENT_TIMESTAMP""",
                        subject_uuid, context_uuid, vec_str,
                    )
                    upserted += 1
                except Exception as e:
                    errors.append(f"{entry.subject_uri}: {e}")

            return VectorUpsertResponse(
                message=f"Upserted {upserted} vector(s)",
                upserted=upserted,
                errors=errors[:20],
            )
        finally:
            await self._release(conn)

    async def get_vectors(
        self, space_id: str, index_name: str, subject_uri: Optional[str],
        graph_uri: Optional[str], current_user: Dict,
        page_size: int = 100, offset: int = 0,
    ):
        """Get stored vectors by subject URI and/or graph URI."""
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            # Verify index exists
            table = f"{space_id}_vector_index"
            idx_row = await conn.fetchrow(
                f"SELECT index_name FROM {table} WHERE index_name = $1", index_name,
            )
            if idx_row is None:
                raise HTTPException(status_code=404, detail=f"Vector index '{index_name}' not found")

            vec_table = self.schema.vec_table_name(space_id, index_name)
            term_table = f"{space_id}_term"
            ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

            conditions = []
            params = []
            param_idx = 1

            if subject_uri:
                subject_uuid = uuid.uuid5(ns, f"{subject_uri}\x00U")
                conditions.append(f"v.subject_uuid = ${param_idx}")
                params.append(subject_uuid)
                param_idx += 1

            if graph_uri:
                context_uuid = uuid.uuid5(ns, f"{graph_uri}\x00U")
                conditions.append(f"v.context_uuid = ${param_idx}")
                params.append(context_uuid)
                param_idx += 1

            if not conditions:
                raise HTTPException(
                    status_code=400,
                    detail="At least one of subject_uri or graph_uri is required",
                )

            where = " AND ".join(conditions)

            # True total count (not capped by LIMIT)
            count_row = await conn.fetchrow(
                f"SELECT COUNT(*) AS cnt FROM {vec_table} v WHERE {where}",
                *params,
            )
            true_total = count_row["cnt"] if count_row else 0

            rows = await conn.fetch(
                f"SELECT v.subject_uuid, v.context_uuid, "
                f"       v.embedding::text AS embedding_text, "
                f"       v.updated_time, "
                f"       s.term_text AS subject_text, "
                f"       c.term_text AS context_text "
                f"FROM {vec_table} v "
                f"LEFT JOIN {term_table} s ON s.term_uuid = v.subject_uuid "
                f"LEFT JOIN {term_table} c ON c.term_uuid = v.context_uuid "
                f"WHERE {where} "
                f"ORDER BY v.updated_time DESC "
                f"LIMIT {page_size} OFFSET {offset}",
                *params,
            )

            vectors = []
            for row in rows:
                emb_text = row["embedding_text"]
                # Parse pgvector text format "[0.1,0.2,...]" → list of floats
                emb_list = [float(x) for x in emb_text.strip("[]").split(",")] if emb_text else []
                vectors.append(VectorGetOut(
                    subject_uri=row["subject_text"] or str(row["subject_uuid"]),
                    graph_uri=row["context_text"] or str(row["context_uuid"]),
                    embedding=emb_list,
                    updated_time=str(row["updated_time"]) if row["updated_time"] else None,
                ))

            return VectorGetResponse(
                vectors=vectors, total_count=true_total,
                page_size=page_size, offset=offset,
            )
        finally:
            await self._release(conn)

    async def reindex(
        self, space_id: str, index_name: str, body: ReindexRequest, current_user: Dict,
    ):
        """Start a reindex as a background task and return immediately."""
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            # Verify index exists (fail fast before spawning background work)
            table = f"{space_id}_vector_index"
            idx_row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE index_name = $1",
                index_name,
            )
            if idx_row is None:
                raise HTTPException(status_code=404, detail=f"Vector index '{index_name}' not found")

            provider_name = idx_row["provider"]
            provider_config = _parse_provider_config(idx_row.get("provider_config"))
        finally:
            await self._release(conn)

        # Build context UUID from graph URI
        ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        context_uuid = uuid.uuid5(ns, f"{body.graph_uri}\x00U")

        # Create tracked job
        job_id = uuid.uuid4().hex[:16]
        job_status = ReindexJobStatus(
            job_id=job_id,
            index_name=index_name,
            space_id=space_id,
            status="running",
            started_at=str(datetime.utcnow()),
        )
        self._reindex_jobs[job_id] = job_status
        # Evict oldest entries if history is too large
        while len(self._reindex_jobs) > _MAX_REINDEX_HISTORY:
            self._reindex_jobs.popitem(last=False)

        # Spawn background task
        asyncio.ensure_future(self._run_reindex(
            job_id, space_id, index_name, context_uuid, body,
            provider_name, provider_config,
        ))

        return ReindexResponse(
            message=f"Reindex started (job_id={job_id})",
            index_name=index_name,
            job_id=job_id,
        )

    async def get_reindex_status(
        self, space_id: str, current_user: Dict,
        job_id: Optional[str] = None,
        index_name: Optional[str] = None,
    ) -> ReindexJobListResponse:
        """Get status of reindex background tasks."""
        require_space_read(current_user, space_id)
        jobs = []
        for jid, js in self._reindex_jobs.items():
            if js.space_id != space_id:
                continue
            if job_id and jid != job_id:
                continue
            if index_name and js.index_name != index_name:
                continue
            jobs.append(js)
        return ReindexJobListResponse(jobs=jobs, total_count=len(jobs))

    async def _run_reindex(
        self, job_id: str, space_id: str, index_name: str, context_uuid,
        body: ReindexRequest, provider_name: str, provider_config: Optional[Dict],
    ):
        """Background worker: populate the vector index."""
        job_status = self._reindex_jobs.get(job_id)
        conn = await self._acquire()
        try:
            from ..vectorization.vector_populator import populate_index

            stats = await populate_index(
                conn=conn,
                space_id=space_id,
                index_name=index_name,
                context_uuid=context_uuid,
                type_uri=body.type_uri,
                mapping_type=body.mapping_type,
                provider_name=provider_name,
                provider_config=provider_config,
                batch_size=body.batch_size,
            )
            logger.info(
                "Reindex complete: %s/%s — %d processed, %d stored (%.1fs)",
                space_id, index_name,
                stats.subjects_processed, stats.embeddings_stored,
                stats.elapsed_seconds,
            )
            if job_status:
                job_status.status = "completed"
                job_status.subjects_processed = stats.subjects_processed
                job_status.embeddings_stored = stats.embeddings_stored
                job_status.subjects_skipped = stats.subjects_skipped
                job_status.elapsed_seconds = stats.elapsed_seconds
                job_status.completed_at = str(datetime.utcnow())
        except Exception as e:
            logger.exception("Reindex failed: %s/%s", space_id, index_name)
            if job_status:
                job_status.status = "failed"
                job_status.error_message = str(e)[:2000]
                job_status.completed_at = str(datetime.utcnow())
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/vector-indexes",
            response_model=VectorIndexListResponse,
            tags=["Vector Indexes"],
            summary="List or Get Vector Indexes",
            description="List all indexes for a space, or get a single index if index_name is provided",
        )
        async def list_route(
            space_id: str = Query(..., description="Space ID"),
            index_name: Optional[str] = Query(None, description="Index name (returns single index if provided)"),
            current_user: Dict = Depends(auth),
        ):
            if index_name:
                idx = await self.get_index(space_id, index_name, current_user)
                return VectorIndexListResponse(indexes=[idx], total_count=1)
            return await self.list_indexes(space_id, current_user)

        @self.router.post(
            "/vector-indexes",
            response_model=VectorIndexOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Vector Indexes"],
            summary="Create Vector Index",
            description="Register a new vector index and create its backing data table",
        )
        async def create_route(
            space_id: str = Query(..., description="Space ID"),
            body: CreateVectorIndexRequest = None,
            current_user: Dict = Depends(auth),
        ):
            return await self.create_index(space_id, body, current_user)

        @self.router.delete(
            "/vector-indexes",
            tags=["Vector Indexes"],
            summary="Delete Vector Index",
            description="Delete a vector index, its data table, and all dependent mappings",
        )
        async def delete_route(
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name to delete"),
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_index(space_id, index_name, current_user)

        @self.router.post(
            "/vector-indexes/reindex",
            response_model=ReindexResponse,
            tags=["Vector Indexes"],
            summary="Reindex Vector Index",
            description="Re-populate all embeddings for a vector index from a specific graph",
        )
        async def reindex_route(
            body: ReindexRequest,
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name to reindex"),
            current_user: Dict = Depends(auth),
        ):
            return await self.reindex(space_id, index_name, body, current_user)

        @self.router.get(
            "/vector-indexes/reindex/status",
            response_model=ReindexJobListResponse,
            tags=["Vector Indexes"],
            summary="Reindex Job Status",
            description="Get status of background reindex tasks. Filter by job_id or index_name.",
        )
        async def reindex_status_route(
            space_id: str = Query(..., description="Space ID"),
            job_id: Optional[str] = Query(None, description="Specific job ID to look up"),
            index_name: Optional[str] = Query(None, description="Filter by index name"),
            current_user: Dict = Depends(auth),
        ):
            return await self.get_reindex_status(space_id, current_user, job_id, index_name)

        @self.router.post(
            "/vector-indexes/vectors",
            response_model=VectorUpsertResponse,
            tags=["Vector Indexes"],
            summary="Upsert Vectors",
            description="Insert or update pre-computed embedding vectors directly",
        )
        async def upsert_vectors_route(
            body: VectorUpsertRequest,
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Target index name"),
            current_user: Dict = Depends(auth),
        ):
            return await self.upsert_vectors(space_id, index_name, body, current_user)

        @self.router.get(
            "/vector-indexes/vectors",
            response_model=VectorGetResponse,
            tags=["Vector Indexes"],
            summary="Get Vectors",
            description="Retrieve stored vectors by subject URI and/or graph URI",
        )
        async def get_vectors_route(
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name"),
            subject_uri: Optional[str] = Query(None, description="Subject URI to look up"),
            graph_uri: Optional[str] = Query(None, description="Graph URI filter"),
            page_size: int = Query(100, ge=1, le=1000, description="Page size"),
            offset: int = Query(0, ge=0, description="Offset"),
            current_user: Dict = Depends(auth),
        ):
            return await self.get_vectors(
                space_id, index_name, subject_uri, graph_uri, current_user,
                page_size=page_size, offset=offset,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonb(val: Optional[Dict]) -> Optional[str]:
    """Convert a dict to a JSON string for asyncpg JSONB parameter."""
    if val is None:
        return None
    import json
    return json.dumps(val)


def _parse_provider_config(val) -> Optional[Dict]:
    """Safely parse a provider_config value from asyncpg (may be dict, str, or None)."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        import json
        return json.loads(val)
    return dict(val)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_vector_indexes_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = VectorIndexesEndpoint(app_impl, auth_dependency)
    return endpoint.router
