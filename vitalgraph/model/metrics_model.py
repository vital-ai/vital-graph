"""
Pydantic request/response models for Metrics endpoints.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MetricsTotals(BaseModel):
    """Summary totals for a metrics query."""
    total_requests: int = 0
    total_errors: int = 0
    avg_latency_ms: int = 0


class MetricsResponse(BaseModel):
    """Time-series metrics response for a space."""
    success: bool = True
    space_id: str
    range: str
    granularity: str = Field(description="minute | hour")
    timestamps: List[str] = Field(default_factory=list)
    series: Dict[str, Any] = Field(default_factory=dict)
    totals: MetricsTotals = Field(default_factory=MetricsTotals)
    message: Optional[str] = None


class SlowQueryEntry(BaseModel):
    """Single slow query log entry."""
    query_id: Optional[str] = None
    space_id: str
    endpoint: Optional[str] = None
    duration_ms: float
    query_text: Optional[str] = None
    timestamp: Optional[str] = None


class SlowQueriesResponse(BaseModel):
    """Slow queries response for a space."""
    success: bool = True
    space_id: str
    slow_queries: List[SlowQueryEntry] = Field(default_factory=list)
    message: Optional[str] = None
