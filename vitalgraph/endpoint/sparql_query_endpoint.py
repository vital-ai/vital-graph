"""SPARQL Query Endpoint for VitalGraph

Implements SPARQL 1.1 query operations (SELECT, CONSTRUCT, ASK, DESCRIBE)
following the SPARQL 1.1 Protocol specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging

from ..model.sparql_model import (
    SPARQLQueryRequest,
    SPARQLQueryResponse
)


class SPARQLQueryEndpoint:
    """SPARQL Query endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLQueryEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL query routes."""
        
        # POST endpoint for SPARQL queries (recommended)
        @self.router.post(
            "/{space_id}/query",
            response_model=SPARQLQueryResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Query (POST)",
            description="Execute a SPARQL query (SELECT, CONSTRUCT, ASK, DESCRIBE) against the specified space"
        )
        async def sparql_query_post(
            space_id: str,
            request: SPARQLQueryRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_query(space_id, request.query, current_user, request.format)
        
        # GET endpoint for SPARQL queries (for simple queries)
        @self.router.get(
            "/{space_id}/query",
            response_model=SPARQLQueryResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Query (GET)",
            description="Execute a simple SPARQL query via GET parameters"
        )
        async def sparql_query_get(
            space_id: str,
            query: str = Query(..., description="SPARQL query string"),
            format: str = Query(
                "application/sparql-results+json",
                description="Response format"
            ),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_query(space_id, query, current_user, format)
    
    async def _execute_query(
        self,
        space_id: str,
        query: str,
        current_user: Dict,
        response_format: str = "application/sparql-results+json"
    ) -> SPARQLQueryResponse:
        """Execute a SPARQL query and return formatted results."""
        
        try:
            self.logger.info(f"Executing SPARQL query in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            self.logger.debug(f"Query: {query[:200]}{'...' if len(query) > 200 else ''}")
            
            # Validate space manager with more detailed error information
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available - server may need restart after recent updates. Please restart the VitalGraph server."
                )
            
            # Validate space exists
            if not self.space_manager.has_space(space_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
                )
            
            # Get space record
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not available"
                )
            
            space_impl = space_record.space_impl
            
            # Get the database-specific PostgreSQL implementation for the orchestrator
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
            
            # Execute SPARQL query using orchestrator with PostgreSQL implementation
            import time
            start_time = time.time()
            
            # print(f" ENDPOINT PRINT: About to call orchestrator with query: {query[:100]}...")
            self.logger.info(f" ENDPOINT: About to call orchestrator with query: {query[:100]}...")
            from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import orchestrate_sparql_query
            results = await orchestrate_sparql_query(db_space_impl, space_id, query)
            # print(f" ENDPOINT PRINT: Orchestrator returned {len(results) if results else 0} results")
            self.logger.info(f" ENDPOINT: Orchestrator returned {len(results) if results else 0} results")
            
            query_time = time.time() - start_time
            
            # Determine query type and format response
            query_upper = query.strip().upper()
            
            if query_upper.startswith('ASK'):
                # ASK query - return boolean result
                boolean_result = len(results) > 0 and results[0].get('ask', False)
                return SPARQLQueryResponse(
                    boolean=boolean_result,
                    query_time=query_time
                )
            
            elif query_upper.startswith('CONSTRUCT') or query_upper.startswith('DESCRIBE'):
                # CONSTRUCT/DESCRIBE query - return RDF triples
                return SPARQLQueryResponse(
                    triples=results,
                    query_time=query_time
                )
            
            else:
                # SELECT query - return variable bindings
                # Extract variables from results
                variables = []
                if results:
                    variables = list(results[0].keys())
                
                response = SPARQLQueryResponse(
                    head={"vars": variables},
                    results={"bindings": results},
                    query_time=query_time
                )
                
                return response
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            return SPARQLQueryResponse(
                error=str(e)
            )


def create_sparql_query_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL query router."""
    endpoint = SPARQLQueryEndpoint(space_manager, auth_dependency)
    return endpoint.router
