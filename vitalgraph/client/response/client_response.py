"""
VitalGraph Client Response Models

Standardized response objects for all VitalGraph client operations.
All responses contain VitalSigns GraphObjects, hiding JSON-LD complexity.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.model.spaces_model import Space


class VitalGraphResponse(BaseModel):
    """
    Standardized response wrapper for all VitalGraph client operations.
    
    Provides consistent structure with:
    - Error code (0 = success, non-zero = error)
    - Objects payload (type varies by response class)
    - Error details (if applicable)
    - Metadata (timing, counts, etc.)
    
    The objects field type depends on the response class:
    - GraphObjectResponse: List[GraphObject] - flat list of objects
    - EntityGraphResponse: EntityGraph - single entity graph container
    - FrameGraphResponse: FrameGraph - single frame graph container
    - MultiEntityGraphResponse: List[EntityGraph] - list of entity graph containers
    - MultiFrameGraphResponse: List[FrameGraph] - list of frame graph containers
    
    Each EntityGraph and FrameGraph container has its own objects: List[GraphObject]
    """
    
    error_code: int = Field(description="Error code (0 = success, non-zero = error)")
    error_message: Optional[str] = Field(default=None, description="Error message if error_code != 0")
    status_code: int = Field(description="HTTP status code")
    message: Optional[str] = Field(default=None, description="Human-readable status message")
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Response metadata")
    
    @property
    def is_success(self) -> bool:
        """Check if operation succeeded (error_code == 0)."""
        return self.error_code == 0
    
    @property
    def is_error(self) -> bool:
        """Check if operation failed (error_code != 0)."""
        return self.error_code != 0
    
    def raise_for_error(self):
        """Raise exception if response indicates error."""
        if self.is_error:
            from ..utils.client_utils import VitalGraphClientError
            raise VitalGraphClientError(
                f"Error {self.error_code}: {self.error_message or self.message}",
                status_code=self.status_code
            )


class GraphObjectResponse(VitalGraphResponse):
    """Response containing VitalSigns GraphObjects."""
    
    objects: Optional[List[GraphObject]] = Field(default=None, description="List of GraphObjects")
    
    @property
    def count(self) -> int:
        """Get count of objects in response."""
        return len(self.objects) if self.objects else 0


class PaginatedGraphObjectResponse(GraphObjectResponse):
    """Response with pagination metadata."""
    
    total_count: int = Field(default=0, description="Total count across all pages")
    page_size: int = Field(default=10, description="Items per page")
    offset: int = Field(default=0, description="Current offset")
    has_more: bool = Field(default=False, description="Whether more pages exist")
    
    entity_type_uri: Optional[str] = Field(default=None, description="Entity type URI filter from request")
    search: Optional[str] = Field(default=None, description="Search term from request")


class EntityGraph(BaseModel):
    """Container for a single entity graph with its own list of objects."""
    
    entity_uri: str = Field(description="URI of the entity")
    objects: List[GraphObject] = Field(description="List of GraphObjects in this entity graph")
    
    @property
    def count(self) -> int:
        """Get count of objects in this entity graph."""
        return len(self.objects)


class FrameGraph(BaseModel):
    """Container for a single frame graph with its own list of objects."""
    
    frame_uri: str = Field(description="URI of the frame")
    objects: List[GraphObject] = Field(description="List of GraphObjects in this frame graph")
    
    @property
    def count(self) -> int:
        """Get count of objects in this frame graph."""
        return len(self.objects)


class CreateEntityResponse(VitalGraphResponse):
    """Response for entity creation - server returns metadata, not objects."""
    
    created_count: int = Field(description="Number of entities created")
    created_uris: List[str] = Field(description="URIs of created entities")
    
    @property
    def count(self) -> int:
        """Get count of created entities."""
        return self.created_count


class UpdateEntityResponse(VitalGraphResponse):
    """Response for entity update - server returns metadata, not objects."""
    
    updated_uri: Optional[str] = Field(default=None, description="URI of updated entity")
    
    @property
    def count(self) -> int:
        """Get count - always 1 for single entity update."""
        return 1 if self.updated_uri else 0


class EntityResponse(GraphObjectResponse):
    """Response for entity GET operations that return actual objects."""
    pass


class EntityGraphResponse(VitalGraphResponse):
    """Response for single entity graph operation."""
    
    objects: Optional[EntityGraph] = Field(default=None, description="EntityGraph container with entity_uri and objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    requested_uri: Optional[str] = Field(default=None, description="Entity URI requested")
    requested_reference_id: Optional[str] = Field(default=None, description="Reference ID requested (if used)")


class FrameGraphResponse(VitalGraphResponse):
    """Response for single frame graph operation."""
    
    frame_graph: Optional[FrameGraph] = Field(default=None, description="FrameGraph container with frame_uri and objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    entity_uri: Optional[str] = Field(default=None, description="Entity URI that owns the frames")
    parent_frame_uri: Optional[str] = Field(default=None, description="Parent frame URI filter (if used)")
    requested_frame_uri: Optional[str] = Field(default=None, description="Frame URI requested")


class FrameResponse(GraphObjectResponse):
    """Response for single frame operations (without graph)."""
    pass


class MultiEntityGraphResponse(VitalGraphResponse):
    """Response for operations returning multiple entity graphs."""
    
    graph_list: Optional[List[EntityGraph]] = Field(default=None, description="List of EntityGraph containers, each with entity_uri and objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    requested_uris: Optional[List[str]] = Field(default=None, description="Entity URIs requested")
    requested_reference_ids: Optional[List[str]] = Field(default=None, description="Reference IDs requested (if used)")


class MultiFrameGraphResponse(VitalGraphResponse):
    """Response for operations returning multiple frame graphs."""
    
    frame_graph_list: Optional[List[FrameGraph]] = Field(default=None, description="List of FrameGraph containers, each with frame_uri and objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    entity_uri: Optional[str] = Field(default=None, description="Entity URI that owns the frames")
    requested_frame_uris: Optional[List[str]] = Field(default=None, description="Frame URIs requested")


class DeleteResponse(VitalGraphResponse):
    """Response for delete operations."""
    
    deleted_count: int = Field(default=0, description="Number of items deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted items")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    requested_uris: Optional[List[str]] = Field(default=None, description="URIs requested for deletion")


class QueryResponse(VitalGraphResponse):
    """Response for query operations."""
    
    objects: Optional[List[GraphObject]] = Field(default=None, description="List of GraphObjects matching the query")
    query_info: Dict[str, Any] = Field(default_factory=dict, description="Query execution information")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    query_criteria: Optional[Dict[str, Any]] = Field(default=None, description="Query criteria from request")
    
    @property
    def count(self) -> int:
        """Get count of objects in query results."""
        return len(self.objects) if self.objects else 0


# ============================================================================
# Files Endpoint Response Classes
# ============================================================================

class FileResponse(GraphObjectResponse):
    """Response for single file metadata operations."""
    
    file_uri: Optional[str] = Field(default=None, description="Primary file URI")
    file_node: Optional[GraphObject] = Field(default=None, description="Primary FileNode object")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    requested_uri: Optional[str] = Field(default=None, description="File URI requested")
    
    @property
    def file(self) -> Optional[GraphObject]:
        """Convenience property to get the primary FileNode."""
        return self.file_node


class FilesListResponse(PaginatedGraphObjectResponse):
    """Response for listing files with pagination."""
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    file_filter: Optional[str] = Field(default=None, description="File filter from request")
    
    @property
    def files(self) -> List[GraphObject]:
        """Convenience property to get FileNode objects."""
        return self.objects if self.objects else []


class FileCreateResponse(VitalGraphResponse):
    """Response for file creation operations."""
    
    created_uris: List[str] = Field(default_factory=list, description="URIs of created file nodes")
    created_count: int = Field(default=0, description="Number of files created")
    objects: Optional[List[GraphObject]] = Field(default=None, description="Created FileNode objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    
    @property
    def file_uri(self) -> Optional[str]:
        """Convenience property to get first created file URI."""
        return self.created_uris[0] if self.created_uris else None
    
    @property
    def count(self) -> int:
        """Get count of created files."""
        return self.created_count


class FileUpdateResponse(VitalGraphResponse):
    """Response for file update operations."""
    
    updated_uris: List[str] = Field(default_factory=list, description="URIs of updated file nodes")
    updated_count: int = Field(default=0, description="Number of files updated")
    objects: Optional[List[GraphObject]] = Field(default=None, description="Updated FileNode objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    
    @property
    def count(self) -> int:
        """Get count of updated files."""
        return self.updated_count


class FileDeleteResponse(VitalGraphResponse):
    """Response for file deletion operations."""
    
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted file nodes")
    deleted_count: int = Field(default=0, description="Number of files deleted")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    requested_uris: Optional[List[str]] = Field(default=None, description="URIs requested for deletion")
    
    @property
    def count(self) -> int:
        """Get count of deleted files."""
        return self.deleted_count


class FileUploadResponse(VitalGraphResponse):
    """Response for file content upload operations."""
    
    file_uri: str = Field(..., description="URI of file node")
    size: int = Field(default=0, description="Size of uploaded content in bytes")
    content_type: Optional[str] = Field(default=None, description="MIME type of uploaded content")
    filename: Optional[str] = Field(default=None, description="Original filename")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    
    @property
    def file_size(self) -> int:
        """Alias for size field for backward compatibility."""
        return self.size


class FileDownloadResponse(VitalGraphResponse):
    """Response for file content download operations (when using destination)."""
    
    file_uri: str = Field(..., description="URI of file node")
    size: int = Field(default=0, description="Size of downloaded content in bytes")
    content_type: Optional[str] = Field(default=None, description="MIME type of content")
    destination: str = Field(..., description="Destination path or type")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")


# ============================================================================
# Spaces Response Classes
# ============================================================================

class SpaceResponse(VitalGraphResponse):
    """Response for single space retrieval operations."""
    space: Optional[Space] = Field(None, description="Retrieved space")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.space is not None and not self.error_code


class SpaceInfoResponse(VitalGraphResponse):
    """Response for space info/statistics operations."""
    space: Optional[Space] = Field(None, description="Space information")
    statistics: Optional[Dict[str, Any]] = Field(None, description="Space statistics")
    quad_dump: Optional[List[str]] = Field(None, description="Quad logging dump if enabled")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.space is not None and not self.error_code


class SpacesListResponse(VitalGraphResponse):
    """Response for spaces listing operations."""
    spaces: List[Space] = Field(default_factory=list, description="List of spaces")
    total: int = Field(0, description="Total number of spaces")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code
    
    @property
    def count(self) -> int:
        """Get count of spaces."""
        return len(self.spaces)


class SpaceCreateResponse(VitalGraphResponse):
    """Response for space creation operations."""
    space: Optional[Any] = Field(None, description="Created space")
    created_count: int = Field(0, description="Number of spaces created (always 1)")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created_count > 0 and not self.error_code


class SpaceUpdateResponse(VitalGraphResponse):
    """Response for space update operations."""
    space: Optional[Any] = Field(None, description="Updated space")
    updated_count: int = Field(0, description="Number of spaces updated (always 1)")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated_count > 0 and not self.error_code


class SpaceDeleteResponse(VitalGraphResponse):
    """Response for space deletion operations."""
    deleted_count: int = Field(0, description="Number of spaces deleted (always 1)")
    space_id: Optional[str] = Field(None, description="ID of deleted space")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted_count > 0 and not self.error_code


# ============================================================================
# Graphs Response Classes
# ============================================================================

class GraphResponse(VitalGraphResponse):
    """Response for single graph retrieval operations."""
    graph: Optional[Any] = Field(None, description="Retrieved graph info")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.graph is not None and not self.error_code


class GraphsListResponse(VitalGraphResponse):
    """Response for graphs listing operations."""
    graphs: List[Any] = Field(default_factory=list, description="List of graphs")
    total: int = Field(0, description="Total number of graphs")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code
    
    @property
    def count(self) -> int:
        """Get count of graphs."""
        return len(self.graphs)


class GraphCreateResponse(VitalGraphResponse):
    """Response for graph creation operations."""
    graph_uri: Optional[str] = Field(None, description="Created graph URI")
    created: bool = Field(False, description="Whether graph was created")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and not self.error_code


class GraphDeleteResponse(VitalGraphResponse):
    """Response for graph deletion operations."""
    graph_uri: Optional[str] = Field(None, description="Deleted graph URI")
    deleted: bool = Field(False, description="Whether graph was deleted")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code


class GraphClearResponse(VitalGraphResponse):
    """Response for graph clear operations."""
    graph_uri: Optional[str] = Field(None, description="Cleared graph URI")
    cleared: bool = Field(False, description="Whether graph was cleared")
    triples_removed: int = Field(0, description="Number of triples removed")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.cleared and not self.error_code


# ============================================================================
# KGTypes Response Classes
# ============================================================================

class KGTypeResponse(VitalGraphResponse):
    """Response for single KGType retrieval operations."""
    type: Optional[Any] = Field(None, description="Retrieved KGType data")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.type is not None and not self.error_code


class KGTypesListResponse(VitalGraphResponse):
    """Response for KGType list operations."""
    types: List[Any] = Field(default_factory=list, description="List of KGTypes")
    count: int = Field(0, description="Total count of types")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code


class KGTypeCreateResponse(VitalGraphResponse):
    """Response for KGType create operations."""
    created: bool = Field(False, description="Whether types were created")
    created_count: int = Field(0, description="Number of types created")
    created_uris: List[str] = Field(default_factory=list, description="URIs of created types")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and self.created_count > 0 and not self.error_code


class KGTypeUpdateResponse(VitalGraphResponse):
    """Response for KGType update operations."""
    updated: bool = Field(False, description="Whether types were updated")
    updated_count: int = Field(0, description="Number of types updated")
    updated_uris: List[str] = Field(default_factory=list, description="URIs of updated types")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated and self.updated_count > 0 and not self.error_code


class KGTypeDeleteResponse(VitalGraphResponse):
    """Response for KGType delete operations."""
    deleted: bool = Field(False, description="Whether types were deleted")
    deleted_count: int = Field(0, description="Number of types deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted types")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code


# ============================================================================
# Objects Response Classes
# ============================================================================

class ObjectResponse(VitalGraphResponse):
    """Response for single object retrieval operations."""
    object: Optional[Any] = Field(None, description="Retrieved object data")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.object is not None and not self.error_code


class ObjectsListResponse(VitalGraphResponse):
    """Response for object list operations."""
    objects: List[Any] = Field(default_factory=list, description="List of objects")
    count: int = Field(0, description="Total count of objects")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code


class ObjectCreateResponse(VitalGraphResponse):
    """Response for object create operations."""
    created: bool = Field(False, description="Whether objects were created")
    created_count: int = Field(0, description="Number of objects created")
    created_uris: List[str] = Field(default_factory=list, description="URIs of created objects")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and self.created_count > 0 and not self.error_code


class ObjectUpdateResponse(VitalGraphResponse):
    """Response for object update operations."""
    updated: bool = Field(False, description="Whether objects were updated")
    updated_count: int = Field(0, description="Number of objects updated")
    updated_uris: List[str] = Field(default_factory=list, description="URIs of updated objects")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated and self.updated_count > 0 and not self.error_code


class ObjectDeleteResponse(VitalGraphResponse):
    """Response for object delete operations."""
    deleted: bool = Field(False, description="Whether objects were deleted")
    deleted_count: int = Field(0, description="Number of objects deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted objects")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code
