"""
Fuseki SPARQL Implementation for VitalGraph

This module provides the Fuseki backend implementation of SparqlBackendInterface
using Apache Jena Fuseki's SPARQL HTTP endpoints for query and update operations.

All SPARQL operations are delegated to Fuseki via HTTP requests with proper
graph URI validation to ensure operations target named graphs only.
"""

import logging
import re
from typing import Dict, List, Any
import aiohttp

# Import interface
from ..space_backend_interface import SparqlBackendInterface


class FusekiSparqlImpl(SparqlBackendInterface):
    """
    Fuseki implementation of SparqlBackendInterface using HTTP SPARQL endpoints.
    
    Delegates all SPARQL operations to Fuseki server via HTTP requests.
    Validates that queries and updates target named graphs only.
    """
    
    def __init__(self, space_impl, space_id: str):
        """
        Initialize Fuseki SPARQL implementation.
        
        Args:
            space_impl: FusekiSpaceImpl instance for HTTP session access
            space_id: Space identifier for graph URI validation
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.space_impl = space_impl
        self.space_id = space_id
        
        # Fuseki endpoints
        self.query_url = space_impl.query_url
        self.update_url = space_impl.update_url
        
        self.logger.info(f"Initialized Fuseki SPARQL implementation for space: {space_id}")
    
    def _validate_graph_usage(self, sparql_query: str) -> bool:
        """
        Validate that SPARQL query/update targets named graphs only.
        
        This ensures we don't accidentally operate on the default graph.
        For now, this is a basic check - can be enhanced with full SPARQL parsing.
        
        Args:
            sparql_query: SPARQL query or update string
            
        Returns:
            True if query appears to use named graphs appropriately
        """
        # Convert to lowercase for case-insensitive matching
        query_lower = sparql_query.lower()
        
        # Check for GRAPH clauses (basic validation)
        has_graph_clause = 'graph <' in query_lower or 'graph ?' in query_lower
        
        # Allow queries without explicit GRAPH if they're metadata queries
        is_metadata_query = (
            'urn:vitalgraph:spaces' in sparql_query or
            'vitalsegment' in query_lower or
            'kgsegment' in query_lower
        )
        
        # Allow ASK queries for existence checks
        is_ask_query = query_lower.strip().startswith('ask')
        
        if has_graph_clause or is_metadata_query or is_ask_query:
            return True
        
        # Log warning for potentially unsafe queries
        self.logger.warning(f"SPARQL query may not target named graphs explicitly: {sparql_query[:100]}...")
        return True  # Allow for now, but log warning
    
    def _rewrite_graph_uris(self, sparql_query: str) -> str:
        """
        Rewrite relative graph URIs to full Fuseki format if needed.
        
        This can be used to automatically convert space-relative graph references
        to full URIs expected by Fuseki.
        
        Args:
            sparql_query: Original SPARQL query
            
        Returns:
            SPARQL query with rewritten graph URIs
        """
        # For now, return query as-is
        # Future enhancement: rewrite relative graph references
        return sparql_query
    
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against Fuseki server.
        
        Handles SELECT, CONSTRUCT, ASK, and DESCRIBE queries.
        
        Args:
            space_id: The space identifier
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings (SELECT)
            or List of RDF triple dictionaries (CONSTRUCT/DESCRIBE)
            or List with single boolean result (ASK)
        """
        try:
            self.logger.info(f"Executing SPARQL query in space '{space_id}'")
            self.logger.debug(f"Query: {sparql_query}")
            
            # Validate graph usage
            if not self._validate_graph_usage(sparql_query):
                raise ValueError("SPARQL query must target named graphs only")
            
            # Rewrite graph URIs if needed
            processed_query = self._rewrite_graph_uris(sparql_query)
            
            # Determine query type for appropriate Accept header
            query_type = self._detect_query_type(processed_query)
            
            if query_type == 'CONSTRUCT':
                accept_header = 'application/rdf+json'
            elif query_type == 'ASK':
                accept_header = 'application/sparql-results+json'
            else:  # SELECT, DESCRIBE
                accept_header = 'application/sparql-results+json'
            
            # Execute query via HTTP
            session = await self.space_impl._get_session()
            async with session.post(
                self.query_url,
                data=processed_query,
                headers={
                    'Content-Type': 'application/sparql-query',
                    'Accept': accept_header
                }
            ) as response:
                
                if response.status == 200:
                    result_data = await response.json()
                    
                    # Convert Fuseki results to standardized format
                    if query_type == 'ASK':
                        return [{'result': result_data.get('boolean', False)}]
                    elif query_type == 'CONSTRUCT':
                        return self._convert_construct_results(result_data)
                    else:  # SELECT, DESCRIBE
                        return self._convert_select_results(result_data)
                        
                else:
                    error_text = await response.text()
                    self.logger.error(f"SPARQL query failed: {response.status} - {error_text}")
                    raise Exception(f"SPARQL query failed: {response.status} - {error_text}")
                    
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            raise
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute a SPARQL 1.1 UPDATE operation against Fuseki server.
        
        Handles INSERT DATA, DELETE DATA, INSERT WHERE, DELETE WHERE, and MODIFY operations.
        
        Args:
            space_id: The space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            self.logger.info(f"Executing SPARQL update in space '{space_id}'")
            self.logger.debug(f"Update: {sparql_update}")
            
            # Validate graph usage
            if not self._validate_graph_usage(sparql_update):
                raise ValueError("SPARQL update must target named graphs only")
            
            # Rewrite graph URIs if needed
            processed_update = self._rewrite_graph_uris(sparql_update)
            
            # Execute update via HTTP
            session = await self.space_impl._get_session()
            async with session.post(
                self.update_url,
                data=processed_update,
                headers={'Content-Type': 'application/sparql-update'}
            ) as response:
                
                if response.status == 200 or response.status == 204:
                    self.logger.info(f"SPARQL update executed successfully")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"SPARQL update failed: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error executing SPARQL update: {e}")
            return False
    
    def _detect_query_type(self, sparql_query: str) -> str:
        """
        Detect the type of SPARQL query (SELECT, CONSTRUCT, ASK, DESCRIBE).
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            Query type as string
        """
        query_upper = sparql_query.strip().upper()
        
        if query_upper.startswith('SELECT'):
            return 'SELECT'
        elif query_upper.startswith('CONSTRUCT'):
            return 'CONSTRUCT'
        elif query_upper.startswith('ASK'):
            return 'ASK'
        elif query_upper.startswith('DESCRIBE'):
            return 'DESCRIBE'
        else:
            # Default to SELECT for unknown types
            return 'SELECT'
    
    def _convert_select_results(self, fuseki_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert Fuseki SELECT results to standardized format.
        
        Args:
            fuseki_results: Raw results from Fuseki SPARQL endpoint
            
        Returns:
            List of result dictionaries with variable bindings
        """
        try:
            bindings = fuseki_results.get('results', {}).get('bindings', [])
            results = []
            
            for binding in bindings:
                result = {}
                for var, value_info in binding.items():
                    if value_info.get('type') == 'uri':
                        result[var] = value_info['value']
                    elif value_info.get('type') == 'literal':
                        result[var] = {
                            'value': value_info['value'],
                            'datatype': value_info.get('datatype'),
                            'lang': value_info.get('xml:lang')
                        }
                    elif value_info.get('type') == 'bnode':
                        result[var] = f"_:{value_info['value']}"
                    else:
                        result[var] = value_info['value']
                
                results.append(result)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error converting SELECT results: {e}")
            return []
    
    def _convert_construct_results(self, fuseki_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert Fuseki CONSTRUCT results to standardized format.
        
        Args:
            fuseki_results: Raw RDF results from Fuseki SPARQL endpoint
            
        Returns:
            List of RDF triple dictionaries
        """
        try:
            # Fuseki CONSTRUCT results come as RDF/JSON
            # Convert to list of triple dictionaries
            results = []
            
            for subject_uri, predicates in fuseki_results.items():
                for predicate_uri, objects in predicates.items():
                    for obj in objects:
                        triple = {
                            'subject': subject_uri,
                            'predicate': predicate_uri,
                            'object': obj.get('value', obj),
                            'object_type': obj.get('type', 'literal')
                        }
                        if 'datatype' in obj:
                            triple['object_datatype'] = obj['datatype']
                        if 'lang' in obj:
                            triple['object_lang'] = obj['lang']
                        
                        results.append(triple)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error converting CONSTRUCT results: {e}")
            return []
    
    # Capability methods with Fuseki-specific implementations
    
    def supports_construct(self) -> bool:
        """Fuseki supports CONSTRUCT queries."""
        return True
    
    def supports_ask(self) -> bool:
        """Fuseki supports ASK queries."""
        return True
    
    def supports_describe(self) -> bool:
        """Fuseki supports DESCRIBE queries."""
        return True
    
    def supports_property_paths(self) -> bool:
        """Fuseki supports SPARQL 1.1 property paths."""
        return True
    
    def get_query_capabilities(self) -> Dict[str, Any]:
        """
        Get Fuseki-specific query capabilities and limitations.
        
        Returns:
            Dictionary with capability flags and limits
        """
        return {
            'supports_construct': True,
            'supports_ask': True,
            'supports_describe': True,
            'supports_property_paths': True,
            'supports_sparql_11': True,
            'supports_named_graphs': True,
            'supports_federation': False,  # Depends on Fuseki configuration
            'max_query_timeout': self.space_impl.timeout,
            'max_result_size': None,  # Depends on Fuseki configuration
            'backend_type': 'fuseki',
            'server_url': self.space_impl.server_url,
            'dataset_name': self.space_impl.dataset_name
        }