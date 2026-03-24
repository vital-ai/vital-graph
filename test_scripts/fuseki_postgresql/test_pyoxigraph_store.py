"""
PyOxigraph implementation of RDFStoreInterface for testing.
"""

import pyoxigraph
from typing import Dict, List, Any
import logging
import re
import sys
import os

# Add the fuseki_postgresql package to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'vitalgraph', 'db', 'fuseki_postgresql'))

from sparql_operations import RDFStoreInterface

logger = logging.getLogger(__name__)


class PyOxigraphStore(RDFStoreInterface):
    """PyOxigraph implementation of RDFStoreInterface for testing."""
    
    def __init__(self, store: pyoxigraph.Store = None):
        """Initialize with optional PyOxigraph store."""
        self.store = store or pyoxigraph.Store()
        self.logger = logging.getLogger(__name__)
    
    def load_turtle_data(self, turtle_data: str) -> bool:
        """Load RDF data from Turtle format."""
        try:
            self.store.load(turtle_data.encode(), "text/turtle")
            return True
        except Exception as e:
            self.logger.error(f"Error loading Turtle data: {e}")
            return False
    
    def execute_sparql_update(self, update_query: str) -> bool:
        """Execute SPARQL UPDATE operation."""
        try:
            self.store.update(update_query)
            return True
        except Exception as e:
            self.logger.error(f"SPARQL UPDATE failed: {e}")
            return False
    
    def execute_sparql_query(self, select_query: str) -> List[Dict[str, str]]:
        """Execute SPARQL SELECT query and return results."""
        try:
            results = []
            query_results = self.store.query(select_query)
            
            # Extract variable names from the query
            var_pattern = r'\?(\w+)'
            variables = re.findall(var_pattern, select_query)
            
            for solution in query_results:
                result = {}
                
                for var_name in variables:
                    try:
                        # Access solution by variable name
                        value = solution[var_name]
                        result[var_name] = str(value)
                    except (KeyError, TypeError):
                        # Variable not bound in this solution
                        continue
                
                if result:  # Only add non-empty results
                    results.append(result)
            
            return results
        except Exception as e:
            self.logger.error(f"SPARQL query failed: {e}")
            return []
    
    def get_all_triples(self) -> List[Dict[str, str]]:
        """Get all triples from store as list of dictionaries."""
        triples = []
        for quad in self.store:
            triples.append({
                'subject': str(quad.subject),
                'predicate': str(quad.predicate),
                'object': str(quad.object),
                'graph': str(quad.graph_name) if quad.graph_name else None
            })
        return sorted(triples, key=lambda x: (x['subject'], x['predicate'], x['object']))
    
    def count_triples(self) -> int:
        """Count total number of triples in the store."""
        return len(list(self.store))
    
    def clear_store(self) -> None:
        """Clear all data from the store."""
        # Create new empty store
        self.store = pyoxigraph.Store()
