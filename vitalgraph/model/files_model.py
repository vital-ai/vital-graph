"""Files Model Classes

Pydantic models for file management operations.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse
from .result_status import ResultStatus, OperationStatus


class FileCreateResponse(BaseCreateResponse):
    """Response model for file creation."""
    pass


class FileUpdateResponse(BaseUpdateResponse):
    """Response model for file updates."""
    pass


class FileDeleteResponse(BaseDeleteResponse):
    """Response model for file deletion."""
    pass


class FileUploadResponse(ResultStatus):
    """Response model for file content upload.

    Inherits the unified success/status/message contract from ResultStatus;
    ``status`` defaults to CREATED for a successful upload, STORE_FAILED on a
    backend upload failure. ``success`` is derived.
    """
    status: OperationStatus = Field(
        OperationStatus.CREATED, description="Outcome discriminator (CREATED/STORE_FAILED/...)"
    )
    file_uri: str
    file_size: int
    content_type: str
    storage_path: Optional[str] = Field(None, description="Backend storage object key/path, when available")