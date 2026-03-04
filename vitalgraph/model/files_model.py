"""Files Model Classes

Pydantic models for file management operations.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse


class FileCreateResponse(BaseCreateResponse):
    """Response model for file creation."""
    pass


class FileUpdateResponse(BaseUpdateResponse):
    """Response model for file updates."""
    pass


class FileDeleteResponse(BaseDeleteResponse):
    """Response model for file deletion."""
    pass


class FileUploadResponse(BaseModel):
    """Response model for file content upload."""
    message: str
    file_uri: str
    file_size: int
    content_type: str