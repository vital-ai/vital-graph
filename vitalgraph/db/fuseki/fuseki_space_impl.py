"""
Fuseki Space Implementation for VitalGraph

This module provides the Fuseki backend implementation of SpaceBackendInterface
using Apache Jena Fuseki's HTTP API for RDF storage and SPARQL operations.

Architecture:
- Single Fuseki dataset contains all VitalGraph data
- Special space-graph tracks space metadata via VitalSegment objects
- KGSegment objects link spaces to named graphs
- All RDF operations target named graphs (not default graph)
- HTTP requests to Fuseki REST endpoints for all operations
"""

import logging
import asyncio
import aiohttp
import json
from typing import Dict, List, Optional, Any, AsyncGenerator, Tuple, Union
from contextlib import asynccontextmanager
from urllib.parse import urlencode, quote
from datetime import datetime

# RDFLib imports for type hints
from rdflib import URIRef, Literal, BNode, Variable
from rdflib.term import Identifier

# VitalSigns imports
from vital_ai_vitalsigns_core.model.VitalSegment import VitalSegment
from ai_haley_kg_domain.model.KGSegment import KGSegment
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator

# Import interfaces
from ..space_backend_interface import SpaceBackendInterface
from ..sparql_inf import SparqlBackendInterface
from .fuseki_sparql_impl import FusekiSparqlImpl
from ..backend_config import BackendConfig
from ...utils.resource_manager import track_session


class FusekiSpaceImpl(SpaceBackendInterface):
    """
    Fuseki implementation of SpaceBackendInterface using HTTP API.
    
    Uses a single Fuseki dataset with:
    - Space metadata in special space-graph via VitalSegment/KGSegment objects
    - RDF data in named graphs per space
    - HTTP requests for all operations
    """
    
    def __init__(self, server_url: str, dataset_name: str = 'vitalgraph', 
                 username: Optional[str] = None, password: Optional[str] = None, 
                 timeout: int = 30, **kwargs):
        """
        Initialize Fuseki space implementation.
        
        Args:
            server_url: Fuseki server URL (e.g., 'http://localhost:3030')
            dataset_name: Dataset name (default: 'vitalgraph')
            username: Optional username for authentication
            password: Optional password for authentication
            timeout: Request timeout in seconds (default: 30)
            **kwargs: Additional configuration parameters
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Store Fuseki configuration
        self.server_url = server_url.rstrip('/')
        self.dataset_name = dataset_name
        self.username = username
        self.password = password
        self.timeout = timeout
        
        # Fuseki endpoint URLs
        self.query_url = f"{self.server_url}/{self.dataset_name}/sparql"
        self.update_url = f"{self.server_url}/{self.dataset_name}/update"
        self.graph_store_url = f"{self.server_url}/{self.dataset_name}/data"
        
        # Special graphs
        self.space_graph_uri = "urn:vitalgraph:spaces"
        
        # HTTP session for connection pooling
        self._session = None
        self._sparql_impl_cache = {}
        
        self.logger.info(f"Initialized Fuseki space implementation: {self.server_url}/{self.dataset_name}")
        
        # Initialize the space-graph infrastructure on first use
        self._space_graph_initialized = False
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session with authentication."""
        if self._session is None or self._session.closed:
            auth = None
            if self.username and self.password:
                auth = aiohttp.BasicAuth(self.username, self.password)
            
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            
            # Configure TCPConnector for ALB compatibility:
            # - keepalive_timeout < ALB idle timeout (default 60s) to avoid stale connections
            # - limit: max simultaneous connections in the pool
            # - enable_cleanup_closed: proactively clean up closed connections
            connector = aiohttp.TCPConnector(
                keepalive_timeout=15,
                limit=20,
                enable_cleanup_closed=True,
            )
            
            self._session = aiohttp.ClientSession(
                auth=auth,
                timeout=timeout,
                connector=connector,
                headers={'Content-Type': 'application/sparql-update'}
            )
            
            # Track the session for proper cleanup
            track_session(self._session)
        return self._session
    
    def _get_space_graph_uri(self, space_id: str, graph_id: str = "main") -> str:
        """Generate named graph URI for space and graph combination."""
        return f"urn:vitalgraph:space:{space_id}:graph:{graph_id}"
    
    def _get_space_uri(self, space_id: str) -> str:
        """Generate URI for VitalSegment representing the space."""
        return f"urn:vitalgraph:space:{space_id}"
    
    def _get_kgsegment_uri(self, space_id: str, graph_id: str = "main") -> str:
        """Generate URI for VitalSegment linking space to graph."""
        return f"urn:vitalgraph:kgsegment:{space_id}:{graph_id}"
    
    def _create_space_vital_segment(self, space_id: str) -> VitalSegment:
        """
        Create VitalSegment object for space metadata.
        
        Args:
            space_id: Space identifier
            
        Returns:
            VitalSegment configured for the space
        """
        vital_segment = VitalSegment()
        vital_segment.URI = self._get_space_uri(space_id)
        vital_segment.name = f"VitalGraph Space {space_id}"
        vital_segment.segmentID = space_id
        vital_segment.segmentGraphURI = None  # Space doesn't have a single graph URI
        vital_segment.segmentNamespace = "vitalgraph"
        vital_segment.segmentTenantID = None
        vital_segment.segmentGlobal = False
        vital_segment.segmentStateJSON = "[]"
        return vital_segment
    
    def _create_graph_kg_segment(self, space_id: str, graph_id: str, graph_name: str = None) -> KGSegment:
        """
        Create KGSegment object for graph metadata.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier within the space
            graph_name: Optional human-readable name for the graph
            
        Returns:
            KGSegment configured for the graph
        """
        kg_segment = KGSegment()
        kg_segment.URI = self._get_kgsegment_uri(space_id, graph_id)
        kg_segment.name = graph_name or f"Graph {graph_id}"
        kg_segment.vitalSegmentID = space_id  # Link to parent space
        kg_segment.kGSegmentGraphURI = self._get_space_graph_uri(space_id, graph_id)
        return kg_segment
    
    def _parse_vital_segments_from_sparql(self, sparql_results: Dict[str, Any]) -> List[VitalSegment]:
        """
        Parse VitalSegment objects from SPARQL SELECT results.
        
        Args:
            sparql_results: Raw SPARQL results from Fuseki
            
        Returns:
            List of VitalSegment objects
        """
        segments = []
        
        try:
            bindings = sparql_results.get('results', {}).get('bindings', [])
            
            for binding in bindings:
                vital_segment = VitalSegment()
                
                # Extract properties from SPARQL binding
                if 'uri' in binding:
                    vital_segment.URI = binding['uri']['value']
                
                if 'name' in binding:
                    vital_segment.name = binding['name']['value']
                
                if 'segmentID' in binding:
                    vital_segment.segmentID = binding['segmentID']['value']
                
                if 'segmentGraphURI' in binding:
                    vital_segment.segmentGraphURI = binding['segmentGraphURI']['value']
                
                if 'segmentNamespace' in binding:
                    vital_segment.segmentNamespace = binding['segmentNamespace']['value']
                
                if 'segmentTenantID' in binding:
                    vital_segment.segmentTenantID = binding['segmentTenantID']['value']
                
                if 'segmentGlobal' in binding:
                    vital_segment.segmentGlobal = binding['segmentGlobal']['value'].lower() == 'true'
                
                if 'segmentStateJSON' in binding:
                    vital_segment.segmentStateJSON = binding['segmentStateJSON']['value']
                else:
                    vital_segment.segmentStateJSON = "[]"
                
                segments.append(vital_segment)
                
        except Exception as e:
            self.logger.error(f"Error parsing VitalSegments from SPARQL results: {e}")
        
        return segments
    
    def _parse_kg_segments_from_sparql(self, sparql_results: Dict[str, Any]) -> List[KGSegment]:
        """
        Parse KGSegment objects from SPARQL SELECT results.
        
        Args:
            sparql_results: Raw SPARQL results from Fuseki
            
        Returns:
            List of KGSegment objects
        """
        segments = []
        
        try:
            bindings = sparql_results.get('results', {}).get('bindings', [])
            
            for binding in bindings:
                kg_segment = KGSegment()
                
                # Extract properties from SPARQL binding
                if 'uri' in binding:
                    kg_segment.URI = binding['uri']['value']
                
                if 'name' in binding:
                    kg_segment.name = binding['name']['value']
                
                if 'vitalSegmentID' in binding:
                    kg_segment.vitalSegmentID = binding['vitalSegmentID']['value']
                
                if 'kGSegmentGraphURI' in binding:
                    kg_segment.kGSegmentGraphURI = binding['kGSegmentGraphURI']['value']
                
                segments.append(kg_segment)
                
        except Exception as e:
            self.logger.error(f"Error parsing KGSegments from SPARQL results: {e}")
        
        return segments
    
    # ========================================
    # Space Infrastructure Initialization
    # ========================================
    
    async def _ensure_space_graph_initialized(self) -> bool:
        """
        Ensure the space-graph infrastructure is initialized.
        
        This creates the special space-graph that stores VitalSegment objects
        to track all spaces and their metadata. This only needs to be done once
        per Fuseki dataset.
        
        Returns:
            bool: True if initialized successfully
        """
        if self._space_graph_initialized:
            return True
            
        try:
            session = await self._get_session()
            
            # Check if space-graph already exists by querying for any VitalSegment
            check_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            ASK {{
                GRAPH <{self.space_graph_uri}> {{
                    ?s a vital:VitalSegment .
                }}
            }}
            """
            
            headers = {'Content-Type': 'application/sparql-query', 'Accept': 'application/sparql-results+json'}
            async with session.post(self.query_url, data=check_query, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    graph_exists = result.get('boolean', False)
                    
                    if not graph_exists:
                        # Initialize space-graph with basic structure
                        init_query = f"""
                        PREFIX vital: <http://vital.ai/ontology/vital#>
                        INSERT DATA {{
                            GRAPH <{self.space_graph_uri}> {{
                                <{self.space_graph_uri}> a vital:Graph ;
                                    vital:name "VitalGraph Space Registry" ;
                                    vital:hasCreatedTime "{datetime.now().isoformat()}" .
                            }}
                        }}
                        """
                        
                        headers = {'Content-Type': 'application/sparql-update'}
                        async with session.post(self.update_url, data=init_query, headers=headers) as response:
                            if response.status == 204:
                                self.logger.info(f"✅ Initialized space-graph infrastructure")
                                self._space_graph_initialized = True
                                return True
                            else:
                                error_text = await response.text()
                                self.logger.error(f"Failed to initialize space-graph: {response.status} - {error_text}")
                                return False
                    else:
                        self.logger.info(f"✅ Space-graph infrastructure already exists")
                        self._space_graph_initialized = True
                        return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to check space-graph existence: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error initializing space-graph infrastructure: {e}")
            return False
    
    # ========================================
    # Space Lifecycle Management
    # ========================================
    
    async def init_space_storage(self, space_id: str) -> bool:
        """
        Initialize storage for a space by creating metadata in space-graph.
        
        This creates VitalSegment objects in the special space-graph to track
        space metadata. Each space gets a VitalSegment with space information.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if space was initialized successfully
        """
        try:
            # First ensure the space-graph infrastructure is initialized
            if not await self._ensure_space_graph_initialized():
                self.logger.error(f"Failed to initialize space-graph infrastructure")
                return False
            
            space_uri = self._get_space_uri(space_id)
            session = await self._get_session()
            
            # Create SPARQL INSERT for VitalSegment with proper metadata
            insert_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            INSERT DATA {{
                GRAPH <{self.space_graph_uri}> {{
                    <{space_uri}> a vital:VitalSegment ;
                        vital:name "{space_id}" ;
                        vital:hasCreatedTime "{datetime.now().isoformat()}" ;
                        vital:hasSpaceID "{space_id}" .
                }}
            }}
            """
            
            headers = {'Content-Type': 'application/sparql-update'}
            async with session.post(self.update_url, data=insert_query, headers=headers) as response:
                if response.status == 204:  # SPARQL UPDATE returns 204 No Content on success
                    self.logger.info(f"✅ Initialized space storage: {space_id}")
                    
                    # Also create the default graph for this space
                    default_graph_uri = f"http://vital.ai/graph/{space_id}"
                    graph_init_query = f"""
                    PREFIX vital: <http://vital.ai/ontology/vital#>
                    INSERT DATA {{
                        GRAPH <{self.space_graph_uri}> {{
                            <{default_graph_uri}> a vital:Graph ;
                                vital:name "{space_id}_default" ;
                                vital:hasCreatedTime "{datetime.now().isoformat()}" ;
                                vital:belongsToSpace <{space_uri}> .
                        }}
                    }}
                    """
                    
                    async with session.post(self.update_url, data=graph_init_query, headers=headers) as graph_response:
                        if graph_response.status == 204:
                            self.logger.info(f"✅ Created default graph for space: {space_id}")
                        else:
                            self.logger.warning(f"Failed to create default graph for space {space_id}")
                    
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to initialize space {space_id}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error initializing space storage {space_id}: {e}")
            return False
    
    async def delete_space_storage(self, space_id: str) -> bool:
        """
        Delete storage for a space by removing all associated data.
        
        Removes:
        1. The default graph for the space
        2. VitalSegment metadata for the space
        3. Any associated graph metadata
        """
        try:
            space_uri = self._get_space_uri(space_id)
            session = await self._get_session()
            
            # Delete ALL graphs for this space (including subgraphs like /entities, /connections)
            space_graph_pattern = f"http://vital.ai/graph/{space_id}"
            
            # First, find all graphs that belong to this space
            find_graphs_query = f"""
            SELECT DISTINCT ?g WHERE {{
                GRAPH ?g {{ ?s ?p ?o }}
                FILTER(STRSTARTS(STR(?g), "{space_graph_pattern}"))
            }}
            """
            
            headers = {'Content-Type': 'application/sparql-query', 'Accept': 'application/sparql-results+json'}
            async with session.post(self.query_url, data=find_graphs_query, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    bindings = result.get('results', {}).get('bindings', [])
                    
                    # Delete each graph found
                    headers = {'Content-Type': 'application/sparql-update'}
                    for binding in bindings:
                        graph_uri = binding.get('g', {}).get('value')
                        if graph_uri:
                            delete_graph_query = f"DROP SILENT GRAPH <{graph_uri}>"
                            async with session.post(self.update_url, data=delete_graph_query, headers=headers) as del_response:
                                if del_response.status == 204:
                                    self.logger.info(f"✅ Deleted graph: {graph_uri}")
                                else:
                                    self.logger.warning(f"Failed to delete graph {graph_uri}: {del_response.status}")
                else:
                    self.logger.warning(f"Failed to find graphs for space {space_id}: {response.status}")
            
            # Delete space metadata from space-graph (split into separate operations)
            # First delete the space itself
            delete_space_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            DELETE WHERE {{
                GRAPH <{self.space_graph_uri}> {{
                    <{space_uri}> ?p ?o .
                }}
            }}
            """
            
            async with session.post(self.update_url, data=delete_space_query, headers=headers) as response:
                if response.status != 204:
                    error_text = await response.text()
                    self.logger.warning(f"Failed to delete space entity {space_id}: {response.status} - {error_text}")
            
            # Then delete any graphs that belong to this space
            delete_graphs_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            DELETE WHERE {{
                GRAPH <{self.space_graph_uri}> {{
                    ?graph vital:belongsToSpace <{space_uri}> .
                    ?graph ?p ?o .
                }}
            }}
            """
            
            async with session.post(self.update_url, data=delete_graphs_query, headers=headers) as response:
                if response.status == 204:
                    self.logger.info(f"✅ Deleted space metadata: {space_id}")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to delete space metadata {space_id}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error deleting space storage {space_id}: {e}")
            return False
    
    async def space_storage_exists(self, space_id: str) -> bool:
        """Check if storage exists for a space by querying space metadata."""
        try:
            space_uri = self._get_space_uri(space_id)
            session = await self._get_session()
            
            # Query for VitalSegment in space-graph
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            ASK {{
                GRAPH <{self.space_graph_uri}> {{
                    <{space_uri}> a vital:VitalSegment .
                }}
            }}
            """
            
            headers = {'Content-Type': 'application/sparql-query', 'Accept': 'application/sparql-results+json'}
            async with session.post(self.query_url, data=query, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('boolean', False)
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to check space existence {space_id}: {response.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error checking space existence {space_id}: {e}")
            return False
    
    # ========================================
    # SPARQL Support
    # ========================================
    
    def get_sparql_impl(self, space_id: str) -> SparqlBackendInterface:
        """Get cached SPARQL implementation for the space."""
        if space_id not in self._sparql_impl_cache:
            from .fuseki_sparql_impl import FusekiSparqlImpl
            self._sparql_impl_cache[space_id] = FusekiSparqlImpl(self, space_id)
        return self._sparql_impl_cache[space_id]
    
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """Execute a SPARQL query - delegates to SPARQL implementation."""
        sparql_impl = self.get_sparql_impl(space_id)
        return await sparql_impl.execute_sparql_query(space_id, sparql_query)
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """Execute a SPARQL update - delegates to SPARQL implementation."""
        sparql_impl = self.get_sparql_impl(space_id)
        return await sparql_impl.execute_sparql_update(space_id, sparql_update)
    
    # ========================================
    # Multiple Graph Support per Space
    # ========================================
    
    async def create_graph(self, space_id: str, graph_id: str, graph_name: str = None) -> bool:
        """
        Create a new graph within a space by adding VitalSegment metadata for the graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier within the space
            graph_name: Optional human-readable name for the graph
            
        Returns:
            True if graph was created successfully
        """
        try:
            # Check if space exists
            if not await self.space_storage_exists(space_id):
                self.logger.error(f"Cannot create graph - space {space_id} does not exist")
                return False
            
            # Check if graph already exists
            if await self.graph_exists(space_id, graph_id):
                self.logger.info(f"Graph {graph_id} already exists in space {space_id}")
                return True
            
            # Create KGSegment object for the graph
            kg_segment = self._create_graph_kg_segment(space_id, graph_id, graph_name)
            rdf_string = kg_segment.to_rdf()
            
            # Create graph metadata via SPARQL INSERT
            create_query = f"""
            INSERT DATA {{
                GRAPH <{self.space_graph_uri}> {{
                    {rdf_string}
                }}
            }}
            """
            
            session = await self._get_session()
            async with session.post(self.update_url, data=create_query) as response:
                if response.status == 200 or response.status == 204:
                    self.logger.info(f"Successfully created graph {graph_id} in space {space_id}")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to create graph {graph_id}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error creating graph {graph_id} in space {space_id}: {e}")
            return False
    
    async def delete_graph(self, space_id: str, graph_id: str) -> bool:
        """
        Delete a graph from a space by removing KGSegment metadata and graph data.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier within the space
            
        Returns:
            True if graph was deleted successfully
        """
        try:
            kgsegment_uri = self._get_kgsegment_uri(space_id, graph_id)
            graph_uri = self._get_space_graph_uri(space_id, graph_id)
            
            session = await self._get_session()
            
            # Delete the named graph data
            drop_graph_query = f"DROP GRAPH <{graph_uri}>"
            async with session.post(self.update_url, data=drop_graph_query) as response:
                if response.status not in [200, 204]:
                    self.logger.warning(f"Failed to drop graph data {graph_uri}: {response.status}")
            
            # Delete KGSegment metadata
            delete_metadata_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            DELETE WHERE {{
                GRAPH <{self.space_graph_uri}> {{
                    <{kgsegment_uri}> ?p ?o .
                }}
            }}
            """
            
            async with session.post(self.update_url, data=delete_metadata_query) as response:
                if response.status == 200 or response.status == 204:
                    self.logger.info(f"Successfully deleted graph {graph_id} from space {space_id}")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to delete graph metadata {graph_id}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error deleting graph {graph_id} from space {space_id}: {e}")
            return False
    
    async def list_graphs(self, space_id: str) -> List[Dict[str, Any]]:
        """
        List all graphs in a space by querying KGSegment objects for graphs.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of graph information dictionaries with KGSegment objects
        """
        try:
            # Get KGSegment objects for all graphs in the space
            graph_segments = await self.get_graph_kg_segments(space_id)
            graphs = []
            
            for segment in graph_segments:
                # Extract graph_id from graph URI
                graph_id = segment.kGSegmentGraphURI.split(':')[-1] if segment.kGSegmentGraphURI else "unknown"
                
                graph_info = {
                    'graph_id': graph_id,
                    'graph_uri': segment.kGSegmentGraphURI,
                    'name': segment.name or graph_id,
                    'kg_segment': segment  # Include the KGSegment object
                }
                graphs.append(graph_info)
            
            return graphs
                    
        except Exception as e:
            self.logger.error(f"Error listing graphs for space {space_id}: {e}")
            return []
    
    async def get_graph_kg_segments(self, space_id: str) -> List[KGSegment]:
        """Get KGSegment objects for all graphs in a space."""
        try:
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?uri ?name ?vitalSegmentID ?kGSegmentGraphURI WHERE {{
                GRAPH <{self.space_graph_uri}> {{
                    ?uri a haley:KGSegment ;
                        haley:vitalSegmentID "{space_id}" .
                    OPTIONAL {{ ?uri vital:hasName ?name }}
                    OPTIONAL {{ ?uri haley:kGSegmentGraphURI ?kGSegmentGraphURI }}
                }}
            }}
            ORDER BY ?name
            """
            
            session = await self._get_session()
            async with session.post(self.query_url, 
                                  data=query,
                                  headers={'Accept': 'application/sparql-results+json'}) as response:
                if response.status == 200:
                    result_data = await response.json()
                    return self._parse_kg_segments_from_sparql(result_data)
                else:
                    self.logger.error(f"Failed to get graph segments: {response.status}")
                    return []
                    
        except Exception as e:
            self.logger.error(f"Error getting graph segments: {e}")
            return []
    
    async def graph_exists(self, space_id: str, graph_id: str) -> bool:
        """
        Check if a specific graph exists in a space.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier within the space
            
        Returns:
            True if graph exists
        """
        try:
            kgsegment_uri = self._get_kgsegment_uri(space_id, graph_id)
            graph_uri = self._get_space_graph_uri(space_id, graph_id)
            
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            ASK {{
                GRAPH <{self.space_graph_uri}> {{
                    <{kgsegment_uri}> a haley:KGSegment ;
                        haley:vitalSegmentID "{space_id}" ;
                        haley:kGSegmentGraphURI <{graph_uri}> .
                }}
            }}
            """
            
            session = await self._get_session()
            async with session.post(self.query_url, 
                                  data=query,
                                  headers={'Accept': 'application/sparql-results+json'}) as response:
                if response.status == 200:
                    result_data = await response.json()
                    return result_data.get('boolean', False)
                else:
                    self.logger.error(f"Failed to check graph existence: {response.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error checking graph existence: {e}")
            return False
    
    # ========================================
    # Connection Management
    # ========================================
    
    @asynccontextmanager
    async def get_db_connection(self):
        """Async context manager for HTTP session management (SpaceBackendInterface method)."""
        session = await self._get_session()
        try:
            yield session
        finally:
            # Keep session open for reuse
            pass
    
    @asynccontextmanager
    async def get_backend_connection(self):
        """Async context manager for HTTP session management."""
        session = await self._get_session()
        try:
            yield session
        finally:
            # Keep session open for reuse
            pass
    
    async def close(self):
        """Close HTTP session and cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Give time for the session to fully close
            import asyncio
            await asyncio.sleep(0.1)
            self._session = None
        self.logger.info("Fuseki space implementation closed")
    
    # ========================================
    # Placeholder Methods (Minimal Implementation)
    # ========================================
    
    # Most methods delegate to SPARQL operations or are not applicable to Fuseki
    
    async def list_spaces(self) -> List[str]:
        """List all spaces by querying VitalSegment objects."""
        try:
            # Get VitalSegment objects for all spaces
            space_segments = await self.get_space_vital_segments()
            return [str(segment.segmentID) for segment in space_segments if segment.segmentID]
                    
        except Exception as e:
            self.logger.error(f"Error listing spaces: {e}")
            return []
    
    async def get_space_vital_segments(self) -> List[VitalSegment]:
        """Get VitalSegment objects for all spaces."""
        try:
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?uri ?name ?segmentID ?segmentGraphURI ?segmentNamespace ?segmentTenantID ?segmentGlobal ?segmentStateJSON WHERE {{
                GRAPH <{self.space_graph_uri}> {{
                    ?uri a vital:VitalSegment ;
                        vital:hasSegmentID ?segmentID .
                    OPTIONAL {{ ?uri vital:hasName ?name }}
                    OPTIONAL {{ ?uri vital:segmentGraphURI ?segmentGraphURI }}
                    OPTIONAL {{ ?uri vital:segmentNamespace ?segmentNamespace }}
                    OPTIONAL {{ ?uri vital:segmentTenantID ?segmentTenantID }}
                    OPTIONAL {{ ?uri vital:segmentGlobal ?segmentGlobal }}
                    OPTIONAL {{ ?uri vital:segmentStateJSON ?segmentStateJSON }}
                    # Filter for space segments (not graph segments)
                    FILTER(!BOUND(?segmentTenantID) || ?segmentTenantID = "")
                }}
            }}
            ORDER BY ?segmentID
            """
            
            session = await self._get_session()
            headers = {
                'Content-Type': 'application/sparql-query',
                'Accept': 'application/sparql-results+json'
            }
            async with session.post(self.query_url, data=query, headers=headers) as response:
                if response.status == 200:
                    result_data = await response.json()
                    return self._parse_vital_segments_from_sparql(result_data)
                else:
                    self.logger.error(f"Failed to get space segments: {response.status}")
                    return []
                    
        except Exception as e:
            self.logger.error(f"Error getting space segments: {e}")
            return []
    
    async def get_space_info(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Get space information from VitalSegment metadata."""
        try:
            space_uri = self._get_space_uri(space_id)
            
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?name ?created ?active WHERE {{
                GRAPH <{self.space_graph_uri}> {{
                    <{space_uri}> a vital:VitalSegment ;
                        vital:hasSegmentID "{space_id}" ;
                        vital:hasName ?name ;
                        vital:hasCreatedDate ?created ;
                        vital:isActive ?active .
                }}
            }}
            """
            
            session = await self._get_session()
            headers = {
                'Content-Type': 'application/sparql-query',
                'Accept': 'application/sparql-results+json'
            }
            async with session.post(self.query_url, data=query, headers=headers) as response:
                if response.status == 200:
                    result_data = await response.json()
                    bindings = result_data.get('results', {}).get('bindings', [])
                    if bindings:
                        binding = bindings[0]
                        return {
                            'space_id': space_id,
                            'name': binding.get('name', {}).get('value', space_id),
                            'created_date': binding.get('created', {}).get('value'),
                            'is_active': binding.get('active', {}).get('value', 'true') == 'true'
                        }
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting space info {space_id}: {e}")
            return None
    
    # Minimal implementations for interface compliance
    async def add_term(self, space_id: str, term: Identifier) -> str:
        """Terms are handled directly in RDF - return term string."""
        return str(term)
    
    async def get_term_uuid(self, space_id: str, term: Identifier) -> Optional[str]:
        """Terms are handled directly in RDF - return term string."""
        return str(term)
    
    async def delete_term(self, space_id: str, term_uuid: str) -> bool:
        """Terms are managed automatically in RDF."""
        return True
    
    async def add_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, 
                      object_uuid: str, graph_uuid: str) -> bool:
        """Use SPARQL UPDATE for quad operations."""
        # This would be implemented via SPARQL UPDATE
        return True
    
    async def remove_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str,
                         object_uuid: str, graph_uuid: str) -> bool:
        """Use SPARQL UPDATE for quad operations."""
        # This would be implemented via SPARQL UPDATE  
        return True
    
    async def get_quad_count(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """Get quad count via SPARQL query."""
        try:
            session = await self._get_session()
            
            if graph_uri:
                query = f"""
                SELECT (COUNT(*) AS ?count) WHERE {{
                    GRAPH <{graph_uri}> {{
                        ?s ?p ?o .
                    }}
                }}
                """
            else:
                # Count all quads in ALL graphs related to this space (including subgraphs)
                space_graph_pattern = f"http://vital.ai/graph/{space_id}"
                query = f"""
                SELECT (COUNT(*) AS ?count) WHERE {{
                    GRAPH ?g {{
                        ?s ?p ?o .
                        FILTER(STRSTARTS(STR(?g), "{space_graph_pattern}"))
                    }}
                }}
                """
            
            headers = {'Content-Type': 'application/sparql-query', 'Accept': 'application/sparql-results+json'}
            async with session.post(self.query_url, data=query, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    bindings = result.get('results', {}).get('bindings', [])
                    if bindings:
                        count_value = bindings[0].get('count', {}).get('value', '0')
                        return int(count_value)
                    return 0
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to get quad count: {response.status} - {error_text}")
                    return 0
                
        except Exception as e:
            self.logger.error(f"Error getting quad count: {e}")
            return 0
    
    # Namespace operations via SPARQL
    async def add_namespace(self, space_id: str, prefix: str, namespace_uri: str) -> bool:
        """Namespaces handled at SPARQL level."""
        return True
    
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """Namespaces handled at SPARQL level."""
        return None
    
    async def list_namespaces(self, space_id: str) -> Dict[str, str]:
        """Namespaces handled at SPARQL level."""
        return {}
    
    # Bulk operations not applicable to HTTP API
    async def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        """Not applicable to Fuseki."""
        return True
    
    async def recreate_indexes_after_bulk_load(self, space_id: str, concurrent: bool = True) -> bool:
        """Not applicable to Fuseki."""
        return True
    
    # Connection stats not applicable
    def get_pool_stats(self) -> Dict[str, Any]:
        """HTTP session stats."""
        return {
            'backend_type': 'fuseki',
            'server_url': self.server_url,
            'dataset_name': self.dataset_name,
            'session_closed': self._session is None or self._session.closed if self._session else True
        }
    
    async def close_pool(self):
        """Close HTTP session."""
        await self.close()
    
    # RDF operations delegate to SPARQL
    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list]) -> bool:
        """Add RDF quad via SPARQL UPDATE."""
        try:
            subject, predicate, obj, graph = quad
            
            # Format RDF terms for SPARQL
            def format_rdf_term(term):
                if hasattr(term, 'n3'):
                    return term.n3()
                return f'<{term}>'
            
            subject_str = format_rdf_term(subject)
            predicate_str = format_rdf_term(predicate)
            object_str = format_rdf_term(obj)
            graph_str = format_rdf_term(graph)
            
            # Create SPARQL INSERT DATA query
            sparql_update = f"""
            INSERT DATA {{
                GRAPH {graph_str} {{
                    {subject_str} {predicate_str} {object_str} .
                }}
            }}
            """
            
            session = await self._get_session()
            headers = {
                'Content-Type': 'application/sparql-update',
                'Accept': 'application/json'
            }
            
            async with session.post(self.update_url, data=sparql_update, headers=headers) as response:
                if response.status == 204:  # No Content - successful update
                    return True
                else:
                    self.logger.error(f"Failed to add RDF quad: HTTP {response.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error adding RDF quad: {e}")
            return False

    async def add_rdf_quads_bulk(self, space_id: str, quads: list, batch_size: int = 100) -> int:
        """Add multiple RDF quads in batches using SPARQL INSERT DATA.
        
        Args:
            space_id: Space identifier
            quads: List of (subject, predicate, object, graph) tuples
            batch_size: Number of quads to insert per batch
            
        Returns:
            Number of quads successfully inserted
        """
        try:
            def format_rdf_term(term):
                if hasattr(term, 'n3'):
                    return term.n3()
                return f'<{term}>'
            
            total_inserted = 0
            
            # Process quads in batches
            for i in range(0, len(quads), batch_size):
                batch = quads[i:i + batch_size]
                
                # Group quads by graph for efficient insertion
                graph_quads = {}
                for subject, predicate, obj, graph in batch:
                    graph_str = format_rdf_term(graph)
                    if graph_str not in graph_quads:
                        graph_quads[graph_str] = []
                    
                    subject_str = format_rdf_term(subject)
                    predicate_str = format_rdf_term(predicate)
                    object_str = format_rdf_term(obj)
                    
                    graph_quads[graph_str].append(f"{subject_str} {predicate_str} {object_str} .")
                
                # Create SPARQL INSERT DATA query for this batch
                graph_blocks = []
                for graph_str, triples in graph_quads.items():
                    triples_str = "\n                    ".join(triples)
                    graph_blocks.append(f"""
                GRAPH {graph_str} {{
                    {triples_str}
                }}""")
                
                sparql_update = f"""
            INSERT DATA {{
                {" ".join(graph_blocks)}
            }}
            """
                
                session = await self._get_session()
                headers = {
                    'Content-Type': 'application/sparql-update',
                    'Accept': 'application/json'
                }
                
                async with session.post(self.update_url, data=sparql_update, headers=headers) as response:
                    if response.status == 204:  # No Content - successful update
                        total_inserted += len(batch)
                    else:
                        self.logger.error(f"Failed to insert batch {i//batch_size + 1}: HTTP {response.status}")
                        break
            
            return total_inserted
                    
        except Exception as e:
            self.logger.error(f"Error adding RDF quads in bulk: {e}")
            return 0
    
    async def remove_rdf_quad(self, space_id: str, subject: Identifier, predicate: Identifier,
                             obj: Identifier, graph_uri: Optional[str] = None) -> bool:
        """Remove RDF quad via SPARQL UPDATE."""
        # Implementation would use SPARQL DELETE DATA
        return True
    
    async def get_rdf_quad(self, space_id: str, subject: Optional[Identifier] = None,
                          predicate: Optional[Identifier] = None, obj: Optional[Identifier] = None,
                          graph_uri: Optional[str] = None) -> List[Tuple[Identifier, Identifier, Identifier, str]]:
        """Get RDF quads via SPARQL SELECT."""
        # Implementation would use SPARQL SELECT
        return []
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, str]]) -> bool:
        """Add RDF quads batch via SPARQL UPDATE."""
        # Implementation would use SPARQL INSERT DATA with multiple triples
        return True
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, str]]) -> bool:
        """Remove RDF quads batch via SPARQL UPDATE."""
        # Implementation would use SPARQL DELETE DATA with multiple triples
        return True
    
    async def quads(self, space_id: str, graph_uri: Optional[str] = None) -> AsyncGenerator[Tuple[Identifier, Identifier, Identifier, str], None]:
        """Stream RDF quads via SPARQL SELECT."""
        # Implementation would use SPARQL SELECT with streaming
        return
        yield  # Make this a generator
    
    async def get_rdf_quad_count(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """Get RDF quad count - same as get_quad_count."""
        return await self.get_quad_count(space_id, graph_uri)
    
    # SpaceBackendInterface adapter methods
    async def create_space_storage(self, space_id: str) -> bool:
        """Create space storage - adapter for SpaceBackendInterface."""
        return await self.init_space_storage(space_id)
    
    async def space_exists(self, space_id: str) -> bool:
        """Check if space exists - adapter for SpaceBackendInterface."""
        return await self.space_storage_exists(space_id)
    
    def get_manager_info(self) -> Dict[str, Any]:
        """Get manager info - adapter for SpaceBackendInterface."""
        return {
            'backend_type': 'fuseki',
            'server_url': self.server_url,
            'dataset_name': self.dataset_name,
            'session_closed': self._session is None or self._session.closed if self._session else True
        }