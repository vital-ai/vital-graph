
import gc
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends, Form, Body, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Import VitalGraph configuration loader
from vitalgraph.config.config_loader import get_config, ConfigurationError
from vitalgraph.api.vitalgraph_api import VitalGraphAPI
from vitalgraph.auth.vitalgraph_auth import VitalGraphAuth
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.websocket.websocket_handler import ConnectionManager, websocket_endpoint
from vitalgraph.signal.notification_bridge import setup_notification_bridge
from vitalgraph.utils.event_loop_monitor import EventLoopMonitor
from vitalgraph.model.users_model import User, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse
from vitalgraph.model.spaces_model import Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse


# Space and User models now imported from their respective model files


class VitalGraphAppImpl:
    """
    VitalGraph FastAPI Application Implementation
    
    This class implements the FastAPI application for VitalGraph, providing:
    - REST API endpoints for graph operations
    - WebSocket support for real-time updates
    - Frontend serving in production mode
    """
    
    def __init__(self, app: FastAPI, config: Dict):
        """Initialize VitalGraph application with FastAPI app and configuration."""
        self.app = app
        self.config = config
        
        # Configure logging based on config file
        try:
            app_config = config.get_app_config()
            log_level = app_config.get('log_level', 'INFO')
            numeric_level = getattr(logging, log_level.upper(), logging.INFO)
            
            # Set level for root logger
            logging.getLogger().setLevel(numeric_level)
            
            # Set level for all existing loggers
            for logger_name in logging.Logger.manager.loggerDict:
                logger = logging.getLogger(logger_name)
                logger.setLevel(numeric_level)
        except (AttributeError, TypeError):
            # Fallback to INFO if config access fails
            numeric_level = logging.INFO
            logging.getLogger().setLevel(logging.INFO)
        
        self.logger = logging.getLogger(f"{__name__}.VitalGraphAppImpl")
        self.logger.setLevel(numeric_level)  # Set this logger's level explicitly
        self.app_mode = os.getenv("APP_MODE", "development").lower()
        
        # Initialize VitalGraphImpl which handles configuration and database initialization
        self.vital_graph_impl = VitalGraphImpl(config=self.config)
        # Get database implementation from VitalGraphImpl
        self.db_impl = self.vital_graph_impl.get_db_impl()
        
        # Update config reference in case it was loaded by VitalGraphImpl
        self.config = self.vital_graph_impl.get_config()
        
        # Initialize authentication
        # Get JWT secret key from environment variable (required)
        jwt_secret = os.getenv("JWT_SECRET_KEY")
        if not jwt_secret:
            raise ValueError("JWT_SECRET_KEY environment variable is required but not set")
        
        self.logger.info("✅ Using JWT secret key from environment variable")
        self.auth = VitalGraphAuth(secret_key=jwt_secret)
        
        # Initialize WebSocket connection manager
        self.websocket_manager = ConnectionManager(self.auth)
        
        # Event loop stall monitor
        self.event_loop_monitor = EventLoopMonitor(threshold_ms=100, check_interval_ms=50)
        
        # Process scheduler (initialized in startup_event after DB connection)
        self.process_scheduler = None
        
        # Get Space Manager from VitalGraphImpl
        self.space_manager = self.vital_graph_impl.get_space_manager()
        self.logger.debug(f"🔍 Retrieved space_manager from VitalGraphImpl: {self.space_manager}")
        self.logger.debug(f"🔍 space_manager type: {type(self.space_manager)}")
        
        # Initialize VitalGraph API with auth handler, database implementation, and space manager
        self.api = VitalGraphAPI(
            auth_handler=self.auth,
            db_impl=self.db_impl, 
            space_manager=self.space_manager
        )
        self.logger.debug(f"🔍 VitalGraphAPI initialized with space_manager: {self.api.space_manager}")
        
        # Add dependency for getting current user (needed before route setup)
        self.get_current_user = self.auth.create_get_current_user_dependency()
        
        # Setup middleware, static files, startup events, and routes
        self._setup_middleware()
        self._setup_static_files()
        self._setup_startup_events()
        
        # Setup endpoints with API instance (space_manager will be set later in startup event)
        self._setup_all_endpoints()

    def _setup_middleware(self):
        """Setup CORS and session middleware"""
        
        # Add request logging middleware
        @self.app.middleware("http")
        async def log_requests(request: Request, call_next):
            self.event_loop_monitor.record_request_activity()
            self.logger.debug(f"🔍 INCOMING REQUEST: {request.method} {request.url}")
            self.logger.debug(f"🔍 REQUEST HEADERS: {dict(request.headers)}")
            response = await call_next(request)
            self.event_loop_monitor.record_request_activity()
            self.logger.debug(f"🔍 RESPONSE STATUS: {response.status_code}")
            return response
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, specify exact origins
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        # Add session middleware for authentication
        self.app.add_middleware(
            SessionMiddleware,
            secret_key=os.getenv("SESSION_SECRET_KEY", "your-secret-key-here"),
            max_age=86400  # 24 hours
        )

    def _setup_static_files(self):
        """Mount React frontend build files only in production"""
        if self.app_mode == "production":
            # Mount static files from React build
            project_root = Path(__file__).parent.parent.parent
            static_dir = project_root / "vitalgraph" / "api" / "frontend" / "dist"
            
            if static_dir.exists():
                self.app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
            else:
                self.logger.warning(f"Static files directory not found at {static_dir}")

    def _setup_startup_events(self):
        """Setup FastAPI startup and shutdown events"""
        @self.app.on_event("startup")
        async def startup_event():
            """Connect to database on server startup"""
            # Re-apply log level after uvicorn has configured its own logging
            try:
                app_config = self.config.get_app_config()
                log_level = app_config.get('log_level', 'INFO')
                numeric_level = getattr(logging, log_level.upper(), logging.INFO)
                logging.getLogger().setLevel(numeric_level)
                for logger_name in logging.Logger.manager.loggerDict:
                    logging.getLogger(logger_name).setLevel(numeric_level)
                self.logger.setLevel(numeric_level)
            except (AttributeError, TypeError):
                pass
            
            if self.vital_graph_impl:
                try:
                    self.logger.debug("About to connect database via VitalGraphImpl")
                    # Use VitalGraphImpl.connect_database() which handles SignalManager creation and injection
                    success = await self.vital_graph_impl.connect_database()
                    self.logger.info(f"Connected to database successfully: {success}")
                    
                    # Refresh db_impl reference (sparql_sql backend sets it during connect)
                    self.db_impl = self.vital_graph_impl.get_db_impl()
                    
                    # Update space_manager reference after database connection
                    self.space_manager = self.vital_graph_impl.get_space_manager()
                    self.logger.debug(f"🔍 STARTUP: Updated space_manager after DB connection: {self.space_manager}")
                    
                    # Set the space_manager on VitalGraphAPI now that it's available
                    if self.space_manager is not None:
                        self.api.space_manager = self.space_manager
                        self.logger.debug(f"🔍 STARTUP: Set space_manager on VitalGraphAPI: {self.api.space_manager}")
                        self.logger.debug(f"🔍 STARTUP: API object id: {id(self.api)}")
                        self.logger.debug(f"🔍 STARTUP: Endpoints already registered during init - they will use this updated API instance")
                    else:
                        self.logger.error(f"❌ STARTUP ERROR: space_manager is still None after database connection")
                    
                    # Ensure SpaceManager is initialized from database after connection
                    self.logger.debug("Checking SpaceManager for initialization...")
                    self.logger.debug(f"self.space_manager exists: {self.space_manager is not None}")
                    self.logger.debug(f"SpaceManager class: {type(self.space_manager)}")
                    self.logger.debug(f"SpaceManager module: {type(self.space_manager).__module__}")
                    if self.space_manager is not None:
                        self.logger.debug(f"Available methods: {[m for m in dir(self.space_manager) if not m.startswith('_')]}")
                        self.logger.debug(f"has initialize_from_database: {hasattr(self.space_manager, 'initialize_from_database')}")
                    
                    if self.space_manager is not None and hasattr(self.space_manager, 'initialize_from_database'):
                        self.logger.debug("Calling initialize_from_database()...")
                        await self.space_manager.initialize_from_database()
                        self.logger.info(f"SpaceManager initialized with {len(self.space_manager)} spaces")
                        self.logger.debug(f"Available spaces: {list(self.space_manager._spaces.keys()) if hasattr(self.space_manager, '_spaces') else 'N/A'}")
                        
                        # Auto-register Fuseki datasets for all known spaces
                        space_backend = getattr(self.vital_graph_impl, 'space_backend', None)
                        fuseki_mgr = getattr(space_backend, 'fuseki_manager', None)
                        if fuseki_mgr and hasattr(self.space_manager, '_spaces'):
                            space_ids = list(self.space_manager._spaces.keys())
                            if space_ids:
                                try:
                                    stats = await fuseki_mgr.ensure_datasets_registered(space_ids)
                                    self.logger.info(f"Fuseki auto-register: {stats}")
                                except Exception as e:
                                    self.logger.warning(f"Fuseki auto-register failed: {e}")
                    else:
                        self.logger.warning("SpaceManager initialization skipped - conditions not met")
                    
                    # Initialize Entity Registry (global, uses same asyncpg pool)
                    try:
                        pool = getattr(self.db_impl, 'connection_pool', None)
                        if pool:
                            from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl
                            from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex
                            from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
                            dedup_index = EntityDedupIndex.from_env()
                            weaviate_index = await EntityWeaviateIndex.from_env()
                            signal_mgr = self.vital_graph_impl.signal_manager if self.vital_graph_impl else None
                            self.entity_registry = EntityRegistryImpl(
                                pool, dedup_index=dedup_index, signal_manager=signal_mgr,
                                weaviate_index=weaviate_index,
                            )
                            await self.entity_registry.ensure_tables()
                            self.logger.info("✅ Entity Registry tables ensured")

                            # Register callback for cross-worker dedup sync
                            if signal_mgr and dedup_index:
                                from vitalgraph.signal.signal_manager import CHANNEL_ENTITY_DEDUP
                                signal_mgr.register_callback(
                                    CHANNEL_ENTITY_DEDUP,
                                    self.entity_registry._handle_dedup_notification,
                                )
                                self.logger.info("✅ Entity dedup cross-worker sync registered")
                        else:
                            self.logger.warning("Entity Registry skipped - no connection pool available")
                            self.entity_registry = None
                    except Exception as e:
                        self.logger.warning(f"Entity Registry initialization failed: {e}")
                        self.entity_registry = None
                    
                    # Initialize Agent Registry (global, uses same asyncpg pool)
                    try:
                        pool = getattr(self.db_impl, 'connection_pool', None)
                        if pool:
                            from vitalgraph.agent_registry.agent_registry_impl import AgentRegistryImpl
                            self.agent_registry = AgentRegistryImpl(pool)
                            self.logger.info("✅ Agent Registry initialized")
                        else:
                            self.logger.warning("Agent Registry skipped - no connection pool available")
                            self.agent_registry = None
                    except Exception as e:
                        self.logger.warning(f"Agent Registry initialization failed: {e}")
                        self.agent_registry = None
                    
                    # Initialize Process Scheduler for periodic maintenance
                    try:
                        pool = getattr(self.db_impl, 'connection_pool', None)
                        if pool:
                            from vitalgraph.process.process_tracker import ProcessTracker
                            from vitalgraph.process.process_scheduler import ProcessScheduler
                            from vitalgraph.process.maintenance_job import MaintenanceJob
                            
                            # Get PostgreSQL config for lock manager connection
                            backend_type = self.config.get_backend_config().get('type', 'sparql_sql')
                            if backend_type == 'sparql_sql':
                                pg_config = self.config.get_sparql_sql_config().get('database', {})
                            else:
                                pg_config = self.config.get_fuseki_postgresql_config().get('database', {})
                            
                            tracker = ProcessTracker(pool)
                            maintenance_job = MaintenanceJob(pool, process_tracker=tracker)
                            
                            # Get maintenance config
                            maintenance_config = self.config.config_data.get('maintenance', {})
                            interval = maintenance_config.get('interval_seconds', 300)
                            enabled = maintenance_config.get('enabled', True)
                            
                            self.process_scheduler = ProcessScheduler(pool, pg_config, enabled=enabled)
                            self.process_scheduler.register_job(
                                name="db_maintenance",
                                interval_seconds=interval,
                                handler=maintenance_job,
                                process_type="maintenance",
                            )
                            await self.process_scheduler.start()
                            self.logger.info(f"✅ Process scheduler started (interval={interval}s, enabled={enabled})")
                        else:
                            self.logger.warning("Process scheduler skipped - no connection pool available")
                    except Exception as e:
                        self.logger.warning(f"Process scheduler initialization failed: {e}")
                    
                    # Start periodic space-cache refresh
                    try:
                        cache_refresh_interval = self.config.config_data.get('space_cache', {}).get('refresh_interval_seconds', 60)
                        await self.space_manager.start_periodic_refresh(interval_seconds=cache_refresh_interval)
                        self.logger.info(f"✅ Space cache periodic refresh started (interval={cache_refresh_interval}s)")
                    except Exception as e:
                        self.logger.warning(f"Space cache periodic refresh failed to start: {e}")

                    # Endpoints are already initialized in __init__
                    # SpaceManager is now fully initialized and connected
                    self.logger.info("SpaceManager ready for endpoint operations")
                    
                    # Set up notification bridge between PostgreSQL and WebSocket
                    if self.websocket_manager is not None:
                        try:
                            # Debug prints to investigate references
                            self.logger.debug(f"VitalGraphAppImpl db_impl id: {id(self.db_impl)}")
                            self.logger.debug(f"VitalGraphImpl db_impl id: {id(self.vital_graph_impl.db_impl)}")
                            
                            # Try to access signal_manager from VitalGraphImpl directly
                            signal_manager = self.vital_graph_impl.signal_manager
                            self.logger.debug(f"Using VitalGraphImpl signal_manager: {signal_manager}")
                            
                            if signal_manager is None:
                                # Fallback to db_impl.get_signal_manager() if direct access fails
                                signal_manager = self.db_impl.get_signal_manager()
                                self.logger.debug(f"Using db_impl.get_signal_manager(): {signal_manager}")
                                
                            self.logger.debug("Setting up notification bridge between PostgreSQL and WebSocket...")
                            bridge = await setup_notification_bridge(signal_manager, self.websocket_manager)
                            if bridge:
                                self.logger.info("PostgreSQL notification bridge initialized successfully")
                            else:
                                self.logger.warning("Failed to initialize notification bridge")
                        except Exception as e:
                            self.logger.warning(f"Error setting up notification bridge: {e}")
                    else:
                        self.logger.warning("WebSocket manager not available, notification bridge skipped")
                    
                    # Register SpaceManager signal callback for cross-instance sync
                    try:
                        signal_manager = self.vital_graph_impl.signal_manager
                        if signal_manager is None:
                            signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                        if signal_manager and self.space_manager and hasattr(self.space_manager, '_handle_space_signal'):
                            from vitalgraph.signal.signal_manager import CHANNEL_SPACE
                            signal_manager.register_callback(
                                CHANNEL_SPACE,
                                self.space_manager._handle_space_signal,
                            )
                            self.logger.info("✅ SpaceManager cross-instance sync registered on CHANNEL_SPACE")
                        else:
                            self.logger.warning("SpaceManager signal sync skipped — signal_manager or space_manager not available")
                    except Exception as e:
                        self.logger.warning(f"SpaceManager signal registration failed (non-critical): {e}")
                    
                    # Register cache invalidation callback for cross-instance datatype/stats sync
                    try:
                        signal_manager = self.vital_graph_impl.signal_manager
                        if signal_manager is None:
                            signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                        if signal_manager:
                            from vitalgraph.signal.signal_manager import CHANNEL_CACHE_INVALIDATE
                            from vitalgraph.db.sparql_sql.generator import invalidate_datatype_cache, invalidate_stats_cache

                            async def _handle_cache_invalidate(data: dict):
                                cache_type = data.get("cache_type", "")
                                space_id = data.get("space_id", "")
                                if cache_type == "datatype" and space_id:
                                    invalidate_datatype_cache(space_id)
                                    self.logger.debug(f"Cache invalidation: cleared datatype cache for {space_id}")
                                elif cache_type == "stats" and space_id:
                                    invalidate_stats_cache(space_id)
                                    self.logger.debug(f"Cache invalidation: cleared stats cache for {space_id}")

                            signal_manager.register_callback(
                                CHANNEL_CACHE_INVALIDATE,
                                _handle_cache_invalidate,
                            )
                            self.logger.info("✅ Cache invalidation cross-instance sync registered on CHANNEL_CACHE_INVALIDATE")
                        else:
                            self.logger.warning("Cache invalidation signal sync skipped — signal_manager not available")
                    except Exception as e:
                        self.logger.warning(f"Cache invalidation signal registration failed (non-critical): {e}")

                    # Start the NOTIFY listener so cross-instance signals are received
                    try:
                        signal_manager = self.vital_graph_impl.signal_manager
                        if signal_manager is None:
                            signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                        if signal_manager:
                            await signal_manager.start_listening()
                            self.logger.info("✅ SignalManager NOTIFY listener started")
                        else:
                            self.logger.warning("SignalManager not available — NOTIFY listener not started")
                    except Exception as e:
                        self.logger.warning(f"SignalManager listener start failed (non-critical): {e}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to connect to database: {e}")
            
            # Freeze all current gen-2 objects so GC never scans them again.
            # This dramatically reduces gen-2 pause duration by excluding the
            # large set of long-lived startup objects (ORM metadata, caches, etc.)
            gc.collect()  # collect garbage first
            frozen_count = len(gc.get_objects(2))
            gc.freeze()
            self.logger.info(f"🧊 gc.freeze(): {frozen_count:,} gen-2 objects frozen — excluded from future GC scans")

            # Start event loop stall monitor
            try:
                await self.event_loop_monitor.start()
            except Exception as e:
                self.logger.warning(f"Failed to start event loop monitor: {e}")
        
        @self.app.on_event("shutdown")
        async def shutdown_event():
            """Clean up resources on server shutdown"""
            self.logger.info("🛑 Shutting down VitalGraph server...")
            
            try:
                # Stop periodic space-cache refresh
                if self.space_manager:
                    try:
                        await self.space_manager.stop_periodic_refresh()
                        self.logger.info("✅ Space cache periodic refresh stopped")
                    except Exception as e:
                        self.logger.warning(f"Error stopping space cache refresh: {e}")

                # Stop process scheduler
                if self.process_scheduler:
                    try:
                        await self.process_scheduler.stop()
                        self.logger.info("✅ Process scheduler stopped")
                    except Exception as e:
                        self.logger.warning(f"Error stopping process scheduler: {e}")
                
                # Stop event loop monitor
                try:
                    await self.event_loop_monitor.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping event loop monitor: {e}")
                
                # Close signal manager (stops listen loops and closes connections)
                if self.vital_graph_impl and self.vital_graph_impl.signal_manager:
                    self.logger.info("Closing signal manager...")
                    try:
                        await self.vital_graph_impl.signal_manager.stop_listening()
                        self.logger.info("✅ Signal manager closed")
                    except Exception as e:
                        self.logger.warning(f"Error closing signal manager: {e}")
                
                # Close database connections
                if self.vital_graph_impl and self.vital_graph_impl.db_impl:
                    self.logger.info("Closing database connections...")
                    try:
                        await self.vital_graph_impl.db_impl.disconnect()
                        self.logger.info("✅ Database connections closed")
                    except Exception as e:
                        self.logger.warning(f"Error closing database: {e}")
                
                # Clean up any tracked resources (aiohttp sessions, etc.)
                try:
                    from vitalgraph.utils.resource_manager import cleanup_resources
                    self.logger.info("Cleaning up tracked resources...")
                    await cleanup_resources()
                    self.logger.info("✅ Resources cleaned up")
                except Exception as e:
                    self.logger.warning(f"Error cleaning up resources: {e}")
                
                self.logger.info("✅ VitalGraph server shutdown complete")
                
            except Exception as e:
                self.logger.error(f"Error during shutdown: {e}")
    
    def _setup_all_endpoints(self):
        """Setup all API endpoints in a single atomic operation."""
        self.logger.info("Setting up all endpoints...")
        
        # Guard against duplicate initialization
        if hasattr(self, '_all_endpoints_initialized'):
            self.logger.info("Endpoints already initialized, skipping...")
            return
        self._all_endpoints_initialized = True
        
        # Initialize all endpoint groups in order (most specific routes first)
        self.logger.info("Initializing auth routes...")
        self._init_auth_routes()
        self.logger.info("Initializing space routes...")
        self._init_space_routes()
        self.logger.info("Initializing user routes...")
        self._init_user_routes()
        self.logger.info("Initializing websocket routes...")
        self._init_websocket_routes()
        self.logger.info("Initializing SPARQL routers...")
        self._init_sparql_routers()
        self.logger.info("Initializing graph data routers...")
        self._init_graph_data_routers()
        self.logger.info("Initializing data routers...")
        self._init_data_routers()
        self.logger.info("Initializing entity registry routes...")
        self._init_entity_registry_routes()
        self.logger.info("Initializing agent registry routes...")
        self._init_agent_registry_routes()
        self.logger.info("Initializing process routes...")
        self._init_process_routes()
        self.logger.info("Initializing admin routes...")
        self._init_admin_routes()
        self.logger.info("Initializing frontend routes...")
        self._init_frontend_routes()
        self.logger.info("All endpoints initialized successfully!")
    
    def _init_sparql_routers(self):
        """Initialize SPARQL endpoint routers."""
        # Set logger to DEBUG level for this function
        import logging
        self.logger.setLevel(logging.DEBUG)
        
        # Import SPARQL endpoint routers
        from vitalgraph.endpoint.sparql_query_endpoint import create_sparql_query_router
        from vitalgraph.endpoint.sparql_update_endpoint import create_sparql_update_router
        from vitalgraph.endpoint.sparql_insert_endpoint import create_sparql_insert_router
        from vitalgraph.endpoint.sparql_delete_endpoint import create_sparql_delete_router
        from vitalgraph.endpoint.sparql_graph_endpoint import create_sparql_graph_router
        
        # Create routers with space manager and auth dependency
        self.logger.info("Creating SPARQL routers...")
        query_router = create_sparql_query_router(self.space_manager, self.get_current_user)
        update_router = create_sparql_update_router(self.space_manager, self.get_current_user)
        insert_router = create_sparql_insert_router(self.space_manager, self.get_current_user)
        delete_router = create_sparql_delete_router(self.space_manager, self.get_current_user)
        graph_router = create_sparql_graph_router(self.space_manager, self.get_current_user)
        
        # Include routers in the FastAPI app
        self.logger.info("Including SPARQL routers in FastAPI app...")
        self.app.include_router(query_router, prefix="/api/graphs/sparql", tags=["SPARQL"])
        self.app.include_router(update_router, prefix="/api/graphs/sparql", tags=["SPARQL"])
        self.app.include_router(insert_router, prefix="/api/graphs/sparql", tags=["SPARQL"])
        self.app.include_router(delete_router, prefix="/api/graphs/sparql")
        self.app.include_router(graph_router, prefix="/api/graphs")
        self.logger.info(f"Included graph router with prefix '/api/graphs' - {len(graph_router.routes)} routes")
    
    def _init_graph_data_routers(self):
        """Initialize graph data endpoint routers."""
        # Import graph data endpoint routers
        from vitalgraph.endpoint.triples_endpoint import create_triples_router
        from vitalgraph.endpoint.kgtypes_endpoint import create_kgtypes_router
        from vitalgraph.endpoint.objects_endpoint import create_objects_router
        from vitalgraph.endpoint.kgentities_endpoint import create_kgentities_router
        from vitalgraph.endpoint.kgframes_endpoint import create_kgframes_router
        from vitalgraph.endpoint.kgrelations_endpoint import create_kgrelations_router
        from vitalgraph.endpoint.kgquery_endpoint import create_kgqueries_router
        from vitalgraph.endpoint.files_endpoint import create_files_router
        
        # Create routers with space manager and auth dependency
        triples_router = create_triples_router(self.space_manager, self.get_current_user)
        kgtypes_router = create_kgtypes_router(self.space_manager, self.get_current_user)
        objects_router = create_objects_router(self.space_manager, self.get_current_user)
        kgentities_router = create_kgentities_router(self.space_manager, self.get_current_user)
        kgframes_router = create_kgframes_router(self.space_manager, self.get_current_user)
        kgrelations_router = create_kgrelations_router(self.space_manager, self.get_current_user)
        kgqueries_router = create_kgqueries_router(self.space_manager, self.get_current_user)
        files_router = create_files_router(self.space_manager, self.get_current_user, config=self.config)
        
        # Include routers in the FastAPI app  
        self.app.include_router(triples_router, prefix="/api/graphs")
        self.app.include_router(kgtypes_router, prefix="/api/graphs")
        self.app.include_router(objects_router, prefix="/api/graphs")
        self.app.include_router(kgentities_router, prefix="/api/graphs")
        self.app.include_router(kgframes_router, prefix="/api/graphs")
        self.app.include_router(kgrelations_router, prefix="/api/graphs")
        self.app.include_router(kgqueries_router, prefix="/api/graphs")
        self.app.include_router(files_router, prefix="/api")
    
    def _init_data_routers(self):
        """Initialize data import/export endpoint routers."""
        # Import data endpoint routers
        from vitalgraph.endpoint.import_endpoint import create_import_router
        from vitalgraph.endpoint.export_endpoint import create_export_router
        
        # Create routers with space manager and auth dependency
        import_router = create_import_router(self.space_manager, self.get_current_user)
        export_router = create_export_router(self.space_manager, self.get_current_user)
        
        # Include routers in the FastAPI app
        self.app.include_router(import_router, prefix="/api/data", tags=["Data"])
        self.app.include_router(export_router, prefix="/api/data", tags=["Data"])
    
    def _init_auth_routes(self):
        """Initialize authentication routes."""
        # Authentication wrapper functions
        async def logout_wrapper(request: Request, current_user: Dict = Depends(self.get_current_user)):
            return await self.logout(request, current_user)
        
        async def refresh_token_wrapper(refresh_token: str = Body(..., embed=True), current_user: Dict = Depends(self.get_current_user)):
            return await self.refresh_token(refresh_token)

        # Health check endpoint (no authentication required)
        self.app.get(
            "/health",
            tags=["Health"],
            summary="Health Check",
            description="Check if the service is running"
        )(self.health)
        
        # Authentication routes
        self.app.post(
            "/api/login",
            tags=["Authentication"],
            summary="User Login",
            description="Authenticate user and generate access token for API access"
        )(self.login)
        self.app.post(
            "/api/logout",
            tags=["Authentication"],
            summary="User Logout",
            description="Invalidate current session and log out user"
        )(logout_wrapper)
        self.app.post(
            "/api/refresh",
            tags=["Authentication"],
            summary="Refresh Token",
            description="Refresh access token using refresh token (requires refresh token as Bearer token)"
        )(refresh_token_wrapper)
    
    def _init_space_routes(self):
        """Initialize space management routes."""
        from vitalgraph.endpoint.spaces_endpoint import create_spaces_router
        
        # Create and include spaces router
        spaces_router = create_spaces_router(self.api, self.get_current_user)
        self.app.include_router(spaces_router, prefix="/api")
    
    def _init_user_routes(self):
        """Initialize user management routes."""
        from vitalgraph.endpoint.users_endpoint import create_users_router
        
        # Create and include users router
        users_router = create_users_router(self.api, self.get_current_user)
        self.app.include_router(users_router, prefix="/api")
    
    def _init_websocket_routes(self):
        """Initialize WebSocket routes."""
        async def websocket_wrapper(websocket: WebSocket):
            await websocket_endpoint(websocket, self.websocket_manager)

        self.app.websocket("/api/ws")(websocket_wrapper)
    
    def _init_entity_registry_routes(self):
        """Initialize Entity Registry endpoint routes."""
        from vitalgraph.endpoint.entity_registry_endpoint import create_entity_registry_router
        
        entity_registry_router = create_entity_registry_router(self, self.get_current_user)
        self.app.include_router(entity_registry_router, prefix="/api/registry")
    
    def _init_agent_registry_routes(self):
        """Initialize Agent Registry endpoint routes."""
        from vitalgraph.agent_registry.agent_endpoint import create_agent_registry_router
        
        agent_registry_router = create_agent_registry_router(self, self.get_current_user)
        self.app.include_router(agent_registry_router, prefix="/api/agents")
    
    def _init_process_routes(self):
        """Initialize Process tracking endpoint routes."""
        from vitalgraph.endpoint.process_endpoint import create_process_router
        
        process_router = create_process_router(self, self.get_current_user)
        self.app.include_router(process_router, prefix="/api", tags=["Processes"])
    
    def _init_admin_routes(self):
        """Initialize admin endpoint routes (resync, etc.)."""
        from vitalgraph.endpoint.admin_endpoint import create_admin_router
        
        admin_router = create_admin_router(self.space_manager, self.get_current_user)
        self.app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
    
    def _init_frontend_routes(self):
        """Initialize frontend serving routes."""
        # Frontend serving routes
        if self.app_mode == "production":
            self.app.get("/", response_class=HTMLResponse)(self.serve_frontend)
            self.app.get("/{path:path}")(self.catch_all)
        else:
            self.app.get("/")(self.api_root)
    

    async def login(self, form_data: OAuth2PasswordRequestForm = Depends(), token_expiry_seconds: Optional[int] = Form(None)):
        """Login endpoint - delegates to API class"""
        return await self.api.login(form_data, token_expiry_seconds)

    async def logout(self, request: Request, current_user: Dict):
        """Logout endpoint - delegates to API class"""
        return await self.api.logout(request, current_user)

    async def refresh_token(self, refresh_token: str = Body(..., embed=True)):
        """Refresh token endpoint - delegates to API class"""
        return await self.api.refresh_token(refresh_token)

    async def list_spaces(self, current_user: Dict):
        """Get list of spaces for the authenticated user"""
        return await self.api.list_spaces(current_user)

    async def sparql_endpoint(
        self,
        query: str,
        current_user: Dict
    ):
        """Execute a SPARQL query"""
        return await self.api.execute_sparql_query(query, current_user)

    async def health(self):
        """Health check endpoint - delegates to API class"""
        return await self.api.health()
    
    async def serve_frontend(self):
        """Serve the built React app's index.html"""
        project_root = Path(__file__).parent.parent.parent
        index_path = project_root / "vitalgraph" / "api" / "frontend" / "dist" / "index.html"
        if index_path.exists():
            with open(index_path) as f:
                return HTMLResponse(content=f.read())
        # Fallback to API docs if index.html doesn't exist
        return RedirectResponse(url="/docs")
    
    async def api_root(self):
        """Development mode root endpoint"""
        return {
            "message": "VitalGraph API Server",
            "documentation": "/docs",
            "alternative_docs": "/redoc"
        }
    
    async def catch_all(self, path: str):
        """Catch-all route for client-side routing - only in production"""
        project_root = Path(__file__).parent.parent.parent
        
        # First, try to serve static files from the dist directory (SVGs, favicon, etc.)
        static_file_path = project_root / "vitalgraph" / "api" / "frontend" / "dist" / path
        if static_file_path.exists() and static_file_path.is_file():
            return FileResponse(static_file_path)
        
        # Only catch routes that don't start with /api or /static for SPA routing
        if path.startswith("api/") or path.startswith("static/") or path.startswith("docs") or path == "openapi.json":
            raise HTTPException(status_code=404, detail="Not found")
        
        # Return the index.html for client-side routing
        index_path = project_root / "vitalgraph" / "api" / "frontend" / "dist" / "index.html"
        if index_path.exists():
            with open(index_path) as f:
                return HTMLResponse(content=f.read())
        return RedirectResponse(url="/docs")
