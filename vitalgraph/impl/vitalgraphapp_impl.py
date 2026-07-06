
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
from vitalgraph.metrics.metrics_middleware import MetricsMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Import VitalGraph configuration loader
from vitalgraph.config.config_loader import get_config, ConfigurationError, VitalGraphConfig
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
    
    def __init__(self, app: FastAPI, config: VitalGraphConfig):
        """Initialize VitalGraph application with FastAPI app and configuration."""
        self.app = app
        self.config: VitalGraphConfig = config
        self.entity_registry: Any = None
        self.agent_registry: Any = None
        self._backfill_task: Any = None
        
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
        self.config = self.vital_graph_impl.get_config() or config
        
        # Initialize authentication
        # Get JWT secret key from environment variable (required)
        jwt_secret = os.getenv("JWT_SECRET_KEY")
        if not jwt_secret:
            raise ValueError("JWT_SECRET_KEY environment variable is required but not set")
        
        self.logger.info("✅ Using JWT secret key from environment variable")
        auth_config = self.config.get_auth_config() if self.config else {}
        token_cache_ttl = auth_config.get("token_version_cache_ttl_seconds", 60)
        self.auth = VitalGraphAuth(
            secret_key=jwt_secret, db_impl=self.db_impl,
            token_version_cache_ttl=token_cache_ttl,
        )
        
        # Configure bootstrap admin from config/env (only if credentials are explicitly set)
        bootstrap_user = auth_config.get("root_username", os.getenv("AUTH_ROOT_USERNAME", ""))
        bootstrap_pass = auth_config.get("root_password", os.getenv("AUTH_ROOT_PASSWORD", ""))
        if bootstrap_user and bootstrap_pass:
            self.auth.set_bootstrap_admin(bootstrap_user, bootstrap_pass)
        
        # Initialize WebSocket connection manager
        self.websocket_manager = ConnectionManager(self.auth)
        
        # Event loop stall monitor
        self.event_loop_monitor = EventLoopMonitor(threshold_ms=100, check_interval_ms=50)
        
        # Process scheduler (initialized in startup_event after DB connection)
        self.process_scheduler: Optional[Any] = None
        
        # Segmentation background worker
        self._segmentation_worker: Optional[Any] = None
        self._segmentation_worker_task: Optional[Any] = None
        
        # Import/export job manager (created in startup_event after pool is available)
        self.import_export_manager = None
        
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
        
        # Add audit context middleware (captures IP/UA for audit events)
        @self.app.middleware("http")
        async def audit_context_middleware(request: Request, call_next):
            from vitalgraph.auth.request_context import set_request_context
            ip = request.client.host if request.client else None
            ua = request.headers.get("user-agent")
            set_request_context(ip, ua)
            return await call_next(request)

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
        # Add query metrics middleware (reads collector from app.state during requests)
        self.app.add_middleware(MetricsMiddleware)
        
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

    async def _auto_init_tables(self):
        """Auto-initialize admin tables if they don't exist.

        Triggered by VG_AUTO_INIT=true — intended for test environments only.
        Mirrors the ``vitalgraphadmin init`` CLI command.
        """
        backend_type = self.config.get_backend_config().get('type', 'sparql_sql')
        self.logger.info(f"VG_AUTO_INIT: initializing {backend_type} admin tables...")

        try:
            if backend_type == 'sparql_sql':
                from vitalgraph.db.sparql_sql.sparql_sql_admin import SparqlSQLAdmin
                admin = SparqlSQLAdmin()
            elif backend_type == 'fuseki_postgresql':
                from vitalgraph.db.fuseki_postgresql.fuseki_admin import FusekiPostgreSQLAdmin
                admin = FusekiPostgreSQLAdmin()
            else:
                self.logger.warning(f"VG_AUTO_INIT: unsupported backend type '{backend_type}', skipping")
                return

            await admin.init_tables(self.db_impl)
            self.logger.info("VG_AUTO_INIT: admin tables initialized successfully")

            # Auth migration tables (api_key, audit_log)
            await self._auto_init_auth_tables()
            # Entity registry tables
            await self._auto_init_entity_registry()

            # Ensure the bootstrap admin user exists in the DB so JWT
            # token-version validation succeeds after login.
            admin_user = os.getenv('AUTH_ROOT_USERNAME', 'admin')
            admin_pass = os.getenv('AUTH_ROOT_PASSWORD', 'admin')
            existing = await self.db_impl.get_user_by_username(admin_user)
            if existing is None:
                from vitalgraph.auth.password import hash_password
                await self.db_impl.create_user(
                    username=admin_user,
                    password_hash=hash_password(admin_pass),
                    email=f"{admin_user}@localhost",
                    full_name="Bootstrap Admin",
                    role="admin",
                )
                self.logger.info(f"VG_AUTO_INIT: created admin user '{admin_user}' in database")
            else:
                self.logger.info(f"VG_AUTO_INIT: admin user '{admin_user}' already exists")
        except Exception as e:
            self.logger.error(f"VG_AUTO_INIT: failed to initialize tables: {e}")
            raise

    async def _auto_init_entity_registry(self):
        """Create entity registry tables if they don't exist."""
        try:
            from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
            schema = EntityRegistrySchema()
            pool = self.db_impl.connection_pool
            for sql in schema.create_tables_sql():
                await pool.execute(sql)
            for sql in schema.create_indexes_sql():
                await pool.execute(sql)
            for sql in schema.create_views_sql():
                await pool.execute(sql)
            await pool.execute(schema.seed_entity_types_sql())
            await pool.execute(schema.seed_entity_categories_sql())
            await pool.execute(schema.seed_location_types_sql())
            await pool.execute(schema.seed_relationship_types_sql())
            for sql in schema.migrations_sql():
                await pool.execute(sql)
            self.logger.info("VG_AUTO_INIT: entity registry tables initialized")
        except Exception as e:
            self.logger.error(f"VG_AUTO_INIT: entity registry init failed: {e}")
            raise

    async def _auto_init_auth_tables(self):
        """Create api_key and audit_log tables if they don't exist."""
        try:
            from vitalgraph.db.migrations.migrate_auth_schema import migrate_auth_schema
            pool = self.db_impl.connection_pool
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await migrate_auth_schema(conn)
            self.logger.info("VG_AUTO_INIT: auth tables (api_key, audit_log) initialized")
        except Exception as e:
            self.logger.error(f"VG_AUTO_INIT: auth tables init failed: {e}")
            raise

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
                    self.auth.set_db_impl(self.db_impl)
                    self.api.db = self.db_impl
                    
                    # Auto-init admin tables if VG_AUTO_INIT=true (test environments only)
                    if os.getenv('VG_AUTO_INIT', '').lower() == 'true':
                        await self._auto_init_tables()
                    
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

                    # Set signal_manager on VitalGraphAPI for endpoint-level NOTIFY
                    sm = self.vital_graph_impl.signal_manager
                    if sm is None:
                        sm = self.db_impl.get_signal_manager() if self.db_impl else None
                    if sm:
                        self.api.signal_manager = sm
                    
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
                            from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex
                            from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
                            from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
                            from vitalgraph.config.config_loader import get_scoped_env

                            fuzzy_backend = get_scoped_env('ENTITY_FUZZY_BACKEND', 'memory').lower()
                            if fuzzy_backend == 'postgresql':
                                fuzzy_index = EntityFuzzyIndexPG.from_env(pool)
                            else:
                                fuzzy_index = EntityFuzzyIndex.from_env()
                            self.logger.info("Initializing Weaviate index (profile=%s)...",
                                             os.getenv('VITALGRAPH_ENVIRONMENT', 'local').upper())
                            weaviate_index = await EntityWeaviateIndex.from_env()
                            signal_mgr = self.vital_graph_impl.signal_manager if self.vital_graph_impl else None
                            self.entity_registry = EntityRegistryImpl(
                                pool, fuzzy_index=fuzzy_index, signal_manager=signal_mgr,
                                weaviate_index=weaviate_index,
                            )
                            await self.entity_registry.ensure_tables()
                            self.logger.info("✅ Entity Registry tables ensured")

                            # Register callback for cross-worker fuzzy sync
                            if signal_mgr and fuzzy_index:
                                from vitalgraph.signal.signal_manager import CHANNEL_ENTITY_FUZZY
                                signal_mgr.register_callback(
                                    CHANNEL_ENTITY_FUZZY,
                                    self.entity_registry._handle_fuzzy_notification,
                                )
                                self.logger.info("✅ Entity fuzzy cross-worker sync registered")
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
                            # Attach vector/FTS populator if vectorization is available
                            try:
                                from vitalgraph.agent_registry.agent_registry_vector_populator import AgentRegistryVectorPopulator
                                populator = AgentRegistryVectorPopulator(pool)
                                self.agent_registry.set_vector_populator(populator)
                                self.logger.info("✅ Agent Registry Vector Populator attached")
                            except Exception as vec_err:
                                self.logger.info(f"Agent Registry Vector Populator not available: {vec_err}")
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
                            from vitalgraph.process.analytics_job import AnalyticsJob
                            from vitalgraph.process.metrics_rollup_job import MetricsRollupJob
                            
                            # Get PostgreSQL config for lock manager connection
                            backend_type = self.config.get_backend_config().get('type', 'sparql_sql')
                            if backend_type == 'sparql_sql':
                                pg_config = self.config.get_sparql_sql_config().get('database', {})
                            else:
                                pg_config = self.config.get_fuseki_postgresql_config().get('database', {})
                            
                            tracker = ProcessTracker(pool)
                            maintenance_job = MaintenanceJob(pool, process_tracker=tracker, postgresql_config=pg_config)
                            
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
                            
                            # Register analytics job (default: once per day)
                            analytics_config = self.config.config_data.get('analytics', {})
                            analytics_interval = analytics_config.get('interval_seconds', 86400)
                            analytics_job = AnalyticsJob(pool)
                            self.process_scheduler.register_job(
                                name="space_analytics",
                                interval_seconds=analytics_interval,
                                handler=analytics_job,
                                process_type="analytics",
                            )
                            
                            # Initialize PostgreSQL-based metrics collector and rollup job
                            try:
                                from vitalgraph.metrics.postgres_metrics_collector import PostgresMetricsCollector
                                metrics_collector = PostgresMetricsCollector(pool)
                                await metrics_collector.start()
                                # Store on app.state for middleware access
                                self.app.state.metrics_collector = metrics_collector
                                # Store on API for endpoint access
                                self.api._metrics_collector = metrics_collector
                                # Register rollup job (hourly) — aggregates minute→hour, purges old data
                                metrics_rollup = MetricsRollupJob(pool)
                                self.process_scheduler.register_job(
                                    name="metrics_rollup",
                                    interval_seconds=3600,
                                    handler=metrics_rollup,
                                    process_type="metrics",
                                )
                                self.logger.info("✅ Query metrics collector initialized (PostgreSQL-backed)")
                            except Exception as e:
                                self.logger.warning(f"Query metrics initialization failed (non-critical): {e}")

                            # Register import/export cleanup job
                            try:
                                from vitalgraph.process.import_export_cleanup_job import ImportExportCleanupJob
                                ie_config = self.config.get_import_export_config()
                                ie_retention = ie_config.get('job_retention_days', 30)
                                ie_interval = ie_config.get('cleanup_interval_seconds', 86400)
                                cleanup_job = ImportExportCleanupJob(
                                    pool,
                                    retention_days=ie_retention,
                                    staging_bucket=ie_config.get('staging_bucket', 'vitalgraph-staging'),
                                )
                                self.process_scheduler.register_job(
                                    name="import_export_cleanup",
                                    interval_seconds=ie_interval,
                                    handler=cleanup_job,
                                    process_type="maintenance",
                                )
                                self.logger.info(f"✅ Import/export cleanup job registered (retention={ie_retention}d, interval={ie_interval}s)")
                            except Exception as e:
                                self.logger.warning(f"Import/export cleanup job registration failed (non-critical): {e}")

                            await self.process_scheduler.start()
                            self.logger.info(f"✅ Process scheduler started (maintenance={interval}s, analytics={analytics_interval}s, enabled={enabled})")
                        else:
                            self.logger.warning("Process scheduler skipped - no connection pool available")
                    except Exception as e:
                        self.logger.warning(f"Process scheduler initialization failed: {e}")
                    
                    # Start periodic space-cache refresh
                    try:
                        cache_refresh_interval = self.config.config_data.get('space_cache', {}).get('refresh_interval_seconds', 60)
                        if self.space_manager:
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
                                signal_manager = getattr(self.db_impl, 'get_signal_manager', lambda: None)()
                                self.logger.debug(f"Using db_impl.get_signal_manager(): {signal_manager}")
                                
                            self.logger.debug("Setting up notification bridge between PostgreSQL and WebSocket...")
                            if signal_manager is None:
                                raise RuntimeError("No signal manager available")
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

                    # Register token version cache invalidation for cross-instance auth sync
                    try:
                        signal_manager = self.vital_graph_impl.signal_manager
                        if signal_manager is None:
                            signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                        if signal_manager:
                            from vitalgraph.signal.signal_manager import CHANNEL_TOKEN_VERSION

                            async def _handle_token_version_signal(data: dict):
                                username = data.get("username", "")
                                if username:
                                    self.auth.invalidate_token_cache(username)
                                    self.logger.debug(f"Token version cache invalidated for '{username}' via NOTIFY")

                            signal_manager.register_callback(
                                CHANNEL_TOKEN_VERSION,
                                _handle_token_version_signal,
                            )
                            self.logger.info("✅ Token version cache cross-instance sync registered on CHANNEL_TOKEN_VERSION")
                        else:
                            self.logger.warning("Token version cache signal sync skipped — signal_manager not available")
                    except Exception as e:
                        self.logger.warning(f"Token version cache signal registration failed (non-critical): {e}")

                    # Register entity graph cache invalidation for cross-instance sync
                    try:
                        signal_manager = self.vital_graph_impl.signal_manager
                        if signal_manager is None:
                            signal_manager = self.db_impl.get_signal_manager() if self.db_impl else None
                        if signal_manager:
                            from vitalgraph.signal.signal_manager import CHANNEL_ENTITY_GRAPH, CHANNEL_GRAPH, CHANNEL_SPACE
                            from vitalgraph.cache.entity_graph_cache import _entity_graph_cache
                            from vitalgraph.cache.count_cache import _count_cache

                            async def _handle_entity_graph_signal(data: dict):
                                space_id = data.get("space_id", "")
                                graph_id = data.get("graph_id", "")
                                entity_uri = data.get("entity_uri", "")
                                if space_id and graph_id and entity_uri:
                                    _entity_graph_cache.invalidate(space_id, graph_id, entity_uri)
                                    _count_cache.invalidate_graph(space_id, graph_id)
                                    self.logger.info(f"📡 Entity+count cache NOTIFY received — invalidated {entity_uri}")
                                elif space_id and graph_id:
                                    _entity_graph_cache.invalidate_graph(space_id, graph_id)
                                    _count_cache.invalidate_graph(space_id, graph_id)
                                    self.logger.info(f"📡 Entity+count cache NOTIFY received — invalidated graph {graph_id}")

                            async def _handle_graph_entity_cache(data: dict):
                                signal_type = data.get("type", "")
                                graph_uri = data.get("graph_uri", "")
                                space_id = data.get("space_id", "")
                                if signal_type in ("deleted", "updated") and space_id and graph_uri:
                                    _entity_graph_cache.invalidate_graph(space_id, graph_uri)
                                    _count_cache.invalidate_graph(space_id, graph_uri)

                            async def _handle_space_entity_cache(data: dict):
                                signal_type = data.get("type", "")
                                space_id = data.get("space_id", "")
                                if signal_type == "deleted" and space_id:
                                    _entity_graph_cache.invalidate_space(space_id)
                                    _count_cache.invalidate_space(space_id)

                            signal_manager.register_callback(CHANNEL_ENTITY_GRAPH, _handle_entity_graph_signal)
                            signal_manager.register_callback(CHANNEL_GRAPH, _handle_graph_entity_cache)
                            signal_manager.register_callback(CHANNEL_SPACE, _handle_space_entity_cache)
                            self.logger.info("✅ Entity graph + count cache cross-instance sync registered on CHANNEL_ENTITY_GRAPH/GRAPH/SPACE")
                        else:
                            self.logger.warning("Entity graph cache signal sync skipped — signal_manager not available")
                    except Exception as e:
                        self.logger.warning(f"Entity graph cache signal registration failed (non-critical): {e}")

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

                    # Configure audit logging with DB pool
                    try:
                        pool = getattr(self.db_impl, 'connection_pool', None)
                        if pool:
                            from vitalgraph.auth.audit import configure_audit
                            audit_enabled = True
                            if self.config:
                                audit_cfg = self.config.get_auth_config().get('audit', {})
                                audit_enabled = audit_cfg.get('enabled', True)
                            configure_audit(db_pool=pool, enabled=audit_enabled)
                            self.logger.info("✅ Audit logging configured (db_pool=%s, enabled=%s)",
                                             pool is not None, audit_enabled)
                    except Exception as e:
                        self.logger.warning(f"Audit configuration failed (non-critical): {e}")

                    # Create the ImportExportJobManager now that the pool exists
                    try:
                        self._init_import_export_manager()
                    except Exception as e:
                        self.logger.warning(f"ImportExportJobManager init failed (non-critical): {e}")

                    # Start segmentation background worker
                    try:
                        if self.space_manager:
                            import asyncio as _asyncio
                            from vitalgraph.document.segmentation_worker import SegmentationWorker
                            self._segmentation_worker = SegmentationWorker(self.space_manager)
                            self._segmentation_worker_task = _asyncio.create_task(
                                self._segmentation_worker.run()
                            )
                            self.logger.info("✅ Segmentation background worker started")
                        else:
                            self.logger.warning("Segmentation worker skipped — no space_manager")
                    except Exception as e:
                        self.logger.warning(f"Segmentation worker initialization failed (non-critical): {e}")

                    # Start incremental backfill of server-managed entity properties
                    try:
                        pool = getattr(self.db_impl, 'connection_pool', None)
                        if pool and self.space_manager:
                            from vitalgraph.tasks.backfill_server_properties_task import (
                                BackfillServerPropertiesTask, set_backfill_task,
                            )
                            self._backfill_task = BackfillServerPropertiesTask(pool, self.space_manager)
                            self._backfill_task.start()
                            set_backfill_task(self._backfill_task)
                            self.logger.info("✅ Server-properties backfill task started")
                            # Wire backfill nudge into import/export manager
                            if hasattr(self, 'import_export_manager') and self.import_export_manager:
                                self.import_export_manager._backfill_task = self._backfill_task
                        else:
                            self.logger.warning("Backfill task skipped — no connection pool or space_manager")
                    except Exception as e:
                        self.logger.warning(f"Backfill task initialization failed (non-critical): {e}")

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

                # Stop segmentation worker
                if self._segmentation_worker:
                    try:
                        self._segmentation_worker.stop()
                        if self._segmentation_worker_task:
                            await self._segmentation_worker_task
                        self.logger.info("✅ Segmentation worker stopped")
                    except Exception as e:
                        self.logger.warning(f"Error stopping segmentation worker: {e}")

                # Stop backfill task
                if self._backfill_task:
                    try:
                        await self._backfill_task.stop()
                        self.logger.info("✅ Backfill task stopped")
                    except Exception as e:
                        self.logger.warning(f"Error stopping backfill task: {e}")

                # Stop event loop monitor
                try:
                    await self.event_loop_monitor.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping event loop monitor: {e}")
                
                # Shut down import/export job manager (cancel running jobs)
                if hasattr(self, 'import_export_manager') and self.import_export_manager:
                    try:
                        await self.import_export_manager.shutdown()
                        self.logger.info("✅ Import/export job manager shut down")
                    except Exception as e:
                        self.logger.warning(f"Error shutting down import/export manager: {e}")

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
        self.logger.info("Initializing fuzzy mapping routes...")
        self._init_fuzzy_mapping_routes()
        self.logger.info("Initializing vector index routes...")
        self._init_vector_index_routes()
        self.logger.info("Initializing search mapping routes...")
        self._init_search_mapping_routes()
        self.logger.info("Initializing FTS index routes...")
        self._init_fts_index_routes()
        self.logger.info("Initializing geo config routes...")
        self._init_geo_config_routes()
        self.logger.info("Initializing geo points routes...")
        self._init_geo_points_routes()
        self.logger.info("Initializing ontology routes...")
        self._init_ontology_routes()
        self.logger.info("Initializing metrics routes...")
        self._init_metrics_routes()
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
        from vitalgraph.endpoint.kgdocuments_endpoint import create_kgdocuments_router
        
        # Create routers with space manager and auth dependency
        triples_router = create_triples_router(self.space_manager, self.get_current_user)
        kgtypes_router = create_kgtypes_router(self.space_manager, self.get_current_user)
        objects_router = create_objects_router(self.space_manager, self.get_current_user)
        kgentities_router = create_kgentities_router(self.space_manager, self.get_current_user)
        kgframes_router = create_kgframes_router(self.space_manager, self.get_current_user)
        kgrelations_router = create_kgrelations_router(self.space_manager, self.get_current_user)
        kgqueries_router = create_kgqueries_router(self.space_manager, self.get_current_user)
        kgdocuments_router = create_kgdocuments_router(self.space_manager, self.get_current_user, segmentation_worker=self._segmentation_worker)
        files_router = create_files_router(self.space_manager, self.get_current_user, config=self.config.config_data)
        
        # Include routers in the FastAPI app  
        self.app.include_router(triples_router, prefix="/api/graphs")
        self.app.include_router(kgtypes_router, prefix="/api/graphs")
        self.app.include_router(objects_router, prefix="/api/graphs")
        self.app.include_router(kgentities_router, prefix="/api/graphs")
        self.app.include_router(kgframes_router, prefix="/api/graphs")
        self.app.include_router(kgrelations_router, prefix="/api/graphs")
        self.app.include_router(kgqueries_router, prefix="/api/graphs")
        self.app.include_router(kgdocuments_router, prefix="/api/graphs")
        self.app.include_router(files_router, prefix="/api")
    
    def _init_data_routers(self):
        """Initialize data import/export endpoint routers.

        Routes are registered unconditionally at init time so FastAPI
        compiles them into the route table.  The actual
        ImportExportJobManager is created later during the startup
        event (see ``_init_import_export_manager``) and stored on
        ``self.import_export_manager``.  The endpoint classes receive
        ``self`` (the app impl) so they can resolve the manager lazily.
        """
        from vitalgraph.endpoint.import_endpoint import create_import_router
        from vitalgraph.endpoint.export_endpoint import create_export_router

        # Create routers – pass *self* so endpoints can lazily access
        # self.import_export_manager once it is created at startup.
        import_router = create_import_router(self, self.space_manager, self.get_current_user)
        export_router = create_export_router(self, self.space_manager, self.get_current_user)

        self.app.include_router(import_router, prefix="/api/data", tags=["Data"])
        self.app.include_router(export_router, prefix="/api/data", tags=["Data"])
        self.logger.info("✅ Data import/export routers registered (manager created at startup)")

    def _init_import_export_manager(self):
        """Create the ImportExportJobManager once the DB pool is available.

        Called from the startup event after ``connect_database()``.
        """
        from vitalgraph.jobs.import_export_manager import ImportExportJobManager

        pool = getattr(self.db_impl, 'connection_pool', None)
        if pool is None:
            self.logger.warning("ImportExportJobManager skipped — no connection pool")
            return

        signal_mgr = None
        if self.vital_graph_impl:
            signal_mgr = self.vital_graph_impl.signal_manager
        if signal_mgr is None and self.db_impl:
            signal_mgr = getattr(self.db_impl, 'get_signal_manager', lambda: None)()

        self.import_export_manager = ImportExportJobManager(pool, signal_manager=signal_mgr)
        self.logger.info("✅ ImportExportJobManager created")
    
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
        
        self.app.get(
            "/health/cache",
            tags=["Health"],
            summary="Cache Stats",
            description="Return entity graph cache statistics"
        )(self.cache_stats)
        
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
        from vitalgraph.endpoint.api_keys_endpoint import create_api_keys_router
        
        # Create and include users router
        users_router = create_users_router(self.api, self.get_current_user)
        self.app.include_router(users_router, prefix="/api")

        # Create and include API keys router
        api_keys_router = create_api_keys_router(self.api, self.get_current_user)
        self.app.include_router(api_keys_router)
    
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
    
    def _init_ontology_routes(self):
        """Initialize Ontology introspection endpoint routes."""
        from vitalgraph.endpoint.ontology_endpoint import create_ontology_router

        ontology_router = create_ontology_router(self.get_current_user)
        self.app.include_router(ontology_router, prefix="/api", tags=["Ontology"])

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
    
    
    def _init_fuzzy_mapping_routes(self):
        """Initialize fuzzy mapping CRUD endpoint routes."""
        from vitalgraph.endpoint.fuzzy_mappings_endpoint import create_fuzzy_mappings_router
        
        fuzzy_mappings_router = create_fuzzy_mappings_router(self, self.get_current_user)
        self.app.include_router(fuzzy_mappings_router, prefix="/api", tags=["Fuzzy Mappings"])

    def _init_vector_index_routes(self):
        """Initialize vector index CRUD endpoint routes."""
        from vitalgraph.endpoint.vector_indexes_endpoint import create_vector_indexes_router
        
        vector_indexes_router = create_vector_indexes_router(self, self.get_current_user)
        self.app.include_router(vector_indexes_router, prefix="/api", tags=["Vector Indexes"])
    
    def _init_search_mapping_routes(self):
        """Initialize search mapping CRUD endpoint routes."""
        from vitalgraph.endpoint.search_mappings_endpoint import create_search_mappings_router
        
        search_mappings_router = create_search_mappings_router(self, self.get_current_user)
        self.app.include_router(search_mappings_router, prefix="/api", tags=["Search Mappings"])

    def _init_fts_index_routes(self):
        """Initialize FTS index CRUD endpoint routes."""
        from vitalgraph.endpoint.fts_indexes_endpoint import create_fts_indexes_router
        
        fts_indexes_router = create_fts_indexes_router(self, self.get_current_user)
        self.app.include_router(fts_indexes_router, prefix="/api", tags=["FTS Indexes"])

    def _init_geo_config_routes(self):
        """Initialize geo config CRUD endpoint routes."""
        from vitalgraph.endpoint.geo_config_endpoint import create_geo_config_router
        
        geo_config_router = create_geo_config_router(self, self.get_current_user)
        self.app.include_router(geo_config_router, prefix="/api", tags=["Geo Config"])

    def _init_geo_points_routes(self):
        """Initialize geo points listing/query endpoint routes."""
        from vitalgraph.endpoint.geo_points_endpoint import create_geo_points_router
        
        geo_points_router = create_geo_points_router(self, self.get_current_user)
        self.app.include_router(geo_points_router, prefix="/api", tags=["Geo"])
    
    def _init_metrics_routes(self):
        """Initialize query metrics endpoint routes."""
        from vitalgraph.endpoint.metrics_endpoint import MetricsEndpoint
        
        metrics_endpoint = MetricsEndpoint(self.api)
        self.app.include_router(metrics_endpoint.router, prefix="/api", tags=["Metrics"])
    
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

    async def health(self):
        """Health check endpoint - delegates to API class"""
        return await self.api.health()

    async def cache_stats(self):
        """Return entity graph cache statistics."""
        from vitalgraph.cache.entity_graph_cache import _entity_graph_cache
        return {"entity_graph_cache": _entity_graph_cache.stats}
    
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
