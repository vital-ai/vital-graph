"""SPARQL Delete Endpoint for VitalGraph

Implements SPARQL 1.1 delete operations (DELETE DATA, DELETE WHERE)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging

from ..model.sparql_model import (
    SPARQLDeleteRequest,
    SPARQLDeleteResponse
)


class SPARQLDeleteEndpoint:
    """SPARQL Delete endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLDeleteEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL delete routes."""
        
        # POST endpoint for SPARQL deletes
        @self.router.post(
            "/{space_id}/delete",
            response_model=SPARQLDeleteResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Delete",
            description="Execute a SPARQL delete operation (DELETE DATA or DELETE WHERE) against the specified space"
        )
        async def sparql_delete_post(
            space_id: str,
            request: SPARQLDeleteRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_delete(space_id, request.update, current_user, request.graph_uri)
        
        # Form-based endpoint for SPARQL deletes
        @self.router.post(
            "/{space_id}/delete-form",
            response_model=SPARQLDeleteResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Delete (Form)",
            description="Execute a SPARQL delete operation via form data"
        )
        async def sparql_delete_form(
            space_id: str,
            update: str = Form(..., description="SPARQL update string"),
            graph_uri: Optional[str] = Form(None, description="Target graph URI"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_delete(space_id, update, current_user, graph_uri)
        
        # Clear graph endpoint
        @self.router.delete(
            "/{space_id}/graph",
            response_model=SPARQLDeleteResponse,
            tags=["Graphs"],
            summary="Clear Graph",
            description="Clear all triples from a specific graph"
        )
        async def clear_graph(
            space_id: str,
            graph_uri: str = Body(..., description="Graph URI to clear"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            # Convert to CLEAR GRAPH operation
            clear_query = f"CLEAR GRAPH <{graph_uri}>"
            return await self._execute_delete(space_id, clear_query, current_user, graph_uri)

    
    async def _execute_delete(
        self,
        space_id: str,
        update: str,
        current_user: Dict,
        graph_uri: Optional[str] = None
    ) -> SPARQLDeleteResponse:
        """Execute a SPARQL update (delete) and return results."""
        
        try:
            self.logger.info(f"Executing SPARQL update (delete) in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
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
        
            # Get the database-specific PostgreSQL implementation for the orchestrator
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
        
            # Execute SPARQL delete using orchestrator with PostgreSQL implementation
            import time
            start_time = time.time()
        
            success = await db_space_impl.execute_sparql_update(space_id, update)
            
            delete_time = time.time() - start_time
            
            if success:
                return SPARQLDeleteResponse(
                    success=True,
                    message="Delete executed successfully",
                    delete_time=delete_time
                )
            else:
                return SPARQLDeleteResponse(
                    success=False,
                    message="Delete failed",
                    delete_time=delete_time,
                    error="Delete operation returned false"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing SPARQL delete: {e}")
            return SPARQLDeleteResponse(
                success=False,
                message=f"SPARQL delete failed: {str(e)}",
                error=str(e)
            )


def create_sparql_delete_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL delete router."""
    endpoint = SPARQLDeleteEndpoint(space_manager, auth_dependency)
    return endpoint.router
