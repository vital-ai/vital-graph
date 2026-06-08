"""Vector Indexes REST Endpoint

REST API for managing per-space vector indexes (the ``{space}_vector_index``
registry) and their backing data tables (``{space}_vec_{index_name}``).

Routes (all under /api/spaces/{space_id}/vector-indexes):
    GET    /                         — list indexes
    POST   /                         — create index (registers + creates data table)
    GET    /{index_name}             — get index details + row count
    DELETE /{index_name}             — delete index (drops data table + registry row)
    POST   /{index_name}/reindex     — trigger full re-population of an index
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth.role_dependencies import require_space_read, require_space_write
from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)

VALID_DISTANCE_METRICS = {"cosine", "l2", "inner_product"}
VALID_PROVIDERS = {"vitalsigns", "openai", "cohere"}


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class VectorIndexOut(BaseModel):
    index_id: int
    index_name: str
    dimensions: int
    distance_metric: str = "cosine"
    provider: str = "vitalsigns"
    model_name: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    created_time: Optional[str] = None
    embedding_count: Optional[int] = None


class VectorIndexListResponse(BaseModel):
    indexes: List[VectorIndexOut]
    total_count: int


class CreateVectorIndexRequest(BaseModel):
    index_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Lowercase alphanumeric + underscores, e.g. 'entity_default'",
    )
    dimensions: int = Field(..., gt=0, le=16000, description="Embedding dimensions")
    distance_metric: str = Field("cosine", description="cosine | l2 | inner_product")
    provider: str = Field("vitalsigns", description="Vectorization provider name")
    model_name: Optional[str] = Field(None, description="Model name, e.g. 'text-embedding-3-small'")
    provider_config: Optional[Dict[str, Any]] = Field(None, description="Provider-specific config")
    description: Optional[str] = Field(None, description="Human-readable description")


class ReindexRequest(BaseModel):
    graph_uri: str = Field(..., description="Graph URI to re-index")
    mapping_type: Optional[str] = Field(None, description="Filter: kgentity | kgdocument | kgframe | kgslot")
    type_uri: Optional[str] = Field(None, description="Filter: specific KG Type URI")
    batch_size: int = Field(100, ge=1, le=1000, description="Batch size for processing")


class ReindexResponse(BaseModel):
    message: str
    index_name: str
    subjects_processed: int = 0
    embeddings_stored: int = 0
    subjects_skipped: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = []


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
                    provider_config=dict(row["provider_config"]) if row.get("provider_config") else None,
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
                provider_config=dict(row["provider_config"]) if row.get("provider_config") else None,
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
                provider_config=dict(row["provider_config"]) if row.get("provider_config") else None,
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

            # Delete dependent mappings (CASCADE would handle mapping_property)
            mapping_table = f"{space_id}_vector_mapping"
            await conn.execute(
                f"DELETE FROM {mapping_table} WHERE index_name = $1",
                index_name,
            )

            # Delete registry row
            await conn.execute(
                f"DELETE FROM {table} WHERE index_name = $1",
                index_name,
            )

            logger.info("Deleted vector index '%s' for space '%s'", index_name, space_id)

            return {"message": "Vector index deleted", "index_name": index_name}
        finally:
            await self._release(conn)

    async def reindex(
        self, space_id: str, index_name: str, body: ReindexRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            # Verify index exists and fetch provider info
            table = f"{space_id}_vector_index"
            idx_row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE index_name = $1",
                index_name,
            )
            if idx_row is None:
                raise HTTPException(status_code=404, detail=f"Vector index '{index_name}' not found")

            # Build context UUID from graph URI
            ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
            context_uuid = uuid.uuid5(ns, body.graph_uri)

            # Import here to avoid circular imports
            from ..vectorization.vector_populator import populate_index

            stats = await populate_index(
                conn=conn,
                space_id=space_id,
                index_name=index_name,
                context_uuid=context_uuid,
                type_uri=body.type_uri,
                mapping_type=body.mapping_type,
                provider_name=idx_row["provider"],
                provider_config=dict(idx_row["provider_config"]) if idx_row.get("provider_config") else None,
                batch_size=body.batch_size,
            )

            return ReindexResponse(
                message="Reindex complete",
                index_name=index_name,
                subjects_processed=stats.subjects_processed,
                embeddings_stored=stats.embeddings_stored,
                subjects_skipped=stats.subjects_skipped,
                elapsed_seconds=round(stats.elapsed_seconds, 2),
                errors=stats.errors[:20],
            )
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/spaces/{space_id}/vector-indexes",
            response_model=VectorIndexListResponse,
            tags=["Vector Indexes"],
            summary="List Vector Indexes",
            description="List all registered vector indexes for a space with embedding counts",
        )
        async def list_route(
            space_id: str,
            current_user: Dict = Depends(auth),
        ):
            return await self.list_indexes(space_id, current_user)

        @self.router.post(
            "/spaces/{space_id}/vector-indexes",
            response_model=VectorIndexOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Vector Indexes"],
            summary="Create Vector Index",
            description="Register a new vector index and create its backing data table",
        )
        async def create_route(
            space_id: str,
            body: CreateVectorIndexRequest,
            current_user: Dict = Depends(auth),
        ):
            return await self.create_index(space_id, body, current_user)

        @self.router.get(
            "/spaces/{space_id}/vector-indexes/{index_name}",
            response_model=VectorIndexOut,
            tags=["Vector Indexes"],
            summary="Get Vector Index",
            description="Get details for a specific vector index including embedding count",
        )
        async def get_route(
            space_id: str,
            index_name: str,
            current_user: Dict = Depends(auth),
        ):
            return await self.get_index(space_id, index_name, current_user)

        @self.router.delete(
            "/spaces/{space_id}/vector-indexes/{index_name}",
            tags=["Vector Indexes"],
            summary="Delete Vector Index",
            description="Delete a vector index, its data table, and all dependent mappings",
        )
        async def delete_route(
            space_id: str,
            index_name: str,
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_index(space_id, index_name, current_user)

        @self.router.post(
            "/spaces/{space_id}/vector-indexes/{index_name}/reindex",
            response_model=ReindexResponse,
            tags=["Vector Indexes"],
            summary="Reindex Vector Index",
            description="Re-populate all embeddings for a vector index from a specific graph",
        )
        async def reindex_route(
            space_id: str,
            index_name: str,
            body: ReindexRequest,
            current_user: Dict = Depends(auth),
        ):
            return await self.reindex(space_id, index_name, body, current_user)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonb(val: Optional[Dict]) -> Optional[str]:
    """Convert a dict to a JSON string for asyncpg JSONB parameter."""
    if val is None:
        return None
    import json
    return json.dumps(val)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_vector_indexes_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = VectorIndexesEndpoint(app_impl, auth_dependency)
    return endpoint.router
