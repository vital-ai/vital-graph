#!/usr/bin/env python3
"""
Direct Fuseki Query Test for Production Data

This script directly queries the production Fuseki instance to verify
that the data created by test_realistic_persistent.py is properly stored
in Fuseki with JWT authentication.

It queries the space_realistic_org_test dataset to verify:
1. Entity data is present
2. Frame data is present
3. Slot data is present
4. All relationships are intact
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class FusekiDirectQueryTester:
    """Test direct Fuseki queries with JWT authentication."""
    
    def __init__(self):
        """Initialize the tester by loading configuration from .env file."""
        # Load .env from project root
        project_root = Path(__file__).parent.parent
        env_path = project_root / '.env'
        
        if not env_path.exists():
            raise FileNotFoundError(f"No .env file found at {env_path}")
        
        load_dotenv(env_path)
        logger.info(f"✅ Loaded configuration from {env_path}\n")
        
        # Keycloak configuration
        self.keycloak_url = os.getenv('KEYCLOAK_URL')
        self.keycloak_realm = os.getenv('KEYCLOAK_REALM')
        self.keycloak_client_id = os.getenv('KEYCLOAK_CLIENT_ID')
        self.keycloak_client_secret = os.getenv('KEYCLOAK_CLIENT_SECRET')
        self.keycloak_username = os.getenv('KEYCLOAK_USERNAME')
        self.keycloak_password = os.getenv('KEYCLOAK_PASSWORD')
        
        # Fuseki configuration
        self.fuseki_url = os.getenv('FUSEKI_URL')
        
        # Test space configuration
        self.space_id = "space_realistic_org_test"
        self.dataset_name = f"vitalgraph_space_{self.space_id}"
        self.graph_id = "urn:realistic_org_graph"
        
        # Validate required configuration
        self._validate_config()
        
        # JWT token storage
        self.access_token: Optional[str] = None
        self.token_type: Optional[str] = None
    
    def _validate_config(self) -> None:
        """Validate that all required configuration is present."""
        # FUSEKI_URL is always required
        if not self.fuseki_url:
            raise ValueError("Missing required environment variable: FUSEKI_URL")
        
        # For localhost, JWT authentication is optional
        if 'localhost' in self.fuseki_url or '127.0.0.1' in self.fuseki_url:
            logger.info("✅ Using local Fuseki - JWT authentication not required")
            return
        
        # For production Fuseki, JWT authentication is required
        required_vars = {
            'KEYCLOAK_URL': self.keycloak_url,
            'KEYCLOAK_REALM': self.keycloak_realm,
            'KEYCLOAK_CLIENT_ID': self.keycloak_client_id,
            'KEYCLOAK_USERNAME': self.keycloak_username,
            'KEYCLOAK_PASSWORD': self.keycloak_password,
        }
        
        missing = [key for key, value in required_vars.items() if not value]
        
        if missing:
            raise ValueError(
                f"Missing required environment variables for production Fuseki: {', '.join(missing)}\n"
                f"Please add them to your .env file"
            )
        
        logger.info("✅ All required configuration variables present")
    
    def get_jwt_token(self) -> bool:
        """
        Obtain JWT token from Keycloak using username/password.
        
        Returns:
            True if token obtained successfully, False otherwise
        """
        logger.info("=" * 80)
        logger.info("🔐 Step 1: Obtaining JWT token from Keycloak")
        logger.info("=" * 80)
        
        token_url = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"
        
        # Prepare token request data
        data = {
            'grant_type': 'password',
            'client_id': self.keycloak_client_id,
            'username': self.keycloak_username,
            'password': self.keycloak_password,
        }
        
        # Add client secret if provided (for confidential clients)
        if self.keycloak_client_secret:
            data['client_secret'] = self.keycloak_client_secret
        
        logger.info(f"Keycloak URL: {self.keycloak_url}")
        logger.info(f"Realm: {self.keycloak_realm}")
        logger.info(f"Client ID: {self.keycloak_client_id}")
        logger.info(f"Username: {self.keycloak_username}")
        
        try:
            response = requests.post(
                token_url,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                self.token_type = token_data.get('token_type', 'Bearer')
                
                logger.info("✅ Successfully obtained JWT token from Keycloak")
                logger.info(f"   Token expires in: {token_data.get('expires_in')} seconds\n")
                
                return True
            else:
                logger.error(f"❌ Failed to obtain JWT token")
                logger.error(f"   Status code: {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error connecting to Keycloak: {e}")
            return False
    
    def query_fuseki(self, sparql_query: str, query_description: str) -> Optional[Dict[str, Any]]:
        """
        Execute a SPARQL query against the test dataset in Fuseki.
        
        Args:
            sparql_query: SPARQL query to execute
            query_description: Description of what the query does
            
        Returns:
            Query results as dictionary, or None if failed
        """
        # For production Fuseki, JWT token is required
        is_localhost = 'localhost' in self.fuseki_url or '127.0.0.1' in self.fuseki_url
        if not is_localhost and not self.access_token:
            logger.error("❌ No JWT token available. Call get_jwt_token() first.")
            return None
        
        query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
        
        logger.info(f"📊 {query_description}")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}")
        
        headers = {
            'Accept': 'application/sparql-results+json',
        }
        
        # Add JWT authorization for production Fuseki
        if not is_localhost and self.access_token:
            headers['Authorization'] = f'{self.token_type} {self.access_token}'
        
        params = {
            'query': sparql_query
        }
        
        try:
            response = requests.get(
                query_url,
                params=params,
                headers=headers,
                timeout=30
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
    
    def update_fuseki(self, sparql_update: str, update_description: str) -> bool:
        """
        Execute a SPARQL UPDATE against the test dataset in Fuseki.
        
        Args:
            sparql_update: SPARQL UPDATE to execute (DELETE, INSERT, etc.)
            update_description: Description of what the update does
            
        Returns:
            True if successful, False otherwise
        """
        # For production Fuseki, JWT token is required
        is_localhost = 'localhost' in self.fuseki_url or '127.0.0.1' in self.fuseki_url
        if not is_localhost and not self.access_token:
            logger.error("❌ No JWT token available. Call get_jwt_token() first.")
            return False
        
        update_url = f"{self.fuseki_url}/{self.dataset_name}/update"
        
        logger.info(f"🔄 {update_description}")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}")
        
        headers = {
            'Content-Type': 'application/sparql-update',
        }
        
        # Add JWT authorization for production Fuseki
        if not is_localhost and self.access_token:
            headers['Authorization'] = f'{self.token_type} {self.access_token}'
        
        try:
            response = requests.post(
                update_url,
                data=sparql_update,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200 or response.status_code == 204:
                logger.info(f"   ✅ Update successful")
                return True
            else:
                logger.error(f"   ❌ Update failed")
                logger.error(f"   Status code: {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ❌ Error executing update: {e}")
            return False
    
    def count_entities(self) -> bool:
        """Count KGEntity objects in the graph."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT (COUNT(?entity) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity a haley-ai-kg:KGEntity .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting KGEntity objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} KGEntity object(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No entities found\n")
        return False
    
    def count_frames(self) -> bool:
        """Count KGFrame objects in the graph."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT (COUNT(?frame) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame a haley-ai-kg:KGFrame .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting KGFrame objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} KGFrame object(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No frames found\n")
        return False
    
    def count_slots(self) -> bool:
        """Count slot objects (KGTextSlot, KGIntegerSlot, KGDateTimeSlot) in the graph."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT (COUNT(?slot) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                {{
                    ?slot a haley-ai-kg:KGTextSlot .
                }} UNION {{
                    ?slot a haley-ai-kg:KGIntegerSlot .
                }} UNION {{
                    ?slot a haley-ai-kg:KGDateTimeSlot .
                }}
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting slot objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} slot object(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No slots found\n")
        return False
    
    def count_files(self) -> bool:
        """Count FileNode objects in the graph."""
        query = f"""
        PREFIX vital: <http://vital.ai/ontology/vital#>
        
        SELECT (COUNT(?file) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?file a vital:FileNode .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting FileNode objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} FileNode object(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No files found\n")
        return False
    
    def list_files(self) -> bool:
        """List all FileNode objects with their properties."""
        query = f"""
        PREFIX vital: <http://vital.ai/ontology/vital#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?file ?name ?uri ?size ?contentType ?fileURL ?fileType
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?file a vital:FileNode .
                OPTIONAL {{ ?file vital-core:hasName ?name }}
                OPTIONAL {{ ?file vital-core:URIProp ?uri }}
                OPTIONAL {{ ?file vital:hasFileLength ?size }}
                OPTIONAL {{ ?file vital:hasFileContentType ?contentType }}
                OPTIONAL {{ ?file vital:hasFileURL ?fileURL }}
                OPTIONAL {{ ?file vital:hasFileType ?fileType }}
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Listing FileNode objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   📄 Found {len(bindings)} FileNode(s):")
                for i, binding in enumerate(bindings, 1):
                    file_uri = binding.get('file', {}).get('value', 'N/A')
                    name = binding.get('name', {}).get('value', 'N/A')
                    uri_prop = binding.get('uri', {}).get('value', 'N/A')
                    size = binding.get('size', {}).get('value', 'N/A')
                    content_type = binding.get('contentType', {}).get('value', 'N/A')
                    file_url = binding.get('fileURL', {}).get('value', 'N/A')
                    file_type = binding.get('fileType', {}).get('value', 'N/A')
                    
                    logger.info(f"      {i}. {name}")
                    logger.info(f"         URI: {uri_prop}")
                    logger.info(f"         Size: {size} bytes")
                    logger.info(f"         Content Type: {content_type}")
                    logger.info(f"         File URL (S3): {file_url}")
                    logger.info(f"         File Type (MIME): {file_type}")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No files found\n")
        return False
    
    def check_ceo_slots(self) -> bool:
        """Check CEO slot values to verify updates."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?slot ?frameURI ?slotType ?name ?textValue ?dateValue
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?slot haley-ai-kg:hasFrameGraphURI ?frameURI .
                ?slot vital-core:hasName ?name .
                FILTER(CONTAINS(LCASE(?name), "ceo"))
                OPTIONAL {{ ?slot haley-ai-kg:hasKGSlotType ?slotType }}
                OPTIONAL {{ ?slot haley-ai-kg:hasTextSlotValue ?textValue }}
                OPTIONAL {{ ?slot haley-ai-kg:hasDateTimeSlotValue ?dateValue }}
            }}
        }}
        ORDER BY ?name
        """
        
        results = self.query_fuseki(query, "Checking CEO slot values")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} CEO slot(s):")
                for binding in bindings:
                    slot_uri = binding.get('slot', {}).get('value', 'unknown')
                    slot_short = slot_uri.split('/')[-1].replace('>', '') if '/' in slot_uri else slot_uri
                    slot_name = binding.get('name', {}).get('value', 'N/A')
                    slot_type = binding.get('slotType', {}).get('value', 'N/A')
                    slot_type_short = slot_type.split('#')[-1] if '#' in slot_type else slot_type
                    text_value = binding.get('textValue', {}).get('value', None)
                    date_value = binding.get('dateValue', {}).get('value', None)
                    
                    value = text_value if text_value else (date_value if date_value else 'N/A')
                    logger.info(f"      • {slot_name} ({slot_type_short}): {value}")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No CEO slots found\n")
        return False
    
    def list_entities(self) -> bool:
        """List all entities with their names."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?name
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity a haley-ai-kg:KGEntity .
                OPTIONAL {{ ?entity vital-core:hasName ?name }}
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Listing entities")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} entity/entities:")
                for binding in bindings:
                    entity_uri = binding.get('entity', {}).get('value', 'unknown')
                    entity_name = binding.get('name', {}).get('value', 'No name')
                    entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                    logger.info(f"      • {entity_name} ({entity_short})")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No entities found\n")
        return False
    
    def list_frames_by_type(self) -> bool:
        """List all frames grouped by their frame type."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?frame ?name ?frameType
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame a haley-ai-kg:KGFrame .
                OPTIONAL {{ ?frame vital-core:hasName ?name }}
                OPTIONAL {{ ?frame haley-ai-kg:hasKGFrameType ?frameType }}
            }}
        }}
        ORDER BY ?frameType
        """
        
        results = self.query_fuseki(query, "Listing frames by type")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} frame(s):")
                for binding in bindings:
                    frame_uri = binding.get('frame', {}).get('value', 'unknown')
                    frame_name = binding.get('name', {}).get('value', 'No name')
                    frame_type = binding.get('frameType', {}).get('value', 'No type')
                    frame_short = frame_uri.split('/')[-1] if '/' in frame_uri else frame_uri
                    type_short = frame_type.split('#')[-1] if '#' in frame_type else frame_type
                    logger.info(f"      • {frame_name} ({type_short})")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No frames found\n")
        return False
    
    def verify_entity_frame_relationships(self) -> bool:
        """Verify that entities are properly connected to frames via edges."""
        query = f"""
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?edge) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge a haley-ai-kg:Edge_hasEntityKGFrame .
                ?edge vital-core:hasEdgeSource ?entity .
                ?edge vital-core:hasEdgeDestination ?frame .
                ?entity a haley-ai-kg:KGEntity .
                ?frame a haley-ai-kg:KGFrame .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Verifying entity-frame relationships")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} entity-frame edge(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No entity-frame relationships found\n")
        return False
    
    def count_all_triples(self) -> bool:
        """Count all triples in the test graph."""
        query = f"""
        SELECT (COUNT(*) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?s ?p ?o .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting all triples in graph")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Total triples: {count}\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No triples found\n")
        return False
    
    def run_verification(self) -> bool:
        """
        Run the complete verification test.
        
        Returns:
            True if all verifications passed, False otherwise
        """
        logger.info("")
        logger.info("🚀 Starting Direct Fuseki Query Verification")
        logger.info(f"   Testing space: {self.space_id}")
        logger.info(f"   Fuseki dataset: {self.dataset_name}")
        logger.info("")
        
        # Step 1: Get JWT token from Keycloak (only for production Fuseki)
        is_localhost = 'localhost' in self.fuseki_url or '127.0.0.1' in self.fuseki_url
        if not is_localhost:
            if not self.get_jwt_token():
                logger.error("❌ Failed to obtain JWT token. Aborting test.")
                return False
        else:
            logger.info("=" * 80)
            logger.info("🔓 Using Local Fuseki")
            logger.info("=" * 80)
            logger.info("JWT authentication not required for localhost")
            logger.info("")
        
        # Step 2: Count all triples
        logger.info("=" * 80)
        logger.info("📊 Step 2: Verifying Data in Fuseki")
        logger.info("=" * 80)
        logger.info("")
        
        all_passed = True
        
        # Count triples
        if not self.count_all_triples():
            all_passed = False
        
        # Count entities
        if not self.count_entities():
            all_passed = False
        
        # List entities
        if not self.list_entities():
            all_passed = False
        
        # Count frames
        if not self.count_frames():
            all_passed = False
        
        # List frames
        if not self.list_frames_by_type():
            all_passed = False
        
        # Count slots
        if not self.count_slots():
            all_passed = False
        
        # Check CEO slot values (verify updates)
        if not self.check_ceo_slots():
            all_passed = False
        
        # Count files
        if not self.count_files():
            all_passed = False
        
        # List files
        if not self.list_files():
            all_passed = False
        
        # Verify relationships
        if not self.verify_entity_frame_relationships():
            all_passed = False
        
        # Summary
        logger.info("=" * 80)
        if all_passed:
            logger.info("🎉 All Fuseki verification checks passed!")
            logger.info("=" * 80)
            logger.info("")
            logger.info("Summary:")
            logger.info("  ✅ JWT authentication successful")
            logger.info("  ✅ Data present in Fuseki")
            logger.info("  ✅ Entities verified")
            logger.info("  ✅ Frames verified")
            logger.info("  ✅ Slots verified")
            logger.info("  ✅ Files verified")
            logger.info("  ✅ Relationships verified")
            logger.info("")
            logger.info(f"✅ The data from test_realistic_persistent.py is correctly stored in Fuseki!")
        else:
            logger.info("❌ Some verification checks failed")
            logger.info("=" * 80)
            logger.info("")
            logger.info("⚠️  The data may not be properly stored in Fuseki")
        
        return all_passed


def main():
    """Main entry point for the test script."""
    try:
        tester = FusekiDirectQueryTester()
        
        # Check if we should run the DELETE test
        if len(sys.argv) > 1 and sys.argv[1] == '--test-delete':
            logger.info("=" * 80)
            logger.info("🧪 Testing DELETE Query Directly Against Fuseki")
            logger.info("=" * 80)
            logger.info("")
            
            # Get JWT token (only for production Fuseki)
            is_localhost = 'localhost' in tester.fuseki_url or '127.0.0.1' in tester.fuseki_url
            if not is_localhost:
                if not tester.get_jwt_token():
                    logger.error("Failed to get JWT token")
                    sys.exit(1)
            else:
                logger.info("🔓 Using local Fuseki - skipping JWT authentication")
                logger.info("")
            
            # First, query to see current CEO name values
            logger.info("📊 Step 1: Query current CEO name values")
            query = f"""
            PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?value
            WHERE {{
                GRAPH <{tester.graph_id}> {{
                    <http://vital.ai/test/kgentity/slot/acme_corporation_ceo_name> haley-ai-kg:hasTextSlotValue ?value .
                }}
            }}
            """
            results = tester.query_fuseki(query, "Querying CEO name values BEFORE delete")
            if results:
                bindings = results.get('results', {}).get('bindings', [])
                logger.info(f"   Found {len(bindings)} value(s):")
                for binding in bindings:
                    logger.info(f"      • {binding.get('value', {}).get('value', 'N/A')}")
            logger.info("")
            
            # Now run the DELETE query
            logger.info("🔄 Step 2: Execute DELETE query")
            delete_query = """
DELETE {
    GRAPH <urn:realistic_org_graph> {
        <http://vital.ai/test/kgentity/slot/acme_corporation_ceo_name> ?p ?o .
    }
}
WHERE {
    GRAPH <urn:realistic_org_graph> {
        <http://vital.ai/test/kgentity/slot/acme_corporation_ceo_name> ?p ?o .
    }
}
"""
            success = tester.update_fuseki(delete_query, "Deleting CEO name slot")
            logger.info("")
            
            # Query again to see if values were deleted
            logger.info("📊 Step 3: Query CEO name values AFTER delete")
            results = tester.query_fuseki(query, "Querying CEO name values AFTER delete")
            if results:
                bindings = results.get('results', {}).get('bindings', [])
                logger.info(f"   Found {len(bindings)} value(s):")
                for binding in bindings:
                    logger.info(f"      • {binding.get('value', {}).get('value', 'N/A')}")
            logger.info("")
            
            if success:
                logger.info("✅ DELETE query executed successfully")
                logger.info("   Check the results above to see if values were actually deleted")
            else:
                logger.info("❌ DELETE query failed")
            
            sys.exit(0 if success else 1)
        else:
            # Normal verification run
            success = tester.run_verification()
            sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
