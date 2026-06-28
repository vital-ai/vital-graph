# KGSlot to KGEntity Migration Plan

**Date**: January 26, 2026  
**Status**: Planning Phase  
**Goal**: Migrate test data from using KGURISlot for entity references to using KGEntity slots directly

---

## Executive Summary

### Problem
Test data uses `KGURISlot` with string URI values to reference entities (organizations). This is semantically incorrect - slots should reference entities directly, not URI strings.

### Solution
Switch to `KGEntity` slots (or `KGEntitySlot` if available) where the slot directly references the entity.

### Scope - Very Limited!
**Only 5 files need code changes**:
1. `client_test_data.py` - 1 line
2. `case_get_business_events.py` - 2 lines  
3. `test_kgquery_event_structure.py` - 2 lines
4. `kg_query_builder.py` - 2 lines
5. `graph_utils.py` - 1 line

**Plus**: 1 comment update, 1 file unchanged (file URIs)

---

## Current State Analysis

### Files Using uriSlotValue (Complete List)

**Search Results**: Only **7 files** use `uriSlotValue`:

**1. Test Data Generator** (`vitalgraph_client_test/client_test_data.py`):
- **Line 822**: `source_business_uri_slot.uriSlotValue = source_business_uri`
- Creates `KGURISlot` for business entity references
- **Action**: Change to entity slot

**2. Organization Creation** (`vitalgraph_client_test/multi_kgentity/case_create_organizations.py`):
- **Line 239**: `uri_slot.uriSlotValue = file_uris[file_key]`
- Creates `KGURISlot` for document file references
- **Action**: Keep as URI slot (external file references)

**3. Business Event Retrieval** (`vitalgraph_client_test/multi_kgentity/case_get_business_events.py`):
- **Lines 158-159**: Reads `obj.uriSlotValue` to get organization URI
- Validates organization references via URI string matching
- **Action**: Update to read entity slot reference

**4. KGQuery Frame Queries - Comment Only** (`vitalgraph_client_test/kgqueries/case_frame_queries.py`):
- **Line 111**: Comment mentions `uriSlotValue = org_uri`
- No actual code usage
- **Action**: Update comment

**5. KGQuery Event Structure Test** (`vitalgraph_client_test/test_kgquery_event_structure.py`):
- **Line 177**: SPARQL query `OPTIONAL { ?slot haley:hasUriSlotValue ?slotValue }`
- **Line 264**: SPARQL query `?slot haley:hasUriSlotValue ?orgURI`
- **Action**: Update SPARQL queries for entity slots

**6. Query Builder** (`vitalgraph/sparql/kg_query_builder.py`):
- **Lines 636, 651**: Maps `KGURISlot` to `haley:hasUriSlotValue` predicate
- **Action**: Add mapping for entity slots

**7. Graph Utils** (`vitalgraph/utils/graph_utils.py`):
- **Line 378**: Slot value property mapping: `'KGURISlot': 'uRISlotValue'`
- **Action**: Add mapping for entity slots

### Summary of Changes Needed

**Client Test Files** (3 files):
1. `client_test_data.py` - Line 822
2. `multi_kgentity/case_get_business_events.py` - Lines 158-159
3. `test_kgquery_event_structure.py` - Lines 177, 264

**Utility/Framework Files** (2 files):
1. `sparql/kg_query_builder.py` - Lines 636, 651
2. `utils/graph_utils.py` - Line 378

**Documentation Only** (1 file):
1. `kgqueries/case_frame_queries.py` - Line 111 (comment)

**Keep As-Is** (1 file):
1. `multi_kgentity/case_create_organizations.py` - Line 239 (file URIs - external, not entities)

---

## Verification: Entity URIs vs External URIs

### URI Slot at Line 822 (client_test_data.py)
```python
source_business_uri_slot.uriSlotValue = source_business_uri
```
**Value Source**: `source_business_uri` parameter from `create_business_event()`  
**Actual Value**: Organization entity URI (e.g., `urn:organization:acme_corp`)  
**Usage**: Passed from `org_name_to_uri` mapping in test scripts  
**Verdict**: ✅ **MIGRATE** - This is an entity URI

### URI Slot at Line 239 (case_create_organizations.py)
```python
uri_slot.uriSlotValue = file_uris[file_key]
```
**Value Source**: `file_uris` dictionary from file upload results  
**Actual Value**: File service URI (e.g., `haley:file_test_document_001`)  
**Usage**: External file reference from file upload API  
**Verdict**: ❌ **KEEP AS URI SLOT** - This is an external file reference, not a graph entity

### Summary
- **BusinessEntityURISlot** (Line 822): References organization entities → Migrate to entity slot
- **DocumentFileURISlot** (Line 239): References external files → Keep as URI slot

### Current vs Proposed

**Current** (Incorrect):
```
Event → Frame → KGURISlot.uriSlotValue = "urn:org:123" (string)
```

**Proposed** (Correct):
```
Event → Frame → KGEntity slot → references entity directly
```

**Why**: Slots should reference entities, not store URI strings.

---

## Implementation Steps

### Step 1: Check Ontology
**Action**: Verify if `KGEntitySlot` class exists in `ai_haley_kg_domain`  
**Decision**: Use `KGEntitySlot` if exists, otherwise use `KGEntity` with slot type

### Step 2: Update Test Data (1 file, 1 line)
**File**: `client_test_data.py` Line 822

**Change**:
```python
# FROM:
source_business_uri_slot.uriSlotValue = source_business_uri

# TO:
source_business_entity_slot = KGEntitySlot()  # or KGEntity
source_business_entity_slot.URI = self.generate_test_uri("slot", ...)
source_business_entity_slot.kGSlotType = "...#BusinessEntitySlot"
# Reference entity directly (implementation depends on ontology)
```

### Step 3: Update Query Criteria (2 files, 4 locations)
**Files**: 
- `case_kgquery_frame_queries.py` Lines 118, 193
- `kgqueries/case_frame_queries.py` Lines 124, 255

**Change**:
```python
# FROM:
slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGURISlot"

# TO:
slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGEntitySlot"  # or KGEntity
```

### Step 4: Update Validation (1 file, 2 lines)
**File**: `case_get_business_events.py` Lines 158-159

**Change**:
```python
# FROM:
if isinstance(obj, KGURISlot):
    if hasattr(obj, 'uriSlotValue') and obj.uriSlotValue:

# TO:
if isinstance(obj, KGEntitySlot):  # or KGEntity with slot type check
    # Check entity reference property
```

### Step 5: Update SPARQL Queries (1 file, 2 lines)
**File**: `test_kgquery_event_structure.py` Lines 177, 264

**Change**:
```python
# FROM:
?slot haley:hasUriSlotValue ?orgURI

# TO:
?slot haley:hasEntitySlotValue ?orgEntity  # or appropriate property
```

### Step 6: Update Framework Mappings (2 files, 3 lines)
**File 1**: `kg_query_builder.py` Lines 636, 651
```python
# Add mapping for entity slots
elif slot_class_uri.endswith("KGEntitySlot"):
    return "haley:hasEntitySlotValue"
```

**File 2**: `graph_utils.py` Line 378
```python
# Add to slot value property mapping
'KGEntitySlot': 'entitySlotValue',
```

### Step 7: Update Slot Class Lists (3 files)

**Critical**: Several files have hardcoded lists of slot classes for validation and type checking. These need to include `KGEntitySlot`.

**File 1**: `validation_utils.py` Lines 59-63, 71
```python
# Add import
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot  # or KGEntity

# Update isinstance checks (Line 71)
slots = [obj for obj in objects if isinstance(obj, (
    KGTextSlot, KGIntegerSlot, KGBooleanSlot, KGDoubleSlot, KGDateTimeSlot, 
    KGEntitySlot  # ADD THIS
))]
```

**Also update Lines 184-188, 193 and Lines 283-287, 292** (same pattern in other validation functions)

**File 2**: `vitalsigns_conversion_utils.py` Lines 11-13, 47
```python
# Add import
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot

# Update isinstance check (Line 47)
elif isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot, KGEntitySlot)):
```

**File 3**: `kgframe_diagnostics_impl.py` Line 37-38
```python
# Update SPARQL FILTER to include KGEntitySlot
FILTER(?slotType IN (haley:KGTextSlot, haley:KGIntegerSlot, haley:KGBooleanSlot, 
                     haley:KGDoubleSlot, haley:KGChoiceSlot, haley:KGEntitySlot))
```

**Summary of Slot Class List Updates**:
- `validation_utils.py`: 3 isinstance() checks (Lines 71, 193, 292)
- `vitalsigns_conversion_utils.py`: 1 isinstance() check (Line 47)
- `kgframe_diagnostics_impl.py`: 1 SPARQL FILTER (Line 37-38)

### Step 8: Test
Run `test_multiple_organizations_crud.py` and verify all tests pass

---

## Timeline

**Estimated**: 2-3 hours total
- Check ontology: 15 min
- Update 5 files: 1-1.5 hours
- Test and debug: 1 hour

---

## Success Criteria

1. ✅ Test data uses entity slots (not URI slots)
2. ✅ All tests in `test_multiple_organizations_crud.py` pass
3. ✅ Query results match pre-migration baseline

---

## Notes

- **File URIs**: Keep as `KGURISlot` (external references, not entities)
- **Ontology Check**: Determine if `KGEntitySlot` exists before starting
- **Backward Compatibility**: Match on entity URI initially (same behavior)
- **Future Enhancement**: Can add entity property queries later

---

**Status**: Ready for implementation  
**Last Updated**: January 26, 2026
