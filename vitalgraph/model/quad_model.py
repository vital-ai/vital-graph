"""Quad Model Classes

Pydantic models for N-Quads and JSON Quads format handling across VitalGraph endpoints.

Term encoding follows standard N-Quads rules:
  - URIs:                  <http://example.org/thing>
  - Plain string literals: "Alice"
  - Typed literals:        "30"^^<http://www.w3.org/2001/XMLSchema#integer>
  - Language-tagged:       "hello"@en
  - Blank nodes:           _:b1
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field

from .result_status import ResultStatus, OperationStatus


class Quad(BaseModel):
    """A single RDF quad with N-Quads term encoding in each field."""
    s: str = Field(description="Subject - URI in angle brackets or blank node label")
    p: str = Field(description="Predicate - URI in angle brackets")
    o: str = Field(description="Object - URI, literal with optional datatype/lang, or blank node")
    g: Optional[str] = Field(default=None, description="Graph - URI in angle brackets, omitted for default graph")


class QuadRequest(BaseModel):
    """JSON Quads request body — a list of quads, no metadata."""
    quads: List[Quad] = Field(description="List of RDF quads to send")


class QuadResultsResponse(ResultStatus):
    """JSON Quads response envelope — non-paginated (get-by-URI).

    Inherits the unified success/status/message contract from ResultStatus;
    ``status`` defaults to FOUND (reads), set to EMPTY at runtime when no results
    match, or NOT_FOUND for a get on a specific missing URI. ``success`` is derived.
    """
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/EMPTY/NOT_FOUND/...)"
    )
    total_count: int = Field(description="Total number of matching quads/objects")
    results: List[Quad] = Field(description="List of RDF quads")


class QuadResponse(QuadResultsResponse):
    """JSON Quads response envelope — paginated list results."""
    page_size: int = Field(description="Number of results per page")
    offset: int = Field(description="Offset into the result set")
    has_more: Optional[bool] = Field(
        None,
        description=(
            "Whether another page exists. None means the route has not been "
            "taught to answer, NOT that the answer is no. The client passes "
            "this through and never derives it, because `page_size` does not "
            "mean the same thing on every route — get-by-identifiers sets it "
            "to the number of identifiers requested, so any formula over it "
            "would report a next page for a route that has none. A route that "
            "sets this must be genuinely paged and must compute it against the "
            "real result-set size, not the length of the page it is returning."
        ),
    )
    slot_counts: Optional[Dict[str, int]] = Field(
        None,
        description=(
            "Frame URI → number of slots, present only when the caller asks "
            "for it (include_slot_counts=true on GET /kgentities/kgframes). "
            "Lets a client decide whether a frame needs slot pagination "
            "WITHOUT fetching its slots. A frame with zero slots is omitted "
            "from the map — treat a missing key as 0, not as unknown. Kept out "
            "of the quad stream because the count is derived, not a triple."
        ),
    )
