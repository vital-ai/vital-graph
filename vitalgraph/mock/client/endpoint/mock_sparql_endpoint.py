"""
Mock implementation of SparqlEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- Real pyoxigraph SPARQL execution for all operations
- VitalSigns native functionality for data conversions
- Proper response model handling without mock data generation
- Direct delegation to pyoxigraph SPARQL engine
"""

from typing import Dict, Any, Optional
import time
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.sparql_model import (
    SPARQLQueryRequest, SPARQLQueryResponse, SPARQLUpdateRequest, SPARQLUpdateResponse,
    SPARQLInsertRequest, SPARQLInsertResponse, SPARQLDeleteRequest, SPARQLDeleteResponse
)


class MockSparqlEndpoint(MockBaseEndpoint):
    """Mock implementation of SparqlEndpoint with real SPARQL execution."""
    
    def execute_sparql_query(self, space_id: str, request: SPARQLQueryRequest) -> SPARQLQueryResponse:
        """
        Execute a SPARQL query using pyoxigraph with proper response handling.
        
        Args:
            space_id: Space identifier
            request: SPARQLQueryRequest containing query and format
            
        Returns:
            SPARQLQueryResponse with real pyoxigraph results
        """
        self._log_method_call("execute_sparql_query", space_id=space_id, request=request)
        
        # Extract query and format from request
        query = request.query
        format = request.format or "application/sparql-results+json"
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLQueryResponse(
                    error=f"Space {space_id} not found",
                    query_time=0.001
                )
            
            start_time = time.time()
            
            # Execute query using pyoxigraph
            result = self._execute_sparql_query(space, query)
            query_time = time.time() - start_time
            
            # Return appropriate response based on query type
            if result.get("query_type") == "SELECT":
                return SPARQLQueryResponse(
                    head={"vars": list(result["bindings"][0].keys()) if result.get("bindings") else []},
                    results={"bindings": result.get("bindings", [])},
                    query_time=query_time
                )
            elif result.get("query_type") == "ASK":
                return SPARQLQueryResponse(
                    boolean=result.get("result", False),
                    query_time=query_time
                )
            elif result.get("query_type") == "CONSTRUCT":
                return SPARQLQueryResponse(
                    triples=result.get("triples", []),
                    query_time=query_time
                )
            else:
                return SPARQLQueryResponse(
                    error=result.get("error", "Unknown query error"),
                    query_time=query_time
                )
                
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            return SPARQLQueryResponse(
                error=str(e),
                query_time=time.time() - start_time if 'start_time' in locals() else 0.001
            )
    
    def execute_sparql_insert(self, space_id: str, request: SPARQLInsertRequest) -> SPARQLInsertResponse:
        """
        Execute a SPARQL insert operation using pyoxigraph.
        
        Args:
            space_id: Space identifier
            request: SPARQLInsertRequest containing update query
            
        Returns:
            SPARQLInsertResponse with real pyoxigraph results
        """
        self._log_method_call("execute_sparql_insert", space_id=space_id, request=request)
        
        # Extract query from request
        query = request.update
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLInsertResponse(
                    error=f"Space {space_id} not found",
                    insert_time=0.001
                )
            
            start_time = time.time()
            
            # Execute insert using pyoxigraph
            result = space.update_sparql(query)
            insert_time = time.time() - start_time
            
            if result.get("success"):
                return SPARQLInsertResponse(
                    success=True,
                    message=f"Successfully inserted {result.get('inserted_triples', 0)} triples",
                    insert_time=insert_time,
                    inserted_triples=result.get("inserted_triples", 0)
                )
            else:
                return SPARQLInsertResponse(
                    success=False,
                    message=result.get("error", "Insert failed"),
                    error=result.get("error", "Insert failed"),
                    insert_time=insert_time
                )
                
        except Exception as e:
            self.logger.error(f"Error executing SPARQL insert: {e}")
            return SPARQLInsertResponse(
                success=False,
                message=f"SPARQL insert failed: {str(e)}",
                error=str(e),
                insert_time=time.time() - start_time if 'start_time' in locals() else 0.001
            )
    
    def execute_sparql_update(self, space_id: str, request: SPARQLUpdateRequest) -> SPARQLUpdateResponse:
        """
        Execute a SPARQL update operation using pyoxigraph.
        
        Args:
            space_id: Space identifier
            request: SPARQLUpdateRequest containing update query
            
        Returns:
            SPARQLUpdateResponse with real pyoxigraph results
        """
        self._log_method_call("execute_sparql_update", space_id=space_id, request=request)
        
        # Extract query from request
        query = request.update
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLUpdateResponse(
                    error=f"Space {space_id} not found",
                    update_time=0.001
                )
            
            start_time = time.time()
            
            # Execute update using pyoxigraph
            result = space.update_sparql(query)
            update_time = time.time() - start_time
            
            if result.get("success"):
                return SPARQLUpdateResponse(
                    success=True,
                    message="SPARQL update completed successfully",
                    update_time=update_time
                )
            else:
                return SPARQLUpdateResponse(
                    success=False,
                    message=result.get("error", "Update failed"),
                    error=result.get("error", "Update failed"),
                    update_time=update_time
                )
                
        except Exception as e:
            self.logger.error(f"Error executing SPARQL update: {e}")
            return SPARQLUpdateResponse(
                success=False,
                message=f"SPARQL update failed: {str(e)}",
                error=str(e),
                update_time=time.time() - start_time if 'start_time' in locals() else 0.001
            )
    
    def execute_sparql_delete(self, space_id: str, request: SPARQLDeleteRequest) -> SPARQLDeleteResponse:
        """
        Execute a SPARQL delete operation using pyoxigraph.
        
        Args:
            space_id: Space identifier
            request: SPARQLDeleteRequest containing delete query
            
        Returns:
            SPARQLDeleteResponse with real pyoxigraph results
        """
        self._log_method_call("execute_sparql_delete", space_id=space_id, request=request)
        
        # Extract query from request
        query = request.update
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLDeleteResponse(
                    error=f"Space {space_id} not found",
                    delete_time=0.001
                )
            
            start_time = time.time()
            
            # Execute delete using pyoxigraph
            result = space.update_sparql(query)
            delete_time = time.time() - start_time
            
            if result.get("success"):
                return SPARQLDeleteResponse(
                    success=True,
                    message=f"Successfully deleted {result.get('deleted_triples', 0)} triples",
                    delete_time=delete_time,
                    deleted_triples=result.get("deleted_triples", 0)
                )
            else:
                return SPARQLDeleteResponse(
                    success=False,
                    message=result.get("error", "Delete failed"),
                    error=result.get("error", "Delete failed"),
                    delete_time=delete_time
                )
                
        except Exception as e:
            self.logger.error(f"Error executing SPARQL delete: {e}")
            return SPARQLDeleteResponse(
                success=False,
                message=f"SPARQL delete failed: {str(e)}",
                error=str(e),
                delete_time=time.time() - start_time if 'start_time' in locals() else 0.001
            )
