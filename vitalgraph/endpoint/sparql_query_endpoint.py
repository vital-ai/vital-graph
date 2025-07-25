"""SPARQL Query Endpoint for VitalGraph

Implements SPARQL 1.1 query operations (SELECT, CONSTRUCT, ASK, DESCRIBE)
following the SPARQL 1.1 Protocol specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging


class SPARQLQueryRequest(BaseModel):
    """Request model for SPARQL query operations."""
    query: str = Field(
        ...,
        description="SPARQL query string (SELECT, CONSTRUCT, ASK, or DESCRIBE)",
        example="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
    )
    default_graph_uri: Optional[List[str]] = Field(
        None,
        description="Default graph URIs for the query",
        example=["http://example.org/graph1"]
    )
    named_graph_uri: Optional[List[str]] = Field(
        None,
        description="Named graph URIs for the query",
        example=["http://example.org/graph2"]
    )
    format: Optional[str] = Field(
        "application/sparql-results+json",
        description="Response format (application/sparql-results+json, text/csv, etc.)",
        example="application/sparql-results+json"
    )


class SPARQLQueryResponse(BaseModel):
    """Response model for SPARQL query results."""
    head: Optional[Dict[str, Any]] = Field(
        None,
        description="Query result metadata (variables, links)"
    )
    results: Optional[Dict[str, Any]] = Field(
        None,
        description="Query result bindings for SELECT queries"
    )
    boolean: Optional[bool] = Field(
        None,
        description="Boolean result for ASK queries"
    )
    triples: Optional[List[Dict[str, str]]] = Field(
        None,
        description="RDF triples for CONSTRUCT/DESCRIBE queries"
    )
    query_time: Optional[float] = Field(
        None,
        description="Query execution time in seconds"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if query failed"
    )


class SPARQLQueryEndpoint:
    """SPARQL Query endpoint handler."""
    
    def __init__(self, db_impl, auth_dependency):
        self.db_impl = db_impl
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
            
            # Validate database connection
            if not self.db_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database not configured"
                )
            
            # Get space implementation
            space_impl = self.db_impl.get_space_impl()
            if not space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Space implementation not available"
                )
            
            # Get SPARQL implementation
            from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
            sparql_impl = PostgreSQLSparqlImpl(space_impl)
            
            # Execute the query
            import time
            start_time = time.time()
            
            results = await sparql_impl.execute_sparql_query(space_id, query)
            
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
                
                return SPARQLQueryResponse(
                    head={"vars": variables},
                    results={"bindings": results},
                    query_time=query_time
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            return SPARQLQueryResponse(
                error=str(e)
            )


def create_sparql_query_router(db_impl, auth_dependency) -> APIRouter:
    """Create and return the SPARQL query router."""
    endpoint = SPARQLQueryEndpoint(db_impl, auth_dependency)
    return endpoint.router
