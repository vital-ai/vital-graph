"""
Pydantic request/response models for Metrics endpoints.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .result_status import ResultStatus, OperationStatus


class MetricsTotals(BaseModel):
    """Summary totals for a metrics query."""
    total_requests: int = 0
    total_errors: int = 0
    avg_latency_ms: int = 0


class MetricsResponse(ResultStatus):
    """Time-series metrics response for a space."""
    space_id: str
    range: str
    granularity: str = Field(description="minute | hour")
    timestamps: List[str] = Field(default_factory=list)
    series: Dict[str, Any] = Field(default_factory=dict)
    totals: MetricsTotals = Field(default_factory=MetricsTotals)
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/INVALID_REQUEST/...)"
    )


class SlowQueryEntry(BaseModel):
    """Single slow query log entry."""
    query_id: Optional[str] = None
    space_id: str
    endpoint: Optional[str] = None
    duration_ms: float
    query_text: Optional[str] = None
    timestamp: Optional[str] = None


class SlowQueriesResponse(ResultStatus):
    """Slow queries response for a space.

    Entries are passed through from the metrics collector unchanged (keys ``ts``,
    ``ms``, ``endpoint``, plus any metadata), which is the shape existing UI clients
    consume. ``SlowQueryEntry`` documents the canonical row model but is not enforced
    here to avoid altering the live wire shape.
    """
    space_id: str
    slow_queries: List[Dict[str, Any]] = Field(default_factory=list)
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/...)"
    )
