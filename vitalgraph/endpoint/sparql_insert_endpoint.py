"""SPARQL Insert Endpoint for VitalGraph

Implements SPARQL 1.1 insert operations (INSERT DATA, INSERT WHERE)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging

from ..model.sparql_model import (
    SPARQLInsertRequest,
    SPARQLInsertResponse
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
            return await self._execute_insert(space_id, request.update, current_user, request.graph_uri)
        
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
            update: str = Form(..., description="SPARQL update string"),
            graph_uri: Optional[str] = Form(None, description="Target graph URI"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_insert(space_id, update, current_user, graph_uri)
        
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
                update_query = f"INSERT DATA {{ GRAPH <{graph_uri}> {{ {rdf_data} }} }}"
            else:
                update_query = f"INSERT DATA {{ {rdf_data} }}"
            
            return await self._execute_insert(space_id, update_query, current_user, graph_uri)
    
    async def _execute_insert(
        self,
        space_id: str,
        update: str,
        current_user: Dict,
        graph_uri: Optional[str] = None
    ) -> SPARQLInsertResponse:
        """Execute a SPARQL update and return results."""
        
        try:
            self.logger.info(f"Executing SPARQL update in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            if graph_uri:
                self.logger.info(f"Target graph: {graph_uri}")
            self.logger.debug(f"Update: {update[:200]}{'...' if len(update) > 200 else ''}")
            
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
        
            # Use the backend's native SPARQL update execution
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(
                    status_code=500,
                    detail="Backend implementation not available"
                )
        
            # Execute SPARQL update using backend's native method
            import time
            start_time = time.time()
        
            success = await backend.execute_sparql_update(space_id, update)
            
            insert_time = time.time() - start_time
            
            if success:
                return SPARQLInsertResponse(
                    success=True,
                    message="Update executed successfully",
                    insert_time=insert_time
                )
            else:
                return SPARQLInsertResponse(
                    success=False,
                    message="Update failed",
                    insert_time=insert_time,
                    error="Update operation returned false"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing SPARQL update: {e}")
            return SPARQLInsertResponse(
                success=False,
                message=f"SPARQL insert failed: {str(e)}",
                error=str(e)
            )


def create_sparql_insert_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL insert router."""
    endpoint = SPARQLInsertEndpoint(space_manager, auth_dependency)
    return endpoint.router
