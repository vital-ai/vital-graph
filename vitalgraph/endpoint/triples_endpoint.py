"""Triples Endpoint for VitalGraph

Implements REST API endpoints for triple management operations using quad-based wire format.
Based on the planned API specification in docs/planned_rest_api_endpoints.md
"""

from typing import Dict, List, Any, Optional, Union
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging
from datetime import datetime

from ..model.quad_model import QuadRequest
from ..model.triples_model import (
    TripleListRequest,
    TripleListResponse,
    TripleOperationResponse
)


class TriplesEndpoint:
    """Triples endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.TriplesEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup triples routes."""
        
        # GET /api/graphs/triples - List/search triples with pagination/filtering
        @self.router.get(
            "/triples",
            response_model=TripleListResponse,
            tags=["Triples"],
            summary="List/Search Triples",
            description="List or search triples with pagination and filtering options"
        )
        async def list_triples(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=100, description="Number of triples per page"),
            offset: int = Query(0, ge=0, description="Number of triples to skip"),
            subject: Optional[str] = Query(None, description="Subject URI to filter by"),
            predicate: Optional[str] = Query(None, description="Predicate URI to filter by"),
            object: Optional[str] = Query(None, description="Object value to filter by"),
            object_filter: Optional[str] = Query(None, description="Keyword to search within object values"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._list_triples(
                space_id, graph_id, page_size, offset, subject, predicate, object, object_filter, current_user
            )
        
        # POST /api/graphs/triples - Add new triples
        @self.router.post(
            "/triples",
            response_model=TripleOperationResponse,
            tags=["Triples"],
            summary="Add Triples",
            description="Add new triples to the specified graph. Accepts a QuadRequest containing N-Quads-encoded triples."
        )
        async def add_triples(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            request: QuadRequest = Body(..., description="Quads to add"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._add_triples(space_id, graph_id, request, current_user)
        
        # DELETE /api/graphs/triples - Delete specific triples
        @self.router.delete(
            "/triples",
            response_model=TripleOperationResponse,
            tags=["Triples"],
            summary="Delete Triples",
            description="Delete specific triples from the specified graph. Accepts a QuadRequest containing N-Quads-encoded triples."
        )
        async def delete_triples(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            request: QuadRequest = Body(..., description="Quads to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._delete_triples(space_id, graph_id, request, current_user)
    
    async def _list_triples(
        self,
        space_id: str,
        graph_id: str,
        page_size: int,
        offset: int,
        subject: Optional[str],
        predicate: Optional[str],
        object: Optional[str],
        object_filter: Optional[str],
        current_user: Dict
    ) -> TripleListResponse:
        """List triples with filtering and pagination."""
        
        try:
            self.logger.info(f"Listing triples in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            space_impl = space_record.space_impl
            
            # Get the hybrid backend implementation
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
            
            # Use SPARQL queries via hybrid backend
            try:
                import time
                start_time = time.time()
                
                # Build SPARQL query for triples
                sparql_query = self._build_sparql_query(
                    graph_id, subject, predicate, object, object_filter, page_size, offset
                )
                
                # Execute SPARQL query via hybrid backend
                results = await db_space_impl.query_quads(space_id, sparql_query)
                
                # Convert SPARQL results to Quad models
                from ..model.quad_model import Quad
                quad_results = []
                for result in results:
                    s_val = result.get('s', {}).get('value', '')
                    p_val = result.get('p', {}).get('value', '')
                    o_binding = result.get('o', {})
                    
                    s_enc = f"<{s_val}>"
                    p_enc = f"<{p_val}>"
                    o_enc = self._sparql_binding_to_nquads_term(o_binding)
                    g_enc = f"<{graph_id}>" if graph_id else None
                    
                    quad_results.append(Quad(s=s_enc, p=p_enc, o=o_enc, g=g_enc))
                
                query_time = time.time() - start_time
                
                # Get total count with SPARQL COUNT query
                count_query = self._build_count_sparql_query(
                    graph_id, subject, predicate, object, object_filter
                )
                count_results = await db_space_impl.query_quads(space_id, count_query)
                total_count = int(count_results[0].get('count', {}).get('value', 0)) if count_results else 0
                        
            except Exception as e:
                self.logger.error(f"Error executing SPARQL query: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to execute SPARQL query: {str(e)}"
                )
            
            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
            current_page = (offset // page_size) + 1
            
            return TripleListResponse(
                total_count=total_count,
                page_size=page_size,
                offset=offset,
                results=quad_results,
                pagination={
                    "page": current_page,
                    "limit": page_size,
                    "total": total_count,
                    "pages": total_pages,
                    "offset": offset
                },
                meta={
                    "timestamp": datetime.now().isoformat() + "Z",
                    "version": "1.0",
                    "format": "JSON Quads",
                    "space_id": space_id,
                    "graph_id": graph_id,
                    "filters": {
                        "subject": subject,
                        "predicate": predicate,
                        "object": object,
                        "object_filter": object_filter
                    }
                }
            )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing triples: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error listing triples: {str(e)}"
            )
    
    async def _add_triples(
        self,
        space_id: str,
        graph_id: str,
        quad_request: QuadRequest,
        current_user: Dict
    ) -> TripleOperationResponse:
        """Add quads to the graph. Operates at the raw triples level — no GraphObject validation."""
        
        try:
            self.logger.info(f"Adding quads to space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            space_impl = space_record.space_impl
            
            # Get the hybrid backend implementation
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
            
            # Convert Quad models directly to RDF quads — no GraphObject validation
            quads = self._quad_request_to_rdf_quads(quad_request, graph_id)
            
            if not quads:
                return TripleOperationResponse(
                    success=True,
                    message=f"No triples found in request for graph '{graph_id}' in space '{space_id}'",
                    affected_count=0
                )
            
            # Pass RDFLib objects directly to preserve type information
            # The backend will handle proper formatting for each storage system
            success = await db_space_impl.add_rdf_quads_batch(space_id, quads)
            added_count = len(quads) if success else 0
            
            self.logger.info(f"Successfully added {added_count} triples to graph '{graph_id}' in space '{space_id}'")
            
            return TripleOperationResponse(
                success=True,
                message=f"Successfully added {added_count} triples to graph '{graph_id}' in space '{space_id}'",
                affected_count=added_count
            )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error adding triples: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error adding triples: {str(e)}"
            )
    
    async def _delete_triples(
        self,
        space_id: str,
        graph_id: str,
        quad_request: QuadRequest,
        current_user: Dict
    ) -> TripleOperationResponse:
        """Delete quads from the graph. Operates at the raw triples level — no GraphObject validation."""
        
        try:
            self.logger.info(f"Deleting quads from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate space exists (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            space_impl = space_record.space_impl
            
            # Get the hybrid backend implementation
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
            
            # Convert Quad models directly to RDF quads — no GraphObject validation
            quads = self._quad_request_to_rdf_quads(quad_request, graph_id)
            
            if not quads:
                return TripleOperationResponse(
                    success=True,
                    message=f"No triples found in request for graph '{graph_id}' in space '{space_id}'",
                    affected_count=0
                )
            
            # Convert quads to tuple format expected by the backend
            # Preserve RDFLib objects (especially Literal with datatype/language)
            # so downstream dual-write formatters can match typed literals correctly
            quad_tuples = []
            for s, p, o, g in quads:
                quad_tuples.append((str(s), str(p), o, str(g)))
            
            # Remove quads from the database using hybrid backend batch method
            success = await db_space_impl.remove_rdf_quads_batch(space_id, quad_tuples)
            removed_count = len(quad_tuples) if success else 0
            
            self.logger.info(f"Successfully removed {removed_count} triples from graph '{graph_id}' in space '{space_id}'")
            
            return TripleOperationResponse(
                success=True,
                message=f"Successfully removed {removed_count} triples from graph '{graph_id}' in space '{space_id}'",
                affected_count=removed_count
            )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting triples: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting triples: {str(e)}"
            )
    
    def _quad_request_to_rdf_quads(self, quad_request: QuadRequest, graph_id: str):
        """Convert QuadRequest directly to RDFLib quads. No GraphObject validation.
        
        Quad fields use N-Quads term encoding (e.g. <http://...>, "value"^^<xsd:int>).
        """
        from rdflib import URIRef
        from ..utils.quad_format_utils import nquads_term_to_rdflib
        
        quads = []
        graph_uri = URIRef(graph_id)
        
        for q in quad_request.quads:
            s = nquads_term_to_rdflib(q.s)
            p = nquads_term_to_rdflib(q.p)
            o = nquads_term_to_rdflib(q.o)
            g = nquads_term_to_rdflib(q.g) if q.g else graph_uri
            quads.append((s, p, o, g))
        
        self.logger.info(f"Converted {len(quads)} quads from QuadRequest")
        return quads
    
    def _sparql_binding_to_nquads_term(self, binding: dict) -> str:
        """Convert a SPARQL result binding to an N-Quads encoded term string."""
        binding_type = binding.get('type', 'literal')
        value = binding.get('value', '')
        
        if binding_type == 'uri':
            return f"<{value}>"
        elif binding_type == 'bnode':
            return f"_:{value}"
        elif binding_type == 'literal':
            escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
            if 'xml:lang' in binding:
                return f'"{escaped}"@{binding["xml:lang"]}'
            elif 'datatype' in binding:
                return f'"{escaped}"^^<{binding["datatype"]}>'
            else:
                return f'"{escaped}"'
        else:
            return f'"{value}"'
    
    def _build_sparql_query(self, graph_id: str, subject: str = None, predicate: str = None, 
                           object: str = None, object_filter: str = None, 
                           limit: int = 100, offset: int = 0) -> str:
        """Build a SPARQL SELECT query with filters and pagination."""
        
        # Build simple SPARQL SELECT with GRAPH clause
        if graph_id:
            query_parts = [
                "SELECT ?s ?p ?o",
                "WHERE {",
                f"  GRAPH <{graph_id}> {{",
                "    ?s ?p ?o .",
                "  }"
            ]
        else:
            query_parts = [
                "SELECT ?s ?p ?o",
                "WHERE {",
                "  ?s ?p ?o ."
            ]
        
        # Add filters
        filters = []
        if subject:
            filters.append(f"  FILTER(?s = <{subject}>)")
        if predicate:
            filters.append(f"  FILTER(?p = <{predicate}>)")
        if object:
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if validate_rfc3986(object, rule='URI'):
                filters.append(f"  FILTER(?o = <{object}>)")
            else:
                filters.append(f'  FILTER(?o = "{object}")')
        if object_filter:
            filters.append(f'  FILTER(CONTAINS(LCASE(STR(?o)), LCASE("{object_filter}")))')
        
        query_parts.extend(filters)
        query_parts.extend([
            "}",
            f"LIMIT {limit}",
            f"OFFSET {offset}"
        ])
        
        return "\n".join(query_parts)
    
    def _build_count_sparql_query(self, graph_id: str, subject: str = None, predicate: str = None,
                                 object: str = None, object_filter: str = None) -> str:
        """Build a SPARQL COUNT query with the same filters."""
        
        if graph_id:
            query_parts = [
                "SELECT (COUNT(*) AS ?count)",
                "WHERE {",
                f"  GRAPH <{graph_id}> {{",
                "    ?s ?p ?o .",
                "  }"
            ]
        else:
            query_parts = [
                "SELECT (COUNT(*) AS ?count)",
                "WHERE {",
                "  ?s ?p ?o ."
            ]
        
        # Add the same filters as the main query
        filters = []
        if subject:
            filters.append(f"  FILTER(?s = <{subject}>)")
        if predicate:
            filters.append(f"  FILTER(?p = <{predicate}>)")
        if object:
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if validate_rfc3986(object, rule='URI'):
                filters.append(f"  FILTER(?o = <{object}>)")
            else:
                filters.append(f'  FILTER(?o = "{object}")')
        if object_filter:
            filters.append(f'  FILTER(CONTAINS(LCASE(STR(?o)), LCASE("{object_filter}")))')
        
        query_parts.extend(filters)
        query_parts.append("}")
        
        return "\n".join(query_parts)
    
    def _convert_sparql_binding_to_rdf_term(self, binding: dict) -> dict:
        """Convert a SPARQL binding to an RDF term dict."""
        if binding['type'] == 'uri':
            return {"@id": binding['value']}
        elif binding['type'] == 'literal':
            if 'datatype' in binding:
                return {
                    "@value": binding['value'],
                    "@type": binding['datatype']
                }
            elif 'xml:lang' in binding:
                return {
                    "@value": binding['value'],
                    "@language": binding['xml:lang']
                }
            else:
                return binding['value']
        else:
            return binding['value']
    
    async def _get_fast_count(self, db_space_impl, space_id: str, graph_id: str, 
                             subject: str = None, predicate: str = None, 
                             object: str = None, object_filter: str = None) -> int:
        """Get count using fast direct SQL query instead of slow SPARQL."""
        try:
            import time
            start_time = time.time()
            
            # Get table names
            table_names = db_space_impl._get_table_names(space_id)
            quad_table = table_names['rdf_quad']
            term_table = table_names['term']
            
            # Get the graph UUID
            graph_uuid = None
            async with db_space_impl.core.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT term_uuid FROM {term_table} WHERE term_text = %s AND term_type = 'U'",
                        (graph_id,)
                    )
                    result = cursor.fetchone()
                    if result:
                        graph_uuid = result[0]
            
            if not graph_uuid:
                self.logger.warning(f"Graph {graph_id} not found in term table")
                return 0
            
            # Build optimized COUNT query
            where_conditions = [f"q.context_uuid = %s"]
            params = [str(graph_uuid)]
            
            # Add filters if specified (these require JOINs)
            joins = []
            if subject:
                joins.append(f"JOIN {term_table} s_term ON q.subject_uuid = s_term.term_uuid")
                where_conditions.append("s_term.term_text = %s AND s_term.term_type = 'U'")
                params.append(subject)
            
            if predicate:
                joins.append(f"JOIN {term_table} p_term ON q.predicate_uuid = p_term.term_uuid")
                where_conditions.append("p_term.term_text = %s AND p_term.term_type = 'U'")
                params.append(predicate)
            
            if object:
                joins.append(f"JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid")
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                if validate_rfc3986(object, rule='URI'):
                    where_conditions.append("o_term.term_text = %s AND o_term.term_type = 'U'")
                    params.append(object)
                else:
                    where_conditions.append("o_term.term_text = %s AND o_term.term_type = 'L'")
                    params.append(object)
            
            if object_filter:
                # Enhanced keyword search - support multiple keywords and search across all terms
                # Ensure we have all term JOINs for comprehensive search
                if not any('s_term' in join for join in joins):
                    joins.append(f"JOIN {term_table} s_term ON q.subject_uuid = s_term.term_uuid")
                if not any('p_term' in join for join in joins):
                    joins.append(f"JOIN {term_table} p_term ON q.predicate_uuid = p_term.term_uuid")
                if not any('o_term' in join for join in joins):
                    joins.append(f"JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid")
                
                keywords = [kw.strip() for kw in object_filter.split() if kw.strip()]
                if keywords:
                    # Create search conditions for each keyword across subject, predicate, and object
                    keyword_conditions = []
                    for keyword in keywords:
                        keyword_condition = (
                            "("
                            "LOWER(s_term.term_text) LIKE LOWER(%s) OR "
                            "LOWER(p_term.term_text) LIKE LOWER(%s) OR "
                            "LOWER(o_term.term_text) LIKE LOWER(%s)"
                            ")"
                        )
                        keyword_conditions.append(keyword_condition)
                        # Add the same keyword parameter 3 times (for s, p, o)
                        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
                    
                    # All keywords must match (AND logic)
                    if keyword_conditions:
                        where_conditions.append("(" + " AND ".join(keyword_conditions) + ")")
            
            # Build final SQL query
            join_clause = " ".join(joins) if joins else ""
            where_clause = " AND ".join(where_conditions)
            
            sql_query = f"""
                SELECT COUNT(*) as count
                FROM {quad_table} q
                {join_clause}
                WHERE {where_clause}
            """
            
            # Execute the optimized count query
            async with db_space_impl.core.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql_query, params)
                    result = cursor.fetchone()
                    count = result[0] if result else 0
            
            query_time = time.time() - start_time
            self.logger.info(f"Fast SQL count query executed in {query_time:.3f}s, count: {count}")
            
            return count
            
        except Exception as e:
            self.logger.error(f"Error in fast count query: {e}")
            # Fallback to 0 if count fails
            return 0
    
    async def _get_fast_triples(self, db_space_impl, space_id: str, graph_id: str,
                               subject: str = None, predicate: str = None, 
                               object: str = None, object_filter: str = None,
                               limit: int = 10, offset: int = 0) -> list:
        """Get triples using fast direct SQL query instead of SPARQL."""
        try:
            import time
            start_time = time.time()
            
            # Get table names
            table_names = db_space_impl._get_table_names(space_id)
            quad_table = table_names['rdf_quad']
            term_table = table_names['term']
            
            # Get the graph UUID
            graph_uuid = None
            async with db_space_impl.core.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT term_uuid FROM {term_table} WHERE term_text = %s AND term_type = 'U'",
                        (graph_id,)
                    )
                    result = cursor.fetchone()
                    if result:
                        graph_uuid = result[0]
            
            if not graph_uuid:
                self.logger.warning(f"Graph {graph_id} not found in term table")
                return []
            
            # Use simpler query when no filters are applied
            has_filters = any([subject, predicate, object, object_filter])
            
            if not has_filters:
                # Simple query without JOINs - much faster
                sql_query = f"""
                    SELECT 
                        s_term.term_text as subject,
                        p_term.term_text as predicate,
                        o_term.term_text as object,
                        o_term.term_type as object_type
                    FROM {quad_table} q
                    JOIN {term_table} s_term ON q.subject_uuid = s_term.term_uuid
                    JOIN {term_table} p_term ON q.predicate_uuid = p_term.term_uuid
                    JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid
                    WHERE q.context_uuid = %s
                    ORDER BY q.subject_uuid, q.predicate_uuid
                    LIMIT %s OFFSET %s
                """
                params = [str(graph_uuid), limit, offset]
            else:
                # Complex query with filters
                where_conditions = [f"q.context_uuid = %s"]
                params = [str(graph_uuid)]
                
                joins = [
                    f"JOIN {term_table} s_term ON q.subject_uuid = s_term.term_uuid",
                    f"JOIN {term_table} p_term ON q.predicate_uuid = p_term.term_uuid", 
                    f"JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid"
                ]
            
                if subject:
                    where_conditions.append("s_term.term_text = %s AND s_term.term_type = 'U'")
                    params.append(subject)
                
                if predicate:
                    where_conditions.append("p_term.term_text = %s AND p_term.term_type = 'U'")
                    params.append(predicate)
                
                if object:
                    from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                    if validate_rfc3986(object, rule='URI'):
                        where_conditions.append("o_term.term_text = %s AND o_term.term_type = 'U'")
                        params.append(object)
                    else:
                        where_conditions.append("o_term.term_text = %s AND o_term.term_type = 'L'")
                        params.append(object)
                
                if object_filter:
                    # Enhanced keyword search - support multiple keywords and search across all terms
                    keywords = [kw.strip() for kw in object_filter.split() if kw.strip()]
                    if keywords:
                        # Create search conditions for each keyword across subject, predicate, and object
                        keyword_conditions = []
                        for keyword in keywords:
                            keyword_condition = (
                                "("
                                "LOWER(s_term.term_text) LIKE LOWER(%s) OR "
                                "LOWER(p_term.term_text) LIKE LOWER(%s) OR "
                                "LOWER(o_term.term_text) LIKE LOWER(%s)"
                                ")"
                            )
                            keyword_conditions.append(keyword_condition)
                            # Add the same keyword parameter 3 times (for s, p, o)
                            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
                        
                        # All keywords must match (AND logic)
                        if keyword_conditions:
                            where_conditions.append("(" + " AND ".join(keyword_conditions) + ")")
                
                # Build final SQL query for filtered case
                join_clause = " ".join(joins)
                where_clause = " AND ".join(where_conditions)
                
                sql_query = f"""
                    SELECT 
                        s_term.term_text as subject,
                        p_term.term_text as predicate,
                        o_term.term_text as object,
                        o_term.term_type as object_type,
                        o_term.lang as object_language,
                        o_term.datatype_id as object_datatype_id
                    FROM {quad_table} q
                    {join_clause}
                    WHERE {where_clause}
                    ORDER BY s_term.term_text, p_term.term_text
                    LIMIT %s OFFSET %s
                """
                
                params.extend([limit, offset])
            
            # Execute the optimized triples query
            triples_data = []
            async with db_space_impl.core.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql_query, params)
                    results = cursor.fetchall()
                    
                    for row in results:
                        if has_filters:
                            subject_uri, predicate_uri, object_text, object_type, object_lang, object_datatype_id = row
                        else:
                            subject_uri, predicate_uri, object_text, object_type = row
                            object_lang = None
                            object_datatype_id = None
                        
                        # Create RDF term structure for UI
                        if object_type == 'U':  # URI
                            object_value = {"@id": object_text}
                        else:  # Literal
                            if object_lang:
                                object_value = {"@value": object_text, "@language": object_lang}
                            elif object_datatype_id:
                                # TODO: Resolve datatype_id to actual datatype URI
                                object_value = {"@value": object_text, "@type": f"datatype_id:{object_datatype_id}"}
                            else:
                                object_value = object_text
                        
                        # Create RDF triple structure
                        triple = {
                            "@id": subject_uri,
                            predicate_uri: object_value
                        }
                            
                        triples_data.append(triple)
            
            query_time = time.time() - start_time
            self.logger.info(f"Fast SQL triples query executed in {query_time:.3f}s, returned {len(triples_data)} results")
            
            return triples_data
            
        except Exception as e:
            self.logger.error(f"Error in fast triples query: {e}")
            # Fallback to empty list if query fails
            return []
    
    def _convert_term_to_rdf_value(self, term_text: str, term_type: str, 
                               term_language: str = None, term_datatype: str = None) -> dict:
        """Convert database term to an RDF value dict."""
        if term_type == 'U':  # URI
            return {"@id": term_text}
        elif term_type == 'L':  # Literal
            if term_datatype:
                return {
                    "@value": term_text,
                    "@type": term_datatype
                }
            elif term_language:
                return {
                    "@value": term_text,
                    "@language": term_language
                }
            else:
                return term_text
        else:  # Blank node
            return {"@id": term_text}
    
    def _convert_term_to_rdf_value_with_type(self, term_text: str, term_type: str, 
                                         term_language: str = None, term_datatype: str = None) -> dict:
        """Convert database term to an RDF value dict with explicit type information for UI."""
        base_value = self._convert_term_to_rdf_value(term_text, term_type, term_language, term_datatype)
        
        # Handle case where base_value is a string (simple literal)
        if isinstance(base_value, str):
            base_dict = {"@value": base_value}
        else:
            base_dict = base_value
        
        # Add explicit type information for the UI
        if term_type == 'U':  # URI
            return {
                **base_dict,
                "_type": "uri"
            }
        elif term_type == 'L':  # Literal
            result = {
                **base_dict,
                "_type": "literal"
            }
            if term_datatype:
                result["_datatype"] = term_datatype
            if term_language:
                result["_language"] = term_language
            return result
        else:  # Blank node
            return {
                **base_dict,
                "_type": "bnode"
            }


def create_triples_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the triples router."""
    endpoint = TriplesEndpoint(space_manager, auth_dependency)
    return endpoint.router
