"""
Fuseki dataset manager for FUSEKI_POSTGRESQL hybrid backend.
Handles per-space Fuseki datasets and graph operations.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
import aiohttp
import json
from urllib.parse import urljoin

from ...utils.resource_manager import track_session
from .fuseki_auth import FusekiAuthManager

logger = logging.getLogger(__name__)


class FusekiDatasetManager:
    """
    Manages Fuseki datasets for the FUSEKI_POSTGRESQL hybrid backend.
    
    Handles creation, deletion, and operations on per-space Fuseki datasets.
    Each space gets its own dedicated Fuseki dataset for optimal performance.
    Supports both basic authentication and Keycloak JWT authentication.
    """
    
    def __init__(self, fuseki_config: dict):
        """
        Initialize Fuseki dataset manager.
        
        Args:
            fuseki_config: Fuseki server configuration
        """
        self.config = fuseki_config
        self.server_url = fuseki_config.get('server_url', 'http://localhost:3030')
        self.username = fuseki_config.get('username', 'vitalgraph_user')
        self.password = fuseki_config.get('password', 'vitalgraph_pass')
        self.session = None
        
        # Keycloak JWT authentication
        self.enable_authentication = fuseki_config.get('enable_authentication', False)
        self.auth_manager: Optional[FusekiAuthManager] = None
        
        if self.enable_authentication:
            keycloak_config = fuseki_config.get('keycloak', {})
            if keycloak_config:
                try:
                    self.auth_manager = FusekiAuthManager(keycloak_config)
                    logger.info("Keycloak JWT authentication enabled for Fuseki")
                except Exception as e:
                    logger.error(f"Failed to initialize Keycloak authentication: {e}")
                    self.enable_authentication = False
        
        # Remove trailing slash from server URL
        if self.server_url.endswith('/'):
            self.server_url = self.server_url[:-1]
        
        logger.info(f"FusekiDatasetManager initialized for server: {self.server_url}")
    
    async def connect(self) -> bool:
        """Initialize HTTP session for Fuseki operations."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            
            # Create HTTP session with appropriate authentication
            if self.enable_authentication and self.auth_manager:
                # JWT authentication - no basic auth
                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    headers={'Content-Type': 'application/json'}
                )
                
                # Obtain initial JWT token
                token = await self.auth_manager.get_token(self.session)
                if not token:
                    logger.error("Failed to obtain JWT token for Fuseki authentication")
                    await self.session.close()
                    return False
                
                logger.info("JWT token obtained successfully for Fuseki")
            else:
                # Basic authentication
                auth = aiohttp.BasicAuth(self.username, self.password)
                self.session = aiohttp.ClientSession(
                    auth=auth,
                    timeout=timeout,
                    headers={'Content-Type': 'application/json'}
                )
            
            # Track the session for proper cleanup
            track_session(self.session)
            
            # Test connection to Fuseki server
            headers = {}
            if self.enable_authentication and self.auth_manager:
                headers.update(self.auth_manager.get_auth_headers())
            
            async with self.session.get(f"{self.server_url}/$/ping", headers=headers) as response:
                if response.status == 200:
                    logger.info("Connected to Fuseki server successfully")
                    return True
                else:
                    logger.error(f"Fuseki server ping failed: {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to connect to Fuseki server: {e}")
            return False
    
    async def _get_request_headers(self, additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Get HTTP headers with authentication for Fuseki requests.
        
        Args:
            additional_headers: Optional additional headers to include
            
        Returns:
            Dictionary of headers including authentication if enabled
        """
        headers = additional_headers.copy() if additional_headers else {}
        
        # Add JWT authentication headers if enabled
        if self.enable_authentication and self.auth_manager:
            # Refresh token if needed
            await self.auth_manager.refresh_token_if_needed(self.session)
            # Add authorization header
            headers.update(self.auth_manager.get_auth_headers())
        
        return headers
    
    async def disconnect(self) -> bool:
        """Close HTTP session with proper cleanup."""
        try:
            if self.session:
                # Ensure all connections are properly closed
                await self.session.close()
                # Give time for the session to fully close
                import asyncio
                await asyncio.sleep(0.1)
                self.session = None
            
            logger.info("Disconnected from Fuseki server")
            return True
            
        except Exception as e:
            logger.error(f"Error disconnecting from Fuseki server: {e}")
            return False
    
    def get_dataset_name(self, space_id: str) -> str:
        """Get Fuseki dataset name for a space."""
        return f"vitalgraph_space_{space_id}"
    
    async def create_dataset(self, space_id: str) -> bool:
        """
        Create a new Fuseki dataset for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if dataset created successfully, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.info(f"Creating Fuseki dataset: {dataset_name}")
            
            # Create dataset using Fuseki admin API
            # Use URL parameters instead of form data
            params = {
                "dbName": dataset_name,
                "dbType": "tdb2"
            }
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            async with self.session.post(
                f"{self.server_url}/$/datasets",
                params=params,
                headers=headers
            ) as response:
                if response.status in [200, 201]:
                    logger.info(f"Fuseki dataset created successfully: {dataset_name}")
                    return True
                elif response.status == 409:
                    logger.info(f"Fuseki dataset already exists: {dataset_name}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create Fuseki dataset {dataset_name}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error creating Fuseki dataset {dataset_name}: {e}")
            return False
    
    async def delete_dataset(self, space_id: str) -> bool:
        """
        Delete a Fuseki dataset for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if dataset deleted successfully, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.info(f"Deleting Fuseki dataset: {dataset_name}")
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # Delete dataset using Fuseki admin API
            async with self.session.delete(
                f"{self.server_url}/$/datasets/{dataset_name}",
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    logger.info(f"Fuseki dataset deleted successfully: {dataset_name}")
                    return True
                elif response.status == 404:
                    logger.info(f"Fuseki dataset not found (already deleted): {dataset_name}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete Fuseki dataset {dataset_name}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting Fuseki dataset {dataset_name}: {e}")
            return False
    
    async def list_datasets(self) -> List[str]:
        """
        List all available Fuseki datasets.
        
        Returns:
            List of dataset names
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # Get datasets using Fuseki admin API
            async with self.session.get(f"{self.server_url}/$/datasets", headers=headers) as response:
                if response.status == 200:
                    datasets_info = await response.json()
                    datasets = datasets_info.get('datasets', [])
                    
                    # Extract dataset names (remove leading slash)
                    dataset_names = []
                    for dataset in datasets:
                        name = dataset.get('ds.name', '')
                        if name.startswith('/'):
                            name = name[1:]  # Remove leading slash
                        if name:
                            dataset_names.append(name)
                    
                    return dataset_names
                else:
                    logger.error(f"Failed to list Fuseki datasets: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error listing Fuseki datasets: {e}")
            return []
    
    async def dataset_exists(self, space_id: str) -> bool:
        """
        Check if a Fuseki dataset exists for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if dataset exists, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # Check dataset existence using Fuseki admin API
            async with self.session.get(f"{self.server_url}/$/datasets", headers=headers) as response:
                if response.status == 200:
                    datasets_info = await response.json()
                    datasets = datasets_info.get('datasets', [])
                    
                    logger.debug(f"🔍 Fuseki datasets list: {datasets}")
                    logger.debug(f"🔍 Looking for dataset: {dataset_name}")
                    
                    for dataset in datasets:
                        ds_name = dataset.get('ds.name', '')
                        logger.debug(f"🔍 Found dataset: {ds_name}")
                        if ds_name == f"/{dataset_name}" or ds_name == dataset_name:
                            logger.info(f"✅ Dataset {dataset_name} found!")
                            return True
                    
                    logger.debug(f"❌ Dataset {dataset_name} not found in list")
                    return False
                else:
                    logger.error(f"Failed to list Fuseki datasets: {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error checking Fuseki dataset existence {dataset_name}: {e}")
            return False
    
    async def add_quads_to_dataset(self, space_id: str, quads: List[tuple], 
                                   convert_float_to_decimal: bool = False) -> bool:
        """
        Add RDF quads to a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to add
            convert_float_to_decimal: If True, convert xsd:float to xsd:decimal
                                     to preserve precision in Fuseki (default: False)
            
        Returns:
            True if quads added successfully, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Adding {len(quads)} quads to Fuseki dataset: {dataset_name}")
            logger.info(f"🔍 add_quads_to_dataset: space_id={space_id}, dataset_name={dataset_name}")
            
            # Log the type of the first quad's components to diagnose the issue
            if quads:
                first_quad = quads[0]
                if len(first_quad) >= 4:
                    s, p, o, g = first_quad[:4]
                    logger.info(f"🔍 First quad types: S={type(s).__name__}, P={type(p).__name__}, O={type(o).__name__}, G={type(g).__name__}")
                    logger.info(f"🔍 First quad values: S={repr(s)}, P={repr(p)}, O={repr(o)[:100] if len(repr(o)) > 100 else repr(o)}")
            
            
            # Convert quads to SPARQL INSERT DATA format with optional float-to-decimal conversion
            insert_data_content = self._quads_to_sparql_insert_data(quads, convert_float_to_decimal)
            # logger.info(f"🔍 Generated SPARQL INSERT DATA content:\n{insert_data_content}")
            
            # Upload data using SPARQL UPDATE with proper graph syntax
            # Ensure proper indentation and no line break issues
            formatted_content = insert_data_content.strip()
            update_query = f"""INSERT DATA {{
{formatted_content}
}}"""
            
            
            # logger.info(f"🔍 Generated SPARQL UPDATE query:\n{update_query}")
            
            fuseki_url = f"{self.server_url}/{dataset_name}/update"
            logger.info(f"🔍 Fuseki request URL: {fuseki_url}")
            logger.info(f"🔍 Dataset name: {dataset_name}")
            logger.info(f"🔍 Space ID: {space_id}")
            # logger.info(f"🔍 Full SPARQL UPDATE request:\n{update_query}")
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            headers['Content-Type'] = 'application/sparql-update'
            logger.info(f"🔍 Request headers: {headers}")
            
            async with self.session.post(
                fuseki_url,
                data=update_query,
                headers=headers
            ) as response:
                response_text = await response.text()
                response_headers = dict(response.headers)
                logger.info(f"🔍 Full Fuseki response:")
                logger.info(f"🔍   Status: {response.status}")
                logger.info(f"🔍   Headers: {response_headers}")
                logger.info(f"🔍   Body: '{response_text}'")
                
                if response.status in [200, 204]:
                    logger.info(f"✅ Fuseki INSERT DATA successful: {dataset_name}")
                    return True
                else:
                    logger.error(f"❌ Failed to add quads to dataset {dataset_name}: {response.status} - {response_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error adding quads to dataset {dataset_name}: {e}")
            return False
    
    async def query_dataset(self, space_id: str, sparql_query: str) -> List[tuple]:
        """
        Execute SPARQL query on a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL query to execute
            
        Returns:
            Query results as list of dictionaries
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Executing SPARQL query on dataset: {dataset_name}")
            
            # Get headers with authentication
            headers = await self._get_request_headers({
                'Content-Type': 'application/sparql-query',
                'Accept': 'application/sparql-results+json'
            })
            
            async with self.session.post(
                f"{self.server_url}/{dataset_name}/sparql",
                data=sparql_query,
                headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # Handle ASK queries which return boolean results
                    if 'boolean' in result:
                        return result  # Return the full result for ASK queries
                    else:
                        return result.get('results', {}).get('bindings', [])
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL query failed on dataset {dataset_name}: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL query on dataset {dataset_name}: {e}")
            return []
    
    async def construct_dataset(self, space_id: str, sparql_construct: str) -> List[tuple]:
        """
        Execute SPARQL CONSTRUCT query on a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            sparql_construct: SPARQL CONSTRUCT query to execute
            
        Returns:
            Constructed triples as list of tuples
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Executing SPARQL CONSTRUCT query on dataset: {dataset_name}")
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            headers['Content-Type'] = 'application/sparql-query'
            headers['Accept'] = 'application/n-triples'
            
            async with self.session.post(
                f"{self.server_url}/{dataset_name}/sparql",
                data=sparql_construct,
                headers=headers
            ) as response:
                if response.status == 200:
                    ntriples_text = await response.text()
                    # Parse N-Triples format using RDFLib to get proper RDF objects
                    from rdflib import Graph
                    graph = Graph()
                    try:
                        graph.parse(data=ntriples_text, format='nt')
                        triples = list(graph)
                        return triples
                    except Exception as parse_error:
                        logger.error(f"Error parsing N-Triples response: {parse_error}")
                        return []
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL CONSTRUCT failed on dataset {dataset_name}: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL CONSTRUCT on dataset {dataset_name}: {e}")
            return []
    
    async def update_dataset(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute SPARQL UPDATE against dataset.
        
        Args:
            space_id: Space identifier
            sparql_update: SPARQL UPDATE query
            
        Returns:
            True if update successful, False otherwise
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            logger.debug(f"Executing SPARQL UPDATE on dataset: {dataset_name}")
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            headers['Content-Type'] = 'application/sparql-update'
            headers['Accept'] = 'application/json'
            
            async with self.session.post(
                f"{self.server_url}/{dataset_name}/update",
                data=sparql_update,
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    logger.debug(f"SPARQL UPDATE successful on dataset {dataset_name}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL UPDATE failed on dataset {dataset_name}: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL UPDATE on dataset {dataset_name}: {e}")
            return False
    
    async def get_dataset_info(self, space_id: str, graph_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get information about a Fuseki dataset.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Dataset information dictionary or None if not found
        """
        if not self.session:
            raise RuntimeError("Not connected to Fuseki server")
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            # Get dataset stats using SPARQL query
            if graph_id:
                count_query = f"SELECT (COUNT(*) AS ?count) WHERE {{ GRAPH <{graph_id}> {{ ?s ?p ?o }} }}"
                logger.info(f"🔍 Counting triples in specific graph: {graph_id}")
            else:
                count_query = "SELECT (COUNT(*) AS ?count) WHERE { GRAPH ?g { ?s ?p ?o } }"
                logger.info(f"🔍 Counting triples across all graphs using GRAPH ?g")
            
            # Use POST method for SPARQL queries (standard approach)
            query_url = f"{self.server_url}/{dataset_name}/sparql"
            logger.info(f"🔍 Querying dataset for count: {query_url}")
            
            # Get headers with authentication
            headers = await self._get_request_headers({
                'Content-Type': 'application/sparql-query',
                'Accept': 'application/json'
            })
            
            async with self.session.post(
                query_url,
                data=count_query,
                headers=headers
            ) as response:
                logger.info(f"🔍 Fuseki query response status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"🔍 Fuseki query result: {result}")
                    bindings = result.get('results', {}).get('bindings', [])
                    logger.info(f"🔍 Bindings count: {len(bindings)}")
                    
                    if bindings:
                        # Fuseki HTTP JSON responses always return dict bindings
                        binding = bindings[0]
                        count = int(binding.get('count', {}).get('value', 0))
                        return {
                            'dataset_name': dataset_name,
                            'space_id': space_id,
                            'triple_count': count,
                            'server_url': self.server_url
                        }
                    
                    logger.warning(f"🔍 No bindings returned from Fuseki query for {dataset_name}")
                    return None
                else:
                    response_text = await response.text()
                    logger.error(f"🔍 Fuseki query failed with status {response.status}: {response_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting dataset info for {dataset_name}: {e}")
            return None
    
    def _quads_to_sparql_insert_data(self, quads: List[tuple], convert_float_to_decimal: bool = False) -> str:
        """
        Convert quads to SPARQL INSERT DATA format with proper GRAPH stanzas.
        Groups triples by unique graph URI and creates separate GRAPH blocks.
        
        Args:
            quads: List of quad tuples (subject, predicate, object, graph)
            convert_float_to_decimal: If True, convert xsd:float to xsd:decimal
                                     to preserve precision in Fuseki (default: False)
            
        Returns:
            SPARQL INSERT DATA formatted string with GRAPH blocks
        """
        # Group triples by unique graph URI
        graphs_data = {}
        
        for quad in quads:
            # Handle tuple format: (subject, predicate, object, graph)
            if len(quad) >= 4:
                subject, predicate, obj, graph = quad[:4]
            else:
                subject, predicate, obj = quad[:3]
                graph = 'default'
            
            # Log the types of quad components to diagnose formatting issues
            # logger.info(f"🔍 Quad component types: S={type(subject).__name__}, P={type(predicate).__name__}, O={type(obj).__name__}")
            
            # Format terms with float-to-decimal conversion
            subject = self._format_term(subject, convert_float_to_decimal)
            predicate = self._format_term(predicate, convert_float_to_decimal)
            obj = self._format_term(obj, convert_float_to_decimal)
            
            # Keep graph as raw value for grouping, format later
            graph_key = str(graph) if graph != 'default' else 'default'
            
            # logger.info(f"🔍 Processing quad: S={subject}, P={predicate}, O={obj}, G={graph_key}")
            
            if subject and predicate and obj:
                if graph_key not in graphs_data:
                    graphs_data[graph_key] = []
                graphs_data[graph_key].append(f"                    {subject} {predicate} {obj} .")
        
        # Generate separate GRAPH stanza for each unique graph URI
        graph_stanzas = []
        for graph_uri, triples in graphs_data.items():
            if graph_uri == 'default':
                # Default graph triples (no GRAPH wrapper needed)
                graph_stanzas.extend(triples)
            else:
                # Named graph - create GRAPH stanza
                # Validate that graph_uri is a proper URI
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                if not validate_rfc3986(str(graph_uri), rule='URI'):
                    logger.error(f"❌ Invalid graph URI: {graph_uri} - must be a valid URI with scheme")
                    raise ValueError(f"Invalid graph URI: {graph_uri} - must be a valid URI with scheme (e.g., http://...)")
                
                formatted_graph = self._format_term(graph_uri, convert_float_to_decimal)
                if not formatted_graph:
                    logger.error(f"❌ Failed to format graph URI: {graph_uri}")
                    raise ValueError(f"Failed to format graph URI: {graph_uri}")
                    
                graph_stanzas.append(f"                GRAPH {formatted_graph} {{")
                graph_stanzas.extend(triples)
                graph_stanzas.append(f"                }}")
        
        logger.info(f"🔍 Generated {len(graphs_data)} graph stanzas for {len(quads)} quads")
        return '\n'.join(graph_stanzas)
    
    def _format_term(self, term: Any, convert_float_to_decimal: bool = False) -> Optional[str]:
        """
        Format an RDF term for N-Quads.
        
        Args:
            term: RDF term (URI, literal, or blank node)
            convert_float_to_decimal: If True, convert xsd:float to xsd:decimal
                                     to preserve precision in Fuseki (default: False)
            
        Returns:
            Formatted term string or None
        """
        if not term:
            return None
        
        # Handle RDFLib objects
        try:
            from rdflib import URIRef, Literal, BNode
            
            # logger.info(f"🔍 _format_term input: {term} (type: {type(term).__name__})")
            
            if isinstance(term, URIRef):
                # Ensure clean URI formatting - strip any existing angle brackets
                clean_uri = str(term).strip('<>')
                result = f"<{clean_uri}>"
                # logger.info(f"🔍 URIRef formatted: {result}")
                return result
            elif isinstance(term, Literal):
                # Escape backslashes and double quotes in literal values for SPARQL
                escaped_value = str(term).replace('\\', '\\\\').replace('"', '\\"')
                
                if term.language:
                    result = f'"{escaped_value}"@{term.language}'
                elif term.datatype:
                    datatype_str = str(term.datatype)
                    # Convert xsd:float to xsd:decimal to preserve precision in Fuseki
                    if convert_float_to_decimal and datatype_str == 'http://www.w3.org/2001/XMLSchema#float':
                        datatype_str = 'http://www.w3.org/2001/XMLSchema#decimal'
                        logger.debug(f"Converting float to decimal for value: {escaped_value}")
                    result = f'"{escaped_value}"^^<{datatype_str}>'
                else:
                    result = f'"{escaped_value}"'
                # logger.info(f"🔍 Literal formatted: {result}")
                return result
            elif isinstance(term, BNode):
                result = f"_:{term}"
                # logger.info(f"🔍 BNode formatted: {result}")
                return result
        except ImportError:
            pass
        
        if isinstance(term, dict):
            term_type = term.get('type')
            value = term.get('value')
            
            if term_type == 'uri':
                # Ensure clean URI formatting - strip any existing angle brackets
                clean_uri = str(value).strip('<>')
                return f"<{clean_uri}>"
            elif term_type == 'literal':
                datatype = term.get('datatype')
                language = term.get('language')
                
                if language:
                    return f'"{value}"@{language}'
                elif datatype:
                    # Convert xsd:float to xsd:decimal to preserve precision in Fuseki
                    if convert_float_to_decimal and datatype == 'http://www.w3.org/2001/XMLSchema#float':
                        datatype = 'http://www.w3.org/2001/XMLSchema#decimal'
                        logger.debug(f"Converting float to decimal for value: {value}")
                    return f'"{value}"^^<{datatype}>'
                else:
                    return f'"{value}"'
            elif term_type == 'bnode':
                return f"_:{value}"
        
        elif isinstance(term, str):
            # Check if string looks like a URI, otherwise treat as literal
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if validate_rfc3986(term, rule='URI'):
                # Clean URI formatting - strip any existing angle brackets
                clean_uri = term.strip('<>')
                return f"<{clean_uri}>"
            else:
                # Treat as string literal - escape quotes and wrap in quotes
                escaped_literal = term.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                return f'"{escaped_literal}"'
        
        return None
    
    async def ask_dataset(self, space_id: str, sparql_query: str) -> bool:
        """
        Execute SPARQL ASK query against a dataset.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL ASK query to execute
            
        Returns:
            bool: True if ASK query returns true, False otherwise
        """
        if not self.session:
            logger.error("FusekiDatasetManager not connected")
            return False
        
        dataset_name = self.get_dataset_name(space_id)
        
        try:
            # Construct query URL for the dataset
            query_url = f"{self.server_url}/{dataset_name}/sparql"
            
            # Get headers with authentication
            headers = await self._get_request_headers()
            headers['Content-Type'] = 'application/sparql-query'
            headers['Accept'] = 'application/sparql-results+json'
            
            # Execute ASK query using POST with proper headers
            async with self.session.post(
                query_url,
                data=sparql_query,
                headers=headers
            ) as response:
                if response.status == 200:
                    # Parse JSON response for ASK query
                    result = await response.json()
                    
                    # ASK queries return {"boolean": true/false}
                    if isinstance(result, dict) and 'boolean' in result:
                        return result['boolean']
                    else:
                        logger.warning(f"Unexpected ASK query response format: {result}")
                        return False
                        
                else:
                    logger.error(f"ASK query failed with status {response.status}: {await response.text()}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error executing ASK query on dataset {dataset_name}: {e}")
            return False
