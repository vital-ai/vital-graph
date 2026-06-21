"""
Pydantic request/response models for FTS Indexes endpoints.

FTS indexes manage per-space full-text search data tables with
multi-language tsvector triggers.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Output / response models
# ---------------------------------------------------------------------------

class FtsIndexOut(BaseModel):
    """An FTS index entry."""
    index_id: int
    index_name: str
    languages: List[str] = ["english"]
    created_time: Optional[str] = None
    row_count: Optional[int] = None


class FtsIndexListResponse(BaseModel):
    indexes: List[FtsIndexOut]
    total_count: int


class FtsIndexStatsResponse(BaseModel):
    index_name: str
    row_count: int = 0
    distinct_entity_count: int = 0
    has_tsv_count: int = 0


# ---------------------------------------------------------------------------
# Create / update request models
# ---------------------------------------------------------------------------

class CreateFtsIndexRequest(BaseModel):
    index_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Lowercase alphanumeric + underscores, e.g. 'entity_default'",
    )
    languages: List[str] = Field(
        ["english"],
        min_length=1,
        description="PostgreSQL text search languages, e.g. ['english', 'spanish']",
    )


class UpdateFtsLanguagesRequest(BaseModel):
    languages: List[str] = Field(
        ...,
        min_length=1,
        description="New language list",
    )
    refresh_tsv: bool = Field(
        True,
        description="Re-compute tsvector values for all existing rows",
    )


class PopulateFtsRequest(BaseModel):
    graph_uri: str = Field(..., description="Graph URI to populate from")
    mapping_type: Optional[str] = Field(
        None,
        description="Filter: kgentity | kgdocument | kgframe | kgslot",
    )
    type_uri: Optional[str] = Field(
        None,
        description="Filter: specific KG Type URI",
    )
    batch_size: int = Field(100, ge=1, le=1000, description="Batch size")


class PopulateFtsResponse(BaseModel):
    message: str
    index_name: str
    rows_populated: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = []


class DeleteResponse(BaseModel):
    message: str
    deleted: bool = False
