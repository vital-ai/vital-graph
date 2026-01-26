"""
Mock implementation of KGQueriesEndpoint for entity-to-entity connection queries.

This endpoint provides two distinct query types:
1. Relation-based queries: Find entities connected via Edge_hasKGRelation
2. Frame-based queries: Find entities connected via shared KGFrames

Each query type is completely separate and never combined.
Results focus on connection triples: source entity -> connection -> destination entity
"""

from typing import Dict, Any, Optional, List
import logging
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgqueries_model import (
    KGQueryRequest, KGQueryResponse, RelationConnection, FrameConnection,
    KGQueryStatsResponse
)
from vitalgraph.sparql.kg_connection_query_builder import KGConnectionQueryBuilder

logger = logging.getLogger(__name__)


class MockKGQueriesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGQueriesEndpoint with VitalSigns native functionality."""
    
    def __init__(self, client=None, space_manager=None, *, config=None):
        """Initialize with connection query builder."""
        super().__init__(client, space_manager, config=config)
        self.connection_query_builder = KGConnectionQueryBuilder()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
    
    def query_connections(self, space_id: str, graph_id: str, 
                         query_request: KGQueryRequest) -> KGQueryResponse:
        """
        Query entities connected via relations or shared frames based on query_type.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_request: Query criteria and pagination
            
        Returns:
            KGQueryResponse with connections based on query_type
        """
        query_type = query_request.criteria.query_type
        logger.info(f"Executing {query_type} query in space {space_id}, graph {graph_id}")
        
        try:
            # Get space and validate
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return KGQueryResponse(
                    query_type=query_type,
                    relation_connections=[] if query_type == "relation" else None,
                    frame_connections=[] if query_type == "frame" else None,
                    total_count=0,
                    page_size=query_request.page_size,
                    offset=query_request.offset
                )
            
            if query_type == "relation":
                return self._execute_relation_query(space, graph_id, query_request)
            elif query_type == "frame":
                return self._execute_frame_query(space, graph_id, query_request)
            else:
                raise ValueError(f"Invalid query_type: {query_type}. Must be 'relation' or 'frame'")
                
        except Exception as e:
            logger.error(f"Error executing {query_type} query: {e}")
            return KGQueryResponse(
                query_type=query_type,
                relation_connections=[] if query_type == "relation" else None,
                frame_connections=[] if query_type == "frame" else None,
                total_count=0,
                page_size=query_request.page_size,
                offset=query_request.offset
            )
    
    def _execute_relation_query(self, space, graph_id: str, query_request: KGQueryRequest) -> KGQueryResponse:
        """Execute relation-based query."""
        # Build SPARQL query for relation connections
        sparql_query = self.connection_query_builder.build_relation_query(
            query_request.criteria, graph_id
        )
        
        logger.debug(f"Generated relation SPARQL query: {sparql_query}")
        
        # Execute SPARQL query
        results = space.triple_store.query(sparql_query)
        
        # Convert results to RelationConnection objects
        connections = []
        for result in results:
            connection = RelationConnection(
                source_entity_uri=str(result['source_entity']),
                destination_entity_uri=str(result['destination_entity']),
                relation_edge_uri=str(result['relation_edge']),
                relation_type_uri=str(result['relation_type'])
            )
            connections.append(connection)
        
        # Apply pagination
        total_count = len(connections)
        start_idx = query_request.offset
        end_idx = start_idx + query_request.page_size
        paginated_connections = connections[start_idx:end_idx]
        
        logger.info(f"Found {total_count} relation connections, returning {len(paginated_connections)}")
        
        return KGQueryResponse(
            query_type="relation",
            relation_connections=paginated_connections,
            frame_connections=None,
            total_count=total_count,
            page_size=query_request.page_size,
            offset=query_request.offset
        )
    
    def _execute_frame_query(self, space, graph_id: str, query_request: KGQueryRequest) -> KGQueryResponse:
        """Execute frame-based query."""
        # Build SPARQL query for frame connections
        sparql_query = self.connection_query_builder.build_frame_query(
            query_request.criteria, graph_id
        )
        
        logger.debug(f"Generated frame SPARQL query: {sparql_query}")
        
        # Execute SPARQL query
        results = space.triple_store.query(sparql_query)
        
        # Convert results to FrameConnection objects
        connections = []
        for result in results:
            connection = FrameConnection(
                source_entity_uri=str(result['source_entity']),
                destination_entity_uri=str(result['destination_entity']),
                shared_frame_uri=str(result['shared_frame']),
                frame_type_uri=str(result['frame_type'])
            )
            connections.append(connection)
        
        # Apply pagination
        total_count = len(connections)
        start_idx = query_request.offset
        end_idx = start_idx + query_request.page_size
        paginated_connections = connections[start_idx:end_idx]
        
        logger.info(f"Found {total_count} frame connections, returning {len(paginated_connections)}")
        
        return KGQueryResponse(
            query_type="frame",
            relation_connections=None,
            frame_connections=paginated_connections,
            total_count=total_count,
            page_size=query_request.page_size,
            offset=query_request.offset
        )
    
    def get_query_stats(self, space_id: str, graph_id: str) -> KGQueryStatsResponse:
        """
        Get statistics about entities, relations, and frames in the graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            KGQueryStatsResponse with graph statistics
        """
        logger.info(f"Getting query stats for space {space_id}, graph {graph_id}")
        
        try:
            # Get space and validate
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return KGQueryStatsResponse(
                    total_entities=0,
                    total_relations=0,
                    total_frames=0,
                    relation_connections_count=0,
                    frame_connections_count=0
                )
            
            # Count entities
            entity_count_query = f"""
            PREFIX haley: <{self.haley_prefix}>
            SELECT (COUNT(DISTINCT ?entity) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?entity a haley:KGEntity .
                }}
            }}
            """
            entity_results = space.triple_store.query(entity_count_query)
            total_entities = int(entity_results[0]['count']) if entity_results else 0
            
            # Count relations
            relation_count_query = f"""
            PREFIX haley: <{self.haley_prefix}>
            SELECT (COUNT(DISTINCT ?relation) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?relation a haley:Edge_hasKGRelation .
                }}
            }}
            """
            relation_results = space.triple_store.query(relation_count_query)
            total_relations = int(relation_results[0]['count']) if relation_results else 0
            
            # Count frames
            frame_count_query = f"""
            PREFIX haley: <{self.haley_prefix}>
            SELECT (COUNT(DISTINCT ?frame) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?frame a haley:KGFrame .
                }}
            }}
            """
            frame_results = space.triple_store.query(frame_count_query)
            total_frames = int(frame_results[0]['count']) if frame_results else 0
            
            # Count relation connections (entity pairs connected via relations)
            relation_connections_query = f"""
            PREFIX haley: <{self.haley_prefix}>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT (COUNT(*) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?relation a haley:Edge_hasKGRelation .
                    ?relation vital:hasEdgeSource ?source .
                    ?relation vital:hasEdgeDestination ?dest .
                }}
            }}
            """
            relation_conn_results = space.triple_store.query(relation_connections_query)
            relation_connections_count = int(relation_conn_results[0]['count']) if relation_conn_results else 0
            
            # Count frame connections (entity pairs connected via shared frames)
            frame_connections_query = f"""
            PREFIX haley: <{self.haley_prefix}>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT (COUNT(*) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge1 a haley:Edge_hasEntityKGFrame .
                    ?edge1 vital:hasEdgeSource ?source .
                    ?edge1 vital:hasEdgeDestination ?frame .
                    
                    ?edge2 a haley:Edge_hasEntityKGFrame .
                    ?edge2 vital:hasEdgeSource ?dest .
                    ?edge2 vital:hasEdgeDestination ?frame .
                    
                    FILTER(?source != ?dest)
                }}
            }}
            """
            frame_conn_results = space.triple_store.query(frame_connections_query)
            frame_connections_count = int(frame_conn_results[0]['count']) if frame_conn_results else 0
            
            logger.info(f"Stats: {total_entities} entities, {total_relations} relations, {total_frames} frames")
            
            return KGQueryStatsResponse(
                total_entities=total_entities,
                total_relations=total_relations,
                total_frames=total_frames,
                relation_connections_count=relation_connections_count,
                frame_connections_count=frame_connections_count
            )
            
        except Exception as e:
            logger.error(f"Error getting query stats: {e}")
            return KGQueryStatsResponse(
                total_entities=0,
                total_relations=0,
                total_frames=0,
                relation_connections_count=0,
                frame_connections_count=0
            )
