"""
VitalGraph Client Response Models

Standardized response objects for all VitalGraph client operations.
All responses contain VitalSigns GraphObjects, hiding wire format complexity.
"""

import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.result_status import OperationStatus, _SUCCESS_STATUSES
from vitalgraph.model.server_properties import MODIFICATION_TIME_URI

# String values of the OperationStatus members that mean "the expected thing happened".
# Used to derive is_success from the server's domain `status` (HTTP is 200 for all
# domain outcomes, so success/failure must be read from the body, not the HTTP code).
_SUCCESS_STATUS_VALUES = frozenset(s.value for s in _SUCCESS_STATUSES)


def modification_stamp(obj: GraphObject) -> Optional[str]:
    """The object's `hasObjectModificationDateTime`, in the form the server compares.

    Half of the optimistic-concurrency loop (`issues/253`): read this, pass it to
    a write as `if_unmodified_since`, and on `is_conflict` read it again and
    re-merge. The other half is the write parameter; without this the caller has
    to know the predicate URI, and two test scripts had already hardcoded it.

    READ IT THROUGH HERE, NOT OFF THE ATTRIBUTE. The obvious thing a caller would
    write is `str(entity.objectModificationDateTime)`, and that is **a value the
    server can never match**: VitalSigns parses the literal into a `datetime`, so
    `str()` renders it space-separated — `2026-10-01 12:23:37.333100+00:00` —
    while the stored term text is ISO-8601 with the `T`. The server compares the
    stored STRING deliberately (a datetime comparison would forgive a formatting
    difference, and a formatting difference means something rewrote the value),
    so the space form would refuse every write and the caller would see a
    permanent conflict it could do nothing about. This returns the wire form,
    which is what round-trips.

    Returns None when the object carries no stamp — a legitimate answer for an
    entity written before stamping, and the caller then has nothing to be
    conditional on.
    """
    try:
        return json.loads(obj.to_json()).get(MODIFICATION_TIME_URI)
    except Exception:
        return None


def find_modification_stamp(objects: Optional[List[GraphObject]],
                            uri: Optional[str]) -> Optional[str]:
    """`modification_stamp` of the object in *objects* whose URI is *uri*.

    An entity graph holds the entity, its frames, its slots and their edges, and
    every one of them carries its own stamp. The guard keys on the OWNING ENTITY,
    so picking the first stamp in the list would send a frame's — accepted or
    refused for the wrong reason.
    """
    if not objects or not uri:
        return None
    for obj in objects:
        if str(getattr(obj, "URI", "")) == str(uri):
            return modification_stamp(obj)
    return None


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

    # Domain outcome from the server body (the OperationStatus enum value, e.g.
    # "created", "already_exists", "not_found", "empty", "store_failed"). HTTP is
    # 200 for every domain outcome, so success/failure is read from this — NOT the
    # HTTP status code. None for legacy/plain responses that don't carry it.
    status: Optional[str] = Field(default=None, description="Server domain outcome (OperationStatus value)")

    metadata: Dict[str, Any] = Field(default_factory=dict, description="Response metadata")

    @property
    def is_success(self) -> bool:
        """Whether the expected operation happened.

        When the server supplied a domain `status`, that is authoritative (an HTTP
        200 with status=already_exists is NOT a success). Otherwise falls back to
        the legacy error_code check.
        """
        if self.status is not None:
            return self.status in _SUCCESS_STATUS_VALUES
        return self.error_code == 0

    @property
    def is_error(self) -> bool:
        """Whether the operation did not succeed (inverse of is_success)."""
        return not self.is_success

    @property
    def is_conflict(self) -> bool:
        """Whether the write was REFUSED because the target moved underneath it.

        `issues/253`. A caller needs this apart from `is_error`, because the two
        want opposite responses: a conflict means re-read, re-merge and try
        again, while a `store_failed` means the write did not happen for a reason
        retrying will not change. Both are `is_error`, and treating a conflict
        like the latter is how a lost update becomes a dropped one.

        Do NOT retry a conflict with the same `if_unmodified_since` — the whole
        point is that the value is stale, so the retry would be refused
        identically. Re-read first.
        """
        return self.status == OperationStatus.CONFLICT.value

    def raise_for_error(self):
        """Raise VitalGraphClientError if the response indicates a non-success outcome."""
        if self.is_error:
            from ..utils.client_utils import VitalGraphClientError
            detail = self.error_message or self.message or (self.status or "unknown error")
            code = self.status or self.error_code
            raise VitalGraphClientError(
                f"Error {code}: {detail}",
                status_code=self.status_code
            )


class GraphObjectResponse(VitalGraphResponse):
    """Response containing VitalSigns GraphObjects."""
    
    objects: Optional[List[GraphObject]] = Field(default=None, description="List of GraphObjects")
    
    @property
    def count(self) -> int:
        """Get count of objects in response."""
        return len(self.objects) if self.objects else 0

    def modification_stamp_for(self, uri: str) -> Optional[str]:
        """The stamp of the object with *uri*, for `if_unmodified_since`.

        `issues/253`. This is the flat read — `get_kgentity` without
        `include_entity_graph` — which is the cheaper way to open the
        read-modify-write loop when the caller only needs the stamp. Takes a URI
        because a flat response may hold many objects and there is no "the" one.
        """
        return find_modification_stamp(self.objects, uri)


class PaginatedGraphObjectResponse(GraphObjectResponse):
    """Response with pagination metadata."""
    
    total_count: int = Field(default=0, description="Total count across all pages")
    page_size: int = Field(default=10, description="Items per page")
    offset: int = Field(default=0, description="Current offset")
    # Optional, and defaulting to None rather than False, because `bool` cannot
    # express "unknown" — and that is precisely what this field was returning
    # before 2026-08-16. It was never computed anywhere on this path, so a
    # caller asking "is there a next page?" got a confident No on every list
    # call. `None` makes the absence of an answer visible instead of dressing it
    # as one; `if response.has_more:` behaves identically, since None is falsy.
    has_more: Optional[bool] = Field(
        default=None,
        description="Whether more pages exist; None when the server did not say "
                    "and it could not be derived",
    )
    # Three-valued for the same reason as `has_more`: False is a CLAIM that the
    # answer is whole, None is the absence of one. A caller reading None as
    # False is back to `issues/229`, where a saturated pool removed 113 of 500
    # entity graphs from a 200 response and nothing said so.
    incomplete: Optional[bool] = Field(
        default=None,
        description="True when the server could not return part of what was "
                    "asked for (retryable, see missing_uris); False when it "
                    "verified the answer is whole; None when the route cannot "
                    "say — NOT the same as False",
    )
    missing_uris: List[str] = Field(
        default_factory=list,
        description="URIs requested whose data did not come back. Retryable "
                    "when `incomplete` is True; when it is False they simply "
                    "do not exist",
    )
    
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

    @property
    def modification_stamp(self) -> Optional[str]:
        """The ENTITY's stamp, to pass as `if_unmodified_since` (`issues/253`).

        The entity's, not the graph's: the frames and slots in here each carry
        their own, and the write guard keys on the owning entity.
        """
        return find_modification_stamp(self.objects, self.entity_uri)


class FrameGraph(BaseModel):
    """Container for a single frame graph with its own list of objects."""
    
    frame_uri: str = Field(description="URI of the frame")
    objects: List[GraphObject] = Field(description="List of GraphObjects in this frame graph")
    
    @property
    def count(self) -> int:
        """Get count of objects in this frame graph."""
        return len(self.objects)

    @property
    def modification_stamp(self) -> Optional[str]:
        """The FRAME's stamp, to pass as `if_unmodified_since` (`issues/253`).

        The frame's, not its slots': the standalone-frame routes guard on the
        frame because they have no owning entity, and a slot's own stamp would be
        a different version of a different thing.
        """
        return find_modification_stamp(self.objects, self.frame_uri)


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

    @property
    def modification_stamp(self) -> Optional[str]:
        """The entity's stamp, to pass as `if_unmodified_since` (`issues/253`).

            r = await c.kgentities.get_kgentity(..., include_entity_graph=True)
            w = await c.kgentities.update_entity_frames(
                    ..., if_unmodified_since=r.modification_stamp)
            if w.is_conflict:
                ...    # somebody else wrote: read again, re-merge, re-send
        """
        return self.objects.modification_stamp if self.objects else None


class FrameGraphResponse(VitalGraphResponse):
    """Response for single frame graph operation."""
    
    frame_graph: Optional[FrameGraph] = Field(default=None, description="FrameGraph container with frame_uri and objects")
    
    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    entity_uri: Optional[str] = Field(default=None, description="Entity URI that owns the frames")
    parent_frame_uri: Optional[str] = Field(default=None, description="Parent frame URI filter (if used)")
    requested_frame_uri: Optional[str] = Field(default=None, description="Frame URI requested")

    @property
    def modification_stamp(self) -> Optional[str]:
        """The frame's stamp, to pass as `if_unmodified_since` (`issues/253`).

            r = await c.kgframes.get_kgframe(..., include_frame_graph=True)
            w = await c.kgframes.update_kgframes(
                    ..., if_unmodified_since=r.modification_stamp)
            if w.is_conflict:
                ...    # somebody else wrote: read again, re-merge, re-send
        """
        return self.frame_graph.modification_stamp if self.frame_graph else None


class FrameResponse(GraphObjectResponse):
    """Response for frame list/single operations (without graph)."""

    slot_counts: Optional[Dict[str, int]] = Field(
        default=None,
        description=(
            "Frame URI -> slot count for the returned page. Present only when "
            "requested via include_slot_counts. A frame with zero slots is "
            "reported as 0, not omitted."
        ),
    )


class MultiEntityGraphResponse(VitalGraphResponse):
    """Response for operations returning multiple entity graphs."""
    
    graph_list: Optional[List[EntityGraph]] = Field(default=None, description="List of EntityGraph containers, each with entity_uri and objects")

    # Pagination. Absent until 2026-08-16, which is why
    # `list_kgentities(include_entity_graph=True)` returned a page with no total
    # even though the SERVER sent the correct one — the client computed
    # pagination and then had nowhere to put it, so it dropped it. See
    # planning_client/pagination_contract_plan.md.
    total_count: int = Field(default=0, description="Total count across all pages")
    page_size: int = Field(default=0, description="Items per page")
    offset: int = Field(default=0, description="Current offset")
    has_more: Optional[bool] = Field(
        default=None,
        description="Whether more pages exist; None when it could not be determined",
    )
    # Three-valued like `has_more` above: False is a CLAIM that the answer is
    # whole, None is the absence of one. See PaginatedGraphObjectResponse.
    incomplete: Optional[bool] = Field(
        default=None,
        description="True when the server could not return part of what was "
                    "asked for (retryable, see missing_uris); False when it "
                    "verified the answer is whole; None when the route cannot "
                    "say — NOT the same as False",
    )
    missing_uris: List[str] = Field(
        default_factory=list,
        description="URIs requested whose data did not come back",
    )

    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    requested_uris: Optional[List[str]] = Field(default=None, description="Entity URIs requested")

    @property
    def modification_stamps(self) -> Dict[str, Optional[str]]:
        """Entity URI -> its stamp, for a batch read (`issues/253`).

        A dict rather than a list, because the per-entity write that follows
        needs the stamp for ITS entity and the two orders need not agree. An
        entity with no stamp appears with None rather than being dropped — it is
        still an entity the caller read.
        """
        return {g.entity_uri: g.modification_stamp for g in (self.graph_list or [])}
    requested_reference_ids: Optional[List[str]] = Field(default=None, description="Reference IDs requested (if used)")


class MultiFrameGraphResponse(VitalGraphResponse):
    """Response for operations returning multiple frame graphs."""
    
    frame_graph_list: Optional[List[FrameGraph]] = Field(default=None, description="List of FrameGraph containers, each with frame_uri and objects")

    # Pagination. Absent until 2026-08-16, which is why
    # `list_kgentities(include_entity_graph=True)` returned a page with no total
    # even though the SERVER sent the correct one — the client computed
    # pagination and then had nowhere to put it, so it dropped it. See
    # planning_client/pagination_contract_plan.md.
    total_count: int = Field(default=0, description="Total count across all pages")
    page_size: int = Field(default=0, description="Items per page")
    offset: int = Field(default=0, description="Current offset")
    has_more: Optional[bool] = Field(
        default=None,
        description="Whether more pages exist; None when it could not be determined",
    )
    # Three-valued like `has_more` above: False is a CLAIM that the answer is
    # whole, None is the absence of one. See PaginatedGraphObjectResponse.
    incomplete: Optional[bool] = Field(
        default=None,
        description="True when the server could not return part of what was "
                    "asked for (retryable, see missing_uris); False when it "
                    "verified the answer is whole; None when the route cannot "
                    "say — NOT the same as False",
    )
    missing_uris: List[str] = Field(
        default_factory=list,
        description="URIs requested whose data did not come back",
    )

    space_id: Optional[str] = Field(default=None, description="Space ID from request")
    graph_id: Optional[str] = Field(default=None, description="Graph ID from request")
    entity_uri: Optional[str] = Field(default=None, description="Entity URI that owns the frames")
    requested_frame_uris: Optional[List[str]] = Field(default=None, description="Frame URIs requested")


class DeleteResponse(VitalGraphResponse):
    """Response for delete operations."""
    
    deleted_count: int = Field(default=0, description="Number of items deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted items")
    absent_uris: List[str] = Field(
        default_factory=list,
        description="Requested URIs that were already absent (NO_OP, not a failure)")
    
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
    # `count` is the number on THIS page; `total_count` is the size of the whole
    # result set. That is the contract KGTypeSearchResponse already documented
    # and GraphObjectResponse.count already implements — these three were the
    # odd ones out, declaring `count` as "total count" and being handed the
    # server's total by the list methods. Aligned 2026-08-16.
    #
    # BREAKING: a caller reading `count` for the total must read `total_count`.
    # `count` now means what its name says everywhere in this module.
    count: int = Field(0, description="Number of types on this page")
    total_count: int = Field(0, description="Total types across all pages")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    has_more: Optional[bool] = Field(
        None,
        description="Whether more pages exist; None when the server did not say",
    )
    
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


class KGTypeRelationshipsResponse(VitalGraphResponse):
    """Response for KGType relationships query."""
    source_type: Dict[str, Any] = Field(default_factory=dict, description="Queried type info")
    edges: List[Dict[str, Any]] = Field(default_factory=list, description="Type-level edges")
    connected_types: List[Dict[str, Any]] = Field(default_factory=list, description="Connected types")

    @property
    def is_success(self) -> bool:
        return not self.error_code


class KGTypeRelationshipCreateResponse(VitalGraphResponse):
    """Response for creating a type-level relationship edge."""
    edge_uri: str = Field("", description="URI of created edge")
    edge_type: str = Field("", description="Edge vitaltype URI")
    source_uri: str = Field("", description="Source type URI")
    destination_uri: str = Field("", description="Destination type URI")

    @property
    def is_success(self) -> bool:
        return bool(self.edge_uri) and not self.error_code


class KGTypeRelationshipDeleteResponse(VitalGraphResponse):
    """Response for deleting a type-level relationship edge."""
    deleted: bool = Field(False, description="Whether edge was deleted")
    edge_uri: str = Field("", description="URI of deleted edge")

    @property
    def is_success(self) -> bool:
        return self.deleted and not self.error_code


class KGTypeDocumentationResponse(VitalGraphResponse):
    """Response for getting type documentation."""
    type_uri: str = Field("", description="Type URI")
    content: Optional[str] = Field(None, description="Markdown documentation content")
    document_uri: Optional[str] = Field(None, description="KGDocument URI")
    has_documentation: bool = Field(False, description="Whether documentation exists")

    @property
    def is_success(self) -> bool:
        return not self.error_code


class KGTypeDocumentationUpdateResponse(VitalGraphResponse):
    """Response for creating/updating type documentation."""
    type_uri: str = Field("", description="Type URI")
    document_uri: str = Field("", description="KGDocument URI")
    created: bool = Field(False, description="Whether new doc was created vs updated")

    @property
    def is_success(self) -> bool:
        return bool(self.document_uri) and not self.error_code


class KGTypeDocumentationDeleteResponse(VitalGraphResponse):
    """Response for deleting type documentation."""
    type_uri: str = Field("", description="Type URI")
    deleted: bool = Field(False, description="Whether documentation was deleted")

    @property
    def is_success(self) -> bool:
        return not self.error_code


class KGTypeSearchResponse(VitalGraphResponse):
    """Response for searching KG types."""
    types: List[Dict[str, Any]] = Field(default_factory=list, description="Matching types")
    count: int = Field(0, description="Number of results on this page")
    total_count: int = Field(0, description="Total matching results across all pages")
    page_size: int = Field(25, description="Page size used")
    offset: int = Field(0, description="Offset used")
    search_mode: str = Field("keyword", description="Search mode used")
    query: str = Field("", description="Original query")

    @property
    def is_success(self) -> bool:
        return not self.error_code


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
    # `count` is the number on THIS page; `total_count` is the size of the whole
    # result set. That is the contract KGTypeSearchResponse already documented
    # and GraphObjectResponse.count already implements — these three were the
    # odd ones out, declaring `count` as "total count" and being handed the
    # server's total by the list methods. Aligned 2026-08-16.
    #
    # BREAKING: a caller reading `count` for the total must read `total_count`.
    # `count` now means what its name says everywhere in this module.
    count: int = Field(0, description="Number of objects on this page")
    total_count: int = Field(0, description="Total objects across all pages")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    has_more: Optional[bool] = Field(
        None,
        description="Whether more pages exist; None when the server did not say",
    )
    
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


# ============================================================================
# KGDocuments Response Classes
# ============================================================================

class KGDocumentResponse(VitalGraphResponse):
    """Response for single KGDocument retrieval operations."""
    document: Optional[Any] = Field(None, description="Retrieved KGDocument data")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.document is not None and not self.error_code


class KGDocumentsListResponse(VitalGraphResponse):
    """Response for KGDocument list operations."""
    documents: List[Any] = Field(default_factory=list, description="List of KGDocuments")
    # `count` is the number on THIS page; `total_count` is the size of the whole
    # result set. That is the contract KGTypeSearchResponse already documented
    # and GraphObjectResponse.count already implements — these three were the
    # odd ones out, declaring `count` as "total count" and being handed the
    # server's total by the list methods. Aligned 2026-08-16.
    #
    # BREAKING: a caller reading `count` for the total must read `total_count`.
    # `count` now means what its name says everywhere in this module.
    count: int = Field(0, description="Number of documents on this page")
    total_count: int = Field(0, description="Total documents across all pages")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    has_more: Optional[bool] = Field(
        None,
        description="Whether more pages exist; None when the server did not say",
    )
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code


class KGDocumentCreateResponse(VitalGraphResponse):
    """Response for KGDocument create operations."""
    created: bool = Field(False, description="Whether documents were created")
    created_count: int = Field(0, description="Number of documents created")
    created_uris: List[str] = Field(default_factory=list, description="URIs of created documents")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and self.created_count > 0 and not self.error_code


class KGDocumentUpdateResponse(VitalGraphResponse):
    """Response for KGDocument update operations."""
    updated: bool = Field(False, description="Whether documents were updated")
    updated_count: int = Field(0, description="Number of documents updated")
    updated_uris: List[str] = Field(default_factory=list, description="URIs of updated documents")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated and self.updated_count > 0 and not self.error_code


class KGDocumentDeleteResponse(VitalGraphResponse):
    """Response for KGDocument delete operations (with cascade)."""
    deleted: bool = Field(False, description="Whether documents were deleted")
    deleted_count: int = Field(0, description="Number of documents deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted documents")

    @property
    def is_success(self) -> bool:
        """Check if operation was successful.

        Defers to the base implementation when the server supplied a domain
        `status`, so an HTTP 200 carrying status=invalid_request (e.g. managed
        segment delete protection) is not reported as a success. Only falls
        back to the `deleted` flag when no status is present.
        """
        if self.status is not None:
            return super().is_success
        return self.deleted and not self.error_code


class KGDocumentSegmentsResponse(VitalGraphResponse):
    """Response for listing segments of a KGDocument."""
    segments: List[Any] = Field(default_factory=list, description="List of segment GraphObjects")
    # Unpaged: every segment of the document is returned, so this is both the
    # page count and the total. Described as a count of what is here, matching
    # `count` everywhere else in this module, rather than as a "total".
    count: int = Field(0, description="Number of segments returned (all of them)")
    parent_uri: Optional[str] = Field(None, description="Parent document URI")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code


# ============================================================================
# KGDocument Segmentation Operation Response Classes
# ============================================================================

class SegmentDocumentClientResponse(VitalGraphResponse):
    """Response for document segmentation trigger operations."""
    success: bool = Field(False, description="Whether segmentation succeeded or was enqueued")
    document_uri: Optional[str] = Field(None, description="URI of segmented document")
    parent_copy_uri: Optional[str] = Field(None, description="URI of parent copy")
    method_uri: Optional[str] = Field(None, description="Segmentation method used")
    segment_count: int = Field(0, description="Number of segments created")
    segment_uris: List[str] = Field(default_factory=list, description="URIs of created segments")
    job_id: Optional[int] = Field(None, description="Background job ID (when async)")
    async_mode: bool = Field(False, description="True if enqueued for background processing")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.success and not self.error_code


class SegmentationStatusClientResponse(VitalGraphResponse):
    """Response for segmentation status queries."""
    pending: int = Field(0, description="Number of pending jobs")
    in_progress: int = Field(0, description="Number of in-progress jobs")
    vectorizing: int = Field(0, description="Number of jobs with segmentation done, vectorization in progress")
    completed: int = Field(0, description="Number of completed jobs")
    failed: int = Field(0, description="Number of failed jobs")
    cancelled: int = Field(0, description="Number of cancelled jobs")
    jobs: List[Dict[str, Any]] = Field(default_factory=list, description="List of job status entries")
    worker_status: Optional[Dict[str, Any]] = Field(None, description="Segmentation worker health status")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code


class SegmentationConfigClientResponse(VitalGraphResponse):
    """Response for single segmentation config operations (create/update)."""
    config_id: Optional[int] = Field(None, description="Config ID")
    document_type_uri: Optional[str] = Field(None, description="Document type URI")
    segment_method_uri: Optional[str] = Field(None, description="Segmentation method URI")
    max_segment_tokens: Optional[int] = Field(None, description="Max tokens per segment")
    min_segment_tokens: Optional[int] = Field(None, description="Min tokens per segment")
    overlap_tokens: Optional[int] = Field(None, description="Token overlap between segments")
    enabled: Optional[bool] = Field(None, description="Whether config is enabled")
    auto_vectorize: Optional[bool] = Field(None, description="Whether to auto-vectorize segments")
    created_time: Optional[str] = Field(None, description="Creation timestamp")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.config_id is not None and not self.error_code


class SegmentationConfigListClientResponse(VitalGraphResponse):
    """Response for listing segmentation configs."""
    configs: List[Dict[str, Any]] = Field(default_factory=list, description="List of segmentation configs")
    total_count: int = Field(0, description="Total number of configs")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code
    
    @property
    def count(self) -> int:
        """Get count of configs."""
        return len(self.configs)


class SegmentationConfigDeleteClientResponse(VitalGraphResponse):
    """Response for segmentation config deletion."""
    deleted: bool = Field(False, description="Whether config was deleted")
    config_id: Optional[int] = Field(None, description="ID of deleted config")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code
