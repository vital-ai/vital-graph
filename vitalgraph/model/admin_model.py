"""
Pydantic request/response models for Admin endpoints.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel

from .api_model import BasePaginatedResponse
from .result_status import ResultStatus, OperationStatus


class ResyncResponse(ResultStatus):
    """Response model for resync operation."""
    status: OperationStatus = OperationStatus.OK
    space_id: str
    edge_rows: int
    frame_slot_rows: int = 0
    # DEPRECATED alias of `frame_slot_rows`, carrying the same value.
    # `frame_entity` was retired for `frame_slot` (`issues/183`) and this field
    # has reported the frame_slot count ever since — a name contradicting its
    # own value. Kept populated so existing admin clients do not break; remove
    # once they read `frame_slot_rows`.
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


class AuditLogResponse(BasePaginatedResponse):
    """Paginated audit log response."""
    entries: List[AuditLogEntry]
