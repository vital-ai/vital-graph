# KG Slot Value Properties Summary

This document provides a quick reference for the specific value properties available for each KGSlot subclass, as well as information about KGType and its subclasses for typing entities, frames, and slots.

## KGType and Type Classification

### Overview
KGType and its subclasses are used to classify and identify the specific types of entities, frames, and slots in the knowledge graph. Each KGEntity, KGFrame, and KGSlot uses a KGType URN to identify what kind of object it is.

**Key Focus Areas:** While KGType has many subclasses, we mainly focus on **entity types**, **frame types**, and **slot types** for core knowledge graph functionality.

### KGType Subclasses
KGType has the following subclasses:

**Core Entity, Frame, and Slot Types:**
- `KGEntityType` - Base type for entity classification
- `KGFrameType` - Base type for frame classification  
- `KGSlotType` - Base type for slot classification
- `KGSlotRoleType` - Role-based slot types

**Entity Types:**
- `KGActorType` - Actor entities (people, organizations acting in roles)
- `KGAgentType` - AI agents and automated systems
- `KGOrganizationType` - Organizations and companies
- `KGGroupType` - Groups and teams
- `KGTeamType` - Specific team structures
- `KGOfficeType` - Office and location entities
- `KGRoomType` - Room and space entities

**Frame and Relationship Types:**
- `KGRelationType` - Relationship frames
- `KGInteractionType` - Interaction and communication frames
- `KGChatInteractionType` - Chat-based interactions
- `KGEventType` - Event and temporal frames
- `KGCalendarEventType` - Calendar and scheduling events
- `KGTaskType` - Task and process frames
- `KGRequestType` - Request and inquiry frames
- `KGResponseType` - Response and reply frames

**Document and Content Types:**
- `KGDocumentType` - Base document classification
- `KGFileType` - File type classification
- `KGNoteDocumentType` - Note and annotation documents
- `KGCodeDocumentType` - Code and technical documents
- `KGRunDocumentType` - Execution and runtime documents
- `KGDocumentRepositoryType` - Document repository classification

**Communication and Message Types:**
- `KGChatMessageType` - Chat messages and communications
- `KGEMailType` - Email and electronic communications
- `KGChatInteractionEventType` - Chat interaction events

**Agent and Automation Types:**
- `KGAgentPublisherType` - Agent publishing systems
- `KGAgentSubmissionType` - Agent submission systems
- `KGToolType` - Tool and utility classification
- `KGToolRequestType` - Tool request handling
- `KGToolResultType` - Tool result processing

**Classification and Metadata Types:**
- `KGAnnotationType` - Annotations and markup
- `KGCategoryType` - Category classification
- `KGRelatedCategoryType` - Related category links
- `KGFlagType` - Flag and marker types
- `KGTagType` - Tag and label classification
- `KGRatingType` - Rating and evaluation types
- `KGRatingSummaryType` - Rating summary aggregation
- `KGStatsSummaryType` - Statistics summary types

**Resource and Search Types:**
- `KGResourceType` - Resource classification
- `KGSearchType` - Search and query types
- `KGInstructionType` - Instruction and guidance types

### Usage in Test Scripts
In test scripts, you typically use URN identifiers for types:

```python
# Entity with type
entity = KGEntity()
entity.URI = "http://vital.ai/haley.ai/app/KGEntity/person_001"
entity.name = "John Doe"
entity.kGEntityType = "urn:PersonEntityType"  # URN reference to type

# Frame with type
frame = KGFrame()
frame.URI = "http://vital.ai/haley.ai/app/KGFrame/employment_001"
frame.name = "Employment Relationship"
frame.kGFrameType = "urn:EmploymentRelationType"  # URN reference to type

# Slot with type
slot = KGTextSlot()
slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/name_001"
slot.name = "Name Slot"
slot.kGSlotType = "urn:NameSlotType"  # URN reference to type
slot.textSlotValue = "John Doe"
```

### Type Properties in KG Objects

Each KG object (Entity, Frame, Slot) has type-related properties:

**KGEntity Type Properties:**
- `kGEntityType` - URN reference to the entity's type (e.g., "urn:PersonEntityType")
- `kGEntityTypeDescription` - Human-readable description of the entity type

**KGFrame Type Properties:**
- `kGFrameType` - URN reference to the frame's type (e.g., "urn:EmploymentRelationType")
- `kGFrameTypeDescription` - Human-readable description of the frame type

**KGSlot Type Properties:**
- `kGSlotType` - URN reference to the slot's type (e.g., "urn:NameSlotType")
- `kGSlotTypeDescription` - Human-readable description of the slot type

### Complete Example with Types

```python
# Create a typed entity
person_entity = KGEntity()
person_entity.URI = "http://vital.ai/haley.ai/app/KGEntity/john_doe"
person_entity.name = "John Doe"
person_entity.kGEntityType = "urn:PersonEntityType"
person_entity.kGEntityTypeDescription = "Person Entity"

# Create a typed frame for employment relationship
employment_frame = KGFrame()
employment_frame.URI = "http://vital.ai/haley.ai/app/KGFrame/employment_001"
employment_frame.name = "Employment Relationship"
employment_frame.kGFrameType = "urn:EmploymentRelationType"
employment_frame.kGFrameTypeDescription = "Employment Relationship"

# Create typed slots for the frame
name_slot = KGTextSlot()
name_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/employee_name"
name_slot.name = "Employee Name"
name_slot.kGSlotType = "urn:EmployeeNameSlotType"
name_slot.kGSlotTypeDescription = "Employee Name Slot"
name_slot.textSlotValue = "John Doe"
```

### KGTypes REST Endpoint
The KGTypes REST endpoint handles:
- **Adding** new type definitions
- **Removing** existing types
- **Searching** and querying available types
- **Managing** type hierarchies and relationships

## KGSlot Subclasses and Their Value Properties

| Slot Class | Short Property Name | Property Type | Full URI |
|------------|---------------------|---------------|----------|
| KGAudioSlot | `audioSlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasAudioSlotValue` |
| KGBooleanSlot | `booleanSlotValue` | BooleanProperty | `http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue` |
| KGChoiceSlot | `choiceSlotValue` | StringProperty | `http://vital.ai/ontology/haley-ai-kg#hasChoiceSlotValue` |
| KGCodeSlot | `codeSlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasCodeSlotValue` |
| KGCurrencySlot | `currencySlotValue` | DoubleProperty | `http://vital.ai/ontology/haley-ai-kg#hasCurrencySlotValue` |
| KGDateTimeSlot | `dateTimeSlotValue` | DateTimeProperty | `http://vital.ai/ontology/haley-ai-kg#hasDateTimeSlotValue` |
| KGDoubleSlot | `doubleSlotValue` | DoubleProperty | `http://vital.ai/ontology/haley-ai-kg#hasDoubleSlotValue` |
| KGEntitySlot | `entitySlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue` |
| KGFileUploadSlot | `fileUploadSlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasFileUploadSlotValue` |
| KGGeoLocationSlot | `geoLocationSlotValue` | GeoLocationProperty | `http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue` |
| KGImageSlot | `imageSlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasImageSlotValue` |
| KGIntegerSlot | `integerSlotValue` | IntegerProperty | `http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue` |
| KGJSONSlot | `jsonSlotValue` | StringProperty | `http://vital.ai/ontology/haley-ai-kg#hasJsonSlotValue` |
| KGLongSlot | `longSlotValue` | IntegerProperty | `http://vital.ai/ontology/haley-ai-kg#hasLongSlotValue` |
| KGLongTextSlot | `longTextSlotValue` | StringProperty | `http://vital.ai/ontology/haley-ai-kg#hasLongTextSlotValue` |
| KGMultiChoiceSlot | `multiChoiceSlotValues` | StringProperty | `http://vital.ai/ontology/haley-ai-kg#hasMultiChoiceSlotValues` |
| KGMultiTaxonomySlot | `multiTaxonomySlotValues` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasMultiTaxonomySlotValues` |
| KGRunSlot | `runSlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasRunSlotValue` |
| KGTaxonomySlot | `taxonomySlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasTaxonomySlotValue` |
| KGTextSlot | `textSlotValue` | StringProperty | `http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue` |
| KGVideoSlot | `videoSlotValue` | URIProperty | `http://vital.ai/ontology/haley-ai-kg#hasVideoSlotValue` |

## Example JSON-LD Usage

### KGTextSlot Example
```json
{
    "@context": {
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "vital": "http://vital.ai/ontology/vital-core#"
    },
    "@id": "http://example.org/text-slot1",
    "@type": "haley:KGTextSlot",
    "vital:hasName": "User Input Slot",
    "haley:hasTextSlotValue": "Hello World",
    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
}
```

### KGIntegerSlot Example
```json
{
    "@context": {
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "vital": "http://vital.ai/ontology/vital-core#"
    },
    "@id": "http://example.org/integer-slot1",
    "@type": "haley:KGIntegerSlot",
    "vital:hasName": "Age Slot",
    "haley:hasIntegerSlotValue": 25,
    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot"
}
```

### KGBooleanSlot Example
```json
{
    "@context": {
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "vital": "http://vital.ai/ontology/vital-core#"
    },
    "@id": "http://example.org/boolean-slot1",
    "@type": "haley:KGBooleanSlot",
    "vital:hasName": "Is Active Slot",
    "haley:hasBooleanSlotValue": true,
    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot"
}
```

### Working with VitalSigns Objects (Python Code)

After creating objects from JSON-LD, use direct property access:

```python
# Create objects from JSON-LD
objects = vitalsigns.from_jsonld_list(jsonld_document)

# Find the text slot
text_slot = None
for obj in objects:
    if isinstance(obj, KGTextSlot):
        text_slot = obj
        break

if text_slot:
    # Get the current value using direct property access
    current_value = text_slot.textSlotValue  # Returns "Hello World"
    
    # Set a new value
    text_slot.textSlotValue = "Updated Text"
    
    # Access other properties
    slot_name = text_slot.hasName  # Returns "User Input Slot"
    slot_uri = text_slot.URI       # Returns "http://example.org/text-slot1"
```

## VitalSigns Conversion Code Reference

### Complete Working Implementation

```python
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vitalgraph.model.kgentities_model import JsonLdDocument

# Import KG classes for isinstance checks
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

def create_kg_objects_from_jsonld(jsonld_document: dict) -> list:
    """
    Create VitalSigns KG objects from JSON-LD document.
    
    Args:
        jsonld_document: JSON-LD document with proper @context
        
    Returns:
        List of VitalSigns objects (KGEntity, KGFrame, KGSlot subclasses, etc.)
    """
    try:
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
        
    except Exception as e:
        print(f"Failed to create VitalSigns objects from JSON-LD: {e}")
        return []

def set_grouping_uris(objects: list, entity_uri: str):
    """Set hasKGGraphURI grouping property on all objects."""
    for obj in objects:
        try:
            # Use short name - hasKGGraphURI short name is 'kGGraphURI'
            obj.kGGraphURI = entity_uri
            print(f"Set kGGraphURI={entity_uri} on object {obj.URI}")
        except Exception as e:
            print(f"Failed to set kGGraphURI on {obj.URI}: {e}")

def access_slot_values(objects: list) -> dict:
    """
    Access slot values from VitalSigns objects using proper property access.
    
    Returns:
        Dictionary mapping object URIs to their values
    """
    # Import specific slot types for isinstance checks
    from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
    from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
    from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
    from ai_haley_kg_domain.model.KGChoiceSlot import KGChoiceSlot
    from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot
    from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
    from ai_haley_kg_domain.model.KGCurrencySlot import KGCurrencySlot
    from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
    
    slot_values = {}
    
    for obj in objects:
        try:
            obj_name = getattr(obj, 'hasName', obj.URI)
            
            # Access slot values using isinstance checks and direct property access
            if isinstance(obj, KGTextSlot):
                value = str(obj.textSlotValue) if obj.textSlotValue else None
                slot_values[obj.URI] = {'type': 'KGTextSlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGIntegerSlot):
                value = int(obj.integerSlotValue) if obj.integerSlotValue else None
                slot_values[obj.URI] = {'type': 'KGIntegerSlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGBooleanSlot):
                value = bool(obj.booleanSlotValue) if obj.booleanSlotValue else None
                slot_values[obj.URI] = {'type': 'KGBooleanSlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGChoiceSlot):
                value = str(obj.choiceSlotValue) if obj.choiceSlotValue else None
                slot_values[obj.URI] = {'type': 'KGChoiceSlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGDoubleSlot):
                value = float(obj.doubleSlotValue) if obj.doubleSlotValue else None
                slot_values[obj.URI] = {'type': 'KGDoubleSlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGDateTimeSlot):
                value = obj.dateTimeSlotValue  # DateTime objects may not need casting
                slot_values[obj.URI] = {'type': 'KGDateTimeSlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGCurrencySlot):
                value = float(obj.currencySlotValue) if obj.currencySlotValue else None
                slot_values[obj.URI] = {'type': 'KGCurrencySlot', 'name': obj_name, 'value': value}
                
            elif isinstance(obj, KGEntitySlot):
                value = str(obj.entitySlotValue) if obj.entitySlotValue else None
                slot_values[obj.URI] = {'type': 'KGEntitySlot', 'name': obj_name, 'value': value}
                
            else:
                # Generic slot handling for other slot types
                slot_type = type(obj).__name__
                slot_values[obj.URI] = {'type': slot_type, 'name': obj_name, 'value': None}
                
        except Exception as e:
            print(f"Error accessing slot value for {obj.URI}: {e}")
    
    return slot_values

def process_complete_entity_document(jsonld_document: dict, entity_uri: str) -> list:
    """
    Complete workflow for processing a KG entity document with VitalSigns.
    
    Args:
        jsonld_document: JSON-LD document containing entity, frames, and slots
        entity_uri: URI of the main entity for grouping
        
    Returns:
        List of processed VitalSigns objects with grouping URIs set
    """
    # Step 1: Convert JSON-LD to VitalSigns objects
    objects = create_kg_objects_from_jsonld(jsonld_document)
    
    if not objects:
        print("No VitalSigns objects created from JSON-LD")
        return []
    
    print(f"Created {len(objects)} VitalSigns objects from JSON-LD")
    
    # Step 2: Set grouping URIs on all objects
    set_grouping_uris(objects, entity_uri)
    
    # Step 3: Categorize objects using isinstance checks
    entities = []
    frames = []
    slots = []
    edges = []
    
    for obj in objects:
        try:
            if isinstance(obj, KGEntity):
                entities.append(obj)
            elif isinstance(obj, KGFrame):
                frames.append(obj)
            elif isinstance(obj, KGSlot):
                slots.append(obj)
            elif isinstance(obj, VITAL_Edge):
                edges.append(obj)
            else:
                print(f"Warning: Unknown object type {type(obj).__name__} for {obj.URI}")
        except Exception as e:
            print(f"Warning: Could not categorize object {obj.URI}: {e}")
    
    print(f"Processed entity document: {len(entities)} entities, {len(frames)} frames, {len(slots)} slots, {len(edges)} edges")
    
    # Step 4: Access slot values for verification
    slot_values = access_slot_values(slots)
    for uri, info in slot_values.items():
        print(f"  {info['type']} '{info['name']}' value: {info['value']}")
    
    return objects
```

## Complete Working Example

### Multi-Slot JSON-LD Document

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
            "vital:hasName": "User Profile Entity",
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity"
        },
        {
            "@id": "http://example.org/frame1", 
            "@type": "haley:KGFrame",
            "vital:hasName": "User Profile Frame",
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGFrame"
        },
        {
            "@id": "http://example.org/text-slot1",
            "@type": "haley:KGTextSlot", 
            "vital:hasName": "Name Slot",
            "haley:hasTextSlotValue": "John Doe",
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
        },
        {
            "@id": "http://example.org/integer-slot1",
            "@type": "haley:KGIntegerSlot",
            "vital:hasName": "Age Slot",
            "haley:hasIntegerSlotValue": 25,
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot"
        },
        {
            "@id": "http://example.org/boolean-slot1",
            "@type": "haley:KGBooleanSlot",
            "vital:hasName": "Is Active Slot",
            "haley:hasBooleanSlotValue": true,
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot"
        },
        {
            "@id": "http://example.org/choice-slot1",
            "@type": "haley:KGChoiceSlot",
            "vital:hasName": "Status Slot",
            "haley:hasChoiceSlotValue": "active",
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGChoiceSlot"
        },
        {
            "@id": "http://example.org/double-slot1",
            "@type": "haley:KGDoubleSlot",
            "vital:hasName": "Score Slot",
            "haley:hasDoubleSlotValue": 95.5,
            "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot"
        }
    ]
}
```

### Usage Example

```python
# Required imports for isinstance checks
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

# Example usage with the complete workflow
sample_document = {
    "@context": {
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "vital": "http://vital.ai/ontology/vital-core#"
    },
    "@graph": [
        # ... JSON-LD objects as shown above
    ]
}

# Process the complete document
entity_uri = "http://example.org/entity1"
processed_objects = process_complete_entity_document(sample_document, entity_uri)

# Expected output:
# Created 7 VitalSigns objects from JSON-LD
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/entity1
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/frame1
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/text-slot1
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/integer-slot1
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/boolean-slot1
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/choice-slot1
# Set kGGraphURI=http://example.org/entity1 on object http://example.org/double-slot1
# Processed entity document: 1 entities, 1 frames, 5 slots, 0 edges
#   KGTextSlot 'Name Slot' value: John Doe
#   KGIntegerSlot 'Age Slot' value: 25
#   KGBooleanSlot 'Is Active Slot' value: True
#   KGChoiceSlot 'Status Slot' value: active
#   KGDoubleSlot 'Score Slot' value: 95.5
```

## Property Access Patterns

### Direct Property Access (Recommended)

VitalSigns objects support direct property access using short property names. **Important**: Property access returns Property objects, not raw values. Cast to get the actual data type value:

```python
# Getting values - Property objects are returned, cast to get actual values
text_property = obj.textSlotValue          # Returns StringProperty object
text_value = str(obj.textSlotValue)        # Cast to get actual string value

integer_property = obj.integerSlotValue    # Returns IntegerProperty object  
integer_value = int(obj.integerSlotValue)  # Cast to get actual int value

boolean_property = obj.booleanSlotValue    # Returns BooleanProperty object
boolean_value = bool(obj.booleanSlotValue) # Cast to get actual bool value

choice_property = obj.choiceSlotValue      # Returns StringProperty object
choice_value = str(obj.choiceSlotValue)    # Cast to get actual string value

double_property = obj.doubleSlotValue      # Returns DoubleProperty object
double_value = float(obj.doubleSlotValue)  # Cast to get actual float value

# Setting values - can assign raw values directly
obj.textSlotValue = "New Text"
obj.integerSlotValue = 42
obj.booleanSlotValue = True
obj.choiceSlotValue = "selected"
obj.doubleSlotValue = 3.14159

# Common properties
obj.hasName = "Object Name"
obj.kGGraphURI = "http://example.org/entity1"
```

### Property Name Mapping

| Full Property URI | Short Property Name | Getting Value | Setting Value |
|-------------------|---------------------|---------------|---------------|
| `http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue` | `textSlotValue` | `str(obj.textSlotValue)` | `obj.textSlotValue = "text"` |
| `http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue` | `integerSlotValue` | `int(obj.integerSlotValue)` | `obj.integerSlotValue = 25` |
| `http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue` | `booleanSlotValue` | `bool(obj.booleanSlotValue)` | `obj.booleanSlotValue = True` |
| `http://vital.ai/ontology/haley-ai-kg#hasChoiceSlotValue` | `choiceSlotValue` | `str(obj.choiceSlotValue)` | `obj.choiceSlotValue = "active"` |
| `http://vital.ai/ontology/haley-ai-kg#hasDoubleSlotValue` | `doubleSlotValue` | `float(obj.doubleSlotValue)` | `obj.doubleSlotValue = 95.5` |
| `http://vital.ai/ontology/haley-ai-kg#hasDateTimeSlotValue` | `dateTimeSlotValue` | `obj.dateTimeSlotValue` | `obj.dateTimeSlotValue = datetime.now()` |
| `http://vital.ai/ontology/haley-ai-kg#hasCurrencySlotValue` | `currencySlotValue` | `float(obj.currencySlotValue)` | `obj.currencySlotValue = 100.50` |
| `http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue` | `entitySlotValue` | `str(obj.entitySlotValue)` | `obj.entitySlotValue = "http://example.org/entity"` |
| `http://vital.ai/ontology/vital-core#hasName` | `hasName` | `str(obj.hasName)` | `obj.hasName = "Object Name"` |
| `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI` | `kGGraphURI` | `str(obj.kGGraphURI)` | `obj.kGGraphURI = "http://example.org/entity1"` |
| `http://vital.ai/ontology/haley-ai-kg#hasKGEntityType` | `kGEntityType` | `str(obj.kGEntityType)` | `obj.kGEntityType = "urn:PersonEntityType"` |
| `http://vital.ai/ontology/haley-ai-kg#hasKGFrameType` | `kGFrameType` | `str(obj.kGFrameType)` | `obj.kGFrameType = "urn:EmploymentRelationType"` |
| `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType` | `kGSlotType` | `str(obj.kGSlotType)` | `obj.kGSlotType = "urn:NameSlotType"` |

### Alternative Property Access Methods

```python
# Method 1: Direct property access (Recommended)
property_obj = obj.textSlotValue           # Returns Property object
value = str(obj.textSlotValue)             # Cast to get actual value
obj.textSlotValue = "new value"            # Set new value

# Method 2: get_property/set_property methods  
property_obj = obj.get_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue')
value = str(property_obj) if property_obj else None  # Cast Property object
obj.set_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue', "new value")

# Method 3: getattr/setattr with short names
property_obj = getattr(obj, 'textSlotValue', None)
value = str(property_obj) if property_obj else None  # Cast Property object
setattr(obj, 'textSlotValue', "new value")
```

### Property Object Types

VitalSigns property access returns specific Property objects:

```python
from vital_ai_vitalsigns.model.properties.StringProperty import StringProperty
from vital_ai_vitalsigns.model.properties.IntegerProperty import IntegerProperty
from vital_ai_vitalsigns.model.properties.BooleanProperty import BooleanProperty
from vital_ai_vitalsigns.model.properties.DoubleProperty import DoubleProperty

# Property objects can be inspected
text_prop = obj.textSlotValue              # Returns StringProperty instance
print(f"Property type: {type(text_prop)}")  # <class 'StringProperty'>
print(f"Property value: {text_prop}")       # Displays the actual value
print(f"Cast to string: {str(text_prop)}")  # Explicit casting
```

### Key Findings from Testing

1. **VitalSigns Methods**: Use `vitalsigns.from_jsonld_list()` for documents with `@graph` arrays
2. **Property Access**: Use direct property access (`obj.textSlotValue`) for clean, readable code
3. **Property Objects**: Property access returns Property objects, not raw values - cast to get actual values (`str(obj.textSlotValue)`)
4. **Grouping URIs**: Use short name `obj.kGGraphURI = entity_uri` to set grouping properties
5. **Type Detection**: Use `isinstance(obj, KGEntity)` instead of string matching on `vitaltype`
6. **Edge Detection**: All edges inherit from `VITAL_Edge` - use `isinstance(obj, VITAL_Edge)`
7. **Imports Required**: Import specific classes (`KGEntity`, `KGFrame`, `KGSlot`, `VITAL_Edge`) for isinstance checks
8. **JSON-LD Format**: Properties must use full URIs with proper `@context` mapping
9. **Python Booleans**: Use `true`/`false` in JSON-LD, but Python expects `True`/`False` in code
10. **Property Names**: VitalSigns converts `hasXxxSlotValue` to `xxxSlotValue` for direct access
11. **Casting Required**: Use `str()`, `int()`, `float()`, `bool()` to extract values from Property objects

### Tested Slot Types and Values

| Slot Type | Test Value | Result | Property Type |
|-----------|------------|--------|---------------|
| KGTextSlot | "John Doe" | ✅ Working | StringProperty |
| KGIntegerSlot | 25 | ✅ Working | IntegerProperty |
| KGBooleanSlot | true | ✅ Working | BooleanProperty |
| KGChoiceSlot | "active" | ✅ Working | StringProperty |
| KGDoubleSlot | 95.5 | ✅ Working | DoubleProperty |

## Notes

- **Recommended Approach**: Use direct property access (`obj.textSlotValue`) for both getting and setting values
- **Property Naming**: VitalSigns converts `hasXxxSlotValue` to `xxxSlotValue` for direct access
- **Type Safety**: Use `isinstance(obj, KGTextSlot)` for reliable type checking before accessing slot-specific properties
- **JSON-LD Format**: Use full URIs in JSON-LD documents, but access via short names in Python code
- **Common Properties**: All slot classes have `hasKGSlotValueType` property and inherit from `KGSlot`
- **Grouping URIs**: Use `obj.kGGraphURI = entity_uri` to set grouping properties on all KG objects
- **Type Management**: Use URN identifiers for types (e.g., `"urn:PersonEntityType"`) and manage types via the KGTypes REST endpoint
- **Alternative Methods**: `get_property()` and `set_property()` methods are available but direct access is cleaner

### Property Access Summary

| Context | Approach | Getting Values | Setting Values |
|---------|----------|----------------|----------------|
| **JSON-LD Documents** | Full URIs with @context | N/A | `"haley:hasTextSlotValue": "text"` |
| **Python Code (Recommended)** | Direct property access | `str(obj.textSlotValue)` | `obj.textSlotValue = "text"` |
| **Python Code (Alternative)** | get_property/set_property | `str(obj.get_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue'))` | `obj.set_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue', "text")` |

**Important**: Property access in Python returns Property objects. Cast with `str()`, `int()`, `float()`, `bool()` to get actual values.

This documentation was generated from vital-ai-haley-kg version 0.1.24 using VitalSigns property discovery.
