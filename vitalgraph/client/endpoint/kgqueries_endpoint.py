"""
VitalGraph Client KGQueries Endpoint

Client-side implementation for KG entity-to-entity connection query operations.
"""

import logging
from typing import Dict, Any, Literal, Optional, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgqueries_model import (
    KGQueryRequest,
    KGQueryResponse,
    KGQueryCriteria,
    SlotProjection,
    PropertyProjection,
    FTSCriteria,
    TotalCountMode,
    FrameQueryResponse,
    KGEntityQueryResponse,
    RelationQueryResponse,
    DocumentQueryResponse,
)
from ...model.kgentities_model import (
    EntityQueryCriteria, EntityPropertyFilter, FrameCriteria, SlotCriteria, SortCriteria,
    VectorSearchCriteria, MultiVectorSearchCriteria, GeoSearchCriteria,
    DocumentSearchCriteria,
)

logger = logging.getLogger(__name__)


class KGQueriesEndpoint(BaseEndpoint):
    """Client endpoint for KG entity-to-entity connection queries."""
    
    async def query_connections(
        self,
        space_id: str,
        graph_id: str,
        criteria: KGQueryCriteria,
        page_size: int = 10,
        offset: int = 0,
        include_frame_graph: bool = False,
        include_entity_graph: bool = False,
        count_only: bool = False,
        slot_projection: Optional[List[SlotProjection]] = None,
        property_projection: Optional[List[PropertyProjection]] = None,
        include_total_count: TotalCountMode = TotalCountMode.NO,
    ) -> KGQueryResponse:
        """
        Query entity-to-entity connections based on criteria.
        
        Supports two query types:
        - relation: Find entities connected via Edge_hasKGRelation
        - frame: Find entities connected via shared KGFrames
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            criteria: Query criteria specifying query type and filters
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with connections based on query_type
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, criteria=criteria)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgqueries"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            # Build request body
            request_body = KGQueryRequest(
                criteria=criteria,
                page_size=page_size,
                offset=offset,
                include_frame_graph=include_frame_graph,
                include_entity_graph=include_entity_graph,
                count_only=count_only,
                slot_projection=slot_projection,
                property_projection=property_projection,
                include_total_count=include_total_count,
            )
            
            # Log complete request for debugging
            request_dict = request_body.model_dump()
            logger.info(f"KGQuery Request URL: {url}")
            logger.info(f"KGQuery Request Params: {params}")
            logger.info(f"KGQuery Request Body: {request_dict}")
            
            # Make typed request
            response = await self._make_typed_request(
                'POST',
                url,
                KGQueryResponse,
                params=params,
                json=request_dict,
                # Read-only query expressed as a POST — safe to replay.
                idempotent=True
            )
            
            # Log response for debugging
            logger.info(f"KGQuery Response: query_type={response.query_type}, total_count={response.total_count}")
            if criteria.fts_criteria and response.success and not response.fts_applied:
                raise VitalGraphClientError(
                    "The server did not acknowledge fts_criteria. Upgrade the "
                    "VitalGraph server to a compatible build; refusing an "
                    "unfiltered response."
                )
            
            return response
            
        except VitalGraphClientError as e:
            logger.error(f"Error querying connections: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error querying connections: {e}")
            raise VitalGraphClientError(f"Failed to query connections: {str(e)}")
    
    async def query_frame_connections(
        self,
        space_id: str,
        graph_id: str,
        source_entity_uris: Optional[List[str]] = None,
        destination_entity_uris: Optional[List[str]] = None,
        source_entity_criteria: Optional[EntityQueryCriteria] = None,
        destination_entity_criteria: Optional[EntityQueryCriteria] = None,
        shared_frame_types: Optional[List[str]] = None,
        exclude_self_connections: bool = True,
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """
        Convenience method for querying frame-based connections.
        
        Find entities connected via shared KGFrames.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            source_entity_uris: Optional list of source entity URIs
            destination_entity_uris: Optional list of destination entity URIs
            source_entity_criteria: Optional criteria for source entities
            destination_entity_criteria: Optional criteria for destination entities
            shared_frame_types: Optional list of frame types to filter by
            exclude_self_connections: Exclude connections from entity to itself (default: True)
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with frame connections
            
        Raises:
            VitalGraphClientError: If request fails
        """
        # Build frame query criteria
        criteria = KGQueryCriteria(
            query_type="frame",
            document_criteria=None,
            query_mode="edge",
            source_entity_uris=source_entity_uris,
            destination_entity_uris=destination_entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=destination_entity_criteria,
            relation_type_uris=None,
            direction="outgoing",
            source_frame_criteria=None,
            destination_frame_criteria=None,
            shared_frame_types=shared_frame_types,
            frame_slot_criteria=None,
            frame_criteria=None,
            sort_criteria=None,
            entity_property_filters=None,
            vector_criteria=None,
            multi_vector_criteria=None,
            geo_criteria=None,
            fts_criteria=None,
            exclude_self_connections=exclude_self_connections,
        )
        
        return await self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset
        )
    
    async def query_relation_connections(
        self,
        space_id: str,
        graph_id: str,
        source_entity_uris: Optional[List[str]] = None,
        destination_entity_uris: Optional[List[str]] = None,
        source_entity_criteria: Optional[EntityQueryCriteria] = None,
        destination_entity_criteria: Optional[EntityQueryCriteria] = None,
        relation_type_uris: Optional[List[str]] = None,
        direction: str = "outgoing",
        source_frame_criteria: Optional[List] = None,
        destination_frame_criteria: Optional[List] = None,
        sort_criteria: Optional[List[SortCriteria]] = None,
        exclude_self_connections: bool = True,
        page_size: int = 10,
        offset: int = 0,
        count_only: bool = False
    ) -> RelationQueryResponse:
        """
        Convenience method for querying relation-based connections.
        
        Find entities connected via Edge_hasKGRelation.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            source_entity_uris: Optional list of source entity URIs
            destination_entity_uris: Optional list of destination entity URIs
            source_entity_criteria: Optional criteria for source entities
            destination_entity_criteria: Optional criteria for destination entities
            relation_type_uris: Optional list of relation type URIs to filter by
            direction: Direction of relations: "outgoing", "incoming", or "bidirectional" (default: "outgoing")
            source_frame_criteria: Optional list of FrameCriteria for filtering source entities by frames/slots
            destination_frame_criteria: Optional list of FrameCriteria for filtering destination entities by frames/slots
            exclude_self_connections: Exclude connections from entity to itself (default: True)
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with relation connections
            
        Raises:
            VitalGraphClientError: If request fails
        """
        # Build relation query criteria
        criteria = KGQueryCriteria(
            query_type="relation",
            document_criteria=None,
            query_mode="edge",
            source_entity_uris=source_entity_uris,
            destination_entity_uris=destination_entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=destination_entity_criteria,
            relation_type_uris=relation_type_uris,
            direction=direction,
            source_frame_criteria=source_frame_criteria,
            destination_frame_criteria=destination_frame_criteria,
            shared_frame_types=None,
            frame_slot_criteria=None,
            frame_criteria=None,
            sort_criteria=sort_criteria,
            entity_property_filters=None,
            vector_criteria=None,
            multi_vector_criteria=None,
            geo_criteria=None,
            fts_criteria=None,
            exclude_self_connections=exclude_self_connections,
        )
        
        raw = await self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset,
            count_only=count_only
        )
        return RelationQueryResponse.from_raw(raw)
    
    async def query_frames(
        self,
        space_id: str,
        graph_id: str,
        frame_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        slot_criteria: Optional[List[SlotCriteria]] = None,
        sort_criteria: Optional[List[SortCriteria]] = None,
        entity_property_filters: Optional[List[EntityPropertyFilter]] = None,
        fts_criteria: Optional[FTSCriteria] = None,
        include_frame_graph: bool = False,
        page_size: int = 10,
        offset: int = 0,
        count_only: bool = False,
        include_total_count: TotalCountMode = TotalCountMode.NO,
    ) -> FrameQueryResponse:
        """
        Query frames matching criteria. Returns frame URIs + entity slot refs.
        
        This is Case 1 (frame as top-most object): find frames where entity slots
        point to specific entities, with optional detail slot filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_type: Optional frame type URI to filter by
            entity_type: Optional entity type URI (frames must belong to entity of this type)
            slot_criteria: Optional list of SlotCriteria for filtering by slot values
            include_frame_graph: Include structured frame graph data in results (default: False)
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with frame_results (List[FrameQueryResult])
            
        Raises:
            VitalGraphClientError: If request fails
        """
        source_entity_criteria = None
        if entity_type or entity_property_filters:
            source_entity_criteria = EntityQueryCriteria(
                search_string=None,
                entity_type=entity_type,
                frame_type=None,
                slot_criteria=None,
                sort_criteria=None,
                filters=None,
                entity_property_filters=entity_property_filters,
                vector_criteria=None,
                multi_vector_criteria=None,
                geo_criteria=None,
            )
        
        # Build frame_criteria from the slot_criteria and frame_type
        frame_criteria = None
        if frame_type or slot_criteria:
            frame_criteria = [FrameCriteria(
                frame_type=frame_type,
                negate=False,
                slot_criteria=slot_criteria,
                frame_criteria=None,
            )]
        
        criteria = KGQueryCriteria(
            query_type="frame_query",
            document_criteria=None,
            query_mode="edge",
            source_entity_criteria=source_entity_criteria,
            source_entity_uris=None,
            destination_entity_criteria=None,
            destination_entity_uris=None,
            relation_type_uris=None,
            direction="outgoing",
            source_frame_criteria=None,
            destination_frame_criteria=None,
            shared_frame_types=None,
            frame_slot_criteria=None,
            frame_criteria=frame_criteria,
            sort_criteria=sort_criteria,
            entity_property_filters=entity_property_filters,
            vector_criteria=None,
            multi_vector_criteria=None,
            geo_criteria=None,
            fts_criteria=fts_criteria,
            exclude_self_connections=True,
        )
        
        raw = await self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset,
            include_frame_graph=include_frame_graph,
            count_only=count_only,
            include_total_count=include_total_count,
        )
        return FrameQueryResponse.from_raw(raw)
    
    async def query_entities(
        self,
        space_id: str,
        graph_id: str,
        entity_type: Optional[str] = None,
        entity_uris: Optional[List[str]] = None,
        frame_criteria: Optional[List[FrameCriteria]] = None,
        sort_criteria: Optional[List[SortCriteria]] = None,
        entity_property_filters: Optional[List[EntityPropertyFilter]] = None,
        fts_criteria: Optional[FTSCriteria] = None,
        query_mode: str = "edge",
        include_entity_graph: bool = False,
        slot_projection: Optional[List[SlotProjection]] = None,
        property_projection: Optional[List[PropertyProjection]] = None,
        page_size: int = 10,
        offset: int = 0,
        count_only: bool = False,
        include_total_count: TotalCountMode = TotalCountMode.NO,
    ) -> KGEntityQueryResponse:
        """
        Query entities matching criteria. Returns entity URIs with correct total count.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_type: Optional entity type URI to filter by
            entity_uris: Optional list of specific entity URIs to filter
            frame_criteria: Optional list of FrameCriteria for filtering by frames/slots
            slot_projection: Optional list of SlotProjection columns — slot values
                to return for the entities of the page, read from the slot-sort
                table rather than by fetching each entity's graph (issues/208).
                Returned on the response as entity_slot_values: entity URI ->
                alias -> list of values.
            property_projection: Optional list of PropertyProjection columns —
                DIRECT entity properties, read from the quads and returned in
                the same entity_values map as the slot columns.
            query_mode: Query mode: 'edge' or 'direct' (default: 'edge')
            page_size: Number of results per page (default: 10)
            offset: Offset for pagination (default: 0)
            
        Returns:
            KGQueryResponse with entity_uris and total_count
            
        Raises:
            VitalGraphClientError: If request fails
        """
        source_entity_criteria = None
        if entity_type or entity_property_filters:
            source_entity_criteria = EntityQueryCriteria(
                search_string=None,
                entity_type=entity_type,
                frame_type=None,
                slot_criteria=None,
                sort_criteria=None,
                filters=None,
                entity_property_filters=entity_property_filters,
                vector_criteria=None,
                multi_vector_criteria=None,
                geo_criteria=None,
            )
        
        criteria = KGQueryCriteria(
            query_type="entity",
            document_criteria=None,
            query_mode=query_mode,
            source_entity_uris=entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=None,
            destination_entity_uris=None,
            relation_type_uris=None,
            direction="outgoing",
            source_frame_criteria=None,
            destination_frame_criteria=None,
            shared_frame_types=None,
            frame_slot_criteria=None,
            frame_criteria=frame_criteria,
            sort_criteria=sort_criteria,
            entity_property_filters=entity_property_filters,
            vector_criteria=None,
            multi_vector_criteria=None,
            geo_criteria=None,
            fts_criteria=fts_criteria,
            exclude_self_connections=True,
        )
        
        raw = await self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset,
            include_entity_graph=include_entity_graph,
            count_only=count_only,
            slot_projection=slot_projection,
            property_projection=property_projection,
            include_total_count=include_total_count,
        )
        response = KGEntityQueryResponse.from_raw(raw)
        
        # Hydrate entity_graphs quads → GraphObjects for client consistency
        if response.entity_graphs:
            from ..utils.format_helpers import deserialize_response_to_graphobjects, ClientWireFormat
            hydrated: Dict[str, list] = {}
            for uri, quads in response.entity_graphs.items():
                if quads:
                    hydrated[uri] = deserialize_response_to_graphobjects(
                        {"results": quads}, ClientWireFormat.JSON_QUADS
                    )
                else:
                    hydrated[uri] = []
            response.entity_graph_objects = hydrated
        
        return response
    
    async def query_documents(
        self,
        space_id: str,
        graph_id: str,
        # Document-specific criteria (all map to SPARQL patterns)
        document_type_uri: Optional[str] = None,
        search_scope: Optional[Literal["all", "segments", "originals", "summaries"]] = None,
        segment_method_uri: Optional[str] = None,
        segment_type_uri: Optional[str] = None,
        parent_document_uri: Optional[str] = None,
        content_type: Optional[str] = None,
        min_token_length: Optional[int] = None,
        max_token_length: Optional[int] = None,
        search_text: Optional[str] = None,
        fts_index_name: Optional[str] = None,
        document_uris: Optional[List[str]] = None,
        # Segmentation-aware response enrichment
        include_parent_context: bool = False,
        include_original_uri: bool = False,
        exclude_managed_segments: bool = True,
        include_segment_text: bool = False,
        group_by_document: bool = False,
        # Shared criteria (same as entity queries)
        vector_criteria: Optional[VectorSearchCriteria] = None,
        multi_vector_criteria: Optional[MultiVectorSearchCriteria] = None,
        geo_criteria: Optional[GeoSearchCriteria] = None,
        sort_criteria: Optional[List[SortCriteria]] = None,
        entity_property_filters: Optional[List[EntityPropertyFilter]] = None,
        frame_criteria: Optional[List[FrameCriteria]] = None,
        # Pagination
        page_size: int = 10,
        offset: int = 0,
        count_only: bool = False,
    ) -> DocumentQueryResponse:
        """Query KGDocuments matching criteria. Returns document URIs.

        Document-specific fields are packed into DocumentSearchCriteria;
        shared fields (vector, geo, sort, etc.) go on KGQueryCriteria.
        """
        doc_criteria = DocumentSearchCriteria(
            document_type_uri=document_type_uri,
            search_scope=search_scope,
            segment_method_uri=segment_method_uri,
            segment_type_uri=segment_type_uri,
            parent_document_uri=parent_document_uri,
            content_type=content_type,
            min_token_length=min_token_length,
            max_token_length=max_token_length,
            search_text=search_text,
            fts_index_name=fts_index_name,
            include_parent_context=include_parent_context,
            include_original_uri=include_original_uri,
            exclude_managed_segments=exclude_managed_segments,
            include_segment_text=include_segment_text,
            group_by_document=group_by_document,
        )
        criteria = KGQueryCriteria(
            query_type="document",
            document_criteria=doc_criteria,
            query_mode="edge",
            source_entity_criteria=None,
            source_entity_uris=document_uris,
            destination_entity_criteria=None,
            destination_entity_uris=None,
            relation_type_uris=None,
            direction="outgoing",
            source_frame_criteria=None,
            destination_frame_criteria=None,
            shared_frame_types=None,
            frame_slot_criteria=None,
            frame_criteria=frame_criteria,
            sort_criteria=sort_criteria,
            entity_property_filters=entity_property_filters,
            vector_criteria=vector_criteria,
            multi_vector_criteria=multi_vector_criteria,
            geo_criteria=geo_criteria,
            fts_criteria=None,
            exclude_self_connections=True,
        )
        raw = await self.query_connections(
            space_id=space_id, graph_id=graph_id,
            criteria=criteria, page_size=page_size,
            offset=offset, count_only=count_only,
        )
        return DocumentQueryResponse.from_raw(raw)
