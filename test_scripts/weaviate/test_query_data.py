#!/usr/bin/env python3
"""
Test script to query Weaviate data and display complete objects including vectors.

This script demonstrates:
1. Connecting to Weaviate with JWT authentication
2. Querying objects from a collection
3. Retrieving complete object data including vectors
4. Pretty printing the results
"""

import os
import sys
from pathlib import Path
import json
import requests
import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.query import MetadataQuery
from dotenv import load_dotenv
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable weaviate client debug logging
logging.getLogger('weaviate').setLevel(logging.DEBUG)
logging.getLogger('httpx').setLevel(logging.INFO)
logging.getLogger('httpcore').setLevel(logging.INFO)


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
        "http_host": os.getenv("WEAVIATE_HTTP_HOST"),
        "grpc_host": os.getenv("WEAVIATE_GRPC_HOST"),
        "grpc_port": int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
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


def pretty_print_object(obj, index):
    """Pretty print a Weaviate object with all its data."""
    print(f"\n{'='*80}")
    print(f"Object {index + 1}")
    print(f"{'='*80}")
    
    # UUID
    print(f"\n📌 UUID: {obj.uuid}")
    
    # Properties
    print(f"\n📝 Properties:")
    for key, value in obj.properties.items():
        print(f"  • {key}: {value}")
    
    # Vector
    if obj.vector:
        print(f"\n🔢 Vector (384 dimensions):")
        # Convert to list if it's a dict-like object
        if hasattr(obj.vector, 'values'):
            vector_list = list(obj.vector.values())
        elif isinstance(obj.vector, dict):
            vector_list = list(obj.vector.values())
        else:
            vector_list = list(obj.vector) if not isinstance(obj.vector, list) else obj.vector
        
        if len(vector_list) > 10:
            print(f"  First 10: {vector_list[:10]}")
            print(f"  ...")
            print(f"  Last 10: {vector_list[-10:]}")
            print(f"  Length: {len(vector_list)}")
        else:
            print(f"  {vector_list}")
    
    # Metadata
    if obj.metadata:
        print(f"\n📊 Metadata:")
        if hasattr(obj.metadata, 'creation_time'):
            print(f"  • Creation time: {obj.metadata.creation_time}")
        if hasattr(obj.metadata, 'last_update_time'):
            print(f"  • Last update: {obj.metadata.last_update_time}")
        if hasattr(obj.metadata, 'distance'):
            print(f"  • Distance: {obj.metadata.distance}")
        if hasattr(obj.metadata, 'certainty'):
            print(f"  • Certainty: {obj.metadata.certainty}")
        if hasattr(obj.metadata, 'score'):
            print(f"  • Score: {obj.metadata.score}")


def query_all_objects_rest(config, token, collection_name="TestArticles"):
    """Query all objects using direct REST API (avoids gRPC issues)."""
    print(f"\n→ Querying all objects from '{collection_name}' via REST API...")
    logger.debug(f"Starting REST API query for collection: {collection_name}")
    
    try:
        # Use GraphQL API via REST to get objects with vectors
        graphql_query = """
        {
          Get {
            TestArticles(limit: 10) {
              _additional {
                id
                creationTimeUnix
                lastUpdateTimeUnix
                vector
              }
              title
              content
              author
              publishDate
            }
          }
        }
        """
        
        logger.debug("Sending GraphQL query via REST...")
        response = requests.post(
            f"https://{config['http_host']}/v1/graphql",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"query": graphql_query},
            timeout=30
        )
        
        logger.debug(f"Response status: {response.status_code}")
        response.raise_for_status()
        
        result = response.json()
        logger.debug(f"Got response: {result}")
        
        if "errors" in result:
            print(f"❌ GraphQL errors: {result['errors']}")
            return False
        
        if "data" not in result or "Get" not in result["data"]:
            print(f"❌ Unexpected response format: {result}")
            return False
        
        objects = result["data"]["Get"].get(collection_name, [])
        object_count = len(objects)
        
        logger.debug(f"Query completed, got {object_count} objects")
        print(f"✓ Retrieved {object_count} object(s)")
        
        if object_count == 0:
            print("  No objects found in collection")
            return True
        
        # Pretty print each object
        for i, obj in enumerate(objects):
            print(f"\n{'='*80}")
            print(f"Object {i + 1}")
            print(f"{'='*80}")
            
            # UUID
            uuid = obj.get("_additional", {}).get("id", "N/A")
            print(f"\n📌 UUID: {uuid}")
            
            # Properties
            print(f"\n📝 Properties:")
            for key, value in obj.items():
                if key != "_additional":
                    print(f"  • {key}: {value}")
            
            # Vector
            vector = obj.get("_additional", {}).get("vector")
            if vector:
                print(f"\n🔢 Vector ({len(vector)} dimensions):")
                print(f"  First 10: {vector[:10]}")
                print(f"  ...")
                print(f"  Last 10: {vector[-10:]}")
            
            # Metadata
            additional = obj.get("_additional", {})
            if additional:
                print(f"\n📊 Metadata:")
                if "creationTimeUnix" in additional:
                    print(f"  • Creation time: {additional['creationTimeUnix']}")
                if "lastUpdateTimeUnix" in additional:
                    print(f"  • Last update: {additional['lastUpdateTimeUnix']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error querying objects: {e}")
        import traceback
        traceback.print_exc()
        return False


def query_all_objects_batch(client, collection_name="TestArticles", auth_label="with JWT"):
    """Query all objects using client iterator (gRPC batch operations)."""
    print(f"\n→ Querying all objects from '{collection_name}' via gRPC batch ({auth_label})...")
    logger.debug(f"Starting gRPC batch query for collection: {collection_name}")
    
    try:
        logger.debug("Getting collection reference...")
        collection = client.collections.get(collection_name)
        logger.debug(f"Got collection: {collection}")
        
        # Use fetch_objects which uses gRPC for batch retrieval
        logger.debug("Executing fetch_objects with vectors...")
        result = collection.query.fetch_objects(
            limit=10,
            include_vector=True,
            return_metadata=MetadataQuery(
                creation_time=True,
                last_update_time=True
            )
        )
        logger.debug(f"Query completed, got {len(result.objects)} objects")
        
        object_count = len(result.objects)
        print(f"✓ Retrieved {object_count} object(s) via gRPC batch ({auth_label})")
        
        if object_count == 0:
            print("  No objects found in collection")
            return True
        
        # Pretty print each object (only first one to keep output concise)
        if object_count > 0:
            pretty_print_object(result.objects[0], 0)
            if object_count > 1:
                print(f"\n  ... and {object_count - 1} more object(s)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error querying objects ({auth_label}): {e}")
        import traceback
        traceback.print_exc()
        return False


def query_all_objects(client, collection_name="TestArticles"):
    """Wrapper that will be replaced by REST API call."""
    print("Note: Using REST API instead of client methods due to gRPC issues")
    return False  # Will be called differently


def query_by_search(client, search_term, collection_name="TestArticles"):
    """Query objects by semantic search."""
    print(f"\n→ Searching for '{search_term}' in '{collection_name}'...")
    logger.debug(f"Starting semantic search for: {search_term}")
    
    try:
        logger.debug("Getting collection reference...")
        collection = client.collections.get(collection_name)
        logger.debug(f"Got collection: {collection}")
        
        # Semantic search with vector
        logger.debug("Executing near_text query...")
        result = collection.query.near_text(
            query=search_term,
            limit=3,
            include_vector=True,
            return_metadata=MetadataQuery(
                distance=True,
                certainty=True
            )
        )
        logger.debug(f"Search completed, got {len(result.objects)} results")
        
        object_count = len(result.objects)
        print(f"✓ Found {object_count} matching object(s)")
        
        if object_count == 0:
            print("  No matching objects found")
            return True
        
        # Pretty print each result
        for i, obj in enumerate(result.objects):
            pretty_print_object(obj, i)
        
        return True
        
    except Exception as e:
        print(f"❌ Error searching objects: {e}")
        import traceback
        traceback.print_exc()
        return False


def export_to_json(client, collection_name="TestArticles", output_file="weaviate_export.json"):
    """Export all objects to JSON file."""
    print(f"\n→ Exporting objects to '{output_file}'...")
    
    try:
        collection = client.collections.get(collection_name)
        
        result = collection.query.fetch_objects(
            limit=100,
            include_vector=True,
            return_metadata=MetadataQuery(
                creation_time=True,
                last_update_time=True
            )
        )
        
        # Convert to JSON-serializable format
        export_data = {
            "collection": collection_name,
            "object_count": len(result.objects),
            "objects": []
        }
        
        for obj in result.objects:
            obj_data = {
                "uuid": str(obj.uuid),
                "properties": obj.properties,
                "vector": obj.vector if obj.vector else None,
                "metadata": {}
            }
            
            if obj.metadata:
                if hasattr(obj.metadata, 'creation_time') and obj.metadata.creation_time:
                    obj_data["metadata"]["creation_time"] = str(obj.metadata.creation_time)
                if hasattr(obj.metadata, 'last_update_time') and obj.metadata.last_update_time:
                    obj_data["metadata"]["last_update_time"] = str(obj.metadata.last_update_time)
            
            export_data["objects"].append(obj_data)
        
        # Write to file
        output_path = Path(__file__).parent / output_file
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✓ Exported {len(result.objects)} objects to {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error exporting objects: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main function."""
    print("=" * 80)
    print("WEAVIATE DATA QUERY TEST")
    print("=" * 80)
    print()
    
    # Load configuration
    config = load_weaviate_config()
    print(f"Configuration loaded:")
    print(f"  - HTTP Host: {config['http_host']}")
    print()
    
    # Get JWT token
    token = get_jwt_token(config)
    
    # Test WITH JWT authentication
    print("\n" + "=" * 80)
    print("TEST 1: Query with JWT Authentication")
    print("=" * 80)
    
    print("\n→ Connecting to Weaviate with JWT...")
    try:
        from weaviate.config import AdditionalConfig, Timeout
        
        client_with_jwt = weaviate.connect_to_custom(
            http_host=config["http_host"],
            http_port=443,
            http_secure=True,
            grpc_host=config["grpc_host"],
            grpc_port=config["grpc_port"],
            grpc_secure=False,
            auth_credentials=Auth.bearer_token(token),
            skip_init_checks=True,
            additional_config=AdditionalConfig(
                timeout=Timeout(init=10, query=30, insert=30)
            )
        )
        print("✓ Connected to Weaviate with JWT\n")
        
        # Query with JWT
        success_with_jwt = query_all_objects_batch(client_with_jwt, auth_label="with JWT")
        client_with_jwt.close()
        
    except Exception as e:
        print(f"❌ Error with JWT: {e}")
        success_with_jwt = False
    
    # Test WITHOUT JWT authentication
    print("\n" + "=" * 80)
    print("TEST 2: Query without JWT Authentication")
    print("=" * 80)
    
    print("\n→ Connecting to Weaviate without JWT...")
    try:
        client_no_jwt = weaviate.connect_to_custom(
            http_host=config["http_host"],
            http_port=443,
            http_secure=True,
            grpc_host=config["grpc_host"],
            grpc_port=config["grpc_port"],
            grpc_secure=False,
            skip_init_checks=True,
            additional_config=AdditionalConfig(
                timeout=Timeout(init=10, query=30, insert=30)
            )
        )
        print("✓ Connected to Weaviate without JWT\n")
        
        # Query without JWT
        success_no_jwt = query_all_objects_batch(client_no_jwt, auth_label="without JWT")
        client_no_jwt.close()
        
    except Exception as e:
        print(f"❌ Error without JWT: {e}")
        import traceback
        traceback.print_exc()
        success_no_jwt = False
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  With JWT:    {'✅ SUCCESS' if success_with_jwt else '❌ FAILED'}")
    print(f"  Without JWT: {'✅ SUCCESS' if success_no_jwt else '❌ FAILED'}")
    
    if success_with_jwt or success_no_jwt:
        print("\n" + "=" * 80)
        print("✅ At least one query method working!")
        print("=" * 80)
        sys.exit(0)
    else:
        print("\n" + "=" * 80)
        print("❌ All query methods failed")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
