# KGQuery Client Test Script Plan

## Overview

This document outlines the plan to create a comprehensive client-side test script for the KGQuery endpoint. The test script will validate entity-to-entity connection queries using both relation-based and frame-based query types.

## Current State Analysis

### Server-Side Implementation Status

**Location:** `vitalgraph/endpoint/kgquery_endpoint.py`

**Implemented Features:**
1. ✅ POST `/api/graphs/kgqueries` endpoint
2. ✅ Two query types supported:
   - **Relation queries**: Find entities connected via `Edge_hasKGRelation`
   - **Frame queries**: Find entities connected via shared `KGFrames`
3. ✅ Query criteria model (`KGQueryCriteria`) with:
   - Source entity specification (criteria or URIs)
   - Destination entity specification (criteria or URIs)
   - Relation-specific criteria (relation types, direction)
   - Frame-specific criteria (frame types, slot criteria)
4. ✅ Response models:
   - `RelationConnection` - source, destination, relation edge, relation type
   - `FrameConnection` - source, destination, shared frame, frame type
   - `KGQueryResponse` - paginated results with total count
5. ✅ SPARQL query builder (`KGConnectionQueryBuilder`)
6. ✅ Pagination support (page_size, offset)

### Client-Side Implementation Status

**Location:** `vitalgraph/client/endpoint/` - **NOT YET IMPLEMENTED**

**Missing Components:**
1. ❌ No `kgqueries_endpoint.py` client endpoint
2. ❌ No client response classes for KGQuery operations
3. ❌ No integration in `VitalGraphClient` class
4. ❌ No test script in `vitalgraph_client_test/`

**Existing Test Directory:**
- `vitalgraph_client_test/kgqueries/` exists but only contains `__init__.py`

### Model Files

**Location:** `vitalgraph/model/kgqueries_model.py`

**Available Models:**
- `KGQueryCriteria` - Query criteria specification
- `KGQueryRequest` - Request wrapper with pagination
- `KGQueryResponse` - Server response model
- `RelationConnection` - Relation connection data
- `FrameConnection` - Frame connection data
- `KGQueryStatsResponse` - Statistics model (optional)

## Test Script Requirements

### Test Data Requirements

**Use Existing Multi-Org Test Data:**

The test script will use the same data loading functions from `test_multiple_organizations_crud.py`:

1. **Organizations (10 entities):**
   - Created via `CreateOrganizationsTester`
   - Each has address frame, employee count frame, industry frame
   - Located in different cities (San Francisco, New York, Boston, Austin, etc.)

2. **Business Events (10 entities):**
   - Created via `CreateBusinessEventsTester`
   - Each event has:
     - `EventDetailsFrame` - event type, timestamp, status
     - `SourceBusinessFrame` - contains URI slot referencing organization
     - `EventDataFrame` - event-specific data
   - Event types: NewCustomer, Transaction, Cancellation
   - Each event references one organization via `uriSlotValue` in `SourceBusinessFrame`

3. **Frame Connection Pattern:**
   ```
   Event Entity
     └─> hasEntityKGFrame -> SourceBusinessFrame
           └─> hasKGSlot -> BusinessEntityURISlot
                 └─> uriSlotValue = <Organization URI>
   ```

**Initial Focus: Frame Queries Only**
- No relation data will be loaded initially
- Focus on querying events that reference organizations through frames
- Test frame-based connections between events and organizations

### Test Coverage Goals

**Frame Query Tests (Initial Focus):**

Using organization URIs to find connected events:

1. ✅ **Find events referencing a specific organization**
   - Query: Given org URI, find all events with SourceBusinessFrame containing that org URI
   - Expected: Events that reference the organization in their BusinessEntityURISlot

2. ✅ **Find events by event type**
   - Query: Find all "NewCustomer" events
   - Filter by EventDetailsFrame with specific event type slot value

3. ✅ **Find events for multiple organizations**
   - Query: Given multiple org URIs, find all events referencing any of them
   - Test batch URI queries

4. ✅ **Filter events by source entity type**
   - Query: Find BusinessEventEntity types only
   - Verify entity type filtering works

5. ✅ **Pagination of event results**
   - Query with page_size and offset
   - Verify correct pagination behavior

6. ✅ **Find organizations referenced by events**
   - Reverse query: Given event URI, find the organization it references
   - Test bidirectional frame connections

7. ✅ **Empty results handling**
   - Query for non-existent organization
   - Verify graceful empty result handling

8. ✅ **Multiple frame types**
   - Query events sharing EventDetailsFrame type
   - Test frame type filtering

**Relation Query Tests (Future - Not Initial Focus):**
- Deferred until relation data is added to test dataset

## Implementation Plan

### Phase 1: Create Client Endpoint (NEW)

**File:** `vitalgraph/client/endpoint/kgqueries_endpoint.py`

**Methods to Implement:**
```python
class KGQueriesEndpoint(BaseEndpoint):
    def query_connections(
        self,
        space_id: str,
        graph_id: str,
        criteria: KGQueryCriteria,
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """Query entity-to-entity connections."""
        pass
    
    def query_relation_connections(
        self,
        space_id: str,
        graph_id: str,
        source_entity_uris: Optional[List[str]] = None,
        destination_entity_uris: Optional[List[str]] = None,
        relation_type_uris: Optional[List[str]] = None,
        direction: str = "outgoing",
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """Convenience method for relation queries."""
        pass
    
    def query_frame_connections(
        self,
        space_id: str,
        graph_id: str,
        source_entity_uris: Optional[List[str]] = None,
        destination_entity_uris: Optional[List[str]] = None,
        shared_frame_types: Optional[List[str]] = None,
        page_size: int = 10,
        offset: int = 0
    ) -> KGQueryResponse:
        """Convenience method for frame queries."""
        pass
```

**Implementation Notes:**
- Use `_make_typed_request()` for HTTP calls
- Build `KGQueryRequest` from parameters
- Return server `KGQueryResponse` directly (already has good structure)
- Add error handling with try/except blocks
- Follow pattern from `kgtypes_endpoint.py`, `kgentities_endpoint.py`

### Phase 2: Integrate into VitalGraphClient (NEW)

**File:** `vitalgraph/client/vitalgraph_client.py`

**Changes:**
```python
from .endpoint.kgqueries_endpoint import KGQueriesEndpoint

class VitalGraphClient:
    def __init__(self, ...):
        # ... existing endpoints ...
        self.kgqueries = KGQueriesEndpoint(self)  # ADD THIS
```

### Phase 3: Use Existing Multi-Org Test Data

**Use Existing Test Functions:**

Import and use the existing multi-org test data loaders:

```python
from vitalgraph_client_test.multi_kgentity.case_create_organizations import CreateOrganizationsTester
from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester

# In test script:
# 1. Create 10 organizations
org_tester = CreateOrganizationsTester(client)
org_results = org_tester.run_tests(space_id, graph_id)
organization_uris = org_results["created_entity_uris"]

# 2. Create 10 business events (each references one organization)
event_tester = CreateBusinessEventsTester(client)
event_results = event_tester.run_tests(space_id, graph_id, organization_uris)
event_uris = event_results["created_event_uris"]
```

**Data Structure Created:**
- 10 Organizations with address, employee, industry frames
- 10 Business Events, each with:
  - EventDetailsFrame (type, timestamp, status)
  - SourceBusinessFrame containing BusinessEntityURISlot → references org URI
  - EventDataFrame (event-specific data)

**Key Connection:**
```
Event.SourceBusinessFrame.BusinessEntityURISlot.uriSlotValue = Organization.URI
```

This is the frame-based connection we'll query!

### Phase 4: Create Test Case Module (Frame Queries Only)

**Directory:** `vitalgraph_client_test/kgqueries/`

**Test Case File:**

**`case_frame_queries.py`** - Frame-based query tests for event-organization connections

Test methods:
1. `_test_find_events_for_organization()` - Given org URI, find all events referencing it
2. `_test_find_organization_for_event()` - Given event URI, find the org it references
3. `_test_find_events_for_multiple_orgs()` - Query multiple org URIs at once
4. `_test_filter_by_event_type()` - Filter events by BusinessEventEntity type
5. `_test_filter_by_frame_type()` - Filter by SourceBusinessFrame type
6. `_test_pagination()` - Test page_size and offset
7. `_test_empty_results()` - Query non-existent organization
8. `_test_exclude_self_connections()` - Verify self-connections excluded

**Pattern:**
```python
class FrameQueriesTester:
    def run_tests(self, space_id, graph_id, org_uris, event_uris):
        # Run 8 frame query tests
        # Return results dict with passed/failed counts
```

### Phase 5: Create Main Test Script

**File:** `vitalgraph_client_test/test_kgqueries_endpoint.py`

**Test Flow:**
```python
async def main():
    """
    Test flow:
    1. Initialize client and authenticate
    2. Create test space
    3. Load organizations using CreateOrganizationsTester (10 orgs)
    4. Load business events using CreateBusinessEventsTester (10 events)
    5. Run frame query tests (8 tests)
    6. Cleanup test space
    7. Report results
    """
    
    # Example implementation:
    client = VitalGraphClient(config_path)
    client.open()
    
    # Create test space
    space_id = "space_kgquery_test"
    graph_id = "urn:kgquery_test_graph"
    
    # Load organizations (reuse multi-org test function)
    from vitalgraph_client_test.multi_kgentity.case_create_organizations import CreateOrganizationsTester
    org_tester = CreateOrganizationsTester(client)
    org_results = org_tester.run_tests(space_id, graph_id)
    organization_uris = org_results["created_entity_uris"]
    
    # Load business events (reuse multi-org test function)
    from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester
    event_tester = CreateBusinessEventsTester(client)
    event_results = event_tester.run_tests(space_id, graph_id, organization_uris)
    event_uris = event_results["created_event_uris"]
    
    # Run frame query tests
    from vitalgraph_client_test.kgqueries.case_frame_queries import FrameQueriesTester
    frame_tester = FrameQueriesTester(client)
    frame_results = frame_tester.run_tests(space_id, graph_id, organization_uris, event_uris)
    
    # Report and cleanup
    print_test_summary([org_results, event_results, frame_results])
    client.spaces.delete_space(space_id)
    client.close()
```

## Test Data Design

### Relation Test Data

**Scenario 1: Business Partnership Network**
```
Organizations:
- TechCorp (Org A)
- DataSystems (Org B)  
- CloudServices (Org C)
- AILabs (Org D)

Relations:
- TechCorp --[PartnerWith]--> DataSystems
- TechCorp --[Owns]--> CloudServices
- DataSystems --[CompetesWith]--> AILabs
- CloudServices --[PartnerWith]--> AILabs
```

**Scenario 2: Employment Network**
```
People:
- Alice Johnson
- Bob Smith
- Carol Davis

Organizations:
- TechCorp
- DataSystems

Relations:
- Alice --[WorksFor]--> TechCorp
- Bob --[WorksFor]--> TechCorp
- Carol --[WorksFor]--> DataSystems
```

### Frame Test Data

**Scenario 1: Shared Location (Address Frames)**
```
Organizations:
- TechCorp (Address: 123 Main St, San Francisco)
- DataSystems (Address: 123 Main St, San Francisco)  # Same building
- CloudServices (Address: 456 Oak Ave, San Jose)

Shared Frames:
- TechCorp and DataSystems share AddressFrame_1 (same location)
```

**Scenario 2: Shared Contact Info**
```
Organizations:
- TechCorp (Phone: 555-1234)
- CloudServices (Phone: 555-1234)  # Same phone number

Shared Frames:
- TechCorp and CloudServices share ContactFrame_1 (same phone)
```

## Test Script Structure

### Main Test Script

**File:** `vitalgraph_client_test/test_kgqueries_endpoint.py`

```python
#!/usr/bin/env python3
"""
Test script for KGQueries endpoint.

Tests entity-to-entity connection queries using both relation-based
and frame-based query types.
"""

import asyncio
import logging
from pathlib import Path

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph_client_test.kgqueries.kgquery_test_data import KGQueryTestDataGenerator
from vitalgraph_client_test.kgqueries.case_relation_queries import RelationQueriesTester
from vitalgraph_client_test.kgqueries.case_frame_queries import FrameQueriesTester
from vitalgraph_client_test.kgqueries.case_query_edge_cases import QueryEdgeCasesTester

async def main():
    """Run KGQueries endpoint tests."""
    
    # 1. Initialize client
    # 2. Create test space
    # 3. Generate and load test data
    # 4. Run relation query tests
    # 5. Run frame query tests
    # 6. Run edge case tests
    # 7. Cleanup and report
    
    pass

if __name__ == "__main__":
    asyncio.run(main())
```

### Test Case Module Structure

**Pattern:** Follow `vitalgraph_client_test/kgtypes/case_kgtype_list.py`

```python
class RelationQueriesTester:
    """Test case for relation-based queries."""
    
    def __init__(self, client: VitalGraphClient):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, test_data: Dict) -> Dict[str, Any]:
        """Run all relation query tests."""
        results = []
        
        # Test 1: Query outgoing relations
        results.append(self._test_outgoing_relations(space_id, graph_id, test_data))
        
        # Test 2: Query incoming relations
        results.append(self._test_incoming_relations(space_id, graph_id, test_data))
        
        # Test 3: Query bidirectional relations
        results.append(self._test_bidirectional_relations(space_id, graph_id, test_data))
        
        # Test 4: Filter by relation type
        results.append(self._test_relation_type_filter(space_id, graph_id, test_data))
        
        # Test 5: Pagination
        results.append(self._test_pagination(space_id, graph_id, test_data))
        
        return {
            'test_name': 'Relation Queries',
            'tests_run': len(results),
            'tests_passed': sum(1 for r in results if r['passed']),
            'tests_failed': sum(1 for r in results if not r['passed']),
            'results': results
        }
    
    def _test_outgoing_relations(self, space_id: str, graph_id: str, test_data: Dict) -> Dict[str, Any]:
        """Test querying outgoing relations from a source entity."""
        try:
            source_uri = test_data['techcorp_uri']
            
            response = self.client.kgqueries.query_relation_connections(
                space_id=space_id,
                graph_id=graph_id,
                source_entity_uris=[source_uri],
                direction="outgoing"
            )
            
            if response.query_type == "relation" and response.relation_connections:
                return {
                    'name': 'Query Outgoing Relations',
                    'passed': True,
                    'details': f"Found {len(response.relation_connections)} outgoing relations"
                }
            else:
                return {
                    'name': 'Query Outgoing Relations',
                    'passed': False,
                    'error': 'No relations found'
                }
        except Exception as e:
            return {
                'name': 'Query Outgoing Relations',
                'passed': False,
                'error': str(e)
            }
```

## Implementation Steps

### Step 1: Create Client Endpoint (1-2 hours)
- [ ] Create `vitalgraph/client/endpoint/kgqueries_endpoint.py`
- [ ] Implement `query_connections()` method
- [ ] Implement `query_frame_connections()` convenience method (focus on this)
- [ ] Add error handling and logging
- [ ] Follow patterns from existing endpoints (kgtypes, kgentities)

### Step 2: Integrate into Client (15 minutes)
- [ ] Update `vitalgraph/client/vitalgraph_client.py`
- [ ] Add `KGQueriesEndpoint` import
- [ ] Initialize `self.kgqueries` endpoint

### Step 3: Create Test Case Module (2-3 hours)
- [ ] Create `vitalgraph_client_test/kgqueries/case_frame_queries.py`
- [ ] Implement 8 frame query test methods:
  - Find events for organization (by org URI)
  - Find organization for event (reverse lookup)
  - Find events for multiple orgs (batch query)
  - Filter by event entity type
  - Filter by frame type
  - Pagination testing
  - Empty results handling
  - Self-connection exclusion
- [ ] Follow modular pattern from KGTypes tests

### Step 4: Create Main Test Script (1-2 hours)
- [ ] Create `test_kgqueries_endpoint.py`
- [ ] Import and use existing multi-org test data loaders:
  - `CreateOrganizationsTester` (creates 10 orgs)
  - `CreateBusinessEventsTester` (creates 10 events)
- [ ] Implement test orchestration flow
- [ ] Add comprehensive result reporting
- [ ] Follow pattern from `test_kgtypes_endpoint.py`

### Step 5: Testing and Validation (1-2 hours)
- [ ] Run test script and verify all tests pass
- [ ] Debug any query failures
- [ ] Validate frame connections are correctly identified
- [ ] Verify organization URIs are properly matched in event frames
- [ ] Test pagination works correctly
- [ ] Test error handling

## Expected Test Results

### Frame Query Tests (8 tests - Initial Focus)

Using multi-org test data (10 organizations + 10 business events):

1. ✅ **Find events for organization** - Given TechCorp URI, find "TechCorp New Enterprise Client" event
2. ✅ **Find organization for event** - Given event URI, find the organization it references
3. ✅ **Find events for multiple orgs** - Query 3 org URIs, find their 3 associated events
4. ✅ **Filter by event entity type** - Find all BusinessEventEntity types
5. ✅ **Filter by frame type** - Find connections via SourceBusinessFrame
6. ✅ **Pagination** - Test page_size=5, offset=0 vs offset=5
7. ✅ **Empty results** - Query non-existent organization URI
8. ✅ **Self-connection exclusion** - Verify no entity connects to itself

### Total Expected Tests: 8 tests

**Future Tests (Deferred):**
- Relation query tests - will be added when relation data is included in test dataset

## Success Criteria

- [ ] Client endpoint `KGQueriesEndpoint` created and integrated
- [ ] Reuses existing multi-org test data (organizations + events)
- [ ] Frame query test case module implemented (8 tests)
- [ ] Main test script orchestrates all tests
- [ ] All tests pass (8/8 frame query tests)
- [ ] Clear test output with pass/fail reporting
- [ ] Proper cleanup of test data
- [ ] Validates event-organization connections via SourceBusinessFrame

## Key Differences from Other Endpoint Tests

### Unique Aspects of KGQuery Testing

1. **Complex Test Data:**
   - Requires entities with relations (edges)
   - Requires entities with shared frames
   - More complex data setup than simple CRUD operations

2. **Two Query Types:**
   - Relation queries (edge-based connections)
   - Frame queries (shared frame connections)
   - Different response structures for each

3. **Graph Traversal:**
   - Tests actual graph connectivity
   - Validates SPARQL query generation
   - Tests multi-hop potential (future)

4. **No CRUD Operations:**
   - Read-only queries
   - No create/update/delete operations
   - Focus on query correctness and performance

## Files to Create

### New Client Files
1. `vitalgraph/client/endpoint/kgqueries_endpoint.py` - Client endpoint (NEW)

### New Test Files
2. `vitalgraph_client_test/kgqueries/case_frame_queries.py` - Frame query tests (8 tests)
3. `vitalgraph_client_test/test_kgqueries_endpoint.py` - Main test script

### Files to Modify
4. `vitalgraph/client/vitalgraph_client.py` - Add kgqueries endpoint

### Files to Reuse (No Changes Needed)
- `vitalgraph_client_test/multi_kgentity/case_create_organizations.py` - Creates 10 orgs
- `vitalgraph_client_test/multi_kgentity/case_create_business_events.py` - Creates 10 events

## Dependencies

**Existing Components:**
- ✅ Server endpoint: `vitalgraph/endpoint/kgquery_endpoint.py`
- ✅ Models: `vitalgraph/model/kgqueries_model.py`
- ✅ Query builder: `vitalgraph/sparql/kg_connection_query_builder.py`
- ✅ Test patterns: `test_kgtypes_endpoint.py`, `test_multiple_organizations_crud.py`

**New Components Needed:**
- ❌ Client endpoint implementation
- ❌ Test data generator
- ❌ Test case modules
- ❌ Main test script

## Timeline Estimate

**Total Time:** 5-8 hours (Reduced - using existing multi-org data)

- Client endpoint implementation: 1-2 hours
- Client integration: 15 minutes
- Frame query test case module: 2-3 hours
- Main test script: 1-2 hours
- Testing and debugging: 1-2 hours

**Time Saved:** 2-3 hours by reusing existing multi-org test data instead of creating new test data generator

## Notes

- KGQuery endpoint is **read-only** - no create/update/delete operations
- Focus on validating query correctness and result accuracy
- Test data must include realistic entity relationships
- Follow existing test patterns for consistency
- Use modular test case structure for maintainability
- Server endpoint already exists and is functional
- Client endpoint needs to be created from scratch
- This is a **new client endpoint** - not a refactoring like Objects/KGTypes

## Related Documentation

- Server Endpoint: `vitalgraph/endpoint/kgquery_endpoint.py`
- Models: `vitalgraph/model/kgqueries_model.py`
- Query Builder: `vitalgraph/sparql/kg_connection_query_builder.py`
- Test Pattern Reference: `vitalgraph_client_test/test_kgtypes_endpoint.py`
- Data Loading Pattern: `vitalgraph_client_test/test_multiple_organizations_crud.py`
