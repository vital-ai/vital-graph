import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# Configure logging FIRST, before any other imports
# This ensures all modules use the correct logging format
# Start with ERROR level, will be overridden by config file in VitalGraphAppImpl
logging.basicConfig(
    # level=logging.ERROR,
    format='%(asctime)s.%(msecs)03d - %(name)s - %(funcName)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler()
    ],
    force=True  # Force reconfiguration even if handlers exist
)

from fastapi import FastAPI, Request, Response, status, Depends, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from vitalgraph.utils.db_retry import DatabaseUnavailableError
import uvicorn
from vitalgraph.impl.vitalgraphapp_impl import VitalGraphAppImpl
from vitalgraph.config.config_loader import get_config, ConfigurationError



def create_app() -> FastAPI:
    """Application factory function."""
    
    try:
        # Load configuration from environment variables
        config = get_config()
        logging.getLogger(__name__).info("✅ Loaded VitalGraph configuration from environment variables")
            
    except ConfigurationError as e:
        logging.getLogger(__name__).error(f"❌ Configuration error: {e}")
        logging.getLogger(__name__).error("Cannot start server without valid configuration")
        raise
    
    app = FastAPI(title="VitalGraph API")
    
    # Add custom validation error handler to log detailed 422 errors
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger = logging.getLogger(__name__)
        logger.error(f"🚨 VALIDATION ERROR for {request.method} {request.url}")
        logger.error(f"Request body: {await request.body()}")
        for error in exc.errors():
            logger.error(f"Field: {error['loc']}, Error: {error['msg']}, Type: {error['type']}")
        # Return the default FastAPI validation error response
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()}
        )
    
    # Convert transient DB failures to 503 so clients know to retry
    @app.exception_handler(DatabaseUnavailableError)
    async def db_unavailable_handler(request: Request, exc: DatabaseUnavailableError):
        logger = logging.getLogger(__name__)
        logger.warning(
            "503 Database unavailable for %s %s: %s",
            request.method, request.url.path, exc,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Database temporarily unavailable, please retry"},
        )
    
    vital_graph = VitalGraphAppImpl(app=app, config=config)
    
    return app

def run_server():
    
    os.environ["APP_MODE"] = "production"
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    workers = int(os.getenv("WORKERS", "1"))
    
    # Read log level from config environment variable
    env = os.getenv('VITALGRAPH_ENVIRONMENT', 'local').upper()
    log_level = os.getenv(f'{env}_LOG_LEVEL', os.getenv('LOG_LEVEL', 'info')).lower()
    
    if workers > 1:
        # Multi-worker: pass factory string so each worker creates its own app
        # with independent DB connections, caches, and VitalSigns state
        uvicorn.run(
            "vitalgraph.main.main:create_app",
            factory=True,
            host=host,
            port=port,
            workers=workers,
            reload=False,
            log_level=log_level
        )
    else:
        # Single-worker: create app directly (preserves existing behavior)
        app = create_app()
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,
            log_level=log_level
        )


if __name__ == "__main__":
    run_server()

