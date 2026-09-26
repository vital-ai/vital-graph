"""
Fuseki Query Utilities for Two-Phase Object Queries

This module provides common utilities for Fuseki SPARQL queries used across all object endpoints.
Implements the two-phase query pattern:
1. Phase 1: Find subject URIs matching criteria using SPARQL SELECT
2. Phase 2: Retrieve complete objects for URIs using SPARQL CONSTRUCT

Used by KGTypes, KGEntities, KGFrames, and other object endpoints.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple


class FusekiQueryUtils:
    """Common utilities for Fuseki SPARQL queries used across all object endpoints."""
    
    @staticmethod
    async def find_subject_uris_by_criteria(fuseki_manager, space_id: str, graph_id: str, 
                                          filters: Optional[Dict[str, Any]] = None, 
                                          page_size: int = 100, offset: int = 0) -> Tuple[List[str], int]:
        """
        Phase 1: Execute SPARQL SELECT to find subject URIs matching criteria.
        
        Args:
            fuseki_manager: FusekiDatasetManager instance
            space_id: Space identifier
            graph_id: Graph identifier  
            filters: Dict with vitaltype_filter, search_text, subject_uri, etc.
            page_size: Results per page
            offset: Pagination offset
            
        Returns:
            Tuple of (subject_uris: List[str], total_count: int)
        """
        logger = logging.getLogger(f"{__name__}.FusekiQueryUtils")
        
        # Build proper graph URI using the existing utility function
        graph_uri = FusekiQueryUtils.build_graph_uri(space_id, graph_id)
        
        # Build filter conditions
        filter_conditions = []
        if filters:
            if filters.get('vitaltype_filter'):
                filter_conditions.append(f"?subject a <{filters['vitaltype_filter']}> .")
            if filters.get('search_text'):
                # Search across all string properties
                search_text = filters['search_text'].replace('"', '\\"')  # Escape quotes
                filter_conditions.append(f"""
                    ?subject ?searchProp ?searchValue .
                    FILTER(CONTAINS(LCASE(STR(?searchValue)), LCASE("{search_text}")))
                """)
            if filters.get('subject_uri'):
                filter_conditions.append(f"?subject = <{filters['subject_uri']}> .")
        
        # Default filter if no specific filters provided
        filter_clause = "\n            ".join(filter_conditions) if filter_conditions else "?subject a ?type ."
        
        # Build SPARQL query with pagination (total count will be calculated separately)
        sparql_query = f"""
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{graph_uri}> {{
                {filter_clause}
            }}
        }}
        ORDER BY ?subject
        LIMIT {page_size} OFFSET {offset}
        """
        
        try:
            logger.info(f"Executing Phase 1 query for {page_size} subjects at offset {offset}")
            logger.info(f"SPARQL Query (full): {repr(sparql_query)}")
            logger.info(f"Query parameters - page_size: {page_size}, offset: {offset}")
            bindings = await fuseki_manager.query_dataset(space_id, sparql_query)
            
            subject_uris = [binding['subject']['value'] for binding in bindings]
            
            # For now, use the returned count as an approximation
            # TODO: Implement separate count query if exact total is needed
            total_count = len(subject_uris)
            
            logger.info(f"Phase 1: Found {len(subject_uris)} subjects (total: {total_count})")
            return subject_uris, total_count
            
        except Exception as e:
            logger.error(f"Error in Phase 1 subject URI discovery: {e}")
            return [], 0
    
    @staticmethod
    async def get_complete_objects_by_uris(fuseki_manager, space_id: str, subject_uris: List[str], 
                                         graph_id: str) -> List[Tuple[str, str, str]]:
        """
        Phase 2: Execute SPARQL CONSTRUCT to get all triples for specific subject URIs.
        
        Args:
            fuseki_manager: FusekiDatasetManager instance
            space_id: Space identifier
            subject_uris: List of subject URIs to retrieve
            graph_id: Graph identifier
            
        Returns:
            List of (subject, predicate, object) triples
        """
        logger = logging.getLogger(f"{__name__}.FusekiQueryUtils")
        
        if not subject_uris:
            logger.debug("No subject URIs provided, returning empty list")
            return []
            
        # Build proper graph URI using the existing utility function
        graph_uri = FusekiQueryUtils.build_graph_uri(space_id, graph_id)
        
        # Format URIs for VALUES clause
        uri_values = " ".join([f"<{uri}>" for uri in subject_uris])
        
        # Build SPARQL CONSTRUCT query
        sparql_query = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{
            GRAPH <{graph_uri}> {{
                ?s ?p ?o .
                VALUES ?s {{ {uri_values} }}
                FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                       ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                       ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
            }}
        }}
        """
        
        try:
            logger.debug(f"Executing Phase 2 query for {len(subject_uris)} subjects")
            triples = await fuseki_manager.construct_dataset(space_id, sparql_query)
            
            logger.debug(f"Phase 2: Retrieved {len(triples)} triples for {len(subject_uris)} subjects")
            return triples
            
        except Exception as e:
            logger.error(f"Error in Phase 2 object retrieval: {e}")
            return []
    
    @staticmethod
    async def get_objects_batch_processing(fuseki_manager, space_id: str, subject_uris: List[str], 
                                         graph_id: str, batch_size: int = 100) -> List[Tuple[str, str, str]]:
        """
        Process large URI lists in batches to avoid SPARQL query size limits.
        
        Args:
            fuseki_manager: FusekiDatasetManager instance
            space_id: Space identifier
            subject_uris: List of all subject URIs to retrieve
            graph_id: Graph identifier
            batch_size: Number of URIs per batch (default: 100)
            
        Returns:
            List of all triples for the subject URIs
        """
        logger = logging.getLogger(f"{__name__}.FusekiQueryUtils")
        
        if not subject_uris:
            return []
        
        all_triples = []
        total_batches = (len(subject_uris) + batch_size - 1) // batch_size
        
        logger.debug(f"Processing {len(subject_uris)} URIs in {total_batches} batches of {batch_size}")
        
        for i in range(0, len(subject_uris), batch_size):
            batch_num = (i // batch_size) + 1
            batch_uris = subject_uris[i:i + batch_size]
            
            logger.debug(f"Processing batch {batch_num}/{total_batches} with {len(batch_uris)} URIs")
            
            batch_triples = await FusekiQueryUtils.get_complete_objects_by_uris(
                fuseki_manager, space_id, batch_uris, graph_id
            )
            all_triples.extend(batch_triples)
        
        logger.debug(f"Batch processing complete: {len(all_triples)} total triples retrieved")
        return all_triples
    
    @staticmethod
    async def check_uris_exist(fuseki_manager, space_id: str, uris: List[str]) -> List[str]:
        """
        Check which URIs exist by querying for any triple with those subjects.
        
        Args:
            fuseki_manager: FusekiDatasetManager instance
            space_id: Space identifier
            uris: List of URIs to check
            
        Returns:
            List of URIs that exist
        """
        logger = logging.getLogger(f"{__name__}.FusekiQueryUtils")
        
        if not uris:
            return []
        
        existing_uris = []
        
        # Use batch ASK queries to check existence efficiently
        for uri in uris:
            sparql_query = f"""
            ASK {{
                GRAPH ?g {{
                    <{uri}> ?p ?o .
                }}
            }}
            """
            
            try:
                exists = await fuseki_manager.ask_dataset(space_id, sparql_query)
                if exists:
                    existing_uris.append(uri)
            except Exception as e:
                logger.warning(f"Error checking existence of URI {uri}: {e}")
        
        logger.info(f"URI existence check: {len(existing_uris)}/{len(uris)} URIs exist")
        return existing_uris
    
    @staticmethod
    def build_graph_uri(space_id: str, graph_id: str) -> str:
        """
        Build graph URI from space and graph identifiers.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (must be proper URN)
            
        Returns:
            Complete graph URI
        """
        return graph_id
    
    @staticmethod
    def format_uri_values(uris: List[str]) -> str:
        """
        Format list of URIs for SPARQL VALUES clause.
        
        Args:
            uris: List of URI strings
            
        Returns:
            Formatted string for VALUES clause
        """
        return " ".join([f"<{uri}>" for uri in uris])
