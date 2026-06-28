# VitalGraph Knowledge Graph Data Model
## Fuseki-PostgreSQL Hybrid Backend

### Overview
This document defines the data model for VitalGraph's Knowledge Graph classes, specifically focusing on KGEntities, KGFrames, KGSlots, and KGRelations. This information is critical for understanding the RDF quad structure, SPARQL query patterns, and PostgreSQL storage requirements.

## Core KG Class Hierarchy

### Entity Classes

#### KGEntity
- **Module**: `ai_haley_kg_domain.model.KGEntity`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGEntity`
- **Properties**: 88 total properties
- **Description**: Root entity class for all knowledge graph entities

**Key Properties for Quads/SPARQL:**

**Vital Core Properties:**
- `http://vital.ai/ontology/vital-core#hasName` (StringProperty)
- `http://vital.ai/ontology/vital-core#hasProvenance` (URIProperty)
- `http://vital.ai/ontology/vital-core#hasTimestamp` (IntegerProperty)
- `http://vital.ai/ontology/vital-core#hasUpdateTime` (IntegerProperty)
- `http://vital.ai/ontology/vital-core#isActive` (BooleanProperty)
- `http://vital.ai/ontology/vital-core#vitaltype` (URIProperty)

**Critical KG Properties:**
- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityType` (URIProperty) - Entity classification
- `http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription` (StringProperty) - Human-readable type description
- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI` (URIProperty) - **GROUPING URI** for entity-level graph retrieval
- `http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier` (StringProperty) - Unique identifier within domain
- `http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion` (StringProperty) - Model version tracking
- `http://vital.ai/ontology/haley-ai-kg#hasKGVersion` (StringProperty) - Entity version
- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription` (StringProperty) - Entity description

**SPARQL Query Patterns:**
```sparql
# Find entities by type
SELECT ?entity WHERE {
    ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> ;
            <http://vital.ai/ontology/haley-ai-kg#hasKGEntityType> ?entityType .
    FILTER(?entityType = <target_entity_type_uri>)
}

# Get complete entity graph using grouping URI
SELECT ?s ?p ?o WHERE {
    ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <entity_uri> ;
       ?p ?o .
}
```

#### KGEntitySlot
- **Module**: `ai_haley_kg_domain.model.KGEntitySlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGEntitySlot`
- **Properties**: 92 total properties
- **Description**: Slot directly attached to entities (not through frames)

**Key Slot Properties:**
- `http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue` (URIProperty) - Reference to slot value
- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType` (URIProperty) - Slot type classification
- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotValueType` (URIProperty) - Value type (String, Integer, etc.)
- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotConstraintType` (URIProperty) - Validation constraints
- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI` (URIProperty) - Frame-level grouping URI

### Frame Classes

#### KGFrame
- **Module**: `ai_haley_kg_domain.model.KGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
- **Properties**: 91 total properties
- **Description**: Structured data container linked to entities

**Critical Frame Properties:**
- `http://vital.ai/ontology/haley-ai-kg#hasKGFrameType` (URIProperty) - Frame type classification
- `http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription` (StringProperty) - Human-readable frame type
- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI` (URIProperty) - **FRAME-LEVEL GROUPING URI**
- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI` (URIProperty) - **ENTITY-LEVEL GROUPING URI**
- `http://vital.ai/ontology/haley-ai-kg#hasFrameSequence` (IntegerProperty) - Ordering within entity
- `http://vital.ai/ontology/haley-ai-kg#hasParentFrameURI` (URIProperty) - Hierarchical frame relationships

**SPARQL Query Patterns:**
```sparql
# Get frames for specific entity
SELECT ?frame WHERE {
    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> ;
          <http://vital.ai/ontology/vital-core#hasEdgeSource> <entity_uri> ;
          <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?frame .
}

# Get complete frame graph using frame-level grouping
SELECT ?s ?p ?o WHERE {
    ?s <http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI> <frame_uri> ;
       ?p ?o .
}
```

#### Edge_hasKGFrame
- **Module**: `ai_haley_kg_domain.model.Edge_hasKGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame`
- **Properties**: 78 total properties
- **Description**: Frame-to-frame hierarchical relationships

**Key Edge Properties:**
- `http://vital.ai/ontology/vital-core#hasEdgeSource` (URIProperty) - Source frame URI
- `http://vital.ai/ontology/vital-core#hasEdgeDestination` (URIProperty) - Destination frame URI
- `http://vital.ai/ontology/haley-ai-kg#hasEdgeName` (StringProperty) - Relationship name
- `http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI` (URIProperty) - Frame-level grouping
- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI` (URIProperty) - Entity-level grouping

### Slot Classes

#### KGTextSlot
- **Module**: `ai_haley_kg_domain.model.KGTextSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGTextSlot`
- **Properties**: 92 total properties
- **Description**: Text-based data slots

**Key Slot Value Properties:**
- `http://vital.ai/ontology/haley-ai-kg#textSlotValue` (StringProperty) - **PRIMARY VALUE PROPERTY**
- `http://vital.ai/ontology/haley-ai-kg#hasSlotSequence` (IntegerProperty) - Ordering within frame

#### KGIntegerSlot
- **Module**: `ai_haley_kg_domain.model.KGIntegerSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot`
- **Properties**: 92 total properties
- **Description**: Integer-based data slots

**Key Slot Value Properties:**
- `http://vital.ai/ontology/haley-ai-kg#integerSlotValue` (IntegerProperty) - **PRIMARY VALUE PROPERTY**

#### KGDateTimeSlot
- **Module**: `ai_haley_kg_domain.model.KGDateTimeSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot`
- **Properties**: 92 total properties
- **Description**: DateTime-based data slots

**Key Slot Value Properties:**
- `http://vital.ai/ontology/haley-ai-kg#dateTimeSlotValue` (DateTimeProperty) - **PRIMARY VALUE PROPERTY**

#### KGBooleanSlot
- **Module**: `ai_haley_kg_domain.model.KGBooleanSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot`
- **Properties**: 92 total properties
- **Description**: Boolean-based data slots

**Key Slot Value Properties:**
- `http://vital.ai/ontology/haley-ai-kg#booleanSlotValue` (BooleanProperty) - **PRIMARY VALUE PROPERTY**

#### KGDoubleSlot
- **Module**: `ai_haley_kg_domain.model.KGDoubleSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot`
- **Properties**: 92 total properties
- **Description**: Double/Float-based data slots

**Key Slot Value Properties:**
- `http://vital.ai/ontology/haley-ai-kg#doubleSlotValue` (DoubleProperty) - **PRIMARY VALUE PROPERTY**

#### Edge_hasKGSlot
- **Module**: `ai_haley_kg_domain.model.Edge_hasKGSlot`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot`
- **Properties**: 81 total properties
- **Description**: Frame-to-slot relationships

**Key Edge Properties:**
- `http://vital.ai/ontology/vital-core#hasEdgeSource` (URIProperty) - Source frame URI
- `http://vital.ai/ontology/vital-core#hasEdgeDestination` (URIProperty) - Destination slot URI
- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotRoleType` (URIProperty) - Slot role classification
- `http://vital.ai/ontology/haley-ai-kg#hasKGSlotRoleSequence` (IntegerProperty) - Slot ordering

### Relationship Classes

#### Edge_hasEntityKGFrame
- **Module**: `ai_haley_kg_domain.model.Edge_hasEntityKGFrame`
- **VitalType**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame`
- **Properties**: Similar to other edge classes
- **Description**: Entity-to-frame relationships

**Key Edge Properties:**
- `http://vital.ai/ontology/vital-core#hasEdgeSource` (URIProperty) - Source entity URI
- `http://vital.ai/ontology/vital-core#hasEdgeDestination` (URIProperty) - Destination frame URI
- `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI` (URIProperty) - Entity-level grouping

## Data Model Architecture

### Hierarchical Structure
```
KGEntity (Root)
├── hasKGGraphURI: entity_uri (entity-level grouping)
├── Connected to KGFrames via Edge_hasEntityKGFrame
│
KGFrame (Child of Entity)
├── hasKGGraphURI: entity_uri (entity-level grouping)
├── hasFrameGraphURI: frame_uri (frame-level grouping)
├── Connected to KGSlots via Edge_hasKGSlot
├── Connected to other KGFrames via Edge_hasKGFrame (hierarchical)
│
KGSlot (Child of Frame)
├── hasKGGraphURI: entity_uri (entity-level grouping)
├── hasFrameGraphURI: frame_uri (frame-level grouping)
├── Contains actual data values (textSlotValue, integerSlotValue, etc.)
│
Connecting Edges:
├── Edge_hasEntityKGFrame (Entity → Frame)
├── Edge_hasKGSlot (Frame → Slot)
├── Edge_hasKGFrame (Frame → Frame, hierarchical)
└── All edges have hasKGGraphURI for entity-level grouping
```

### Grouping URI Strategy

#### Entity-Level Grouping (`hasKGGraphURI`)
- **Purpose**: Fast retrieval of complete entity graphs
- **Applied to**: All objects related to an entity (entity, frames, slots, edges)
- **Value**: The entity's URI
- **Usage**: `include_entity_graph=True` operations

#### Frame-Level Grouping (`hasFrameGraphURI`)
- **Purpose**: Fast retrieval of complete frame graphs
- **Applied to**: Frame and its slots, plus connecting edges
- **Value**: The frame's URI
- **Usage**: `include_frame_graph=True` operations

## Backend Storage Implications

For PostgreSQL quad storage, term types, indexes, and performance optimization details, see `endpoints/fuseki_psql_backend_plan.md`.

## SPARQL Query Optimization Patterns

### Entity Graph Retrieval
```sparql
# Optimized entity graph query using grouping URI
SELECT ?s ?p ?o WHERE {
    ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <entity_uri> ;
       ?p ?o .
}
```

### Frame Graph Retrieval
```sparql
# Optimized frame graph query using frame grouping URI
SELECT ?s ?p ?o WHERE {
    ?s <http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI> <frame_uri> ;
       ?p ?o .
}
```

### Slot Value Filtering
```sparql
# Efficient slot value queries
SELECT ?entity ?slot ?value WHERE {
    ?entity <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> ?entityGraphURI .
    ?slot <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> ?entityGraphURI ;
          <http://vital.ai/ontology/haley-ai-kg#textSlotValue> ?value .
    FILTER(CONTAINS(?value, "search_term"))
}
```

## VitalSigns Integration Notes

### Property Access Patterns
- **Short Names**: Some properties may have short name aliases (e.g., `kGGraphURI` for `hasKGGraphURI`)
- **Type Safety**: VitalSigns provides compile-time type checking for property access
- **JSON-LD Conversion**: Native support for converting to/from JSON-LD format

### Grouping URI Assignment
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

This data model provides the foundation for VitalSigns integration and SPARQL query patterns. For backend storage implementation details, see `endpoints/fuseki_psql_backend_plan.md`.