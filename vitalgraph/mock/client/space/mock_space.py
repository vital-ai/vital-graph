"""Mock Space

Mock implementation of a VitalGraph space for testing.
Uses pyoxigraph for in-memory quad storage.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import pyoxigraph as px
import logging

from .mock_graph import MockGraph
from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986

logger = logging.getLogger(__name__)


class MockSpace:
    """
    Mock implementation of a VitalGraph space.
    
    Contains an in-memory pyoxigraph store for quad storage
    and manages a collection of graphs within the space.
    """
    
    def __init__(self, space_id: int, name: str, tenant: Optional[str] = None, **kwargs):
        """
        Initialize a mock space with pyoxigraph store.
        
        Args:
            space_id: Unique space identifier
            name: Space name
            tenant: Optional tenant identifier
            **kwargs: Additional space properties
        """
        self.space_id = space_id
        self.name = name
        self.tenant = tenant
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.is_active = True
        self.properties = kwargs
        
        # Initialize in-memory pyoxigraph store
        self.store = px.Store()
        
        # Manage graphs within this space
        self.graphs: Dict[str, MockGraph] = {}
        self._next_graph_id = 1
        
        logger.info(f"Initialized MockSpace {space_id} with pyoxigraph store")
    
    def _is_valid_uri(self, value: str) -> bool:
        """
        Check if a string is a valid URI using RFC 3986 compliant validation.
        
        Uses the project's uri_utils module which provides comprehensive
        RFC 3986 validation without exceptions.
        
        Args:
            value: String to check
            
        Returns:
            True if valid URI, False otherwise
        """
        return bool(validate_rfc3986(value, rule='URI'))
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert space to dictionary representation.
        
        Returns:
            Dictionary containing space data
        """
        return {
            "space_id": self.space_id,
            "name": self.name,
            "tenant": self.tenant,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "graph_count": len(self.graphs),
            "triple_count": self.get_total_triple_count(),
            **self.properties
        }
    
    def update(self, **kwargs) -> None:
        """
        Update space properties.
        
        Args:
            **kwargs: Properties to update
        """
        for key, value in kwargs.items():
            if key in ["name", "tenant", "is_active"]:
                setattr(self, key, value)
            else:
                self.properties[key] = value
        
        self.updated_at = datetime.now()
    
    # Graph Management
    
    def add_graph(self, graph_uri: str, name: Optional[str] = None, **kwargs) -> MockGraph:
        """
        Add a new graph to the space.
        
        Args:
            graph_uri: Graph URI
            name: Optional graph name
            **kwargs: Additional graph properties
            
        Returns:
            Created MockGraph instance
        """
        graph_id = str(self._next_graph_id)
        self._next_graph_id += 1
        
        graph = MockGraph(
            graph_id=graph_id,
            graph_uri=graph_uri,
            space_id=self.space_id,
            name=name,
            **kwargs
        )
        
        self.graphs[graph_id] = graph
        logger.info(f"Added graph {graph_id} ({graph_uri}) to space {self.space_id}")
        return graph
    
    def get_graph(self, graph_id: str) -> Optional[MockGraph]:
        """Get a graph by ID."""
        return self.graphs.get(graph_id)
    
    def get_graph_by_uri(self, graph_uri: str) -> Optional[MockGraph]:
        """Get a graph by URI."""
        for graph in self.graphs.values():
            if graph.graph_uri == graph_uri:
                return graph
        return None
    
    def list_graphs(self) -> List[MockGraph]:
        """List all graphs in the space."""
        return list(self.graphs.values())
    
    def remove_graph(self, graph_id: str) -> bool:
        """
        Remove a graph from the space.
        
        Args:
            graph_id: Graph ID to remove
            
        Returns:
            True if graph was removed, False if not found
        """
        if graph_id in self.graphs:
            graph = self.graphs[graph_id]
            # Clear all triples from this graph in the store
            self.clear_graph(graph_id)
            del self.graphs[graph_id]
            logger.info(f"Removed graph {graph_id} from space {self.space_id}")
            return True
        return False
    
    # Quad Store Operations
    
    def add_quad(self, subject: str, predicate: str, object_value: str, 
                 graph_id: Optional[str] = None, object_type: str = "auto") -> None:
        """
        Add a quad to the store.
        
        Args:
            subject: Subject URI
            predicate: Predicate URI
            object_value: Object value (URI or literal)
            graph_id: Optional graph ID (uses default graph if None)
            object_type: Type of object ("uri", "literal", "auto")
        """
        try:
            subj = px.NamedNode(subject)
            pred = px.NamedNode(predicate)
            
            # Parse object based on type hint
            if object_type == "uri":
                obj = px.NamedNode(object_value)
            elif object_type == "literal":
                obj = px.Literal(object_value)
            else:  # auto-detect
                if self._is_valid_uri(object_value):
                    obj = px.NamedNode(object_value)
                else:
                    obj = px.Literal(object_value)
            
            if graph_id:
                # Check if it's a graph ID or URI
                graph_obj = self.graphs.get(graph_id)
                if not graph_obj:
                    # Try to find by URI
                    graph_obj = self.get_graph_by_uri(graph_id)
                
                if graph_obj:
                    graph = graph_obj.get_named_graph()
                    quad = px.Quad(subj, pred, obj, graph)
                else:
                    # Create a named graph directly using the graph_id as URI
                    graph = px.NamedNode(graph_id)
                    quad = px.Quad(subj, pred, obj, graph)
            else:
                quad = px.Quad(subj, pred, obj, px.DefaultGraph())
            
            self.store.add(quad)
            logger.debug(f"Successfully added quad: {subject} {predicate} {object_value}")
            
            # Update graph statistics
            if graph_id and graph_id in self.graphs:
                self._update_graph_stats(graph_id)
                
        except Exception as e:
            logger.error(f"Error adding quad: {e}")
            logger.error(f"  Subject: {subject}")
            logger.error(f"  Predicate: {predicate}")
            logger.error(f"  Object: {object_value}")
            logger.error(f"  Graph: {graph_id}")
            raise
    
    def remove_quad(self, subject: str, predicate: str, object_value: str,
                    graph_id: Optional[str] = None) -> None:
        """
        Remove a quad from the store.
        
        Args:
            subject: Subject URI
            predicate: Predicate URI
            object_value: Object value
            graph_id: Optional graph ID
        """
        try:
            logger.info(f"REMOVE_QUAD: Attempting to remove quad:")
            logger.info(f"  Input subject: '{subject}'")
            logger.info(f"  Input predicate: '{predicate}'")
            logger.info(f"  Input object: '{object_value}'")
            logger.info(f"  Input graph: '{graph_id}'")
            
            # Check if object is URI or literal
            is_uri = self._is_valid_uri(object_value)
            logger.info(f"  Object is URI: {is_uri}")
            
            # Create the exact same pyoxigraph objects as we did when adding
            subj = px.NamedNode(subject)
            pred = px.NamedNode(predicate)
            
            # Handle object value - match exactly how we created it in add_quad
            if is_uri:
                obj = px.NamedNode(object_value)
                logger.info(f"  Created NamedNode object: {obj}")
            else:
                # For literals, strip outer quotes if present (they were added by the query result formatting)
                if object_value.startswith('"') and object_value.endswith('"'):
                    literal_value = object_value[1:-1]  # Remove outer quotes
                    logger.info(f"  Stripped quotes from literal: '{object_value}' -> '{literal_value}'")
                else:
                    literal_value = object_value
                    logger.info(f"  Using literal as-is: '{literal_value}'")
                
                obj = px.Literal(literal_value)
                logger.info(f"  Created Literal object: {obj}")
            
            # Create the quad to remove - match the logic from add_quad
            if graph_id:
                logger.info(f"  Available graphs: {list(self.graphs.keys())}")
                
                # Check if it's a graph ID or URI (same logic as add_quad)
                graph_obj = self.graphs.get(graph_id)
                if not graph_obj:
                    # Try to find by URI
                    graph_obj = self.get_graph_by_uri(graph_id)
                    logger.info(f"  Found graph by URI: {graph_obj is not None}")
                
                if graph_obj:
                    graph = graph_obj.get_named_graph()
                    quad = px.Quad(subj, pred, obj, graph)
                    logger.info(f"  Created quad with named graph from graph object: {quad}")
                else:
                    # Create a named graph directly using the graph_id as URI (same as add_quad)
                    graph = px.NamedNode(graph_id)
                    quad = px.Quad(subj, pred, obj, graph)
                    logger.info(f"  Created quad with direct named graph: {quad}")
            else:
                quad = px.Quad(subj, pred, obj, px.DefaultGraph())
                logger.info(f"  Created quad with default graph: {quad}")
            
            # Count quads before removal
            before_count = len(list(self.store))
            logger.info(f"  Quads in store before removal: {before_count}")
            
            # Remove the quad
            self.store.remove(quad)
            logger.info(f"  Called store.remove(quad)")
            
            # Count quads after removal
            after_count = len(list(self.store))
            logger.info(f"  Quads in store after removal: {after_count}")
            logger.info(f"  Actually removed: {before_count - after_count}")
            
            # Update graph statistics
            if graph_id and graph_id in self.graphs:
                self._update_graph_stats(graph_id)
                
        except Exception as e:
            logger.error(f"Error removing quad: {e}")
            logger.error(f"  Subject: {subject}")
            logger.error(f"  Predicate: {predicate}")
            logger.error(f"  Object: {object_value}")
            logger.error(f"  Graph: {graph_id}")
            raise
    
    def add_quads_batch(self, quads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Add multiple quads in a single transaction.
        
        Args:
            quads: List of quad dictionaries with keys: subject, predicate, object, graph_id
            
        Returns:
            Result dictionary with success status and count
        """
        try:
            px_quads = []
            for quad_data in quads:
                subj = px.NamedNode(quad_data['subject'])
                pred = px.NamedNode(quad_data['predicate'])
                
                # Parse object - detect URI vs literal
                obj_value = quad_data['object']
                if self._is_valid_uri(obj_value):
                    obj = px.NamedNode(obj_value)
                else:
                    obj = px.Literal(obj_value)
                
                # Parse graph
                graph_id = quad_data.get('graph_id')
                if graph_id and graph_id in self.graphs:
                    graph = self.graphs[graph_id].get_named_graph()
                    px_quad = px.Quad(subj, pred, obj, graph)
                else:
                    px_quad = px.Quad(subj, pred, obj, px.DefaultGraph())
                
                px_quads.append(px_quad)
            
            # Transactional batch insert
            self.store.extend(px_quads)
            
            # Update all affected graph statistics
            affected_graphs = set(q.get('graph_id') for q in quads if q.get('graph_id'))
            for graph_id in affected_graphs:
                if graph_id in self.graphs:
                    self._update_graph_stats(graph_id)
            
            return {"success": True, "added_count": len(quads)}
            
        except Exception as e:
            logger.error(f"Error in batch quad insertion: {e}")
            return {"success": False, "error": str(e), "added_count": 0}
    
    def query_sparql(self, query: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a SPARQL query against the store.
        
        Args:
            query: SPARQL query string
            **kwargs: Additional query parameters (base_iri, prefixes, etc.)
            
        Returns:
            Query results with metadata
        """
        try:
            logger.debug(f"Executing SPARQL query: {query}")
            results = self.store.query(query, **kwargs)
            logger.debug(f"Query results type: {type(results)}")
            logger.debug(f"Query results dir: {[attr for attr in dir(results) if not attr.startswith('_')]}")
            
            # Handle different query types
            # Check for ASK query first (QueryBoolean)
            if str(type(results)) == "<class 'pyoxigraph.QueryBoolean'>":
                # ASK query - pyoxigraph QueryBoolean object
                boolean_result = bool(results)  # Convert to Python boolean
                logger.debug(f"ASK query result: {boolean_result}")
                return {
                    "query_type": "ASK",
                    "result": boolean_result
                }
            elif hasattr(results, 'value') and isinstance(getattr(results, 'value', None), bool):
                # ASK query
                return {
                    "query_type": "ASK",
                    "result": results.value
                }
            elif isinstance(results, bool):
                # ASK query (direct boolean)
                return {
                    "query_type": "ASK",
                    "result": results
                }
            # Check for CONSTRUCT query (QueryTriples)
            elif "CONSTRUCT" in query.upper() and hasattr(results, '__iter__'):
                # CONSTRUCT/DESCRIBE query - return triples
                triples = []
                for triple in results:
                    triples.append({
                        "subject": str(triple.subject),
                        "predicate": str(triple.predicate),
                        "object": str(triple.object)
                    })
                
                return {
                    "query_type": "CONSTRUCT",
                    "triples": triples,
                    "count": len(triples)
                }
            elif hasattr(results, '__iter__'):
                # SELECT query - return bindings
                bindings = []
                variables = []
                solution_count = 0
                
                for solution in results:
                    solution_count += 1
                    logger.debug(f"Processing solution {solution_count}: {type(solution)}")
                    
                    binding = {}
                    # Extract variables from the first solution if not done yet
                    if not variables:
                        # Get variable names from the query - simplified approach
                        import re
                        var_matches = re.findall(r'\?(\w+)', query)
                        variables = list(set(var_matches))
                        logger.debug(f"Extracted variables: {variables}")
                    
                    # Access solution values by variable name
                    for var_name in variables:
                        try:
                            var = px.Variable(var_name)
                            try:
                                value = solution[var]
                                binding[var_name] = {
                                    "value": str(value),
                                    "type": self._get_term_type(value)
                                }
                                logger.debug(f"  {var_name} = {value}")
                            except KeyError:
                                logger.debug(f"Variable {var_name} not in solution")
                                continue
                        except Exception as e:
                            logger.debug(f"Could not access variable {var_name}: {e}")
                            continue
                    
                    if binding:  # Only add non-empty bindings
                        bindings.append(binding)
                        logger.debug(f"Added binding: {binding}")
                
                logger.debug(f"Total solutions processed: {solution_count}, bindings created: {len(bindings)}")
                
                return {
                    "query_type": "SELECT",
                    "bindings": bindings,
                    "count": len(bindings)
                }
            else:
                # Unknown query type
                return {
                    "query_type": "UNKNOWN",
                    "error": f"Unsupported query result type: {type(results)}"
                }
                
        except Exception as e:
            logger.error(f"Error executing SPARQL query: {e}")
            return {
                "error": str(e),
                "query_type": "ERROR"
            }
    
    def update_sparql(self, update: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a SPARQL update operation.
        
        Args:
            update: SPARQL update string
            **kwargs: Additional update parameters
            
        Returns:
            Update result with success status
        """
        try:
            self.store.update(update, **kwargs)
            
            # Update statistics for all graphs (since we don't know which were affected)
            for graph_id in self.graphs:
                self._update_graph_stats(graph_id)
            
            return {"success": True, "message": "Update completed"}
            
        except Exception as e:
            logger.error(f"Error executing SPARQL update: {e}")
            return {"success": False, "error": str(e)}
    
    def _get_term_type(self, term) -> str:
        """Get the type of an RDF term."""
        if isinstance(term, px.NamedNode):
            return "uri"
        elif isinstance(term, px.Literal):
            return "literal"
        elif isinstance(term, px.BlankNode):
            return "bnode"
        else:
            return "unknown"
    
    def query_quads_pattern(self, subject: Optional[str] = None, 
                           predicate: Optional[str] = None,
                           object_value: Optional[str] = None,
                           graph_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Query quads using pattern matching.
        
        Args:
            subject: Subject URI pattern (None matches all)
            predicate: Predicate URI pattern (None matches all)
            object_value: Object value pattern (None matches all)
            graph_id: Graph ID pattern (None matches all)
            
        Returns:
            List of matching quads as dictionaries
        """
        try:
            # Convert string patterns to pyoxigraph terms
            subj_pattern = px.NamedNode(subject) if subject else None
            pred_pattern = px.NamedNode(predicate) if predicate else None
            
            obj_pattern = None
            if object_value:
                if self._is_valid_uri(object_value):
                    obj_pattern = px.NamedNode(object_value)
                else:
                    obj_pattern = px.Literal(object_value)
            
            graph_pattern = None
            if graph_id and graph_id in self.graphs:
                graph_pattern = self.graphs[graph_id].get_named_graph()
            elif graph_id == "default":
                graph_pattern = px.DefaultGraph()
            
            # Execute pattern query
            matching_quads = []
            for quad in self.store.quads_for_pattern(subj_pattern, pred_pattern, obj_pattern, graph_pattern):
                quad_dict = {
                    "subject": str(quad.subject),
                    "predicate": str(quad.predicate),
                    "object": str(quad.object),
                    "object_type": self._get_term_type(quad.object),
                    "graph": str(quad.graph_name) if quad.graph_name else "default"
                }
                matching_quads.append(quad_dict)
            
            return matching_quads
            
        except Exception as e:
            logger.error(f"Error in quad pattern query: {e}")
            return []
    
    def get_graph_statistics(self, graph_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics for a specific graph or all graphs.
        
        Args:
            graph_id: Graph ID (None for all graphs)
            
        Returns:
            Statistics dictionary
        """
        if graph_id and graph_id in self.graphs:
            graph = self.graphs[graph_id]
            graph_node = graph.get_named_graph()
            quad_count = len(list(self.store.quads_for_pattern(None, None, None, graph_node)))
            
            return {
                "graph_id": graph_id,
                "graph_uri": graph.graph_uri,
                "triple_count": quad_count,
                "last_modified": graph.last_modified.isoformat(),
                "exists": self.store.contains_named_graph(graph_node)
            }
        else:
            # Statistics for all graphs
            stats = {
                "total_graphs": len(self.graphs),
                "total_triples": self.get_total_triple_count(),
                "graphs": []
            }
            
            for gid, graph in self.graphs.items():
                graph_stats = self.get_graph_statistics(gid)
                stats["graphs"].append(graph_stats)
            
            return stats
    
    def load_rdf_data(self, data: str, format_type: str = "turtle", 
                     graph_id: Optional[str] = None, base_iri: Optional[str] = None) -> Dict[str, Any]:
        """
        Load RDF data into the store.
        
        Args:
            data: RDF data as string
            format_type: RDF format ("turtle", "ntriples", "jsonld", etc.)
            graph_id: Target graph ID (default graph if None)
            base_iri: Base IRI for relative URI resolution
            
        Returns:
            Load result with success status and count
        """
        try:
            # Map format names to pyoxigraph formats
            format_map = {
                "turtle": px.RdfFormat.TURTLE,
                "ntriples": px.RdfFormat.N_TRIPLES,
                "nquads": px.RdfFormat.N_QUADS,
                "jsonld": px.RdfFormat.JSON_LD,
                "rdfxml": px.RdfFormat.RDF_XML,
                "trig": px.RdfFormat.TRIG
            }
            
            px_format = format_map.get(format_type.lower(), px.RdfFormat.TURTLE)
            
            # Determine target graph
            to_graph = None
            if graph_id and graph_id in self.graphs:
                to_graph = self.graphs[graph_id].get_named_graph()
            
            # Count triples before loading
            before_count = self.get_total_triple_count()
            
            # Load data
            self.store.load(
                input=data,
                format=px_format,
                base_iri=base_iri,
                to_graph=to_graph
            )
            
            # Count triples after loading
            after_count = self.get_total_triple_count()
            loaded_count = after_count - before_count
            
            # Update graph statistics
            if graph_id and graph_id in self.graphs:
                self._update_graph_stats(graph_id)
            
            return {
                "success": True,
                "loaded_count": loaded_count,
                "format": format_type,
                "target_graph": graph_id or "default"
            }
            
        except Exception as e:
            logger.error(f"Error loading RDF data: {e}")
            return {
                "success": False,
                "error": str(e),
                "loaded_count": 0
            }
    
    def export_rdf_data(self, format_type: str = "turtle", 
                       graph_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Export RDF data from the store.
        
        Args:
            format_type: Export format
            graph_id: Source graph ID (all graphs if None)
            
        Returns:
            Export result with data or error
        """
        try:
            format_map = {
                "turtle": px.RdfFormat.TURTLE,
                "ntriples": px.RdfFormat.N_TRIPLES,
                "nquads": px.RdfFormat.N_QUADS,
                "jsonld": px.RdfFormat.JSON_LD,
                "rdfxml": px.RdfFormat.RDF_XML,
                "trig": px.RdfFormat.TRIG
            }
            
            px_format = format_map.get(format_type.lower(), px.RdfFormat.TURTLE)
            
            # Determine source graph
            from_graph = None
            if graph_id and graph_id in self.graphs:
                from_graph = self.graphs[graph_id].get_named_graph()
            
            # Export data
            data = self.store.dump(format=px_format, from_graph=from_graph)
            
            return {
                "success": True,
                "data": data.decode('utf-8') if isinstance(data, bytes) else data,
                "format": format_type,
                "source_graph": graph_id or "all"
            }
            
        except Exception as e:
            logger.error(f"Error exporting RDF data: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None
            }
    
    def clear_graph(self, graph_id: Optional[str] = None) -> None:
        """
        Clear all triples from a graph.
        
        Args:
            graph_id: Graph ID to clear (clears default graph if None)
        """
        try:
            if graph_id and graph_id in self.graphs:
                graph = self.graphs[graph_id].get_named_graph()
                self.store.clear_graph(graph)
                self._update_graph_stats(graph_id)
            else:
                # Clear default graph
                self.store.clear_graph(px.DefaultGraph())
        except Exception as e:
            logger.error(f"Error clearing graph: {e}")
            raise
    
    def get_total_triple_count(self) -> int:
        """Get total number of triples across all graphs."""
        return len(list(self.store.quads_for_pattern(None, None, None, None)))
    
    def _update_graph_stats(self, graph_id: str) -> None:
        """Update statistics for a specific graph."""
        if graph_id in self.graphs:
            graph = self.graphs[graph_id]
            graph_node = graph.get_named_graph()
            count = len(list(self.store.quads_for_pattern(None, None, None, graph_node)))
            graph.update_stats(count)
    
    def __str__(self) -> str:
        """String representation of the space."""
        return f"MockSpace(id={self.space_id}, name='{self.name}', graphs={len(self.graphs)})"
    
    def __repr__(self) -> str:
        """Detailed string representation of the space."""
        return self.__str__()