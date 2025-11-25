"""
SPARQL queries for grouping URI-based graph retrieval.

This module provides SPARQL query builders for efficiently retrieving
complete entity and frame graphs using the enforced grouping URIs.
"""

from typing import List, Dict, Any, Optional


class GroupingURIQueryBuilder:
    """Builds SPARQL queries for retrieving graphs using grouping URIs."""
    
    def __init__(self):
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
    
    def build_entity_graph_subjects_query(self, entity_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to find all subjects with hasKGGraphURI = entity_uri.
        
        Args:
            entity_uri: The entity URI to find components for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{graph_id}> {{
                ?subject <{self.haley_prefix}hasKGGraphURI> <{entity_uri}> .
            }}
        }}
        """
    
    def build_frame_graph_subjects_query(self, frame_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to find all subjects with hasFrameGraphURI = frame_uri.
        
        Args:
            frame_uri: The frame URI to find components for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{graph_id}> {{
                ?subject <{self.haley_prefix}hasFrameGraphURI> <{frame_uri}> .
            }}
        }}
        """
    
    def build_subject_triples_query(self, subject_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to get all triples for a specific subject.
        
        Args:
            subject_uri: The subject to get triples for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                <{subject_uri}> ?predicate ?object .
            }}
        }}
        """
    
    def build_complete_entity_graph_query(self, entity_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to get complete entity graph in one query.
        
        Args:
            entity_uri: The entity URI to get complete graph for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                ?subject <{self.haley_prefix}hasKGGraphURI> <{entity_uri}> .
                ?subject ?predicate ?object .
            }}
        }}
        """
    
    def build_complete_frame_graph_query(self, frame_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to get complete frame graph in one query.
        
        Args:
            frame_uri: The frame URI to get complete graph for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                ?subject <{self.haley_prefix}hasFrameGraphURI> <{frame_uri}> .
                ?subject ?predicate ?object .
            }}
        }}
        """
    
    def build_entity_components_by_type_query(self, entity_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to get entity graph components grouped by type.
        
        Args:
            entity_uri: The entity URI to get components for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT DISTINCT ?subject ?type WHERE {{
            GRAPH <{graph_id}> {{
                ?subject <{self.haley_prefix}hasKGGraphURI> <{entity_uri}> .
                ?subject a ?type .
                FILTER(?type IN (
                    <{self.haley_prefix}KGEntity>,
                    <{self.haley_prefix}KGFrame>, 
                    <{self.haley_prefix}KGSlot>,
                    <{self.haley_prefix}hasSlot>
                ))
            }}
        }}
        """
    
    def build_frame_components_by_type_query(self, frame_uri: str, graph_id: str) -> str:
        """
        Build SPARQL query to get frame graph components grouped by type.
        
        Args:
            frame_uri: The frame URI to get components for
            graph_id: The graph to search in
            
        Returns:
            SPARQL query string
        """
        return f"""
        SELECT DISTINCT ?subject ?type WHERE {{
            GRAPH <{graph_id}> {{
                ?subject <{self.haley_prefix}hasFrameGraphURI> <{frame_uri}> .
                ?subject a ?type .
                FILTER(?type IN (
                    <{self.haley_prefix}KGFrame>,
                    <{self.haley_prefix}KGSlot>,
                    <{self.haley_prefix}hasSlot>
                ))
            }}
        }}
        """


class GroupingURIGraphRetriever:
    """Retrieves complete graphs using grouping URI-based SPARQL queries."""
    
    def __init__(self, query_builder: Optional[GroupingURIQueryBuilder] = None):
        self.query_builder = query_builder or GroupingURIQueryBuilder()
    
    def get_entity_graph_triples(self, entity_uri: str, graph_id: str, 
                                sparql_executor) -> List[Dict[str, Any]]:
        """
        Get all triples for complete entity graph using hasKGGraphURI.
        
        Args:
            entity_uri: Entity URI to get graph for
            graph_id: Graph to search in
            sparql_executor: Function that executes SPARQL queries
            
        Returns:
            List of triple dictionaries with 'subject', 'predicate', 'object'
        """
        query = self.query_builder.build_complete_entity_graph_query(entity_uri, graph_id)
        results = sparql_executor(query)
        
        return [
            {
                'subject': result['subject'],
                'predicate': result['predicate'], 
                'object': result['object']
            }
            for result in results
        ]
    
    def get_frame_graph_triples(self, frame_uri: str, graph_id: str,
                               sparql_executor) -> List[Dict[str, Any]]:
        """
        Get all triples for complete frame graph using hasFrameGraphURI.
        
        Args:
            frame_uri: Frame URI to get graph for
            graph_id: Graph to search in
            sparql_executor: Function that executes SPARQL queries
            
        Returns:
            List of triple dictionaries with 'subject', 'predicate', 'object'
        """
        query = self.query_builder.build_complete_frame_graph_query(frame_uri, graph_id)
        results = sparql_executor(query)
        
        return [
            {
                'subject': result['subject'],
                'predicate': result['predicate'],
                'object': result['object']
            }
            for result in results
        ]
    
    def get_entity_components_by_type(self, entity_uri: str, graph_id: str,
                                     sparql_executor) -> Dict[str, List[str]]:
        """
        Get entity graph component URIs grouped by type.
        
        Args:
            entity_uri: Entity URI to get components for
            graph_id: Graph to search in
            sparql_executor: Function that executes SPARQL queries
            
        Returns:
            Dictionary mapping type URIs to lists of component URIs
        """
        query = self.query_builder.build_entity_components_by_type_query(entity_uri, graph_id)
        results = sparql_executor(query)
        
        components_by_type = {}
        for result in results:
            type_uri = result['type']
            subject_uri = result['subject']
            
            if type_uri not in components_by_type:
                components_by_type[type_uri] = []
            components_by_type[type_uri].append(subject_uri)
        
        return components_by_type
    
    def get_frame_components_by_type(self, frame_uri: str, graph_id: str,
                                    sparql_executor) -> Dict[str, List[str]]:
        """
        Get frame graph component URIs grouped by type.
        
        Args:
            frame_uri: Frame URI to get components for
            graph_id: Graph to search in
            sparql_executor: Function that executes SPARQL queries
            
        Returns:
            Dictionary mapping type URIs to lists of component URIs
        """
        query = self.query_builder.build_frame_components_by_type_query(frame_uri, graph_id)
        results = sparql_executor(query)
        
        components_by_type = {}
        for result in results:
            type_uri = result['type']
            subject_uri = result['subject']
            
            if type_uri not in components_by_type:
                components_by_type[type_uri] = []
            components_by_type[type_uri].append(subject_uri)
        
        return components_by_type
