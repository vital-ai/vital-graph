"""
Pydantic request/response models for Vector Indexes endpoints.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
    job_id: Optional[str] = Field(None, description="Background job ID for status polling")
    subjects_processed: int = 0
    embeddings_stored: int = 0
    subjects_skipped: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = []


# ---------------------------------------------------------------------------
# Direct vector upsert / get (for testing and client-provided embeddings)
# ---------------------------------------------------------------------------

class VectorEntry(BaseModel):
    """A single vector to upsert."""
    subject_uri: str = Field(..., description="Subject URI of the entity")
    graph_uri: str = Field(..., description="Graph URI (context)")
    embedding: List[float] = Field(..., description="Embedding vector")
    search_text: Optional[str] = Field(None, description="Optional source text (enables hybrid search)")


class VectorUpsertRequest(BaseModel):
    """Batch upsert of pre-computed vectors."""
    vectors: List[VectorEntry] = Field(..., min_length=1, max_length=1000)


class VectorUpsertResponse(BaseModel):
    message: str
    upserted: int = 0
    errors: List[str] = []


class VectorGetOut(BaseModel):
    """A stored vector entry."""
    subject_uri: str
    graph_uri: str
    embedding: List[float]
    search_text: Optional[str] = None
    updated_time: Optional[str] = None


class VectorGetResponse(BaseModel):
    vectors: List[VectorGetOut]
    total_count: int
    page_size: int = 100
    offset: int = 0


# ---------------------------------------------------------------------------
# Reindex job status tracking
# ---------------------------------------------------------------------------

class ReindexJobStatus(BaseModel):
    """Status of a background reindex task."""
    job_id: str = Field(..., description="Unique reindex job identifier")
    index_name: str = Field(..., description="Index being reindexed")
    space_id: str = Field(..., description="Space ID")
    status: str = Field(..., description="pending | running | completed | failed")
    subjects_processed: int = 0
    embeddings_stored: int = 0
    subjects_skipped: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ReindexJobListResponse(BaseModel):
    """List of reindex job statuses."""
    jobs: List[ReindexJobStatus] = []
    total_count: int = 0
