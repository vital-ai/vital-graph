"""
Pydantic request/response models for Admin endpoints.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel


class ResyncResponse(BaseModel):
    """Response model for resync operation."""
    space_id: str
    edge_rows: int
    frame_entity_rows: int
    pred_stats_rows: int
    quad_stats_rows: int
    elapsed_ms: float


class AuditLogEntry(BaseModel):
    """Single audit log entry."""
    id: int
    timestamp: str
    event: str
    actor: str
    target: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[dict] = None
    level: str = "INFO"


class AuditLogResponse(BaseModel):
    """Paginated audit log response."""
    entries: List[AuditLogEntry]
    total_count: int
    limit: int
    offset: int
