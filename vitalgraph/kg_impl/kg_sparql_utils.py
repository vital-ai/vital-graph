#!/usr/bin/env python3
"""
KG SPARQL Utilities

Utility functions for SPARQL query processing and result handling.
Used across KG processors to provide consistent SPARQL operations.
"""

import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class KGSparqlUtils:
    """Utility class for common SPARQL operations and result processing."""
    
    @staticmethod
    def extract_count_from_results(results: Any) -> int:
        """
        Extract count value from SPARQL COUNT query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            int: Extracted count value, 0 if not found
        """
        try:
            if isinstance(results, dict) and results.get("results", {}).get("bindings"):
                bindings = results["results"]["bindings"]
                if bindings and len(bindings) > 0:
                    count_binding = bindings[0]
                    if "count" in count_binding:
                        count_value = count_binding["count"].get("value", "0")
                        return int(count_value)
            return 0
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Error extracting count from SPARQL results: {e}")
            return 0
    
    @staticmethod
    def extract_uris_from_results(results: Any, variable_name: str = "uri") -> List[str]:
        """
        Extract URI values from SPARQL query results.
        
        Args:
            results: SPARQL query results
            variable_name: Name of the variable containing URIs
            
        Returns:
            List[str]: List of extracted URIs
        """
        uris = []
        try:
            if isinstance(results, dict) and results.get("results", {}).get("bindings"):
                for binding in results["results"]["bindings"]:
                    if variable_name in binding:
                        uri_value = binding[variable_name].get("value")
                        if uri_value:
                            uris.append(uri_value)
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting URIs from SPARQL results: {e}")
        
        return uris
    
    @staticmethod
    def extract_subject_uris_from_results(results: Any) -> List[str]:
        """
        Extract subject URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List[str]: List of extracted subject URIs
        """
        return KGSparqlUtils.extract_uris_from_results(results, "subject")
    
    @staticmethod
    def build_search_filter(search: Optional[str], search_properties: List[str] = None) -> str:
        """
        Build SPARQL search filter for text search across properties.
        
        Args:
            search: Search term
            search_properties: List of properties to search (defaults to common text properties)
            
        Returns:
            str: SPARQL filter clause
        """
        if not search:
            return ""
        
        if search_properties is None:
            search_properties = [
                "haley:hasName", 
                "vital:hasName", 
                "haley:hasKGSlotStringValue",
                "vital:hasDescription"
            ]
        
        # Escape search term for SPARQL
        escaped_search = search.replace('"', '\\"')
        
        # Build filter conditions for each property
        filter_conditions = []
        for prop in search_properties:
            filter_conditions.append(f'CONTAINS(LCASE(STR(?{prop.split(":")[-1]})), LCASE("{escaped_search}"))')
        
        if filter_conditions:
            return f"""
            OPTIONAL {{ ?subject {search_properties[0]} ?{search_properties[0].split(":")[-1]} }}
            """ + "".join([f"""
            OPTIONAL {{ ?subject {prop} ?{prop.split(":")[-1]} }}""" for prop in search_properties[1:]]) + f"""
            FILTER ({" || ".join(filter_conditions)})
            """
        
        return ""
    
    @staticmethod
    def build_pagination_clause(page_size: int, offset: int) -> str:
        """
        Build SPARQL LIMIT and OFFSET clause for pagination.
        
        Args:
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            str: SPARQL pagination clause
        """
        return f"LIMIT {page_size} OFFSET {offset}"
    
    @staticmethod
    def build_graph_clause(graph_id: str) -> str:
        """
        Build SPARQL GRAPH clause.
        
        Args:
            graph_id: Graph identifier
            
        Returns:
            str: SPARQL GRAPH clause
        """
        return f"GRAPH <{graph_id}>"
    
    @staticmethod
    def escape_sparql_string(value: str) -> str:
        """
        Escape string value for use in SPARQL queries.
        
        Args:
            value: String value to escape
            
        Returns:
            str: Escaped string value
        """
        if not isinstance(value, str):
            return str(value)
        
        # Escape quotes and backslashes
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return escaped
    
    @staticmethod
    def build_uri_reference(uri: str) -> str:
        """
        Build proper URI reference for SPARQL queries.
        
        Args:
            uri: URI string
            
        Returns:
            str: Properly formatted URI reference
        """
        if not uri:
            return ""
        
        # If already wrapped in angle brackets, return as-is
        if uri.startswith('<') and uri.endswith('>'):
            return uri
        
        # Wrap in angle brackets
        return f"<{uri}>"
    
    @staticmethod
    def build_prefixes() -> str:
        """
        Build standard SPARQL prefixes for KG operations.
        
        Returns:
            str: SPARQL prefix declarations
        """
        return """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        """
    
    @staticmethod
    def validate_sparql_results(results: Any) -> bool:
        """
        Validate SPARQL query results structure.
        
        Args:
            results: SPARQL query results
            
        Returns:
            bool: True if results are valid, False otherwise
        """
        try:
            if not isinstance(results, dict):
                return False
            
            if "results" not in results:
                return False
            
            if "bindings" not in results["results"]:
                return False
            
            return True
        except Exception:
            return False
    
    @staticmethod
    def build_type_filter(entity_type: Optional[str]) -> str:
        """
        Build SPARQL type filter clause.
        
        Args:
            entity_type: Entity type URI
            
        Returns:
            str: SPARQL type filter clause
        """
        if not entity_type:
            return ""
        
        return f"""
        ?subject a {KGSparqlUtils.build_uri_reference(entity_type)} .
        """
    
    @staticmethod
    def build_grouping_uri_filter(grouping_uri: str, property_name: str = "haley:kGGraphURI") -> str:
        """
        Build SPARQL filter for grouping URI properties.
        
        Args:
            grouping_uri: Grouping URI value
            property_name: Property name for grouping URI
            
        Returns:
            str: SPARQL grouping URI filter clause
        """
        if not grouping_uri:
            return ""
        
        return f"""
        ?subject {property_name} {KGSparqlUtils.build_uri_reference(grouping_uri)} .
        """
    
    @staticmethod
    def extract_triples_from_sparql_results(results: Any) -> List[tuple]:
        """
        Extract triples from SPARQL SELECT results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List[tuple]: List of (subject, predicate, object) triples
        """
        triples = []
        try:
            # Handle nested structure: results.results.bindings
            if isinstance(results, dict) and "results" in results and isinstance(results["results"], dict):
                bindings = results["results"].get("bindings", [])
                for binding in bindings:
                    subject = binding.get("subject", {}).get("value")
                    predicate = binding.get("predicate", {}).get("value")
                    obj = binding.get("object", {}).get("value")
                    if subject and predicate and obj:
                        triples.append((subject, predicate, obj))
            # Handle flat structure: results.bindings
            elif isinstance(results, dict) and results.get("bindings"):
                for binding in results["bindings"]:
                    subject = binding.get("subject", {}).get("value")
                    predicate = binding.get("predicate", {}).get("value")
                    obj = binding.get("object", {}).get("value")
                    if subject and predicate and obj:
                        triples.append((subject, predicate, obj))
            elif isinstance(results, list):
                for item in results:
                    if isinstance(item, dict):
                        subject = item.get("subject")
                        predicate = item.get("predicate")
                        obj = item.get("object")
                        
                        # Handle both string and dict formats
                        if isinstance(subject, dict):
                            subject = subject.get("value")
                        if isinstance(predicate, dict):
                            predicate = predicate.get("value")
                        if isinstance(obj, dict):
                            obj = obj.get("value")
                        
                        if subject and predicate and obj:
                            triples.append((subject, predicate, obj))
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting triples from SPARQL results: {e}")
        
        return triples
    
    @staticmethod
    def extract_frame_uris_from_results(results: Any) -> List[str]:
        """
        Extract frame URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List[str]: List of extracted frame URIs
        """
        frame_uris = []
        try:
            if isinstance(results, dict) and results.get("bindings"):
                for binding in results["bindings"]:
                    frame_uri = binding.get("frame_uri", {}).get("value")
                    if frame_uri:
                        frame_uris.append(frame_uri)
            elif isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and "frame_uri" in item:
                        frame_value = item["frame_uri"]
                        if isinstance(frame_value, str):
                            frame_uris.append(frame_value)
                        elif isinstance(frame_value, dict):
                            frame_uri = frame_value.get("value")
                            if frame_uri:
                                frame_uris.append(frame_uri)
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting frame URIs from SPARQL results: {e}")
        
        return frame_uris
    
    @staticmethod
    def convert_triples_to_vitalsigns_frames(triples: List[Dict[str, str]]) -> List:
        """
        Convert triples to VitalSigns frame objects using GraphObject.from_triples_list().
        
        Args:
            triples: List of triple dictionaries with 'subject', 'predicate', 'object' keys
            
        Returns:
            List: List of VitalSigns KGFrame objects
        """
        try:
            if not triples:
                return []
            
            # Convert triples to the format expected by GraphObject.from_triples_list()
            # The method expects a Generator[Tuple, None, None] of RDFLib (URIRef, URIRef, URIRef/Literal) tuples
            def triples_generator():
                from rdflib import URIRef, Literal
                for triple in triples:
                    subject = URIRef(triple["subject"])
                    predicate = URIRef(triple["predicate"])
                    
                    # Object might be a URI or literal value
                    obj_str = triple["object"]
                    from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                    if validate_rfc3986(obj_str, rule='URI'):
                        obj = URIRef(obj_str)
                    else:
                        obj = Literal(obj_str)
                    
                    yield (subject, predicate, obj)
            
            # Use GraphObject.from_triples_list() to convert all triples to VitalSigns objects
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            all_objects = GraphObject.from_triples_list(triples_generator())
            
            # Filter for KGFrame objects
            frames = []
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            
            for obj in all_objects:
                if isinstance(obj, KGFrame):
                    frames.append(obj)
            
            logger.info(f"🔍 DEBUG: Converted {len(triples)} triples to {len(all_objects)} objects, {len(frames)} frames")
            
            return frames
            
        except Exception as e:
            logger.error(f"Error converting triples to VitalSigns frames: {e}")
            return []


class KGSparqlQueryBuilder:
    """Builder class for constructing common SPARQL queries."""
    
    def __init__(self):
        self.utils = KGSparqlUtils()
    
    def build_frame_discovery_query(self, graph_id: str, entity_uri: str, 
                                  page_size: int = 100, offset: int = 0, 
                                  search: Optional[str] = None) -> str:
        """
        Build SPARQL query to discover frames associated with an entity.
        
        Args:
            graph_id: Graph identifier
            entity_uri: Entity URI
            page_size: Number of results per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            str: SPARQL query string
        """
        search_filter = self.utils.build_search_filter(search) if search else ""
        pagination = self.utils.build_pagination_clause(page_size, offset)
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT DISTINCT ?frame WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                ?frame a haley:KGFrame ;
                       haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} .
                {search_filter}
            }}
        }}
        ORDER BY ?frame
        {pagination}
        """
    
    def build_frame_count_query(self, graph_id: str, entity_uri: str, 
                               search: Optional[str] = None) -> str:
        """
        Build SPARQL query to count frames associated with an entity.
        
        Args:
            graph_id: Graph identifier
            entity_uri: Entity URI
            search: Optional search term
            
        Returns:
            str: SPARQL count query string
        """
        search_filter = self.utils.build_search_filter(search) if search else ""
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT (COUNT(DISTINCT ?frame) as ?count) WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                ?frame a haley:KGFrame ;
                       haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} .
                {search_filter}
            }}
        }}
        """
    
    def build_frame_graph_query(self, graph_id: str, frame_uri: str, 
                               include_frame_graph: bool = True) -> str:
        """
        Build SPARQL query to get frame and optionally its complete graph.
        
        Args:
            graph_id: Graph identifier
            frame_uri: Frame URI
            include_frame_graph: Whether to include complete frame graph
            
        Returns:
            str: SPARQL query string
        """
        import logging
        logger = logging.getLogger(f"{__name__}.KGSparqlQueryBuilder")
        
        if include_frame_graph:
            # Get frame and all objects in its frame graph, including connecting edges
            query = f"""
            {self.utils.build_prefixes()}
            
            SELECT DISTINCT ?subject WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    {{
                        # Get the frame itself
                        BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                        {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame .
                    }} UNION {{
                        # Get all objects that belong to this frame's graph
                        ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                    }} UNION {{
                        # Get edges connecting objects within the frame
                        # Only include edges that have frameGraphURI (excludes Edge_hasEntityKGFrame)
                        ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                        ?subject vital:hasEdgeSource ?frameObject .
                    }}
                }}
            }}
            """
            logger.error(f"🔍 Built frame graph query for {frame_uri}")
            logger.error(f"🔍 Query will look for:")
            logger.error(f"🔍   1. Frame itself: {frame_uri}")
            logger.error(f"🔍   2. Objects with hasFrameGraphURI = {frame_uri}")
            logger.error(f"🔍   3. Edges with hasFrameGraphURI = {frame_uri}")
            return query
        else:
            # Get only the frame itself
            return f"""
            {self.utils.build_prefixes()}
            
            SELECT DISTINCT ?subject WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                    {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame .
                }}
            }}
            """
    
    def build_frame_deletion_count_query(self, graph_id: str, frame_uri: str) -> str:
        """
        Build SPARQL query to count objects that will be deleted with a frame.
        
        Args:
            graph_id: Graph identifier
            frame_uri: Frame URI
            
        Returns:
            str: SPARQL count query string
        """
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT (COUNT(?subject) as ?count) WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                {{
                    # Count the frame itself
                    BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                    {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame .
                }} UNION {{
                    # Count all objects that belong to this frame's graph
                    ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                }}
            }}
        }}
        """
    
    def build_frame_deletion_query(self, graph_id: str, frame_uri: str) -> str:
        """
        Build SPARQL DELETE query to remove frame and its complete graph.
        
        Args:
            graph_id: Graph identifier
            frame_uri: Frame URI
            
        Returns:
            str: SPARQL DELETE query string
        """
        return f"""
        {self.utils.build_prefixes()}
        
        DELETE {{
            {self.utils.build_graph_clause(graph_id)} {{
                ?subject ?predicate ?object .
            }}
        }}
        WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                {{
                    # Delete the frame itself
                    BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                    {self.utils.build_uri_reference(frame_uri)} ?predicate ?object .
                }} UNION {{
                    # Delete all objects that belong to this frame's graph
                    ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} ;
                             ?predicate ?object .
                }}
            }}
        }}
        """
    
    def build_entity_graphs_query(self, graph_id: str, entity_type_uri: Optional[str] = None, 
                                 search: Optional[str] = None, page_size: int = 100, 
                                 offset: int = 0) -> str:
        """
        Build SPARQL query for listing complete entity graphs (all objects with kGGraphURI).
        
        Args:
            graph_id: Graph identifier
            entity_type_uri: Optional entity type filter
            search: Optional search term
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            str: SPARQL query string
        """
        # Build entity type filter
        if entity_type_uri:
            entity_filter = f"?entity a {self.utils.build_uri_reference(entity_type_uri)} ."
        else:
            entity_filter = """
            ?entity a ?entityType .
            FILTER(STRSTARTS(STR(?entityType), "http://vital.ai/ontology/haley-ai-kg#KG") && STRENDS(STR(?entityType), "Entity"))
            """
        
        # Build search filter
        search_filter = ""
        if search:
            escaped_search = self.utils.escape_sparql_string(search)
            search_filter = f"""
            ?entity vital:hasName ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{escaped_search}")))
            """
        
        # Build pagination
        pagination = self.utils.build_pagination_clause(page_size, offset)
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT DISTINCT ?subject WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                # Find entities first
                {entity_filter}
                {search_filter}
                
                # Then find all objects with matching hasKGGraphURI
                ?subject haley:hasKGGraphURI ?entity .
            }}
        }}
        ORDER BY ?subject
        {pagination}
        """
    
    def build_list_entities_query(self, graph_id: str, entity_type_uri: Optional[str] = None, 
                                 search: Optional[str] = None, page_size: int = 100, 
                                 offset: int = 0) -> str:
        """
        Build SPARQL query for listing entity subjects (subject-first pattern).
        
        Args:
            graph_id: Graph identifier
            entity_type_uri: Optional entity type filter
            search: Optional search term
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            str: SPARQL query string
        """
        # Build entity type filter
        # KGEntity uses hasKGEntityType property, not rdf:type
        if entity_type_uri:
            type_filter = f"""
            ?entity vital-core:vitaltype haley:KGEntity .
            ?entity haley:hasKGEntityType {self.utils.build_uri_reference(entity_type_uri)} .
            """
        else:
            type_filter = """
            ?entity vital-core:vitaltype haley:KGEntity .
            """
        
        # Build search filter
        search_filter = ""
        if search:
            escaped_search = self.utils.escape_sparql_string(search)
            search_filter = f"""
            ?entity vital:hasName ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{escaped_search}")))
            """
        
        # Build pagination
        pagination = self.utils.build_pagination_clause(page_size, offset)
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT DISTINCT ?entity WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                {type_filter}
                {search_filter}
            }}
        }}
        ORDER BY ?entity
        {pagination}
        """