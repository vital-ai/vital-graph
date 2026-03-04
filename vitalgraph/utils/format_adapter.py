"""
Format Adapter

Bridges between wire formats (JSON Quads, N-Quads) and VitalSigns
GraphObjects. Every request/response goes through this adapter.

Request flow:
  Wire format → format_adapter → List[Quad]
  (endpoints convert quads to GraphObjects internally)

Response flow:
  List[GraphObject] + pagination → format_adapter → FastAPI Response
"""

import logging
from typing import List, Optional, Union, Dict, Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse
from vitalgraph.utils.format_negotiation import WireFormat
from vitalgraph.utils.quad_format_utils import (
    graphobjects_to_quad_list,
    quad_list_to_graphobjects,
    quads_to_nquads_text,
    nquads_text_to_quads,
    graphobjects_to_json_quads_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request parsing: wire format → List[Quad]
# ---------------------------------------------------------------------------

async def parse_request_body_as_quads(
    request: Request,
    wire_format: WireFormat,
) -> List[Quad]:
    """Parse request body into quads based on detected wire format.

    Args:
        request: FastAPI Request object
        wire_format: Detected format from get_request_format dependency

    Returns:
        List of Quad objects
    """
    if wire_format == WireFormat.NQUADS:
        body_bytes = await request.body()
        nquads_text = body_bytes.decode("utf-8")
        return nquads_text_to_quads(nquads_text)

    if wire_format == WireFormat.JSON_QUADS:
        body = getattr(request.state, "parsed_body", None)
        if body is None:
            body = await request.json()
        quad_request = QuadRequest(**body)
        return quad_request.quads

    # Unrecognized JSON body — try as raw quad list
    body = getattr(request.state, "parsed_body", None)
    if body is None:
        body = await request.json()
    if isinstance(body, list):
        return [Quad(**q) for q in body]
    return []


async def parse_request_body(
    request: Request,
    wire_format: WireFormat,
) -> List[GraphObject]:
    """Parse request body into GraphObjects based on detected wire format.

    .. deprecated:: Use parse_request_body_as_quads instead.
    """
    quads = await parse_request_body_as_quads(request, wire_format)
    return quad_list_to_graphobjects(quads)


# ---------------------------------------------------------------------------
# Response serialization: GraphObjects → wire format
# ---------------------------------------------------------------------------

def build_response(
    graph_objects: List[GraphObject],
    wire_format: WireFormat,
    response: Response,
    graph_uri: Optional[str] = None,
    total_count: int = 0,
    page_size: int = 0,
    offset: int = 0,
) -> Any:
    """Serialize GraphObjects to the requested wire format.

    Args:
        graph_objects: VitalSigns objects to serialize
        wire_format: Desired response format
        response: FastAPI Response for setting headers
        graph_uri: Optional graph URI for quad g field
        total_count: Total matching results
        page_size: Page size
        offset: Offset

    Returns:
        FastAPI-compatible response (JSONResponse, Response, or Pydantic model)
    """
    if wire_format == WireFormat.NQUADS:
        quads = graphobjects_to_quad_list(graph_objects, graph_uri)
        nquads_text = quads_to_nquads_text(quads)

        return Response(
            content=nquads_text,
            media_type="application/n-quads",
            headers={
                "X-Total-Count": str(total_count),
                "X-Page-Size": str(page_size),
                "X-Offset": str(offset),
            },
        )

    # JSON_QUADS — produce JSON Quads response
    quad_response = graphobjects_to_json_quads_response(
        graph_objects,
        graph_uri=graph_uri,
        total_count=total_count,
        page_size=page_size,
        offset=offset,
    )
    return JSONResponse(
        content=quad_response.model_dump(),
        media_type="application/json",
    )


def build_graphobjects_response(
    graph_objects: List[GraphObject],
    wire_format: WireFormat,
    response: Response,
    graph_uri: Optional[str] = None,
) -> Any:
    """Serialize GraphObjects for single-entity or multi-entity GET responses.

    Unlike build_response(), this does NOT include pagination metadata.
    Use for GET-by-URI responses that return raw data.

    Returns None if format is unrecognized.
    """
    if wire_format == WireFormat.NQUADS:
        quads = graphobjects_to_quad_list(graph_objects, graph_uri)
        nquads_text = quads_to_nquads_text(quads)
        return Response(
            content=nquads_text,
            media_type="application/n-quads",
        )

    # JSON_QUADS — respond with JSON Quads
    quads = graphobjects_to_quad_list(graph_objects, graph_uri)
    return JSONResponse(
        content={
            "results": [q.model_dump(exclude_none=True) for q in quads],
            "total_count": len(graph_objects),
        },
        media_type="application/json",
    )
