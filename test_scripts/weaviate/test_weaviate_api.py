#!/usr/bin/env python3
"""
Test script for Weaviate API access.

Tests REST API, GraphQL API, and gRPC API endpoints with JWT authentication.
Credentials are loaded from .env file in project root.
"""

import os
import sys
from pathlib import Path
import requests
import weaviate
from weaviate.classes.init import Auth
from dotenv import load_dotenv


def load_weaviate_config():
    """Load Weaviate configuration from .env file."""
    # Load .env from project root
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    
    if not env_path.exists():
        print(f"❌ Error: .env file not found at {env_path}")
        print("Please create .env file with Weaviate credentials")
        sys.exit(1)
    
    load_dotenv(env_path)
    
    config = {
        "keycloak_url": os.getenv("WEAVIATE_KEYCLOAK_URL"),
        "client_id": os.getenv("WEAVIATE_CLIENT_ID"),
        "client_secret": os.getenv("WEAVIATE_CLIENT_SECRET"),
        "username": os.getenv("WEAVIATE_USERNAME"),
        "password": os.getenv("WEAVIATE_PASSWORD"),
        "rest_url": os.getenv("WEAVIATE_REST_URL"),
        "http_host": os.getenv("WEAVIATE_HTTP_HOST"),
        "grpc_host": os.getenv("WEAVIATE_GRPC_HOST"),
        "grpc_port": int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
    }
    
    # Validate required fields
    missing = [k for k, v in config.items() if not v]
    if missing:
        print(f"❌ Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    
    return config


def get_jwt_token(config):
    """Get JWT token from Keycloak."""
    print("→ Getting JWT token from Keycloak...")
    
    try:
        response = requests.post(
            config["keycloak_url"],
            data={
                "grant_type": "password",
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "username": config["username"],
                "password": config["password"],
                "scope": "openid profile email"
            },
            timeout=10
        )
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            print("❌ Error: No access_token in response")
            print(f"Response: {token_data}")
            sys.exit(1)
        
        expires_in = token_data.get("expires_in", "unknown")
        print(f"✓ Token obtained (expires in {expires_in} seconds)\n")
        
        return access_token
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error getting token: {e}")
        sys.exit(1)


def test_rest_api(config, token):
    """Test Weaviate REST API."""
    print("→ Testing REST API (/v1/meta)...")
    
    try:
        response = requests.get(
            f"{config['rest_url']}/meta",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        response.raise_for_status()
        
        meta = response.json()
        
        # Print full raw response
        import json
        print(f"✓ REST API working")
        print(f"\nFull /v1/meta response:")
        print(json.dumps(meta, indent=2))
        
        version = meta.get("version", "unknown")
        modules = meta.get("modules", {})
        module_count = len(modules)
        
        print(f"\n  - Version: {version}")
        print(f"  - Modules: {module_count}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ REST API error: {e}")
        return False


def test_graphql_api(config, token):
    """Test Weaviate GraphQL API."""
    print("\n→ Testing GraphQL API...")
    
    try:
        # Simple introspection query
        query = """
        {
            __schema {
                queryType {
                    name
                }
            }
        }
        """
        
        response = requests.post(
            f"{config['rest_url']}/graphql",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"query": query},
            timeout=10
        )
        
        # Print detailed error information before raising
        if response.status_code != 200:
            import json
            print(f"❌ GraphQL API error: {response.status_code} {response.reason}")
            print(f"\nRequest URL: {response.url}")
            print(f"Request Headers: {dict(response.request.headers)}")
            print(f"\nResponse Status: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            print(f"\nResponse Body:")
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text)
            return False
        
        response.raise_for_status()
        
        result = response.json()
        
        if "data" in result:
            print("✓ GraphQL API working")
            return True
        elif "errors" in result:
            print(f"⚠ GraphQL API responded with errors: {result['errors']}")
            return True  # Still counts as working if we got a response
        else:
            print(f"❌ Unexpected GraphQL response: {result}")
            return False
        
    except requests.exceptions.RequestException as e:
        print(f"❌ GraphQL API error: {e}")
        return False


def test_grpc_api(config, token):
    """Test Weaviate gRPC API using Python client."""
    print("\n→ Testing gRPC API (via Python client)...")
    
    try:
        # Connect to Weaviate with gRPC
        client = weaviate.connect_to_custom(
            http_host=config["http_host"],
            http_port=443,
            http_secure=True,
            grpc_host=config["grpc_host"],
            grpc_port=config["grpc_port"],
            grpc_secure=False,
            auth_credentials=Auth.bearer_token(token),
            skip_init_checks=True
        )
        
        # Test gRPC by listing collections
        collections = client.collections.list_all()
        collection_count = len(collections)
        
        print(f"✓ gRPC API working")
        print(f"  - Collections: {collection_count}")
        
        if collection_count > 0:
            print(f"  - Collection names: {', '.join(list(collections.keys())[:5])}")
            if collection_count > 5:
                print(f"    ... and {collection_count - 5} more")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"❌ gRPC API error: {e}")
        return False


def main():
    """Main test function."""
    print("=" * 78)
    print("WEAVIATE API TEST SCRIPT")
    print("=" * 78)
    print()
    
    # Load configuration
    config = load_weaviate_config()
    print(f"Configuration loaded:")
    print(f"  - Keycloak: {config['keycloak_url']}")
    print(f"  - REST API: {config['rest_url']}")
    print(f"  - gRPC: {config['grpc_host']}:{config['grpc_port']}")
    print()
    
    # Get JWT token
    token = get_jwt_token(config)
    
    # Run tests
    results = {
        "REST API": test_rest_api(config, token),
        "GraphQL API": test_graphql_api(config, token),
        "gRPC API": test_grpc_api(config, token),
    }
    
    # Summary
    print("\n" + "=" * 78)
    print("TEST SUMMARY")
    print("=" * 78)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("✅ All endpoints working!")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
