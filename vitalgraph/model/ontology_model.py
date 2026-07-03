"""Ontology introspection request/response models."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class OntologyProperty(BaseModel):
    uri: str
    local_name: Optional[str] = None
    short_name: Optional[str] = None
    property_class: Optional[str] = None


class OntologyPropertiesResponse(BaseModel):
    class_uri: str
    properties: List[OntologyProperty]
    total_count: int


class OntologyClassesResponse(BaseModel):
    classes: List[str]
