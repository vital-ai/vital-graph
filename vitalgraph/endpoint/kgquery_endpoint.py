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
    FrameConnection
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
            if query_type not in ["relation", "frame"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid query_type: {query_type}. Must be 'relation' or 'frame'"
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


def create_kgqueries_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG queries router."""
    endpoint = KGQueriesEndpoint(space_manager, auth_dependency)
    return endpoint.router