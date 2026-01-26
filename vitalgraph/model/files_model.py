"""Files Model Classes

Pydantic models for file management operations.
"""

from typing import List, Union
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument, JsonLdObject
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class FilesResponse(BasePaginatedResponse):
    """Response model for files listing."""
    files: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing files")


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