"""
Format Negotiation Utilities

FastAPI dependencies for detecting request/response format based on
Content-Type and Accept headers. Supports two primary formats:

  - JSON Quads (application/json) — default
  - N-Quads   (application/n-quads)

"""

import logging
from enum import Enum
from typing import Optional

from fastapi import Request, Header

logger = logging.getLogger(__name__)


class WireFormat(str, Enum):
    """Supported wire formats for VitalGraph API."""
    JSON_QUADS = "json_quads"
    NQUADS = "nquads"


# MIME type constants
MIME_NQUADS = "application/n-quads"
MIME_JSON = "application/json"


def detect_request_format(content_type: Optional[str] = None) -> WireFormat:
    """Detect request format from Content-Type header.

    Rules:
      - application/n-quads          → NQUADS
      - application/json / missing   → JSON_QUADS (default)
    """
    if not content_type:
        return WireFormat.JSON_QUADS

    ct = content_type.lower().split(";")[0].strip()

    if ct == MIME_NQUADS:
        return WireFormat.NQUADS

    return WireFormat.JSON_QUADS


def detect_json_body_format(body: dict) -> WireFormat:
    """Inspect a parsed JSON body to distinguish JSON Quads formats.

    - Has "quads" key                        → JSON_QUADS (QuadRequest)
    - Otherwise                              → JSON_QUADS (default)
    """
    return WireFormat.JSON_QUADS


def detect_response_format(accept: Optional[str] = None) -> WireFormat:
    """Detect desired response format from Accept header.

    Rules:
      - application/n-quads     → NQUADS
      - application/json / missing / other → JSON_QUADS (default)
    """
    if not accept:
        return WireFormat.JSON_QUADS

    accept_lower = accept.lower()

    if MIME_NQUADS in accept_lower:
        return WireFormat.NQUADS

    return WireFormat.JSON_QUADS


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

async def get_request_format(request: Request) -> WireFormat:
    """FastAPI dependency: detect the incoming request format.

    For application/json bodies, inspects the parsed JSON.
    """
    content_type = request.headers.get("content-type", "")
    ct = content_type.lower().split(";")[0].strip()

    if ct == MIME_NQUADS:
        return WireFormat.NQUADS

    # For JSON content type, peek at body to detect format
    if ct == MIME_JSON:
        try:
            body = await request.json()
            # Cache the parsed body so the endpoint doesn't re-parse
            request.state.parsed_body = body
            return detect_json_body_format(body)
        except Exception:
            pass

    return WireFormat.JSON_QUADS


async def get_response_format(
    accept: Optional[str] = Header(None, alias="accept"),
) -> WireFormat:
    """FastAPI dependency: detect the desired response format from Accept header."""
    return detect_response_format(accept)
