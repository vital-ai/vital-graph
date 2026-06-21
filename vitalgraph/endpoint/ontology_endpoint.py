"""Ontology Properties Endpoint for VitalGraph

Provides a REST API endpoint to discover available RDF properties
for a given KG class URI using VitalSigns introspection.
"""

import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Map of class URI → Python import path
_CLASS_MAP: Dict[str, str] = {
    "http://vital.ai/ontology/haley-ai-kg#KGEntity": "ai_haley_kg_domain.model.KGEntity.KGEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGFrame": "ai_haley_kg_domain.model.KGFrame.KGFrame",
    "http://vital.ai/ontology/haley-ai-kg#KGSlot": "ai_haley_kg_domain.model.KGSlot.KGSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGTextSlot": "ai_haley_kg_domain.model.KGTextSlot.KGTextSlot",
    "http://vital.ai/ontology/haley-ai-kg#KGDocument": "ai_haley_kg_domain.model.KGDocument.KGDocument",
    "http://vital.ai/ontology/haley-ai-kg#KGEntityType": "ai_haley_kg_domain.model.KGEntityType.KGEntityType",
    "http://vital.ai/ontology/haley-ai-kg#KGFrameType": "ai_haley_kg_domain.model.KGFrameType.KGFrameType",
    "http://vital.ai/ontology/haley-ai-kg#KGSlotType": "ai_haley_kg_domain.model.KGSlotType.KGSlotType",
    "http://vital.ai/ontology/haley-ai-kg#KGRelationType": "ai_haley_kg_domain.model.KGRelationType.KGRelationType",
    "http://vital.ai/ontology/haley-ai-kg#KGType": "ai_haley_kg_domain.model.KGType.KGType",
}

# Cache: class_uri → list of property dicts
_CACHE: Dict[str, List[Dict]] = {}


class OntologyProperty(BaseModel):
    uri: str
    local_name: Optional[str] = None
    short_name: Optional[str] = None
    property_class: Optional[str] = None


class OntologyPropertiesResponse(BaseModel):
    class_uri: str
    properties: List[OntologyProperty]
    total_count: int


def _import_class(dotted_path: str):
    """Import a class from a dotted module path like 'module.Class'."""
    parts = dotted_path.rsplit(".", 1)
    module_path, class_name = parts[0], parts[1]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _get_properties_for_class(class_uri: str) -> List[Dict]:
    """Introspect VitalSigns class to get its domain properties."""
    if class_uri in _CACHE:
        return _CACHE[class_uri]

    dotted_path = _CLASS_MAP.get(class_uri)
    if not dotted_path:
        logger.warning("Unknown class URI for ontology lookup: %s", class_uri)
        return []

    try:
        cls = _import_class(dotted_path)
        instance = cls()
        domain_props = instance.get_allowed_domain_properties()

        from vital_ai_vitalsigns.impl.vitalsigns_impl import VitalSignsImpl

        results = []
        for prop in domain_props:
            prop_uri = prop.get("uri", "")
            prop_class = prop.get("prop_class", "")
            prop_class_name = prop_class.__name__ if hasattr(prop_class, "__name__") else str(prop_class)

            short_name = None
            local_name = None
            try:
                trait_class = VitalSignsImpl.get_trait_class_from_uri(prop_uri)
                if trait_class:
                    short_name = trait_class.get_short_name()
                    local_name = trait_class.local_name
            except Exception:
                pass

            results.append({
                "uri": prop_uri,
                "local_name": local_name,
                "short_name": short_name,
                "property_class": prop_class_name,
            })

        _CACHE[class_uri] = results
        logger.info("Cached %d properties for %s", len(results), class_uri)
        return results

    except Exception as e:
        logger.error("Failed to introspect properties for %s: %s", class_uri, e)
        return []


def create_ontology_router(auth_dependency) -> APIRouter:
    """Create and return the ontology router."""
    router = APIRouter()

    @router.get(
        "/ontology/properties",
        response_model=OntologyPropertiesResponse,
        tags=["Ontology"],
        summary="Get Properties for a Class",
        description="Returns the list of available RDF properties for the given VitalSigns class URI.",
    )
    async def get_ontology_properties(
        class_uri: str = Query(..., description="VitalSigns class URI (e.g. http://vital.ai/ontology/haley-ai-kg#KGEntity)"),
        current_user: Dict = Depends(auth_dependency),
    ):
        properties = _get_properties_for_class(class_uri)
        return OntologyPropertiesResponse(
            class_uri=class_uri,
            properties=[OntologyProperty(**p) for p in properties],
            total_count=len(properties),
        )

    @router.get(
        "/ontology/classes",
        tags=["Ontology"],
        summary="List Known Classes",
        description="Returns the list of class URIs known to the ontology endpoint.",
    )
    async def list_ontology_classes(
        current_user: Dict = Depends(auth_dependency),
    ):
        return {"classes": list(_CLASS_MAP.keys())}

    return router
