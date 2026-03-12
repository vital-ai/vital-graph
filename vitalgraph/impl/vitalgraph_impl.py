import asyncio
import logging

from vitalgraph.config.config_loader import get_config, ConfigurationError
from vitalgraph.db.backend_config import BackendFactory, BackendConfig, BackendType
from vitalgraph.space.space_manager import SpaceManager
from vitalgraph.signal.signal_manager import SignalManager

logger = logging.getLogger(__name__)


class VitalGraphImpl:
    def __init__(self, config=None):
        self.config = config
        
        # Load VitalGraph configuration if not provided
        if self.config is None:
            try:
                self.config = get_config()
            except ConfigurationError as e:
                logger.warning(f"Could not load VitalGraph configuration: {e}")
                self.config = None
        
        # Initialize database implementation using BackendFactory
        self.db_impl = None
        if self.config:
            try:
                # Check for backend configuration
                backend_config = self.config.get_backend_config()
                backend_type = backend_config.get('type', 'postgresql').lower()
                
                logger.debug(f"🔍 Backend type detected: '{backend_type}'")
                logger.debug(f"🔍 Backend config: {backend_config}")
                
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
                    logger.info(f"✅ Initialized Fuseki backend successfully: {fuseki_config.get('server_url')}")
                    
                elif backend_type == 'sparql_sql':
                    logger.debug("Initializing sparql_sql backend...")
                    sparql_sql_config = self.config.get_sparql_sql_config()

                    backend_config_obj = BackendConfig(
                        backend_type=BackendType.SPARQL_SQL,
                        connection_params=sparql_sql_config
                    )

                    self.space_backend = BackendFactory.create_space_backend(backend_config_obj)

                    # SparqlSQLSpaceImpl owns a SparqlSQLDbImpl (created on connect)
                    if hasattr(self.space_backend, 'db_impl'):
                        self.db_impl = self.space_backend.db_impl
                    logger.info("Initialized sparql_sql backend (sidecar=%s)",
                                sparql_sql_config.get('sidecar', {}).get('url', 'http://localhost:7070'))

                elif backend_type == 'fuseki_postgresql':
                    logger.debug(f"🔍 Initializing fuseki_postgresql hybrid backend...")
                    # Create Fuseki-PostgreSQL hybrid backend configuration
                    fuseki_postgresql_config = self.config.get_fuseki_postgresql_config()
                    logger.debug(f"🔍 Fuseki-PostgreSQL config: {fuseki_postgresql_config}")
                    
                    backend_config_obj = BackendConfig(
                        backend_type=BackendType.FUSEKI_POSTGRESQL,
                        connection_params=fuseki_postgresql_config
                    )
                    logger.debug(f"🔍 Created BackendConfig object for FUSEKI_POSTGRESQL")
                    
                    # Use BackendFactory to create hybrid space backend
                    logger.debug(f"🔍 Calling BackendFactory.create_space_backend()...")
                    self.space_backend = BackendFactory.create_space_backend(backend_config_obj)
                    logger.debug(f"🔍 Space backend created: {type(self.space_backend)}")
                    
                    # For hybrid backend, also create the db_impl from the space backend
                    if hasattr(self.space_backend, 'postgresql_impl'):
                        self.db_impl = self.space_backend.postgresql_impl
                        logger.debug(f"🔍 Set db_impl from space_backend.postgresql_impl: {type(self.db_impl)}")
                    else:
                        logger.warning(f"⚠️ space_backend does not have postgresql_impl attribute")
                    logger.info(f"✅ Initialized Fuseki-PostgreSQL hybrid backend successfully")
                    
                else:
                    raise ValueError(
                        f"Unsupported backend type: '{backend_type}'. "
                        f"The 'postgresql' (V1) backend has been archived. "
                        f"Use 'sparql_sql' or 'fuseki_postgresql' instead."
                    )
                    
            except Exception as e:
                logger.error(f"❌ Could not initialize backend: {e}")
                logger.debug(f"🔍 Exception type: {type(e)}")
                import traceback
                logger.debug(f"🔍 Full traceback:\n{traceback.format_exc()}")
                self.db_impl = None
                self.space_backend = None
        
        # Initialize SpaceManager with the appropriate backend
        # Note: sparql_sql backend has db_impl=None until connect() is called
        logger.debug(f"🔍 About to create SpaceManager")
        logger.debug(f"🔍 self.db_impl = {self.db_impl}")
        logger.debug(f"🔍 self.space_backend = {getattr(self, 'space_backend', None)}")
        
        if self.db_impl is None and not getattr(self, 'space_backend', None):
            logger.error(f"❌ Cannot create SpaceManager - no db_impl or space_backend")
            self.space_manager = None
        elif self.db_impl is None and getattr(self, 'space_backend', None):
            # sparql_sql backend: create SpaceManager now so endpoints get a real reference;
            # db_impl will be set after connect()
            try:
                self.space_manager = SpaceManager(db_impl=None, space_backend=self.space_backend)
                logger.info("SpaceManager created eagerly (sparql_sql, db_impl pending connect)")
            except Exception as e:
                logger.error(f"❌ Failed to create SpaceManager: {e}")
                self.space_manager = None
        else:
            try:
                backend = getattr(self, 'space_backend', None) or self.db_impl
                self.space_manager = SpaceManager(db_impl=self.db_impl, space_backend=getattr(self, 'space_backend', None))
                logger.info(f"✅ Initialized SpaceManager successfully: {self.space_manager}")
            except Exception as e:
                logger.error(f"❌ Failed to create SpaceManager: {e}")
                import traceback
                logger.debug(traceback.format_exc())
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
            logger.info(f"✅ SpaceManager lazy-initialized from database with {len(self.space_manager)} spaces")
    
    async def connect_database(self):
        """Connect to database and automatically initialize SpaceManager."""
        logger.debug("VitalGraphImpl.connect_database() called")
            
        # Connect to database and space backend
        logger.debug(f"🔍 Starting database connection in VitalGraphImpl.connect_database()")
        
        # For backends with space_backend (hybrid, sparql_sql), connect it first
        if hasattr(self, 'space_backend') and self.space_backend:
            logger.debug(f"🔍 Connecting space backend: {type(self.space_backend)}")
            connected = await self.space_backend.connect()
            if not connected:
                logger.error("❌ Failed to connect to space backend")
                return False
            logger.debug(f"✅ Space backend connected successfully")
            
            # For sparql_sql backend, db_impl is created during connect()
            if self.db_impl is None and hasattr(self.space_backend, 'db_impl'):
                self.db_impl = self.space_backend.db_impl
                logger.debug(f"🔍 Picked up db_impl from space_backend: {type(self.db_impl)}")
        elif self.db_impl:
            # For non-hybrid backends, connect db_impl directly
            connected = await self.db_impl.connect()
            if not connected:
                logger.error("❌ Failed to connect to database")
                return False
            logger.debug(f"✅ Database connected successfully")
        else:
            logger.warning("⚠️ No database implementation or space backend available")
            return False
            
        try:
            logger.debug(f"🔍 Creating SignalManager in VitalGraphImpl")
            self.signal_manager = SignalManager(db_impl=self.db_impl)
            logger.debug(f"✅ SignalManager created: {self.signal_manager}")
        
            logger.debug(f"🔍 Setting SignalManager on db_impl")
            self.db_impl.set_signal_manager(self.signal_manager)
            logger.debug(f"✅ SignalManager set on db_impl")
            logger.debug(f"🔍 Verifying get_signal_manager: {self.db_impl.get_signal_manager()}")
        except Exception as e:
            logger.error(f"❌ ERROR creating/setting SignalManager: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        # Update SpaceManager's db_impl if it was created eagerly without one (sparql_sql)
        if self.space_manager is not None and self.space_manager.db_impl is None and self.db_impl:
            self.space_manager.db_impl = self.db_impl
            logger.info("Updated SpaceManager with db_impl after connect")
        elif self.space_manager is None and self.db_impl:
            try:
                self.space_manager = SpaceManager(
                    db_impl=self.db_impl,
                    space_backend=getattr(self, 'space_backend', None)
                )
                logger.info("SpaceManager created after connect (was deferred)")
            except Exception as e:
                logger.error(f"❌ Failed to create SpaceManager after connect: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return False

        if self.space_manager:
            await self.space_manager.initialize_from_database()
            logger.info(f"✅ SpaceManager initialized from database with {len(self.space_manager)} spaces")
                
        return True
    
    async def initialize_space_manager(self):
        """Initialize SpaceManager from database after database connection is established."""
        if self.space_manager and self.db_impl and self.db_impl.is_connected():
            await self.space_manager.initialize_from_database()
            logger.info(f"✅ SpaceManager initialized from database with {len(self.space_manager)} spaces")
        
        else:
            logger.warning(f"⚠️ Cannot initialize SpaceManager: db_impl connected={self.db_impl.is_connected() if self.db_impl else False}")
