from vitalgraph.config.config_loader import get_config, ConfigurationError
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
from vitalgraph.space.space_manager import SpaceManager
from vitalgraph.signal.signal_manager import SignalManager
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
        
        self.space_manager = SpaceManager(db_impl=self.db_impl)
        print(f"✅ Initialized SpaceManager successfully")
        
        # Initialize SignalManager (will be fully initialized after DB connection)
        self.signal_manager = None
            
    def get_db_impl(self):
        """Return the PostgreSQL database implementation instance."""
        return self.db_impl
    
    def get_config(self):
        """Return the VitalGraph configuration instance."""
        return self.config
    
    def get_space_manager(self):
        """Return the SpaceManager instance."""
        return self.space_manager
        
    def get_signal_manager(self):
        """Return the SignalManager instance."""
        return self.signal_manager
        
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
        print("🔍 TRACE: VitalGraphImpl.connect_database() called")
        if not self.db_impl:
            print("⚠️ No database implementation available")
            return False
            
        # Connect to database
        print(f"🔍 DEBUG: Starting database connection in VitalGraphImpl.connect_database()")
        connected = await self.db_impl.connect()
        if not connected:
            print("❌ Failed to connect to database")
            return False
        print(f"✅ DEBUG: Database connected successfully")
            
        try:
            print(f"🔍 DEBUG: Creating SignalManager in VitalGraphImpl")
            self.signal_manager = SignalManager(db_impl=self.db_impl)
            print(f"✅ DEBUG: SignalManager created: {self.signal_manager}")
        
            print(f"🔍 DEBUG: Setting SignalManager on db_impl")
            self.db_impl.set_signal_manager(self.signal_manager)
            print(f"✅ DEBUG: SignalManager set on db_impl")
            print(f"🔍 DEBUG: Verifying get_signal_manager: {self.db_impl.get_signal_manager()}")
        except Exception as e:
            print(f"❌ ERROR creating/setting SignalManager: {e}")
            import traceback
            print(traceback.format_exc())

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
