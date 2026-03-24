#!/usr/bin/env python3
"""
Test script to call Weaviate vectorization endpoint with JWT authentication.

This script demonstrates:
1. Getting JWT token from Keycloak
2. Calling Weaviate vectorization endpoint to generate embeddings
3. Displaying the resulting vector
"""

import os
import sys
from pathlib import Path
import json
import requests
from dotenv import load_dotenv


def load_weaviate_config():
    """Load Weaviate configuration from .env file."""
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    
    if not env_path.exists():
        print(f"❌ Error: .env file not found at {env_path}")
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
    }
    
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
            sys.exit(1)
        
        expires_in = token_data.get("expires_in", "unknown")
        print(f"✓ Token obtained (expires in {expires_in} seconds)\n")
        
        return access_token
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error getting token: {e}")
        sys.exit(1)


def test_vectorization_endpoint(config, token, text, use_auth=True):
    """Test Weaviate vectorization endpoint."""
    auth_status = "with JWT" if use_auth else "without JWT"
    print(f"→ Testing vectorization endpoint {auth_status}...")
    print(f"  Input text: \"{text}\"\n")
    
    # Try different possible vectorization endpoints
    endpoints_to_try = [
        f"https://{config['http_host']}/vectors",  # Exact path from user example
        f"{config['rest_url']}/vectors",
        f"https://{config['http_host']}/v1/modules/text2vec-transformers/vectors",
    ]
    
    for endpoint in endpoints_to_try:
        print(f"→ Trying endpoint: {endpoint}")
        
        try:
            headers = {"Content-Type": "application/json"}
            if use_auth:
                headers["Authorization"] = f"Bearer {token}"
            
            response = requests.post(
                endpoint,
                headers=headers,
                json={"text": text},
                timeout=30
            )
            
            print(f"  Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✓ Vectorization successful!")
                
                # Display the vector
                if "vector" in result:
                    vector = result["vector"]
                    print(f"\n🔢 Generated Vector:")
                    print(f"  Dimensions: {len(vector)}")
                    print(f"  First 10 values: {vector[:10]}")
                    print(f"  Last 10 values: {vector[-10:]}")
                    print(f"\n  Full vector (JSON):")
                    print(json.dumps(result, indent=2))
                    return True
                else:
                    print(f"  Response: {json.dumps(result, indent=2)}")
                    
            elif response.status_code == 404:
                print(f"  ❌ Endpoint not found (404)")
                continue
            else:
                print(f"  ❌ Error: {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"  Response: {json.dumps(error_data, indent=2)}")
                except:
                    print(f"  Response: {response.text}")
                continue
                
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Request failed: {e}")
            continue
    
    print(f"\n❌ All vectorization endpoints failed")
    return False


def test_module_capabilities(config, token):
    """Check what vectorization modules are available."""
    print(f"\n→ Checking available vectorization modules...")
    
    try:
        response = requests.get(
            f"{config['rest_url']}/meta",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        response.raise_for_status()
        
        meta = response.json()
        modules = meta.get("modules", {})
        
        print(f"\n📋 Available Vectorization Modules:")
        vectorization_modules = {k: v for k, v in modules.items() if "text2vec" in k or "multi2vec" in k}
        
        for module_name, module_info in vectorization_modules.items():
            print(f"\n  • {module_name}")
            if isinstance(module_info, dict):
                if "name" in module_info:
                    print(f"    Name: {module_info['name']}")
                if "documentationHref" in module_info:
                    print(f"    Docs: {module_info['documentationHref']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking modules: {e}")
        return False


def main():
    """Main function."""
    print("=" * 80)
    print("WEAVIATE VECTORIZATION ENDPOINT TEST")
    print("=" * 80)
    print()
    
    # Load configuration
    config = load_weaviate_config()
    print(f"Configuration loaded:")
    print(f"  - REST URL: {config['rest_url']}")
    print(f"  - HTTP Host: {config['http_host']}")
    print()
    
    # Get JWT token
    token = get_jwt_token(config)
    
    # Check available modules
    test_module_capabilities(config, token)
    
    # Test vectorization with sample text
    test_text = "This is a test sentence for embedding generation"
    
    # Test WITHOUT JWT
    print("\n" + "=" * 80)
    print("VECTORIZATION TEST (WITHOUT JWT)")
    print("=" * 80)
    
    success_without_jwt = test_vectorization_endpoint(config, None, test_text, use_auth=False)
    
    # Test WITH JWT
    print("\n" + "=" * 80)
    print("VECTORIZATION TEST (WITH JWT)")
    print("=" * 80)
    
    success_with_jwt = test_vectorization_endpoint(config, token, test_text, use_auth=True)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Without JWT: {'✅ SUCCESS' if success_without_jwt else '❌ FAILED'}")
    print(f"  With JWT:    {'✅ SUCCESS' if success_with_jwt else '❌ FAILED'}")
    
    if success_without_jwt or success_with_jwt:
        print("\n" + "=" * 80)
        print("✅ Vectorization endpoint is working!")
        print("=" * 80)
        sys.exit(0)
    else:
        print("\n" + "=" * 80)
        print("❌ FAILED: Vectorization endpoint not available")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
