"""
Mock implementation of GraphsEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- Real pyoxigraph graph operations for CREATE, DROP, CLEAR
- SPARQL queries to get actual graph information and triple counts
- VitalSigns native functionality for data conversions
- No mock data generation - all operations use real pyoxigraph storage
"""

import time
from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.sparql_model import (
    GraphInfo, SPARQLGraphRequest, SPARQLGraphResponse
)


class MockGraphsEndpoint(MockBaseEndpoint):
    """Mock implementation of GraphsEndpoint."""
    
    def _parse_sparql_integer(self, value_str: str) -> int:
        """Parse SPARQL integer result that may include XSD datatype."""
        try:
            # Handle XSD datatype format like "0"^^<http://www.w3.org/2001/XMLSchema#integer>
            if "^^" in value_str:
                value_str = value_str.split("^^")[0].strip('"')
            return int(value_str)
        except (ValueError, AttributeError):
            return 0
    
    def list_graphs(self, space_id: str) -> List[GraphInfo]:
        """
        List graphs in a space by examining the MockGraph objects managed by the space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of GraphInfo objects with graph metadata and triple counts
        """
        self._log_method_call("list_graphs", space_id=space_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return []
            
            # List all MockGraph objects managed by the space
            graphs = []
            for mock_graph in space.graphs.values():
                # Get triple count for this graph's URI from the SPARQL store
                query = f"""
                SELECT (COUNT(*) as ?triple_count) WHERE {{
                    GRAPH <{mock_graph.graph_uri}> {{
                        ?s ?p ?o .
                    }}
                }}
                """
                
                results = self._execute_sparql_query(space, query)
                triple_count = 0
                if results.get("bindings"):
                    triple_count_str = results["bindings"][0].get("triple_count", {}).get("value", "0")
                    triple_count = self._parse_sparql_integer(triple_count_str)
                
                # Use current time as placeholder for created/updated times
                current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                
                graph_info = GraphInfo(
                    graph_uri=mock_graph.graph_uri,
                    triple_count=triple_count,
                    created_time=current_time,
                    updated_time=current_time
                )
                graphs.append(graph_info)
            
            return graphs
            
        except Exception as e:
            self.logger.error(f"Error listing graphs: {e}")
            return []
    
    def get_graph_info(self, space_id: str, graph_uri: str) -> GraphInfo:
        """
        Get information about a specific graph using real pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to get information about
            
        Returns:
            GraphInfo object with real graph data
        """
        self._log_method_call("get_graph_info", space_id=space_id, graph_uri=graph_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                # Return empty graph info for non-existent space
                current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return GraphInfo(
                    graph_uri=graph_uri,
                    triple_count=0,
                    created_time=current_time,
                    updated_time=current_time
                )
            
            # Query for triple count in specific graph
            query = f"""
            SELECT (COUNT(*) as ?triple_count) WHERE {{
                GRAPH <{graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            triple_count = 0
            if results.get("bindings"):
                triple_count_str = results["bindings"][0].get("triple_count", {}).get("value", "0")
                triple_count = self._parse_sparql_integer(triple_count_str)
            
            # Use current time as placeholder for created/updated times
            current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            return GraphInfo(
                graph_uri=graph_uri,
                triple_count=triple_count,
                created_time=current_time,
                updated_time=current_time
            )
            
        except Exception as e:
            self.logger.error(f"Error getting graph info for {graph_uri}: {e}")
            current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return GraphInfo(
                graph_uri=graph_uri,
                triple_count=0,
                updated_time=current_time
            )
    
    def create_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """
        Create a new MockGraph object in the space.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to create
            
        Returns:
            SPARQLGraphResponse with operation results
        """
        self._log_method_call("create_graph", space_id=space_id, graph_uri=graph_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLGraphResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    operation_time=0.001
                )
            
            start_time = time.time()
            
            # Check if graph already exists
            existing_graph = space.get_graph_by_uri(graph_uri)
            if existing_graph:
                return SPARQLGraphResponse(
                    success=False,
                    message=f"Graph {graph_uri} already exists",
                    operation_time=time.time() - start_time
                )
            
            # Create MockGraph object in the space
            mock_graph = space.add_graph(graph_uri, name=f"Graph {graph_uri}")
            
            operation_time = time.time() - start_time
            
            return SPARQLGraphResponse(
                success=True,
                message="Graph created successfully",
                operation_time=operation_time
            )
                
        except Exception as e:
            self.logger.error(f"Error creating graph {graph_uri}: {e}")
            return SPARQLGraphResponse(
                success=False,
                operation_time=0.001
            )
    
    def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> SPARQLGraphResponse:
        """
        Drop (delete) a MockGraph object from the space and clear its data.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to drop
            silent: Whether to suppress errors if graph doesn't exist
            
        Returns:
            SPARQLGraphResponse with operation results
        """
        self._log_method_call("drop_graph", space_id=space_id, graph_uri=graph_uri, silent=silent)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLGraphResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    operation_time=0.001
                )
            
            start_time = time.time()
            
            # Find the MockGraph by URI
            mock_graph = space.get_graph_by_uri(graph_uri)
            if not mock_graph:
                if silent:
                    return SPARQLGraphResponse(
                        success=True,
                        message="Graph dropped successfully",
                        operation_time=time.time() - start_time
                    )
                else:
                    return SPARQLGraphResponse(
                        success=False,
                        message=f"The graph <{graph_uri}> does not exist",
                        operation_time=time.time() - start_time
                    )
            
            # Remove the MockGraph object from the space (this also clears its data)
            removed = space.remove_graph(mock_graph.graph_id)
            
            operation_time = time.time() - start_time
            
            if removed:
                return SPARQLGraphResponse(
                    success=True,
                    message="Graph dropped successfully",
                    operation_time=operation_time
                )
            else:
                return SPARQLGraphResponse(
                    success=False,
                    message="Graph drop failed",
                    operation_time=operation_time
                )
                
        except Exception as e:
            self.logger.error(f"Error dropping graph {graph_uri}: {e}")
            return SPARQLGraphResponse(
                success=False,
                message=str(e),
                operation_time=0.001
            )
    
    def clear_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """
        Clear a graph (remove all triples but keep the MockGraph object).
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to clear
            
        Returns:
            SPARQLGraphResponse with operation results
        """
        self._log_method_call("clear_graph", space_id=space_id, graph_uri=graph_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return SPARQLGraphResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    operation_time=0.001
                )
            
            start_time = time.time()
            
            # Find the MockGraph by URI
            mock_graph = space.get_graph_by_uri(graph_uri)
            if not mock_graph:
                return SPARQLGraphResponse(
                    success=False,
                    message=f"The graph <{graph_uri}> does not exist",
                    operation_time=time.time() - start_time
                )
            
            # Clear all triples from this graph using SPARQL DELETE
            delete_query = f"""
            DELETE {{
                GRAPH <{graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            """
            
            result = space.update_sparql(delete_query)
            operation_time = time.time() - start_time
            
            # SPARQL DELETE doesn't fail for empty graphs, so we consider it successful
            return SPARQLGraphResponse(
                success=True,
                message="Graph cleared successfully",
                operation_time=operation_time
            )
                
        except Exception as e:
            self.logger.error(f"Error clearing graph {graph_uri}: {e}")
            return SPARQLGraphResponse(
                success=False,
                message=str(e),
                operation_time=0.001
            )
    
