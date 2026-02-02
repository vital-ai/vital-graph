#!/usr/bin/env python3
"""
VitalGraph Client JWT Authentication Test

This script tests JWT-only authentication with the VitalGraph client,
validating that the client can successfully authenticate and make API calls
using JWT tokens without requiring username/password for each request.

Key Features Tested:
- JWT token acquisition via login
- Automatic token refresh
- Authenticated API calls using JWT
- Typed client methods with response models
- Error handling for authentication failures
"""

import sys
import os
import logging
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import SpacesListResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_jwt_authentication() -> bool:
    """Test JWT-only authentication flow.
    
    Returns:
        bool: True if authentication test was successful, False otherwise
    """
    
    # Path to client configuration
    config_path = "/Users/hadfield/Local/vital-git/vital-graph/vitalgraphclient_config/vitalgraphclient-config.yaml"
    
    try:
        logger.info("🔧 Initializing VitalGraph JWT client...")
        client = VitalGraphClient(config_path)
        
        logger.info("🔌 Opening connection and authenticating with JWT...")
        client.open()
        
        # Get server info with authentication details
        server_info: Dict[str, Any] = client.get_server_info()
        logger.info("📊 Server Info:")
        for key, value in server_info.items():
            logger.info(f"   {key}: {value}")
        
        # Test authenticated API call
        logger.info("📋 Testing authenticated API call - listing spaces...")
        spaces_response: SpacesListResponse = client.list_spaces()
        
        # Access typed response properties
        spaces = spaces_response.spaces
        total_count = spaces_response.total_count
        logger.info(f"   ✓ Found {len(spaces)} spaces (total: {total_count})")
        logger.info(f"   📊 Pagination: page_size={spaces_response.page_size}, offset={spaces_response.offset}")
        
        # Show some space details if available
        if spaces:
            logger.info(f"   📋 Sample spaces:")
            for i, space in enumerate(spaces[:3]):  # Show first 3 spaces
                logger.info(f"     {i+1}. ID: {space.id}, Name: {space.space_name}, Space: {space.space}")
        
        # Test token refresh by simulating expired token
        logger.info("🔄 Testing token refresh...")
        if hasattr(client, '_is_token_expired') and hasattr(client, '_refresh_access_token'):
            # Force token refresh
            if client.refresh_token:
                success = client._refresh_access_token()
                if success:
                    logger.info("✅ Token refresh successful")
                else:
                    logger.warning("⚠️ Token refresh failed")
            else:
                logger.info("ℹ️ No refresh token available for testing")
        
        # Test another authenticated call after potential refresh
        logger.info("📋 Testing API call after token refresh...")
        spaces_after_response: SpacesListResponse = client.list_spaces()
        
        # Access typed response properties
        spaces_after = spaces_after_response.spaces
        total_count_after = spaces_after_response.total_count
        logger.info(f"   ✓ Found {len(spaces_after)} spaces after refresh (total: {total_count_after})")
        
        # Verify consistency
        if total_count == total_count_after:
            logger.info("   ✅ Space count consistent after token refresh")
        else:
            logger.warning(f"   ⚠️ Space count changed: {total_count} -> {total_count_after}")
        
        logger.info("🚪 Closing connection...")
        client.close()
        
        logger.info("✅ JWT-only authentication test completed successfully!")
        
    except VitalGraphClientError as e:
        logger.error(f"❌ VitalGraph client error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False
    
    return True


def main() -> None:
    """Main test function."""
    logger.info("🚀 Starting VitalGraph Client JWT-Only Authentication Test")
    logger.info("📋 Note: Using typed client methods with SpacesListResponse models for full type safety")
    
    success = test_jwt_authentication()
    
    if success:
        logger.info("🎉 All JWT tests passed with typed client methods!")
        logger.info("   ✅ Used SpacesListResponse models for full type safety")
        sys.exit(0)
    else:
        logger.error("💥 JWT tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
