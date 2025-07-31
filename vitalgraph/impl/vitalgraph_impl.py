from vitalgraph.config.config_loader import get_config, ConfigurationError
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
from vitalgraph.space.space_manager import SpaceManager
import asyncio


class VitalGraphImpl:
    def __init__(self, config=None):
        self.config = config
        
        # Load VitalGraph configuration if not provided
        if self.config is None:
            try:
                self.config = get_config()
            except ConfigurationError as e:
                print(f"Warning: Could not load VitalGraph configuration: {e}")
                self.config = None
        
        # Initialize database implementation
        self.db_impl = None
        if self.config:
            try:
                db_config = self.config.get_database_config()
                tables_config = self.config.get_tables_config()
                self.db_impl = PostgreSQLDbImpl(db_config, tables_config, config_loader=self.config)
                print(f"✅ Initialized database implementation successfully with RDF connection pool support")
            except Exception as e:
                print(f"Warning: Could not initialize database: {e}")
                self.db_impl = None
        
        # Initialize SpaceManager with database implementation
        self.space_manager = SpaceManager(db_impl=self.db_impl)
        print(f"✅ Initialized SpaceManager successfully")
        
        # Auto-initialize SpaceManager from database if already connected
        if self.db_impl and self.db_impl.is_connected():
            import asyncio
            try:
                # Run the async initialization in a new event loop if needed
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an async context, we can't run this here
                    print("⚠️ Database already connected - SpaceManager will be initialized on first async access")
                else:
                    loop.run_until_complete(self.space_manager.initialize_from_database())
                    print(f"✅ SpaceManager auto-initialized from database with {len(self.space_manager)} spaces")
            except Exception as e:
                print(f"⚠️ Could not auto-initialize SpaceManager: {e}")
    
    def get_db_impl(self):
        """Return the PostgreSQL database implementation instance."""
        return self.db_impl
    
    def get_config(self):
        """Return the VitalGraph configuration instance."""
        return self.config
    
    def get_space_manager(self):
        """Return the SpaceManager instance."""
        return self.space_manager
        
    async def ensure_space_manager_initialized(self):
        """Ensure SpaceManager is initialized from database if not already done."""
        if (self.space_manager and 
            self.db_impl and 
            self.db_impl.is_connected() and 
            not self.space_manager._initialized):
            await self.space_manager.initialize_from_database()
            print(f"✅ SpaceManager lazy-initialized from database with {len(self.space_manager)} spaces")
    
    async def connect_database(self):
        """Connect to database and automatically initialize SpaceManager."""
        if not self.db_impl:
            print("⚠️ No database implementation available")
            return False
            
        # Connect to database
        connected = await self.db_impl.connect()
        if not connected:
            print("❌ Failed to connect to database")
            return False
            
        # Automatically initialize SpaceManager from database
        await self.space_manager.initialize_from_database()
        print(f"✅ SpaceManager automatically initialized from database with {len(self.space_manager)} spaces")
        return True
    
    async def initialize_space_manager(self):
        """Initialize SpaceManager from database after database connection is established."""
        if self.space_manager and self.db_impl and self.db_impl.is_connected():
            await self.space_manager.initialize_from_database()
            print(f"✅ SpaceManager initialized from database with {len(self.space_manager)} spaces")
        else:
            print(f"⚠️ Cannot initialize SpaceManager: db_impl connected={self.db_impl.is_connected() if self.db_impl else False}")
