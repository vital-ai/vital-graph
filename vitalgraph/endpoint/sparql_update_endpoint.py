"""SPARQL Update Endpoint for VitalGraph

Implements SPARQL 1.1 update operations (INSERT, DELETE, LOAD, CLEAR, etc.)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging


class SPARQLUpdateRequest(BaseModel):
    """Request model for SPARQL update operations."""
    update: str = Field(
        ...,
        description="SPARQL update string (INSERT, DELETE, LOAD, CLEAR, etc.)",
        example="INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }"
    )
    using_graph_uri: Optional[List[str]] = Field(
        None,
        description="USING graph URIs for the update",
        example=["http://example.org/graph1"]
    )
    using_named_graph_uri: Optional[List[str]] = Field(
        None,
        description="USING NAMED graph URIs for the update",
        example=["http://example.org/graph2"]
    )


class SPARQLUpdateResponse(BaseModel):
    """Response model for SPARQL update results."""
    success: bool = Field(
        ...,
        description="Whether the update operation was successful"
    )
    message: Optional[str] = Field(
        None,
        description="Success or error message"
    )
    update_time: Optional[float] = Field(
        None,
        description="Update execution time in seconds"
    )
    affected_triples: Optional[int] = Field(
        None,
        description="Number of triples affected by the update"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if update failed"
    )


class SPARQLUpdateEndpoint:
    """SPARQL Update endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLUpdateEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL update routes."""
        
        # POST endpoint for SPARQL updates
        @self.router.post(
            "/{space_id}/update",
            response_model=SPARQLUpdateResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Update",
            description="Execute a SPARQL update operation (INSERT, DELETE, LOAD, CLEAR, etc.) against the specified space"
        )
        async def sparql_update_post(
            space_id: str,
            request: SPARQLUpdateRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_update(space_id, request.update, current_user)
        
        # Form-based endpoint for SPARQL updates (SPARQL 1.1 Protocol compatibility)
        @self.router.post(
            "/{space_id}/update-form",
            response_model=SPARQLUpdateResponse,
            tags=["SPARQL"],
            summary="Execute SPARQL Update (Form)",
            description="Execute a SPARQL update operation via form data"
        )
        async def sparql_update_form(
            space_id: str,
            update: str = Form(..., description="SPARQL update string"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_update(space_id, update, current_user)
    
    async def _execute_update(
        self,
        space_id: str,
        update: str,
        current_user: Dict
    ) -> SPARQLUpdateResponse:
        """Execute a SPARQL update and return results."""
        
        try:
            self.logger.info(f"Executing SPARQL update in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
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
            
            # Execute SPARQL update using orchestrator with PostgreSQL implementation
            import time
            start_time = time.time()
            
            from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import execute_sparql_update
            
            success = await execute_sparql_update(db_space_impl, space_id, update)
            
            update_time = time.time() - start_time
            
            if success:
                return SPARQLUpdateResponse(
                    success=True,
                    message="Update executed successfully",
                    update_time=update_time
                )
            else:
                return SPARQLUpdateResponse(
                    success=False,
                    message="Update failed",
                    update_time=update_time,
                    error="Update operation returned false"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing SPARQL update: {e}")
            return SPARQLUpdateResponse(
                success=False,
                error=str(e)
            )


def create_sparql_update_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL update router."""
    endpoint = SPARQLUpdateEndpoint(space_manager, auth_dependency)
    return endpoint.router
