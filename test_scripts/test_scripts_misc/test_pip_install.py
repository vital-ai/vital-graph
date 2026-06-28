#!/usr/bin/env python3
"""
Test script to verify different pip installation scenarios for VitalGraph.

This script tests that the optional dependencies are correctly configured
and that the appropriate modules can be imported based on the installation type.
"""

import sys
import importlib
import subprocess
from pathlib import Path


def test_import(module_name, description=""):
    """Test if a module can be imported."""
    try:
        importlib.import_module(module_name)
        print(f"✅ {module_name} - {description}")
        return True
    except ImportError as e:
        print(f"❌ {module_name} - {description} (Error: {e})")
        return False


def test_client_installation():
    """Test that client-only installation works."""
    print("\n🔍 Testing Client Installation Dependencies:")
    
    # Core client dependencies that should always be available
    client_modules = [
        ("requests", "HTTP client library"),
        ("pydantic", "Data validation"),
        ("yaml", "YAML configuration parsing"),
        ("rdflib", "RDF processing"),
        ("vitalgraph.client.vitalgraph_client", "VitalGraph client"),
        ("vitalgraph.client.config.client_config_loader", "Client configuration"),
    ]
    
    success_count = 0
    for module, desc in client_modules:
        if test_import(module, desc):
            success_count += 1
    
    print(f"\nClient Dependencies: {success_count}/{len(client_modules)} available")
    return success_count == len(client_modules)


def test_server_installation():
    """Test that server installation dependencies are available."""
    print("\n🔍 Testing Server Installation Dependencies:")
    
    # Server-specific dependencies
    server_modules = [
        ("fastapi", "FastAPI web framework"),
        ("uvicorn", "ASGI server"),
        ("sqlalchemy", "Database ORM"),
        ("psycopg", "PostgreSQL driver"),
        ("asyncpg", "Async PostgreSQL driver"),
        ("alembic", "Database migrations"),
        ("aiofiles", "Async file operations"),
        ("vitalgraph.main.main", "VitalGraph server main"),
        ("vitalgraph.db.postgresql.postgresql_db_impl", "PostgreSQL implementation"),
    ]
    
    success_count = 0
    for module, desc in server_modules:
        if test_import(module, desc):
            success_count += 1
    
    print(f"\nServer Dependencies: {success_count}/{len(server_modules)} available")
    return success_count == len(server_modules)


def test_console_scripts():
    """Test that console scripts are properly installed."""
    print("\n🔍 Testing Console Scripts:")
    
    scripts_to_test = [
        ("vitalgraphdb", "Server command"),
        ("vitalgraphadmin", "Admin command"),
        ("vitalgraph", "Client command"),
    ]
    
    success_count = 0
    for script, desc in scripts_to_test:
        try:
            result = subprocess.run([script, "--help"], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=10)
            if result.returncode == 0:
                print(f"✅ {script} - {desc}")
                success_count += 1
            else:
                print(f"❌ {script} - {desc} (Exit code: {result.returncode})")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"❌ {script} - {desc} (Error: {e})")
    
    print(f"\nConsole Scripts: {success_count}/{len(scripts_to_test)} available")
    return success_count == len(scripts_to_test)


def get_installation_info():
    """Get information about the current installation."""
    print("📦 Installation Information:")
    
    try:
        import vitalgraph
        if hasattr(vitalgraph, '__version__'):
            print(f"VitalGraph Version: {vitalgraph.__version__}")
        else:
            print("VitalGraph Version: Unknown (development)")
    except ImportError:
        print("VitalGraph: Not installed")
    
    print(f"Python Version: {sys.version}")
    print(f"Python Path: {sys.executable}")


def main():
    """Main test function."""
    print("🧪 VitalGraph Installation Test")
    print("=" * 50)
    
    get_installation_info()
    
    # Test core client functionality (should always work)
    client_ok = test_client_installation()
    
    # Test server functionality (only if server extras installed)
    server_ok = test_server_installation()
    
    # Test console scripts
    scripts_ok = test_console_scripts()
    
    print("\n" + "=" * 50)
    print("📊 Test Summary:")
    print(f"Client Dependencies: {'✅ PASS' if client_ok else '❌ FAIL'}")
    print(f"Server Dependencies: {'✅ PASS' if server_ok else '❌ FAIL (expected if server extras not installed)'}")
    print(f"Console Scripts: {'✅ PASS' if scripts_ok else '❌ FAIL'}")
    
    if client_ok:
        print("\n🎉 Basic VitalGraph client functionality is available!")
        if server_ok:
            print("🎉 Full VitalGraph server functionality is available!")
        else:
            print("ℹ️  For server functionality, install with: pip install vital-graph[server]")
    else:
        print("\n❌ VitalGraph installation has issues. Please check dependencies.")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
