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
from fastapi.encoders import jsonable_encoder
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



# Shaping validation errors needs nothing from the server, so it lives in a
# module that does not drag fastapi/uvicorn/torch in with it. Re-exported
# here because callers and tests already import these names from `main`.
from vitalgraph.main.validation_errors import (  # noqa: F401
    _MAX_ECHOED_INPUT,
    _describe_input,
    _safe_errors,
)


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
        logger.warning("Validation error for %s %s", request.method, request.url)
        for error in exc.errors():
            logger.warning(
                "  field=%s error=%s type=%s",
                error.get("loc"), error.get("msg"), error.get("type"),
            )
        # jsonable_encoder is not optional here, and leaving it out was turning
        # 422s into 500s.
        #
        # When a request body fails validation, pydantic v2 puts the offending
        # input in `error["input"]` -- and for a body whose Content-Type is not
        # JSON that input is raw BYTES. json.dumps cannot serialise bytes, so
        # this handler raised, and a handler that raises produces a 500. The
        # result was that any request carrying a non-JSON body to any endpoint
        # expecting a model got a SERVER FAULT for what is a client mistake.
        #
        # Measured 2026-08-16 against the SPARQL 1.1 Protocol suite: 22 of 34
        # standard protocol requests returned 500, all through this one line.
        # A JSON body with a wrong field returned 422 correctly, which is why
        # this survived -- the ordinary case, and every test of it, was fine.
        #
        # FastAPI's own default handler encodes for exactly this reason; this
        # one was written to add logging and dropped it.
        #
        # The encoder alone is still not enough. Its default rule for bytes is
        # `o.decode()`, which assumes UTF-8 and raises UnicodeDecodeError on a
        # body that is not -- so a UTF-16 or binary body still produced a 500,
        # inside the handler meant to prevent one. `_safe_errors` therefore
        # takes the raw input out of the encoder's path entirely.
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"detail": _safe_errors(exc.errors())}),
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

