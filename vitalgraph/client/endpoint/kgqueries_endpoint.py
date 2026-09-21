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
        property_projection: Optional[List[PropertyProjection]] = None
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
                property_projection=property_projection
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
            source_entity_uris=source_entity_uris,
            destination_entity_uris=destination_entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=destination_entity_criteria,
            shared_frame_types=shared_frame_types,
            exclude_self_connections=exclude_self_connections
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
            source_entity_uris=source_entity_uris,
            destination_entity_uris=destination_entity_uris,
            source_entity_criteria=source_entity_criteria,
            destination_entity_criteria=destination_entity_criteria,
            relation_type_uris=relation_type_uris,
            direction=direction,
            source_frame_criteria=source_frame_criteria,
            destination_frame_criteria=destination_frame_criteria,
            sort_criteria=sort_criteria,
            exclude_self_connections=exclude_self_connections
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
        include_frame_graph: bool = False,
        page_size: int = 10,
        offset: int = 0,
        count_only: bool = False
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
        if entity_type:
            source_entity_criteria = EntityQueryCriteria(entity_type=entity_type)
        
        # Build frame_criteria from the slot_criteria and frame_type
        frame_criteria = None
        if frame_type or slot_criteria:
            frame_criteria = [FrameCriteria(
                frame_type=frame_type,
                slot_criteria=slot_criteria
            )]
        
        criteria = KGQueryCriteria(
            query_type="frame_query",
            source_entity_criteria=source_entity_criteria,
            frame_criteria=frame_criteria,
            sort_criteria=sort_criteria
        )
        
        raw = await self.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
            offset=offset,
            include_frame_graph=include_frame_graph,
            count_only=count_only
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
        query_mode: str = "edge",
        include_entity_graph: bool = False,
        slot_projection: Optional[List[SlotProjection]] = None,
        property_projection: Optional[List[PropertyProjection]] = None,
        page_size: int = 10,
        offset: int = 0,
        count_only: bool = False
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
                entity_type=entity_type,
                entity_property_filters=entity_property_filters
            )
        
        criteria = KGQueryCriteria(
            query_type="entity",
            query_mode=query_mode,
            source_entity_uris=entity_uris,
            source_entity_criteria=source_entity_criteria,
            frame_criteria=frame_criteria,
            sort_criteria=sort_criteria,
            entity_property_filters=entity_property_filters
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
            property_projection=property_projection
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
            source_entity_uris=document_uris,
            vector_criteria=vector_criteria,
            multi_vector_criteria=multi_vector_criteria,
            geo_criteria=geo_criteria,
            sort_criteria=sort_criteria,
            entity_property_filters=entity_property_filters,
            frame_criteria=frame_criteria,
        )
        raw = await self.query_connections(
            space_id=space_id, graph_id=graph_id,
            criteria=criteria, page_size=page_size,
            offset=offset, count_only=count_only,
        )
        return DocumentQueryResponse.from_raw(raw)

    # ------------------------------------------------------------------
    # Slot-text (message) search
    # ------------------------------------------------------------------

    HALEY_NS = "http://vital.ai/ontology/haley-ai-kg#"
    VG_NS = "http://vital.ai/ontology/vitalgraph#"
    VITAL_CORE_NS = "http://vital.ai/ontology/vital-core#"

    async def search_messages(
        self,
        space_id: str,
        graph_id: str,
        text: str,
        fts_index_name: str,
        slot_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_uris: Optional[List[str]] = None,
        include_text: bool = True,
        page_size: int = 25,
        offset: int = 0,
        after: Optional[tuple] = None,
        order_by: str = "relevance",
    ) -> "MessageSearchResponse":
        """Ranked full-text search over KG slot values.

        Searches the SLOTS, not the entities, and returns the entity graph each
        match belongs to. That granularity is deliberate: a conversation search
        wants to know WHICH message matched, and slots are what the FTS index
        holds (see `planning/planning_vector_geo/nurture_message_keyword_search_plan.md`
        §4, Option A). It needs no entity-level rollup and no populator
        traversal.

        Args:
            space_id: Space identifier.
            graph_id: Graph URI to search within.
            text: Query text. Parsed with `websearch_to_tsquery`, so quoted
                phrases, `or`, and `-exclusion` all work, and no input raises.
            fts_index_name: FTS index to search. REQUIRED and deliberately not
                defaulted — this search is only as fast as the index it hits,
                and guessing one would hide that from the caller.
            slot_type: Restrict to one `hasKGSlotType`, e.g. a message-content
                slot. STRONGLY recommended — see the cost note below.
            entity_type: Restrict to slots owned by entities of this
                `hasKGEntityType`.
            entity_uris: Restrict to slots inside these specific entity graphs.
            order_by: "relevance" (default) or "slot".

                "slot" returns matches in URI order instead of by score, and
                is DRAMATICALLY cheaper on broad queries because nothing has to
                be scored: ranked top-N on GIN must compute `ts_rank_cd` for
                EVERY match before LIMIT applies, while an unranked page stops
                at `page_size`. Measured on a term matching 118,702 of 321,276
                messages: 357-848 ms ranked against 2.3 ms unranked-stable.

                It is not a free win in general — it is a free win exactly
                where ranking carries no information, which on this corpus is
                the same place. Score variance collapses as the match set
                grows: 7 matches gave 7 distinct scores, 4,320 gave 75, and
                80,705 gave ONE. A "top 25 by relevance" over a single score is
                arbitrary, so ordering by URI loses nothing real and costs two
                orders of magnitude less.

                Check before assuming that holds elsewhere — the diagnostic is
                `count(DISTINCT ts_rank_cd(...))` against the match count, and
                `rank_normalization` on the index changes it (norm=1 took that
                118,702-match query from 3 distinct scores to 101).

            include_text: Project the matching slot value.
            page_size: Rows per page.
            offset: OFFSET paging, and the right default. Measured flat with
                depth on this shape — 147 ms at 0, 328 at 1,000, 173 at 4,000
                — because the cost is scoring every match, not discarding the
                skipped rows.
            after: KEYSET cursor, `(score, slot_uri)` of the last row of the
                previous page. NOT RECOMMENDED — measured SLOWER than
                `offset` here (870-3,264 ms vs 174-549 ms), because the sort
                key is computed rather than indexed so there is no position to
                seek to. Kept because it becomes correct-and-fast the moment
                the rank is materialised or the index can order by it.

                The cursor is the FULL sort key, not just the score:
                `ts_rank_cd` ties heavily here, so a score-only cursor would
                either repeat or skip every row sharing a score at the page
                boundary.

        Returns:
            MessageSearchResponse — hits best-first, plus the SPARQL executed.

        COST, because the signature hides it otherwise:

            `vg:textSearch` compiles to a CORRELATED SCALAR SUBQUERY keyed on
            the bound variable's uuid. It scores rows the rest of the pattern
            has already produced; it cannot drive the query from the GIN index.
            So the cost tracks the size of the candidate set, NOT the number of
            matches, and a search with no `slot_type`, `entity_type` or
            `entity_uris` probes the FTS table once per slot in the graph.

            Pass the narrowest scope you can. On a measured KG space,
            constraining to one slot type cut the candidate set 55.7x
            (180,878 text slots -> 3,249 message slots).

            The response carries `.sparql` so this is inspectable rather than
            mysterious.
        """
        from ...model.kgqueries_model import MessageHit, MessageSearchResponse
        from ...model.result_status import OperationStatus

        self._check_connection()
        validate_required_params(
            space_id=space_id, graph_id=graph_id, text=text,
            fts_index_name=fts_index_name,
        )

        sparql = self._build_message_search_sparql(
            graph_id=graph_id, text=text, fts_index_name=fts_index_name,
            slot_type=slot_type, entity_type=entity_type,
            entity_uris=entity_uris, include_text=include_text,
            page_size=page_size, offset=offset, after=after,
            order_by=order_by,
        )

        from ...model.sparql_model import SPARQLQueryRequest
        raw = await self.client.sparql.execute_sparql_query(
            space_id, SPARQLQueryRequest(query=sparql))

        hits: List[MessageHit] = []
        bindings = ((raw.results or {}).get("bindings") or []) if raw else []
        for b in bindings:
            def val(name):
                cell = b.get(name)
                return cell.get("value") if isinstance(cell, dict) else None
            score = val("score")
            hits.append(MessageHit(
                entity_uri=val("entity"),
                slot_uri=val("slot") or "",
                frame_uri=val("frame"),
                text=val("text"),
                score=float(score) if score not in (None, "") else 0.0,
            ))

        next_after = ((hits[-1].score, hits[-1].slot_uri)
                      if len(hits) == page_size else None)
        return MessageSearchResponse(
            status=OperationStatus.OK if hits else OperationStatus.NOT_FOUND,
            message=f"{len(hits)} match(es)" if hits else "No matches",
            hits=hits, sparql=sparql, index_name=fts_index_name,
            next_after=next_after, ordered_by=order_by,
        )

    def _build_message_search_sparql(
        self, *, graph_id: str, text: str, fts_index_name: str,
        slot_type: Optional[str], entity_type: Optional[str],
        entity_uris: Optional[List[str]], include_text: bool,
        page_size: int, offset: int, after: Optional[tuple] = None,
        order_by: str = "relevance",
    ) -> str:
        """Build the slot-search SPARQL. Split out so it is testable without a
        server, and so the generated query can be reviewed in isolation."""
        from ...sparql.utils import escape_sparql_string

        h, vg, vc = self.HALEY_NS, self.VG_NS, self.VITAL_CORE_NS
        # NB: this escape_sparql_string returns the value ALREADY WRAPPED in
        # quotes. The same-named function in sparql/kg_query_builder.py does
        # not, and callers there add their own. Do not add quotes here.
        quoted_text = escape_sparql_string(text)

        unranked = (order_by or "relevance").lower() == "slot"
        lines: List[str] = []
        # Put the narrowing patterns FIRST. vg:textSearch scores what the BGP
        # already produced, so anything that shrinks the BGP shrinks the probe
        # count; ordering them ahead of the BIND is how that intent is stated.
        if slot_type:
            lines.append(f"    ?slot <{h}hasKGSlotType> <{slot_type}> .")
        # BIND ?entity DIRECTLY from hasKGGraphURI. Its object IS the entity's
        # subject term — verified by round trip on production data — so the
        # `?entity vc:URIProp ?entityUri` hop that used to sit here joined a
        # term to itself.
        #
        # It was not free. `URIProp` is carried by EVERY subject in the graph,
        # so that pattern gave the planner a leaf with no selectivity, and it
        # built the entity side by walking all 84,291 NurtureActions through it
        # before meeting the FTS-narrowed slot side: `Index Scan ... q2
        # (actual rows=1.00 loops=84291)` for 4,320 surviving rows.
        lines.append(f"    ?slot <{h}hasKGGraphURI> ?entity .")
        if entity_type:
            lines.append(f"    ?entity <{h}hasKGEntityType> <{entity_type}> .")
        if entity_uris:
            uris = " ".join(f"<{u}>" for u in entity_uris)
            lines.append(f"    VALUES ?entity {{ {uris} }}")
        # REQUIRED, not OPTIONAL, and that is a performance decision as much
        # as a modelling one.
        #
        # OPTIONAL becomes a LEFT JOIN in the plan, and `push_filters` refuses
        # to descend into one (`_find_bgp_binding` rejects LEFT_JOIN/UNION/
        # MINUS, correctly — pushing into the preserved side of a left join
        # changes "keep the row, unbound" into "drop the row"). So a single
        # OPTIONAL anywhere in this pattern silently disables the
        # `vg:textSearch` push-down, and the query reverts to scoring every
        # candidate. Measured: the OPTIONAL form exceeded the client's 60 s
        # budget where the pushed form is ~56-77 ms.
        #
        # Nothing is lost by requiring them. A slot is IN the FTS index only
        # because it had text, so `hasTextSlotValue` is present by
        # construction; measured on the loaded production export, all 321,276
        # indexed slots carry both this and `hasFrameGraphURI`, zero missing.
        if include_text:
            lines.append(f"    ?slot <{h}hasTextSlotValue> ?text .")
        lines.append(f"    ?slot <{h}hasFrameGraphURI> ?frame .")
        if unranked:
            # vg:textMatch — BOOLEAN, no score, no EXTEND. Dropping ?score from
            # the projection is NOT enough to stop it being computed:
            # `emit_extend` emits the companion columns whether or not the
            # outer SELECT reads them, so an earlier version of this mode still
            # ran `ts_rank_cd` twice per row and measured no faster.
            lines.append(
                f'    FILTER(<{vg}textMatch>(?slot, {quoted_text}, '
                f'"{fts_index_name}"))')
        else:
            lines.append(
                f'    BIND(<{vg}textSearch>(?slot, {quoted_text}, '
                f'"{fts_index_name}") AS ?score)')
        # BOUND, not `> 0`: a non-matching row yields NULL, and a legitimate
        # match can score 0.0 when every query term is common enough to carry
        # no weight. Filtering on `> 0` would silently drop those.
        if not unranked:
            lines.append("    FILTER(BOUND(?score))")
        if after:
            # KEYSET PAGING — MEASURED SLOWER, KEPT ONLY AS AN OPT-IN.
            #
            # Keyset wins when the sort key is INDEXED and the scan can seek to
            # a position. `ts_rank_cd` is computed per row, not stored, so
            # there is nothing to seek: every candidate is scored either way
            # and this only adds a filter on top. Measured on a 4,320-match
            # query, pages 1-5: keyset 870-3,264 ms against OFFSET 174-549 ms.
            #
            # OFFSET is also not the problem it looked like. Repeated, it is
            # flat — 147 ms at offset 0, 328 at 1,000, 173 at 4,000 — because
            # the cost is scoring all matches, which happens regardless of how
            # many rows are then discarded. An earlier single sample suggested
            # otherwise and was noise.
            #
            # (score, slot) strictly after the cursor, under ORDER BY
            # DESC(?score) ?slot. Both arms are needed: the first advances past
            # lower scores, the second walks the TIE at the boundary. Omitting
            # the second would drop every row sharing the cursor's score.
            a_score, a_slot = after
            lines.append(
                f"    FILTER(?score < {float(a_score)} || "
                f"(?score = {float(a_score)} && STR(?slot) > "
                f"{escape_sparql_string(str(a_slot))}))")

        body = "\n".join(lines)
        # ?score is NOT projected when unranked. Projecting it would compute
        # the correlated subquery for every candidate row and give back the
        # cost the mode exists to avoid; the BIND stays only so
        # `push_text_search` still has a filter to consume into the BGP.
        select = ("?entity ?slot ?frame"
                  + ("" if unranked else " ?score")
                  + (" ?text" if include_text else ""))
        return (
            f"SELECT {select}\n"
            f"WHERE {{\n"
            f"  GRAPH <{graph_id}> {{\n{body}\n  }}\n"
            f"}}\n"
            # ?slot is a TIEBREAKER, not decoration. `ts_rank_cd` ties
            # heavily on this corpus — the top score is shared by many
            # messages — and ORDER BY score alone is therefore not a TOTAL
            # order. Two OFFSET pages of an unstable sort overlap and drop
            # rows: measured, page 1 and page 2 of a 10-row page shared 6 of
            # 10 slots and together did not equal the 20-row page. A caller
            # sees a plausible list with duplicates and gaps, never an error.
            + ("ORDER BY ?slot\n" if unranked else
               # ?slot is a TIEBREAKER, not decoration. `ts_rank_cd` ties
               # heavily on this corpus — the top score is shared by many
               # messages — and ORDER BY score alone is therefore not a TOTAL
               # order. Two OFFSET pages of an unstable sort overlap and drop
               # rows: measured, page 1 and page 2 of a 10-row page shared 6 of
               # 10 slots and together did not equal the 20-row page. A caller
               # sees a plausible list with duplicates and gaps, never an error.
               "ORDER BY DESC(?score) ?slot\n")
            + (f"LIMIT {int(page_size)}" if after
               else f"LIMIT {int(page_size)} OFFSET {int(offset)}")
        )
