import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
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
    
    vital_graph = VitalGraphImpl(app=app, config=config)
    
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

