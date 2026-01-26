"""
Admin dataset implementation for VitalGraph space management.

Manages separate Fuseki dataset: vitalgraph_admin
Replicates PostgreSQL admin tables as RDF:
- Install: Installation metadata and state
- Space: Space registry with tenant isolation  
- User: User management with authentication
- Graph: Graph tracking within each space
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
import aiohttp
from datetime import datetime
import json
from urllib.parse import urljoin

from ...utils.resource_manager import track_session
from .fuseki_auth import FusekiAuthManager
import json

logger = logging.getLogger(__name__)


class FusekiAdminDataset:
    """
    Admin dataset implementation for VitalGraph space management.
    
    Manages separate Fuseki dataset: vitalgraph_admin
    Replicates PostgreSQL admin tables as RDF:
    - Install: Installation metadata and state
    - Space: Space registry with tenant isolation  
    - User: User management with authentication
    - Graph: Graph tracking within each space
    
    Supports both basic authentication and Keycloak JWT authentication.
    """
    
    ADMIN_DATASET = "vitalgraph_admin"
    
    # RDF Classes (equivalent to PostgreSQL tables)
    INSTALL_CLASS = "http://vital.ai/admin/Install"
    SPACE_CLASS = "http://vital.ai/admin/Space"
    USER_CLASS = "http://vital.ai/admin/User"
    GRAPH_CLASS = "http://vital.ai/admin/Graph"
    
    # RDF Properties
    PROPERTIES = {
        # Install properties
        'install_datetime': 'http://vital.ai/admin/installDateTime',
        'update_datetime': 'http://vital.ai/admin/updateDateTime',
        'active': 'http://vital.ai/admin/active',
        
        # Space properties
        'space_id': 'http://vital.ai/admin/spaceId',
        'space_name': 'http://vital.ai/admin/spaceName',
        'space_description': 'http://vital.ai/admin/spaceDescription',
        'tenant': 'http://vital.ai/admin/tenant',
        'update_time': 'http://vital.ai/admin/updateTime',
        
        # User properties
        'username': 'http://vital.ai/admin/username',
        'password': 'http://vital.ai/admin/password',
        'email': 'http://vital.ai/admin/email',
        
        # Graph properties
        'graph_uri': 'http://vital.ai/admin/graphUri',
        'graph_name': 'http://vital.ai/admin/graphName',
        'created_time': 'http://vital.ai/admin/createdTime',
        'triple_count': 'http://vital.ai/admin/tripleCount'
    }
    
    def __init__(self, fuseki_config: dict):
        """
        Initialize admin dataset manager.
        
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
                    logger.info("Keycloak JWT authentication enabled for admin dataset")
                except Exception as e:
                    logger.error(f"Failed to initialize Keycloak authentication: {e}")
                    self.enable_authentication = False
        
        # Remove trailing slash from server URL
        if self.server_url.endswith('/'):
            self.server_url = self.server_url[:-1]
        
        # Admin dataset endpoints
        self.admin_query_url = f"{self.server_url}/{self.ADMIN_DATASET}/sparql"
        self.admin_update_url = f"{self.server_url}/{self.ADMIN_DATASET}/update"
        
        logger.info(f"FusekiAdminDataset initialized for admin dataset: {self.ADMIN_DATASET}")
    
    async def connect(self) -> bool:
        """Initialize HTTP session for admin dataset operations."""
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
                    logger.error("Failed to obtain JWT token for admin dataset authentication")
                    await self.session.close()
                    return False
                
                logger.info("JWT token obtained successfully for admin dataset")
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
            
            logger.info("FusekiAdminDataset session initialized")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing FusekiAdminDataset session: {e}")
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
                await self.session.close()
                # Give time for the session to fully close
                import asyncio
                await asyncio.sleep(0.1)
                self.session = None
            logger.info("FusekiAdminDataset session closed")
            return True
        except Exception as e:
            logger.error(f"Error closing FusekiAdminDataset session: {e}")
            return False
    
    async def initialize_admin_dataset(self) -> bool:
        """Create admin dataset and initialize with schema."""
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            
            # First create the admin dataset via HTTP Admin API
            # Use URL parameters instead of form data
            admin_api_url = f"{self.server_url}/$/datasets"
            
            params = {
                "dbName": self.ADMIN_DATASET,
                "dbType": "tdb2"
            }
            
            async with self.session.post(
                admin_api_url,
                params=params,
                headers=headers
            ) as response:
                if response.status in [200, 201]:
                    logger.info(f"Admin dataset {self.ADMIN_DATASET} created successfully")
                elif response.status == 409:
                    logger.info(f"Admin dataset {self.ADMIN_DATASET} already exists")
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create admin dataset: {response.status} - {error_text}")
                    return False
            
            # Initialize with basic schema/ontology
            await self._initialize_schema()
            
            return True
            
        except Exception as e:
            logger.error(f"Error initializing admin dataset: {e}")
            return False
    
    async def _initialize_schema(self) -> bool:
        """Initialize admin dataset with RDF schema/ontology."""
        try:
            # Insert basic ontology definitions
            schema_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            
            INSERT DATA {{
                # Class definitions
                <{self.INSTALL_CLASS}> rdf:type rdfs:Class ;
                    rdfs:label "Install" ;
                    rdfs:comment "Installation metadata and state" .
                
                <{self.SPACE_CLASS}> rdf:type rdfs:Class ;
                    rdfs:label "Space" ;
                    rdfs:comment "VitalGraph space registry" .
                
                <{self.USER_CLASS}> rdf:type rdfs:Class ;
                    rdfs:label "User" ;
                    rdfs:comment "User management" .
                
                <{self.GRAPH_CLASS}> rdf:type rdfs:Class ;
                    rdfs:label "Graph" ;
                    rdfs:comment "Graph tracking within spaces" .
            }}
            """
            
            return await self._execute_update(schema_sparql)
            
        except Exception as e:
            logger.error(f"Error initializing admin dataset schema: {e}")
            return False
    
    async def create_install_record(self) -> bool:
        """Create initial install record (equivalent to PostgreSQL Install table)."""
        try:
            install_uri = f"http://vital.ai/admin/install/{datetime.now().isoformat()}"
            now = datetime.now().isoformat()
            
            install_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            INSERT DATA {{
                <{install_uri}> a <{self.INSTALL_CLASS}> ;
                    <{self.PROPERTIES['install_datetime']}> "{now}"^^<http://www.w3.org/2001/XMLSchema#dateTime> ;
                    <{self.PROPERTIES['update_datetime']}> "{now}"^^<http://www.w3.org/2001/XMLSchema#dateTime> ;
                    <{self.PROPERTIES['active']}> true .
            }}
            """
            
            success = await self._execute_update(install_sparql)
            if success:
                logger.info(f"Install record created: {install_uri}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error creating install record: {e}")
            return False
    
    async def register_space(self, space_id: str, space_name: str, 
                           space_description: str = None, tenant: str = None) -> bool:
        """Register new space in admin dataset."""
        try:
            space_uri = f"http://vital.ai/admin/space/{space_id}"
            now = datetime.now().isoformat()
            
            # Build SPARQL INSERT with proper semicolon handling
            sparql_parts = [
                f"<{space_uri}> a <{self.SPACE_CLASS}> ;",
                f'    <{self.PROPERTIES["space_id"]}> "{space_id}" ;',
                f'    <{self.PROPERTIES["space_name"]}> "{space_name}" ;'
            ]
            
            if space_description:
                sparql_parts.append(f'    <{self.PROPERTIES["space_description"]}> "{space_description}" ;')
            
            if tenant:
                sparql_parts.append(f'    <{self.PROPERTIES["tenant"]}> "{tenant}" ;')
            
            # Add update_time as the last property with period
            sparql_parts.append(f'    <{self.PROPERTIES["update_time"]}> "{now}"^^<http://www.w3.org/2001/XMLSchema#dateTime> .')
            
            register_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            INSERT DATA {{
                {chr(10).join(sparql_parts)}
            }}
            """
            
            success = await self._execute_update(register_sparql)
            if success:
                logger.info(f"Space registered in admin dataset: {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error registering space {space_id}: {e}")
            return False
    
    async def unregister_space(self, space_id: str) -> bool:
        """Remove space from admin dataset."""
        try:
            unregister_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            DELETE WHERE {{
                ?space a <{self.SPACE_CLASS}> ;
                       <{self.PROPERTIES['space_id']}> "{space_id}" ;
                       ?p ?o .
            }}
            """
            
            success = await self._execute_update(unregister_sparql)
            if success:
                logger.info(f"Space unregistered from admin dataset: {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error unregistering space {space_id}: {e}")
            return False
    
    async def register_graph(self, space_id: str, graph_uri: str, 
                           graph_name: str = None) -> bool:
        """Register graph within a space."""
        try:
            graph_record_uri = f"http://vital.ai/admin/graph/{space_id}/{hash(graph_uri)}"
            now = datetime.now().isoformat()
            
            sparql_parts = [
                f"<{graph_record_uri}> a <{self.GRAPH_CLASS}> ;",
                f'    <{self.PROPERTIES["space_id"]}> "{space_id}" ;',
                f'    <{self.PROPERTIES["graph_uri"]}> "{graph_uri}" ;',
                f'    <{self.PROPERTIES["created_time"]}> "{now}"^^<http://www.w3.org/2001/XMLSchema#dateTime>'
            ]
            
            if graph_name:
                sparql_parts.append(f'    <{self.PROPERTIES["graph_name"]}> "{graph_name}" ;')
            
            # Remove trailing semicolon and add period
            sparql_parts[-1] = sparql_parts[-1].rstrip(' ;') + ' .'
            
            register_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            INSERT DATA {{
                {chr(10).join(sparql_parts)}
            }}
            """
            
            success = await self._execute_update(register_sparql)
            if success:
                logger.info(f"Graph registered in admin dataset: {graph_uri} for space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error registering graph {graph_uri} for space {space_id}: {e}")
            return False
    
    async def list_spaces(self) -> List[Dict[str, Any]]:
        """List all registered spaces with metadata."""
        try:
            list_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            SELECT ?space_id ?space_name ?space_description ?tenant ?update_time
            WHERE {{
                ?space a <{self.SPACE_CLASS}> ;
                       <{self.PROPERTIES['space_id']}> ?space_id ;
                       <{self.PROPERTIES['space_name']}> ?space_name .
                
                OPTIONAL {{ ?space <{self.PROPERTIES['space_description']}> ?space_description }}
                OPTIONAL {{ ?space <{self.PROPERTIES['tenant']}> ?tenant }}
                OPTIONAL {{ ?space <{self.PROPERTIES['update_time']}> ?update_time }}
            }}
            ORDER BY ?space_id
            """
            
            results = await self._execute_query(list_sparql)
            
            spaces = []
            for result in results:
                space_info = {
                    'space_id': result.get('space_id', {}).get('value'),
                    'space_name': result.get('space_name', {}).get('value'),
                    'space_description': result.get('space_description', {}).get('value'),
                    'tenant': result.get('tenant', {}).get('value'),
                    'update_time': result.get('update_time', {}).get('value')
                }
                spaces.append(space_info)
            
            return spaces
            
        except Exception as e:
            logger.error(f"Error listing spaces: {e}")
            return []
    
    async def list_graphs_for_space(self, space_id: str) -> List[Dict[str, Any]]:
        """List all graphs within a specific space."""
        try:
            list_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            SELECT ?graph_uri ?graph_name ?created_time
            WHERE {{
                ?graph a <{self.GRAPH_CLASS}> ;
                       <{self.PROPERTIES['space_id']}> "{space_id}" ;
                       <{self.PROPERTIES['graph_uri']}> ?graph_uri .
                
                OPTIONAL {{ ?graph <{self.PROPERTIES['graph_name']}> ?graph_name }}
                OPTIONAL {{ ?graph <{self.PROPERTIES['created_time']}> ?created_time }}
            }}
            ORDER BY ?graph_uri
            """
            
            results = await self._execute_query(list_sparql)
            
            graphs = []
            for result in results:
                graph_info = {
                    'graph_uri': result.get('graph_uri', {}).get('value'),
                    'graph_name': result.get('graph_name', {}).get('value'),
                    'created_time': result.get('created_time', {}).get('value')
                }
                graphs.append(graph_info)
            
            return graphs
            
        except Exception as e:
            logger.error(f"Error listing graphs for space {space_id}: {e}")
            return []
    
    async def get_space_info(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed space information from admin dataset."""
        try:
            info_sparql = f"""
            PREFIX admin: <http://vital.ai/admin/>
            
            SELECT ?space_name ?space_description ?tenant ?update_time
            WHERE {{
                ?space a <{self.SPACE_CLASS}> ;
                       <{self.PROPERTIES['space_id']}> "{space_id}" ;
                       <{self.PROPERTIES['space_name']}> ?space_name .
                
                OPTIONAL {{ ?space <{self.PROPERTIES['space_description']}> ?space_description }}
                OPTIONAL {{ ?space <{self.PROPERTIES['tenant']}> ?tenant }}
                OPTIONAL {{ ?space <{self.PROPERTIES['update_time']}> ?update_time }}
            }}
            """
            
            results = await self._execute_query(info_sparql)
            
            if results:
                result = results[0]
                return {
                    'space_id': space_id,
                    'space_name': result.get('space_name', {}).get('value'),
                    'space_description': result.get('space_description', {}).get('value'),
                    'tenant': result.get('tenant', {}).get('value'),
                    'update_time': result.get('update_time', {}).get('value')
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting space info for {space_id}: {e}")
            return None
    
    async def _execute_query(self, sparql_query: str) -> List[Dict[str, Any]]:
        """Execute SPARQL query against admin dataset."""
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            headers['Content-Type'] = 'application/sparql-query'
            headers['Accept'] = 'application/json'
            
            async with self.session.post(
                self.admin_query_url,
                data=sparql_query,
                headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('results', {}).get('bindings', [])
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL query failed: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL query: {e}")
            return []
    
    async def _execute_update(self, sparql_update: str) -> bool:
        """Execute SPARQL update against admin dataset."""
        try:
            # Get headers with authentication
            headers = await self._get_request_headers()
            headers['Content-Type'] = 'application/sparql-update'
            
            async with self.session.post(
                self.admin_update_url,
                data=sparql_update,
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"SPARQL update failed: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error executing SPARQL update: {e}")
            return False
