"""SPARQL Graph Management Endpoint for VitalGraph

Implements SPARQL 1.1 graph management operations (CREATE, DROP, CLEAR, COPY, MOVE, ADD)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging

from ..model.sparql_model import (
    SPARQLGraphRequest,
    SPARQLGraphResponse,
    GraphInfo,
    GraphInfoResponse
)


class SPARQLGraphEndpoint:
    """SPARQL Graph endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLGraphEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL graph management routes."""
        
        self.logger.info("Setting up SPARQL graph routes...")
        
        # GET endpoint to list graphs (must come before catch-all graph/{graph_uri:path})
        @self.router.get(
            "/{space_id}/graphs",
            response_model=List[GraphInfo],
            tags=["Graphs"],
            summary="List Graphs",
            description="List all graphs in the specified space"
        )
        async def list_graphs(
            space_id: str,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            self.logger.info(f"List graphs endpoint called for space: {space_id}")
            return await self._list_graphs(space_id, current_user)
        
        self.logger.info("Registered GET /{space_id}/graphs route")
        
        # POST endpoint for graph operations
        @self.router.post(
            "/{space_id}/graph",
            response_model=SPARQLGraphResponse,
            tags=["Graphs"],
            summary="Execute Graph Operation",
            description="Execute a SPARQL graph operation (CREATE, DROP, CLEAR, COPY, MOVE, ADD)"
        )
        async def sparql_graph_operation(
            space_id: str,
            request: SPARQLGraphRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_graph_operation(space_id, request, current_user)
        
        # GET endpoint to get graph info (catch-all route - must come after specific routes)
        @self.router.get(
            "/{space_id}/graph/{graph_uri:path}",
            response_model=GraphInfoResponse,
            tags=["Graphs"],
            summary="Get Graph Info",
            description="Get information about a specific graph"
        )
        async def get_graph_info(
            space_id: str,
            graph_uri: str,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._get_graph_info(space_id, graph_uri, current_user)
        
        # PUT endpoint to create graph
        @self.router.put(
            "/{space_id}/graph/{graph_uri:path}",
            response_model=SPARQLGraphResponse,
            tags=["Graphs"],
            summary="Create Graph",
            description="Create a new empty graph"
        )
        async def create_graph(
            space_id: str,
            graph_uri: str,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            request = SPARQLGraphRequest(
                operation="CREATE",
                target_graph_uri=graph_uri
            )
            return await self._execute_graph_operation(space_id, request, current_user)
        
        # DELETE endpoint to drop graph
        @self.router.delete(
            "/{space_id}/graph/{graph_uri:path}",
            response_model=SPARQLGraphResponse,
            tags=["Graphs"],
            summary="Drop Graph",
            description="Drop a graph and all its triples"
        )
        async def drop_graph(
            space_id: str,
            graph_uri: str,
            silent: bool = Query(False, description="Execute silently"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            request = SPARQLGraphRequest(
                operation="DROP",
                target_graph_uri=graph_uri,
                silent=silent
            )
            return await self._execute_graph_operation(space_id, request, current_user)
    
    async def _execute_graph_operation(
        self,
        space_id: str,
        request: SPARQLGraphRequest,
        current_user: Dict
    ) -> SPARQLGraphResponse:
        """Execute a SPARQL graph operation."""
        
        try:
            self.logger.info(f"Executing graph operation '{request.operation}' in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
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
            
            # Get the database-specific implementation for graph operations
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
            
            # Execute the operation using PostgreSQL graph table operations
            import time
            start_time = time.time()
            
            operation = request.operation.upper()
            success = False
            
            if operation == "CREATE":
                if not request.target_graph_uri:
                    raise HTTPException(
                        status_code=400,
                        detail="target_graph_uri required for CREATE operation"
                    )
                success = await db_space_impl.graphs.create_graph(space_id, request.target_graph_uri)
                
            elif operation == "DROP":
                if not request.target_graph_uri:
                    raise HTTPException(
                        status_code=400,
                        detail="target_graph_uri required for DROP operation"
                    )
                success = await db_space_impl.graphs.drop_graph(space_id, request.target_graph_uri)
                
            elif operation == "CLEAR":
                if not request.target_graph_uri:
                    raise HTTPException(
                        status_code=400,
                        detail="target_graph_uri required for CLEAR operation"
                    )
                success = await db_space_impl.graphs.clear_graph(space_id, request.target_graph_uri)
                
            elif operation in ["COPY", "MOVE", "ADD"]:
                # For complex operations, fall back to SPARQL update
                sparql_query = self._build_graph_operation_query(request)
                success = await space_impl.execute_sparql_update(space_id, sparql_query)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported graph operation: {operation}"
                )
            
            operation_time = time.time() - start_time
            
            if success:
                return SPARQLGraphResponse(
                    success=True,
                    operation=request.operation,
                    graph_uri=request.target_graph_uri or request.source_graph_uri,
                    message=f"{request.operation} operation completed successfully",
                    operation_time=operation_time
                )
            else:
                return SPARQLGraphResponse(
                    success=False,
                    operation=request.operation,
                    graph_uri=request.target_graph_uri or request.source_graph_uri,
                    message=f"{request.operation} operation failed",
                    operation_time=operation_time,
                    error="Graph operation returned false"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error executing graph operation: {e}")
            return SPARQLGraphResponse(
                success=False,
                operation=request.operation,
                graph_uri=request.target_graph_uri or request.source_graph_uri,
                message=f"Graph operation failed: {str(e)}",
                error=str(e)
            )
    
    def _build_graph_operation_query(self, request: SPARQLGraphRequest) -> str:
        """Build SPARQL query for graph operation."""
        
        operation = request.operation.upper()
        silent = "SILENT " if request.silent else ""
        
        if operation == "CREATE":
            if not request.target_graph_uri:
                raise ValueError("target_graph_uri required for CREATE operation")
            return f"CREATE {silent}GRAPH <{request.target_graph_uri}>"
        
        elif operation == "DROP":
            if not request.target_graph_uri:
                raise ValueError("target_graph_uri required for DROP operation")
            return f"DROP {silent}GRAPH <{request.target_graph_uri}>"
        
        elif operation == "CLEAR":
            if not request.target_graph_uri:
                raise ValueError("target_graph_uri required for CLEAR operation")
            return f"CLEAR {silent}GRAPH <{request.target_graph_uri}>"
        
        elif operation == "COPY":
            if not request.source_graph_uri or not request.target_graph_uri:
                raise ValueError("source_graph_uri and target_graph_uri required for COPY operation")
            return f"COPY {silent}GRAPH <{request.source_graph_uri}> TO <{request.target_graph_uri}>"
        
        elif operation == "MOVE":
            if not request.source_graph_uri or not request.target_graph_uri:
                raise ValueError("source_graph_uri and target_graph_uri required for MOVE operation")
            return f"MOVE {silent}GRAPH <{request.source_graph_uri}> TO <{request.target_graph_uri}>"
        
        elif operation == "ADD":
            if not request.source_graph_uri or not request.target_graph_uri:
                raise ValueError("source_graph_uri and target_graph_uri required for ADD operation")
            return f"ADD {silent}GRAPH <{request.source_graph_uri}> TO <{request.target_graph_uri}>"
        
        else:
            raise ValueError(f"Unsupported graph operation: {operation}")
    
    async def _list_graphs(self, space_id: str, current_user: Dict) -> List[GraphInfo]:
        """List all graphs in the space."""
        
        try:
            self.logger.info(f"Listing graphs in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
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
        
            # Get the database-specific implementation for graph operations
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                raise HTTPException(
                    status_code=500,
                    detail="Database-specific space implementation not available"
                )
        
            # Get graphs using PostgreSQL graph table operations
            graphs_data = await db_space_impl.graphs.list_graphs(space_id)
            
            # Convert to GraphInfo objects
            graph_infos = []
            for graph_data in graphs_data:
                graph_info = GraphInfo(
                    graph_uri=graph_data['graph_uri'],
                    triple_count=graph_data.get('triple_count', 0),
                    created_time=graph_data.get('created_time', '').isoformat() if graph_data.get('created_time') else None,
                    updated_time=graph_data.get('updated_time', '').isoformat() if graph_data.get('updated_time') else None
                )
                graph_infos.append(graph_info)
            
            return graph_infos
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing graphs: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error listing graphs: {str(e)}"
            )
    
    async def _get_graph_info(self, space_id: str, graph_uri: str, current_user: Dict) -> GraphInfoResponse:
        """Get information about a specific graph."""
        
        try:
            self.logger.info(f"Getting info for graph '{graph_uri}' in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager
            if self.space_manager is None:
                return GraphInfoResponse(
                    success=False,
                    graph_info=None,
                    error="Space manager not available",
                    message="Internal server error"
                )
        
            # Validate space exists
            if not self.space_manager.has_space(space_id):
                return GraphInfoResponse(
                    success=False,
                    graph_info=None,
                    error=f"Space '{space_id}' not found",
                    message="Space not found"
                )
        
            # Get space record
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return GraphInfoResponse(
                    success=False,
                    graph_info=None,
                    error=f"Space '{space_id}' not available",
                    message="Space not available"
                )
        
            space_impl = space_record.space_impl
        
            # Get the database-specific implementation for graph operations
            db_space_impl = space_impl.get_db_space_impl()
            if not db_space_impl:
                return GraphInfoResponse(
                    success=False,
                    graph_info=None,
                    error="Database-specific space implementation not available",
                    message="Internal server error"
                )
        
            # Get graph info using PostgreSQL graph table operations
            graph_data = await db_space_impl.graphs.get_graph(space_id, graph_uri)
            
            if not graph_data:
                # Return error response for non-existent graphs
                self.logger.info(f"Graph '{graph_uri}' not found in space '{space_id}'")
                return GraphInfoResponse(
                    success=False,
                    graph_info=None,
                    error=f"Graph '{graph_uri}' not found in space '{space_id}'",
                    message="Graph not found"
                )
            
            # Return success response with graph info
            graph_info = GraphInfo(
                graph_uri=graph_data['graph_uri'],
                triple_count=graph_data.get('triple_count', 0),
                created_time=graph_data.get('created_time', '').isoformat() if graph_data.get('created_time') else None,
                updated_time=graph_data.get('updated_time', '').isoformat() if graph_data.get('updated_time') else None
            )
            
            return GraphInfoResponse(
                success=True,
                graph_info=graph_info,
                error=None,
                message="Graph info retrieved successfully"
            )
        
        except Exception as e:
            self.logger.error(f"Error getting graph info: {e}")
            return GraphInfoResponse(
                success=False,
                graph_info=None,
                error=str(e),
                message="Error getting graph info"
            )


def create_sparql_graph_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the SPARQL graph router."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Creating SPARQL graph router...")
    endpoint = SPARQLGraphEndpoint(space_manager, auth_dependency)
    logger.info(f"SPARQL graph router created with {len(endpoint.router.routes)} routes")
    return endpoint.router
