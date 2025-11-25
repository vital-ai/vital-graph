# KG Classes Properties Documentation

This document provides comprehensive information about the properties available for Knowledge Graph (KG) classes in the vital-ai-haley-kg package.

## Overview

The KG classes are defined in the `vital-ai-haley-kg` package version 0.1.24. This documentation was generated using VitalSigns to discover all available properties for each class.

## VitalSigns JSON-LD Conversion Code

### Converting JSON-LD to VitalSigns Objects

```python
from vital_ai_vitalsigns.vitalsigns import VitalSigns

def create_vitalsigns_objects_from_jsonld(jsonld_document: dict) -> list:
    """
    Create VitalSigns objects from JSON-LD document using VitalSigns native methods.
    
    Args:
        jsonld_document: JSON-LD document dict with proper @context
        
    Returns:
        List of VitalSigns objects
    """
    vitalsigns = VitalSigns()
    
    # Use VitalSigns native from_jsonld_list method
    if "@graph" in jsonld_document and isinstance(jsonld_document["@graph"], list):
        # Document with @graph array
        objects = vitalsigns.from_jsonld_list(jsonld_document)
    else:
        # Single object document
        objects = [vitalsigns.from_jsonld(jsonld_document)]
    
    # Ensure we return a list and filter out None objects
    if not isinstance(objects, list):
        objects = [objects] if objects else []
    
    return [obj for obj in objects if obj is not None]
```

### Example JSON-LD Format

```json
{
    "@context": {
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "vital": "http://vital.ai/ontology/vital-core#"
    },
    "@graph": [
        {
            "@id": "http://example.org/entity1",
            "@type": "haley:KGEntity",
            "vital:hasName": "Test Entity",
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity"
        },
        {
            "@id": "http://example.org/slot1",
            "@type": "haley:KGTextSlot", 
            "vital:hasName": "Test Slot",
            "haley:hasTextSlotValue": "Test Text Value",
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
        }
    ]
}
```

### Setting Grouping URIs

```python
def set_grouping_uris(objects: list, entity_uri: str):
    """Set hasKGGraphURI grouping property on all objects."""
    for obj in objects:
        try:
            # Use short name property access - hasKGGraphURI short name is 'kGGraphURI'
            obj.kGGraphURI = entity_uri
        except Exception as e:
            print(f"Failed to set kGGraphURI on object {obj.URI}: {e}")
```

## Class Properties


### Entity Classes

#### KGEntity

- **Module**: `ai_haley_kg_domain.model.KGEntity`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGEntity`
- **Properties**: 88

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityAccountURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityLoginURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFormType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTypeMethodURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGEntitySlot

- **Module**: `ai_haley_kg_domain.model.KGEntitySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGEntitySlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---


### Frame Classes

#### Edge_hasKGFrame

- **Module**: `ai_haley_kg_domain.model.Edge_hasKGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame`
- **Properties**: 78

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasEdgeDestination`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeSource`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasListIndex`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefEdgeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOfficeAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOriginDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley#hasOriginURI`
  - Short name: `None`
  - Type: `URIProperty`

... and 30 more properties

---

#### KGFrame

- **Module**: `ai_haley_kg_domain.model.KGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
- **Properties**: 91

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFormType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFrameType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTypeMethodURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasParentFrameURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---


### Slot Classes

#### Edge_hasKGSlot

- **Module**: `ai_haley_kg_domain.model.Edge_hasKGSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot`
- **Properties**: 81

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasEdgeDestination`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeSource`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasListIndex`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefEdgeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotRoleSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotRoleType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeExternIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOfficeAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOriginDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley#hasOriginURI`
  - Short name: `None`
  - Type: `URIProperty`

... and 30 more properties

---

#### KGAudioSlot

- **Module**: `ai_haley_kg_domain.model.KGAudioSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGAudioSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasAudioSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGBooleanSlot

- **Module**: `ai_haley_kg_domain.model.KGBooleanSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGChoiceOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGChoiceOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGChoiceOptionSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasChoiceSlotOptionValues`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGChoiceSlot

- **Module**: `ai_haley_kg_domain.model.KGChoiceSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGChoiceSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasChoiceSlotValue`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGCodeSlot

- **Module**: `ai_haley_kg_domain.model.KGCodeSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGCodeSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasCodeSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGCurrencySlot

- **Module**: `ai_haley_kg_domain.model.KGCurrencySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGCurrencySlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasCurrencySlotValue`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGDateTimeSlot

- **Module**: `ai_haley_kg_domain.model.KGDateTimeSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasDateTimeSlotValue`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGDoubleSlot

- **Module**: `ai_haley_kg_domain.model.KGDoubleSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasDoubleSlotValue`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGFileUploadSlot

- **Module**: `ai_haley_kg_domain.model.KGFileUploadSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGFileUploadSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFileUploadSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGGeoLocationSlot

- **Module**: `ai_haley_kg_domain.model.KGGeoLocationSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue`
  - Short name: `None`
  - Type: `GeoLocationProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGImageSlot

- **Module**: `ai_haley_kg_domain.model.KGImageSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGImageSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasImageSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGIntegerSlot

- **Module**: `ai_haley_kg_domain.model.KGIntegerSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGJSONSlot

- **Module**: `ai_haley_kg_domain.model.KGJSONSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGJSONSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasJsonSlotValue`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGLongSlot

- **Module**: `ai_haley_kg_domain.model.KGLongSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGLongSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasLongSlotValue`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGLongTextSlot

- **Module**: `ai_haley_kg_domain.model.KGLongTextSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGLongTextSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasLongTextSlotValue`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGMultiChoiceOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGMultiChoiceOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiChoiceOptionSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasMultiChoiceSlotValues`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGMultiChoiceSlot

- **Module**: `ai_haley_kg_domain.model.KGMultiChoiceSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiChoiceSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasMultiChoiceSlotValues`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGMultiTaxonomyOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGMultiTaxonomyOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiTaxonomyOptionSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTaxonomyOptionURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGMultiTaxonomySlot

- **Module**: `ai_haley_kg_domain.model.KGMultiTaxonomySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiTaxonomySlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasMultiTaxonomySlotValues`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGPropertySlot

- **Module**: `ai_haley_kg_domain.model.KGPropertySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGPropertySlot`
- **Properties**: 95

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPropertyGroupNameSlotValue`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPropertyNameSlotValue`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasPropertyFrameTypeSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasPropertySlotTypeSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGRunSlot

- **Module**: `ai_haley_kg_domain.model.KGRunSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGRunSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasRunSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGSlot

- **Module**: `ai_haley_kg_domain.model.KGSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGSlot`
- **Properties**: 91

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGTaxonomyOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGTaxonomyOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTaxonomyOptionSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTaxonomyOptionURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGTaxonomySlot

- **Module**: `ai_haley_kg_domain.model.KGTaxonomySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTaxonomySlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasTaxonomySlotValue`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGTextSlot

- **Module**: `ai_haley_kg_domain.model.KGTextSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTextSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGURISlot

- **Module**: `ai_haley_kg_domain.model.KGURISlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGURISlot`
- **Properties**: 91

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---

#### KGVideoSlot

- **Module**: `ai_haley_kg_domain.model.KGVideoSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGVideoSlot`
- **Properties**: 92

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasVideoSlotValue`
  - Short name: `None`
  - Type: `URIProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

... and 34 more properties

---


### Edge Classes

#### Edge_hasKGEdge

- **Module**: `ai_haley_kg_domain.model.Edge_hasKGEdge`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGEdge`
- **Properties**: 77

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#hasEdgeDestination`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeSource`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasListIndex`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Short name: `None`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefEdgeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Short name: `None`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Short name: `None`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Short name: `None`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Short name: `None`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Short name: `None`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOfficeAccessURIs`
  - Short name: `None`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOriginDateTime`
  - Short name: `None`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley#hasOriginURI`
  - Short name: `None`
  - Type: `URIProperty`

... and 30 more properties

---


## Summary

- **Total Classes Documented**: 33
- **Entity Classes**: 2
- **Frame Classes**: 2
- **Slot Classes**: 28
- **Edge Classes**: 1

This documentation was generated automatically using VitalSigns property discovery.
