#!/usr/bin/env python3
"""
KG SPARQL Query Processor

Processor for handling SPARQL query generation and execution for KG operations.
Refactored from KGEntities endpoint to reduce code complexity and improve reusability.
"""

import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

from .kg_sparql_utils import KGSparqlUtils, KGSparqlQueryBuilder

logger = logging.getLogger(__name__)


class KGSparqlQueryProcessor:
    """Processor for SPARQL query generation and criteria conversion."""
    
    def __init__(self, backend_adapter, logger_instance=None):
        """
        Initialize the SPARQL query processor.
        
        Args:
            backend_adapter: Backend adapter for SPARQL execution
            logger_instance: Optional logger instance
        """
        self.backend = backend_adapter
        self.logger = logger_instance or logger
        self.utils = KGSparqlUtils()
        self.query_builder = KGSparqlQueryBuilder()
    
    def convert_query_criteria_to_sparql(self, criteria):
        """
        Convert Pydantic EntityQueryCriteria to SPARQL dataclass format.
        
        Args:
            criteria: Pydantic EntityQueryCriteria object
            
        Returns:
            SPARQL-compatible criteria object
        """
        try:
            from ..sparql.kg_query_builder import (
                EntityQueryCriteria as SparqlEntityQueryCriteria,
                SlotCriteria as SparqlSlotCriteria,
                SortCriteria as SparqlSortCriteria
            )
            
            # Convert slot criteria
            sparql_slot_criteria = []
            if criteria.slot_criteria:
                for slot_criterion in criteria.slot_criteria:
                    sparql_slot_criteria.append(SparqlSlotCriteria(
                        slot_type=slot_criterion.slot_type,
                        comparator=slot_criterion.comparator,
                        value=slot_criterion.value
                    ))
            
            # Convert sort criteria if present
            sparql_sort_criteria = None
            if hasattr(criteria, 'sort_criteria') and criteria.sort_criteria:
                sparql_sort_criteria = []
                for sort_criterion in criteria.sort_criteria:
                    sparql_sort_criteria.append(SparqlSortCriteria(
                        sort_type=sort_criterion.sort_type,
                        slot_type=sort_criterion.slot_type,
                        frame_type=sort_criterion.frame_type,
                        property_uri=sort_criterion.property_uri,
                        sort_order=sort_criterion.sort_order,
                        priority=sort_criterion.priority
                    ))
            
            # Convert filters if present
            sparql_filters = None
            if hasattr(criteria, 'filters') and criteria.filters:
                from ..sparql.kg_query_builder import QueryFilter as SparqlQueryFilter
                sparql_filters = []
                for filter_criterion in criteria.filters:
                    sparql_filters.append(SparqlQueryFilter(
                        property_name=filter_criterion.property_name,
                        operator=filter_criterion.operator,
                        value=filter_criterion.value
                    ))
            
            # Convert frame_type to frame_criteria if provided
            sparql_frame_criteria = None
            if hasattr(criteria, 'frame_type') and criteria.frame_type:
                from ..sparql.kg_query_builder import FrameCriteria
                sparql_frame_criteria = [FrameCriteria(
                    frame_type=criteria.frame_type
                )]
            
            # Create SPARQL criteria object
            sparql_criteria = SparqlEntityQueryCriteria(
                search_string=criteria.search_string,
                entity_type=criteria.entity_type,
                frame_criteria=sparql_frame_criteria,
                slot_criteria=sparql_slot_criteria,
                sort_criteria=sparql_sort_criteria,
                filters=sparql_filters
            )
            
            return sparql_criteria
            
        except Exception as e:
            self.logger.error(f"Error converting query criteria to SPARQL format: {e}")
            raise
    
    async def execute_entity_query(self, space_id: str, graph_id: str, query_request) -> Dict[str, Any]:
        """
        Execute entity query using SPARQL criteria.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_request: Entity query request object
            
        Returns:
            Dict containing query results and metadata
        """
        try:
            self.logger.info(f"Executing entity query in space {space_id}, graph {graph_id}")
            
            # Convert criteria to SPARQL format
            sparql_criteria = self.convert_query_criteria_to_sparql(query_request.criteria)
            
            # Use the KGQueryCriteriaBuilder for SPARQL generation
            from ..sparql.kg_query_builder import KGQueryCriteriaBuilder
            query_builder = KGQueryCriteriaBuilder()
            
            # Build SPARQL query with sorting support
            if hasattr(sparql_criteria, 'sort_criteria') and sparql_criteria.sort_criteria:
                sparql_query = query_builder.build_entity_query_sparql_with_sorting(
                    criteria=sparql_criteria,
                    graph_id=graph_id,
                    page_size=query_request.page_size,
                    offset=query_request.offset
                )
            else:
                # Use existing method for backward compatibility
                sparql_query = query_builder.build_entity_query_sparql(
                    criteria=sparql_criteria,
                    graph_id=graph_id,
                    page_size=query_request.page_size,
                    offset=query_request.offset
                )
            
            self.logger.info(f"Generated SPARQL query: {sparql_query}")
            
            # Execute the query
            results = await self.backend.execute_sparql_query(space_id, sparql_query)
            
            # Process results
            entity_uris = self.utils.extract_uris_from_results(results, "entity")
            
            # Build count query for total results
            count_query = query_builder.build_entity_count_query_sparql(
                criteria=sparql_criteria,
                graph_id=graph_id
            )
            
            count_results = await self.backend.execute_sparql_query(space_id, count_query)
            total_count = self.utils.extract_count_from_results(count_results)
            
            return {
                'entity_uris': entity_uris,
                'total_count': total_count,
                'page_size': query_request.page_size,
                'offset': query_request.offset,
                'sparql_query': sparql_query,
                'count_query': count_query
            }
            
        except Exception as e:
            self.logger.error(f"Error executing entity query: {e}")
            raise
    
    async def get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                               frame_uris: Optional[List[str]] = None, 
                               page_size: int = 100, offset: int = 0, 
                               search: Optional[str] = None) -> Dict[str, Any]:
        """
        Get frames associated with an entity using SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI
            frame_uris: Optional specific frame URIs to retrieve
            page_size: Number of results per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            Dict containing frame results and metadata
        """
        try:
            self.logger.info(f"Getting entity frames for {entity_uri} in space {space_id}, graph {graph_id}")
            
            if frame_uris:
                # Get specific frames
                return await self._get_specific_frames(space_id, graph_id, entity_uri, frame_uris)
            else:
                # List frames with pagination
                return await self._list_entity_frames(space_id, graph_id, entity_uri, page_size, offset, search)
                
        except Exception as e:
            self.logger.error(f"Error getting entity frames: {e}")
            raise
    
    async def _list_entity_frames(self, space_id: str, graph_id: str, entity_uri: str,
                                 page_size: int, offset: int, search: Optional[str]) -> Dict[str, Any]:
        """List frames for entity with pagination and search."""
        try:
            # Build and execute frame discovery query
            frames_query = self.query_builder.build_frame_discovery_query(
                graph_id, entity_uri, page_size, offset, search
            )
            
            results = await self.backend.execute_sparql_query(space_id, frames_query)
            frame_uris = self.utils.extract_uris_from_results(results, "frame")
            
            # Get total count
            count_query = self.query_builder.build_frame_count_query(graph_id, entity_uri, search)
            count_results = await self.backend.execute_sparql_query(space_id, count_query)
            total_count = self.utils.extract_count_from_results(count_results)
            
            return {
                'frame_uris': frame_uris,
                'total_count': total_count,
                'page_size': page_size,
                'offset': offset,
                'search': search,
                'frames_query': frames_query,
                'count_query': count_query
            }
            
        except Exception as e:
            self.logger.error(f"Error listing entity frames: {e}")
            raise
    
    async def _get_specific_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                                  frame_uris: List[str]) -> Dict[str, Any]:
        """Get specific frames by URI."""
        try:
            frame_results = {}
            
            for frame_uri in frame_uris:
                # Get frame and its complete graph
                frame_query = self.query_builder.build_frame_graph_query(
                    graph_id, frame_uri, include_frame_graph=True
                )
                
                results = await self.backend.execute_sparql_query(space_id, frame_query)
                subject_uris = self.utils.extract_subject_uris_from_results(results)
                
                frame_results[frame_uri] = {
                    'subject_uris': subject_uris,
                    'frame_query': frame_query
                }
            
            return {
                'frame_results': frame_results,
                'entity_uri': entity_uri,
                'frame_count': len(frame_uris)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting specific frames: {e}")
            raise
    
    async def get_individual_frame(self, space_id: str, graph_id: str, frame_uri: str, 
                                  include_frame_graph: bool = True) -> Dict[str, Any]:
        """
        Get individual frame with optional complete frame graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI
            include_frame_graph: Whether to include complete frame graph
            
        Returns:
            Dict containing frame data and metadata
        """
        try:
            self.logger.info(f"Getting individual frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            # Build and execute frame query
            frame_query = self.query_builder.build_frame_graph_query(
                graph_id, frame_uri, include_frame_graph
            )
            
            results = await self.backend.execute_sparql_query(space_id, frame_query)
            subject_uris = self.utils.extract_subject_uris_from_results(results)
            
            self.logger.info(f"🔍 Frame {frame_uri}: get_individual_frame returned {len(subject_uris)} subject URIs")
            for i, uri in enumerate(subject_uris[:10]):
                self.logger.info(f"🔍   Subject {i+1}: {uri}")
            if len(subject_uris) > 10:
                self.logger.info(f"🔍   ... and {len(subject_uris) - 10} more subjects")
            
            # Diagnostic: Check what hasFrameGraphURI values exist near this frame
            if len(subject_uris) <= 1:
                diagnostic_query = f"""
                {self.query_builder.utils.build_prefixes()}
                SELECT ?subject ?frameGraphURI WHERE {{
                    {self.query_builder.utils.build_graph_clause(graph_id)} {{
                        ?subject ?p {self.query_builder.utils.build_uri_reference(frame_uri)} .
                        OPTIONAL {{ ?subject haley:hasFrameGraphURI ?frameGraphURI }}
                    }}
                }}
                LIMIT 10
                """
                diagnostic_results = await self.backend.execute_sparql_query(space_id, diagnostic_query)
                self.logger.error(f"🔍 DIAGNOSTIC: Objects connected to frame {frame_uri}:")
                if diagnostic_results and 'results' in diagnostic_results and 'bindings' in diagnostic_results['results']:
                    for binding in diagnostic_results['results']['bindings'][:5]:
                        subj = binding.get('subject', {}).get('value', 'N/A')
                        fgu = binding.get('frameGraphURI', {}).get('value', 'NONE')
                        self.logger.error(f"🔍   {subj} -> hasFrameGraphURI: {fgu}")
            
            return {
                'frame_uri': frame_uri,
                'subject_uris': subject_uris,
                'include_frame_graph': include_frame_graph,
                'frame_query': frame_query,
                'object_count': len(subject_uris)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting individual frame: {e}")
            raise
    
    async def delete_frame(self, space_id: str, graph_id: str, frame_uri: str) -> Dict[str, Any]:
        """
        Delete frame and its complete graph using SPARQL.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to delete
            
        Returns:
            Dict containing deletion results and metadata
        """
        try:
            self.logger.info(f"Deleting frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            # Get count of objects that will be deleted
            count_query = self.query_builder.build_frame_deletion_count_query(graph_id, frame_uri)
            count_results = await self.backend.execute_sparql_query(space_id, count_query)
            deleted_count = self.utils.extract_count_from_results(count_results)
            
            # Build and execute deletion query
            delete_query = self.query_builder.build_frame_deletion_query(graph_id, frame_uri)
            await self.backend.execute_sparql_update(delete_query)
            
            self.logger.info(f"Successfully deleted frame {frame_uri} and {deleted_count} related objects")
            
            return {
                'frame_uri': frame_uri,
                'deleted_count': deleted_count,
                'count_query': count_query,
                'delete_query': delete_query,
                'success': True
            }
            
        except Exception as e:
            self.logger.error(f"Error deleting frame: {e}")
            raise
    
    async def validate_entity_frame_relationships(self, space_id: str, graph_id: str, 
                                                entity_uri: str) -> bool:
        """
        Validate entity-frame relationships using SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to validate
            
        Returns:
            bool: True if relationships are valid, False otherwise
        """
        try:
            self.logger.debug(f"Validating entity-frame relationships for {entity_uri}")
            
            # Query for frames associated with this entity using Edge relationships
            frame_query = f"""
            {self.utils.build_prefixes()}
            
            SELECT DISTINCT ?frame WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    ?edge a haley:Edge_hasEntityKGFrame ;
                          vital:hasEdgeSource {self.utils.build_uri_reference(entity_uri)} ;
                          vital:hasEdgeDestination ?frame .
                    ?frame a haley:KGFrame .
                }}
            }}
            """
            
            frame_results = await self.backend.execute_sparql_select(frame_query)
            
            if not frame_results or not frame_results.get('results', {}).get('bindings'):
                return True  # No frames to validate
            
            # Validate each complete atomic frame graph
            for binding in frame_results['results']['bindings']:
                frame_uri = binding.get('frame', {}).get('value')
                if frame_uri:
                    # Validate the complete atomic frame graph using frameGraphURI
                    atomic_frame_validation = f"""
                    {self.utils.build_prefixes()}
                    
                    ASK {{
                        {self.utils.build_graph_clause(graph_id)} {{
                            # Validate frame exists with proper grouping URIs
                            {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame ;
                                         haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} ;
                                         haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                            
                            # Validate ALL objects in this atomic frame have consistent grouping URIs
                            FILTER NOT EXISTS {{
                                ?obj haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                                FILTER NOT EXISTS {{ ?obj haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} }}
                            }}
                        }}
                    }}
                    """
                    
                    validation_result = await self.backend.execute_sparql_ask(atomic_frame_validation)
                    if not validation_result:
                        self.logger.warning(f"Invalid atomic frame graph consistency: {frame_uri} -> {entity_uri}")
                        return False
                    
                    # Ensure atomic frame completeness - count all objects in frame graph
                    completeness_query = f"""
                    {self.utils.build_prefixes()}
                    
                    SELECT (COUNT(?obj) as ?count) WHERE {{
                        {self.utils.build_graph_clause(graph_id)} {{
                            ?obj haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                        }}
                    }}
                    """
                    
                    count_result = await self.backend.execute_sparql_select(completeness_query)
                    if count_result and count_result.get('results', {}).get('bindings'):
                        count_binding = count_result['results']['bindings'][0]
                        object_count = int(count_binding.get('count', {}).get('value', 0))
                        self.logger.debug(f"Atomic frame graph {frame_uri} contains {object_count} objects")
                        
                        if object_count == 0:
                            self.logger.warning(f"Empty atomic frame graph detected: {frame_uri}")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating entity-frame relationships: {e}")
            return False
    
    async def get_specific_frame_graphs(self, space_id: str, graph_id: str, entity_uri: str, 
                                       frame_uris: List[str]) -> Dict[str, Any]:
        """
        Retrieve specific frame graphs using two-phase SPARQL architecture.
        
        Phase 1: Validate frame ownership by entity (security)
        Phase 2: Retrieve complete frame graphs using frameGraphURI grouping
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI
            frame_uris: List of frame URIs to retrieve
            
        Returns:
            Dict containing frame graphs and validation results
        """
        try:
            self.logger.info(f"🔍 Phase 1: Validating ownership of {len(frame_uris)} frames for entity {entity_uri}")
            
            # Phase 1: Frame ownership validation query
            # Check that frames belong to entity via kGGraphURI (grouping property)
            # This works for both top-level frames and child frames
            frame_uris_filter = ", ".join([self.utils.build_uri_reference(uri) for uri in frame_uris])
            ownership_query = f"""
            {self.utils.build_prefixes()}
            
            SELECT ?frame_uri WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    ?frame_uri a haley:KGFrame ;
                               haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} .
                    FILTER(?frame_uri IN ({frame_uris_filter}))
                }}
            }}
            """
            
            ownership_results = await self.backend.execute_sparql_query(space_id, ownership_query)
            validated_frame_uris = self.utils.extract_uris_from_results(ownership_results, "frame_uri")
            
            self.logger.info(f"🔍 Phase 1 Results: {len(validated_frame_uris)} of {len(frame_uris)} frames validated")
            
            # Security check: Track frames that don't belong to the entity
            missing_frames = set(frame_uris) - set(validated_frame_uris)
            if missing_frames:
                self.logger.warning(f"🔒 Cross-entity frame access attempted: {list(missing_frames)} do not belong to entity {entity_uri}")
            
            self.logger.info(f"🔍 Phase 2: Retrieving complete frame graphs for {len(validated_frame_uris)} frames")
            
            # Phase 2: Retrieve complete frame graphs
            frame_graphs = {}
            
            # Process all requested frames (both valid and invalid)
            for frame_uri in frame_uris:
                if frame_uri in validated_frame_uris:
                    # Valid frame - retrieve its graph using processor method
                    frame_data = await self.get_individual_frame(space_id, graph_id, frame_uri, include_frame_graph=True)
                    
                    self.logger.info(f"🔍 Frame {frame_uri}: get_individual_frame returned {len(frame_data.get('subject_uris', [])) if frame_data else 0} subject URIs")
                    
                    if frame_data and frame_data.get('subject_uris'):
                        # Get triples for all subject URIs (frame, slots, and edges)
                        subject_uris = frame_data.get('subject_uris', [])
                        subject_uris_filter = ", ".join([self.utils.build_uri_reference(uri) for uri in subject_uris])
                        
                        frame_graph_query = f"""
                        {self.utils.build_prefixes()}
                        
                        SELECT ?subject ?predicate ?object WHERE {{
                            {self.utils.build_graph_clause(graph_id)} {{
                                ?subject ?predicate ?object .
                                FILTER(?subject IN ({subject_uris_filter}))
                                FILTER(?predicate != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                                       ?predicate != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                                       ?predicate != <http://vital.ai/vitalgraph/direct#hasSlot>)
                            }}
                        }}
                        """
                        
                        graph_results = await self.backend.execute_sparql_query(space_id, frame_graph_query)
                        
                        if graph_results:
                            # Extract triples for VitalSigns processing
                            self.logger.info(f"🔍 Frame {frame_uri}: graph_results type={type(graph_results)}, has 'results' key={isinstance(graph_results, dict) and 'results' in graph_results}")
                            if isinstance(graph_results, dict) and 'results' in graph_results:
                                self.logger.info(f"🔍 Frame {frame_uri}: results has 'bindings' key={'bindings' in graph_results.get('results', {})}")
                            triples = self.utils.extract_triples_from_sparql_results(graph_results)
                            frame_graphs[frame_uri] = {
                                'triples': triples,
                                'object_count': len(frame_data.get('subject_uris', []))
                            }
                            self.logger.info(f"🔍 Frame {frame_uri}: Retrieved {len(triples)} triples")
                            for i, (s, p, o) in enumerate(triples[:15]):
                                self.logger.info(f"🔍   Triple {i+1}: {s} | {p} | {o}")
                            if len(triples) > 15:
                                self.logger.info(f"🔍   ... and {len(triples) - 15} more triples")
                        else:
                            frame_graphs[frame_uri] = {'triples': [], 'object_count': 0}
                            self.logger.info(f"🔍 Frame {frame_uri}: No graph data found")
                    else:
                        frame_graphs[frame_uri] = {'triples': [], 'object_count': 0}
                        self.logger.info(f"🔍 Frame {frame_uri}: Empty result")
                else:
                    # Invalid frame - doesn't belong to entity
                    frame_graphs[frame_uri] = {
                        "error": "frame_not_owned_by_entity",
                        "message": f"Frame {frame_uri} does not belong to entity {entity_uri}",
                        "frame_uri": frame_uri,
                        "entity_uri": entity_uri
                    }
                    self.logger.info(f"🔒 Frame {frame_uri}: Access denied (not owned by entity)")
            
            # Prepare response with error information
            response = {
                "frame_graphs": frame_graphs,
                "entity_uri": entity_uri,
                "requested_frames": len(frame_uris),
                "retrieved_frames": len([fg for fg in frame_graphs.values() if fg and "error" not in fg]),
                "validation_results": {
                    "valid_frames": len(validated_frame_uris),
                    "invalid_frames": len(missing_frames),
                    "invalid_frame_uris": list(missing_frames) if missing_frames else []
                }
            }
            
            return response
            
        except Exception as e:
            self.logger.error(f"Error in specific frame graph retrieval: {e}")
            raise
    
    async def get_all_triples_for_subjects(self, space_id: str, graph_id: str, subject_uris: List[str]) -> List[Dict[str, str]]:
        """
        Get all triples for the given subject URIs using batched SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            subject_uris: List of subject URIs to get triples for
            
        Returns:
            List[Dict[str, str]]: List of triple dictionaries with 'subject', 'predicate', 'object' keys
        """
        try:
            if not subject_uris:
                return []
            
            # Build SPARQL query to get all triples for subjects
            # Use batching if there are many subjects
            batch_size = 50  # Reasonable batch size for SPARQL IN clause
            all_triples = []
            
            for i in range(0, len(subject_uris), batch_size):
                batch_uris = subject_uris[i:i + batch_size]
                uri_list = ", ".join([self.utils.build_uri_reference(uri) for uri in batch_uris])
                
                query = f"""
                {self.utils.build_prefixes()}
                
                SELECT ?s ?p ?o WHERE {{
                    {self.utils.build_graph_clause(graph_id)} {{
                        ?s ?p ?o .
                        FILTER(?s IN ({uri_list}))
                        FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                    }}
                }}
                ORDER BY ?s ?p ?o
                """
                
                result = await self.backend.execute_sparql_query(space_id, query)
                
                # Handle nested results structure
                bindings = None
                if isinstance(result, dict):
                    if result.get("results", {}).get("bindings"):
                        bindings = result["results"]["bindings"]
                    elif result.get("bindings"):
                        bindings = result["bindings"]
                
                if bindings:
                    for binding in bindings:
                        subject = binding.get("s", {}).get("value")
                        predicate = binding.get("p", {}).get("value") 
                        obj = binding.get("o", {}).get("value")
                        
                        if subject and predicate and obj:
                            all_triples.append({
                                "subject": subject,
                                "predicate": predicate,
                                "object": obj
                            })
            
            self.logger.info(f"Retrieved {len(all_triples)} triples for {len(subject_uris)} subjects")
            return all_triples
            
        except Exception as e:
            self.logger.error(f"Error getting triples for subjects: {e}")
            raise
    
    async def get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                               page_size: int = 100, offset: int = 0, search: Optional[str] = None,
                               parent_frame_uri: Optional[str] = None) -> Dict[str, Any]:
        """
        Get frames associated with an entity using SPARQL queries with pagination and search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI
            page_size: Number of results per page
            offset: Offset for pagination
            search: Optional search term
            parent_frame_uri: Optional parent frame URI for hierarchical filtering
                - If None: Returns top-level frames (children of entity via Edge_hasEntityKGFrame)
                - If provided: Returns only frames that are children of the specified parent frame
            
        Returns:
            Dict containing frame_uris and total_count
        """
        try:
            # Build search filter
            search_filter = ""
            if search:
                escaped_search = self.utils.escape_sparql_string(search)
                search_filter = f"""
                OPTIONAL {{ ?frame haley:name ?name }}
                FILTER(CONTAINS(LCASE(STR(?name)), LCASE("{escaped_search}")))
                """
            
            # Build pagination
            pagination = self.utils.build_pagination_clause(page_size, offset)
            
            # Build parent filter based on parent_frame_uri
            if parent_frame_uri:
                # Query for child frames of a specific parent frame
                self.logger.error(f"🔍 DEBUG: Querying for child frames of parent: {parent_frame_uri}")
                parent_filter = f"""
                    # Frame-to-frame connections (child frames of parent)
                    ?edge a haley:Edge_hasKGFrame ;
                          vital:hasEdgeSource {self.utils.build_uri_reference(parent_frame_uri)} ;
                          vital:hasEdgeDestination ?frame .
                """
            else:
                # Query for top-level frames (direct entity-to-frame connections)
                self.logger.error(f"🔍 DEBUG: Querying for top-level frames of entity: {entity_uri}")
                parent_filter = f"""
                    # Direct entity-to-frame connections only
                    ?edge a haley:Edge_hasEntityKGFrame ;
                          vital:hasEdgeSource {self.utils.build_uri_reference(entity_uri)} ;
                          vital:hasEdgeDestination ?frame .
                """
            
            # Query to get frame URIs
            frames_query = f"""
            {self.utils.build_prefixes()}
            
            SELECT DISTINCT ?frame WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    {parent_filter}
                    ?frame a haley:KGFrame .
                    {search_filter}
                }}
            }}
            ORDER BY ?frame
            {pagination}
            """
            
            # Execute query to get frame URIs
            self.logger.error(f"🔍 DEBUG: Executing frames query...")
            results = await self.backend.execute_sparql_query(space_id, frames_query)
            frame_uris = self.utils.extract_uris_from_results(results, "frame")
            self.logger.error(f"🔍 DEBUG: Found {len(frame_uris)} frame URIs: {frame_uris[:5]}")
            
            # Get total count (without pagination)
            count_query = f"""
            {self.utils.build_prefixes()}
            
            SELECT (COUNT(DISTINCT ?frame) as ?count) WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    {parent_filter}
                    ?frame a haley:KGFrame .
                }}
            }}
            """
            
            count_results = await self.backend.execute_sparql_query(space_id, count_query)
            total_count = self.utils.extract_count_from_results(count_results)
            
            return {
                'frame_uris': frame_uris,
                'total_count': total_count
            }
            
        except Exception as e:
            self.logger.error(f"Error getting entity frames: {e}")
            raise
    
    async def validate_frame_parent_relationship(self, space_id: str, graph_id: str, 
                                                 parent_frame_uri: str, child_frame_uris: List[str]) -> Dict[str, bool]:
        """
        Validate that specified frames are children of a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            child_frame_uris: List of child frame URIs to validate
            
        Returns:
            Dict mapping frame URIs to validation status (True if valid child, False otherwise)
        """
        try:
            if not child_frame_uris:
                return {}
            
            # Build VALUES clause for child frames
            values_clause = " ".join([self.utils.build_uri_reference(uri) for uri in child_frame_uris])
            
            # Query to check which frames are children of the parent
            validation_query = f"""
            {self.utils.build_prefixes()}
            
            SELECT ?frame WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    VALUES ?frame {{ {values_clause} }}
                    ?edge a haley:Edge_hasKGFrame ;
                          vital:hasEdgeSource {self.utils.build_uri_reference(parent_frame_uri)} ;
                          vital:hasEdgeDestination ?frame .
                }}
            }}
            """
            
            results = await self.backend.execute_sparql_query(space_id, validation_query)
            valid_frame_uris = self.utils.extract_uris_from_results(results, "frame")
            
            # Create validation map
            validation_map = {uri: (uri in valid_frame_uris) for uri in child_frame_uris}
            
            return validation_map
            
        except Exception as e:
            self.logger.error(f"Error validating frame parent relationships: {e}")
            raise