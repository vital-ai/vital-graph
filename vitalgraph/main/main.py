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



_MAX_ECHOED_INPUT = 200


def _safe_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Make pydantic's validation errors safe to serialise back to the client.

    Two problems with returning `exc.errors()` as-is, both of which showed up as
    500s rather than as anything that looked like a client error:

    1. `error["input"]` holds the raw request body when the body itself failed
       to parse. For a non-JSON Content-Type that is BYTES, and bytes are not
       JSON-serialisable. `jsonable_encoder` fixes the common case by decoding
       as UTF-8 -- and then raises UnicodeDecodeError on a body that is not
       UTF-8, which is the case the SPARQL Protocol suite tests deliberately.

    2. Echoing a whole request body back to the caller is not something to do by
       default regardless of encoding. It can be large, and it can contain
       whatever the caller sent, including credentials they put in the wrong
       field.

    So the input is summarised rather than reflected: decoded if it is text,
    described if it is not, and truncated either way. The error's `loc`, `msg`
    and `type` -- which are what a caller needs to fix the request -- are
    untouched.
    """
    safe: List[Dict[str, Any]] = []
    for error in errors:
        item = dict(error)
        if "input" in item:
            item["input"] = _describe_input(item["input"])
        # `ctx` can carry the original exception object, which is not
        # serialisable either.
        if "ctx" in item:
            item["ctx"] = {k: str(v) for k, v in (item["ctx"] or {}).items()}
        safe.append(item)
    return safe


def _describe_input(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            # The point of the non-UTF-8 protocol cases: say what it was rather
            # than fail trying to render it.
            return f"<{len(value)} bytes, not valid UTF-8>"
        return text[:_MAX_ECHOED_INPUT] + ("..." if len(text) > _MAX_ECHOED_INPUT else "")
    if isinstance(value, str) and len(value) > _MAX_ECHOED_INPUT:
        return value[:_MAX_ECHOED_INPUT] + "..."
    return value


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

