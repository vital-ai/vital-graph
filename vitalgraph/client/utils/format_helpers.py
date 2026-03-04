"""
Client-side Format Helpers

Utilities for converting between VitalSigns GraphObjects and the supported
wire formats (JSON Quads, N-Quads) on the client side.

Used by client endpoint classes to serialize requests and deserialize responses
without leaking format details into the endpoint logic.
"""

import json
import logging
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse
from vitalgraph.utils.quad_format_utils import (
    graphobjects_to_quad_list,
    quad_list_to_graphobjects,
    quads_to_nquads_text,
    nquads_text_to_quads,
)

logger = logging.getLogger(__name__)


class ClientWireFormat(str, Enum):
    """Wire format preference for the client."""
    JSON_QUADS = "json_quads"
    NQUADS = "nquads"


# MIME types
MIME_NQUADS = "application/n-quads"
MIME_JSON = "application/json"

FORMAT_TO_ACCEPT = {
    ClientWireFormat.JSON_QUADS: MIME_JSON,
    ClientWireFormat.NQUADS: MIME_NQUADS,
}

FORMAT_TO_CONTENT_TYPE = {
    ClientWireFormat.JSON_QUADS: MIME_JSON,
    ClientWireFormat.NQUADS: MIME_NQUADS,
}


# ---------------------------------------------------------------------------
# Request serialization  (GraphObjects → wire body)
# ---------------------------------------------------------------------------

def serialize_quads_for_request(
    quads: List[Quad],
    wire_format: ClientWireFormat,
) -> Tuple[Any, str]:
    """Serialize quads into a request body for the given wire format.

    Returns:
        (body, content_type) where body is:
          - dict for JSON formats (passed as json= kwarg)
          - str for N-Quads (passed as content= kwarg)
    """
    if wire_format == ClientWireFormat.NQUADS:
        text = quads_to_nquads_text(quads)
        return text, MIME_NQUADS

    # JSON Quads (default)
    req = QuadRequest(quads=quads)
    return req.model_dump(), MIME_JSON


def serialize_graphobjects_for_request(
    objects: List[GraphObject],
    wire_format: ClientWireFormat,
    graph_uri: Optional[str] = None,
) -> Tuple[Any, str]:
    """Serialize GraphObjects into a request body for the given wire format.

    .. deprecated:: Use serialize_quads_for_request instead.

    Returns:
        (body, content_type) where body is:
          - dict for JSON formats (passed as json= kwarg)
          - str for N-Quads (passed as content= kwarg)
    """
    quads = graphobjects_to_quad_list(objects, graph_uri)
    logger.debug(f"Serialized {len(objects)} GraphObjects → {len(quads)} quads (format={wire_format.value})")
    if quads and logger.isEnabledFor(logging.DEBUG):
        for i, q in enumerate(quads[:5]):
            logger.debug(f"  quad[{i}]: s={q.s}  p={q.p}  o={q.o}  g={q.g}")
        if len(quads) > 5:
            logger.debug(f"  ... and {len(quads) - 5} more quads")
    return serialize_quads_for_request(quads, wire_format)


# ---------------------------------------------------------------------------
# Response deserialization  (wire body → GraphObjects)
# ---------------------------------------------------------------------------

def deserialize_response_to_graphobjects(
    response_data: Any,
    wire_format: ClientWireFormat,
    vs: Optional[VitalSigns] = None,
) -> List[GraphObject]:
    """Deserialize a response body (already parsed) into GraphObjects.

    Args:
        response_data: Parsed JSON dict (for JSON formats) or raw text (for N-Quads)
        wire_format: The format the server responded with
        vs: VitalSigns instance (unused, kept for API compatibility)

    Returns:
        List of GraphObject instances
    """
    if wire_format == ClientWireFormat.JSON_QUADS:
        if logger.isEnabledFor(logging.DEBUG) and isinstance(response_data, dict):
            results = response_data.get('results', [])
            logger.debug(f"Deserializing JSON_QUADS response: {len(results)} quads")
            for i, q in enumerate(results[:5]):
                logger.debug(f"  result[{i}]: s={q.get('s')}  p={q.get('p')}  o={q.get('o')}  g={q.get('g')}")
            if len(results) > 5:
                logger.debug(f"  ... and {len(results) - 5} more quads")
        return _parse_json_quads_response(response_data)

    if wire_format == ClientWireFormat.NQUADS:
        if isinstance(response_data, str):
            quads = nquads_text_to_quads(response_data)
            return quad_list_to_graphobjects(quads)
        return []

    # Unrecognized format
    logger.warning(f"Unsupported wire format: {wire_format}")
    return []


def extract_pagination_from_json_quads(response_data: dict) -> dict:
    """Extract pagination metadata from a QuadResponse envelope."""
    return {
        "total_count": response_data.get("total_count", 0),
        "page_size": response_data.get("page_size", 0),
        "offset": response_data.get("offset", 0),
    }


def is_json_quads_response(response_data: Any) -> bool:
    """Check if a parsed JSON response is a JSON Quads envelope.
    
    Matches both paginated responses (results + total_count) from build_response
    and non-paginated responses (results only) from build_graphobjects_response.
    """
    if not isinstance(response_data, dict):
        return False
    if "results" in response_data:
        results = response_data["results"]
        if isinstance(results, list) and (len(results) == 0 or (len(results) > 0 and isinstance(results[0], dict) and "s" in results[0])):
            return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_json_quads_response(response_data: Any) -> List[GraphObject]:
    """Parse a JSON Quads response (QuadResponse envelope or bare list)."""
    if isinstance(response_data, dict):
        if "results" in response_data:
            # Parse results list directly — works for both full QuadResponse
            # (with page_size/offset) and non-paginated responses (results only)
            raw_quads = response_data["results"]
            quads = [Quad.model_validate(q) for q in raw_quads]
            return quad_list_to_graphobjects(quads)
        if "quads" in response_data:
            # QuadRequest-like body
            req = QuadRequest.model_validate(response_data)
            return quad_list_to_graphobjects(req.quads)
    return []

