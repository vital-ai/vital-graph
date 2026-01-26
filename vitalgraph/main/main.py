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
import uvicorn
from vitalgraph.impl.vitalgraphapp_impl import VitalGraphAppImpl
from vitalgraph.config.config_loader import get_config, ConfigurationError



def create_app() -> FastAPI:
    """Application factory function."""
    
    try:
        # Try to find configuration file in expected locations
        config_paths = [
            "vitalgraphdb_config/vitalgraphdb-config.yaml",  # Standard location
            "/app/vitalgraphdb_config/vitalgraphdb-config.yaml",  # Docker location
            "config/vitalgraphdb-config.yaml",  # Alternative location
        ]
        
        config = None
        for config_path in config_paths:
            try:
                if Path(config_path).exists():
                    config = get_config(config_path)
                    print(f"✅ Loaded VitalGraph configuration from: {config.config_path}")
                    break
            except Exception as e:
                print(f"⚠️  Failed to load config from {config_path}: {e}")
                continue
        
        if config is None:
            print("❌ No configuration file found in expected locations")
            print("Expected locations:")
            for path in config_paths:
                print(f"  - {path}")
            raise ConfigurationError("No valid configuration file found")
            
    except ConfigurationError as e:
        print(f"❌ Configuration error: {e}")
        print("Cannot start server without valid configuration")
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
    
    vital_graph = VitalGraphAppImpl(app=app, config=config)
    
    return app

def run_server():
    
    os.environ["APP_MODE"] = "production"
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    
    app = create_app()
    
    uvicorn.run(
        app, 
        host=host, 
        port=port, 
        reload=False
    )


# For development and testing
app = create_app()

if __name__ == "__main__":
    run_server()

