"""Quad Model Classes

Pydantic models for N-Quads and JSON Quads format handling across VitalGraph endpoints.

Term encoding follows standard N-Quads rules:
  - URIs:                  <http://example.org/thing>
  - Plain string literals: "Alice"
  - Typed literals:        "30"^^<http://www.w3.org/2001/XMLSchema#integer>
  - Language-tagged:       "hello"@en
  - Blank nodes:           _:b1
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class Quad(BaseModel):
    """A single RDF quad with N-Quads term encoding in each field."""
    s: str = Field(description="Subject - URI in angle brackets or blank node label")
    p: str = Field(description="Predicate - URI in angle brackets")
    o: str = Field(description="Object - URI, literal with optional datatype/lang, or blank node")
    g: Optional[str] = Field(default=None, description="Graph - URI in angle brackets, omitted for default graph")


class QuadRequest(BaseModel):
    """JSON Quads request body — a list of quads, no metadata."""
    quads: List[Quad] = Field(description="List of RDF quads to send")


class QuadResultsResponse(BaseModel):
    """JSON Quads response envelope — non-paginated (get-by-URI)."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    total_count: int = Field(description="Total number of matching quads/objects")
    results: List[Quad] = Field(description="List of RDF quads")


class QuadResponse(QuadResultsResponse):
    """JSON Quads response envelope — paginated list results."""
    page_size: int = Field(description="Number of results per page")
    offset: int = Field(description="Offset into the result set")
