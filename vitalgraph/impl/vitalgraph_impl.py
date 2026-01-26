from vitalgraph.config.config_loader import get_config, ConfigurationError
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
from vitalgraph.db.backend_config import BackendFactory, BackendConfig, BackendType
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
        
        # Initialize database implementation using BackendFactory
        self.db_impl = None
        if self.config:
            try:
                # Check for backend configuration
                backend_config = self.config.get_backend_config()
                backend_type = backend_config.get('type', 'postgresql').lower()
                
                print(f"🔍 DEBUG: Backend type detected: '{backend_type}'")
                print(f"🔍 DEBUG: Backend config: {backend_config}")
                
                if backend_type == 'fuseki':
                    # Create Fuseki backend configuration
                    fuseki_config = self.config.get_fuseki_config()
                    backend_config_obj = BackendConfig(
                        backend_type=BackendType.FUSEKI,
                        connection_params={
                            'server_url': fuseki_config.get('server_url', 'http://localhost:3030'),
                            'dataset_name': fuseki_config.get('dataset_name', 'vitalgraph'),
                            'username': fuseki_config.get('username', 'vitalgraph_user'),
                            'password': fuseki_config.get('password', 'vitalgraph_pass')
                        }
                    )
                    # Use BackendFactory to create space backend (Fuseki doesn't have db_impl)
                    self.space_backend = BackendFactory.create_space_backend(backend_config_obj)
                    print(f"✅ Initialized Fuseki backend successfully: {fuseki_config.get('server_url')}")
                    
                elif backend_type == 'fuseki_postgresql':
                    print(f"🔍 DEBUG: Initializing fuseki_postgresql hybrid backend...")
                    # Create Fuseki-PostgreSQL hybrid backend configuration
                    fuseki_postgresql_config = self.config.get_fuseki_postgresql_config()
                    print(f"🔍 DEBUG: Fuseki-PostgreSQL config: {fuseki_postgresql_config}")
                    
                    backend_config_obj = BackendConfig(
                        backend_type=BackendType.FUSEKI_POSTGRESQL,
                        connection_params=fuseki_postgresql_config
                    )
                    print(f"🔍 DEBUG: Created BackendConfig object for FUSEKI_POSTGRESQL")
                    
                    # Use BackendFactory to create hybrid space backend
                    print(f"🔍 DEBUG: Calling BackendFactory.create_space_backend()...")
                    self.space_backend = BackendFactory.create_space_backend(backend_config_obj)
                    print(f"🔍 DEBUG: Space backend created: {type(self.space_backend)}")
                    
                    # For hybrid backend, also create the db_impl from the space backend
                    if hasattr(self.space_backend, 'postgresql_impl'):
                        self.db_impl = self.space_backend.postgresql_impl
                        print(f"🔍 DEBUG: Set db_impl from space_backend.postgresql_impl: {type(self.db_impl)}")
                    else:
                        print(f"⚠️ DEBUG: space_backend does not have postgresql_impl attribute")
                    print(f"✅ Initialized Fuseki-PostgreSQL hybrid backend successfully")
                    
                else:
                    # Default to PostgreSQL - create both db_impl and space_backend
                    db_config = self.config.get_database_config()
                    tables_config = self.config.get_tables_config()
                    self.db_impl = PostgreSQLDbImpl(db_config, tables_config, config_loader=self.config)
                    
                    # Also create PostgreSQL space backend for consistent interface
                    postgresql_config = BackendConfig(
                        backend_type=BackendType.POSTGRESQL,
                        connection_params=db_config
                    )
                    self.space_backend = BackendFactory.create_space_backend(postgresql_config)
                    print(f"✅ Initialized PostgreSQL database implementation successfully with RDF connection pool support")
                    
            except Exception as e:
                print(f"❌ ERROR: Could not initialize backend: {e}")
                print(f"🔍 DEBUG: Exception type: {type(e)}")
                import traceback
                print(f"🔍 DEBUG: Full traceback:")
                traceback.print_exc()
                self.db_impl = None
                self.space_backend = None
        
        # Initialize SpaceManager with the appropriate backend
        print(f"🔍 DEBUG: About to create SpaceManager")
        print(f"🔍 DEBUG: self.db_impl = {self.db_impl}")
        print(f"🔍 DEBUG: self.space_backend = {getattr(self, 'space_backend', None)}")
        
        if self.db_impl is None:
            print(f"❌ ERROR: Cannot create SpaceManager - db_impl is None")
            self.space_manager = None
        else:
            try:
                backend = getattr(self, 'space_backend', None) or self.db_impl
                self.space_manager = SpaceManager(db_impl=self.db_impl, space_backend=getattr(self, 'space_backend', None))
                print(f"✅ Initialized SpaceManager successfully: {self.space_manager}")
            except Exception as e:
                print(f"❌ ERROR: Failed to create SpaceManager: {e}")
                import traceback
                traceback.print_exc()
                self.space_manager = None
        
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
            
        # Connect to database and space backend
        print(f"🔍 DEBUG: Starting database connection in VitalGraphImpl.connect_database()")
        
        # For hybrid backends, connect the space_backend which handles both systems
        if hasattr(self, 'space_backend') and self.space_backend:
            print(f"🔍 DEBUG: Connecting hybrid space backend: {type(self.space_backend)}")
            connected = await self.space_backend.connect()
            if not connected:
                print("❌ Failed to connect to hybrid space backend")
                return False
            print(f"✅ DEBUG: Hybrid space backend connected successfully")
        else:
            # For non-hybrid backends, connect db_impl directly
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
