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

# For production, you would use a more secure method for storing and validating users
USERS_DB = {
    "admin": {
        "username": "admin",
        "password": "admin",  # In production, this would be hashed
        "full_name": "Admin User",
        "email": "admin@example.com",
        "profile_image": "/images/users/bonnie-green.png",
        "role": "Administrator",
    }
}

# Set app mode - 'production' serves frontend, 'development' is API only
APP_MODE = os.getenv("APP_MODE", "development").lower()

app = FastAPI(title="VitalGraph API")

# Add CORS middleware to allow requests from the React frontend
if APP_MODE == "production":
    # In production, we need to allow both localhost and 0.0.0.0
    port = os.getenv("PORT", "8001")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://localhost:{port}", f"http://0.0.0.0:{port}", f"http://127.0.0.1:{port}"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # In development, allow requests from the separate frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # Frontend dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Keep session middleware for backward compatibility
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "CHANGE_THIS"))

# Mount React frontend build files only in production
if APP_MODE == "production":
    # Get the directory where main.py is located
    main_dir = Path(__file__).parent
    
    app.mount(
        "/assets",
        StaticFiles(directory=str(main_dir / "frontend" / "dist" / "assets")),
        name="frontend_assets"
    )
    
    # Mount images directory for user profile pictures and other static images
    app.mount(
        "/images",
        StaticFiles(directory=str(main_dir / "frontend" / "dist" / "images")),
        name="static_images"
    )


# Simple token authentication utilities
def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """Authenticate a user against the user database."""
    if username in USERS_DB and USERS_DB[username]["password"] == password:
        return USERS_DB[username]
    return None

# API endpoint to serve the React app - only in production
if APP_MODE == "production":
    @app.get("/", response_class=HTMLResponse)
    async def serve_frontend():
        # Serve the built React app's index.html
        main_dir = Path(__file__).parent
        index_path = main_dir / "frontend" / "dist" / "index.html"
        if index_path.exists():
            with open(index_path) as f:
                return HTMLResponse(content=f.read())
        # Fallback to API docs if index.html doesn't exist
        return RedirectResponse(url="/docs")
else:
    # In development, provide a simple message at root
    @app.get("/")
    async def api_root():
        return {
            "message": "VitalGraph API Server",
            "documentation": "/docs",
            "alternative_docs": "/redoc"
        }

# Authentication API endpoints
@app.post("/api/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # In a production app, we would use JWT tokens here
    # For simplicity, we're just returning a simple token
    token = f"user-{form_data.username}-token"
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "profile_image": user["profile_image"],
        "role": user["role"]
    }

# Token verification dependency
def get_current_user(token: str = Depends(OAuth2PasswordBearer(tokenUrl="api/login"))):
    """Verify token and return user"""
    # In a real app, this would validate a JWT token
    # For our simple example, we'll just check if it follows our pattern
    if not token.startswith("user-") or not token.endswith("-token"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Extract username from token
    username = token.split("-")[1]
    if username not in USERS_DB:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return USERS_DB[username]

@app.post("/api/logout")
async def logout(request: Request, current_user: Dict = Depends(get_current_user)):
    """Logout the current user"""
    request.session.clear()
    return {"status": "logged out"}

# API endpoint for spaces
@app.get("/api/spaces")
async def list_spaces(current_user: Dict = Depends(get_current_user)):
    """Get list of spaces for the authenticated user"""
    # In a real app, these would come from the database
    spaces = [
        {"id": 1, "name": "RDF Graph", "type": "rdf_graph"},
        {"id": 2, "name": "Vital Graph", "type": "vital_graph"},
    ]
    
    return {"spaces": spaces, "user": current_user["username"]}

# SPARQL endpoint (placeholder)
@app.post("/api/sparql")
async def sparql_endpoint(
    query: str = Body(...),
    current_user: Dict = Depends(get_current_user)
):
    """Execute a SPARQL query"""
    # In a real app, this would execute the query against the graph database
    # For now, just return a dummy response
    return {
        "results": {
            "bindings": [
                {"subject": {"value": "http://example.org/subject1"}},
                {"subject": {"value": "http://example.org/subject2"}}
            ]
        }
    }

# Health check endpoint
@app.get("/health")
async def health():
    return {"status": "ok"}

# No legacy endpoints - all routes use /api/* convention


# Catch-all route for client-side routing - only in production
if APP_MODE == "production":
    @app.get("/{path:path}")
    async def catch_all(path: str):
        main_dir = Path(__file__).parent
        
        # First, try to serve static files from the dist directory (SVGs, favicon, etc.)
        static_file_path = main_dir / "frontend" / "dist" / path
        if static_file_path.exists() and static_file_path.is_file():
            return FileResponse(static_file_path)
        
        # Only catch routes that don't start with /api or /static for SPA routing
        if path.startswith("api/") or path.startswith("static/") or path.startswith("docs") or path == "openapi.json":
            raise HTTPException(status_code=404, detail="Not found")
        
        # Return the index.html for client-side routing
        index_path = main_dir / "frontend" / "dist" / "index.html"
        if index_path.exists():
            with open(index_path) as f:
                return HTMLResponse(content=f.read())
        return RedirectResponse(url="/docs")

def run_server():
    """Entry point for the console script (vitalgraphdb command).
    Always runs in production mode with frontend serving.
    """
    # Force production mode for the vitalgraphdb command
    # This overrides any APP_MODE environment variable
    global APP_MODE
    APP_MODE = "production"
    
    # Get host and port from environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    
    # No auto-reload in production
    uvicorn.run(
        "vitalgraph.api.main:app", 
        host=host, 
        port=port, 
        reload=False
    )

if __name__ == "__main__":
    run_server()

