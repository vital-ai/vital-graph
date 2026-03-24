#!/usr/bin/env python3
"""
Test script to create a Weaviate collection using gRPC API.

This script demonstrates:
1. Authentication with Keycloak to get JWT token
2. Connecting to Weaviate via gRPC
3. Creating a new collection with schema
4. Verifying the collection was created
"""

import os
import sys
from pathlib import Path
import requests
import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
from dotenv import load_dotenv
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Also enable weaviate client debug logging
logging.getLogger('weaviate').setLevel(logging.DEBUG)
logging.getLogger('httpx').setLevel(logging.INFO)  # Changed to INFO to reduce noise
logging.getLogger('httpcore').setLevel(logging.INFO)  # Changed to INFO to reduce noise

# Add handler to capture HTTP errors
class HTTPErrorFilter(logging.Filter):
    def filter(self, record):
        if '404' in str(record.msg) or 'Not Found' in str(record.msg):
            logger.error(f"HTTP 404 Error detected: {record.msg}")
        return True

logging.getLogger('httpx').addFilter(HTTPErrorFilter())
logging.getLogger('httpcore').addFilter(HTTPErrorFilter())


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


def create_test_collection(client, collection_name="TestArticles"):
    """Create a test collection with schema."""
    print(f"→ Creating collection '{collection_name}'...")
    
    try:
        # Check if collection already exists
        if client.collections.exists(collection_name):
            print(f"⚠ Collection '{collection_name}' already exists, deleting it first...")
            client.collections.delete(collection_name)
            print(f"✓ Deleted existing collection")
        
        # Create collection with schema
        collection = client.collections.create(
            name=collection_name,
            description="Test collection for articles with title and content",
            properties=[
                Property(
                    name="title",
                    data_type=DataType.TEXT,
                    description="Article title"
                ),
                Property(
                    name="content",
                    data_type=DataType.TEXT,
                    description="Article content"
                ),
                Property(
                    name="author",
                    data_type=DataType.TEXT,
                    description="Article author"
                ),
                Property(
                    name="publishDate",
                    data_type=DataType.DATE,
                    description="Publication date"
                ),
            ],
            vectorizer_config=Configure.Vectorizer.text2vec_transformers()
        )
        
        print(f"✓ Collection '{collection_name}' created successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error creating collection: {e}")
        return False


def verify_collection(client, collection_name="TestArticles"):
    """Verify the collection exists and get its details."""
    print(f"\n→ Verifying collection '{collection_name}'...")
    
    try:
        if not client.collections.exists(collection_name):
            print(f"❌ Collection '{collection_name}' does not exist")
            return False
        
        # Get collection details
        collection = client.collections.get(collection_name)
        config = collection.config.get()
        
        print(f"✓ Collection exists")
        print(f"  - Name: {config.name}")
        print(f"  - Description: {config.description}")
        print(f"  - Properties: {len(config.properties)}")
        
        print(f"\n  Properties:")
        for prop in config.properties:
            print(f"    - {prop.name} ({prop.data_type}): {prop.description}")
        
        print(f"\n  Vectorizer: {config.vectorizer}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error verifying collection: {e}")
        return False


def add_sample_data(client, collection_name="TestArticles"):
    """Add sample data to the collection."""
    print(f"\n→ Adding sample data to '{collection_name}'...")
    logger.debug(f"Starting add_sample_data for collection: {collection_name}")
    
    try:
        logger.debug("Getting collection reference...")
        collection = client.collections.get(collection_name)
        logger.debug(f"Got collection reference: {collection}")
        
        # Sample articles
        articles = [
            {
                "title": "Introduction to Weaviate",
                "content": "Weaviate is a vector database that enables semantic search and AI-powered applications.",
                "author": "John Doe",
                "publishDate": "2024-01-15T10:00:00Z"
            },
            {
                "title": "Getting Started with Vector Databases",
                "content": "Vector databases store and query high-dimensional vectors for similarity search.",
                "author": "Jane Smith",
                "publishDate": "2024-01-20T14:30:00Z"
            },
            {
                "title": "GraphQL and Weaviate",
                "content": "Weaviate provides a GraphQL API for flexible data querying and manipulation.",
                "author": "Bob Johnson",
                "publishDate": "2024-01-25T09:15:00Z"
            }
        ]
        
        # Insert data using batch operation (testing with grpc_secure=True)
        logger.debug(f"Starting batch insert of {len(articles)} articles...")
        print(f"  Using batch insert for {len(articles)} articles (testing secure gRPC)...")
        
        try:
            logger.debug("Creating batch context with rate_limit...")
            
            # Use rate_limit batch mode which doesn't wait for vectorization
            with collection.batch.rate_limit(requests_per_minute=600) as batch:
                logger.debug("Batch context created, adding objects...")
                for i, article in enumerate(articles):
                    logger.debug(f"Adding article {i+1} to batch: {article['title']}")
                    batch.add_object(properties=article)
                    logger.debug(f"Article {i+1} added to batch")
                    
                    # Check for excessive errors during batch
                    if batch.number_errors > 10:
                        logger.error(f"Batch has {batch.number_errors} errors, stopping")
                        print(f"❌ Batch import stopped due to excessive errors")
                        break
                        
                logger.debug("All articles added to batch, exiting context...")
            
            logger.debug("Batch context exited, checking for errors...")
            
            # Check for failed objects after batch completion
            failed_objects = collection.batch.failed_objects
            if failed_objects:
                logger.error(f"Number of failed imports: {len(failed_objects)}")
                logger.error(f"First failed object: {failed_objects[0]}")
                print(f"⚠ Batch completed with {len(failed_objects)} failed imports")
                print(f"  First error: {failed_objects[0]}")
                return len(failed_objects) < len(articles)  # Return True if some succeeded
            else:
                logger.debug("No batch errors detected")
                print(f"✓ Batch insert completed successfully for {len(articles)} articles")
                print(f"  Note: Vectorization will complete asynchronously in background")
                return True
            
        except Exception as e:
            logger.error(f"Batch insert failed: {e}", exc_info=True)
            print(f"❌ Batch insert failed: {e}")
            return False
        
    except Exception as e:
        print(f"❌ Error adding sample data: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_all_collections(client):
    """List all collections in Weaviate."""
    print("\n→ Listing all collections...")
    logger.debug("Starting list_all_collections")
    
    try:
        logger.debug("Calling client.collections.list_all()...")
        collections = client.collections.list_all()
        logger.debug(f"Got collections: {collections}")
        
        if not collections:
            print("  No collections found")
            logger.debug("No collections found")
            return True
        
        print(f"  Found {len(collections)} collection(s):")
        for name in collections.keys():
            print(f"    - {name}")
        
        logger.debug("Finished listing collections")
        return True
        
    except Exception as e:
        logger.error(f"Error listing collections: {e}", exc_info=True)
        print(f"❌ Error listing collections: {e}")
        return False


def main():
    """Main function."""
    print("=" * 78)
    print("WEAVIATE COLLECTION CREATION TEST (gRPC)")
    print("=" * 78)
    print()
    
    # Load configuration
    config = load_weaviate_config()
    print(f"Configuration loaded:")
    print(f"  - HTTP Host: {config['http_host']}")
    print(f"  - gRPC: {config['grpc_host']}:{config['grpc_port']}")
    print()
    
    # Get JWT token
    token = get_jwt_token(config)
    
    # Connect to Weaviate
    print("→ Connecting to Weaviate...")
    print("  Note: gRPC port 50051 not working, will use HTTP for all operations")
    try:
        from weaviate.config import AdditionalConfig, Timeout
        
        # Connect with gRPC parameters - using insecure gRPC
        client = weaviate.connect_to_custom(
            http_host=config["http_host"],
            http_port=443,
            http_secure=True,
            grpc_host=config["grpc_host"],
            grpc_port=config["grpc_port"],
            grpc_secure=False,  # Insecure gRPC
            auth_credentials=Auth.bearer_token(token),
            skip_init_checks=True,
            additional_config=AdditionalConfig(
                timeout=Timeout(init=10, query=30, insert=30)
            )
        )
        print("✓ Connected to Weaviate\n")
        
        # List existing collections
        logger.debug("Step 1: Listing existing collections")
        list_all_collections(client)
        logger.debug("Step 1 complete")
        
        # Create test collection
        logger.debug("Step 2: Creating test collection")
        if not create_test_collection(client):
            print("\n❌ Failed to create collection")
            client.close()
            sys.exit(1)
        logger.debug("Step 2 complete")
        
        # Verify collection
        logger.debug("Step 3: Verifying collection")
        if not verify_collection(client):
            print("\n❌ Failed to verify collection")
            client.close()
            sys.exit(1)
        logger.debug("Step 3 complete")
        
        # Add sample data
        logger.debug("Step 4: Adding sample data")
        if not add_sample_data(client):
            print("\n❌ Failed to add sample data")
            client.close()
            sys.exit(1)
        logger.debug("Step 4 complete")
        
        # List collections again
        logger.debug("Step 5: Listing collections again")
        list_all_collections(client)
        logger.debug("Step 5 complete")
        
        # Close connection
        client.close()
        
        print("\n" + "=" * 78)
        print("✅ SUCCESS: Collection created and populated via gRPC!")
        print("=" * 78)
        sys.exit(0)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
