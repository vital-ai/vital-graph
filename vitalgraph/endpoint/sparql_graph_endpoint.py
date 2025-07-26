"""SPARQL Graph Management Endpoint for VitalGraph

Implements SPARQL 1.1 graph management operations (CREATE, DROP, CLEAR, COPY, MOVE, ADD)
following the SPARQL 1.1 Update specification.
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging


class SPARQLGraphRequest(BaseModel):
    """Request model for SPARQL graph operations."""
    operation: str = Field(
        ...,
        description="Graph operation (CREATE, DROP, CLEAR, COPY, MOVE, ADD)",
        example="CREATE"
    )
    source_graph_uri: Optional[str] = Field(
        None,
        description="Source graph URI for COPY, MOVE, ADD operations",
        example="http://example.org/source-graph"
    )
    target_graph_uri: Optional[str] = Field(
        None,
        description="Target graph URI for the operation",
        example="http://example.org/target-graph"
    )
    silent: bool = Field(
        False,
        description="Whether to execute operation silently (ignore errors)"
    )


class SPARQLGraphResponse(BaseModel):
    """Response model for SPARQL graph operation results."""
    success: bool = Field(
        ...,
        description="Whether the graph operation was successful"
    )
    operation: str = Field(
        ...,
        description="The graph operation that was executed"
    )
    graph_uri: Optional[str] = Field(
        None,
        description="Graph URI that was operated on"
    )
    message: Optional[str] = Field(
        None,
        description="Success or error message"
    )
    operation_time: Optional[float] = Field(
        None,
        description="Operation execution time in seconds"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if operation failed"
    )


class GraphInfo(BaseModel):
    """Information about a graph."""
    graph_uri: str = Field(
        ...,
        description="Graph URI"
    )
    triple_count: Optional[int] = Field(
        None,
        description="Number of triples in the graph"
    )
    created_time: Optional[str] = Field(
        None,
        description="Graph creation timestamp"
    )
    updated_time: Optional[str] = Field(
        None,
        description="Graph last update timestamp"
    )


class SPARQLGraphEndpoint:
    """SPARQL Graph Management endpoint handler."""
    
    def __init__(self, db_impl, auth_dependency):
        self.db_impl = db_impl
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SPARQLGraphEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup SPARQL graph management routes."""
        
        # POST endpoint for graph operations
        @self.router.post(
            "/{space_id}/graph",
            response_model=SPARQLGraphResponse,
            tags=["SPARQL"],
            summary="Execute Graph Operation",
            description="Execute a SPARQL graph operation (CREATE, DROP, CLEAR, COPY, MOVE, ADD)"
        )
        async def sparql_graph_operation(
            space_id: str,
            request: SPARQLGraphRequest,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._execute_graph_operation(space_id, request, current_user)
        
        # GET endpoint to list graphs
        @self.router.get(
            "/{space_id}/graphs",
            response_model=List[GraphInfo],
            tags=["SPARQL"],
            summary="List Graphs",
            description="List all graphs in the specified space"
        )
        async def list_graphs(
            space_id: str,
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._list_graphs(space_id, current_user)
        
        # GET endpoint to get graph info
        @self.router.get(
            "/{space_id}/graph/{graph_uri:path}",
            response_model=GraphInfo,
            tags=["SPARQL"],
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
            tags=["SPARQL"],
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
            tags=["SPARQL"],
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
            self.logger.info(f"Executing SPARQL graph operation '{request.operation}' in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
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
            
            # Get cached SPARQL implementation (preserves term cache across requests)
            sparql_impl = space_impl.get_sparql_impl(space_id)
            
            # Build SPARQL update query based on operation
            sparql_query = self._build_graph_operation_query(request)
            
            self.logger.debug(f"Generated SPARQL: {sparql_query}")
            
            # Execute the operation
            import time
            start_time = time.time()
            
            success = await sparql_impl.execute_sparql_update(space_id, sparql_query)
            
            operation_time = time.time() - start_time
            
            if success:
                return SPARQLGraphResponse(
                    success=True,
                    operation=request.operation,
                    graph_uri=request.target_graph_uri or request.source_graph_uri,
                    message=f"{request.operation} operation executed successfully",
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
            self.logger.error(f"Error executing SPARQL graph operation: {e}")
            return SPARQLGraphResponse(
                success=False,
                operation=request.operation,
                graph_uri=request.target_graph_uri or request.source_graph_uri,
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
            # This would typically query the graph metadata table
            # For now, return a placeholder implementation
            self.logger.info(f"Listing graphs in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # TODO: Implement actual graph listing from database
            return [
                GraphInfo(
                    graph_uri="urn:___GLOBAL",
                    triple_count=0,
                    created_time="2025-01-01T00:00:00Z",
                    updated_time="2025-01-01T00:00:00Z"
                )
            ]
        
        except Exception as e:
            self.logger.error(f"Error listing graphs: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error listing graphs: {str(e)}"
            )
    
    async def _get_graph_info(self, space_id: str, graph_uri: str, current_user: Dict) -> GraphInfo:
        """Get information about a specific graph."""
        
        try:
            self.logger.info(f"Getting info for graph '{graph_uri}' in space '{space_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # TODO: Implement actual graph info retrieval from database
            return GraphInfo(
                graph_uri=graph_uri,
                triple_count=0,
                created_time="2025-01-01T00:00:00Z",
                updated_time="2025-01-01T00:00:00Z"
            )
        
        except Exception as e:
            self.logger.error(f"Error getting graph info: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting graph info: {str(e)}"
            )


def create_sparql_graph_router(db_impl, auth_dependency) -> APIRouter:
    """Create and return the SPARQL graph management router."""
    endpoint = SPARQLGraphEndpoint(db_impl, auth_dependency)
    return endpoint.router
