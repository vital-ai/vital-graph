"""Ontology introspection request/response models."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel

from .result_status import ResultStatus, OperationStatus


class OntologyProperty(BaseModel):
    uri: str
    local_name: Optional[str] = None
    short_name: Optional[str] = None
    property_class: Optional[str] = None


class OntologyPropertiesResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    class_uri: str
    properties: List[OntologyProperty]
    total_count: int


class OntologyClassesResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    classes: List[str]
