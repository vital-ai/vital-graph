from typing import List, TypeVar, Optional
import logging
from vital_ai_vitalsigns.service.graph.graph_service import VitalGraphService
from vital_ai_vitalsigns.service.graph.graph_service_status import GraphServiceStatus
from vital_ai_vitalsigns.service.vital_name_graph import VitalNameGraph
from vital_ai_vitalsigns.service.graph.vital_graph_status import VitalGraphStatus
from vital_ai_vitalsigns.query.result_list import ResultList
from vital_ai_vitalsigns.query.solution_list import SolutionList
from vital_ai_vitalsigns.query.metaql_result import MetaQLResult
from vital_ai_vitalsigns.metaql.metaql_query import SelectQuery as MetaQLSelectQuery
from vital_ai_vitalsigns.metaql.metaql_query import GraphQuery as MetaQLGraphQuery
from vital_ai_vitalsigns.service.graph.binding import Binding
from vital_ai_vitalsigns.service.graph.graph_object_generator import GraphObjectGenerator
from vital_ai_vitalsigns.ontology.ontology import Ontology
from vital_ai_vitalsigns.service.graph.graph_service_constants import VitalGraphServiceConstants
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
from vital_ai_vitalsigns_core.model.VitalSegment import VitalSegment

# Import VitalGraphClient for backend operations
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError

G = TypeVar('G', bound='GraphObject')


class VitalGraphServiceImpl(VitalGraphService):
    """
    VitalGraph service implementation providing graph operations and management.
    
    This implementation follows the VitalGraphService interface exactly,
    providing all the required methods for graph management, object operations,
    and SPARQL/MetaQL query execution.
    """
    
    def _strip_angle_brackets(self, uri_text: str) -> str:
        """
        Strip angle brackets from URI text if present.
        
        Args:
            uri_text: URI text that may have angle brackets
            
        Returns:
            Clean URI text without angle brackets
        """
        if uri_text.startswith('<') and uri_text.endswith('>'):
            return uri_text[1:-1]
        return uri_text
    
    def __init__(self, space_id: str = None, **kwargs):
        """
        Initialize the VitalGraph service implementation.
        
        Configuration is loaded from profile-prefixed environment variables.
        Set VITALGRAPH_CLIENT_ENVIRONMENT to select profile (local, dev, staging, prod).
        
        Args:
            space_id: Fixed space ID for all operations (constant throughout service lifetime)
            **kwargs: Additional configuration parameters
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Store fixed space_id for all client operations
        self.space_id = space_id
        if not space_id:
            raise ValueError("space_id is required for VitalGraphServiceImpl")
        
        # Initialize VitalGraphClient from environment variables
        self.client: Optional[VitalGraphClient] = None
        
        try:
            self.client = VitalGraphClient()
            self.logger.info("VitalGraphClient initialized from environment variables")
        except VitalGraphClientError as e:
            self.logger.error(f"Failed to initialize VitalGraphClient: {e}")
            raise
        
        self.logger.info(f"VitalGraphServiceImpl initialized with space_id: {space_id}")
    
    # Service Management Methods
    def service_status(self) -> GraphServiceStatus:
        """
        Get the current status of the graph service.
        
        Returns:
            GraphServiceStatus indicating the current service state
        """
        self.logger.info("Getting service status")
        
        if not self.client:
            return GraphServiceStatus.OFFLINE
        
        try:
            if self.client.is_connected():
                return GraphServiceStatus.ONLINE
            else:
                return GraphServiceStatus.OFFLINE
        except Exception as e:
            self.logger.error(f"Error checking service status: {e}")
            return GraphServiceStatus.ERROR
    
    def service_info(self):
        """
        Get information about the graph service.
        
        Returns:
            Service information
        """
        self.logger.info("Getting service info")
        
        info = {
            "service_name": "VitalGraphServiceImpl",
            "client_initialized": self.client is not None,
            "client_connected": self.client.is_connected() if self.client else False,
            "config_path": self.config_path
        }
        
        if self.client:
            try:
                server_info = self.client.get_server_info()
                info.update({"server_info": server_info})
            except Exception as e:
                self.logger.warning(f"Could not retrieve server info: {e}")
                info["server_info_error"] = str(e)
        
        return info
    
    def initialize_service(self):
        """
        Initialize the graph service.
        
        Returns:
            Initialization result
        """
        self.logger.info(f"Initializing graph service with namespace: {self.namespace}")
        self.logger.info(f"Initializing graph service with base uri: {self.base_uri}")
        
        try:
            self._ensure_client_connected()
            
            service_graph_uri = self._get_service_graph_uri()
            self.logger.info(f"Service graph URI: {service_graph_uri}")
            
            # Check if service graph already exists
            if self._check_graph_exists(service_graph_uri):
                self.logger.info(f"Service graph already exists: {service_graph_uri}")
                return {"success": False, "error": "Service already initialized"}
            
            # Check for graphs that include the namespace (conflict detection)
            namespace_prefix = f"{self.base_uri}/{self.namespace}"
            existing_graphs = self._list_all_graph_uris()
            
            for graph_uri in existing_graphs:
                if graph_uri.startswith(namespace_prefix):
                    self.logger.info(f"Graph URI with prefix {namespace_prefix} exists: {graph_uri}")
                    return {"success": False, "error": f"Conflicting graph exists: {graph_uri}"}
            
            # Create service graph with VitalSegment metadata
            vital_segment = self._create_service_vital_segment()
            rdf_string = vital_segment.to_rdf()
            
            self.logger.info(f"Creating service graph with metadata: {rdf_string[:200]}...")
            
            # Insert service graph metadata using SPARQL INSERT DATA
            insert_query = f"""
            INSERT DATA {{
                GRAPH <{service_graph_uri}> {{
                    {rdf_string}
                }}
            }}
            """
            
            result = self.client.execute_sparql_insert(self.space_id, insert_query)
            
            self.logger.info(f"Service graph initialized: {service_graph_uri}")
            return {"success": True, "message": "Service initialized successfully"}
            
        except Exception as e:
            error_msg = f"Failed to initialize service: {e}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
    
    def destroy_service(self):
        """
        Destroy/cleanup the graph service.
        
        Returns:
            Destruction result
        """
        self.logger.info("Destroying graph service")
        
        try:
            self._ensure_client_connected()
            
            service_graph_uri = self._get_service_graph_uri()
            
            # Query service graph for all managed graphs
            managed_graphs = self._query_all_managed_graphs()
            
            # Delete all managed graphs
            deleted_graphs = []
            for graph_info in managed_graphs:
                graph_uri = graph_info.get('graphURI')
                if graph_uri and graph_uri != service_graph_uri:
                    try:
                        self._delete_graph_by_uri(graph_uri)
                        deleted_graphs.append(graph_uri)
                        self.logger.info(f"Deleted managed graph: {graph_uri}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete graph {graph_uri}: {e}")
            
            # Delete service graph last
            self._delete_graph_by_uri(service_graph_uri)
            self.logger.info(f"Deleted service graph: {service_graph_uri}")
            
            # Close client connection
            if self.client and self.client.is_connected():
                self.client.close()
                self.logger.info("VitalGraphClient connection closed")
            
            return {
                "success": True, 
                "message": "Service destroyed successfully",
                "deleted_graphs": deleted_graphs
            }
            
        except Exception as e:
            error_msg = f"Failed to destroy service: {e}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
    
    # Helper Methods for Client Operations
    def _ensure_client_connected(self):
        """
        Ensure the VitalGraphClient is connected.
        
        Raises:
            VitalGraphClientError: If client is not available or cannot connect
        """
        self.logger.debug("Ensuring client is connected")
        
        if not self.client:
            raise VitalGraphClientError("VitalGraphClient not initialized")
        
        if not self.client.is_connected():
            raise VitalGraphClientError("VitalGraphClient not connected")
        
        self.logger.debug("Client connection verified")
    
    def _get_service_graph_uri(self) -> str:
        """
        Get the service graph URI for metadata storage.
        
        Returns:
            Service graph URI string
        """
        return f"{self.base_uri}/{self.namespace}/{VitalGraphServiceConstants.SERVICE_GRAPH_ID}"
    
    def _get_graph_uri(self, graph_id: str, account_id: str, global_graph: bool) -> str:
        """
        Build graph URI from parameters using documented naming conventions.
        
        Args:
            graph_id: Graph identifier
            account_id: Account identifier
            global_graph: Whether this is a global graph
            
        Returns:
            Complete graph URI string
        """
        if global_graph:
            return f"{self.base_uri}/GLOBAL/{graph_id}"
        else:
            return f"{self.base_uri}/{account_id}/{graph_id}"
    
    def _create_service_vital_segment(self) -> VitalSegment:
        """
        Create VitalSegment metadata object for service graph tracking.
        
        Returns:
            VitalSegment configured for service graph
        """
        vital_segment = VitalSegment()
        vital_segment.URI = URIGenerator.generate_uri()
        vital_segment.name = VitalGraphServiceConstants.SERVICE_GRAPH_ID
        vital_segment.segmentNamespace = self.namespace
        vital_segment.segmentGraphURI = self._get_service_graph_uri()
        vital_segment.segmentID = VitalGraphServiceConstants.SERVICE_GRAPH_ID
        vital_segment.segmentTenantID = None
        vital_segment.segmentGlobal = False
        vital_segment.segmentStateJSON = "[]"
        return vital_segment
    
    def _create_graph_vital_segment(self, graph_id: str, account_id: str, global_graph: bool) -> VitalSegment:
        """
        Create VitalSegment metadata object for graph tracking.
        
        Args:
            graph_id: Graph identifier
            account_id: Account identifier
            global_graph: Whether this is a global graph
            
        Returns:
            VitalSegment configured for the specified graph
        """
        vital_segment = VitalSegment()
        vital_segment.URI = URIGenerator.generate_uri()
        vital_segment.name = graph_id
        vital_segment.segmentNamespace = self.namespace
        vital_segment.segmentID = graph_id
        vital_segment.segmentTenantID = account_id
        vital_segment.segmentGlobal = global_graph
        vital_segment.segmentGraphURI = self._get_graph_uri(graph_id, account_id, global_graph)
        return vital_segment
    
    def _check_graph_exists(self, graph_uri: str) -> bool:
        """
        Check if a graph exists using ASK query.
        
        Args:
            graph_uri: URI of the graph to check
            
        Returns:
            True if graph exists, False otherwise
        """
        self._ensure_client_connected()
        
        query = f"""
        ASK WHERE {{
            GRAPH <{graph_uri}> {{ ?s ?p ?o }}
        }}
        """
        
        try:
            result = self.client.execute_sparql_query(self.space_id, query)
            return result.get("boolean", False)
        except VitalGraphClientError as e:
            self.logger.error(f"Error checking graph existence for {graph_uri}: {e}")
            return False
    
    def _check_object_exists_in_graph(self, graph_uri: str, object_uri: str) -> bool:
        """
        Check if a specific object exists in a graph.
        
        Args:
            graph_uri: URI of the graph to check
            object_uri: URI of the object to check
            
        Returns:
            True if object exists in the graph, False otherwise
        """
        try:
            query = f"""
            ASK WHERE {{
                GRAPH <{graph_uri}> {{
                    <{object_uri}> ?p ?o .
                }}
            }}
            """
            
            result = self.client.execute_sparql_query(self.space_id, query)
            return result.get("boolean", False)
            
        except Exception as e:
            self.logger.error(f"Error checking object existence for {object_uri} in graph {graph_uri}: {e}")
            return False
    
    def _sparql_results_to_triples(self, sparql_result: dict) -> List[tuple]:
        """
        Convert SPARQL query results to RDF triples format.
        
        Args:
            sparql_result: SPARQL query result dictionary
            
        Returns:
            List of RDF triples as tuples (subject, predicate, object)
        """
        triples = []
        
        try:
            if "results" in sparql_result and "bindings" in sparql_result["results"]:
                bindings = sparql_result["results"]["bindings"]
                
                for binding in bindings:
                    # Extract subject, predicate, object from binding
                    if "s" in binding and "p" in binding and "o" in binding:
                        subject = binding["s"]["value"]
                        predicate = binding["p"]["value"]
                        obj = binding["o"]["value"]
                        
                        # Create tuple for triple
                        triple = (subject, predicate, obj)
                        triples.append(triple)
                        
            self.logger.debug(f"Converted {len(triples)} SPARQL bindings to triples")
            return triples
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL results to triples: {e}")
            return []
    
    def _get_object_list_internal(self, object_uri_list: List[str], graph_id: str, 
                                 global_graph: bool = False, account_id: str | None = None) -> ResultList:
        """
        Internal helper to get multiple objects by URI list.
        
        Args:
            object_uri_list: List of object URIs to retrieve
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            
        Returns:
            ResultList containing the retrieved objects
        """
        result_list = ResultList()
        
        try:
            for object_uri in object_uri_list:
                try:
                    graph_object = self.get_object(
                        object_uri=object_uri,
                        graph_id=graph_id,
                        global_graph=global_graph,
                        account_id=account_id,
                        safety_check=False  # Skip safety checks for performance
                    )
                    
                    if graph_object:
                        result_list.add_result(graph_object)
                    else:
                        self.logger.debug(f"Object {object_uri} not found or could not be retrieved")
                        
                except Exception as e:
                    self.logger.warning(f"Failed to retrieve object {object_uri}: {e}")
                    # Continue with other objects
                    
            self.logger.info(f"Retrieved {len(result_list.results)} objects out of {len(object_uri_list)} requested")
            return result_list
            
        except Exception as e:
            self.logger.error(f"Error in _get_object_list_internal: {e}")
            return ResultList()
    
    def _list_all_graph_uris(self) -> List[str]:
        """
        List all graph URIs in the space using client.list_graphs().
        
        Returns:
            List of graph URI strings
        """
        self._ensure_client_connected()
        
        try:
            graphs = self.client.list_graphs(self.space_id)
            return graphs if graphs else []
        except VitalGraphClientError as e:
            self.logger.error(f"Error listing graphs: {e}")
            return []
    
    def _query_all_managed_graphs(self) -> List[dict]:
        """
        Query service graph for all managed graph metadata.
        
        Returns:
            List of dictionaries containing graph metadata
        """
        self._ensure_client_connected()
        
        service_graph_uri = self._get_service_graph_uri()
        
        query = f"""
        SELECT DISTINCT ?graphID ?graphURI ?isGlobal ?accountId WHERE {{
            GRAPH <{service_graph_uri}> {{
                ?s <http://vital.ai/ontology/vital-core#hasSegmentNamespace> "{self.namespace}"^^xsd:string .
                ?s <http://vital.ai/ontology/vital-core#hasSegmentID> ?graphID .
                ?s <http://vital.ai/ontology/vital-core#hasSegmentGraphURI> ?graphURI .
                ?s <http://vital.ai/ontology/vital-core#isSegmentGlobal> ?isGlobal .
                OPTIONAL {{ ?s <http://vital.ai/ontology/vital-core#hasSegmentTenantID> ?accountId }}
                ?s <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/vital-core#VitalSegment> .
            }}
        }}
        ORDER BY ?graphID
        """
        
        try:
            result = self.client.execute_sparql_query(self.space_id, query)
            graphs = []
            
            if result and "results" in result and "bindings" in result["results"]:
                for binding in result["results"]["bindings"]:
                    graph_info = {
                        "graphID": binding.get("graphID", {}).get("value"),
                        "graphURI": binding.get("graphURI", {}).get("value"),
                        "isGlobal": binding.get("isGlobal", {}).get("value") == "true",
                        "accountId": binding.get("accountId", {}).get("value")
                    }
                    graphs.append(graph_info)
            
            return graphs
        except VitalGraphClientError as e:
            self.logger.error(f"Error querying managed graphs: {e}")
            return []
    
    def _delete_graph_by_uri(self, graph_uri: str) -> bool:
        """
        Delete a graph by URI using SPARQL DROP and remove its metadata.
        
        Args:
            graph_uri: URI of the graph to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        self._ensure_client_connected()
        
        try:
            # Use SPARQL DROP to delete the graph and its triples
            drop_query = f"DROP GRAPH <{graph_uri}>"
            self.client.execute_sparql_update(self.space_id, drop_query)
            
            # Remove metadata from service graph
            service_graph_uri = self._get_service_graph_uri()
            delete_metadata_query = f"""
            DELETE {{
                GRAPH <{service_graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{service_graph_uri}> {{
                    ?s <http://vital.ai/ontology/vital-core#hasSegmentGraphURI> "{graph_uri}" ;
                       <http://vital.ai/ontology/vital-core#hasSegmentNamespace> "{self.namespace}" ;
                       ?p ?o .
                }}
            }}
            """
            
            self.client.execute_sparql_delete(self.space_id, delete_metadata_query)
            
            self.logger.info(f"Graph and metadata deleted successfully: {graph_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting graph {graph_uri}: {e}")
            return False
    

    
    # Graph Management Methods
    def is_graph_global(self, graph_id: str, *, account_id: str | None = None) -> bool:
        """
        Check if a graph is global.
        
        Args:
            graph_id: Graph identifier
            account_id: Optional account ID
            
        Returns:
            True if graph is global, False otherwise
        """
        self.logger.info(f"Checking if graph is global: {graph_id}")
        
        try:
            self._ensure_client_connected()
            
            # Validate graph_id parameter
            if not graph_id or not isinstance(graph_id, str):
                self.logger.warning(f"Invalid graph_id: {graph_id}")
                return False
            
            # Use the service's fixed space_id for client operations
            space_id = self.space_id
            
            # Get all graphs from the space
            existing_graphs = self.client.list_graphs(space_id)
            
            # Handle different response formats from client
            if isinstance(existing_graphs, dict) and "graphs" in existing_graphs:
                graph_list = existing_graphs["graphs"]
            elif isinstance(existing_graphs, list):
                graph_list = existing_graphs
            else:
                self.logger.warning(f"Unexpected response format from list_graphs: {type(existing_graphs)}")
                return False
            
            # Check both possible URIs (global and private) to see which one exists
            global_uri = self._build_graph_uri(graph_id, True, account_id)
            private_uri = self._build_graph_uri(graph_id, False, account_id)
            
            # Determine which URI exists and return accordingly
            global_exists = global_uri in graph_list
            private_exists = private_uri in graph_list
            
            if global_exists and private_exists:
                self.logger.warning(f"Both global and private versions of graph {graph_id} exist")
                # If both exist, prefer global (this shouldn't normally happen)
                return True
            elif global_exists:
                self.logger.info(f"Graph {graph_id} is global")
                return True
            elif private_exists:
                self.logger.info(f"Graph {graph_id} is private")
                return False
            else:
                self.logger.warning(f"Graph {graph_id} does not exist")
                return False
            
        except Exception as e:
            self.logger.error(f"Error checking if graph is global: {e}")
            return False
    
    def check_create_graph(self, graph_id: str, *, global_graph: bool = False,
                          account_id: str | None = None, safety_check: bool = True) -> bool:
        """
        Check if a graph can be created.
        
        Args:
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            True if graph can be created, False otherwise
        """
        self.logger.info(f"Checking if graph can be created: {graph_id} (global={global_graph})")
        
        try:
            self._ensure_client_connected()
            
            # Validate graph_id parameter
            if not graph_id or not isinstance(graph_id, str):
                self.logger.warning(f"Invalid graph_id: {graph_id}")
                return False
            
            # Generate the graph URI to check
            graph_uri = self._build_graph_uri(graph_id, global_graph, account_id)
            
            # Use the service's fixed space_id for client operations
            space_id = self.space_id
            
            # Check if graph already exists
            existing_graphs = self.client.list_graphs(space_id)
            
            # Handle different response formats from client
            if isinstance(existing_graphs, dict) and "graphs" in existing_graphs:
                graph_list = existing_graphs["graphs"]
            elif isinstance(existing_graphs, list):
                graph_list = existing_graphs
            else:
                self.logger.warning(f"Unexpected response format from list_graphs: {type(existing_graphs)}")
                graph_list = []
            
            # Check if the graph URI already exists
            if graph_uri in graph_list:
                self.logger.info(f"Graph {graph_uri} already exists, cannot create")
                return False
            
            # Additional safety checks if requested
            if safety_check:
                # Check for valid account_id if not global
                if not global_graph and not account_id:
                    self.logger.warning("Private graph requires account_id")
                    return False
                
                # Check for valid graph_id format (basic validation)
                if not graph_id.replace('_', '').replace('-', '').isalnum():
                    self.logger.warning(f"Graph ID contains invalid characters: {graph_id}")
                    return False
            
            self.logger.info(f"Graph {graph_uri} can be created")
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking if graph can be created: {e}")
            return False
    
    def list_graph_uris(self, *, safety_check: bool = True) -> List[str]:
        """
        List all graph URIs in the service.
        
        Args:
            safety_check: Whether to perform safety checks
            
        Returns:
            List of graph URI strings
        """
        self.logger.info("Listing graph URIs")
        
        try:
            self._ensure_client_connected()
            
            # Use the service's fixed space_id for client operations
            space_id = self.space_id
            
            # Get all graphs from the service's space
            result = self.client.list_graphs(space_id)
            
            if isinstance(result, dict) and "graphs" in result:
                graph_uris = result["graphs"]
            elif isinstance(result, list):
                graph_uris = result
            else:
                self.logger.warning(f"Unexpected result format from list_graphs: {type(result)}")
                graph_uris = []
            
            self.logger.info(f"Found {len(graph_uris)} graph URIs in space {space_id}")
            return graph_uris
            
        except Exception as e:
            self.logger.error(f"Failed to list graph URIs: {e}")
            return []
    
    def list_graphs(self, *, account_id: str | None = None, include_global: bool = True,
                   include_private: bool = True, safety_check: bool = True) -> List[VitalNameGraph]:
        """
        List graphs with filtering options.
        
        Args:
            account_id: Optional account ID filter
            include_global: Whether to include global graphs
            include_private: Whether to include private graphs
            safety_check: Whether to perform safety checks
            
        Returns:
            List of VitalNameGraph objects
        """
        self.logger.info(f"Listing graphs (account_id={account_id}, global={include_global}, private={include_private})")
        
        try:
            self._ensure_client_connected()
            
            # Query service graph for metadata
            managed_graphs = self._query_managed_graphs()
            
            # Filter graphs based on criteria
            filtered_graphs = []
            
            for graph_info in managed_graphs:
                graph_id = graph_info.get("graphID")
                graph_uri = graph_info.get("graphURI")
                is_global = graph_info.get("isGlobal", False)
                graph_account_id = graph_info.get("accountId")
                
                # Skip if missing required information
                if not graph_id or not graph_uri:
                    continue
                
                # Apply global/private filter
                if is_global and not include_global:
                    continue
                if not is_global and not include_private:
                    continue
                
                # Apply account_id filter
                if account_id is not None:
                    if is_global:
                        # Global graphs don't have account_id restriction
                        pass
                    else:
                        # Private graphs must match account_id
                        if graph_account_id != account_id:
                            continue
                
                # Create VitalNameGraph object
                try:
                    from vital_ai_vitalsigns_core.model.VitalNameGraph import VitalNameGraph
                    
                    vital_graph = VitalNameGraph()
                    vital_graph.URI = f"http://vital.ai/graph/{graph_id}"
                    vital_graph.name = graph_id
                    vital_graph.graphURI = graph_uri
                    vital_graph.global_graph = is_global
                    if graph_account_id:
                        vital_graph.account_id = graph_account_id
                    
                    filtered_graphs.append(vital_graph)
                    
                except ImportError as e:
                    self.logger.warning(f"Could not import VitalNameGraph: {e}")
                    # Create a simple dict-based object as fallback
                    class SimpleVitalNameGraph:
                        def __init__(self):
                            self.URI = f"http://vital.ai/graph/{graph_id}"
                            self.name = graph_id
                            self.graphURI = graph_uri
                            self.global_graph = is_global
                            if graph_account_id:
                                self.account_id = graph_account_id
                    
                    filtered_graphs.append(SimpleVitalNameGraph())
            
            self.logger.info(f"Found {len(filtered_graphs)} graphs matching criteria")
            return filtered_graphs
            
        except Exception as e:
            self.logger.error(f"Failed to list graphs: {e}")
            return []
    
    def get_graph(self, graph_id: str, *, global_graph: bool = False,
                 account_id: str | None = None, safety_check: bool = True) -> VitalNameGraph:
        """
        Get a specific graph by ID.
        
        Args:
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalNameGraph object
        """
        self.logger.info(f"Getting graph: {graph_id} (global={global_graph}, account_id={account_id})")
        
        try:
            self._ensure_client_connected()
            
            # Validate graph_id parameter
            if not graph_id or not isinstance(graph_id, str):
                self.logger.error(f"Invalid graph_id: {graph_id}")
                raise ValueError(f"Invalid graph_id: {graph_id}")
            
            # Query service graph for this specific graph's metadata
            managed_graphs = self._query_managed_graphs()
            
            # Find the specific graph
            target_graph = None
            for graph_info in managed_graphs:
                if graph_info.get("graphID") == graph_id:
                    # Check if the global_graph parameter matches
                    is_global = graph_info.get("isGlobal", False)
                    graph_account_id = graph_info.get("accountId")
                    
                    # Verify the graph matches the specified parameters
                    if is_global == global_graph:
                        # For private graphs, check account_id match
                        if not is_global and account_id and graph_account_id != account_id:
                            continue  # Skip if account_id doesn't match
                        target_graph = graph_info
                        break
            
            if not target_graph:
                error_msg = f"Graph not found: {graph_id} (global={global_graph}, account_id={account_id})"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Extract graph information
            graph_uri = target_graph.get("graphURI")
            is_global = target_graph.get("isGlobal", False)
            graph_account_id = target_graph.get("accountId")
            
            # Validate required information
            if not graph_uri:
                error_msg = f"Graph metadata incomplete for {graph_id}: missing graphURI"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Create VitalNameGraph object
            try:
                from vital_ai_vitalsigns_core.model.VitalNameGraph import VitalNameGraph
                
                vital_graph = VitalNameGraph()
                vital_graph.URI = f"http://vital.ai/graph/{graph_id}"
                vital_graph.name = graph_id
                vital_graph.graphURI = graph_uri
                vital_graph.global_graph = is_global
                if graph_account_id:
                    vital_graph.account_id = graph_account_id
                
                self.logger.info(f"Retrieved graph: {graph_id} -> {graph_uri}")
                return vital_graph
                
            except ImportError as e:
                self.logger.warning(f"Could not import VitalNameGraph: {e}")
                # Create a simple object as fallback
                class SimpleVitalNameGraph:
                    def __init__(self):
                        self.URI = f"http://vital.ai/graph/{graph_id}"
                        self.name = graph_id
                        self.graphURI = graph_uri
                        self.global_graph = is_global
                        if graph_account_id:
                            self.account_id = graph_account_id
                
                return SimpleVitalNameGraph()
            
        except ValueError:
            # Re-raise ValueError as-is (these are expected errors)
            raise
        except Exception as e:
            self.logger.error(f"Failed to get graph {graph_id}: {e}")
            raise RuntimeError(f"Failed to get graph {graph_id}: {e}")
    
    def create_graph(self, graph_id: str, *, global_graph: bool = False,
                    account_id: str | None = None, safety_check: bool = True) -> bool:
        """
        Create a new graph.
        
        Args:
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            True if creation was successful, False otherwise
        """
        self.logger.info(f"Creating graph: {graph_id} (global={global_graph}, account_id={account_id})")
        
        try:
            self._ensure_client_connected()
            
            # Get graph URI using naming conventions
            graph_uri = self._get_graph_uri(graph_id, account_id, global_graph)
            
            # Check if graph already exists
            if self._check_graph_exists(graph_uri):
                raise ValueError(f"Graph with URI {graph_uri} already exists")
            
            # Create graph using SPARQL CREATE GRAPH
            create_query = f"CREATE GRAPH <{graph_uri}>"
            self.client.execute_sparql_update(self.space_id, create_query)
            
            # Create VitalSegment metadata for the graph
            vital_segment = self._create_graph_vital_segment(graph_id, account_id, global_graph)
            rdf_string = vital_segment.to_rdf()
            
            # Insert metadata into service graph
            service_graph_uri = self._get_service_graph_uri()
            insert_query = f"""
            INSERT DATA {{
                GRAPH <{service_graph_uri}> {{
                    {rdf_string}
                }}
            }}
            """
            
            self.client.execute_sparql_insert(self.space_id, insert_query)
            
            self.logger.info(f"Graph created successfully: {graph_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create graph {graph_id}: {e}")
            return False
    
    def delete_graph(self, graph_id: str, *, global_graph: bool = False,
                    account_id: str | None = None, safety_check: bool = True) -> bool:
        """
        Delete a graph.
        
        Args:
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            True if deletion was successful, False otherwise
        """
        self.logger.info(f"Deleting graph: {graph_id} (global={global_graph}, account_id={account_id})")
        
        try:
            self._ensure_client_connected()
            
            # Get graph URI using naming conventions
            graph_uri = self._get_graph_uri(graph_id, account_id, global_graph)
            
            # Check if graph exists
            if not self._check_graph_exists(graph_uri):
                self.logger.warning(f"Graph does not exist: {graph_uri}")
                return False
            
            # Delete graph using SPARQL DROP
            drop_query = f"DROP GRAPH <{graph_uri}>"
            self.client.execute_sparql_update(self.space_id, drop_query)
            
            # Remove metadata from service graph
            service_graph_uri = self._get_service_graph_uri()
            delete_query = f"""
            DELETE {{
                GRAPH <{service_graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{service_graph_uri}> {{
                    ?s <http://vital.ai/ontology/vital-core#hasSegmentID> "{graph_id}" ;
                       <http://vital.ai/ontology/vital-core#hasSegmentNamespace> "{self.namespace}" ;
                       ?p ?o .
                    OPTIONAL {{
                        ?s <http://vital.ai/ontology/vital-core#hasSegmentTenantID> "{account_id}" .
                    }}
                }}
            }}
            """
            
            self.client.execute_sparql_delete(self.space_id, delete_query)
            
            self.logger.info(f"Graph deleted successfully: {graph_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete graph {graph_id}: {e}")
            return False
    
    def purge_graph(self, graph_id: str, *, global_graph: bool = False,
                   account_id: str | None = None, safety_check: bool = True) -> bool:
        """
        Purge all data from a graph but keep the graph structure.
        
        Args:
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            True if purge was successful, False otherwise
        """
        self.logger.info(f"Purging graph: {graph_id} (global={global_graph}, account_id={account_id})")
        
        try:
            self._ensure_client_connected()
            
            # Validate graph_id parameter
            if not graph_id or not isinstance(graph_id, str):
                self.logger.error(f"Invalid graph_id: {graph_id}")
                return False
            
            # Build graph URI
            graph_uri = self._build_graph_uri(graph_id, global_graph, account_id)
            
            # Safety check: verify graph exists if requested
            if safety_check:
                # Check if graph exists by querying service graph metadata
                managed_graphs = self._query_managed_graphs()
                graph_exists = False
                
                for graph_info in managed_graphs:
                    if (graph_info.get("graphID") == graph_id and 
                        graph_info.get("isGlobal") == global_graph):
                        # For private graphs, check account_id match
                        if not global_graph and account_id:
                            if graph_info.get("accountId") != account_id:
                                continue
                        graph_exists = True
                        break
                
                if not graph_exists:
                    self.logger.warning(f"Graph does not exist: {graph_uri}")
                    return False
            
            # Clear all triples from the graph using SPARQL DELETE
            # This removes all data but keeps the graph structure
            clear_query = f"""
            DELETE {{
                GRAPH <{graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            """
            
            self.client.execute_sparql_delete(self.space_id, clear_query)
            
            # Note: We do NOT remove the graph metadata from the service graph
            # The graph structure and metadata remain intact, only the data is cleared
            
            self.logger.info(f"Graph purged successfully: {graph_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to purge graph {graph_id}: {e}")
            return False
    
    def get_graph_all_objects(self, graph_id: str, *, global_graph: bool = False,
                             account_id: str | None = None, limit=100, offset=0,
                             safety_check: bool = True) -> ResultList:
        """
        Get all objects from a graph.
        
        Args:
            graph_id: Graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            limit: Maximum number of results
            offset: Result offset for pagination
            safety_check: Whether to perform safety checks
            
        Returns:
            ResultList containing all graph objects
        """
        self.logger.info(f"Getting all objects from graph: {graph_id} (global={global_graph}, limit={limit}, offset={offset})")
        
        try:
            self._ensure_client_connected()
            
            # Validate parameters
            if not graph_id or not isinstance(graph_id, str):
                self.logger.error(f"Invalid graph_id: {graph_id}")
                return ResultList()
            
            if limit <= 0:
                limit = 100  # Default limit
            if offset < 0:
                offset = 0   # Default offset
            
            # Build graph URI
            graph_uri = self._build_graph_uri(graph_id, global_graph, account_id)
            
            # Safety check: verify graph exists if requested
            if safety_check:
                managed_graphs = self._query_managed_graphs()
                graph_exists = False
                
                for graph_info in managed_graphs:
                    if (graph_info.get("graphID") == graph_id and 
                        graph_info.get("isGlobal") == global_graph):
                        # For private graphs, check account_id match
                        if not global_graph and account_id:
                            if graph_info.get("accountId") != account_id:
                                continue
                        graph_exists = True
                        break
                
                if not graph_exists:
                    self.logger.warning(f"Graph does not exist: {graph_uri}")
                    return ResultList()
            
            # Build SPARQL query to get all objects from the graph
            # Include VitalAI ontology prefixes
            prefixes = self._get_sparql_prefixes()
            
            sparql_query = f"""
            {prefixes}
            SELECT DISTINCT ?subject WHERE {{
                GRAPH <{graph_uri}> {{
                    ?subject ?predicate ?object .
                    # Filter to get only subjects that are likely objects (have rdf:type or vital properties)
                    {{
                        ?subject rdf:type ?type .
                    }} UNION {{
                        ?subject vital-core:vitaltype ?vitaltype .
                    }}
                }}
            }}
            ORDER BY ?subject
            LIMIT {limit}
            OFFSET {offset}
            """
            
            # Execute the query to get object URIs
            result = self.client.execute_sparql_query(self.space_id, sparql_query)
            
            if not result or "results" not in result or "bindings" not in result["results"]:
                self.logger.info(f"No objects found in graph: {graph_uri}")
                return ResultList()
            
            # Extract object URIs from query results
            object_uris = []
            for binding in result["results"]["bindings"]:
                subject_uri = binding.get("subject", {}).get("value")
                if subject_uri:
                    object_uris.append(subject_uri)
            
            if not object_uris:
                self.logger.info(f"No objects found in graph: {graph_uri}")
                return ResultList()
            
            # Use the existing helper method to retrieve the actual objects
            objects = self._get_object_list_internal(object_uris, graph_uri)
            
            # Create ResultList with the objects
            try:
                from vital_ai_vitalsigns_core.model.ResultList import ResultList as VitalResultList
                
                result_list = VitalResultList()
                result_list.results = objects
                result_list.totalResults = len(objects)
                result_list.limit = limit
                result_list.offset = offset
                
                self.logger.info(f"Retrieved {len(objects)} objects from graph: {graph_uri}")
                return result_list
                
            except ImportError as e:
                self.logger.warning(f"Could not import VitalResultList: {e}")
                # Create a simple ResultList-like object as fallback
                class SimpleResultList:
                    def __init__(self):
                        self.results = objects
                        self.totalResults = len(objects)
                        self.limit = limit
                        self.offset = offset
                
                return SimpleResultList()
            
        except Exception as e:
            self.logger.error(f"Failed to get all objects from graph {graph_id}: {e}")
            return ResultList()
    
    # Object Operations
    def insert_object(self, graph_id: str, graph_object: G, *, global_graph: bool = False,
                     account_id: str | None = None, safety_check: bool = True) -> VitalGraphStatus:
        """
        Insert a single object into a graph.
        
        Args:
            graph_id: Graph identifier
            graph_object: Object to insert
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalGraphStatus indicating success or failure
        """
        self.logger.info(f"Inserting object into graph: {graph_id}")
        
        try:
            # Ensure client is connected
            self._ensure_client_connected()
            
            # Get graph URI
            graph_uri = self._get_graph_uri(graph_id, global_graph, account_id)
            
            # Verify graph exists if safety check is enabled
            if safety_check:
                if not self._check_graph_exists(graph_uri):
                    return VitalGraphStatus(-1, f"Graph {graph_id} does not exist")
            
            # Get object URI
            object_uri = str(graph_object.URI)
            
            # Check if object already exists in the graph
            if self._check_object_exists_in_graph(graph_uri, object_uri):
                return VitalGraphStatus(-1, f"Object {object_uri} already exists in graph {graph_id}")
            
            # Convert object to RDF
            rdf_data = graph_object.to_rdf()
            
            # Build SPARQL INSERT query
            insert_query = f"""
            INSERT DATA {{
                GRAPH <{graph_uri}> {{
                    {rdf_data}
                }}
            }}
            """
            
            # Execute the insert
            result = self.client.execute_sparql_insert(self.space_id, insert_query)
            
            if result.get("success", False):
                self.logger.info(f"Successfully inserted object {object_uri} into graph {graph_id}")
                return VitalGraphStatus(0, "Graph object inserted successfully.")
            else:
                error_msg = result.get("error", "Unknown error during insert")
                self.logger.error(f"Failed to insert object {object_uri}: {error_msg}")
                return VitalGraphStatus(-1, f"Failed to insert graph object: {error_msg}")
                
        except VitalGraphClientError as e:
            self.logger.error(f"Client error during object insertion: {e}")
            return VitalGraphStatus(-1, f"Client error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error during object insertion: {e}")
            return VitalGraphStatus(-1, f"Failed to insert graph object: {str(e)}")
    
    def insert_object_list(self, graph_id: str, graph_object_list: List[G], *, global_graph: bool = False,
                          account_id: str | None = None, safety_check: bool = True) -> VitalGraphStatus:
        """
        Insert multiple objects into a graph.
        
        Args:
            graph_id: Graph identifier
            graph_object_list: List of objects to insert
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalGraphStatus indicating success or failure
        """
        self.logger.info(f"Inserting {len(graph_object_list)} objects into graph: {graph_id}")
        # TODO: Implement object list insertion
        raise NotImplementedError("insert_object_list method not yet implemented")
    
    def update_object(self, graph_object: G, *, graph_id: str = None, global_graph: bool = False,
                     account_id: str | None = None, upsert: bool = False,
                     safety_check: bool = True) -> VitalGraphStatus:
        """
        Update a single object in a graph.
        
        Args:
            graph_object: Object to update
            graph_id: Optional graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            upsert: Whether to insert if object doesn't exist
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalGraphStatus indicating success or failure
        """
        object_uri = getattr(graph_object, 'URI', None)
        self.logger.info(f"Updating object: {object_uri} in graph: {graph_id}")
        
        try:
            self._ensure_client_connected()
            
            # Validate object has URI
            if not object_uri:
                error_msg = "Object must have a URI property"
                self.logger.error(error_msg)
                return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
            
            # Validate graph_id parameter
            if not graph_id:
                error_msg = "graph_id is required for update_object"
                self.logger.error(error_msg)
                return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
            
            # Build graph URI
            graph_uri = self._build_graph_uri(graph_id, global_graph, account_id)
            
            # Safety check: verify graph exists if requested
            if safety_check:
                managed_graphs = self._query_managed_graphs()
                graph_exists = False
                
                for graph_info in managed_graphs:
                    if (graph_info.get("graphID") == graph_id and 
                        graph_info.get("isGlobal") == global_graph):
                        # For private graphs, check account_id match
                        if not global_graph and account_id:
                            if graph_info.get("accountId") != account_id:
                                continue
                        graph_exists = True
                        break
                
                if not graph_exists:
                    error_msg = f"Graph does not exist: {graph_uri}"
                    self.logger.error(error_msg)
                    return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
            
            # Check if object exists in the graph
            object_exists = self._check_object_exists_in_graph(object_uri, graph_uri)
            
            if not object_exists and not upsert:
                error_msg = f"Object {object_uri} does not exist in graph {graph_uri} and upsert=False"
                self.logger.warning(error_msg)
                return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
            
            # Convert object to RDF triples
            try:
                rdf_data = graph_object.to_rdf()
                if not rdf_data:
                    error_msg = f"Failed to serialize object {object_uri} to RDF"
                    self.logger.error(error_msg)
                    return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
            except Exception as e:
                error_msg = f"Error serializing object {object_uri} to RDF: {e}"
                self.logger.error(error_msg)
                return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
            
            # Perform atomic update: delete existing triples then insert new ones
            if object_exists:
                # Delete existing triples for this object
                delete_query = f"""
                DELETE {{
                    GRAPH <{graph_uri}> {{
                        <{object_uri}> ?p ?o .
                    }}
                }}
                WHERE {{
                    GRAPH <{graph_uri}> {{
                        <{object_uri}> ?p ?o .
                    }}
                }}
                """
                
                self.client.execute_sparql_delete(self.space_id, delete_query)
                self.logger.debug(f"Deleted existing triples for object: {object_uri}")
            
            # Insert updated object data
            prefixes = self._get_sparql_prefixes()
            insert_query = f"""
            {prefixes}
            INSERT DATA {{
                GRAPH <{graph_uri}> {{
                    {rdf_data}
                }}
            }}
            """
            
            self.client.execute_sparql_insert(self.space_id, insert_query)
            
            action = "updated" if object_exists else "inserted (upsert)"
            success_msg = f"Object {action} successfully: {object_uri}"
            self.logger.info(success_msg)
            
            return VitalGraphStatus(status=VitalGraphStatus.Status.SUCCESS, message=success_msg)
            
        except Exception as e:
            error_msg = f"Failed to update object {object_uri}: {e}"
            self.logger.error(error_msg)
            return VitalGraphStatus(status=VitalGraphStatus.Status.FAILURE, message=error_msg)
    
    def update_object_list(self, graph_object_list: List[G], *, graph_id: str = None,
                          global_graph: bool = False, account_id: str | None = None,
                          upsert: bool = False, safety_check: bool = True) -> VitalGraphStatus:
        """
        Update multiple objects in a graph.
        
        Args:
            graph_object_list: List of objects to update
            graph_id: Optional graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            upsert: Whether to insert if objects don't exist
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalGraphStatus indicating success or failure
        """
        self.logger.info(f"Updating {len(graph_object_list)} objects")
        # TODO: Implement object list update
        raise NotImplementedError("update_object_list method not yet implemented")
    
    def get_object(self, object_uri: str, *, graph_id: str = None, global_graph: bool = False,
                  account_id: str | None = None, safety_check: bool = True) -> G:
        """
        Get a single object by URI.
        
        Args:
            object_uri: URI of the object to retrieve
            graph_id: Optional graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            The requested graph object
        """
        self.logger.info(f"Getting object: {object_uri}")
        
        try:
            # Ensure client is connected
            self._ensure_client_connected()
            
            if graph_id is None:
                raise ValueError("Error: graph_id is required")
            
            # Get graph URI
            graph_uri = self._get_graph_uri(graph_id, global_graph, account_id)
            
            # Verify graph exists if safety check is enabled
            if safety_check:
                if not self._check_graph_exists(graph_uri):
                    raise ValueError(f"Graph {graph_id} does not exist")
            
            # Check if object exists in the graph
            if not self._check_object_exists_in_graph(graph_uri, object_uri):
                return None  # Object not found
            
            # Build SPARQL CONSTRUCT query to get all triples for the object
            construct_query = f"""
            CONSTRUCT {{
                <{object_uri}> ?p ?o .
            }} WHERE {{
                GRAPH <{graph_uri}> {{
                    <{object_uri}> ?p ?o .
                }}
            }}
            """
            
            # Execute the query
            result = self.client.execute_sparql_query(self.space_id, construct_query)
            
            if result and "results" in result:
                # Convert SPARQL results to RDF triples
                triples = self._sparql_results_to_triples(result)
                
                if triples:
                    # Use VitalSigns to convert triples back to graph object
                    from vital_ai_vitalsigns.vitalsigns import VitalSigns
                    vs = VitalSigns()
                    graph_object = vs.from_triples(triples)
                    
                    self.logger.info(f"Successfully retrieved object {object_uri} from graph {graph_id}")
                    return graph_object
                else:
                    self.logger.warning(f"No triples found for object {object_uri} in graph {graph_id}")
                    return None
            else:
                self.logger.warning(f"No results returned for object {object_uri} in graph {graph_id}")
                return None
                
        except VitalGraphClientError as e:
            self.logger.error(f"Client error during object retrieval: {e}")
            raise ValueError(f"Error retrieving object {object_uri}: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error during object retrieval: {e}")
            raise ValueError(f"Error retrieving object {object_uri}: {str(e)}")
    
    def get_object_list(self, object_uri_list: List[str], *, graph_id: str = None,
                       global_graph: bool = False, account_id: str | None = None,
                       safety_check: bool = True) -> ResultList:
        """
        Get multiple objects by URI list.
        
        Args:
            object_uri_list: List of object URIs to retrieve
            graph_id: Optional graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            ResultList containing the requested objects
        """
        self.logger.info(f"Getting {len(object_uri_list)} objects")
        # TODO: Implement object list retrieval
        raise NotImplementedError("get_object_list method not yet implemented")
    
    def delete_object(self, object_uri: str, *, graph_id: str = None, global_graph: bool = False,
                     account_id: str | None = None, safety_check: bool = True) -> VitalGraphStatus:
        """
        Delete a single object.
        
        Args:
            object_uri: URI of the object to delete
            graph_id: Optional graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalGraphStatus indicating success or failure
        """
        self.logger.info(f"Deleting object: {object_uri}")
        
        try:
            # Ensure client is connected
            self._ensure_client_connected()
            
            if graph_id is None:
                return VitalGraphStatus(-1, "Error: graph_id is required")
            
            # Get graph URI
            graph_uri = self._get_graph_uri(graph_id, global_graph, account_id)
            
            # Verify graph exists if safety check is enabled
            if safety_check:
                if not self._check_graph_exists(graph_uri):
                    return VitalGraphStatus(-1, f"Graph {graph_id} does not exist")
            
            # Check if object exists in the graph
            if not self._check_object_exists_in_graph(graph_uri, object_uri):
                return VitalGraphStatus(-1, f"Object {object_uri} not found in graph {graph_id}")
            
            # Build SPARQL DELETE query
            delete_query = f"""
            DELETE {{
                GRAPH <{graph_uri}> {{
                    <{object_uri}> ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{graph_uri}> {{
                    <{object_uri}> ?p ?o .
                }}
            }}
            """
            
            # Execute the delete
            result = self.client.execute_sparql_delete(self.space_id, delete_query)
            
            if result.get("success", False):
                self.logger.info(f"Successfully deleted object {object_uri} from graph {graph_id}")
                return VitalGraphStatus(0, "Graph object deleted successfully.")
            else:
                error_msg = result.get("error", "Unknown error during delete")
                self.logger.error(f"Failed to delete object {object_uri}: {error_msg}")
                return VitalGraphStatus(-1, f"Failed to delete graph object: {error_msg}")
                
        except VitalGraphClientError as e:
            self.logger.error(f"Client error during object deletion: {e}")
            return VitalGraphStatus(-1, f"Client error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error during object deletion: {e}")
            return VitalGraphStatus(-1, f"Error deleting object {object_uri}: {str(e)}")
    
    def delete_object_list(self, object_uri_list: List[str], *, graph_id: str = None,
                          global_graph: bool = False, account_id: str | None = None,
                          safety_check: bool = True) -> VitalGraphStatus:
        """
        Delete multiple objects from a graph.
        
        Args:
            object_uri_list: List of object URIs to delete
            graph_id: Optional graph identifier
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            VitalGraphStatus indicating success or failure
        """
        self.logger.info(f"Deleting {len(object_uri_list)} objects")
        # TODO: Implement object list deletion
        raise NotImplementedError("delete_object_list method not yet implemented")
    
    # Query Operations
    def filter_query(self, graph_id: str, sparql_query: str, uri_binding='uri', *,
                    limit: int = 100, offset: int = 0, global_graph: bool = False,
                    account_id: str | None = None, resolve_objects: bool = True,
                    safety_check: bool = True) -> ResultList:
        """
        Execute a filter query on a graph.
        
        Args:
            graph_id: Graph identifier
            sparql_query: SPARQL query string
            uri_binding: URI binding parameter
            limit: Maximum number of results
            offset: Result offset for pagination
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            resolve_objects: Whether to resolve objects
            safety_check: Whether to perform safety checks
            
        Returns:
            ResultList with filtered results
        """
        self.logger.info(f"Executing filter query on graph: {graph_id}")
        
        try:
            # Ensure client is connected
            self._ensure_client_connected()
            
            if graph_id is None:
                self.logger.error("Graph ID is required for filter query")
                return ResultList()
            
            # Get graph URI
            graph_uri = self._get_graph_uri(graph_id, global_graph, account_id)
            
            # Verify graph exists if safety check is enabled
            if safety_check:
                if not self._check_graph_exists(graph_uri):
                    self.logger.error(f"Graph {graph_id} does not exist")
                    return ResultList()
            
            # Build complete SPARQL filter query with prefixes and graph context
            # Filter query is similar to regular query but may have different structure
            full_query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX vital: <http://vital.ai/ontology/vital#>
            PREFIX vital-aimp: <http://vital.ai/ontology/vital-aimp#>
            PREFIX haley: <http://vital.ai/ontology/haley#>
            PREFIX haley-ai-question: <http://vital.ai/ontology/haley-ai-question#>
            PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT DISTINCT ?{uri_binding} WHERE {{
                GRAPH <{graph_uri}> {{
                    ?{uri_binding} a ?type .
                    FILTER ({sparql_query})
                }}
            }} ORDER BY ?{uri_binding}
            LIMIT {limit} OFFSET {offset}
            """
            
            self.logger.debug(f"Executing SPARQL filter query: {full_query}")
            
            # Execute SPARQL query using client
            result = self.client.execute_sparql_query(self.space_id, full_query)
            
            if not result or "results" not in result:
                self.logger.warning(f"No results returned from filter query on graph {graph_id}")
                return ResultList()
            
            # Extract object URIs from results
            bindings = result["results"].get("bindings", [])
            object_uri_list = []
            
            for binding in bindings:
                if uri_binding in binding:
                    uri_value = binding[uri_binding].get("value")
                    if uri_value:
                        object_uri_list.append(uri_value)
            
            if not object_uri_list:
                self.logger.info(f"Filter query returned no object URIs for graph {graph_id}")
                return ResultList()
            
            self.logger.info(f"Filter query found {len(object_uri_list)} object URIs")
            
            # Resolve objects if requested
            if resolve_objects:
                # Use internal helper to resolve all objects
                return self._get_object_list_internal(object_uri_list, graph_id, global_graph, account_id)
            else:
                # Return ResultList with RDFStatement objects for URIs
                result_list = ResultList()
                
                for uri in object_uri_list:
                    from vital_ai_vitalsigns_core.model.RDFStatement import RDFStatement
                    from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
                    
                    rdf_triple = RDFStatement()
                    rdf_triple.URI = URIGenerator.generate_uri()
                    rdf_triple.rdfSubject = uri
                    rdf_triple.rdfPredicate = ''
                    rdf_triple.rdfObject = ''
                    
                    result_list.add_result(rdf_triple)
                
                return result_list
                
        except VitalGraphClientError as e:
            self.logger.error(f"Client error during filter query execution: {e}")
            return ResultList()
        except Exception as e:
            self.logger.error(f"Unexpected error during filter query execution: {e}")
            return ResultList()
    
    # Query Operations
    def query(self, graph_id: str, sparql_query: str, uri_binding='uri', *, limit=100, offset=0,
             resolve_objects=True, global_graph: bool = False, account_id: str | None = None,
             safety_check: bool = True) -> ResultList | VitalGraphStatus:
        """
        Execute a SPARQL query on a graph.
        
        Args:
            graph_id: Graph identifier
            sparql_query: SPARQL query string
            uri_binding: URI binding parameter
            limit: Maximum number of results
            offset: Result offset for pagination
            resolve_objects: Whether to resolve objects
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            ResultList with query results or VitalGraphStatus on error
        """
        self.logger.info(f"Executing query on graph: {graph_id}")
        
        try:
            # Ensure client is connected
            self._ensure_client_connected()
            
            if graph_id is None:
                return VitalGraphStatus(-1, "Error: graph_id is required")
            
            # Get graph URI
            graph_uri = self._get_graph_uri(graph_id, global_graph, account_id)
            
            # Verify graph exists if safety check is enabled
            if safety_check:
                if not self._check_graph_exists(graph_uri):
                    return VitalGraphStatus(-1, f"Graph {graph_id} does not exist")
            
            # Build complete SPARQL query with prefixes and graph context
            full_query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX vital: <http://vital.ai/ontology/vital#>
            PREFIX vital-aimp: <http://vital.ai/ontology/vital-aimp#>
            PREFIX haley: <http://vital.ai/ontology/haley#>
            PREFIX haley-ai-question: <http://vital.ai/ontology/haley-ai-question#>
            PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT DISTINCT ?{uri_binding} WHERE {{
                GRAPH <{graph_uri}> {{
                    {sparql_query}
                }}
            }} ORDER BY ?{uri_binding}
            LIMIT {limit} OFFSET {offset}
            """
            
            self.logger.debug(f"Executing SPARQL query: {full_query}")
            
            # Execute SPARQL query using client
            result = self.client.execute_sparql_query(self.space_id, full_query)
            
            if not result or "results" not in result:
                self.logger.warning(f"No results returned from query on graph {graph_id}")
                return ResultList()
            
            # Extract object URIs from results
            bindings = result["results"].get("bindings", [])
            object_uri_list = []
            
            for binding in bindings:
                if uri_binding in binding:
                    uri_value = binding[uri_binding].get("value")
                    if uri_value:
                        object_uri_list.append(uri_value)
            
            if not object_uri_list:
                self.logger.info(f"Query returned no object URIs for graph {graph_id}")
                return ResultList()
            
            self.logger.info(f"Query found {len(object_uri_list)} object URIs")
            
            # Resolve objects if requested
            if resolve_objects:
                # Use get_object_list to resolve all objects
                return self._get_object_list_internal(object_uri_list, graph_id, global_graph, account_id)
            else:
                # Return ResultList with RDFStatement objects for URIs
                result_list = ResultList()
                
                for uri in object_uri_list:
                    from vital_ai_vitalsigns_core.model.RDFStatement import RDFStatement
                    from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
                    
                    rdf_triple = RDFStatement()
                    rdf_triple.URI = URIGenerator.generate_uri()
                    rdf_triple.rdfSubject = uri
                    rdf_triple.rdfPredicate = ''
                    rdf_triple.rdfObject = ''
                    
                    result_list.add_result(rdf_triple)
                
                return result_list
                
        except VitalGraphClientError as e:
            self.logger.error(f"Client error during query execution: {e}")
            return VitalGraphStatus(-1, f"Client error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error during query execution: {e}")
            return VitalGraphStatus(-1, f"Failed to execute query: {str(e)}")
    
    def query_construct(self, graph_id: str, sparql_query: str, namespace_list: List[Ontology],
                       binding_list: List[Binding], *, limit=100, offset=0, global_graph: bool = False,
                       account_id: str | None = None, safety_check: bool = True) -> ResultList:
        """
        Execute a SPARQL CONSTRUCT query.
        
        Args:
            graph_id: Graph identifier
            sparql_query: SPARQL query string
            namespace_list: List of ontology namespaces
            binding_list: List of variable bindings
            limit: Maximum number of results
            offset: Result offset for pagination
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            safety_check: Whether to perform safety checks
            
        Returns:
            ResultList with constructed results
        """
        self.logger.info(f"Executing CONSTRUCT query on graph: {graph_id} (limit={limit}, offset={offset})")
        
        try:
            self._ensure_client_connected()
            
            # Validate parameters
            if not graph_id or not isinstance(graph_id, str):
                self.logger.error(f"Invalid graph_id: {graph_id}")
                result_list = ResultList()
                result_list.set_status(-1)
                result_list.set_message("Error: graph_id is not set.")
                return result_list
            
            if not sparql_query or not isinstance(sparql_query, str):
                self.logger.error(f"Invalid sparql_query: {sparql_query}")
                result_list = ResultList()
                result_list.set_status(-1)
                result_list.set_message("Error: sparql_query is not set.")
                return result_list
            
            if limit <= 0:
                limit = 100  # Default limit
            if offset < 0:
                offset = 0   # Default offset
            
            # Build graph URI
            graph_uri = self._build_graph_uri(graph_id, global_graph, account_id)
            
            # Safety check: verify graph exists if requested
            if safety_check:
                managed_graphs = self._query_managed_graphs()
                graph_exists = False
                
                for graph_info in managed_graphs:
                    if (graph_info.get("graphID") == graph_id and 
                        graph_info.get("isGlobal") == global_graph):
                        # For private graphs, check account_id match
                        if not global_graph and account_id:
                            if graph_info.get("accountId") != account_id:
                                continue
                        graph_exists = True
                        break
                
                if not graph_exists:
                    self.logger.warning(f"Graph does not exist: {graph_uri}")
                    result_list = ResultList()
                    result_list.set_status(-1)
                    result_list.set_message(f"Graph {graph_id} does not exist.")
                    return result_list
            
            # Build namespace prefixes from ontology list
            prefix_section = ""
            if namespace_list:
                prefix_section = "\n".join([f"PREFIX {ns.prefix}: <{ns.ontology_iri}>" for ns in namespace_list])
            
            # Build order by section from bindings
            order_by_section = ""
            if binding_list:
                order_by_section = " ".join([binding.variable for binding in binding_list])
            
            # Build CONSTRUCT template from bindings (following Virtuoso pattern)
            construct_template = ""
            if binding_list:
                construct_template = "\n".join([f"_:bnode1 <{binding.property_uri}> ?{binding.variable[1:]} ." for binding in binding_list])
            else:
                # Default construct template if no bindings
                construct_template = "?s ?p ?o ."
            
            # Build SELECT clause with optional handling
            select_parts = []
            if binding_list:
                for binding in binding_list:
                    variable = binding.variable
                    if hasattr(binding, 'optional') and binding.optional:
                        unbound_symbol = getattr(binding, 'unbound_symbol', 'UNBOUND')
                        select_parts.append(f"(COALESCE({variable}, \"{unbound_symbol}\") AS {variable})")
                    else:
                        select_parts.append(f"{variable}")
                select_clause = "SELECT " + ", ".join(select_parts)
            else:
                select_clause = "SELECT ?s ?p ?o"
            
            # Build the complete CONSTRUCT query following Virtuoso pattern
            if binding_list and order_by_section:
                query = f"""
{prefix_section}
CONSTRUCT {{
{construct_template}
}}
WHERE {{
GRAPH <{graph_uri}> {{
    {select_clause} WHERE 
    {{
    {sparql_query}
    }}
}}
}}
ORDER BY {order_by_section}
LIMIT {limit}
OFFSET {offset}
"""
            else:
                # Simpler query structure when no bindings
                base_prefixes = self._get_sparql_prefixes()
                query = f"""
{base_prefixes}
{prefix_section}
CONSTRUCT {{
{construct_template}
}}
WHERE {{
GRAPH <{graph_uri}> {{
    {sparql_query}
}}
}}
LIMIT {limit}
OFFSET {offset}
"""
            
            self.logger.debug(f"Executing CONSTRUCT query: {query}")
            
            # Execute the CONSTRUCT query
            result = self.client.execute_sparql_query(self.space_id, query)
            
            if not result:
                self.logger.info(f"No results from CONSTRUCT query on graph: {graph_uri}")
                return ResultList()
            
            # Process CONSTRUCT results - create RDFStatement objects
            result_list = ResultList()
            
            # Handle different result formats
            if "results" in result and "bindings" in result["results"]:
                # SELECT-style result format
                for binding in result["results"]["bindings"]:
                    try:
                        from vital_ai_vitalsigns_core.model.RDFStatement import RDFStatement
                        from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
                        
                        rdf_statement = RDFStatement()
                        rdf_statement.URI = URIGenerator.generate_uri()
                        
                        # Extract subject, predicate, object from bindings
                        if "s" in binding:
                            rdf_statement.rdfSubject = binding["s"].get("value", "")
                        if "p" in binding:
                            rdf_statement.rdfPredicate = binding["p"].get("value", "")
                        if "o" in binding:
                            rdf_statement.rdfObject = binding["o"].get("value", "")
                        
                        result_list.add_result(rdf_statement)
                        
                    except Exception as e:
                        self.logger.warning(f"Failed to create RDFStatement from binding: {e}")
                        continue
            
            elif "triples" in result:
                # Direct triple format
                for triple in result["triples"]:
                    try:
                        from vital_ai_vitalsigns_core.model.RDFStatement import RDFStatement
                        from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
                        
                        rdf_statement = RDFStatement()
                        rdf_statement.URI = URIGenerator.generate_uri()
                        rdf_statement.rdfSubject = str(triple.get("subject", ""))
                        rdf_statement.rdfPredicate = str(triple.get("predicate", ""))
                        rdf_statement.rdfObject = str(triple.get("object", ""))
                        
                        result_list.add_result(rdf_statement)
                        
                    except Exception as e:
                        self.logger.warning(f"Failed to create RDFStatement from triple: {e}")
                        continue
            
            # If we got a graph result (typical for CONSTRUCT), process it
            elif hasattr(result, 'triples') or (hasattr(result, '__iter__') and not isinstance(result, dict)):
                try:
                    from vital_ai_vitalsigns_core.model.RDFStatement import RDFStatement
                    from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
                    
                    # Handle RDFLib-style graph results
                    for s, p, o in result:
                        rdf_statement = RDFStatement()
                        rdf_statement.URI = URIGenerator.generate_uri()
                        rdf_statement.rdfSubject = str(s)
                        rdf_statement.rdfPredicate = str(p)
                        rdf_statement.rdfObject = str(o)
                        
                        result_list.add_result(rdf_statement)
                        
                except Exception as e:
                    self.logger.warning(f"Failed to process graph result: {e}")
            
            self.logger.info(f"CONSTRUCT query returned {len(result_list.results)} triples from graph: {graph_uri}")
            return result_list
            
        except Exception as e:
            self.logger.error(f"Failed to execute CONSTRUCT query on graph {graph_id}: {e}")
            result_list = ResultList()
            result_list.set_status(-1)
            result_list.set_message(f"Failed to execute CONSTRUCT query: {str(e)}")
            return result_list
    
    def query_construct_solution(self, graph_id: str, sparql_query: str, namespace_list: List[Ontology],
                                binding_list: List[Binding], root_binding: str | None = None, *,
                                limit=100, offset=0, global_graph: bool = False,
                                account_id: str | None = None, resolve_objects: bool = True,
                                safety_check: bool = True) -> SolutionList:
        """
        Execute a SPARQL CONSTRUCT query and return solutions.
        
        Args:
            graph_id: Graph identifier
            sparql_query: SPARQL query string
            namespace_list: List of ontology namespaces
            binding_list: List of variable bindings
            root_binding: Optional root binding
            limit: Maximum number of results
            offset: Result offset for pagination
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            resolve_objects: Whether to resolve objects
            safety_check: Whether to perform safety checks
            
        Returns:
            SolutionList with constructed solutions
        """
        self.logger.info(f"Executing CONSTRUCT solution query on graph: {graph_id} (limit={limit}, offset={offset})")
        
        try:
            # Build graph URI
            graph_uri = self._build_graph_uri(graph_id, global_graph, account_id)
            
            # Object cache to use during query processing
            graph_map: dict = {}
            
            # First, execute the CONSTRUCT query to get RDF triples
            result_list = self.query_construct(
                graph_id,
                sparql_query,
                namespace_list,
                binding_list,
                global_graph=global_graph,
                account_id=account_id,
                limit=limit,
                offset=offset,
                safety_check=safety_check
            )
            
            # Import required classes
            try:
                from rdflib import Graph, URIRef, Literal
                from vital_ai_vitalsigns_core.model.RDFStatement import RDFStatement
                from vital_ai_vitalsigns.model.properties.BindingValueType import BindingValueType
                from vital_ai_vitalsigns_core.model.Solution import Solution
                from vital_ai_vitalsigns_core.model.SolutionList import SolutionList
            except ImportError as e:
                self.logger.error(f"Failed to import required classes: {e}")
                # Return empty SolutionList as fallback
                class SimpleSolutionList:
                    def __init__(self):
                        self.solutions = []
                        self.limit = limit
                        self.offset = offset
                return SimpleSolutionList()
            
            # Build RDFLib graph from the construct results
            graph = Graph()
            
            for result in result_list.results:
                if isinstance(result, RDFStatement):
                    s = result.rdfSubject
                    p = result.rdfPredicate
                    o = result.rdfObject
                    
                    # Determine value type from binding list
                    value_type = BindingValueType.URIREF
                    for binding in binding_list:
                        if binding.property_uri == str(p):
                            value_type = binding.value_type
                            break
                    
                    # Add triple to graph with appropriate type
                    if value_type == BindingValueType.URIREF:
                        graph.add((URIRef(self._strip_angle_brackets(str(s))), 
                                  URIRef(self._strip_angle_brackets(str(p))), 
                                  URIRef(self._strip_angle_brackets(str(o)))))
                    else:
                        graph.add((URIRef(self._strip_angle_brackets(str(s))), 
                                  URIRef(self._strip_angle_brackets(str(p))), 
                                  Literal(str(o))))
            
            # Collect unique URI objects for bulk retrieval
            unique_objects = set(graph.objects())
            uri_objects = {o for o in unique_objects if isinstance(o, URIRef)}
            
            retrieve_list: List[str] = []
            for obj_uri in uri_objects:
                object_uri_str = str(obj_uri)
                retrieve_list.append(object_uri_str)
            
            self.logger.debug(f"Bulk retrieving {len(retrieve_list)} URI objects")
            
            # Bulk retrieve objects in chunks for efficiency
            total_objects = len(retrieve_list)
            start_index = 0
            chunk_size = 1000
            
            while start_index < total_objects:
                end_index = min(start_index + chunk_size, total_objects)
                chunk = retrieve_list[start_index:end_index]
                
                # Use get_object_list to retrieve chunk of objects
                try:
                    chunk_result_list = self.get_object_list(
                        chunk,
                        graph_id=graph_id,
                        account_id=account_id,
                        global_graph=global_graph,
                        safety_check=False  # Skip safety check for bulk operations
                    )
                    
                    # Add retrieved objects to cache
                    if hasattr(chunk_result_list, 'results'):
                        for result_obj in chunk_result_list.results:
                            if hasattr(result_obj, 'URI'):
                                graph_map[str(result_obj.URI)] = result_obj
                    
                except Exception as e:
                    self.logger.warning(f"Failed to bulk retrieve chunk: {e}")
                    # Fall back to individual retrieval for this chunk
                    for uri in chunk:
                        try:
                            obj = self.get_object(
                                uri,
                                graph_id=graph_id,
                                account_id=account_id,
                                global_graph=global_graph,
                                safety_check=False
                            )
                            if obj:
                                graph_map[uri] = obj
                        except Exception as obj_e:
                            self.logger.warning(f"Failed to retrieve object {uri}: {obj_e}")
                
                start_index += chunk_size
            
            # Remove duplicate triples and create unique graph
            unique_triples = set(graph.triples((None, None, None)))
            unique_graph = Graph()
            for triple in unique_triples:
                unique_graph.add(triple)
            
            # Get unique subjects to create solutions
            unique_subjects = set(unique_graph.subjects())
            
            solutions = []
            solution_count = 0
            
            # Process each subject to create a solution
            for subject in unique_subjects:
                uri_map = {}
                obj_map = {}
                root_binding_obj = None
                
                # Get all triples for this subject
                triples = unique_graph.triples((subject, None, None))
                
                for s, p, o in triples:
                    # Find matching bindings for this predicate
                    matching_bindings = [binding for binding in binding_list if binding.property_uri == str(p)]
                    
                    if len(matching_bindings) == 1:
                        matching_binding = matching_bindings[0]
                        binding_var = matching_binding.variable
                        binding_value = o
                        
                        # Set URI mapping (string value)
                        uri_map[binding_var] = str(binding_value)
                        
                        # Handle URIREF bindings - resolve to objects if requested
                        if matching_binding.value_type == BindingValueType.URIREF and resolve_objects:
                            # Try to get cached object first
                            cache_obj = graph_map.get(str(o))
                            
                            if cache_obj is None:
                                # Cache miss - retrieve individual object
                                self.logger.debug(f"Cache miss, retrieving: {str(o)}")
                                try:
                                    binding_obj = self.get_object(
                                        str(o),
                                        graph_id=graph_id,
                                        account_id=account_id,
                                        global_graph=global_graph,
                                        safety_check=False
                                    )
                                    if binding_obj:
                                        graph_map[str(o)] = binding_obj
                                        cache_obj = binding_obj
                                except Exception as e:
                                    self.logger.warning(f"Failed to retrieve object {str(o)}: {e}")
                            
                            if cache_obj:
                                obj_map[binding_var] = cache_obj
                                
                                # Check if this is the root binding
                                if binding_var == root_binding:
                                    root_binding_obj = cache_obj
                
                solution_count += 1
                self.logger.debug(f"Creating solution {solution_count}")
                
                # Create solution with URI map, object map, root binding, and root object
                solution = Solution(uri_map, obj_map, root_binding, root_binding_obj)
                solutions.append(solution)
            
            # Create and return SolutionList
            solution_list = SolutionList(solutions, limit, offset)
            
            self.logger.info(f"CONSTRUCT solution query completed: {solution_count} solutions from graph: {graph_uri}")
            return solution_list
            
        except Exception as e:
            self.logger.error(f"Failed to execute CONSTRUCT solution query on graph {graph_id}: {e}")
            # Return empty SolutionList on error
            try:
                from vital_ai_vitalsigns_core.model.SolutionList import SolutionList
                return SolutionList([], limit, offset)
            except ImportError:
                # Fallback if SolutionList import fails
                class SimpleSolutionList:
                    def __init__(self):
                        self.solutions = []
                        self.limit = limit
                        self.offset = offset
                return SimpleSolutionList()
    
    def metaql_select_query(self, *, select_query: MetaQLSelectQuery, namespace_list: List[Ontology] = None,
                           account_id: str | None = None, is_global: bool = False) -> MetaQLResult:
        """
        Execute a MetaQL SELECT query.
        
        Args:
            select_query: MetaQL SELECT query object
            namespace_list: List of ontology namespaces
            account_id: Optional account ID
            is_global: Whether this is a global query
            
        Returns:
            MetaQLResult with query results
        """
        self.logger.info("Executing MetaQL SELECT query")
        # TODO: Implement MetaQL SELECT query execution
        raise NotImplementedError("metaql_select_query method not yet implemented")
    
    def metaql_graph_query(self, *, graph_query: MetaQLGraphQuery, namespace_list: List[Ontology] = None,
                          account_id: str | None = None, is_global: bool = False) -> MetaQLResult:
        """
        Execute a MetaQL GRAPH query.
        
        Args:
            graph_query: MetaQL GRAPH query object
            namespace_list: List of ontology namespaces
            account_id: Optional account ID
            is_global: Whether this is a global query
            
        Returns:
            MetaQLResult with query results
        """
        self.logger.info("Executing MetaQL GRAPH query")
        # TODO: Implement MetaQL GRAPH query execution
        raise NotImplementedError("metaql_graph_query method not yet implemented")
    
    # Import Operations
    def import_graph_batch(self, graph_id: str, object_generator: GraphObjectGenerator, *,
                          global_graph: bool = False, account_id: str | None = None,
                          purge_first: bool = True, batch_size: int = 10_000):
        """
        Import objects into a graph using a batch process.
        
        Args:
            graph_id: Graph identifier
            object_generator: Generator for graph objects
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            purge_first: Whether to purge graph before import
            batch_size: Size of import batches
        """
        self.logger.info(f"Starting batch import for graph: {graph_id}")
        # TODO: Implement batch import
        raise NotImplementedError("import_graph_batch method not yet implemented")
    
    def import_graph_batch_file(self, graph_id: str, file_path: str, *,
                               global_graph: bool = False, account_id: str | None = None,
                               purge_first: bool = True, batch_size: int = 10_000):
        """
        Import objects into a graph from a file using batch processing.
        
        Args:
            graph_id: Graph identifier
            file_path: Path to file containing objects
            global_graph: Whether this is a global graph
            account_id: Optional account ID
            purge_first: Whether to purge graph before import
            batch_size: Size of import batches
        """
        self.logger.info(f"Starting batch file import for graph: {graph_id} from {file_path}")
        # TODO: Implement batch file import
        raise NotImplementedError("import_graph_batch_file method not yet implemented")
    
    def import_multi_graph_batch(self, object_generator: GraphObjectGenerator, *,
                                use_account_id: bool = True, purge_first: bool = True,
                                batch_size: int = 10_000):
        """
        Import objects into multiple graphs using batch processing.
        
        Args:
            object_generator: Generator for graph objects
            use_account_id: Whether to use account ID from objects
            purge_first: Whether to purge graphs before import
            batch_size: Size of import batches
        """
        self.logger.info("Starting multi-graph batch import")
        # TODO: Implement multi-graph batch import
        raise NotImplementedError("import_multi_graph_batch method not yet implemented")
    
    def import_multi_graph_batch_file(self, file_path: str, *,
                                     use_account_id: bool = True, purge_first: bool = True,
                                     batch_size: int = 10_000):
        """
        Import objects into multiple graphs from a file using batch processing.
        
        Args:
            file_path: Path to file containing objects
            use_account_id: Whether to use account ID from objects
            purge_first: Whether to purge graphs before import
            batch_size: Size of import batches
        """
        self.logger.info(f"Starting multi-graph batch file import from {file_path}")
        # TODO: Implement multi-graph batch file import
        raise NotImplementedError("import_multi_graph_batch_file method not yet implemented")


