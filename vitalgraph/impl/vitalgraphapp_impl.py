
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
        
        # Get Space Manager from VitalGraphImpl
        self.space_manager = self.vital_graph_impl.get_space_manager()
        print(f"🔍 DEBUG: Retrieved space_manager from VitalGraphImpl: {self.space_manager}")
        print(f"🔍 DEBUG: space_manager type: {type(self.space_manager)}")
        
        # Initialize VitalGraph API with auth handler, database implementation, and space manager
        self.api = VitalGraphAPI(
            auth_handler=self.auth,
            db_impl=self.db_impl, 
            space_manager=self.space_manager
        )
        print(f"🔍 DEBUG: VitalGraphAPI initialized with space_manager: {self.api.space_manager}")
        
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
            self.logger.debug(f"🔍 INCOMING REQUEST: {request.method} {request.url}")
            self.logger.debug(f"🔍 REQUEST HEADERS: {dict(request.headers)}")
            response = await call_next(request)
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
        """Setup FastAPI startup events"""
        @self.app.on_event("startup")
        async def startup_event():
            """Connect to database on server startup"""
            if self.vital_graph_impl:
                try:
                    self.logger.debug("About to connect database via VitalGraphImpl")
                    # Use VitalGraphImpl.connect_database() which handles SignalManager creation and injection
                    success = await self.vital_graph_impl.connect_database()
                    self.logger.info(f"Connected to database successfully: {success}")
                    
                    # Update space_manager reference after database connection
                    self.space_manager = self.vital_graph_impl.get_space_manager()
                    print(f"🔍 STARTUP DEBUG: Updated space_manager after DB connection: {self.space_manager}")
                    
                    # Set the space_manager on VitalGraphAPI now that it's available
                    if self.space_manager is not None:
                        self.api.space_manager = self.space_manager
                        print(f"🔍 STARTUP DEBUG: Set space_manager on VitalGraphAPI: {self.api.space_manager}")
                        print(f"🔍 STARTUP DEBUG: API object id: {id(self.api)}")
                        print(f"🔍 STARTUP DEBUG: Endpoints already registered during init - they will use this updated API instance")
                    else:
                        print(f"❌ STARTUP ERROR: space_manager is still None after database connection")
                    
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
                    else:
                        self.logger.warning("SpaceManager initialization skipped - conditions not met")
                    
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
                    
                except Exception as e:
                    self.logger.error(f"Failed to connect to database: {e}")
    
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
        self.app.include_router(graph_router, prefix="/api/graphs/sparql")
        self.logger.info(f"Included graph router with prefix '/api/graphs/sparql' - {len(graph_router.routes)} routes")
    
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
    
    def _init_frontend_routes(self):
        """Initialize frontend serving routes."""
        # Frontend serving routes
        if self.app_mode == "production":
            self.app.get("/", response_class=HTMLResponse)(self.serve_frontend)
            self.app.get("/{path:path}")(self.catch_all)
        else:
            self.app.get("/")(self.api_root)
    

    async def login(self, form_data: OAuth2PasswordRequestForm = Depends()):
        """Login endpoint - delegates to API class"""
        return await self.api.login(form_data)

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
