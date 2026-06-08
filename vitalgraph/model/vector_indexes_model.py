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
    subjects_processed: int = 0
    embeddings_stored: int = 0
    subjects_skipped: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = []
