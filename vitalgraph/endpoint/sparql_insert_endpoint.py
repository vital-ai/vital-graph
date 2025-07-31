"""SPARQL Insert Endpoint for VitalGraph

Implements SPARQL 1.1 insert operations (INSERT DATA, INSERT WHERE)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging


class SPARQLInsertRequest(BaseModel):
    """Request model for SPARQL insert operations."""
    insert: str = Field(
        ...,
        description="SPARQL insert string (INSERT DATA or INSERT WHERE)",
        example="INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }"
    )
    graph_uri: Optional[str] = Field(
        None,
        description="Target graph URI for the insert operation",
        example="http://example.org/graph1"
    )
    format: Optional[str] = Field(
        "application/n-triples",
        description="RDF format for data insertion",
        example="application/n-triples"
    )


class SPARQLInsertResponse(BaseModel):
    """Response model for SPARQL insert results."""
    success: bool = Field(
        ...,
        description="Whether the insert operation was successful"
    )
    message: Optional[str] = Field(
        None,
        description="Success or error message"
    )
    insert_time: Optional[float] = Field(
        None,
        description="Insert execution time in seconds"
    )
    inserted_triples: Optional[int] = Field(
        None,
        description="Number of triples inserted"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if insert failed"
    )


class SPARQLInsertEndpoint:
    """SPARQL Insert endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLInsertEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL insert routes."""
        
        # POST endpoint for SPARQL inserts
        @self.router.post(
            "/{space_id}/insert",
            response_model=SPARQLInsertResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Insert",
            description="Execute a SPARQL insert operation (INSERT DATA or INSERT WHERE) against the specified space"
        )
        async def sparql_insert_post(
            space_id: str,
            request: SPARQLInsertRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_insert(space_id, request.insert, current_user, request.graph_uri)
        
        # Form-based endpoint for SPARQL inserts
        @self.router.post(
            "/{space_id}/insert-form",
            response_model=SPARQLInsertResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Insert (Form)",
            description="Execute a SPARQL insert operation via form data"
        )
        async def sparql_insert_form(
            space_id: str,
            insert: str = Form(..., description="SPARQL insert string"),
            graph_uri: Optional[str] = Form(None, description="Target graph URI"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_insert(space_id, insert, current_user, graph_uri)
        
        # Direct RDF data insert endpoint
        @self.router.post(
            "/{space_id}/insert-data",
            response_model=SPARQLInsertResponse,
            tags=["SPARQL"],
            summary="Insert RDF Data Directly",
            description="Insert RDF data directly without SPARQL syntax"
        )
        async def insert_rdf_data(
            space_id: str,
            rdf_data: str = Body(..., description="RDF data in N-Triples, Turtle, or RDF/XML format"),
            graph_uri: Optional[str] = Body(None, description="Target graph URI"),
            format: str = Body("application/n-triples", description="RDF format"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            # Convert RDF data to INSERT DATA query
            if graph_uri:
                insert_query = f"INSERT DATA {{ GRAPH <{graph_uri}> {{ {rdf_data} }} }}"
            else:
                insert_query = f"INSERT DATA {{ {rdf_data} }}"
            
            return await self._execute_insert(space_id, insert_query, current_user, graph_uri)
    
    async def _execute_insert(
        self,
        space_id: str,
        insert: str,
        current_user: Dict,
        graph_uri: Optional[str] = None
    ) -> SPARQLInsertResponse:
        """Execute a SPARQL insert and return results."""
        
        try:
            self.logger.info(f"Executing SPARQL insert in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            if graph_uri:
                self.logger.info(f"Target graph: {graph_uri}")
            self.logger.debug(f"Insert: {insert[:200]}{'...' if len(insert) > 200 else ''}")
            
            # Validate space manager
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
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
        
            # Execute SPARQL insert using orchestrator with PostgreSQL implementation
            import time
            start_time = time.time()
        
            from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import execute_sparql_update
            success = await execute_sparql_update(db_space_impl, space_id, insert)
            
            insert_time = time.time() - start_time
            
            if success:
                return SPARQLInsertResponse(
                    success=True,
                    message="Insert executed successfully",
                    insert_time=insert_time
                )
            else:
                return SPARQLInsertResponse(
                    success=False,
                    message="Insert failed",
                    insert_time=insert_time,
                    error="Insert operation returned false"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing SPARQL insert: {e}")
            return SPARQLInsertResponse(
                success=False,
                error=str(e)
            )


def create_sparql_insert_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL insert router."""
    endpoint = SPARQLInsertEndpoint(space_manager, auth_dependency)
    return endpoint.router
