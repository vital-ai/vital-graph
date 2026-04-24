"""
KG Queries REST API endpoint for VitalGraph.

This module provides REST API endpoints for entity-to-entity connection queries.
KG queries support two distinct query types:
1. Relation-based queries: Find entities connected via Edge_hasKGRelation
2. Frame-based queries: Find entities connected via shared KGFrames
"""

import asyncio
import logging
import re
import time as _time
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field

from ..model.kgqueries_model import (
    KGQueryRequest,
    KGQueryResponse,
    RelationConnection,
    FrameConnection,
    EntitySlotRef,
    FrameQueryResult
)


class KGQueriesEndpoint:
    """REST API endpoint for KG entity-to-entity connection queries."""
    
    def __init__(self, space_manager, auth_dependency):
        """Initialize KG Queries endpoint with space manager and authentication."""
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(__name__)
        self.router = APIRouter()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
        
        # Initialize KG criteria query builder for entity queries with slot criteria
        from ..sparql.kg_query_builder import KGQueryCriteriaBuilder
        self.query_builder = KGQueryCriteriaBuilder()
        
        # Initialize connection query builder for relation and frame queries
        from ..sparql.kg_connection_query_builder import KGConnectionQueryBuilder
        self.connection_query_builder = KGConnectionQueryBuilder()
        
        # Set up routes
        self._setup_routes()
    
    @staticmethod
    def _pretty_sql(sql: str) -> str:
        """Pretty-print SQL by inserting newlines before major keywords."""
        kw = r'\b(SELECT|FROM|WHERE|JOIN|INNER JOIN|LEFT JOIN|LEFT OUTER JOIN|CROSS JOIN|ON|AND|OR|ORDER BY|GROUP BY|HAVING|LIMIT|OFFSET|UNION ALL|UNION|VALUES|WITH|AS)\b'
        out = re.sub(kw, r'\n\1', sql, flags=re.IGNORECASE)
        # indent sub-selects
        out = out.replace('(SELECT', '(\n  SELECT').replace('( SELECT', '(\n  SELECT')
        return out.strip()
    
    def _setup_routes(self):
        """Set up FastAPI routes for KG Queries operations."""
        
        @self.router.post("/kgqueries", response_model=KGQueryResponse, tags=["KG Queries"])
        async def query_connections(
            query_request: KGQueryRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Query entities connected via relations or shared frames based on query_type.
            
            Supports two distinct query types:
            - relation: Find entities connected via Edge_hasKGRelation
            - frame: Find entities connected via shared KGFrames
            
            Args:
                query_request: Query criteria and pagination
                space_id: Space identifier
                graph_id: Graph identifier
                
            Returns:
                KGQueryResponse with connections based on query_type
            """
            # Debug logging at endpoint entry
            self.logger.info(f"FastAPI received query_request as dict: {query_request.model_dump()}")
            self.logger.info(f"FastAPI endpoint received query_request.criteria.frame_criteria: {query_request.criteria.frame_criteria}")
            return await self._query_connections(space_id, graph_id, query_request, current_user)
        
    
    async def _query_connections(self, space_id: str, graph_id: str, query_request: KGQueryRequest, current_user: Dict) -> KGQueryResponse:
        """Query entities connected via relations or shared frames based on query_type."""
        try:
            query_type = query_request.criteria.query_type
            self.logger.info(f"Executing {query_type} query in space {space_id}, graph {graph_id}")
            
            try:
                from ..db.sparql_sql.auto_analyze import get_last_analyze_time
                import time as _time
                last_at = get_last_analyze_time(space_id)
                age = f"{_time.monotonic() - last_at:.1f}s ago" if last_at is not None else "never"
                self.logger.debug(f"last_analyze for '{space_id}': {age}")
            except Exception:
                pass
            
            # Validate query type
            if query_type not in ["relation", "frame", "entity", "frame_query"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid query_type: {query_type}. Must be 'relation', 'frame', 'entity', or 'frame_query'"
                )
            
            # Get backend implementation via generic interface
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            # Execute appropriate query type
            if query_type == "relation":
                return await self._execute_relation_query(backend, space_id, graph_id, query_request)
            elif query_type == "entity":
                return await self._execute_entity_query(backend, space_id, graph_id, query_request)
            elif query_type == "frame_query":
                return await self._execute_frame_query_case(backend, space_id, graph_id, query_request)
            else:  # query_type == "frame"
                return await self._execute_frame_query(backend, space_id, graph_id, query_request)
                
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing {query_request.criteria.query_type} query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to execute KG query: {str(e)}"
            )
    
    async def _execute_relation_query(self, backend, space_id: str, graph_id: str, query_request: KGQueryRequest) -> KGQueryResponse:
        """Execute relation-based query."""
        try:
            # Build SPARQL query for relation connections
            sparql_query = self.connection_query_builder.build_relation_query(
                query_request.criteria, graph_id
            )
            
            self.logger.info(f"Generated relation SPARQL query:\n{sparql_query}")
            
            # Execute SPARQL query via backend interface
            t0 = _time.monotonic()
            results = await backend.execute_sparql_query(space_id, sparql_query)
            t_query = _time.monotonic()
            
            # Log the final SQL if returned by the backend (fire-and-forget, non-blocking)
            if results.get('sql') and self.logger.isEnabledFor(logging.DEBUG):
                _sql = results['sql']
                _logger = self.logger
                _pretty = self._pretty_sql
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: _logger.debug(f"Final SQL ({len(_sql)} chars):\n{_pretty(_sql)}"))
            
            # Convert results to RelationConnection objects
            connections = []
            if results and results.get("results") and results["results"].get("bindings"):
                for result in results["results"]["bindings"]:
                    connection = RelationConnection(
                        source_entity_uri=result.get('source_entity', {}).get('value', ''),
                        destination_entity_uri=result.get('destination_entity', {}).get('value', ''),
                        relation_edge_uri=result.get('relation_edge', {}).get('value', ''),
                        relation_type_uri=result.get('relation_type', {}).get('value', '')
                    )
                    connections.append(connection)
            
            # Apply pagination
            total_count = len(connections)
            start_idx = query_request.offset
            end_idx = start_idx + query_request.page_size
            paginated_connections = connections[start_idx:end_idx]
            
            self.logger.info(f"Relation query: {total_count} results, {len(paginated_connections)} returned, {(t_query - t0)*1000:.0f}ms")
            
            return KGQueryResponse(
                query_type="relation",
                relation_connections=paginated_connections,
                frame_connections=None,
                total_count=total_count,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
            
        except Exception as e:
            self.logger.error(f"Error executing relation query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to execute relation query: {str(e)}"
            )
    
    async def _execute_entity_query(self, backend, space_id: str, graph_id: str, query_request: KGQueryRequest) -> KGQueryResponse:
        """Execute entity query — return matching entity URIs with correct total count."""
        try:
            from ..sparql.kg_query_builder import EntityQueryCriteria as BuilderEntityQueryCriteria
            from ..sparql.kg_query_builder import FrameCriteria as BuilderFrameCriteria
            from ..sparql.kg_query_builder import SlotCriteria as BuilderSlotCriteria
            
            criteria = query_request.criteria
            
            # Reuse the same frame criteria conversion as the frame query path
            def convert_frame_criteria(frame_crit):
                builder_slots = None
                if frame_crit.slot_criteria:
                    builder_slots = [
                        BuilderSlotCriteria(
                            slot_type=s.slot_type,
                            slot_class_uri=s.slot_class_uri,
                            value=s.value,
                            comparator=s.comparator or ("eq" if s.value else None)
                        ) for s in frame_crit.slot_criteria
                    ]
                builder_nested = None
                if frame_crit.frame_criteria:
                    builder_nested = [convert_frame_criteria(fc) for fc in frame_crit.frame_criteria]
                return BuilderFrameCriteria(
                    frame_type=frame_crit.frame_type,
                    negate=getattr(frame_crit, 'negate', False),
                    slot_criteria=builder_slots,
                    frame_criteria=builder_nested
                )
            
            builder_frame_criteria = None
            if criteria.frame_criteria:
                builder_frame_criteria = [convert_frame_criteria(fc) for fc in criteria.frame_criteria]
            
            use_edge_pattern = (criteria.query_mode == "edge") if hasattr(criteria, 'query_mode') else True
            
            entity_criteria = BuilderEntityQueryCriteria(
                entity_type=criteria.source_entity_criteria.entity_type if criteria.source_entity_criteria else None,
                entity_uris=criteria.source_entity_uris,
                frame_criteria=builder_frame_criteria,
                use_edge_pattern=use_edge_pattern
            )
            
            # Build paginated query + count query
            sparql_query = self.query_builder.build_entity_query_sparql(
                entity_criteria, graph_id,
                query_request.page_size, query_request.offset
            )
            count_query = self.query_builder.build_entity_count_query_sparql(
                entity_criteria, graph_id
            )
            
            self.logger.info(f"Generated entity SPARQL query:\n{sparql_query}")
            
            # Execute both in parallel
            t0 = _time.monotonic()
            results, count_results = await asyncio.gather(
                backend.execute_sparql_query(space_id, sparql_query),
                backend.execute_sparql_query(space_id, count_query),
            )
            t_query = _time.monotonic()
            
            # Extract total count
            total_count = 0
            if count_results and count_results.get("results") and count_results["results"].get("bindings"):
                count_bindings = count_results["results"]["bindings"]
                if count_bindings:
                    total_count = int(count_bindings[0].get('count', {}).get('value', 0))
            
            # Extract entity URIs
            entity_uris = []
            if results and results.get("results") and results["results"].get("bindings"):
                for binding in results["results"]["bindings"]:
                    uri = binding.get('entity', {}).get('value', '')
                    if uri:
                        entity_uris.append(uri)
            
            self.logger.info(f"Entity query: {len(entity_uris)} results (total={total_count}), {(t_query - t0)*1000:.0f}ms")
            
            # Optionally fetch entity graphs
            entity_graphs = None
            if query_request.include_entity_graph and entity_uris:
                t_eg0 = _time.monotonic()
                entity_graphs = await self._fetch_entity_graphs(backend, space_id, graph_id, entity_uris)
                t_eg = _time.monotonic()
                self.logger.info(f"Entity graph fetch: {len(entity_uris)} entities, {(t_eg - t_eg0)*1000:.0f}ms")
            
            return KGQueryResponse(
                query_type="entity",
                entity_uris=entity_uris,
                entity_graphs=entity_graphs,
                total_count=total_count,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
            
        except Exception as e:
            self.logger.error(f"Error executing entity query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to execute entity query: {str(e)}"
            )
    
    async def _execute_frame_query(self, backend, space_id: str, graph_id: str, query_request: KGQueryRequest) -> KGQueryResponse:
        """Execute frame-based query using entity query with slot criteria."""
        try:
            # Convert KGQueryCriteria to EntityQueryCriteria for the query builder
            from ..sparql.kg_query_builder import EntityQueryCriteria as BuilderEntityQueryCriteria
            from ..sparql.kg_query_builder import FrameCriteria as BuilderFrameCriteria
            from ..sparql.kg_query_builder import SlotCriteria as BuilderSlotCriteria
            
            criteria = query_request.criteria
            
            # Helper function to recursively convert frame criteria
            def convert_frame_criteria(frame_crit):
                """Recursively convert FrameCriteria including nested frame_criteria."""
                # Convert nested slot criteria
                builder_slots = None
                if frame_crit.slot_criteria:
                    builder_slots = []
                    for slot_crit in frame_crit.slot_criteria:
                        builder_slots.append(BuilderSlotCriteria(
                            slot_type=slot_crit.slot_type,
                            slot_class_uri=slot_crit.slot_class_uri,
                            value=slot_crit.value,
                            comparator=slot_crit.comparator or ("eq" if slot_crit.value else None)
                        ))
                
                # Recursively convert nested frame criteria (for hierarchical structures)
                builder_nested_frames = None
                if frame_crit.frame_criteria:
                    builder_nested_frames = []
                    for nested_frame_crit in frame_crit.frame_criteria:
                        builder_nested_frames.append(convert_frame_criteria(nested_frame_crit))
                
                return BuilderFrameCriteria(
                    frame_type=frame_crit.frame_type,
                    negate=getattr(frame_crit, 'negate', False),
                    slot_criteria=builder_slots,
                    frame_criteria=builder_nested_frames
                )
            
            # Convert frame criteria (with nested slot criteria and nested frame criteria)
            builder_frame_criteria = None
            if criteria.frame_criteria:
                builder_frame_criteria = []
                for frame_crit in criteria.frame_criteria:
                    builder_frame_criteria.append(convert_frame_criteria(frame_crit))
            
            self.logger.info(f"Converted builder_frame_criteria count: {len(builder_frame_criteria) if builder_frame_criteria else 0}")
            
            # Build entity query criteria
            # Map query_mode to use_edge_pattern: "edge" -> True, "direct" -> False
            use_edge_pattern = (criteria.query_mode == "edge") if hasattr(criteria, 'query_mode') else True
            
            entity_criteria = BuilderEntityQueryCriteria(
                entity_type=criteria.source_entity_criteria.entity_type if criteria.source_entity_criteria else None,
                entity_uris=criteria.source_entity_uris,  # Filter by specific entity URIs if provided
                frame_criteria=builder_frame_criteria,
                use_edge_pattern=use_edge_pattern  # Use query_mode from request ("edge" or "direct")
            )
            
            self.logger.info(f"Entity criteria: entity_type={entity_criteria.entity_type}, frame_criteria count={len(entity_criteria.frame_criteria) if entity_criteria.frame_criteria else 0}")
            
            # Build SPARQL query for entities matching criteria
            sparql_query = self.query_builder.build_entity_query_sparql(
                entity_criteria, 
                graph_id,
                query_request.page_size,
                query_request.offset
            )
            
            self.logger.info(f"Generated frame SPARQL query:\n{sparql_query}")
            
            # Build count query (same WHERE clause, no LIMIT/OFFSET)
            count_query = self.query_builder.build_entity_count_query_sparql(
                entity_criteria, graph_id
            )
            
            # Execute both queries (paginated results + total count)
            t0 = _time.monotonic()
            results, count_results = await asyncio.gather(
                backend.execute_sparql_query(space_id, sparql_query),
                backend.execute_sparql_query(space_id, count_query),
            )
            t_query = _time.monotonic()
            
            # Log the final SQL if returned by the backend (fire-and-forget, non-blocking)
            if results.get('sql') and self.logger.isEnabledFor(logging.DEBUG):
                _sql = results['sql']
                _logger = self.logger
                _pretty = self._pretty_sql
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: _logger.debug(f"Final SQL ({len(_sql)} chars):\n{_pretty(_sql)}"))
            
            # Extract total count from COUNT query
            total_count = 0
            if count_results and count_results.get("results") and count_results["results"].get("bindings"):
                count_bindings = count_results["results"]["bindings"]
                if count_bindings:
                    total_count = int(count_bindings[0].get('count', {}).get('value', 0))
            
            # Convert results to FrameConnection objects
            # For now, return entities as "connections" where source is the entity
            connections = []
            if results and results.get("results") and results["results"].get("bindings"):
                # Get frame type from frame_criteria if available
                frame_type_uri = ""
                if entity_criteria.frame_criteria and len(entity_criteria.frame_criteria) > 0:
                    frame_type_uri = entity_criteria.frame_criteria[0].frame_type or ""
                
                for result in results["results"]["bindings"]:
                    entity_uri = result.get('entity', {}).get('value', '')
                    # Create a connection representing the entity that matches the criteria
                    connection = FrameConnection(
                        source_entity_uri=entity_uri,
                        destination_entity_uri="",  # No destination for entity queries
                        shared_frame_uri="",
                        frame_type_uri=frame_type_uri
                    )
                    connections.append(connection)
            
            self.logger.info(f"Frame query: {len(connections)} results (total={total_count}), {(t_query - t0)*1000:.0f}ms")
            
            return KGQueryResponse(
                query_type="frame",
                relation_connections=None,
                frame_connections=connections,
                total_count=total_count,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
            
        except Exception as e:
            self.logger.error(f"Error executing frame query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to execute frame query: {str(e)}"
            )


    async def _execute_frame_query_case(self, backend, space_id: str, graph_id: str, query_request: KGQueryRequest) -> KGQueryResponse:
        """Execute frame_query — find frames matching criteria, return frame URIs + entity slot refs."""
        try:
            from ..sparql.kg_query_builder import FrameQueryCriteria as BuilderFrameQueryCriteria
            from ..sparql.kg_query_builder import SlotCriteria as BuilderSlotCriteria
            
            criteria = query_request.criteria
            
            # Convert slot criteria from request model to builder model
            builder_slot_criteria = None
            if criteria.frame_criteria and len(criteria.frame_criteria) > 0:
                fc = criteria.frame_criteria[0]  # Top-level frame criteria
                if fc.slot_criteria:
                    builder_slot_criteria = [
                        BuilderSlotCriteria(
                            slot_type=s.slot_type,
                            slot_class_uri=s.slot_class_uri,
                            value=s.value,
                            comparator=s.comparator or ("eq" if s.value else None)
                        ) for s in fc.slot_criteria
                    ]
            
            # Get frame_type from frame_criteria if provided
            frame_type = None
            if criteria.frame_criteria and len(criteria.frame_criteria) > 0:
                frame_type = criteria.frame_criteria[0].frame_type
            
            # Build frame query criteria
            frame_query_criteria = BuilderFrameQueryCriteria(
                frame_type=frame_type,
                entity_type=criteria.source_entity_criteria.entity_type if criteria.source_entity_criteria else None,
                slot_criteria=builder_slot_criteria
            )
            
            # Build paginated SPARQL query for frames
            sparql_query = self.query_builder.build_frame_query_sparql(
                frame_query_criteria, graph_id,
                query_request.page_size, query_request.offset
            )
            
            # Build count query for frames
            count_query = self._build_frame_count_query(
                frame_query_criteria, graph_id
            )
            
            self.logger.info(f"Generated frame_query SPARQL:\n{sparql_query}")
            
            # Execute both in parallel
            t0 = _time.monotonic()
            results, count_results = await asyncio.gather(
                backend.execute_sparql_query(space_id, sparql_query),
                backend.execute_sparql_query(space_id, count_query),
            )
            t_query = _time.monotonic()
            
            # Extract total count
            total_count = 0
            if count_results and count_results.get("results") and count_results["results"].get("bindings"):
                count_bindings = count_results["results"]["bindings"]
                if count_bindings:
                    total_count = int(count_bindings[0].get('count', {}).get('value', 0))
            
            # Extract frame URIs
            frame_uris = []
            if results and results.get("results") and results["results"].get("bindings"):
                for binding in results["results"]["bindings"]:
                    uri = binding.get('frame', {}).get('value', '')
                    if uri:
                        frame_uris.append(uri)
            
            # For each frame, fetch entity slot refs (includes frame_type)
            frame_results = []
            if frame_uris:
                entity_refs_query = self._build_entity_slot_refs_query(frame_uris, graph_id)
                self.logger.info(f"Fetching entity slot refs for {len(frame_uris)} frames")
                refs_results = await backend.execute_sparql_query(space_id, entity_refs_query)
                
                # Group entity refs and frame types by frame URI
                refs_by_frame: Dict[str, List[EntitySlotRef]] = {uri: [] for uri in frame_uris}
                frame_types: Dict[str, str] = {}
                if refs_results and refs_results.get("results") and refs_results["results"].get("bindings"):
                    for binding in refs_results["results"]["bindings"]:
                        f_uri = binding.get('frame', {}).get('value', '')
                        slot_type = binding.get('slot_type', {}).get('value', '')
                        entity_uri = binding.get('entity_ref', {}).get('value', '')
                        ft = binding.get('frame_type', {}).get('value', '')
                        if f_uri and ft and f_uri not in frame_types:
                            frame_types[f_uri] = ft
                        if f_uri in refs_by_frame and entity_uri:
                            refs_by_frame[f_uri].append(EntitySlotRef(
                                slot_type_uri=slot_type,
                                entity_uri=entity_uri
                            ))
                
                for uri in frame_uris:
                    frame_results.append(FrameQueryResult(
                        frame_uri=uri,
                        frame_type_uri=frame_types.get(uri, ""),
                        entity_refs=refs_by_frame.get(uri, []),
                        frame_graph=None  # TODO: implement include_frame_graph
                    ))
            
            self.logger.info(f"Frame query: {len(frame_results)} frames (total={total_count}), {(t_query - t0)*1000:.0f}ms")
            
            return KGQueryResponse(
                query_type="frame_query",
                frame_results=frame_results,
                total_count=total_count,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
            
        except Exception as e:
            self.logger.error(f"Error executing frame_query: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to execute frame query: {str(e)}"
            )
    
    def _build_frame_count_query(self, criteria, graph_id: str) -> str:
        """Build a COUNT query for frames matching criteria (mirrors build_frame_query_sparql WHERE clause)."""
        # Build the same WHERE clauses as build_frame_query_sparql but wrap in COUNT
        where_clauses = ["?frame rdf:type haley:KGFrame ."]
        
        if criteria.frame_type:
            where_clauses.append(f"?frame haley:hasKGFrameType <{criteria.frame_type}> .")
        
        if criteria.search_string:
            where_clauses.append(f"""
            {{
                ?frame rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{criteria.search_string}")))
            }} UNION {{
                ?frame vital-core:name ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
            }}
            """)
        
        if criteria.entity_type:
            where_clauses.append(f"""
            ?entity haley:hasFrame ?frame .
            ?entity vital-core:vitaltype <{criteria.entity_type}> .
            """)
        
        if criteria.slot_criteria:
            for i, slot_criterion in enumerate(criteria.slot_criteria):
                slot_var = f"slot_{i}"
                if slot_criterion.comparator == "not_exists":
                    inner = [f"?{slot_var}_edge vital-core:hasEdgeSource ?frame . ?{slot_var}_edge vital-core:hasEdgeDestination ?{slot_var} ."]
                    if slot_criterion.slot_type:
                        inner.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    where_clauses.append(f"FILTER NOT EXISTS {{ {' '.join(inner)} }}")
                else:
                    slot_clauses = [f"?{slot_var}_edge vital-core:hasEdgeSource ?frame . ?{slot_var}_edge vital-core:hasEdgeDestination ?{slot_var} ."]
                    if slot_criterion.slot_type:
                        slot_clauses.append(f"?{slot_var} haley:hasKGSlotType <{slot_criterion.slot_type}> .")
                    if slot_criterion.value is not None and slot_criterion.comparator:
                        value_clause = self.query_builder._build_value_filter(
                            slot_var, slot_criterion.value, slot_criterion.comparator,
                            slot_criterion.slot_class_uri, slot_criterion.slot_type, f"val_frame_{i}"
                        )
                        slot_clauses.append(value_clause)
                    where_clauses.append(" ".join(slot_clauses))
        
        where_clause = " ".join(where_clauses)
        
        if graph_id is None:
            return f"""
            {self.query_builder.prefixes}
            SELECT (COUNT(DISTINCT ?frame) AS ?count) WHERE {{
                {where_clause}
            }}
            """.strip()
        else:
            return f"""
            {self.query_builder.prefixes}
            SELECT (COUNT(DISTINCT ?frame) AS ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    {where_clause}
                }}
            }}
            """.strip()
    
    async def _fetch_entity_graphs(
        self, backend, space_id: str, graph_id: str, entity_uris: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch complete entity graphs for a list of entity URIs in a single batched query.
        
        Uses hasKGGraphURI to find all objects (frames, slots, edges) belonging to each entity.
        Returns property maps grouped by entity URI — no rdflib dependency.
        """
        values_clause = " ".join(f"<{uri}>" for uri in entity_uris)
        
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?entity_uri ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    VALUES ?entity_uri {{ {values_clause} }}
                    {{
                        ?entity_uri ?p ?o .
                        BIND(?entity_uri AS ?s)
                    }}
                    UNION
                    {{
                        ?s haley:hasKGGraphURI ?entity_uri .
                        FILTER(?s != ?entity_uri)
                        ?s ?p ?o .
                    }}
                }}
            }}
        """.strip()
        
        results = await backend.execute_sparql_query(space_id, query)
        
        # Unwrap SPARQL JSON results
        bindings = []
        if isinstance(results, dict):
            bindings = results.get('results', {}).get('bindings', [])
        
        if not bindings:
            return {uri: [] for uri in entity_uris}
        
        # Group bindings by entity_uri, then by subject within each entity graph
        _RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
        _VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype'
        _URI_PROP = 'http://vital.ai/ontology/vital-core#URIProp'
        _XSD = 'http://www.w3.org/2001/XMLSchema#'
        
        # entity_uri -> {subject_uri -> {type_uri, properties}}
        by_entity: Dict[str, Dict[str, Dict]] = {uri: {} for uri in entity_uris}
        
        for b in bindings:
            e_uri = b.get('entity_uri', {}).get('value', '')
            s = b.get('s', {}).get('value', '')
            p = b.get('p', {}).get('value', '')
            o_data = b.get('o', {})
            o_val = o_data.get('value')
            if not (e_uri and s and p and o_val is not None):
                continue
            
            if e_uri not in by_entity:
                continue
            
            subjects = by_entity[e_uri]
            if s not in subjects:
                subjects[s] = {'type_uri': None, 'properties': {}}
            
            # Handle type predicates
            if p in (_RDF_TYPE, _VITALTYPE):
                subjects[s]['type_uri'] = o_val
                continue
            if p == _URI_PROP:
                continue
            
            # Convert literal values
            o_type = o_data.get('type', 'literal')
            if o_type == 'uri':
                value = o_val
            else:
                dt = o_data.get('datatype', '')
                if dt.startswith(_XSD):
                    local = dt[len(_XSD):]
                    if local in ('integer', 'int', 'long'):
                        value = int(o_val)
                    elif local in ('float', 'double', 'decimal'):
                        value = float(o_val)
                    elif local == 'boolean':
                        value = o_val.lower() in ('true', '1')
                    else:
                        value = o_val
                else:
                    value = o_val
            
            props = subjects[s]['properties']
            if p in props:
                existing = props[p]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    props[p] = [existing, value]
            else:
                props[p] = value
        
        # Convert to response format: {entity_uri: [{uri, type, properties}, ...]}
        result: Dict[str, List[Dict[str, Any]]] = {}
        for e_uri in entity_uris:
            objects = []
            for s_uri, data in by_entity.get(e_uri, {}).items():
                if data['type_uri']:
                    objects.append({
                        'uri': s_uri,
                        'type': data['type_uri'],
                        'properties': data['properties']
                    })
            result[e_uri] = objects
        
        return result
    
    def _build_entity_slot_refs_query(self, frame_uris: List[str], graph_id: str) -> str:
        """Build SPARQL to fetch entity slot refs for a list of frames."""
        values_clause = " ".join(f"<{uri}>" for uri in frame_uris)
        
        slot_to_frame = """
                ?slot_edge vital-core:hasEdgeSource ?frame .
                ?slot_edge vital-core:hasEdgeDestination ?slot ."""
        
        if graph_id is None:
            return f"""
            {self.query_builder.prefixes}
            SELECT ?frame ?frame_type ?slot_type ?entity_ref WHERE {{
                VALUES ?frame {{ {values_clause} }}
                OPTIONAL {{ ?frame haley:hasKGFrameType ?frame_type . }}
                {slot_to_frame}
                ?slot haley:hasKGSlotType ?slot_type .
                {{
                    ?slot haley:hasEntitySlotValue ?entity_ref .
                }} UNION {{
                    ?slot haley:hasUriSlotValue ?entity_ref .
                }}
            }}
            ORDER BY ?frame ?slot_type
            """.strip()
        else:
            return f"""
            {self.query_builder.prefixes}
            SELECT ?frame ?frame_type ?slot_type ?entity_ref WHERE {{
                GRAPH <{graph_id}> {{
                    VALUES ?frame {{ {values_clause} }}
                    OPTIONAL {{ ?frame haley:hasKGFrameType ?frame_type . }}
                    {slot_to_frame}
                    ?slot haley:hasKGSlotType ?slot_type .
                    {{
                        ?slot haley:hasEntitySlotValue ?entity_ref .
                    }} UNION {{
                        ?slot haley:hasUriSlotValue ?entity_ref .
                    }}
                }}
            }}
            ORDER BY ?frame ?slot_type
            """.strip()


def create_kgqueries_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG queries router."""
    endpoint = KGQueriesEndpoint(space_manager, auth_dependency)
    return endpoint.router