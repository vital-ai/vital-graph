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
- **Properties**: 94

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityAccountURI`
  - Local name: `hasKGEntityAccountURI`
  - Short name: `kGEntityAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityLoginURI`
  - Local name: `hasKGEntityLoginURI`
  - Short name: `kGEntityLoginURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityType`
  - Local name: `hasKGEntityType`
  - Short name: `kGEntityType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription`
  - Local name: `hasKGEntityTypeDescription`
  - Short name: `kGEntityTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFormType`
  - Local name: `hasKGFormType`
  - Short name: `kGFormType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType`
  - Local name: `hasKGProvenanceType`
  - Short name: `kGProvenanceType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTypeMethodURI`
  - Local name: `hasKGTypeMethodURI`
  - Short name: `kGTypeMethodURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGEntitySlot

- **Module**: `ai_haley_kg_domain.model.KGEntitySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGEntitySlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue`
  - Local name: `hasEntitySlotValue`
  - Short name: `entitySlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---


### Frame Classes

#### Edge_hasKGFrame

- **Module**: `ai_haley_kg_domain.model.Edge_hasKGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame`
- **Properties**: 84

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeDestination`
  - Local name: `hasEdgeDestination`
  - Short name: `edgeDestination`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeSource`
  - Local name: `hasEdgeSource`
  - Short name: `edgeSource`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasListIndex`
  - Local name: `hasListIndex`
  - Short name: `listIndex`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName`
  - Local name: `hasEdgeName`
  - Short name: `edgeName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefEdgeURI`
  - Local name: `hasKGRefEdgeURI`
  - Short name: `kGRefEdgeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasDestinationReferenceClass`
  - Local name: `hasDestinationReferenceClass`
  - Short name: `destinationReferenceClass`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasDestinationReferenceIdentifier`
  - Local name: `hasDestinationReferenceIdentifier`
  - Short name: `destinationReferenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSourceReferenceClass`
  - Local name: `hasSourceReferenceClass`
  - Short name: `sourceReferenceClass`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSourceReferenceIdentifier`
  - Local name: `hasSourceReferenceIdentifier`
  - Short name: `sourceReferenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOfficeAccessURIs`
  - Local name: `hasOfficeAccessURIs`
  - Short name: `officeAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOriginDateTime`
  - Local name: `hasOriginDateTime`
  - Short name: `originDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley#hasOriginURI`
  - Local name: `hasOriginURI`
  - Short name: `originURI`
  - Type: `URIProperty`

... and 14 more properties

---

#### KGFrame

- **Module**: `ai_haley_kg_domain.model.KGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
- **Properties**: 97

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameSequence`
  - Local name: `hasFrameSequence`
  - Short name: `frameSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFormType`
  - Local name: `hasKGFormType`
  - Short name: `kGFormType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFrameType`
  - Local name: `hasKGFrameType`
  - Short name: `kGFrameType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription`
  - Local name: `hasKGFrameTypeDescription`
  - Short name: `kGFrameTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType`
  - Local name: `hasKGProvenanceType`
  - Short name: `kGProvenanceType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTypeMethodURI`
  - Local name: `hasKGTypeMethodURI`
  - Short name: `kGTypeMethodURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasParentFrameURI`
  - Local name: `hasParentFrameURI`
  - Short name: `parentFrameURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---


### Slot Classes

#### Edge_hasKGSlot

- **Module**: `ai_haley_kg_domain.model.Edge_hasKGSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot`
- **Properties**: 87

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeDestination`
  - Local name: `hasEdgeDestination`
  - Short name: `edgeDestination`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeSource`
  - Local name: `hasEdgeSource`
  - Short name: `edgeSource`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasListIndex`
  - Local name: `hasListIndex`
  - Short name: `listIndex`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName`
  - Local name: `hasEdgeName`
  - Short name: `edgeName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefEdgeURI`
  - Local name: `hasKGRefEdgeURI`
  - Short name: `kGRefEdgeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotRoleSequence`
  - Local name: `hasKGSlotRoleSequence`
  - Short name: `kGSlotRoleSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotRoleType`
  - Local name: `hasKGSlotRoleType`
  - Short name: `kGSlotRoleType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeExternIdentifier`
  - Local name: `hasKGSlotTypeExternIdentifier`
  - Short name: `kGSlotTypeExternIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasDestinationReferenceClass`
  - Local name: `hasDestinationReferenceClass`
  - Short name: `destinationReferenceClass`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasDestinationReferenceIdentifier`
  - Local name: `hasDestinationReferenceIdentifier`
  - Short name: `destinationReferenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSourceReferenceClass`
  - Local name: `hasSourceReferenceClass`
  - Short name: `sourceReferenceClass`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSourceReferenceIdentifier`
  - Local name: `hasSourceReferenceIdentifier`
  - Short name: `sourceReferenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOfficeAccessURIs`
  - Local name: `hasOfficeAccessURIs`
  - Short name: `officeAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOriginDateTime`
  - Local name: `hasOriginDateTime`
  - Short name: `originDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley#hasOriginURI`
  - Local name: `hasOriginURI`
  - Short name: `originURI`
  - Type: `URIProperty`

... and 14 more properties

---

#### KGAudioSlot

- **Module**: `ai_haley_kg_domain.model.KGAudioSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGAudioSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasAudioSlotValue`
  - Local name: `hasAudioSlotValue`
  - Short name: `audioSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGBooleanSlot

- **Module**: `ai_haley_kg_domain.model.KGBooleanSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue`
  - Local name: `hasBooleanSlotValue`
  - Short name: `booleanSlotValue`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGChoiceOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGChoiceOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGChoiceOptionSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasChoiceSlotOptionValues`
  - Local name: `hasChoiceSlotOptionValues`
  - Short name: `choiceSlotOptionValues`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGChoiceSlot

- **Module**: `ai_haley_kg_domain.model.KGChoiceSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGChoiceSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasChoiceSlotValue`
  - Local name: `hasChoiceSlotValue`
  - Short name: `choiceSlotValue`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGCodeSlot

- **Module**: `ai_haley_kg_domain.model.KGCodeSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGCodeSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasCodeSlotValue`
  - Local name: `hasCodeSlotValue`
  - Short name: `codeSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGCurrencySlot

- **Module**: `ai_haley_kg_domain.model.KGCurrencySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGCurrencySlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasCurrencySlotValue`
  - Local name: `hasCurrencySlotValue`
  - Short name: `currencySlotValue`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGDateTimeSlot

- **Module**: `ai_haley_kg_domain.model.KGDateTimeSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasDateTimeSlotValue`
  - Local name: `hasDateTimeSlotValue`
  - Short name: `dateTimeSlotValue`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGDoubleSlot

- **Module**: `ai_haley_kg_domain.model.KGDoubleSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasDoubleSlotValue`
  - Local name: `hasDoubleSlotValue`
  - Short name: `doubleSlotValue`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGFileUploadSlot

- **Module**: `ai_haley_kg_domain.model.KGFileUploadSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGFileUploadSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFileUploadSlotValue`
  - Local name: `hasFileUploadSlotValue`
  - Short name: `fileUploadSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGGeoLocationSlot

- **Module**: `ai_haley_kg_domain.model.KGGeoLocationSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue`
  - Local name: `hasGeoLocationSlotValue`
  - Short name: `geoLocationSlotValue`
  - Type: `GeoLocationProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGImageSlot

- **Module**: `ai_haley_kg_domain.model.KGImageSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGImageSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasImageSlotValue`
  - Local name: `hasImageSlotValue`
  - Short name: `imageSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGIntegerSlot

- **Module**: `ai_haley_kg_domain.model.KGIntegerSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue`
  - Local name: `hasIntegerSlotValue`
  - Short name: `integerSlotValue`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGJSONSlot

- **Module**: `ai_haley_kg_domain.model.KGJSONSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGJSONSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasJsonSlotValue`
  - Local name: `hasJsonSlotValue`
  - Short name: `jsonSlotValue`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGLongSlot

- **Module**: `ai_haley_kg_domain.model.KGLongSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGLongSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasLongSlotValue`
  - Local name: `hasLongSlotValue`
  - Short name: `longSlotValue`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGLongTextSlot

- **Module**: `ai_haley_kg_domain.model.KGLongTextSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGLongTextSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasLongTextSlotValue`
  - Local name: `hasLongTextSlotValue`
  - Short name: `longTextSlotValue`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGMultiChoiceOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGMultiChoiceOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiChoiceOptionSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasMultiChoiceSlotValues`
  - Local name: `hasMultiChoiceSlotValues`
  - Short name: `multiChoiceSlotValues`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGMultiChoiceSlot

- **Module**: `ai_haley_kg_domain.model.KGMultiChoiceSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiChoiceSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasMultiChoiceSlotValues`
  - Local name: `hasMultiChoiceSlotValues`
  - Short name: `multiChoiceSlotValues`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGMultiTaxonomyOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGMultiTaxonomyOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiTaxonomyOptionSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTaxonomyOptionURI`
  - Local name: `hasKGTaxonomyOptionURI`
  - Short name: `kGTaxonomyOptionURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGMultiTaxonomySlot

- **Module**: `ai_haley_kg_domain.model.KGMultiTaxonomySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGMultiTaxonomySlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasMultiTaxonomySlotValues`
  - Local name: `hasMultiTaxonomySlotValues`
  - Short name: `multiTaxonomySlotValues`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGPropertySlot

- **Module**: `ai_haley_kg_domain.model.KGPropertySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGPropertySlot`
- **Properties**: 102

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPropertyGroupNameSlotValue`
  - Local name: `hasKGPropertyGroupNameSlotValue`
  - Short name: `kGPropertyGroupNameSlotValue`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPropertyNameSlotValue`
  - Local name: `hasKGPropertyNameSlotValue`
  - Short name: `kGPropertyNameSlotValue`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasPropertyClassSlotValue`
  - Local name: `hasPropertyClassSlotValue`
  - Short name: `propertyClassSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasPropertyFrameTypeSlotValue`
  - Local name: `hasPropertyFrameTypeSlotValue`
  - Short name: `propertyFrameTypeSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasPropertySlotTypeSlotValue`
  - Local name: `hasPropertySlotTypeSlotValue`
  - Short name: `propertySlotTypeSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGRunSlot

- **Module**: `ai_haley_kg_domain.model.KGRunSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGRunSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasRunSlotValue`
  - Local name: `hasRunSlotValue`
  - Short name: `runSlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGSlot

- **Module**: `ai_haley_kg_domain.model.KGSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGSlot`
- **Properties**: 97

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGTaxonomyOptionSlot

- **Module**: `ai_haley_kg_domain.model.KGTaxonomyOptionSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTaxonomyOptionSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTaxonomyOptionURI`
  - Local name: `hasKGTaxonomyOptionURI`
  - Short name: `kGTaxonomyOptionURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGTaxonomySlot

- **Module**: `ai_haley_kg_domain.model.KGTaxonomySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTaxonomySlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasTaxonomySlotValue`
  - Local name: `hasTaxonomySlotValue`
  - Short name: `taxonomySlotValue`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGTextSlot

- **Module**: `ai_haley_kg_domain.model.KGTextSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTextSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue`
  - Local name: `hasTextSlotValue`
  - Short name: `textSlotValue`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGURISlot

- **Module**: `ai_haley_kg_domain.model.KGURISlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGURISlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUriSlotValue`
  - Local name: `hasUriSlotValue`
  - Short name: `uriSlotValue`
  - Type: `URIProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---

#### KGVideoSlot

- **Module**: `ai_haley_kg_domain.model.KGVideoSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGVideoSlot`
- **Properties**: 98

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI`
  - Local name: `hasFrameGraphURI`
  - Short name: `frameGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList`
  - Local name: `hasKGActionTypeList`
  - Short name: `kGActionTypeList`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeSummaryDateTime`
  - Local name: `hasKGActionTypeSummaryDateTime`
  - Short name: `kGActionTypeSummaryDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGBeliefModeType`
  - Local name: `hasKGBeliefModeType`
  - Short name: `kGBeliefModeType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGExpressionType`
  - Local name: `hasKGExpressionType`
  - Short name: `kGExpressionType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime`
  - Local name: `hasKGNodeCacheDateTime`
  - Short name: `kGNodeCacheDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGParticipationType`
  - Local name: `hasKGParticipationType`
  - Short name: `kGParticipationType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefURI`
  - Local name: `hasKGRefURI`
  - Short name: `kGRefURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGReferentURI`
  - Local name: `hasKGReferentURI`
  - Short name: `kGReferentURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType`
  - Local name: `hasKGSlotConstraintType`
  - Short name: `kGSlotConstraintType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotReferenceURI`
  - Local name: `hasKGSlotReferenceURI`
  - Short name: `kGSlotReferenceURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType`
  - Local name: `hasKGSlotType`
  - Short name: `kGSlotType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription`
  - Local name: `hasKGSlotTypeDescription`
  - Short name: `kGSlotTypeDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType`
  - Local name: `hasKGSlotValueType`
  - Short name: `kGSlotValueType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence`
  - Local name: `hasSlotSequence`
  - Short name: `slotSequence`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasVideoSlotValue`
  - Local name: `hasVideoSlotValue`
  - Short name: `videoSlotValue`
  - Type: `URIProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedContent`
  - Local name: `hasAnalyzedContent`
  - Short name: `analyzedContent`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAnalyzedName`
  - Local name: `hasAnalyzedName`
  - Short name: `analyzedName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasKnowledgeGraphID`
  - Local name: `hasKnowledgeGraphID`
  - Short name: `knowledgeGraphID`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

... and 22 more properties

---


### Edge Classes

#### Edge_hasKGEdge

- **Module**: `ai_haley_kg_domain.model.Edge_hasKGEdge`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGEdge`
- **Properties**: 83

**Available Properties:**

**Vital Core Properties:**

- `http://vital.ai/ontology/vital-core#URIProp`
  - Local name: `URIProp`
  - Short name: `uRIProp`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeDestination`
  - Local name: `hasEdgeDestination`
  - Short name: `edgeDestination`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasEdgeSource`
  - Local name: `hasEdgeSource`
  - Short name: `edgeSource`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasListIndex`
  - Local name: `hasListIndex`
  - Short name: `listIndex`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasName`
  - Local name: `hasName`
  - Short name: `name`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#hasOntologyIRI`
  - Local name: `hasOntologyIRI`
  - Short name: `ontologyIRI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasProvenance`
  - Local name: `hasProvenance`
  - Short name: `provenance`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#hasTimestamp`
  - Local name: `hasTimestamp`
  - Short name: `timestamp`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasUpdateTime`
  - Local name: `hasUpdateTime`
  - Short name: `updateTime`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/vital-core#hasVersionIRI`
  - Local name: `hasVersionIRI`
  - Short name: `versionIRI`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-core#isActive`
  - Local name: `isActive`
  - Short name: `active`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/vital-core#types`
  - Local name: `types`
  - Short name: `types`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-core#vitaltype`
  - Local name: `vitaltype`
  - Short name: `vitaltype`
  - Type: `URIProperty`

**Haley KG Properties:**

- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName`
  - Local name: `hasEdgeName`
  - Short name: `edgeName`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGChatInteractionGraphURI`
  - Local name: `hasKGChatInteractionGraphURI`
  - Short name: `kGChatInteractionGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGDataHash`
  - Local name: `hasKGDataHash`
  - Short name: `kGDataHash`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime`
  - Local name: `hasKGGraphAssertionDateTime`
  - Short name: `kGGraphAssertionDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`
  - Local name: `hasKGGraphURI`
  - Short name: `kGGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier`
  - Local name: `hasKGIdentifier`
  - Short name: `kGIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime`
  - Local name: `hasKGIndexDateTime`
  - Short name: `kGIndexDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGIndexStatusURI`
  - Local name: `hasKGIndexStatusURI`
  - Short name: `kGIndexStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGJSON`
  - Local name: `hasKGJSON`
  - Short name: `kGJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion`
  - Local name: `hasKGModelVersion`
  - Short name: `kGModelVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGPurgeUpdateTime`
  - Local name: `hasKGPurgeUpdateTime`
  - Short name: `kGPurgeUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGRefEdgeURI`
  - Local name: `hasKGRefEdgeURI`
  - Short name: `kGRefEdgeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncStatusURI`
  - Local name: `hasKGSyncStatusURI`
  - Short name: `kGSyncStatusURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncTypeURI`
  - Local name: `hasKGSyncTypeURI`
  - Short name: `kGSyncTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGSyncUpdateTime`
  - Local name: `hasKGSyncUpdateTime`
  - Short name: `kGSyncUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGTenantIdentifier`
  - Local name: `hasKGTenantIdentifier`
  - Short name: `kGTenantIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGValidTypeURI`
  - Local name: `hasKGValidTypeURI`
  - Short name: `kGValidTypeURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion`
  - Local name: `hasKGVersion`
  - Short name: `kGVersion`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGVisualStyleJSON`
  - Local name: `hasKGVisualStyleJSON`
  - Short name: `kGVisualStyleJSON`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
  - Local name: `hasKGraphDescription`
  - Short name: `kGraphDescription`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainBooleanProperty`
  - Local name: `hasUnionDomainBooleanProperty`
  - Short name: `unionDomainBooleanProperty`
  - Type: `BooleanProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDateTimeProperty`
  - Local name: `hasUnionDomainDateTimeProperty`
  - Short name: `unionDomainDateTimeProperty`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainDoubleProperty`
  - Local name: `hasUnionDomainDoubleProperty`
  - Short name: `unionDomainDoubleProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainFloatProperty`
  - Local name: `hasUnionDomainFloatProperty`
  - Short name: `unionDomainFloatProperty`
  - Type: `DoubleProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainIntegerProperty`
  - Local name: `hasUnionDomainIntegerProperty`
  - Short name: `unionDomainIntegerProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainLongProperty`
  - Local name: `hasUnionDomainLongProperty`
  - Short name: `unionDomainLongProperty`
  - Type: `IntegerProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainObjectProperty`
  - Local name: `hasUnionDomainObjectProperty`
  - Short name: `unionDomainObjectProperty`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley-ai-kg#hasUnionDomainStringProperty`
  - Local name: `hasUnionDomainStringProperty`
  - Short name: `unionDomainStringProperty`
  - Type: `StringProperty`

**Vital AIMP Properties:**

- `http://vital.ai/ontology/vital-aimp#hasAIMPGraphURI`
  - Local name: `hasAIMPGraphURI`
  - Short name: `aIMPGraphURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAccountURIs`
  - Local name: `hasAccountURIs`
  - Short name: `accountURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessAccountURI`
  - Local name: `hasAgentAccessAccountURI`
  - Short name: `agentAccessAccountURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentAccessURI`
  - Local name: `hasAgentAccessURI`
  - Short name: `agentAccessURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGenerationDateTime`
  - Local name: `hasAgentGenerationDateTime`
  - Short name: `agentGenerationDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasAgentGeneratorURI`
  - Local name: `hasAgentGeneratorURI`
  - Short name: `agentGeneratorURI`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasBotCreatorIdentifier`
  - Local name: `hasBotCreatorIdentifier`
  - Short name: `botCreatorIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasDestinationReferenceClass`
  - Local name: `hasDestinationReferenceClass`
  - Short name: `destinationReferenceClass`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasDestinationReferenceIdentifier`
  - Local name: `hasDestinationReferenceIdentifier`
  - Short name: `destinationReferenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasGraphLabelURIs`
  - Local name: `hasGraphLabelURIs`
  - Short name: `graphLabelURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
  - Local name: `hasObjectCreationTime`
  - Short name: `objectCreationTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
  - Local name: `hasObjectStatusType`
  - Short name: `objectStatusType`
  - Type: `URIProperty`

- `http://vital.ai/ontology/vital-aimp#hasObjectUpdateTime`
  - Local name: `hasObjectUpdateTime`
  - Short name: `objectUpdateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`
  - Local name: `hasReferenceIdentifier`
  - Short name: `referenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSecurityProfile`
  - Local name: `hasSecurityProfile`
  - Short name: `securityProfile`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSourceReferenceClass`
  - Local name: `hasSourceReferenceClass`
  - Short name: `sourceReferenceClass`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasSourceReferenceIdentifier`
  - Local name: `hasSourceReferenceIdentifier`
  - Short name: `sourceReferenceIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/vital-aimp#hasUserCreatorIdentifier`
  - Local name: `hasUserCreatorIdentifier`
  - Short name: `userCreatorIdentifier`
  - Type: `StringProperty`

**Other Properties:**

- `http://vital.ai/ontology/chat-ai#hasVersionNonce`
  - Local name: `hasVersionNonce`
  - Short name: `versionNonce`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasAccountObjectAccessTypes`
  - Local name: `hasAccountObjectAccessTypes`
  - Short name: `accountObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasApplicationObjectAccessTypes`
  - Local name: `hasApplicationObjectAccessTypes`
  - Short name: `applicationObjectAccessTypes`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasDatasetAccessURIs`
  - Local name: `hasDatasetAccessURIs`
  - Short name: `datasetAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasGroupAccessURIs`
  - Local name: `hasGroupAccessURIs`
  - Short name: `groupAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasHaleyContextIdentifier`
  - Local name: `hasHaleyContextIdentifier`
  - Short name: `haleyContextIdentifier`
  - Type: `StringProperty`

- `http://vital.ai/ontology/haley#hasLoginAccessURIs`
  - Local name: `hasLoginAccessURIs`
  - Short name: `loginAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOfficeAccessURIs`
  - Local name: `hasOfficeAccessURIs`
  - Short name: `officeAccessURIs`
  - Type: `URIProperty`

- `http://vital.ai/ontology/haley#hasOriginDateTime`
  - Local name: `hasOriginDateTime`
  - Short name: `originDateTime`
  - Type: `DateTimeProperty`

- `http://vital.ai/ontology/haley#hasOriginURI`
  - Local name: `hasOriginURI`
  - Short name: `originURI`
  - Type: `URIProperty`

... and 14 more properties

---


## Summary

- **Total Classes Documented**: 33
- **Entity Classes**: 2
- **Frame Classes**: 2
- **Slot Classes**: 28
- **Edge Classes**: 1

This documentation was generated automatically using VitalSigns property discovery.
