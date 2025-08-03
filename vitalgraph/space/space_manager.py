import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import asyncio
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
    
    @property
    def exists(self) -> bool:
        """Flag to indicate that this space exists (always True for a SpaceRecord instance)"""
        return True


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
        self.signal_manager = None
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
                        if not await space_impl.exists():
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
        3. Creates tables needed for space operation
        4. Creates default namespace entries (rdf, rdfs, owl, xsd)
        5. Registers space with manager
        
        Args:
            space_id: Unique identifier for the space
            space_name: Human-readable name
            space_description: Optional description
            
        Returns:
            True if space created successfully, False otherwise
        """
        self.logger.info(f"Creating space with tables: '{space_id}'")
        
        if not self.db_impl:
            self.logger.error(f"Cannot create space '{space_id}': No database implementation available")
            return False
            
        if not self.db_impl.is_connected():
            self.logger.error(f"Cannot create space '{space_id}': Database not connected")
            return False
            
        # Check if space already exists in the manager
        if space_id in self._spaces:
            self.logger.error(f"Cannot create space '{space_id}': Space already exists in manager")
            return False
            
        # First check if space record exists in the Space table
        space_record_exists = await self.db_impl.space_record_exists(space_id)
        if space_record_exists:
            self.logger.error(f"Cannot create space '{space_id}': Space record already exists in database")
            return False
            
        # Then check if space tables exist
        space_impl = self.db_impl.get_space_impl()
        if space_impl:
            tables_exist = await space_impl.space_exists(space_id)
            if tables_exist:
                self.logger.warning(f"Unusual state: Space '{space_id}' has tables but no record. May need cleanup.")
                return False
        else:
            self.logger.error(f"Cannot create space '{space_id}': Space implementation not available")
            return False
            
        try:
            # 1. Create space record in database
            space_data = {
                'space': space_id,
                'space_name': space_name,
                'space_description': space_description,
                'tenant': None
            }
            space_result = await self.db_impl.add_space(space_data)
            if not space_result:
                self.logger.error(f"Failed to create space record in database: '{space_id}'")
                return False
                
            self.logger.info(f"Created space record in database: '{space_id}'")
            
            # 2. Create SpaceImpl instance
            space_impl = self.create_space(space_id)
            if not space_impl:
                self.logger.error(f"Failed to create SpaceImpl for '{space_id}'")
                return False
                
            # 3. Create tables for space
            tables_created = await space_impl.create()
            if not tables_created:
                self.logger.error(f"Failed to create tables for space '{space_id}'")
                # Rollback space creation in database
                await self.db_impl.remove_space(space_id)
                return False
                
            # 4. Initialize default namespaces
            await space_impl.initialize_default_namespaces()
            
            # 5. Register space with manager
            space_record = SpaceRecord(space_id=space_id, space_impl=space_impl)
            self._spaces[space_id] = space_record
            
            # Send notifications for space creation
            try:
                from vitalgraph.signal.signal_manager import SIGNAL_TYPE_CREATED
                
                # Get SignalManager instance from db_impl
                signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                
                if signal_manager:
                    # Send notification asynchronously without blocking
                    asyncio.create_task(signal_manager.notify_spaces_changed(SIGNAL_TYPE_CREATED))
                    asyncio.create_task(signal_manager.notify_space_changed(space_id, SIGNAL_TYPE_CREATED))
                    self.logger.info(f"📤 Sent notifications for space creation: '{space_id}'")
                else:
                    self.logger.warning(f"No SignalManager available for notifications")
            except Exception as e:
                # Log but don't fail the operation if notification fails
                self.logger.warning(f"Failed to send notification for space creation: {e}")
                import traceback
                self.logger.warning(f"Notification error traceback: {traceback.format_exc()}")
            
            self.logger.info(f"✅ Successfully created space with tables: '{space_id}'")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating space '{space_id}' with tables: {e}")
            # Attempt to clean up partially created space
            try:
                await self.db_impl.remove_space(space_id)
            except Exception as cleanup_error:
                self.logger.warning(f"Error cleaning up failed space creation for '{space_id}': {cleanup_error}")
            return False
                
    async def delete_space_with_tables(self, space_id: str) -> bool:
        """
        Delete a space with complete cleanup of tables and database record.
        
        This method orchestrates the complete space deletion process:
        1. Removes space tables via SpaceImpl
        2. Removes database record from Space table
        3. Removes space from manager registry
        
        Args:
            space_id: Unique identifier of the space to delete
            
        Returns:
            True if space deleted successfully, False otherwise
        """
        self.logger.info(f"Deleting space with tables: '{space_id}'")
        
        if not self.db_impl:
            self.logger.error(f"Cannot delete space '{space_id}': No database implementation available")
            return False
            
        if not self.db_impl.is_connected():
            self.logger.error(f"Cannot delete space '{space_id}': Database not connected")
            return False
            
        # Check if space exists in the manager
        space_record = self._spaces.get(space_id)
        if not space_record:
            # Check if either space record or tables exist
            # First check the space record
            space_record_exists = await self.db_impl.space_record_exists(space_id)
            
            # Then check the space tables
            space_impl = self.db_impl.get_space_impl()
            if not space_impl:
                self.logger.error(f"Cannot delete space '{space_id}': Space implementation not available")
                return False
                
            tables_exist = await space_impl.space_exists(space_id)
            
            # If neither record nor tables exist, space doesn't exist at all
            if not space_record_exists and not tables_exist:
                self.logger.error(f"Cannot delete space '{space_id}': Space does not exist (no record or tables)")
                return False
                
            # Log warning about inconsistent state if needed
            if space_record_exists and not tables_exist:
                self.logger.warning(f"Space '{space_id}' has record but no tables (inconsistent state)")
            elif not space_record_exists and tables_exist:
                self.logger.warning(f"Space '{space_id}' has tables but no record (inconsistent state)")
                
            # We'll proceed with deletion even in inconsistent state to clean up
                
            # Space exists in database but not in manager, create temporary SpaceImpl
            space_impl = self.create_space(space_id)
        else:
            # Get the existing SpaceImpl
            space_impl = space_record.space_impl
            
        try:
            # 1. Delete tables for space
            tables_deleted = await space_impl.destroy()
            if not tables_deleted:
                self.logger.error(f"Failed to delete tables for space '{space_id}'")
                return False
                
            # 2. Delete space record from database
            space_deleted = await self.db_impl.remove_space(space_id)
            if not space_deleted:
                self.logger.error(f"Failed to delete space record for '{space_id}' from database")
                return False
                
            # 3. Remove space from manager registry
            if space_id in self._spaces:
                # Close the space before removing from registry
                try:
                    self._spaces[space_id].space_impl.close()
                except Exception as close_e:
                    self.logger.warning(f"Error closing space '{space_id}': {close_e}")
                
                # Now remove from registry
                del self._spaces[space_id]
                self.logger.debug(f"\u2705 Removed space '{space_id}' from registry")
            else:
                self.logger.debug(f"Space '{space_id}' was not in registry (already removed)")    
                
            # Send notifications for space deletion
            try:
                from vitalgraph.signal.signal_manager import SIGNAL_TYPE_DELETED
                
                # Get SignalManager instance from db_impl
                signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                
                if signal_manager:
                    # Send notification asynchronously without blocking
                    asyncio.create_task(signal_manager.notify_spaces_changed(SIGNAL_TYPE_DELETED))
                    asyncio.create_task(signal_manager.notify_space_changed(space_id, SIGNAL_TYPE_DELETED))
                    self.logger.info(f"📤 Sent notifications for space deletion: '{space_id}'")
                else:
                    self.logger.warning(f"No SignalManager available for notifications")
            except Exception as e:
                # Log but don't fail the operation if notification fails
                self.logger.warning(f"Failed to send notification for space deletion: {e}")
                import traceback
                self.logger.warning(f"Notification error traceback: {traceback.format_exc()}")
        
            self.logger.info(f"✅ Successfully deleted space '{space_id}' with complete cleanup")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to delete space '{space_id}': {e}")
            return False
    
    async def detect_orphaned_spaces(self) -> List[str]:
        """
        Detect spaces that have database records but no corresponding tables.
        
        Returns:
            List of space_ids that are orphaned
        """
        orphaned_spaces = []
        
        try:
            self.logger.info("Detecting orphaned spaces...")
            
            for space_id, space_record in self._spaces.items():
                if not await space_record.space_impl.exists():
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
    
    
