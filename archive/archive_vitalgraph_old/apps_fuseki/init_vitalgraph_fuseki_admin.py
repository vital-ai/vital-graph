#!/usr/bin/env python3
"""
Initialize VitalGraph with multi-dataset Fuseki backend.

Steps:
1. Create admin dataset (vitalgraph_admin)
2. Initialize admin dataset with RDF schema
3. Create initial install record
4. Validate connectivity to all endpoints
5. Set up default admin user (optional)

Usage:
    python scripts/init_vitalgraph_fuseki_admin.py
    python scripts/init_vitalgraph_fuseki_admin.py --config /path/to/config.yaml
"""

import sys
import os
import asyncio
import argparse
import yaml
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.db.fuseki_postgresql.fuseki_dataset_manager import FusekiDatasetManager
from vitalgraph.db.fuseki_postgresql.fuseki_admin_dataset import FusekiAdminDataset
from vitalgraph.db.fuseki_postgresql.postgresql_db_impl import FusekiPostgreSQLDbImpl

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = None) -> dict:
    """Load VitalGraph configuration."""
    if config_path:
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
    else:
        # Default config locations (checked in order)
        possible_configs = [
            project_root / "vitalgraphdb_config" / "vitalgraphdb-config-local.yaml",
            project_root / "vitalgraphdb_config" / "vitalgraphdb-config-production.yaml",
            project_root / "vitalgraphdb_config" / "vitalgraphdb-config-fuseki-postgresql.yaml",
            project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        ]
        
        config_file = None
        for config_path in possible_configs:
            if config_path.exists():
                config_file = config_path
                break
        
        if not config_file:
            raise FileNotFoundError("No configuration file found. Please specify --config or ensure config exists.")
    
    logger.info(f"Loading configuration from: {config_file}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


async def validate_fuseki_connectivity(fuseki_config: dict) -> bool:
    """Validate basic connectivity to Fuseki server."""
    try:
        dataset_manager = FusekiDatasetManager(fuseki_config)
        await dataset_manager.connect()
        
        # Try to list datasets to validate connectivity
        datasets = await dataset_manager.list_datasets()
        logger.info(f"Fuseki server connectivity validated. Found {len(datasets)} datasets.")
        
        await dataset_manager.disconnect()
        return True
        
    except Exception as e:
        logger.error(f"Failed to validate Fuseki connectivity: {e}")
        return False


async def validate_postgresql_connectivity(postgresql_config: dict) -> bool:
    """Validate basic connectivity to PostgreSQL server."""
    try:
        db_impl = FusekiPostgreSQLDbImpl(postgresql_config)
        connected = await db_impl.connect()
        
        if connected:
            logger.info("PostgreSQL server connectivity validated.")
            await db_impl.disconnect()
            return True
        else:
            logger.error("Failed to connect to PostgreSQL server.")
            return False
        
    except Exception as e:
        logger.error(f"Failed to validate PostgreSQL connectivity: {e}")
        return False


async def initialize_admin_dataset(fuseki_config: dict) -> bool:
    """Initialize the admin dataset with schema and install record."""
    try:
        admin_dataset = FusekiAdminDataset(fuseki_config)
        await admin_dataset.connect()
        
        # Step 1: Create and initialize admin dataset
        logger.info("Creating admin dataset...")
        success = await admin_dataset.initialize_admin_dataset()
        if not success:
            logger.error("Failed to initialize admin dataset")
            return False
        
        # Step 2: Create install record
        logger.info("Creating install record...")
        success = await admin_dataset.create_install_record()
        if not success:
            logger.error("Failed to create install record")
            return False
        
        await admin_dataset.disconnect()
        logger.info("Admin dataset initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing admin dataset: {e}")
        return False


async def initialize_postgresql_schema(postgresql_config: dict) -> bool:
    """Initialize PostgreSQL schema for admin tables."""
    try:
        db_impl = FusekiPostgreSQLDbImpl(postgresql_config)
        await db_impl.connect()
        
        # Initialize admin schema
        logger.info("Initializing PostgreSQL admin schema...")
        success = await db_impl.initialize_schema()
        if not success:
            logger.error("Failed to initialize PostgreSQL schema")
            return False
        
        await db_impl.disconnect()
        logger.info("PostgreSQL admin schema initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL schema: {e}")
        return False


async def create_test_space(fuseki_config: dict, postgresql_config: dict, space_id: str = "test_space") -> bool:
    """Create a test space to validate the multi-dataset architecture."""
    try:
        # Initialize components
        dataset_manager = FusekiDatasetManager(fuseki_config)
        admin_dataset = FusekiAdminDataset(fuseki_config)
        db_impl = FusekiPostgreSQLDbImpl(postgresql_config)
        
        await dataset_manager.connect()
        await admin_dataset.connect()
        await db_impl.connect()
        
        # Step 1: Create Fuseki dataset for space
        logger.info(f"Creating Fuseki dataset for test space: {space_id}")
        success = await dataset_manager.create_dataset(space_id)
        if not success:
            logger.error(f"Failed to create Fuseki dataset for space {space_id}")
            return False
        
        # Step 2: Create PostgreSQL backup tables
        logger.info(f"Creating PostgreSQL backup tables for space: {space_id}")
        success = await db_impl.create_space_backup_tables(space_id)
        if not success:
            logger.error(f"Failed to create PostgreSQL backup tables for space {space_id}")
            # Cleanup: Delete Fuseki dataset
            await dataset_manager.delete_dataset(space_id)
            return False
        
        # Step 3: Register space in admin dataset
        logger.info(f"Registering space in admin dataset: {space_id}")
        success = await admin_dataset.register_space(
            space_id=space_id,
            space_name="Test Space",
            space_description="Test space for validating multi-dataset architecture",
            tenant="default"
        )
        if not success:
            logger.error(f"Failed to register space {space_id} in admin dataset")
            # Cleanup
            await dataset_manager.delete_dataset(space_id)
            await db_impl.drop_space_backup_tables(space_id)
            return False
        
        # Cleanup connections
        await dataset_manager.disconnect()
        await admin_dataset.disconnect()
        await db_impl.disconnect()
        
        logger.info(f"Test space '{space_id}' created successfully with multi-dataset architecture")
        return True
        
    except Exception as e:
        logger.error(f"Error creating test space: {e}")
        return False


async def validate_setup(fuseki_config: dict) -> bool:
    """Validate the complete setup by querying admin dataset."""
    try:
        admin_dataset = FusekiAdminDataset(fuseki_config)
        await admin_dataset.connect()
        
        # List all spaces
        spaces = await admin_dataset.list_spaces()
        logger.info(f"Validation: Found {len(spaces)} registered spaces")
        
        for space in spaces:
            logger.info(f"  - Space: {space['space_id']} ({space['space_name']})")
            
            # List graphs for each space
            graphs = await admin_dataset.list_graphs_for_space(space['space_id'])
            logger.info(f"    Graphs: {len(graphs)}")
        
        await admin_dataset.disconnect()
        return True
        
    except Exception as e:
        logger.error(f"Error validating setup: {e}")
        return False


async def main():
    """Main initialization function."""
    parser = argparse.ArgumentParser(description='Initialize VitalGraph Fuseki Admin Dataset')
    parser.add_argument('--config', help='Path to configuration file')
    parser.add_argument('--skip-test-space', action='store_true', help='Skip creating test space')
    parser.add_argument('--validate-only', action='store_true', help='Only validate existing setup')
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Extract backend configurations
        if config.get('backend', {}).get('type') == 'fuseki_postgresql':
            fuseki_config = config['fuseki_postgresql']['fuseki']
            postgresql_config = config['fuseki_postgresql']['database']
        else:
            # Fallback to separate configs
            fuseki_config = config.get('fuseki', {})
            postgresql_config = config.get('database', {})
        
        if not fuseki_config or not postgresql_config:
            logger.error("Missing fuseki or postgresql configuration")
            return False
        
        logger.info("🚀 Starting VitalGraph Fuseki Admin Dataset Initialization")
        
        # Step 1: Validate connectivity
        logger.info("Step 1: Validating connectivity...")
        
        fuseki_ok = await validate_fuseki_connectivity(fuseki_config)
        if not fuseki_ok:
            logger.error("❌ Fuseki connectivity validation failed")
            return False
        
        postgresql_ok = await validate_postgresql_connectivity(postgresql_config)
        if not postgresql_ok:
            logger.error("❌ PostgreSQL connectivity validation failed")
            return False
        
        logger.info("✅ Connectivity validation successful")
        
        if args.validate_only:
            # Just validate existing setup
            logger.info("Validating existing setup...")
            success = await validate_setup(fuseki_config)
            if success:
                logger.info("✅ Setup validation successful")
            else:
                logger.error("❌ Setup validation failed")
            return success
        
        # Step 2: Initialize PostgreSQL schema
        logger.info("Step 2: Initializing PostgreSQL schema...")
        success = await initialize_postgresql_schema(postgresql_config)
        if not success:
            logger.error("❌ PostgreSQL schema initialization failed")
            return False
        logger.info("✅ PostgreSQL schema initialized")
        
        # Step 3: Initialize admin dataset
        logger.info("Step 3: Initializing admin dataset...")
        success = await initialize_admin_dataset(fuseki_config)
        if not success:
            logger.error("❌ Admin dataset initialization failed")
            return False
        logger.info("✅ Admin dataset initialized")
        
        # Step 4: Create test space (optional)
        if not args.skip_test_space:
            logger.info("Step 4: Creating test space...")
            success = await create_test_space(fuseki_config, postgresql_config)
            if not success:
                logger.error("❌ Test space creation failed")
                return False
            logger.info("✅ Test space created")
        
        # Step 5: Final validation
        logger.info("Step 5: Final validation...")
        success = await validate_setup(fuseki_config)
        if not success:
            logger.error("❌ Final validation failed")
            return False
        
        logger.info("🎉 VitalGraph Fuseki Admin Dataset initialization completed successfully!")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Start your VitalGraph service with backend.type: fuseki_postgresql")
        logger.info("2. Create spaces using the VitalGraph API")
        logger.info("3. Each space will get its own Fuseki dataset + PostgreSQL backup tables")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
