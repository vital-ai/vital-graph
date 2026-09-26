#!/usr/bin/env python3
"""
Keycloak JWT Authentication Test for Production Fuseki

This script tests the complete authentication flow:
1. Obtain JWT token from Keycloak using username/password
2. Use JWT token to authenticate with production Fuseki endpoint
3. Execute a test SPARQL query to verify access

Configuration is read from the top-level .env file.
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.config.config_loader import get_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KeycloakFusekiAuthTester:
    """Test Keycloak JWT authentication with Fuseki backend."""
    
    def __init__(self):
        """Initialize the tester by loading configuration from VitalGraph config loader."""
        # Load .env from project root
        env_path = project_root / '.env'
        
        if not env_path.exists():
            raise FileNotFoundError(f"No .env file found at {env_path}")
        
        load_dotenv(env_path)
        logger.info(f"Loaded configuration from {env_path}")
        
        # Load configuration using VitalGraph config loader (profile-based)
        config = get_config()
        fuseki_config = config.get_fuseki_config()
        keycloak_config = fuseki_config.get('keycloak', {})
        
        # Keycloak configuration from profile-based config
        self.keycloak_url = keycloak_config.get('url')
        self.keycloak_realm = keycloak_config.get('realm')
        self.keycloak_client_id = keycloak_config.get('client_id')
        self.keycloak_client_secret = keycloak_config.get('client_secret')
        self.keycloak_username = keycloak_config.get('username')
        self.keycloak_password = keycloak_config.get('password')
        
        # Fuseki configuration
        self.fuseki_url = fuseki_config.get('server_url')
        
        # Validate required configuration
        self._validate_config()
        
        # JWT token storage
        self.access_token: Optional[str] = None
        self.token_type: Optional[str] = None
        
        # Discovered datasets
        self.available_datasets: List[str] = []
    
    def _validate_config(self) -> None:
        """Validate that all required configuration is present."""
        required_vars = {
            'KEYCLOAK_URL': self.keycloak_url,
            'KEYCLOAK_REALM': self.keycloak_realm,
            'KEYCLOAK_CLIENT_ID': self.keycloak_client_id,
            'KEYCLOAK_USERNAME': self.keycloak_username,
            'KEYCLOAK_PASSWORD': self.keycloak_password,
            'FUSEKI_URL': self.fuseki_url,
        }
        
        missing = [key for key, value in required_vars.items() if not value]
        
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
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
        logger.info("Step 1: Obtaining JWT token from Keycloak")
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
        logger.info(f"Token endpoint: {token_url}")
        
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
                logger.info(f"Token type: {self.token_type}")
                logger.info(f"Token expires in: {token_data.get('expires_in')} seconds")
                logger.info(f"Token (first 50 chars): {self.access_token[:50]}...")
                
                return True
            else:
                logger.error(f"❌ Failed to obtain JWT token")
                logger.error(f"Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error connecting to Keycloak: {e}")
            return False
    
    def list_fuseki_datasets(self) -> bool:
        """
        List all datasets available in Fuseki.
        
        Returns:
            True if datasets listed successfully, False otherwise
        """
        if not self.access_token:
            logger.error("❌ No JWT token available. Call get_jwt_token() first.")
            return False
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("Step 2: Listing Fuseki datasets")
        logger.info("=" * 80)
        
        # Fuseki datasets endpoint
        datasets_url = f"{self.fuseki_url}/$/datasets"
        
        logger.info(f"Datasets endpoint: {datasets_url}")
        
        # Prepare request with JWT token in Authorization header
        headers = {
            'Authorization': f'{self.token_type} {self.access_token}',
            'Accept': 'application/json',
        }
        
        try:
            response = requests.get(
                datasets_url,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                datasets_data = response.json()
                logger.info("✅ Successfully retrieved Fuseki datasets list")
                
                # Parse and display datasets
                if 'datasets' in datasets_data:
                    datasets = datasets_data['datasets']
                    logger.info(f"Found {len(datasets)} dataset(s):")
                    
                    for dataset in datasets:
                        ds_name = dataset.get('ds.name', 'unknown')
                        ds_state = dataset.get('ds.state', 'unknown')
                        
                        # Store active datasets
                        if ds_state:
                            self.available_datasets.append(ds_name)
                        
                        logger.info(f"  📊 Dataset: {ds_name}")
                        logger.info(f"     State: {'Active' if ds_state else 'Inactive'}")
                        
                        # List services for each dataset
                        if 'ds.services' in dataset:
                            services = dataset['ds.services']
                            logger.info(f"     Services: {len(services)}")
                            for service in services:
                                svc_type = service.get('srv.type', 'unknown')
                                svc_endpoints = service.get('srv.endpoints', [])
                                logger.info(f"       - {svc_type}: {', '.join(svc_endpoints)}")
                else:
                    logger.warning("⚠️  No datasets found in response")
                
                return True
            else:
                logger.error(f"❌ Failed to list datasets")
                logger.error(f"Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error connecting to Fuseki: {e}")
            return False
    
    def test_fuseki_access(self) -> bool:
        """
        Test Fuseki access using the JWT token.
        
        Returns:
            True if Fuseki access successful, False otherwise
        """
        if not self.access_token:
            logger.error("❌ No JWT token available. Call get_jwt_token() first.")
            return False
        
        if not self.available_datasets:
            logger.error("❌ No datasets available. Call list_fuseki_datasets() first.")
            return False
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("Step 3: Testing Fuseki access with JWT token")
        logger.info("=" * 80)
        
        # Use wordnet-frames dataset if available, otherwise use first dataset
        dataset = '/wordnet-frames' if '/wordnet-frames' in self.available_datasets else self.available_datasets[0]
        query_url = f"{self.fuseki_url}{dataset}/query"
        
        # Simple test query to verify access - count triples across all graphs
        test_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            GRAPH ?g {
                ?s ?p ?o
            }
        }
        """
        
        logger.info(f"Fuseki URL: {self.fuseki_url}")
        logger.info(f"Using dataset: {dataset}")
        logger.info(f"Query endpoint: {query_url}")
        logger.info(f"Test query: {test_query.strip()}")
        
        # Prepare request with JWT token in Authorization header
        headers = {
            'Authorization': f'{self.token_type} {self.access_token}',
            'Accept': 'application/sparql-results+json',
        }
        
        params = {
            'query': test_query
        }
        
        try:
            response = requests.get(
                query_url,
                params=params,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                results = response.json()
                logger.info("✅ Successfully accessed Fuseki with JWT token")
                logger.info(f"Query results: {results}")
                
                # Extract count if available
                if 'results' in results and 'bindings' in results['results']:
                    bindings = results['results']['bindings']
                    if bindings and 'count' in bindings[0]:
                        count = bindings[0]['count']['value']
                        logger.info(f"Total triples in dataset: {count}")
                
                return True
            else:
                logger.error(f"❌ Failed to access Fuseki")
                logger.error(f"Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error connecting to Fuseki: {e}")
            return False
    
    def test_fuseki_query(self, sparql_query: str) -> Optional[Dict[str, Any]]:
        """
        Execute a custom SPARQL query against Fuseki.
        
        Args:
            sparql_query: SPARQL query to execute
            
        Returns:
            Query results as dictionary, or None if failed
        """
        if not self.access_token:
            logger.error("❌ No JWT token available. Call get_jwt_token() first.")
            return None
        
        if not self.available_datasets:
            logger.error("❌ No datasets available. Call list_fuseki_datasets() first.")
            return None
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("Step 4: Executing custom SPARQL query")
        logger.info("=" * 80)
        
        # Use wordnet-frames dataset if available, otherwise use first dataset
        dataset = '/wordnet-frames' if '/wordnet-frames' in self.available_datasets else self.available_datasets[0]
        query_url = f"{self.fuseki_url}{dataset}/query"
        
        logger.info(f"Query: {sparql_query}")
        
        headers = {
            'Authorization': f'{self.token_type} {self.access_token}',
            'Accept': 'application/sparql-results+json',
        }
        
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
                logger.info("✅ Query executed successfully")
                
                # Display results
                if 'results' in results and 'bindings' in results['results']:
                    bindings = results['results']['bindings']
                    logger.info(f"Number of results: {len(bindings)}")
                    
                    if bindings:
                        logger.info("First few results:")
                        for i, binding in enumerate(bindings[:5], 1):
                            logger.info(f"  Result {i}: {binding}")
                
                return results
            else:
                logger.error(f"❌ Query failed")
                logger.error(f"Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error executing query: {e}")
            return None
    
    def run_full_test(self) -> bool:
        """
        Run the complete authentication flow test.
        
        Returns:
            True if all tests passed, False otherwise
        """
        logger.info("")
        logger.info("🚀 Starting Keycloak + Fuseki Authentication Flow Test")
        logger.info("")
        
        # Step 1: Get JWT token from Keycloak
        if not self.get_jwt_token():
            logger.error("❌ Failed to obtain JWT token. Aborting test.")
            return False
        
        # Step 2: List available Fuseki datasets
        if not self.list_fuseki_datasets():
            logger.error("❌ Failed to list Fuseki datasets. Aborting test.")
            return False
        
        # Step 3: Test basic Fuseki access
        if not self.test_fuseki_access():
            logger.error("❌ Failed to access Fuseki with JWT token. Aborting test.")
            return False
        
        # Step 4: Execute a more complex query across all graphs
        complex_query = """
        SELECT ?type (COUNT(?s) as ?count)
        WHERE {
            GRAPH ?g {
                ?s a ?type
            }
        }
        GROUP BY ?type
        ORDER BY DESC(?count)
        LIMIT 10
        """
        
        results = self.test_fuseki_query(complex_query)
        
        if results:
            logger.info("")
            logger.info("=" * 80)
            logger.info("🎉 All authentication tests passed successfully!")
            logger.info("=" * 80)
            logger.info("")
            logger.info("Summary:")
            logger.info("  ✅ JWT token obtained from Keycloak")
            logger.info("  ✅ Fuseki datasets listed successfully")
            logger.info("  ✅ Fuseki access verified with JWT authentication")
            logger.info("  ✅ SPARQL queries executed successfully")
            logger.info("")
            return True
        else:
            logger.error("")
            logger.error("=" * 80)
            logger.error("❌ Authentication test failed")
            logger.error("=" * 80)
            return False


def main():
    """Main entry point for the test script."""
    try:
        tester = KeycloakFusekiAuthTester()
        success = tester.run_full_test()
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
