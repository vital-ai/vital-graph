import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from .space_impl import SpaceImpl


@dataclass
class SpaceRecord:
    """
    Record that keeps references to all objects representing a space.
    
    This class encapsulates all the components needed for a complete space:
    - space_id: Unique identifier for the space
    - space_impl: SpaceImpl instance for database operations
    """
    space_id: str
    space_impl: SpaceImpl
    
    def __post_init__(self):
        """Validate the space record after initialization."""
        if not self.space_id:
            raise ValueError("space_id cannot be empty")
        if not isinstance(self.space_impl, SpaceImpl):
            raise TypeError(f"space_impl must be SpaceImpl instance, got {type(self.space_impl)}")
    
    def __repr__(self) -> str:
        return f"SpaceRecord(space_id='{self.space_id}', space_impl={type(self.space_impl).__name__})"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert SpaceRecord to dictionary representation."""
        return {
            'space_id': self.space_id,
            'space_impl_type': type(self.space_impl).__name__,
        }


class SpaceManager:
    """
    Manager for space records that maintains a mapping of space_id to SpaceRecord objects.
    
    This class provides centralized management of all spaces, including their
    SpaceImpl, Dataset, and Store instances. It supports adding, removing, getting,
    and listing space records.
    """
    
    def __init__(self, db_impl=None):
        """Initialize the SpaceManager with an empty space registry.
        
        Args:
            db_impl: Database implementation instance (e.g., PostgreSQLDbImpl)
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.db_impl = db_impl
        self._spaces: Dict[str, SpaceRecord] = {}
        self._initialized = False
        self.logger.info(f"SpaceManager initialized with db_impl: {type(db_impl).__name__ if db_impl else 'None'}")
        
        # Note: Eager initialization will be done via async initialize_from_database() method
    
    async def initialize_from_database(self) -> None:
        """
        Initialize the space manager by loading existing spaces from the database.
        Creates SpaceImpl instances for each space record found.
        This method should be called after SpaceManager construction to eagerly load all spaces.
        """
        if self._initialized:
            self.logger.debug("SpaceManager already initialized from database")
            return
            
        try:
            self.logger.info("Initializing SpaceManager from database...")
            
            if not self.db_impl:
                self.logger.warning("No database implementation available for initialization")
                return
                
            if not self.db_impl.is_connected():
                self.logger.warning("Database not connected, cannot initialize from database")
                return
            
            # Get all space records from database (async call)
            spaces = await self.db_impl.list_spaces()
            self.logger.info(f"Found {len(spaces)} space records in database")
            
            for space_data in spaces:
                space_id = space_data.get('space')
                if space_id:
                    try:
                        # Create SpaceImpl instance
                        space_impl = SpaceImpl(space_id=space_id, db_impl=self.db_impl)
                        
                        # Create SpaceRecord and add to registry
                        space_record = SpaceRecord(space_id=space_id, space_impl=space_impl)
                        self._spaces[space_id] = space_record
                        
                        # Check for orphaned spaces (database record but no tables)
                        if not space_impl.exists():
                            self.logger.warning(f"⚠️ ORPHANED SPACE DETECTED: Space '{space_id}' has database record but no tables!")
                        else:
                            self.logger.debug(f"✅ Space '{space_id}' loaded successfully with tables")
                            
                    except Exception as e:
                        self.logger.error(f"❌ Failed to initialize space '{space_id}': {e}")
                        
            self._initialized = True
            self.logger.info(f"✅ SpaceManager initialized with {len(self._spaces)} spaces from database")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize SpaceManager from database: {e}")
    
    async def create_space_with_tables(self, space_id: str, space_name: str, space_description: str = None) -> bool:
        """
        Create a new space with both database record and tables.
        
        This method orchestrates the complete space creation process:
        1. Creates database record in Space table
        2. Creates SpaceImpl instance
        3. Creates space tables via SpaceImpl
        4. Adds to in-memory registry
        
        Args:
            space_id: Unique identifier for the space
            space_name: Human-readable name for the space
            space_description: Optional description
            
        Returns:
            True if space created successfully, False otherwise
        """
        self.logger.info(f"create_space_with_tables() called for space_id='{space_id}'")
        
        # Validate inputs
        if not space_id or not space_name:
            self.logger.error("space_id and space_name are required")
            return False
            
        if not self.db_impl:
            self.logger.error("No database implementation available")
            return False
            
        # Check if space already exists
        if space_id in self._spaces:
            self.logger.warning(f"Space '{space_id}' already exists in registry")
            return False
            
        try:
            # Create space data dictionary
            space_data = {
                'tenant': None,  # tenant is optional/nullable
                'space': space_id,
                'space_name': space_name,
                'space_description': space_description
            }
            
            space_result = await self.db_impl.add_space(space_data)
            if not space_result:
                self.logger.error(f"Failed to create database record for space '{space_id}'")
                return False
                
            self.logger.debug(f"✅ Created database record for space '{space_id}'")
            
            # Step 2: Create SpaceImpl instance
            space_impl = SpaceImpl(space_id=space_id, db_impl=self.db_impl)
            
            # Step 3: Create space tables
            if not space_impl.create():
                self.logger.error(f"Failed to create tables for space '{space_id}'")
                # Cleanup: remove database record
                try:
                    # Look up space integer ID for removal
                    db_spaces = await self.db_impl.list_spaces()
                    space_record = next((s for s in db_spaces if s.get('space') == space_id), None)
                    if space_record:
                        space_db_id = space_record.get('id')
                        await self.db_impl.remove_space(str(space_db_id))
                        self.logger.debug(f"Cleaned up database record for failed space '{space_id}'")
                except Exception as cleanup_e:
                    self.logger.error(f"Failed to cleanup database record for '{space_id}': {cleanup_e}")
                return False
                
            self.logger.debug(f"✅ Created tables for space '{space_id}'")
            
            # Step 4: Add to registry
            space_record = SpaceRecord(space_id=space_id, space_impl=space_impl)
            self._spaces[space_id] = space_record
            
            self.logger.info(f"✅ Successfully created space '{space_id}' with tables and database record")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create space '{space_id}': {e}")
            return False
    
    async def delete_space_with_tables(self, space_id: str) -> bool:
        """
        Delete a space with complete cleanup of tables and database record.
        
        This method orchestrates the complete space deletion process:
        1. Removes space tables via SpaceImpl
        2. Removes database record from Space table
        3. Removes from in-memory registry
        
        Args:
            space_id: Unique identifier of the space to delete
            
        Returns:
            True if space deleted successfully, False otherwise
        """
        self.logger.info(f"delete_space_with_cleanup() called for space_id='{space_id}'")
        
        if not self.db_impl:
            self.logger.error("No database implementation available")
            return False
            
        # Check if space exists in registry
        if space_id not in self._spaces:
            self.logger.warning(f"Space '{space_id}' not found in registry")
            # Still try to cleanup database record if it exists
            
        success = True
        
        try:
            # Step 1: Delete space tables
            if space_id in self._spaces:
                # Use existing SpaceImpl from registry
                space_record = self._spaces[space_id]
                if not space_record.space_impl.destroy():
                    self.logger.error(f"Failed to delete tables for space '{space_id}'")
                    success = False
                else:
                    self.logger.debug(f"✅ Deleted tables for space '{space_id}'")
            else:
                # Space not in registry, create temporary SpaceImpl for table deletion
                try:
                    temp_space_impl = SpaceImpl(space_id=space_id, db_impl=self.db_impl)
                    if not temp_space_impl.destroy():
                        self.logger.error(f"Failed to delete tables for space '{space_id}'")
                        success = False
                    else:
                        self.logger.debug(f"✅ Deleted tables for space '{space_id}' (via temporary SpaceImpl)")
                except Exception as e:
                    self.logger.error(f"Failed to create temporary SpaceImpl for table deletion: {e}")
                    success = False
            
            # Step 2: Delete database record
            # First get the space to find its integer ID (remove_space expects integer ID)
            db_spaces = await self.db_impl.list_spaces()
            space_record = next((s for s in db_spaces if s.get('space') == space_id), None)
            
            if space_record:
                space_db_id = space_record.get('id')
                if not await self.db_impl.remove_space(str(space_db_id)):
                    self.logger.error(f"Failed to delete database record for space '{space_id}'")
                    success = False
                else:
                    self.logger.debug(f"✅ Deleted database record for space '{space_id}'")
            else:
                self.logger.warning(f"Space '{space_id}' not found in database records")
                # Don't mark as failure since space might already be deleted
            
            # Step 3: Remove from registry
            if space_id in self._spaces:
                # Close the space before removing
                try:
                    self._spaces[space_id].space_impl.close()
                except Exception as close_e:
                    self.logger.warning(f"Error closing space '{space_id}': {close_e}")
                    
                del self._spaces[space_id]
                self.logger.debug(f"✅ Removed space '{space_id}' from registry")
            
            if success:
                self.logger.info(f"✅ Successfully deleted space '{space_id}' with complete cleanup")
            else:
                self.logger.error(f"❌ Partial failure deleting space '{space_id}'")
                
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Failed to delete space '{space_id}': {e}")
            return False
    
    def detect_orphaned_spaces(self) -> List[str]:
        """
        Detect spaces that have database records but no corresponding tables.
        
        Returns:
            List of space_ids that are orphaned
        """
        orphaned_spaces = []
        
        try:
            self.logger.info("Detecting orphaned spaces...")
            
            for space_id, space_record in self._spaces.items():
                if not space_record.space_impl.exists():
                    orphaned_spaces.append(space_id)
                    self.logger.error(f"⚠️ ORPHANED SPACE: '{space_id}' has database record but no tables")
                    
            if orphaned_spaces:
                self.logger.warning(f"Found {len(orphaned_spaces)} orphaned spaces: {orphaned_spaces}")
            else:
                self.logger.info("✅ No orphaned spaces detected")
                
        except Exception as e:
            self.logger.error(f"Error detecting orphaned spaces: {e}")
            
        return orphaned_spaces
    
    def create_space(self, space_id: str) -> SpaceImpl:
        """
        Create a new SpaceImpl instance.
        
        Args:
            space_id: Unique identifier for the space
            
        Returns:
            SpaceImpl instance configured with the space_id and database implementation
            
        Raises:
            ValueError: If space_id is empty or None
            RuntimeError: If no database implementation is available
        """
        self.logger.info(f"create_space() called for space_id='{space_id}'")
        
        # Validate space_id
        if not space_id:
            raise ValueError("space_id cannot be empty or None")
        
        # Check if database implementation is available
        if self.db_impl is None:
            raise RuntimeError("Cannot create space: no database implementation available")
        
        try:
            # Create SpaceImpl instance
            space_impl = SpaceImpl(space_id=space_id, db_impl=self.db_impl)
            self.logger.info(f"✅ Created SpaceImpl for space_id='{space_id}'")
            self.logger.debug(f"SpaceImpl instance: {space_impl}")
            return space_impl
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create SpaceImpl for space_id='{space_id}': {e}")
            raise
    
    def add_space_record(self, space_record: SpaceRecord) -> bool:
        """
        Add a space record to the manager.
        
        Args:
            space_record: SpaceRecord instance to add
            
        Returns:
            True if added successfully, False if space_id already exists
        """
        self.logger.info(f"add_space_record() called for space_id='{space_record.space_id}'")
        
        if space_record.space_id in self._spaces:
            self.logger.warning(f"Space '{space_record.space_id}' already exists, cannot add")
            return False
        
        try:
            # Validate the space record
            space_record.__post_init__()
            
            # Add to registry
            self._spaces[space_record.space_id] = space_record
            self.logger.info(f"✅ Space '{space_record.space_id}' added successfully")
            self.logger.debug(f"Space record: {space_record}")
            return True
            
        except (ValueError, TypeError) as e:
            self.logger.error(f"❌ Failed to add space '{space_record.space_id}': {e}")
            return False
    
    def remove_space(self, space_id: str) -> bool:
        """
        Remove a space record from the manager.
        
        Args:
            space_id: Unique identifier of the space to remove
            
        Returns:
            True if removed successfully, False if space_id doesn't exist
        """
        self.logger.info(f"remove_space() called for space_id='{space_id}'")
        
        if space_id not in self._spaces:
            self.logger.warning(f"Space '{space_id}' not found, cannot remove")
            return False
        
        try:
            # Get the space record before removing
            space_record = self._spaces[space_id]
            
            # Close the space components if they have close methods
            try:
                if hasattr(space_record.space_impl, 'close'):
                    space_record.space_impl.close()
                    self.logger.debug(f"SpaceImpl closed for space '{space_id}'")
                    
            except Exception as e:
                self.logger.warning(f"Error closing space components for '{space_id}': {e}")
            
            # Remove from registry
            del self._spaces[space_id]
            self.logger.info(f"✅ Space '{space_id}' removed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to remove space '{space_id}': {e}")
            return False
    
    def get_space(self, space_id: str) -> Optional[SpaceRecord]:
        """
        Get a space record by space_id.
        
        Args:
            space_id: Unique identifier of the space to retrieve
            
        Returns:
            SpaceRecord instance if found, None otherwise
        """
        self.logger.debug(f"get_space() called for space_id='{space_id}'")
        
        space_record = self._spaces.get(space_id)
        if space_record:
            self.logger.debug(f"✅ Space '{space_id}' found")
        else:
            self.logger.debug(f"❌ Space '{space_id}' not found")
        
        return space_record
    
    def list_spaces(self) -> List[str]:
        """
        List all space_ids currently managed.
        
        Returns:
            List of space_id strings
        """
        self.logger.debug(f"list_spaces() called")
        space_ids = list(self._spaces.keys())
        self.logger.debug(f"Found {len(space_ids)} spaces: {space_ids}")
        return space_ids
    
    def list_space_records(self) -> List[SpaceRecord]:
        """
        List all space records currently managed.
        
        Returns:
            List of SpaceRecord instances
        """
        self.logger.debug(f"list_space_records() called")
        space_records = list(self._spaces.values())
        self.logger.debug(f"Found {len(space_records)} space records")
        return space_records
    
    def get_space_count(self) -> int:
        """
        Get the number of spaces currently managed.
        
        Returns:
            Number of spaces
        """
        count = len(self._spaces)
        self.logger.debug(f"get_space_count() returning {count}")
        return count
    
    def has_space(self, space_id: str) -> bool:
        """
        Check if a space exists in the manager.
        
        Args:
            space_id: Unique identifier of the space to check
            
        Returns:
            True if space exists, False otherwise
        """
        exists = space_id in self._spaces
        self.logger.debug(f"has_space('{space_id}') returning {exists}")
        return exists
    
    def get_space_info(self, space_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a space.
        
        Args:
            space_id: Unique identifier of the space
            
        Returns:
            Dictionary with space information, None if space doesn't exist
        """
        self.logger.debug(f"get_space_info() called for space_id='{space_id}'")
        
        space_record = self._spaces.get(space_id)
        if not space_record:
            self.logger.debug(f"Space '{space_id}' not found")
            return None
        
        info = space_record.to_dict()
        self.logger.debug(f"Space info for '{space_id}': {info}")
        return info
    
    def clear_all_spaces(self) -> int:
        """
        Remove all spaces from the manager.
        
        Returns:
            Number of spaces that were removed
        """
        self.logger.info("clear_all_spaces() called")
        
        count = len(self._spaces)
        if count == 0:
            self.logger.info("No spaces to clear")
            return 0
        
        # Close all space components
        for space_id, space_record in self._spaces.items():
            try:
                if hasattr(space_record.space_impl, 'close'):
                    space_record.space_impl.close()
                
            except Exception as e:
                self.logger.warning(f"Error closing space components for '{space_id}': {e}")
        
        # Clear the registry
        self._spaces.clear()
        self.logger.info(f"✅ Cleared {count} spaces")
        return count
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get overall status of the SpaceManager.
        
        Returns:
            Dictionary with manager status information
        """
        status = {
            'total_spaces': len(self._spaces),
            'space_ids': list(self._spaces.keys()),
            'manager_class': self.__class__.__name__
        }
        self.logger.debug(f"SpaceManager status: {status}")
        return status
    
    def __len__(self) -> int:
        """Return the number of spaces managed."""
        return len(self._spaces)
    
    def __contains__(self, space_id: str) -> bool:
        """Check if a space_id is managed by this manager."""
        return space_id in self._spaces
    
    def __iter__(self):
        """Iterate over space_ids."""
        return iter(self._spaces.keys())
    
    def __repr__(self) -> str:
        return f"SpaceManager(spaces={len(self._spaces)}, space_ids={list(self._spaces.keys())})"
