"""
Abstract SPARQL operations engine for parsing and execution.

This class encapsulates all SPARQL UPDATE parsing and execution logic
in a way that can be tested independently with different RDF store backends.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
import logging
import re
from rdflib.plugins.sparql import prepareQuery, prepareUpdate
from rdflib.plugins.sparql.parser import parseUpdate
from rdflib.plugins.sparql.algebra import translateUpdate

logger = logging.getLogger(__name__)


class RDFStoreInterface(ABC):
    """Abstract interface for RDF store backends."""
    
    @abstractmethod
    def load_turtle_data(self, turtle_data: str) -> bool:
        """Load RDF data from Turtle format."""
        pass
    
    @abstractmethod
    def execute_sparql_update(self, update_query: str) -> bool:
        """Execute SPARQL UPDATE operation."""
        pass
    
    @abstractmethod
    def execute_sparql_query(self, select_query: str) -> List[Dict[str, str]]:
        """Execute SPARQL SELECT query and return results."""
        pass
    
    @abstractmethod
    def get_all_triples(self) -> List[Dict[str, str]]:
        """Get all triples from store as list of dictionaries."""
        pass
    
    @abstractmethod
    def count_triples(self) -> int:
        """Count total number of triples in the store."""
        pass
    
    @abstractmethod
    def clear_store(self) -> None:
        """Clear all data from the store."""
        pass


class SPARQLOperationsEngine:
    """
    Abstract SPARQL operations engine for parsing and execution.
    
    This class encapsulates all SPARQL UPDATE parsing and execution logic
    in a way that can be tested independently with different RDF store backends.
    """
    
    def __init__(self, rdf_store: RDFStoreInterface):
        """
        Initialize SPARQL operations engine.
        
        Args:
            rdf_store: RDF store backend implementing RDFStoreInterface
        """
        self.rdf_store = rdf_store
        self.logger = logging.getLogger(__name__)
    
    def load_turtle_data(self, turtle_data: str) -> bool:
        """Load RDF data from Turtle format into the store."""
        return self.rdf_store.load_turtle_data(turtle_data)
    
    def execute_sparql_update(self, update_query: str) -> bool:
        """Execute SPARQL UPDATE operation on the store."""
        return self.rdf_store.execute_sparql_update(update_query)
    
    def execute_sparql_query(self, select_query: str) -> List[Dict[str, str]]:
        """Execute SPARQL SELECT query and return results."""
        return self.rdf_store.execute_sparql_query(select_query)
    
    def get_all_triples(self) -> List[Dict[str, str]]:
        """Get all triples from store as list of dictionaries."""
        return self.rdf_store.get_all_triples()
    
    def count_triples(self) -> int:
        """Count total number of triples in the store."""
        return self.rdf_store.count_triples()
    
    def clear_store(self) -> None:
        """Clear all data from the store."""
        self.rdf_store.clear_store()
    
    def parse_sparql_update(self, update_query: str) -> Dict[str, Any]:
        """
        Parse SPARQL UPDATE query to extract operation details using proper parse tree.
        
        Returns:
            Dictionary containing:
            - operation_type: 'insert', 'delete', 'delete_insert', 'insert_data', 'delete_data'
            - insert_patterns: List of INSERT patterns (if any)
            - delete_patterns: List of DELETE patterns (if any)
            - where_clause: WHERE clause (if any)
            - raw_query: Original query string
        """
        
        try:
            # Parse the SPARQL UPDATE query into a parse tree
            parsed_update = parseUpdate(update_query)
            
            result = {
                'operation_type': self._identify_operation_type(parsed_update),
                'insert_patterns': [],
                'delete_patterns': [],
                'where_clause': None,
                'raw_query': update_query,
                'parsed_tree': parsed_update  # Include parse tree for advanced processing
            }
            
            # Extract patterns from parse tree
            patterns = self._extract_patterns_from_query(parsed_update)
            result.update(patterns)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing SPARQL UPDATE: {e}")
            return {
                'operation_type': 'unknown',
                'insert_patterns': [],
                'delete_patterns': [],
                'where_clause': None,
                'raw_query': update_query,
                'error': str(e)
            }
    
    def resolve_delete_patterns(self, delete_patterns: List[str], where_clause: str) -> List[Dict[str, str]]:
        """
        Resolve DELETE patterns by executing SELECT query to find matching triples.
        
        This implements the "query-before-delete" strategy by converting
        DELETE patterns + WHERE clause into a SELECT query.
        """
        
        try:
            # Build SELECT query from DELETE patterns and WHERE clause
            select_query = self._build_select_from_delete(delete_patterns, where_clause)
            
            # Execute query to find matching triples
            results = self.execute_sparql_query(select_query)
            
            # Convert results to triple format
            return self._convert_results_to_triples(results, delete_patterns)
            
        except Exception as e:
            self.logger.error(f"Error resolving DELETE patterns: {e}")
            return []
    
    def validate_sparql_update_operation(self, update_query: str) -> Dict[str, Any]:
        """
        Comprehensive validation of SPARQL UPDATE operation.
        
        Returns validation report with:
        - syntax_valid: Boolean indicating if syntax is valid
        - operation_details: Parsed operation details
        - affected_triples_before: Triples that would be affected (for DELETE operations)
        - execution_result: Result of executing the operation
        - affected_triples_after: Actual changes made
        """
        
        validation_report = {
            'syntax_valid': False,
            'operation_details': {},
            'affected_triples_before': [],
            'execution_result': False,
            'affected_triples_after': [],
            'triple_count_before': 0,
            'triple_count_after': 0
        }
        
        try:
            # Step 1: Parse the query
            operation_details = self.parse_sparql_update(update_query)
            validation_report['operation_details'] = operation_details
            
            if 'error' not in operation_details:
                validation_report['syntax_valid'] = True
            
            # Step 2: Get current state
            triples_before = self.get_all_triples()
            validation_report['triple_count_before'] = len(triples_before)
            
            # Step 3: For DELETE operations, resolve affected triples
            if operation_details['operation_type'] in ['delete', 'delete_insert']:
                if operation_details['where_clause']:
                    affected_triples = self.resolve_delete_patterns(
                        operation_details['delete_patterns'],
                        operation_details['where_clause']
                    )
                    validation_report['affected_triples_before'] = affected_triples
            
            # Step 4: Execute the operation
            execution_success = self.execute_sparql_update(update_query)
            validation_report['execution_result'] = execution_success
            
            # Step 5: Get final state
            triples_after = self.get_all_triples()
            validation_report['triple_count_after'] = len(triples_after)
            
            # Step 6: Calculate actual changes
            validation_report['affected_triples_after'] = self._calculate_triple_changes(
                triples_before, triples_after
            )
            
            return validation_report
            
        except Exception as e:
            validation_report['error'] = str(e)
            return validation_report
    
    # Internal helper methods
    
    def _identify_operation_type(self, parsed_update) -> str:
        """Identify the type of SPARQL UPDATE operation from parse tree."""
        try:
            # rdflib parseUpdate returns a different structure than expected
            # Let's examine the actual structure and adapt
            
            # Try different ways to access the parsed structure
            if hasattr(parsed_update, 'request'):
                request = parsed_update.request
            elif hasattr(parsed_update, 'operations'):
                request = parsed_update
            else:
                request = parsed_update
            
            # Look for operations in various possible locations
            operations = None
            if hasattr(request, 'operations'):
                operations = request.operations
            elif hasattr(request, 'algebra'):
                operations = [request.algebra] if request.algebra else []
            elif isinstance(request, list):
                operations = request
            else:
                operations = [request]
            
            if operations:
                first_op = operations[0]
                
                # Get operation name from various possible attributes
                op_name = ''
                if hasattr(first_op, 'name'):
                    op_name = first_op.name
                elif hasattr(first_op, '_name'):
                    op_name = first_op._name
                else:
                    op_name = str(type(first_op).__name__)
                
                op_name = op_name.lower()
                
                # Map rdflib operation names to our operation types
                if 'insertdata' in op_name or 'load' in op_name:
                    return 'insert_data'
                elif 'deletedata' in op_name or 'clear' in op_name:
                    return 'delete_data'
                elif 'modify' in op_name or ('delete' in op_name and 'insert' in op_name):
                    return 'delete_insert'
                elif 'delete' in op_name:
                    return 'delete'
                elif 'insert' in op_name:
                    return 'insert'
            
            return 'unknown'
        except Exception as e:
            logger.error(f"Error identifying operation type: {e}")
            return 'unknown'
    
    def _extract_patterns_from_query(self, parsed_update) -> Dict[str, Any]:
        """Extract INSERT/DELETE patterns and WHERE clause from parse tree."""
        result = {
            'insert_patterns': [],
            'delete_patterns': [],
            'where_clause': None
        }
        
        try:
            # Get the first update operation from the parsed query
            if hasattr(parsed_update, 'request') and hasattr(parsed_update.request, 'operations'):
                operations = parsed_update.request.operations
                if operations:
                    first_op = operations[0]
                    
                    # Extract DELETE patterns
                    if hasattr(first_op, 'delete') and first_op.delete:
                        delete_patterns = self._extract_graph_patterns(first_op.delete)
                        result['delete_patterns'] = delete_patterns
                    
                    # Extract INSERT patterns
                    if hasattr(first_op, 'insert') and first_op.insert:
                        insert_patterns = self._extract_graph_patterns(first_op.insert)
                        result['insert_patterns'] = insert_patterns
                    
                    # Extract WHERE clause
                    if hasattr(first_op, 'where') and first_op.where:
                        where_clause = self._extract_where_clause(first_op.where)
                        result['where_clause'] = where_clause
        
        except Exception as e:
            logger.error(f"Error extracting patterns from parse tree: {e}")
        
        return result
    
    def _extract_graph_patterns(self, graph_pattern) -> List[str]:
        """Extract triple patterns from a graph pattern node."""
        patterns = []
        try:
            # This is a simplified extraction - in practice, we'd need to traverse
            # the parse tree more carefully to extract all triple patterns
            if hasattr(graph_pattern, 'triples'):
                for triple in graph_pattern.triples:
                    pattern = f"{triple[0]} {triple[1]} {triple[2]}"
                    patterns.append(pattern)
            elif hasattr(graph_pattern, 'part'):
                # Handle different graph pattern structures
                patterns.append(str(graph_pattern))
        except Exception as e:
            logger.error(f"Error extracting graph patterns: {e}")
            patterns.append(str(graph_pattern))
        
        return patterns
    
    def _extract_where_clause(self, where_pattern) -> str:
        """Extract WHERE clause from parse tree."""
        try:
            # Convert the WHERE pattern back to string representation
            return str(where_pattern)
        except Exception as e:
            logger.error(f"Error extracting WHERE clause: {e}")
            return None
    
    def _build_select_from_delete(self, delete_patterns: List[str], where_clause: str) -> str:
        """Build SELECT query from DELETE patterns and WHERE clause."""
        # Extract variables from DELETE patterns
        variables = set()
        for pattern in delete_patterns:
            # Extract ?variables from pattern
            vars_in_pattern = re.findall(r'\?(\w+)', pattern)
            variables.update(vars_in_pattern)
        
        # Format variables for SELECT
        if variables:
            select_vars = ' '.join([f'?{var}' for var in sorted(variables)])
        else:
            select_vars = '*'
        
        # Combine WHERE clause with DELETE patterns
        if where_clause and delete_patterns:
            combined_where = f"{where_clause} . {' . '.join(delete_patterns)}"
        elif where_clause:
            combined_where = where_clause
        elif delete_patterns:
            combined_where = ' . '.join(delete_patterns)
        else:
            combined_where = "?s ?p ?o"
        
        return f"SELECT {select_vars} WHERE {{ {combined_where} }}"
    
    def _convert_results_to_triples(self, results: List[Dict], patterns: List[str]) -> List[tuple]:
        """Convert SPARQL SELECT results to triple format."""
        triples = []
        
        for result in results:
            # For each result, try to construct triples based on the patterns
            # This is a simplified implementation - full version would need more sophisticated pattern matching
            if 's' in result and 'p' in result and 'o' in result:
                # Convert to tuple format: (subject, predicate, object, graph)
                graph = result.get('g', 'default')
                triple_tuple = (result['s'], result['p'], result['o'], graph)
                triples.append(triple_tuple)
        
        return triples
    
    def _calculate_triple_changes(self, before: List[tuple], after: List[tuple]) -> Dict[str, List]:
        """Calculate the differences between before and after triple sets."""
        before_set = set(str(t) for t in before)
        after_set = set(str(t) for t in after)
        
        added = [t for t in after if str(t) not in before_set]
        removed = [t for t in before if str(t) not in after_set]
        
        return {
            'added_triples': added,
            'removed_triples': removed,
            'added_count': len(added),
            'removed_count': len(removed)
        }
