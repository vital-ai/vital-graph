"""Temporary Triple Store Wrapper

Provides a wrapper around pyoxigraph temporary stores with utility methods
for loading JSON-LD documents and executing SPARQL queries.
"""

import logging
from typing import Dict, List, Any, Optional
import pyoxigraph

# VitalSigns imports for JSON-LD handling
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

logger = logging.getLogger(__name__)


class TemporaryTripleStore:
    """Wrapper for pyoxigraph temporary stores with utility methods."""
    
    def __init__(self, vitalsigns: Optional[VitalSigns] = None):
        """Initialize temporary triple store.
        
        Args:
            vitalsigns: Optional VitalSigns instance for JSON-LD conversion
        """
        self.store = pyoxigraph.Store()
        self.vitalsigns = vitalsigns or VitalSigns()
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def load_jsonld_document(self, document: Dict[str, Any]) -> None:
        """Load JSON-LD document into the store.
        
        Args:
            document: JSON-LD document to load
            
        Raises:
            Exception: If loading fails
        """
        try:
            # Convert JSON-LD document to string format for pyoxigraph
            import json
            jsonld_str = json.dumps(document)
            
            # Load into pyoxigraph store using the correct API
            self.store.load(
                jsonld_str.encode('utf-8'),
                "application/ld+json"
            )
            
            self.logger.debug(f"Loaded JSON-LD document with {len(document.get('@graph', []))} objects")
            
        except Exception as e:
            self.logger.error(f"Failed to load JSON-LD document: {e}")
            raise
    
    def execute_query(self, sparql_query: str) -> List[Dict[str, Any]]:
        """Execute SPARQL query and return results.
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings
            
        Raises:
            Exception: If query execution fails
        """
        try:
            results = []
            
            # Execute query using pyoxigraph
            query_results = self.store.query(sparql_query)
            
            # Convert results to list of dictionaries
            for result in query_results:
                try:
                    # Handle QuerySolution (SELECT results)
                    result_dict = {}
                    
                    # Get all variables from the query result
                    # We need to extract variable names from the query since iteration doesn't work
                    # For now, try common variable names or parse from query
                    var_names = self._extract_variables_from_query(sparql_query)
                    
                    for var_name in var_names:
                        try:
                            value = result[var_name]
                            if value is not None:
                                result_dict[var_name] = {
                                    'type': self._get_term_type(value),
                                    'value': self._clean_value(value)
                                }
                        except (KeyError, TypeError):
                            # Variable not in this result
                            continue
                    
                    results.append(result_dict)
                    
                except Exception:
                    # Handle other query types (CONSTRUCT, ASK, etc.) or different result formats
                    results.append({'result': str(result)})
            
            self.logger.debug(f"Query returned {len(results)} results")
            return results
            
        except Exception as e:
            self.logger.error(f"Failed to execute SPARQL query: {e}")
            self.logger.error(f"Query: {sparql_query}")
            raise
    
    def get_subject_triples(self, subject_uri: str) -> List[Dict[str, str]]:
        """Get all triples for a specific subject.
        
        Args:
            subject_uri: URI of the subject
            
        Returns:
            List of triple dictionaries with subject, predicate, object
        """
        try:
            sparql_query = f"""
            SELECT ?predicate ?object WHERE {{
                <{subject_uri}> ?predicate ?object .
            }}
            """
            
            results = self.execute_query(sparql_query)
            
            triples = []
            for result in results:
                if 'predicate' in result and 'object' in result:
                    triples.append({
                        'subject': subject_uri,
                        'predicate': result['predicate']['value'],
                        'object': result['object']['value']
                    })
            
            self.logger.debug(f"Found {len(triples)} triples for subject {subject_uri}")
            return triples
            
        except Exception as e:
            self.logger.error(f"Failed to get triples for subject {subject_uri}: {e}")
            raise
    
    def get_all_subjects(self) -> List[str]:
        """Get all unique subjects in the store.
        
        Returns:
            List of subject URIs
        """
        try:
            sparql_query = """
            SELECT DISTINCT ?subject WHERE {
                ?subject ?predicate ?object .
            }
            """
            
            results = self.execute_query(sparql_query)
            
            subjects = []
            for result in results:
                if 'subject' in result:
                    subjects.append(result['subject']['value'])
            
            self.logger.debug(f"Found {len(subjects)} unique subjects")
            return subjects
            
        except Exception as e:
            self.logger.error(f"Failed to get all subjects: {e}")
            raise
    
    def _extract_variables_from_query(self, sparql_query: str) -> List[str]:
        """Extract variable names from SPARQL query.
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            List of variable names (without ? prefix)
        """
        import re
        
        # Find all variables in the query (starting with ?)
        variables = re.findall(r'\?(\w+)', sparql_query)
        
        # Remove duplicates and return
        return list(set(variables))
    
    def _clean_value(self, value) -> str:
        """Clean value from pyoxigraph term.
        
        Args:
            value: RDF term from pyoxigraph
            
        Returns:
            Clean string value
        """
        value_str = str(value)
        
        # Remove angle brackets from URIs
        if value_str.startswith('<') and value_str.endswith('>'):
            return value_str[1:-1]
        
        # Remove quotes and datatype from literals
        if '^^' in value_str:
            # Extract just the literal value part
            if value_str.startswith('"') and '"^^' in value_str:
                return value_str[1:value_str.index('"^^')]
        
        # Remove quotes from simple literals
        if value_str.startswith('"') and value_str.endswith('"'):
            return value_str[1:-1]
        
        return value_str
    
    def _get_term_type(self, term) -> str:
        """Get the type of an RDF term.
        
        Args:
            term: RDF term from pyoxigraph
            
        Returns:
            Term type string ('uri', 'literal', 'bnode')
        """
        term_str = str(type(term))
        
        if 'NamedNode' in term_str:
            return 'uri'
        elif 'Literal' in term_str:
            return 'literal'
        elif 'BlankNode' in term_str:
            return 'bnode'
        else:
            return 'unknown'
    
    def clear(self) -> None:
        """Clear all triples from the store."""
        try:
            # Create a new store instance to clear all data
            self.store = pyoxigraph.Store()
            self.logger.debug("Cleared all triples from store")
        except Exception as e:
            self.logger.error(f"Failed to clear store: {e}")
            raise
    
    def get_triple_count(self) -> int:
        """Get the total number of triples in the store.
        
        Returns:
            Number of triples
        """
        try:
            sparql_query = """
            SELECT (COUNT(*) as ?count) WHERE {
                ?subject ?predicate ?object .
            }
            """
            
            results = self.execute_query(sparql_query)
            
            if results and 'count' in results[0]:
                return int(results[0]['count']['value'])
            else:
                return 0
                
        except Exception as e:
            self.logger.error(f"Failed to get triple count: {e}")
            return 0
