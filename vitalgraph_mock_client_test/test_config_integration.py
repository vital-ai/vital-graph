#!/usr/bin/env python3
"""
Test script to verify that MockFilesEndpoint properly reads and uses configuration settings.

This script tests:
1. Configuration parsing from YAML files
2. MockFilesEndpoint using VitalGraphClientConfig settings
3. Both temporary and configured storage modes
"""

import sys
import tempfile
import yaml
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.client.client_factory import create_mock_client
from vitalgraph.mock.client.endpoint.mock_files_endpoint import MockFilesEndpoint
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager


def test_config_parsing():
    """Test that configuration parameters are parsed correctly."""
    print("=== Testing Configuration Parsing ===")
    
    # Create a temporary config file with mock settings
    config_data = {
        'server': {
            'url': 'http://localhost:8001',
            'api_base_path': '/api/v1'
        },
        'auth': {
            'username': 'admin',
            'password': 'admin'
        },
        'client': {
            'timeout': 30,
            'max_retries': 3,
            'retry_delay': 1,
            'use_mock_client': True,
            'mock': {
                'use_temp_storage': False,
                'filePath': '/tmp/test_mock_storage'
            }
        }
    }
    
    # Write config to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name
    
    try:
        # Load configuration
        config = VitalGraphClientConfig(config_path)
        
        # Test configuration methods
        use_mock = config.use_mock_client()
        use_temp_storage = config.use_temp_storage()
        file_path = config.get_mock_file_path()
        
        print(f"✅ use_mock_client: {use_mock}")
        print(f"✅ use_temp_storage: {use_temp_storage}")
        print(f"✅ filePath: {file_path}")
        
        # Verify values
        assert use_mock == True, f"Expected use_mock_client=True, got {use_mock}"
        assert use_temp_storage == False, f"Expected use_temp_storage=False, got {use_temp_storage}"
        assert file_path == '/tmp/test_mock_storage', f"Expected filePath='/tmp/test_mock_storage', got {file_path}"
        
        print("✅ Configuration parsing test PASSED")
        return config
        
    finally:
        # Clean up temp file
        Path(config_path).unlink()


def test_mock_files_endpoint_with_config():
    """Test MockFilesEndpoint using VitalGraphClientConfig."""
    print("\n=== Testing MockFilesEndpoint with VitalGraphClientConfig ===")
    
    # Test 1: Temporary storage configuration
    print("\n--- Test 1: Temporary Storage ---")
    temp_config_data = {
        'client': {
            'use_mock_client': True,
            'mock': {
                'use_temp_storage': True,
                'filePath': None
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(temp_config_data, f)
        temp_config_path = f.name
    
    try:
        config = VitalGraphClientConfig(temp_config_path)
        space_manager = MockSpaceManager()
        endpoint = MockFilesEndpoint(client=None, space_manager=space_manager, config=config)
        
        print(f"✅ Storage type: {'Temporary' if endpoint._use_temp_storage else 'Configured'}")
        print(f"✅ MinIO path exists: {endpoint.minio_base_path is not None}")
        print(f"✅ MinIO client configured: {endpoint.minio_client is not None}")
        
        assert endpoint._use_temp_storage == True, "Expected temporary storage"
        assert endpoint.minio_base_path is not None, "Expected MinIO path to be configured"
        assert endpoint.minio_client is not None, "Expected MinIO client to be configured"
        
    finally:
        Path(temp_config_path).unlink()
    
    # Test 2: Configured storage
    print("\n--- Test 2: Configured Storage ---")
    configured_storage_dir = tempfile.mkdtemp(prefix="test_configured_storage_")
    
    configured_config_data = {
        'client': {
            'use_mock_client': True,
            'mock': {
                'use_temp_storage': False,
                'filePath': configured_storage_dir
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(configured_config_data, f)
        configured_config_path = f.name
    
    try:
        config = VitalGraphClientConfig(configured_config_path)
        space_manager = MockSpaceManager()
        endpoint = MockFilesEndpoint(client=None, space_manager=space_manager, config=config)
        
        print(f"✅ Storage type: {'Temporary' if endpoint._use_temp_storage else 'Configured'}")
        print(f"✅ MinIO path: {endpoint.minio_base_path}")
        print(f"✅ MinIO client configured: {endpoint.minio_client is not None}")
        
        assert endpoint._use_temp_storage == False, "Expected configured storage"
        assert str(endpoint.minio_base_path) == configured_storage_dir, f"Expected path {configured_storage_dir}"
        assert endpoint.minio_client is not None, "Expected MinIO client to be configured"
        
    finally:
        Path(configured_config_path).unlink()
        # Clean up configured storage directory
        import shutil
        shutil.rmtree(configured_storage_dir)
    
    # Test 3: No storage configuration (should fail)
    print("\n--- Test 3: No Storage Configuration ---")
    no_storage_config_data = {
        'client': {
            'use_mock_client': True,
            'mock': {
                'use_temp_storage': False,
                'filePath': None
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(no_storage_config_data, f)
        no_storage_config_path = f.name
    
    try:
        config = VitalGraphClientConfig(no_storage_config_path)
        space_manager = MockSpaceManager()
        endpoint = MockFilesEndpoint(client=None, space_manager=space_manager, config=config)
        
        print(f"✅ Storage type: {'Temporary' if endpoint._use_temp_storage else 'Configured'}")
        print(f"✅ MinIO path: {endpoint.minio_base_path}")
        print(f"✅ MinIO client configured: {endpoint.minio_client is not None}")
        
        assert endpoint._use_temp_storage == False, "Expected configured storage"
        assert endpoint.minio_base_path is None, "Expected no MinIO path"
        assert endpoint.minio_client is None, "Expected no MinIO client"
        
        # Test that file operations fail
        try:
            endpoint.upload_file_content("test_space", "test_uri", "test_file.txt")
            assert False, "Expected upload to fail"
        except RuntimeError as e:
            print(f"✅ Upload correctly failed: {e}")
        
    finally:
        Path(no_storage_config_path).unlink()
    
    print("✅ MockFilesEndpoint configuration test PASSED")


def test_client_factory_integration():
    """Test that the client factory properly passes config to MockFilesEndpoint."""
    print("\n=== Testing Client Factory Integration ===")
    
    # Create config with temporary storage
    config_data = {
        'client': {
            'use_mock_client': True,
            'mock': {
                'use_temp_storage': True,
                'filePath': None
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name
    
    try:
        # Create mock client using factory
        mock_client = create_mock_client(config_path)
        
        # Check that files endpoint is properly configured
        files_endpoint = mock_client.files
        
        print(f"✅ Mock client created successfully")
        print(f"✅ Files endpoint storage type: {'Temporary' if files_endpoint._use_temp_storage else 'Configured'}")
        print(f"✅ Files endpoint MinIO configured: {files_endpoint.minio_client is not None}")
        
        assert files_endpoint._use_temp_storage == True, "Expected temporary storage"
        assert files_endpoint.minio_client is not None, "Expected MinIO client configured"
        
        print("✅ Client factory integration test PASSED")
        
    finally:
        Path(config_path).unlink()


def main():
    """Run all configuration integration tests."""
    print("MockFilesEndpoint Configuration Integration Tests")
    print("=" * 60)
    
    try:
        # Test configuration parsing
        test_config_parsing()
        
        # Test MockFilesEndpoint with config
        test_mock_files_endpoint_with_config()
        
        # Test client factory integration
        test_client_factory_integration()
        
        print("\n" + "=" * 60)
        print("🎉 All configuration integration tests PASSED!")
        print("MockFilesEndpoint properly reads and uses YAML configuration settings.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Configuration integration test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
