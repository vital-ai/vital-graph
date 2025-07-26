"""
PostgreSQL SPARQL Updates Implementation for VitalGraph

This module handles SPARQL UPDATE operations including INSERT DATA,
DELETE DATA, INSERT/DELETE with WHERE patterns, and MODIFY operations.
Supports both ground triples and pattern-based updates.
"""

import logging
from typing import List, Dict, Tuple, Set, Optional, Any, Union
from rdflib import Variable, URIRef, Literal, BNode, Graph, ConjunctiveGraph
from rdflib.plugins.sparql.parser import parseUpdate
from rdflib.plugins.sparql.algebra import translateUpdate
import re

# Import shared utilities
from .postgresql_sparql_utils import GraphConstants, TableConfig, SparqlUtils


class PostgreSQLSparqlUpdates:
    """Handles SPARQL UPDATE operations for PostgreSQL backend."""
    
    def __init__(self, space_impl, logger: Optional[logging.Logger] = None):
        """Initialize the SPARQL updates handler.
        
        Args:
            space_impl: PostgreSQL space implementation instance
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.space_impl = space_impl
        self.logger = logger or logging.getLogger(__name__)

    async def execute_insert_data(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute INSERT DATA operation with ground triples.
        
        Args:
            space_id: The space identifier
            sparql_update: INSERT DATA SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing INSERT DATA operation")
        
        try:
            # Initialize graph cache if needed
            await self._initialize_graph_cache_if_needed(space_id)
            # Parse INSERT DATA query to extract triples
            triples = self._parse_insert_data_triples(sparql_update)
            self.logger.debug(f"Parsed {len(triples)} triples for insertion")
            
            if not triples:
                self.logger.warning("No triples found in INSERT DATA operation")
                return True
            
            # Convert triples to quads and collect unique graph URIs
            quads = []
            unique_graphs = set()
            
            for subject, predicate, obj, graph in triples:
                # Use global graph if no graph specified
                # In this system, INSERT DATA without GRAPH clause targets the global graph
                # since that's where most queries look for data
                if graph is None:
                    graph = URIRef(GraphConstants.GLOBAL_GRAPH_URI)
                
                quads.append((subject, predicate, obj, graph))
                unique_graphs.add(str(graph))
            
            # Efficiently register only unique graphs (batch optimization)
            await self._ensure_graphs_registered_batch(space_id, unique_graphs)
            
            # Insert quads in batch
            await self.space_impl.add_rdf_quads_batch(space_id, quads)
            
            self.logger.info(f"Successfully inserted {len(quads)} quads")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in INSERT DATA operation: {e}")
            raise

    async def execute_delete_data(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute DELETE DATA operation with ground triples.
        
        Args:
            space_id: The space identifier
            sparql_update: DELETE DATA SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing DELETE DATA operation")
        
        try:
            # Parse DELETE DATA query to extract triples
            triples = self._parse_delete_data_triples(sparql_update)
            self.logger.debug(f"Parsed {len(triples)} triples for deletion")
            
            if not triples:
                self.logger.warning("No triples found in DELETE DATA operation")
                return True
            
            # Convert triples to quads and delete
            quads = []
            for subject, predicate, obj, graph in triples:
                # Use global graph if no graph specified
                # In this system, DELETE DATA without GRAPH clause targets the global graph
                # since that's where most queries look for data
                if graph is None:
                    graph = URIRef(GraphConstants.GLOBAL_GRAPH_URI)
                quads.append((subject, predicate, obj, graph))
            
            # Delete quads in batch
            await self.space_impl.remove_rdf_quads_batch(space_id, quads)
            
            self.logger.info(f"Successfully deleted {len(quads)} quads")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in DELETE DATA operation: {e}")
            raise

    async def execute_insert_delete_pattern(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute INSERT/DELETE operations with WHERE patterns (Phase 2).
        
        This handles:
        - INSERT { ... } WHERE { ... }
        - DELETE { ... } WHERE { ... }
        - DELETE { ... } INSERT { ... } WHERE { ... }
        
        Args:
            space_id: The space identifier
            sparql_update: Pattern-based INSERT/DELETE SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing pattern-based INSERT/DELETE operation")
        
        try:
            from rdflib import Graph, ConjunctiveGraph, URIRef
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            
            # Parse the update query
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            self.logger.debug(f"Parsed update algebra: {algebra}")
            
            # Examine the algebra structure to understand how to access operations
            self.logger.debug(f"Algebra attributes: {dir(algebra)}")
            
            # Try different ways to access the update operations
            operations = None
            if hasattr(algebra, 'request'):
                operations = algebra.request
            elif hasattr(algebra, 'operations'):
                operations = algebra.operations
            elif hasattr(algebra, 'updates'):
                operations = algebra.updates
            elif hasattr(algebra, 'algebra'):
                operations = [algebra.algebra] if not isinstance(algebra.algebra, list) else algebra.algebra
            else:
                # Try to iterate directly over the algebra
                try:
                    operations = list(algebra)
                except (TypeError, AttributeError):
                    operations = [algebra]
            
            self.logger.debug(f"Found operations: {operations}")
            
            if operations:
                for update_op in operations:
                    self.logger.debug(f"Processing update operation: {update_op}, type: {type(update_op)}")
                    self.logger.debug(f"Update operation attributes: {dir(update_op)}")
                    
                    if hasattr(update_op, 'name'):
                        if update_op.name == 'Modify':
                            # This is a DELETE/INSERT WHERE operation
                            await self._execute_modify_operation(space_id, update_op, sparql_update)
                        elif update_op.name == 'InsertData':
                            # This should have been handled by INSERT_DATA type
                            self.logger.warning("InsertData found in pattern operation - delegating to INSERT_DATA handler")
                            return await self.execute_insert_data(space_id, sparql_update)
                        elif update_op.name == 'DeleteData':
                            # This should have been handled by DELETE_DATA type
                            self.logger.warning("DeleteData found in pattern operation - delegating to DELETE_DATA handler")
                            return await self.execute_delete_data(space_id, sparql_update)
                        else:
                            self.logger.warning(f"Unknown update operation: {update_op.name}")
                    else:
                        # Try to handle the operation directly if it's a Modify-like structure
                        if hasattr(update_op, 'where') or hasattr(update_op, 'delete') or hasattr(update_op, 'insert'):
                            await self._execute_modify_operation(space_id, update_op, sparql_update)
                        else:
                            self.logger.warning(f"Update operation without name or recognizable structure: {update_op}")
            else:
                self.logger.error("No operations found in algebra structure")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing pattern-based UPDATE: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def get_supported_update_types(self) -> Set[str]:
        """Get the set of supported SPARQL UPDATE operation types.
        
        Returns:
            Set of supported update type names
        """
        return {"INSERT_DATA", "DELETE_DATA", "INSERT_DELETE_PATTERN", "MODIFY"}
    
    def is_supported_update_type(self, update_type: str) -> bool:
        """Check if an update type is supported.
        
        Args:
            update_type: Name of the update type to check
            
        Returns:
            True if the update type is supported
        """
        return update_type in self.get_supported_update_types()
    
    def validate_sparql_update(self, sparql_update: str) -> bool:
        """Validate that a SPARQL UPDATE query can be parsed.
        
        Args:
            sparql_update: SPARQL UPDATE query string to validate
            
        Returns:
            True if the update is valid
        """
        try:
            parsed_update = parseUpdate(sparql_update)
            return parsed_update is not None
        except Exception as e:
            self.logger.error(f"SPARQL UPDATE validation failed: {e}")
            return False
    
    def extract_update_type(self, sparql_update: str) -> Optional[str]:
        """Extract the update operation type from a SPARQL UPDATE query.
        
        Args:
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            Update type name or None if extraction fails
        """
        try:
            # Normalize whitespace and convert to uppercase for pattern matching
            normalized = ' '.join(sparql_update.strip().split()).upper()
            
            if normalized.startswith('INSERT DATA'):
                return 'INSERT_DATA'
            elif normalized.startswith('DELETE DATA'):
                return 'DELETE_DATA'
            elif 'INSERT' in normalized and 'WHERE' in normalized:
                return 'INSERT_DELETE_PATTERN'
            elif 'DELETE' in normalized and 'WHERE' in normalized:
                return 'INSERT_DELETE_PATTERN'
            elif 'DELETE' in normalized and 'INSERT' in normalized:
                return 'MODIFY'
            else:
                return None
        except Exception as e:
            self.logger.error(f"Update type extraction failed: {e}")
            return None
    
    def parse_insert_data_triples(self, sparql_update: str) -> List[Tuple[Any, Any, Any, Optional[Any]]]:
        """Parse INSERT DATA query to extract ground triples.
        
        Args:
            sparql_update: INSERT DATA SPARQL query string
            
        Returns:
            List of (subject, predicate, object, graph) tuples
        """
        try:
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            triples = []
            
            # Extract operations from algebra
            operations = self.extract_operations_from_algebra(algebra)
            
            for op in operations:
                if hasattr(op, 'name') and op.name == 'InsertData':
                    if hasattr(op, 'quads'):
                        for quad in op.quads:
                            if len(quad) == 3:
                                # Triple without explicit graph
                                triples.append((quad[0], quad[1], quad[2], None))
                            elif len(quad) == 4:
                                # Quad with explicit graph
                                triples.append((quad[0], quad[1], quad[2], quad[3]))
                    elif hasattr(op, 'triples'):
                        for triple in op.triples:
                            triples.append((triple[0], triple[1], triple[2], None))
            
            return triples
            
        except Exception as e:
            self.logger.error(f"Error parsing INSERT DATA triples: {e}")
            return []
    
    def parse_delete_data_triples(self, sparql_update: str) -> List[Tuple[Any, Any, Any, Optional[Any]]]:
        """Parse DELETE DATA query to extract ground triples.
        
        Args:
            sparql_update: DELETE DATA SPARQL query string
            
        Returns:
            List of (subject, predicate, object, graph) tuples
        """
        try:
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            triples = []
            
            # Extract operations from algebra
            operations = self.extract_operations_from_algebra(algebra)
            
            for op in operations:
                if hasattr(op, 'name') and op.name == 'DeleteData':
                    if hasattr(op, 'quads'):
                        for quad in op.quads:
                            if len(quad) == 3:
                                # Triple without explicit graph
                                triples.append((quad[0], quad[1], quad[2], None))
                            elif len(quad) == 4:
                                # Quad with explicit graph
                                triples.append((quad[0], quad[1], quad[2], quad[3]))
                    elif hasattr(op, 'triples'):
                        for triple in op.triples:
                            triples.append((triple[0], triple[1], triple[2], None))
            
            return triples
            
        except Exception as e:
            self.logger.error(f"Error parsing DELETE DATA triples: {e}")
            return []
    
    def extract_operations_from_algebra(self, algebra) -> List[Any]:
        """Extract update operations from SPARQL algebra.
        
        Args:
            algebra: SPARQL update algebra object
            
        Returns:
            List of update operations
        """
        operations = []
        
        # Try different ways to access the update operations
        if hasattr(algebra, 'request'):
            operations = algebra.request if isinstance(algebra.request, list) else [algebra.request]
        elif hasattr(algebra, 'operations'):
            operations = algebra.operations if isinstance(algebra.operations, list) else [algebra.operations]
        elif hasattr(algebra, 'updates'):
            operations = algebra.updates if isinstance(algebra.updates, list) else [algebra.updates]
        elif hasattr(algebra, 'algebra'):
            operations = [algebra.algebra] if not isinstance(algebra.algebra, list) else algebra.algebra
        else:
            # Try to iterate directly over the algebra
            try:
                operations = list(algebra)
            except (TypeError, AttributeError):
                operations = [algebra]
        
        return operations
    
    async def initialize_graph_cache_if_needed(self, space_id: str) -> None:
        """Initialize graph cache if needed for the space.
        
        Args:
            space_id: Space identifier
        """
        try:
            # Check if space implementation has graph cache initialization
            if hasattr(self.space_impl, 'initialize_graph_cache'):
                await self.space_impl.initialize_graph_cache(space_id)
            else:
                self.logger.debug("Space implementation does not support graph cache")
        except Exception as e:
            self.logger.warning(f"Failed to initialize graph cache: {e}")
    
    async def ensure_graphs_registered_batch(self, space_id: str, graph_uris: Set[str]) -> None:
        """Ensure that all graph URIs are registered in the space.
        
        Args:
            space_id: Space identifier
            graph_uris: Set of graph URI strings to register
        """
        try:
            if hasattr(self.space_impl, 'ensure_graphs_registered_batch'):
                await self.space_impl.ensure_graphs_registered_batch(space_id, graph_uris)
            elif hasattr(self.space_impl, 'register_graph'):
                # Fallback to individual registration
                for graph_uri in graph_uris:
                    await self.space_impl.register_graph(space_id, URIRef(graph_uri))
            else:
                self.logger.debug("Space implementation does not support graph registration")
        except Exception as e:
            self.logger.error(f"Failed to register graphs: {e}")
            raise
    
    def convert_triples_to_quads(self, triples: List[Tuple[Any, Any, Any, Optional[Any]]], 
                                default_graph: Optional[URIRef] = None) -> List[Tuple[Any, Any, Any, Any]]:
        """Convert triples to quads with default graph handling.
        
        Args:
            triples: List of (subject, predicate, object, graph) tuples
            default_graph: Default graph URI to use when graph is None
            
        Returns:
            List of (subject, predicate, object, graph) quads
        """
        if default_graph is None:
            default_graph = URIRef(GraphConstants.GLOBAL_GRAPH_URI)
        
        quads = []
        for subject, predicate, obj, graph in triples:
            if graph is None:
                graph = default_graph
            quads.append((subject, predicate, obj, graph))
        
        return quads
    
    def extract_unique_graphs(self, quads: List[Tuple[Any, Any, Any, Any]]) -> Set[str]:
        """Extract unique graph URIs from a list of quads.
        
        Args:
            quads: List of (subject, predicate, object, graph) quads
            
        Returns:
            Set of unique graph URI strings
        """
        return {str(quad[3]) for quad in quads if quad[3] is not None}
    
    async def execute_modify_operation(self, space_id: str, modify_op: Any, sparql_update: str) -> bool:
        """Execute a MODIFY operation (DELETE/INSERT WHERE).
        
        Args:
            space_id: Space identifier
            modify_op: SPARQL algebra MODIFY operation
            sparql_update: Original SPARQL UPDATE query string
            
        Returns:
            True if successful
        """
        try:
            self.logger.debug(f"Executing MODIFY operation: {modify_op}")
            
            # Extract DELETE and INSERT templates
            delete_template = getattr(modify_op, 'delete', None)
            insert_template = getattr(modify_op, 'insert', None)
            where_pattern = getattr(modify_op, 'where', None)
            
            self.logger.debug(f"DELETE template: {delete_template}")
            self.logger.debug(f"INSERT template: {insert_template}")
            self.logger.debug(f"WHERE pattern: {where_pattern}")
            
            # For now, log that this is a complex operation that needs implementation
            self.logger.warning("MODIFY operations with WHERE patterns not yet fully implemented")
            self.logger.info("This would require:")
            self.logger.info("1. Translating WHERE pattern to SQL to find matching bindings")
            self.logger.info("2. Applying DELETE template to remove matching triples")
            self.logger.info("3. Applying INSERT template to add new triples")
            
            # Return success for now (placeholder implementation)
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing MODIFY operation: {e}")
            raise
    
    def estimate_update_complexity(self, sparql_update: str) -> int:
        """Estimate the computational complexity of an update operation.
        
        Args:
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            Complexity score (higher = more complex)
        """
        try:
            update_type = self.extract_update_type(sparql_update)
            
            if update_type == 'INSERT_DATA':
                # Count number of triples/quads
                triples = self.parse_insert_data_triples(sparql_update)
                return len(triples)
            elif update_type == 'DELETE_DATA':
                # Count number of triples/quads
                triples = self.parse_delete_data_triples(sparql_update)
                return len(triples)
            elif update_type in ('INSERT_DELETE_PATTERN', 'MODIFY'):
                # Pattern-based operations are more complex
                base_complexity = 10
                # Add complexity based on query length as proxy for pattern complexity
                return base_complexity + len(sparql_update) // 100
            else:
                return 1
                
        except Exception as e:
            self.logger.error(f"Error estimating update complexity: {e}")
            return 1
    
    def generate_update_statistics(self, sparql_update: str) -> Dict[str, Any]:
        """Generate statistics about a SPARQL UPDATE operation.
        
        Args:
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            Dictionary of update statistics
        """
        try:
            update_type = self.extract_update_type(sparql_update)
            complexity = self.estimate_update_complexity(sparql_update)
            
            stats = {
                'update_type': update_type,
                'query_length': len(sparql_update),
                'complexity_score': complexity,
                'supported': self.is_supported_update_type(update_type) if update_type else False,
                'valid': self.validate_sparql_update(sparql_update)
            }
            
            # Add type-specific statistics
            if update_type == 'INSERT_DATA':
                triples = self.parse_insert_data_triples(sparql_update)
                stats['triple_count'] = len(triples)
                stats['unique_graphs'] = len(self.extract_unique_graphs(
                    self.convert_triples_to_quads(triples)
                ))
            elif update_type == 'DELETE_DATA':
                triples = self.parse_delete_data_triples(sparql_update)
                stats['triple_count'] = len(triples)
                stats['unique_graphs'] = len(self.extract_unique_graphs(
                    self.convert_triples_to_quads(triples)
                ))
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error generating update statistics: {e}")
            return {
                'update_type': 'unknown',
                'query_length': len(sparql_update),
                'complexity_score': 0,
                'supported': False,
                'valid': False,
                'error': str(e)
            }