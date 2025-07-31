#!/usr/bin/env python3
"""
Test SPARQL endpoints via HTTP requests to debug 500 errors.
"""

import asyncio
import aiohttp
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_http_sparql_query():
    """Test SPARQL query endpoint via HTTP to debug 500 errors."""
    
    # Server configuration
    base_url = "http://localhost:8001"
    
    # Test credentials (matching server USERS_DB)
    login_data = {
        "username": "admin",
        "password": "admin"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            # Step 1: Login to get authentication token
            print("🔐 Authenticating...")
            async with session.post(
                f"{base_url}/api/login",
                data=login_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            ) as response:
                if response.status != 200:
                    print(f"❌ Login failed: {response.status}")
                    text = await response.text()
                    print(f"Response: {text}")
                    return False
                
                auth_data = await response.json()
                token = auth_data.get("access_token")
                if not token:
                    print("❌ No access token in login response")
                    return False
                
                print(f"✅ Authentication successful")
            
            # Step 2: Test SPARQL query endpoint
            print("\n🔍 Testing SPARQL Query Endpoint via HTTP...")
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            query_data = {
                "query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5",
                "format": "json"
            }
            
            async with session.post(
                f"{base_url}/api/graphs/sparql/wordnet_space/query",
                json=query_data,
                headers=headers
            ) as response:
                print(f"📊 Response status: {response.status}")
                
                if response.status == 500:
                    print("❌ 500 Internal Server Error detected!")
                    text = await response.text()
                    print(f"Error response: {text}")
                    
                    # Try to get more details from response headers
                    print(f"Response headers: {dict(response.headers)}")
                    return False
                elif response.status == 200:
                    result = await response.json()
                    print(f"✅ Query successful!")
                    print(f"Result keys: {list(result.keys())}")
                    return True
                else:
                    print(f"❌ Unexpected status: {response.status}")
                    text = await response.text()
                    print(f"Response: {text}")
                    return False
                    
        except Exception as e:
            print(f"❌ HTTP test failed with exception: {str(e)}")
            return False


async def main():
    """Main test function."""
    print("🚀 TESTING SPARQL ENDPOINTS VIA HTTP")
    print("=" * 50)
    
    success = await test_http_sparql_query()
    
    if success:
        print("\n✅ HTTP SPARQL endpoint test completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ HTTP SPARQL endpoint test failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
