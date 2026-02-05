#!/usr/bin/env python3
"""
Inspect Lead Data Script

This script directly queries the lead dataset to find actual frame and slot values
that can be used in KGQuery frame queries. It inspects the space_lead_dataset_test
to discover what criteria are available for filtering leads.

It queries to find:
1. Available frame types and their counts
2. Available slot types within each frame
3. Actual slot values (for text, boolean, numeric slots)
4. Distribution of values to identify good filter criteria
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging BEFORE imports to capture all module logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"Loaded environment variables from {env_path}\n")
else:
    logger.warning(f".env file not found at {env_path}\n")

from vitalgraph.config.config_loader import get_config


class LeadDataInspector:
    """Inspect lead data to find usable frame query criteria."""
    
    def __init__(self, space_id: str = "space_lead_dataset_test"):
        """Initialize the inspector.
        
        Args:
            space_id: Space identifier to inspect (default: space_lead_dataset_test)
        """
        # Load configuration using VitalGraph config loader (profile-based)
        config = get_config()
        fuseki_config = config.get_fuseki_config()
        keycloak_config = fuseki_config.get('keycloak', {})
        
        # Fuseki configuration from profile-based config
        self.fuseki_url = fuseki_config.get('server_url')
        
        # Keycloak configuration for authentication
        self.keycloak_url = keycloak_config.get('url')
        self.keycloak_realm = keycloak_config.get('realm')
        self.keycloak_client_id = keycloak_config.get('client_id')
        self.keycloak_client_secret = keycloak_config.get('client_secret')
        self.keycloak_username = keycloak_config.get('username')
        self.keycloak_password = keycloak_config.get('password')
        
        # JWT token storage
        self.access_token = None
        
        # Test space configuration
        self.space_id = space_id
        self.dataset_name = f"vitalgraph_space_{self.space_id}"
        self.graph_id = "urn:lead_entity_graph_dataset"
        
        # Determine if authentication is needed
        self.needs_auth = 'localhost' not in self.fuseki_url and '127.0.0.1' not in self.fuseki_url
        
        logger.info(f"✅ Initialized Lead Data Inspector")
        logger.info(f"   Fuseki URL: {self.fuseki_url}")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}")
        logger.info(f"   Authentication: {'Required' if self.needs_auth else 'Not required'}\n")
        
        # Get JWT token if needed
        if self.needs_auth:
            self._get_jwt_token()
    
    def _get_jwt_token(self) -> bool:
        """Obtain JWT token from Keycloak for Fuseki authentication.
        
        Returns:
            True if token obtained successfully, False otherwise
        """
        if not self.needs_auth:
            return True
            
        try:
            token_url = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"
            
            data = {
                'grant_type': 'password',
                'client_id': self.keycloak_client_id,
                'username': self.keycloak_username,
                'password': self.keycloak_password,
            }
            
            if self.keycloak_client_secret:
                data['client_secret'] = self.keycloak_client_secret
            
            response = requests.post(token_url, data=data, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                logger.info(f"✅ Successfully obtained JWT token from Keycloak\n")
                return True
            else:
                logger.error(f"❌ Failed to obtain JWT token: {response.status_code}")
                logger.error(f"   Response: {response.text}\n")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error obtaining JWT token: {e}\n")
            return False
    
    def query_fuseki(self, sparql_query: str, query_description: str, timeout: int = 30, use_post: bool = False) -> Optional[Dict[str, Any]]:
        """
        Execute a SPARQL query against the lead dataset in Fuseki.
        
        Args:
            sparql_query: SPARQL query to execute
            query_description: Description of what the query does
            timeout: Query timeout in seconds (default 30)
            use_post: If True, use POST instead of GET (for large queries)
            
        Returns:
            Query results as dictionary, or None if failed
        """
        query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
        
        logger.info(f"📊 {query_description}")
        
        headers = {
            'Accept': 'application/sparql-results+json',
        }
        
        # Add JWT token if authentication is needed
        if self.needs_auth and self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        
        try:
            if use_post:
                # Use POST with query in body for large queries
                headers['Content-Type'] = 'application/sparql-query'
                response = requests.post(
                    query_url,
                    data=sparql_query,
                    headers=headers,
                    timeout=timeout
                )
            else:
                # Use GET with query in params for small queries
                params = {
                    'query': sparql_query
                }
                response = requests.get(
                    query_url,
                    params=params,
                    headers=headers,
                    timeout=timeout
                )
            
            if response.status_code == 200:
                results = response.json()
                return results
            else:
                logger.error(f"   ❌ Query failed")
                logger.error(f"   Status code: {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ❌ Error executing query: {e}")
            return None
    
    def count_entities(self) -> int:
        """Count total lead entities."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?entity) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting total lead entities")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} lead entities\n")
                return count
        
        logger.error(f"   ❌ No entities found\n")
        return 0
    
    def list_frame_types(self) -> List[Dict[str, Any]]:
        """List all frame types and their counts."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?frameType (COUNT(?frame) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame vital-core:vitaltype haley-ai-kg:KGFrame .
                ?frame haley-ai-kg:hasKGFrameType ?frameType .
            }}
        }}
        GROUP BY ?frameType
        ORDER BY DESC(?count)
        """
        
        results = self.query_fuseki(query, "Listing frame types and counts")
        
        frame_types = []
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} frame type(s):\n")
                for binding in bindings:
                    frame_type = binding.get('frameType', {}).get('value', 'unknown')
                    count = int(binding.get('count', {}).get('value', 0))
                    frame_types.append({'type': frame_type, 'count': count})
                    logger.info(f"      • {frame_type}")
                    logger.info(f"        Count: {count} frames")
                logger.info("")
                return frame_types
        
        logger.error(f"   ❌ No frame types found\n")
        return []
    
    def list_slot_types_for_frame(self, frame_type: str) -> List[Dict[str, Any]]:
        """List all slot types within a specific frame type."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?slotType ?slotClass (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame vital-core:vitaltype haley-ai-kg:KGFrame .
                ?frame haley-ai-kg:hasKGFrameType <{frame_type}> .
                
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?frame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                
                ?slot haley-ai-kg:hasKGSlotType ?slotType .
                ?slot vital-core:vitaltype ?slotClass .
                FILTER(CONTAINS(STR(?slotClass), "Slot"))
            }}
        }}
        GROUP BY ?slotType ?slotClass
        ORDER BY DESC(?count)
        """
        
        results = self.query_fuseki(query, f"Listing slot types for {frame_type.split('#')[-1]}")
        
        slot_types = []
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} slot type(s):\n")
                for binding in bindings:
                    slot_type = binding.get('slotType', {}).get('value', 'unknown')
                    slot_class = binding.get('slotClass', {}).get('value', 'unknown')
                    count = int(binding.get('count', {}).get('value', 0))
                    slot_types.append({
                        'type': slot_type,
                        'class': slot_class,
                        'count': count
                    })
                    slot_class_short = slot_class.split('#')[-1] if '#' in slot_class else slot_class
                    logger.info(f"      • {slot_type}")
                    logger.info(f"        Class: {slot_class_short}")
                    logger.info(f"        Count: {count} slots")
                logger.info("")
                return slot_types
        
        logger.error(f"   ❌ No slot types found\n")
        return []
    
    def get_slot_values(self, frame_type: str, slot_type: str, slot_class: str, limit: int = 20) -> List[Any]:
        """Get actual values for a specific slot type."""
        # Determine value property based on slot class
        value_property = "haley-ai-kg:hasTextSlotValue"
        if "Boolean" in slot_class:
            value_property = "haley-ai-kg:hasBooleanSlotValue"
        elif "Integer" in slot_class or "Long" in slot_class:
            value_property = "haley-ai-kg:hasIntegerSlotValue"
        elif "Double" in slot_class or "Float" in slot_class:
            value_property = "haley-ai-kg:hasDoubleSlotValue"
        elif "DateTime" in slot_class:
            value_property = "haley-ai-kg:hasDateTimeSlotValue"
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?value (COUNT(?value) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame vital-core:vitaltype haley-ai-kg:KGFrame .
                ?frame haley-ai-kg:hasKGFrameType <{frame_type}> .
                
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?frame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                
                ?slot haley-ai-kg:hasKGSlotType <{slot_type}> .
                ?slot {value_property} ?value .
            }}
        }}
        GROUP BY ?value
        ORDER BY DESC(?count)
        LIMIT {limit}
        """
        
        slot_type_short = slot_type.split(':')[-1] if ':' in slot_type else slot_type
        results = self.query_fuseki(query, f"Getting values for slot {slot_type_short}")
        
        values = []
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} unique value(s):\n")
                for binding in bindings:
                    value = binding.get('value', {}).get('value', 'N/A')
                    count = int(binding.get('count', {}).get('value', 0))
                    values.append({'value': value, 'count': count})
                    logger.info(f"      • {value} (appears {count} times)")
                logger.info("")
                return values
        
        logger.error(f"   ❌ No values found\n")
        return []
    
    def check_entity_frame_edges(self) -> bool:
        """Check if entity-to-frame edges exist."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?edge) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?edge vital-core:hasEdgeSource ?entity .
                ?edge vital-core:hasEdgeDestination ?frame .
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                ?frame vital-core:vitaltype haley-ai-kg:KGFrame .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Checking entity-to-frame edges")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} entity-to-frame edges\n")
                return count > 0
        
        logger.error(f"   ❌ No entity-to-frame edges found\n")
        return False
    
    def check_frame_slot_edges(self) -> bool:
        """Check if frame-to-slot edges exist."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?edge) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?edge vital-core:hasEdgeSource ?frame .
                ?edge vital-core:hasEdgeDestination ?slot .
                ?frame vital-core:vitaltype haley-ai-kg:KGFrame .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Checking frame-to-slot edges")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} frame-to-slot edges\n")
                return count > 0
        
        logger.error(f"   ❌ No frame-to-slot edges found\n")
        return False
    
    def test_mql_query_normal_order(self) -> tuple:
        """Test MQL query with normal order: Entity → Frame → Slot."""
        import time
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?entity
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Entity type
                {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGNewsEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGProductEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGWebEntity .
                }}
                
                # Entity → Parent Frame
                ?frame_edge_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                ?frame_edge_0 vital-core:hasEdgeSource ?entity .
                ?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
                ?frame_0 haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusFrame> .
                
                # Parent Frame → Child Frame
                ?frame_edge_0_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                ?frame_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
                ?frame_edge_0_0 vital-core:hasEdgeDestination ?frame_0_0 .
                ?frame_0_0 haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusQualificationFrame> .
                
                # Child Frame → Slot
                ?slot_edge_0_0_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                ?slot_edge_0_0_0 vital-core:hasEdgeSource ?frame_0_0 .
                ?slot_edge_0_0_0 vital-core:hasEdgeDestination ?slot_0_0_0 .
                ?slot_0_0_0 haley-ai-kg:hasKGSlotType <urn:cardiff:kg:slot:MQLv2> .
                ?slot_0_0_0 haley-ai-kg:hasBooleanSlotValue true .
            }}
        }}
        ORDER BY ?entity
        """
        
        start_time = time.time()
        results = self.query_fuseki(query, "Testing MQL query - Normal order (edge-based)")
        query_time = time.time() - start_time
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            count = len(bindings)
            # Extract entities (already sorted by SPARQL ORDER BY ?entity)
            entities = [b['entity']['value'] for b in bindings]
            logger.info(f"   ✅ Found {count} MQL leads")
            logger.info(f"   ⏱️  Query time: {query_time:.3f}s\n")
            return (True, entities, query_time)
        
        logger.error(f"   ❌ Query failed\n")
        return (False, [], query_time)
    
    def test_mql_query_with_filters(self) -> bool:
        """Test MQL query using FILTER clauses for types and values."""
        import time
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?entity
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Entity type
                {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGNewsEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGProductEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGWebEntity .
                }}
                
                # Entity → Parent Frame
                ?frame_edge_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                ?frame_edge_0 vital-core:hasEdgeSource ?entity .
                ?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
                ?frame_0 haley-ai-kg:hasKGFrameType ?parentFrameType .
                
                # Parent Frame → Child Frame
                ?frame_edge_0_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                ?frame_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
                ?frame_edge_0_0 vital-core:hasEdgeDestination ?frame_0_0 .
                ?frame_0_0 haley-ai-kg:hasKGFrameType ?childFrameType .
                
                # Child Frame → Slot
                ?slot_edge_0_0_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                ?slot_edge_0_0_0 vital-core:hasEdgeSource ?frame_0_0 .
                ?slot_edge_0_0_0 vital-core:hasEdgeDestination ?slot_0_0_0 .
                ?slot_0_0_0 haley-ai-kg:hasKGSlotType ?slotType .
                ?slot_0_0_0 haley-ai-kg:hasBooleanSlotValue ?slotValue .
                
                # Apply filters
                FILTER(?parentFrameType = <urn:cardiff:kg:frame:LeadStatusFrame>)
                FILTER(?childFrameType = <urn:cardiff:kg:frame:LeadStatusQualificationFrame>)
                FILTER(?slotType = <urn:cardiff:kg:slot:MQLv2>)
                FILTER(?slotValue = true)
            }}
        }}
        ORDER BY ?entity
        LIMIT 10
        """
        
        start_time = time.time()
        results = self.query_fuseki(query, "Testing MQL query - With FILTER clauses")
        query_time = time.time() - start_time
        
        if results and 'results' in results and 'bindings' in results['results']:
            count = len(results['results']['bindings'])
            logger.info(f"   ✅ Found {count} MQL leads")
            logger.info(f"   ⏱️  Query time: {query_time:.3f}s\n")
            return True
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def test_mql_query_reversed_order(self) -> bool:
        """Test MQL query with reversed order: Slot → Frame → Entity."""
        import time
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?entity
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Start with Slot (most selective)
                ?slot_0_0_0 haley-ai-kg:hasKGSlotType <urn:cardiff:kg:slot:MQLv2> .
                ?slot_0_0_0 haley-ai-kg:hasBooleanSlotValue true .
                
                # Slot → Child Frame
                ?slot_edge_0_0_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                ?slot_edge_0_0_0 vital-core:hasEdgeDestination ?slot_0_0_0 .
                ?slot_edge_0_0_0 vital-core:hasEdgeSource ?frame_0_0 .
                ?frame_0_0 haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusQualificationFrame> .
                
                # Child Frame → Parent Frame
                ?frame_edge_0_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                ?frame_edge_0_0 vital-core:hasEdgeDestination ?frame_0_0 .
                ?frame_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
                ?frame_0 haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusFrame> .
                
                # Parent Frame → Entity
                ?frame_edge_0 vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                ?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
                ?frame_edge_0 vital-core:hasEdgeSource ?entity .
                
                # Entity type
                {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGNewsEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGProductEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGWebEntity .
                }}
            }}
        }}
        ORDER BY ?entity
        LIMIT 10
        """
        
        start_time = time.time()
        results = self.query_fuseki(query, "Testing MQL query - Reversed order")
        query_time = time.time() - start_time
        
        if results and 'results' in results and 'bindings' in results['results']:
            count = len(results['results']['bindings'])
            logger.info(f"   ✅ Found {count} MQL leads")
            logger.info(f"   ⏱️  Query time: {query_time:.3f}s\n")
            return True
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def materialize_direct_properties(self) -> bool:
        """Materialize direct properties to bypass edge objects."""
        import time
        
        logger.info("   Materializing direct properties...")
        
        # Insert hasEntityFrame direct properties
        insert_entity_frame = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        INSERT {{
            GRAPH <{self.graph_id}> {{
                ?entity vg-direct:hasEntityFrame ?frame .
            }}
        }}
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?edge vital-core:hasEdgeSource ?entity .
                ?edge vital-core:hasEdgeDestination ?frame .
            }}
        }}
        """
        
        # Insert hasFrame direct properties (frame to child frame)
        insert_frame_frame = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        INSERT {{
            GRAPH <{self.graph_id}> {{
                ?parentFrame vg-direct:hasFrame ?childFrame .
            }}
        }}
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge vital-core:vitaltype haley-ai-kg:Edge_hasKGFrame .
                ?edge vital-core:hasEdgeSource ?parentFrame .
                ?edge vital-core:hasEdgeDestination ?childFrame .
            }}
        }}
        """
        
        # Insert hasSlot direct properties
        insert_frame_slot = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        INSERT {{
            GRAPH <{self.graph_id}> {{
                ?frame vg-direct:hasSlot ?slot .
            }}
        }}
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?edge vital-core:hasEdgeSource ?frame .
                ?edge vital-core:hasEdgeDestination ?slot .
            }}
        }}
        """
        
        try:
            # Execute inserts
            start_time = time.time()
            
            logger.info("   Inserting hasEntityFrame properties...")
            self.execute_sparql_update(insert_entity_frame)
            
            logger.info("   Inserting hasFrame properties...")
            self.execute_sparql_update(insert_frame_frame)
            
            logger.info("   Inserting hasSlot properties...")
            self.execute_sparql_update(insert_frame_slot)
            
            materialization_time = time.time() - start_time
            
            logger.info(f"   ✅ Materialization completed in {materialization_time:.3f}s\n")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Materialization failed: {e}\n")
            return False
    
    def test_mql_query_with_direct_properties(self) -> tuple:
        """Test MQL query using materialized direct properties (no edge hops).
        
        Returns entities, parent frames, child frames, and slots for reuse.
        """
        import time
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        SELECT DISTINCT ?entity ?parentFrame ?childFrame ?slot
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Entity type
                {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGNewsEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGProductEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley-ai-kg:KGWebEntity .
                }}
                
                # Direct: Entity → Parent Frame (no edge hop)
                ?entity vg-direct:hasEntityFrame ?parentFrame .
                ?parentFrame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusFrame> .
                
                # Direct: Parent Frame → Child Frame (no edge hop)
                ?parentFrame vg-direct:hasFrame ?childFrame .
                ?childFrame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusQualificationFrame> .
                
                # Direct: Child Frame → Slot (no edge hop)
                ?childFrame vg-direct:hasSlot ?slot .
                ?slot haley-ai-kg:hasKGSlotType <urn:cardiff:kg:slot:MQLv2> .
                ?slot haley-ai-kg:hasBooleanSlotValue true .
            }}
        }}
        ORDER BY ?entity
        """
        
        start_time = time.time()
        results = self.query_fuseki(query, "Testing MQL query - Direct properties (no edges)")
        query_time = time.time() - start_time
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            
            # Extract all URIs
            entities_list = []
            parent_frames_list = []
            child_frames_list = []
            slots_list = []
            
            for b in bindings:
                entities_list.append(b['entity']['value'])
                parent_frames_list.append(b['parentFrame']['value'])
                child_frames_list.append(b['childFrame']['value'])
                slots_list.append(b['slot']['value'])
            
            # Deduplicate while preserving order
            entities = list(dict.fromkeys(entities_list))
            parent_frames = list(dict.fromkeys(parent_frames_list))
            child_frames = list(dict.fromkeys(child_frames_list))
            slots = list(dict.fromkeys(slots_list))
            
            count = len(entities)
            logger.info(f"   ✅ Found {count} MQL leads")
            logger.info(f"   ⏱️  Query time: {query_time:.3f}s")
            logger.info(f"   📊 Pattern: 7 triple patterns (vs 19 with edges)\n")
            return (True, entities, parent_frames, child_frames, slots, query_time)
        
        logger.error(f"   ❌ Query failed\n")
        return (False, [], [], [], [], query_time)
    
    def query_edges_from_direct_results(self, entities: list, parent_frames: list, child_frames: list, slots: list) -> dict:
        """Find edge URIs that connect the entities/frames/slots from the direct property query.
        
        This identifies the edge subject URIs that were skipped by the direct property query.
        """
        import time
        
        # Merge parent and child frames for Frame→Frame and Frame→Slot queries
        all_frames = list(set(parent_frames + child_frames))
        
        logger.info(f"   Using results from direct property query:")
        logger.info(f"      {len(entities)} entities")
        logger.info(f"      {len(parent_frames)} parent frames")
        logger.info(f"      {len(child_frames)} child frames")
        logger.info(f"      {len(slots)} slots\n")
        
        # Build lists for FILTER IN clauses
        entity_list = ", ".join([f"<{e}>" for e in entities])
        parent_frame_list = ", ".join([f"<{f}>" for f in parent_frames])
        all_frame_list = ", ".join([f"<{f}>" for f in all_frames])
        slot_list = ", ".join([f"<{s}>" for s in slots])
        
        logger.info("   Finding edge URIs that connect these entities/frames/slots...")
        
        # Query to find edge URIs using FILTER IN with FILTER on vitaltype
        edge_query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?edge
        WHERE {{
            GRAPH <{self.graph_id}> {{
                {{
                    # Case 1: Entity → Frame edges
                    ?edge vital-core:hasEdgeSource ?source .
                    ?edge vital-core:hasEdgeDestination ?dest .
                    ?edge vital-core:vitaltype ?type .
                    FILTER(?source IN ({entity_list}))
                    FILTER(?dest IN ({parent_frame_list}))
                    FILTER(?type = haley-ai-kg:Edge_hasEntityKGFrame)
                }} UNION {{
                    # Case 2: Frame → Frame edges
                    ?edge vital-core:hasEdgeSource ?source .
                    ?edge vital-core:hasEdgeDestination ?dest .
                    ?edge vital-core:vitaltype ?type .
                    FILTER(?source IN ({all_frame_list}))
                    FILTER(?dest IN ({all_frame_list}))
                    FILTER(?type = haley-ai-kg:Edge_hasKGFrame)
                }} UNION {{
                    # Case 3: Frame → Slot edges
                    ?edge vital-core:hasEdgeSource ?source .
                    ?edge vital-core:hasEdgeDestination ?dest .
                    ?edge vital-core:vitaltype ?type .
                    FILTER(?source IN ({all_frame_list}))
                    FILTER(?dest IN ({slot_list}))
                    FILTER(?type = haley-ai-kg:Edge_hasKGSlot)
                }}
            }}
        }}
        ORDER BY ?edge
        """
        
        start_time = time.time()
        results = self.query_fuseki(edge_query, "Finding edge URIs", use_post=True)
        edge_query_time = time.time() - start_time
        
        if not results or 'results' not in results or 'bindings' not in results['results']:
            logger.error(f"   ❌ Edge query failed\n")
            return {"success": False}
        
        bindings = results['results']['bindings']
        
        # Collect all edge URIs
        edge_uris = []
        
        for b in bindings:
            edge_uri = b['edge']['value']
            edge_uris.append(edge_uri)
        
        logger.info(f"   ✅ Found {len(bindings)} total edge URIs (these were skipped by direct properties)")
        logger.info(f"   ⏱️  Edge query time: {edge_query_time:.3f}s\n")
        
        # Show samples
        logger.info(f"   📊 Sample edge URIs (first 10):")
        for i, edge_uri in enumerate(edge_uris[:10], 1):
            logger.info(f"      {i}. {edge_uri}")
        logger.info("")
        
        return {
            "success": True,
            "total_edges": len(bindings),
            "edge_uris": edge_uris,
            "edge_query_time": edge_query_time
        }
    
    def query_triples_and_convert_to_objects(self, entities: list, parent_frames: list, child_frames: list, slots: list, edge_uris: list) -> dict:
        """Query all triples where subjects are nodes (entities/frames/slots) or edges, then convert to VitalSigns objects.
        
        This tests whether VitalSigns conversion automatically skips materialized triples or if we need to filter them.
        """
        import time
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        
        # Combine all node URIs
        all_nodes = list(set(entities + parent_frames + child_frames + slots))
        
        # Combine nodes and edges
        all_subjects = all_nodes + edge_uris
        
        logger.info(f"   Querying triples for:")
        logger.info(f"      {len(all_nodes)} nodes (entities + frames + slots)")
        logger.info(f"      {len(edge_uris)} edges")
        logger.info(f"      {len(all_subjects)} total subjects\n")
        
        # Build VALUES clause for all subjects
        subject_values = " ".join([f"<{s}>" for s in all_subjects])
        
        # Query to get all triples with these subjects, filtering out materialized direct properties
        triples_query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        SELECT ?subject ?predicate ?object
        WHERE {{
            GRAPH <{self.graph_id}> {{
                VALUES ?subject {{ {subject_values} }}
                ?subject ?predicate ?object .
                
                # Filter out materialized direct properties
                FILTER(?predicate NOT IN (vg-direct:hasEntityFrame, vg-direct:hasFrame, vg-direct:hasSlot))
            }}
        }}
        ORDER BY ?subject ?predicate
        """
        
        start_time = time.time()
        results = self.query_fuseki(triples_query, "Querying all triples for nodes and edges", use_post=True)
        query_time = time.time() - start_time
        
        if not results or 'results' not in results or 'bindings' not in results['results']:
            logger.error(f"   ❌ Triples query failed\n")
            return {"success": False}
        
        bindings = results['results']['bindings']
        
        logger.info(f"   ✅ Found {len(bindings)} total triples")
        logger.info(f"   ⏱️  Query time: {query_time:.3f}s\n")
        
        # Check for materialized direct properties in results
        materialized_count = 0
        regular_count = 0
        
        for b in bindings:
            predicate = b['predicate']['value']
            if 'vitalgraph/direct#' in predicate:
                materialized_count += 1
            else:
                regular_count += 1
        
        logger.info(f"   📊 Triple Breakdown:")
        logger.info(f"      Regular triples: {regular_count}")
        logger.info(f"      Materialized triples (vg-direct:*): {materialized_count}")
        logger.info("")
        
        # Convert SPARQL results to RDF triple list for VitalSigns
        # Note: Materialized triples are already filtered out in the SPARQL query
        from rdflib import URIRef, Literal
        
        rdf_triples = []
        
        for b in bindings:
            subject = URIRef(b['subject']['value'])
            predicate = URIRef(b['predicate']['value'])
            
            # Handle object based on type
            obj_data = b['object']
            if obj_data['type'] == 'uri':
                obj = URIRef(obj_data['value'])
            elif obj_data['type'] == 'literal':
                # Handle datatype if present
                if 'datatype' in obj_data:
                    obj = Literal(obj_data['value'], datatype=URIRef(obj_data['datatype']))
                elif 'xml:lang' in obj_data:
                    obj = Literal(obj_data['value'], lang=obj_data['xml:lang'])
                else:
                    obj = Literal(obj_data['value'])
            else:
                obj = Literal(obj_data['value'])
            
            rdf_triples.append((subject, predicate, obj))
        
        logger.info(f"   📊 Created {len(rdf_triples)} RDF triple objects (materialized triples filtered in SPARQL query)\n")
        
        # Convert to VitalSigns objects using from_triples_list
        logger.info("   Converting RDF triple list to VitalSigns objects...")
        
        start_time = time.time()
        
        # Use from_triples_list with the triple list (using shared VitalSigns instance)
        graph_objects = self.vs.from_triples_list(rdf_triples)
        
        conversion_time = time.time() - start_time
        
        logger.info(f"   ✅ Converted to {len(graph_objects)} VitalSigns objects")
        logger.info(f"   ⏱️  Conversion time: {conversion_time:.3f}s\n")
        
        # Analyze the converted objects
        object_types = {}
        for obj in graph_objects:
            obj_type = type(obj).__name__
            object_types[obj_type] = object_types.get(obj_type, 0) + 1
        
        logger.info(f"   📊 VitalSigns Object Types:")
        for obj_type, count in sorted(object_types.items()):
            logger.info(f"      {obj_type}: {count}")
        logger.info("")
        
        # Check if any objects have materialized properties
        # (This should be 0 since we filtered them out)
        logger.info(f"   📊 Materialized triples were filtered out before conversion")
        logger.info(f"   📊 VitalSigns successfully converted {len(graph_objects)} objects from {len(rdf_triples)} regular triples")
        logger.info("")
        
        return {
            "success": True,
            "total_triples_returned": len(bindings),
            "regular_triples": regular_count,
            "materialized_triples": materialized_count,
            "vitalsigns_objects": len(graph_objects),
            "object_types": object_types,
            "query_time": query_time,
            "conversion_time": conversion_time
        }
    
    def delete_direct_properties(self) -> bool:
        """Delete all materialized direct properties to restore original state."""
        import time
        
        logger.info("   Deleting materialized direct properties...")
        
        delete_query = f"""
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        DELETE {{
            GRAPH <{self.graph_id}> {{
                ?s ?p ?o .
            }}
        }}
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?s ?p ?o .
                FILTER(?p IN (vg-direct:hasEntityFrame, vg-direct:hasFrame, vg-direct:hasSlot))
            }}
        }}
        """
        
        try:
            start_time = time.time()
            self.execute_sparql_update(delete_query)
            delete_time = time.time() - start_time
            
            logger.info(f"   ✅ Direct properties deleted in {delete_time:.3f}s\n")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Deletion failed: {e}\n")
            return False
    
    def execute_sparql_update(self, update_query: str):
        """Execute a SPARQL UPDATE query."""
        import requests
        
        url = f"{self.fuseki_url}/{self.dataset_name}/update"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"update": update_query}
        
        response = requests.post(url, data=data, headers=headers)
        
        if response.status_code not in [200, 204]:
            raise Exception(f"SPARQL UPDATE failed: {response.status_code} - {response.text}")
    
    def test_query_builder_with_hierarchical_criteria(self) -> bool:
        """Test the query builder with hierarchical frame criteria on lead data."""
        try:
            # Import the query builder and criteria models
            import sys
            from pathlib import Path
            project_root = Path(__file__).parent.parent
            sys.path.insert(0, str(project_root))
            
            from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder, EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            logger.info("   Building hierarchical query using KGQueryCriteriaBuilder...")
            
            # Create query builder
            builder = KGQueryCriteriaBuilder()
            
            # Build hierarchical frame criteria for lead data:
            # Entity → LeadStatusFrame (parent) → LeadStatusQualificationFrame (child) → MQLV2 slot
            hierarchical_frame_criteria = FrameCriteria(
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",  # Parent frame
                frame_criteria=[  # Child frames
                    FrameCriteria(
                        frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",  # Child frame
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="urn:cardiff:kg:slot:MQLv2",
                                slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                value=True,
                                comparator="eq"
                            )
                        ]
                    )
                ]
            )
            
            # Create entity query criteria with hierarchical frame criteria
            criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=[hierarchical_frame_criteria],
                use_edge_pattern=True
            )
            
            # Build the SPARQL query
            sparql_query = builder.build_entity_query_sparql(
                criteria,
                self.graph_id,
                page_size=10,
                offset=0
            )
            
            logger.info("   Generated SPARQL query:")
            logger.info("   " + "=" * 70)
            for line in sparql_query.split('\n'):
                logger.info(f"   {line}")
            logger.info("   " + "=" * 70)
            logger.info("")
            
            # Execute the query
            query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
            headers = {'Accept': 'application/sparql-results+json'}
            params = {'query': sparql_query}
            
            response = requests.get(query_url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                results = response.json()
                if results and 'results' in results and 'bindings' in results['results']:
                    bindings = results['results']['bindings']
                    entity_count = len(bindings)
                    
                    logger.info(f"   ✅ Query executed successfully!")
                    logger.info(f"   Found {entity_count} entities matching hierarchical criteria")
                    
                    if entity_count > 0:
                        logger.info(f"\n   Sample entities:")
                        for i, binding in enumerate(bindings[:3], 1):
                            entity_uri = binding.get('entity', {}).get('value', 'N/A')
                            logger.info(f"      {i}. {entity_uri.split(':')[-1]}")
                        logger.info("")
                        return True
                    else:
                        logger.warning(f"   ⚠️  Query returned 0 results")
                        logger.warning(f"   This may indicate the hierarchical structure doesn't match the data")
                        logger.warning(f"   or the specific frame/slot types don't exist.\n")
                        return False
            else:
                logger.error(f"   ❌ Query failed with status {response.status_code}")
                logger.error(f"   Response: {response.text}\n")
                return False
                
        except Exception as e:
            logger.error(f"   ❌ Error testing query builder: {e}\n")
            import traceback
            traceback.print_exc()
            return False
    
    def investigate_zero_result_queries(self) -> None:
        """Investigate all queries that returned 0 results."""
        
        # 1. Check LeadOwnerFrame slots
        logger.info("=" * 80)
        logger.info("Investigating: LeadTrackingFrame → LeadOwnerFrame → OwnerName")
        logger.info("=" * 80)
        logger.info("")
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?slotType (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?parentFrame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadTrackingFrame> .
                ?frameEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGFrame .
                ?frameEdge vital-core:hasEdgeSource ?parentFrame .
                ?frameEdge vital-core:hasEdgeDestination ?childFrame .
                ?childFrame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadOwnerFrame> .
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?childFrame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                ?slot haley-ai-kg:hasKGSlotType ?slotType .
            }}
        }}
        GROUP BY ?slotType
        ORDER BY DESC(?count)
        LIMIT 10
        """
        
        results = self.query_fuseki(query, "Finding slots in LeadOwnerFrame")
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} slot type(s) in LeadOwnerFrame:\n")
                for binding in bindings:
                    slot_type = binding.get('slotType', {}).get('value', 'N/A')
                    count = binding.get('count', {}).get('value', '0')
                    logger.info(f"      • {slot_type.split(':')[-1]}: {count} slots")
                logger.info("")
            else:
                logger.info(f"   ⚠️  No slots found in LeadOwnerFrame\n")
        
        # 2. Check if BankingFrame exists and what child frames it has
        logger.info("=" * 80)
        logger.info("Investigating: BankingFrame → BankAccountFrame")
        logger.info("=" * 80)
        logger.info("")
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?frame) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:BankingFrame> .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Checking if BankingFrame exists")
        if results and 'results' in results and 'bindings' in results['results']:
            count = results['results']['bindings'][0].get('count', {}).get('value', '0')
            if int(count) > 0:
                logger.info(f"   ✅ Found {count} BankingFrame instances\n")
            else:
                logger.info(f"   ⚠️  BankingFrame does not exist in data\n")
                # Check what banking-related frames exist
                query2 = f"""
                PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
                SELECT DISTINCT ?frameType (COUNT(?frame) as ?count)
                WHERE {{
                    GRAPH <{self.graph_id}> {{
                        ?frame haley-ai-kg:hasKGFrameType ?frameType .
                        FILTER(CONTAINS(LCASE(STR(?frameType)), "bank"))
                    }}
                }}
                GROUP BY ?frameType
                ORDER BY DESC(?count)
                """
                results2 = self.query_fuseki(query2, "Finding banking-related frames")
                if results2 and 'results' in results2 and 'bindings' in results2['results']:
                    bindings = results2['results']['bindings']
                    if bindings:
                        logger.info(f"   Found {len(bindings)} banking-related frame type(s):\n")
                        for binding in bindings:
                            frame_type = binding.get('frameType', {}).get('value', 'N/A')
                            count = binding.get('count', {}).get('value', '0')
                            logger.info(f"      • {frame_type.split(':')[-1]}: {count} frames")
                        logger.info("")
        
        # 3. Check LeadStatusConversionFrame
        logger.info("=" * 80)
        logger.info("Investigating: LeadStatusConversionFrame → IsConverted")
        logger.info("=" * 80)
        logger.info("")
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?slotType (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:LeadStatusConversionFrame> .
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?frame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                ?slot haley-ai-kg:hasKGSlotType ?slotType .
            }}
        }}
        GROUP BY ?slotType
        ORDER BY DESC(?count)
        LIMIT 10
        """
        
        results = self.query_fuseki(query, "Finding slots in LeadStatusConversionFrame")
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} slot type(s) in LeadStatusConversionFrame:\n")
                for binding in bindings:
                    slot_type = binding.get('slotType', {}).get('value', 'N/A')
                    count = binding.get('count', {}).get('value', '0')
                    logger.info(f"      • {slot_type.split(':')[-1]}: {count} slots")
                logger.info("")
            else:
                logger.info(f"   ⚠️  No slots found in LeadStatusConversionFrame\n")
    
    def check_mqlv2_exists(self) -> bool:
        """Check what values MQLV2 slots actually have."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?value (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?slot haley-ai-kg:hasKGSlotType <urn:cardiff:kg:slot:MQLv2> .
                ?slot haley-ai-kg:hasBooleanSlotValue ?value .
            }}
        }}
        GROUP BY ?value
        ORDER BY DESC(?count)
        """
        
        results = self.query_fuseki(query, "Checking MQLV2 slot values")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found MQLV2 slots with values:\n")
                for binding in bindings:
                    value = binding.get('value', {}).get('value', 'N/A')
                    count = binding.get('count', {}).get('value', '0')
                    logger.info(f"      • value={value}: {count} slots")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No MQLV2 slots found\n")
        return False
    
    def find_mql_slot_location(self) -> bool:
        """Find which child frame contains the MQL slot."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?parentFrameType ?childFrameType (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Find entity
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                
                # Entity to parent frame
                ?entityFrameEdge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?entityFrameEdge vital-core:hasEdgeSource ?entity .
                ?entityFrameEdge vital-core:hasEdgeDestination ?parentFrame .
                ?parentFrame haley-ai-kg:hasKGFrameType ?parentFrameType .
                
                # Parent to child frame
                ?frameEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGFrame .
                ?frameEdge vital-core:hasEdgeSource ?parentFrame .
                ?frameEdge vital-core:hasEdgeDestination ?childFrame .
                ?childFrame haley-ai-kg:hasKGFrameType ?childFrameType .
                
                # Child frame to MQL slot
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?childFrame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                ?slot haley-ai-kg:hasKGSlotType <urn:cardiff:kg:slot:MQL> .
            }}
        }}
        GROUP BY ?parentFrameType ?childFrameType
        ORDER BY DESC(?count)
        """
        
        results = self.query_fuseki(query, "Finding MQL slot location")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found MQL slot in {len(bindings)} frame path(s):\n")
                for binding in bindings:
                    parent = binding.get('parentFrameType', {}).get('value', 'N/A')
                    child = binding.get('childFrameType', {}).get('value', 'N/A')
                    count = binding.get('count', {}).get('value', '0')
                    logger.info(f"      • {parent.split(':')[-1]} → {child.split(':')[-1]}: {count} slots")
                logger.info("")
                return True
            else:
                logger.error(f"   ❌ MQL slot not found in any hierarchical path\n")
                return False
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def find_systemflags_slots(self) -> bool:
        """Find what slot types actually exist in SystemFlagsFrame."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?slotType (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Find SystemFrame
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                ?entityFrameEdge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?entityFrameEdge vital-core:hasEdgeSource ?entity .
                ?entityFrameEdge vital-core:hasEdgeDestination ?systemFrame .
                ?systemFrame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:SystemFrame> .
                
                # Find SystemFlagsFrame child
                ?frameEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGFrame .
                ?frameEdge vital-core:hasEdgeSource ?systemFrame .
                ?frameEdge vital-core:hasEdgeDestination ?flagsFrame .
                ?flagsFrame haley-ai-kg:hasKGFrameType <urn:cardiff:kg:frame:SystemFlagsFrame> .
                
                # Find slots in SystemFlagsFrame
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?flagsFrame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                ?slot haley-ai-kg:hasKGSlotType ?slotType .
            }}
        }}
        GROUP BY ?slotType
        ORDER BY DESC(?count)
        LIMIT 20
        """
        
        results = self.query_fuseki(query, "Finding slot types in SystemFlagsFrame")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} slot type(s) in SystemFlagsFrame:\n")
                for binding in bindings:
                    slot_type = binding.get('slotType', {}).get('value', 'N/A')
                    count = binding.get('count', {}).get('value', '0')
                    logger.info(f"      • {slot_type.split(':')[-1]}: {count} slots")
                logger.info("")
                return True
            else:
                logger.error(f"   ❌ No slots found in SystemFlagsFrame\n")
                return False
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def test_hierarchical_frame_structure(self) -> bool:
        """Test entity → parent frame → child frame → slot path."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?parentFrame ?childFrame ?slot ?slotType ?slotValue
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Entity to parent frame
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                
                ?entityFrameEdge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?entityFrameEdge vital-core:hasEdgeSource ?entity .
                ?entityFrameEdge vital-core:hasEdgeDestination ?parentFrame .
                
                ?parentFrame vital-core:vitaltype haley-ai-kg:KGFrame .
                
                # Parent frame to child frame
                ?parentChildEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGFrame .
                ?parentChildEdge vital-core:hasEdgeSource ?parentFrame .
                ?parentChildEdge vital-core:hasEdgeDestination ?childFrame .
                
                ?childFrame vital-core:vitaltype haley-ai-kg:KGFrame .
                ?childFrame haley-ai-kg:hasKGFrameType ?frameType .
                
                # Child frame to slot
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?childFrame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                
                ?slot haley-ai-kg:hasKGSlotType ?slotType .
                OPTIONAL {{ ?slot haley-ai-kg:hasBooleanSlotValue ?slotValue }}
            }}
        }}
        LIMIT 10
        """
        
        results = self.query_fuseki(query, "Testing hierarchical frame structure (entity → parent → child → slot)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} hierarchical path(s):\n")
                for i, binding in enumerate(bindings[:5], 1):
                    entity = binding.get('entity', {}).get('value', 'N/A')
                    parent_frame = binding.get('parentFrame', {}).get('value', 'N/A')
                    child_frame = binding.get('childFrame', {}).get('value', 'N/A')
                    slot = binding.get('slot', {}).get('value', 'N/A')
                    slot_type = binding.get('slotType', {}).get('value', 'N/A')
                    slot_value = binding.get('slotValue', {}).get('value', 'N/A')
                    
                    logger.info(f"   Path {i}:")
                    logger.info(f"      Entity: {entity.split(':')[-1]}")
                    logger.info(f"      Parent Frame: {parent_frame.split(':')[-1]}")
                    logger.info(f"      Child Frame: {child_frame.split(':')[-1]}")
                    logger.info(f"      Slot Type: {slot_type.split(':')[-1]}")
                    logger.info(f"      Slot Value: {slot_value}")
                    logger.info("")
                
                logger.info(f"   ✅ Hierarchical frame structure confirmed!\n")
                return True
            else:
                logger.error(f"   ❌ No hierarchical paths found\n")
                return False
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def check_frame_uri_mismatch(self) -> bool:
        """Check if frame URIs match between entity-frame edges and frame-slot edges."""
        # Get sample frame URIs from entity-frame edges
        query1 = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?frame
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entityFrameEdge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?entityFrameEdge vital-core:hasEdgeDestination ?frame .
            }}
        }}
        LIMIT 5
        """
        
        # Get sample frame URIs from frame-slot edges
        query2 = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?frame
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?frame .
            }}
        }}
        LIMIT 5
        """
        
        results1 = self.query_fuseki(query1, "Getting frame URIs from entity-frame edges")
        results2 = self.query_fuseki(query2, "Getting frame URIs from frame-slot edges")
        
        if results1 and results2:
            frames1 = []
            frames2 = []
            
            if 'results' in results1 and 'bindings' in results1['results']:
                for binding in results1['results']['bindings']:
                    frames1.append(binding.get('frame', {}).get('value', ''))
            
            if 'results' in results2 and 'bindings' in results2['results']:
                for binding in results2['results']['bindings']:
                    frames2.append(binding.get('frame', {}).get('value', ''))
            
            logger.info(f"   Sample frames from entity-frame edges:")
            for f in frames1[:3]:
                logger.info(f"      {f}")
            logger.info(f"\n   Sample frames from frame-slot edges:")
            for f in frames2[:3]:
                logger.info(f"      {f}")
            logger.info("")
            
            # Check if any overlap
            overlap = set(frames1) & set(frames2)
            if overlap:
                logger.info(f"   ✅ Found {len(overlap)} overlapping frame URI(s)")
                logger.info(f"   These frames are both connected to entities AND contain slots.\n")
                return True
            else:
                logger.info(f"   ℹ️  No overlapping frame URIs found.")
                logger.info(f"   This is expected for hierarchical frame structures:")
                logger.info(f"   - Parent frames connect to entities")
                logger.info(f"   - Child frames (nested within parents) contain slots\n")
                return True
        
        return False
    
    def debug_entity_frame_slot_structure(self) -> bool:
        """Debug the entity-frame-slot structure to understand the data model."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?frame ?slot
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                
                ?entityFrameEdge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?entityFrameEdge vital-core:hasEdgeSource ?entity .
                ?entityFrameEdge vital-core:hasEdgeDestination ?frame .
                
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?frame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
            }}
        }}
        LIMIT 5
        """
        
        results = self.query_fuseki(query, "Debugging entity-frame-slot structure")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} entity-frame-slot path(s):\n")
                for binding in bindings:
                    entity = binding.get('entity', {}).get('value', 'N/A')
                    frame = binding.get('frame', {}).get('value', 'N/A')
                    slot = binding.get('slot', {}).get('value', 'N/A')
                    slot_type = binding.get('slotType', {}).get('value', 'N/A')
                    value = binding.get('value', {}).get('value', 'N/A')
                    logger.info(f"      Entity: {entity.split(':')[-1]}")
                    logger.info(f"      Frame: {frame.split(':')[-1]}")
                    logger.info(f"      Slot: {slot.split(':')[-1]}")
                    logger.info(f"      Slot Type: {slot_type.split(':')[-1]}")
                    logger.info(f"      Value: {value}")
                    logger.info("")
                return True
            else:
                logger.error(f"   ❌ No entity-frame-slot paths found!")
                logger.error(f"   This means the SPARQL pattern doesn't match the data structure.\n")
                return False
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def find_entities_with_criteria(self, frame_type: str, slot_type: str, slot_value: Any) -> int:
        """Find how many entities match specific frame/slot criteria."""
        # Determine value property based on value type
        if isinstance(slot_value, bool):
            value_property = "haley-ai-kg:hasBooleanSlotValue"
            value_literal = "true" if slot_value else "false"
        elif isinstance(slot_value, int):
            value_property = "haley-ai-kg:hasIntegerSlotValue"
            value_literal = str(slot_value)
        elif isinstance(slot_value, float):
            value_property = "haley-ai-kg:hasDoubleSlotValue"
            value_literal = str(slot_value)
        else:
            value_property = "haley-ai-kg:hasTextSlotValue"
            value_literal = f'"{slot_value}"'
        
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(DISTINCT ?entity) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley-ai-kg:KGEntity .
                
                ?entityFrameEdge vital-core:vitaltype haley-ai-kg:Edge_hasEntityKGFrame .
                ?entityFrameEdge vital-core:hasEdgeSource ?entity .
                ?entityFrameEdge vital-core:hasEdgeDestination ?frame .
                
                ?frame vital-core:vitaltype haley-ai-kg:KGFrame .
                ?frame haley-ai-kg:hasKGFrameType <{frame_type}> .
                
                ?slotEdge vital-core:vitaltype haley-ai-kg:Edge_hasKGSlot .
                ?slotEdge vital-core:hasEdgeSource ?frame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                
                ?slot haley-ai-kg:hasKGSlotType <{slot_type}> .
                ?slot {value_property} {value_literal} .
            }}
        }}
        """
        
        results = self.query_fuseki(query, f"Finding entities with {frame_type.split('#')[-1]} / {slot_type.split(':')[-1]} = {slot_value}")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} matching entities\n")
                return count
        
        logger.error(f"   ❌ Query failed\n")
        return 0
    
    def run_inspection(self) -> bool:
        """Run the complete inspection."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("🔍 Lead Data Inspection")
        logger.info("=" * 80)
        logger.info("")
        
        # Step 1: Count entities
        logger.info("=" * 80)
        logger.info("Step 1: Count Entities")
        logger.info("=" * 80)
        logger.info("")
        
        entity_count = self.count_entities()
        if entity_count == 0:
            logger.error("❌ No entities found. Make sure the lead dataset test has been run.")
            return False
        
        # Step 2: Check entity-frame edges
        logger.info("=" * 80)
        logger.info("Step 2: Check Entity-Frame Edges")
        logger.info("=" * 80)
        logger.info("")
        
        edges_exist = self.check_entity_frame_edges()
        if not edges_exist:
            logger.error("❌ No entity-to-frame edges found.")
            logger.error("   The lead data may not have the expected edge structure.")
            logger.error("   This explains why KGQuery frame queries return 0 results.")
            return False
        
        # Step 2b: Check frame-slot edges
        logger.info("=" * 80)
        logger.info("Step 2b: Check Frame-Slot Edges")
        logger.info("=" * 80)
        logger.info("")
        
        slot_edges_exist = self.check_frame_slot_edges()
        if not slot_edges_exist:
            logger.error("❌ No frame-to-slot edges found.")
            logger.error("   Frames exist but slots are not connected via edges.")
            logger.error("   This explains why KGQuery frame queries return 0 results.")
            return False
        
        # Step 2c: Test hierarchical frame structure
        logger.info("=" * 80)
        logger.info("Step 2c: Test Hierarchical Frame Structure")
        logger.info("=" * 80)
        logger.info("")
        
        hierarchical_ok = self.test_hierarchical_frame_structure()
        if hierarchical_ok:
            logger.info("✅ Lead data uses hierarchical frame structure:")
            logger.info("   Entity → Parent Frame → Child Frame → Slot")
            logger.info("   This is why flat queries (Entity → Frame → Slot) return 0 results.\n")
        
        # Step 2c-1: Investigate zero result queries
        logger.info("=" * 80)
        logger.info("Step 2c-1: Investigate Zero Result Queries")
        logger.info("=" * 80)
        logger.info("")
        
        self.investigate_zero_result_queries()
        
        # Step 2c-2: Test MQL query with normal order
        logger.info("=" * 80)
        logger.info("Step 2c-2: Test MQL Query - Normal Order (Entity → Frame → Slot)")
        logger.info("=" * 80)
        logger.info("")
        
        edge_success, edge_entities, edge_time = self.test_mql_query_normal_order()
        
        # Step 2c-3: Test MQL query with FILTER clauses
        logger.info("=" * 80)
        logger.info("Step 2c-3: Test MQL Query - Using FILTER Clauses")
        logger.info("=" * 80)
        logger.info("")
        
        self.test_mql_query_with_filters()
        
        # Step 2c-4: Test MQL query with reversed order
        logger.info("=" * 80)
        logger.info("Step 2c-4: Test MQL Query - Reversed Order (Slot → Frame → Entity)")
        logger.info("=" * 80)
        logger.info("")
        
        self.test_mql_query_reversed_order()
        
        # Step 2c-5: Materialize direct properties
        # logger.info("=" * 80)
        # logger.info("Step 2c-5: Materialize Direct Properties (Performance Optimization)")
        # logger.info("=" * 80)
        # logger.info("")
        
        # materialized = self.materialize_direct_properties()
        materialized = False  # Skip materialization (requires SPARQL UPDATE auth)
        
        materialized = True 

        if materialized:
            # Step 2c-6: Test MQL query with direct properties
            logger.info("=" * 80)
            logger.info("Step 2c-6: Test MQL Query - Using Direct Properties (No Edge Hops)")
            logger.info("=" * 80)
            logger.info("")
            
            direct_success, direct_entities, direct_parent_frames, direct_child_frames, direct_slots, direct_time = self.test_mql_query_with_direct_properties()
            
            # Step 2c-6a: Query edge URIs from direct results
            if direct_success and direct_entities:
                logger.info("=" * 80)
                logger.info("Step 2c-6a: Query Edge URIs from Direct Property Results")
                logger.info("=" * 80)
                logger.info("")
                
                edge_info = self.query_edges_from_direct_results(direct_entities, direct_parent_frames, direct_child_frames, direct_slots)
                
                # Step 2c-6a-1: Query all triples and convert to VitalSigns objects
                if edge_info.get("success") and edge_info.get("edge_uris"):
                    logger.info("=" * 80)
                    logger.info("Step 2c-6a-1: Query All Triples and Convert to VitalSigns Objects")
                    logger.info("=" * 80)
                    logger.info("")
                    
                    triples_info = self.query_triples_and_convert_to_objects(
                        direct_entities, 
                        direct_parent_frames, 
                        direct_child_frames, 
                        direct_slots,
                        edge_info["edge_uris"]
                    )
            
            # Step 2c-6b: Compare results
            if edge_success and direct_success:
                logger.info("=" * 80)
                logger.info("Step 2c-6b: Compare Edge-Based vs Direct Properties Results")
                logger.info("=" * 80)
                logger.info("")
                
                logger.info(f"📊 Performance Comparison:")
                logger.info(f"   Edge-based query time:    {edge_time:.3f}s")
                logger.info(f"   Direct properties time:   {direct_time:.3f}s")
                speedup = edge_time / direct_time if direct_time > 0 else 0
                logger.info(f"   Speedup:                  {speedup:.1f}x faster\n")
                
                logger.info(f"📊 Results Comparison:")
                logger.info(f"   Edge-based results:       {len(edge_entities)} entities")
                logger.info(f"   Direct properties results: {len(direct_entities)} entities")
                
                # Check if results match
                edge_set = set(edge_entities)
                direct_set = set(direct_entities)
                
                if edge_set == direct_set:
                    logger.info(f"   ✅ Results match perfectly!\n")
                else:
                    logger.warning(f"   ⚠️  Results differ!")
                    only_in_edge = edge_set - direct_set
                    only_in_direct = direct_set - edge_set
                    if only_in_edge:
                        logger.warning(f"   Only in edge-based: {len(only_in_edge)} entities")
                    if only_in_direct:
                        logger.warning(f"   Only in direct: {len(only_in_direct)} entities\n")
                
                # Show sample entities
                logger.info(f"📊 Sample Entity URIs (first 5):")
                logger.info(f"   Edge-based:")
                for entity in edge_entities[:5]:
                    logger.info(f"      {entity}")
                logger.info(f"\n   Direct properties:")
                for entity in direct_entities[:5]:
                    logger.info(f"      {entity}")
                logger.info("")
            
            # Step 2c-7: Clean up direct properties
            # COMMENTED OUT: Skip deletion to preserve materialized data
            # logger.info("=" * 80)
            # logger.info("Step 2c-7: Delete Direct Properties (Restore Original State)")
            # logger.info("=" * 80)
            # logger.info("")
            # 
            # self.delete_direct_properties()
        
        # Step 2d: Check frame URI overlap
        logger.info("=" * 80)
        logger.info("Step 2d: Check Frame URI Overlap")
        logger.info("=" * 80)
        logger.info("")
        
        frame_overlap = self.check_frame_uri_mismatch()
        if not frame_overlap:
            logger.error("❌ Frame URIs don't overlap between entity-frame and frame-slot edges.")
            logger.error("   This is the root cause of why queries return 0 results.")
            return False
        
        # Step 2e: Debug entity-frame-slot structure
        logger.info("=" * 80)
        logger.info("Step 2e: Debug Entity-Frame-Slot Structure")
        logger.info("=" * 80)
        logger.info("")
        
        structure_ok = self.debug_entity_frame_slot_structure()
        if not structure_ok:
            logger.error("❌ Entity-frame-slot structure doesn't match expected pattern.")
            logger.error("   The SPARQL query pattern may need to be adjusted.")
            return False
        
        # Step 3: List frame types
        logger.info("=" * 80)
        logger.info("Step 3: List Frame Types")
        logger.info("=" * 80)
        logger.info("")
        
        frame_types = self.list_frame_types()
        if not frame_types:
            logger.error("❌ No frame types found.")
            return False
        
        # Step 4: Inspect top frame types
        logger.info("=" * 80)
        logger.info("Step 4: Inspect Top Frame Types")
        logger.info("=" * 80)
        logger.info("")
        
        # Focus on a few interesting frame types
        interesting_frames = [
            'urn:cardiff:kg:frame:LeadStatusQualificationFrame',
            'urn:cardiff:kg:frame:CompanyAddressFrame',
            'urn:cardiff:kg:frame:SystemFlagsFrame',
            'urn:cardiff:kg:frame:BankAccountFrame',
            'urn:cardiff:kg:frame:LeadStatusConversionFrame'
        ]
        
        recommendations = []
        
        for frame_type_uri in interesting_frames:
            # Check if this frame type exists in the data
            frame_exists = any(ft['type'] == frame_type_uri for ft in frame_types)
            if not frame_exists:
                continue
            
            logger.info("-" * 80)
            logger.info(f"Inspecting: {frame_type_uri.split(':')[-1]}")
            logger.info("-" * 80)
            logger.info("")
            
            # Get slot types for this frame
            slot_types = self.list_slot_types_for_frame(frame_type_uri)
            
            # For each slot type, get sample values
            for slot_info in slot_types[:5]:  # Limit to top 5 slots per frame
                slot_type = slot_info['type']
                slot_class = slot_info['class']
                
                values = self.get_slot_values(frame_type_uri, slot_type, slot_class, limit=10)
                
                # For interesting values, check how many entities match
                if values:
                    # Pick a good value to test (most common or an interesting one)
                    test_value = values[0]['value']
                    
                    # Convert string booleans to actual booleans
                    if slot_class and "Boolean" in slot_class:
                        test_value = test_value.lower() == 'true'
                    elif slot_class and ("Integer" in slot_class or "Long" in slot_class):
                        test_value = int(test_value)
                    elif slot_class and ("Double" in slot_class or "Float" in slot_class):
                        test_value = float(test_value)
                    
                    matching_count = self.find_entities_with_criteria(
                        frame_type_uri,
                        slot_type,
                        test_value
                    )
                    
                    if matching_count > 0:
                        recommendations.append({
                            'frame_type': frame_type_uri,
                            'slot_type': slot_type,
                            'slot_class': slot_class,
                            'value': test_value,
                            'matching_entities': matching_count
                        })
        
        # Step 5: Print recommendations
        logger.info("=" * 80)
        logger.info("Step 5: Recommendations for KGQuery Frame Queries")
        logger.info("=" * 80)
        logger.info("")
        
        if recommendations:
            logger.info("✅ Found usable criteria for frame queries:\n")
            for i, rec in enumerate(recommendations, 1):
                frame_short = rec['frame_type'].split(':')[-1]
                slot_short = rec['slot_type'].split(':')[-1]
                slot_class_short = rec['slot_class'].split('#')[-1]
                
                logger.info(f"{i}. Frame: {frame_short}")
                logger.info(f"   Slot: {slot_short} ({slot_class_short})")
                logger.info(f"   Value: {rec['value']}")
                logger.info(f"   Matching Entities: {rec['matching_entities']}")
                logger.info("")
                
                # Print example query structure
                logger.info("   Example Query Structure:")
                logger.info("   ```python")
                logger.info("   FrameCriteria(")
                logger.info(f"       frame_type=\"{rec['frame_type']}\",")
                logger.info("       slot_criteria=[")
                logger.info("           SlotCriteria(")
                logger.info(f"               slot_type=\"{rec['slot_type']}\",")
                logger.info(f"               slot_class_uri=\"{rec['slot_class']}\",")
                logger.info(f"               value={repr(rec['value'])},")
                logger.info("               comparator=\"eq\"")
                logger.info("           )")
                logger.info("       ]")
                logger.info("   )")
                logger.info("   ```")
                logger.info("")
        else:
            logger.warning("⚠️  No usable criteria found. The data may not have the expected structure.")
        
        logger.info("=" * 80)
        logger.info("🎉 Inspection Complete!")
        logger.info("=" * 80)
        logger.info("")
        
        return True


def main():
    """Main entry point for the inspection script."""
    try:
        # Initialize VitalSigns once at the beginning to avoid repeated ontology loading
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        logger.info("Initializing VitalSigns (loading ontologies)...")
        vs = VitalSigns()
        logger.info("VitalSigns initialized\n")
        
        inspector = LeadDataInspector()
        inspector.vs = vs  # Store VitalSigns instance in inspector
        
        # First, do a quick check of what data exists
        logger.info("=" * 100)
        logger.info("🔍 Quick Data Check")
        logger.info("=" * 100)
        logger.info("")
        
        # Count all triples in the graph
        count_query = f"""
        SELECT (COUNT(*) as ?count)
        WHERE {{
            GRAPH <{inspector.graph_id}> {{
                ?s ?p ?o .
            }}
        }}
        """
        
        results = inspector.query_fuseki(count_query, "Counting all triples in graph", timeout=30)
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} total triples in graph\n")
        
        # Count distinct subjects
        subjects_query = f"""
        SELECT (COUNT(DISTINCT ?s) as ?count)
        WHERE {{
            GRAPH <{inspector.graph_id}> {{
                ?s ?p ?o .
            }}
        }}
        """
        
        results = inspector.query_fuseki(subjects_query, "Counting distinct subjects", timeout=30)
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} distinct subjects\n")
        
        # Count objects with hasKGGraphURI
        graph_uri_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT (COUNT(DISTINCT ?s) as ?count)
        WHERE {{
            GRAPH <{inspector.graph_id}> {{
                ?s haley:hasKGGraphURI ?graphURI .
            }}
        }}
        """
        
        results = inspector.query_fuseki(graph_uri_query, "Counting objects with hasKGGraphURI", timeout=30)
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} objects with hasKGGraphURI\n")
                
                if count == 0:
                    logger.warning("   ⚠️  No objects with hasKGGraphURI found.")
                    logger.info("")
            else:
                logger.warning("   ⚠️  Could not count objects\n")
        else:
            logger.warning("   ⚠️  Query failed\n")
        
        # Sample some subjects
        sample_query = f"""
        SELECT DISTINCT ?s
        WHERE {{
            GRAPH <{inspector.graph_id}> {{
                ?s ?p ?o .
            }}
        }}
        LIMIT 10
        """
        
        results = inspector.query_fuseki(sample_query, "Getting sample subjects", timeout=30)
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   Sample subjects (first {len(bindings)}):")
                for i, binding in enumerate(bindings, 1):
                    subject = binding.get('s', {}).get('value', 'unknown')
                    logger.info(f"      {i}. {subject}")
                logger.info("")
        
        # Run full inspection
        success = inspector.run_inspection()
        
        # Test the DELETE operation's first step - find subjects with hasKGGraphURI for a specific entity
        # COMMENTED OUT: Skip DELETE operation testing to preserve data
        # import time
        # 
        # logger.info("\n" + "=" * 100)
        # logger.info("🔍 Testing DELETE Operation First Step")
        # logger.info("=" * 100)
        # logger.info("")
        # 
        # # Pick the first entity to test
        # test_entity_uri = "urn:cardiff:lead:00QUg00000Xzjy8MAB"
        # 
        # delete_step1_query = f"""
        # PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        # 
        # SELECT DISTINCT ?s WHERE {{
        #     GRAPH <{inspector.graph_id}> {{
        #         ?s haley:hasKGGraphURI <{test_entity_uri}> .
        #     }}
        # }}
        # """
        # 
        # logger.info(f"Testing with entity: {test_entity_uri}")
        # logger.info(f"This query mimics the FIRST STEP of delete_entity_graph()\n")
        # 
        # start_time = time.time()
        # results = inspector.query_fuseki(delete_step1_query, "Finding subjects with hasKGGraphURI (DELETE step 1)", timeout=60)
        # query_time = time.time() - start_time
        # 
        # if results and 'results' in results and 'bindings' in results['results']:
        #     bindings = results['results']['bindings']
        #     subject_count = len(bindings)
        #     logger.info(f"   ✅ Found {subject_count} subjects with hasKGGraphURI={test_entity_uri}")
        #     logger.info(f"   ⏱️  Query time: {query_time:.3f}s")
        #     
        #     if subject_count > 0:
        #         logger.info(f"\n   Sample subjects (first 10):")
        #         for i, binding in enumerate(bindings[:10], 1):
        #             subject = binding.get('s', {}).get('value', 'unknown')
        #             logger.info(f"      {i}. {subject}")
        #         logger.info(f"\n   📊 Step 1 Summary:")
        #         logger.info(f"   - Query returned {subject_count} objects in {query_time:.3f}s")
        #         logger.info(f"   - These objects would all need to be deleted")
        #         logger.info("")
        #         
        #         # Step 2: Query all triples for these subjects
        #         logger.info("=" * 100)
        #         logger.info("🔍 Testing DELETE Operation Second Step")
        #         logger.info("=" * 100)
        #         logger.info("")
        #         
        #         # Build the subject filter (FILTER IN clause)
        #         subject_uris = [binding.get('s', {}).get('value', '') for binding in bindings if binding.get('s', {}).get('value', '')]
        #         subject_filter = ', '.join([f'<{uri}>' for uri in subject_uris])
        #         
        #         delete_step2_query = f"""
        #         SELECT ?s ?p ?o WHERE {{
        #             GRAPH <{inspector.graph_id}> {{
        #                 ?s ?p ?o .
        #                 FILTER(?s IN ({subject_filter}))
        #             }}
        #         }}
        #         """
        #         
        #         logger.info(f"Querying all triples for {subject_count} subjects")
        #         logger.info(f"This query mimics the SECOND STEP of delete_entity_graph()")
        #         logger.info(f"Using HTTP POST to avoid 414 Request-URI Too Large error\n")
        #         
        #         start_time = time.time()
        #         results2 = inspector.query_fuseki(delete_step2_query, "Getting all triples for subjects (DELETE step 2)", timeout=120, use_post=True)
        #         query_time2 = time.time() - start_time
        #         
        #         if results2 and 'results' in results2 and 'bindings' in results2['results']:
        #             bindings2 = results2['results']['bindings']
        #             triple_count = len(bindings2)
        #             logger.info(f"   ✅ Found {triple_count} triples for {subject_count} subjects")
        #             logger.info(f"   ⏱️  Query time: {query_time2:.3f}s")
        #             
        #             logger.info(f"\n   📊 Step 2 Summary:")
        #             logger.info(f"   - Query returned {triple_count} triples in {query_time2:.3f}s")
        #             logger.info(f"   - Average: {triple_count/subject_count:.1f} triples per subject")
        #             logger.info(f"   - These triples would be used to build the DELETE DATA query")
        #             logger.info("")
        #             
        #             logger.info(f"   📊 Overall DELETE Operation Summary:")
        #             logger.info(f"   - Step 1 (find subjects): {query_time:.3f}s")
        #             logger.info(f"   - Step 2 (get triples): {query_time2:.3f}s")
        #             logger.info(f"   - Total query time: {query_time + query_time2:.3f}s")
        #             logger.info(f"   - Objects to delete: {subject_count}")
        #             logger.info(f"   - Triples to delete: {triple_count}")
        #             logger.info("")
        #         else:
        #             logger.warning(f"   ⚠️  Step 2 query failed after {query_time2:.3f}s\n")
        # else:
        #     logger.warning(f"   ⚠️  Query failed after {query_time:.3f}s\n")
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Inspection failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
