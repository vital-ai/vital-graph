# Automatic Graph Registration Plan

## Overview
Automatically register graphs in the PostgreSQL `graph` table when data is inserted into those graphs through the **DualWriteCoordinator**, where new graphs are being created with data operations.

## Problem Statement

Currently, when data is inserted into a graph:
1. Entities/data are created with a specified `graph_id`
2. Data is written to both Fuseki and PostgreSQL RDF tables via DualWriteCoordinator
3. **BUT** the graph is NOT automatically registered in the PostgreSQL `graph` table
4. This causes the "List graphs in space" API to fail to find graphs that contain data

### Current Test Failure
```
❌ FAIL: List and Verify Graphs
   Tests: 0/2 passed
   Errors:
      • List graphs in space: Expected graph not found in list: urn:multi_org_crud_graph
      • Get graph info: Failed to get graph info: Request failed: 500 Server Error
```

The graph `urn:multi_org_crud_graph` contains data (20 entities with frames/slots) but is not registered in the `graph` table.

## Architecture Principle

**Implement in DualWriteCoordinator where graphs are being created with data.**

- ✅ Implement in: DualWriteCoordinator.add_quads()
- ✅ Implement in: DualWriteCoordinator.execute_sparql_update()
- ✅ Extract graph URIs from quads being inserted
- ✅ Register graphs BEFORE data operations
- ❌ NOT in: Low-level quad table SQL operations
- ❌ NOT in: Individual API endpoints (too many places)

## Current Architecture

### DualWriteCoordinator - The Central Point

**Location**: `vitalgraph/db/fuseki_postgresql/dual_write_coordinator.py`

The DualWriteCoordinator is where ALL data writes flow through:
- Entity creation → add_quads()
- Entity updates → execute_sparql_update()
- File uploads → add_quads()
- Type creation → add_quads()

### Key Methods

1. **`add_quads(space_id, quads)`** (line 177)
   - Receives quads as tuples: `(subject, predicate, object, graph)`
   - Called for all INSERT operations
   - Already captures graph URIs from data

2. **`execute_sparql_update(space_id, sparql_update)`** (line 44)
   - Parses SPARQL UPDATE queries
   - SPARQLUpdateParser extracts graph URIs
   - Handles INSERT/DELETE/UPDATE operations
   - Graph URIs available in parsed operation

### Graph Management Infrastructure

**FusekiPostgreSQLSpaceGraphs** (`fuseki_postgresql_space_graphs.py`)

Already provides the infrastructure we need:
- `create_graph(space_id, graph_uri, graph_name)` - Register graph
- Uses **idempotent INSERT**: `INSERT ... ON CONFLICT DO NOTHING`
- Safe to call multiple times
- No error if graph already exists

**Existing Graph Table Schema** (NO CHANGES NEEDED):
```sql
CREATE TABLE graph (
    graph_id SERIAL PRIMARY KEY,
    space_id VARCHAR(255) NOT NULL,
    graph_uri VARCHAR(500),
    graph_name VARCHAR(255),
    created_time TIMESTAMP,
    UNIQUE (space_id, graph_uri)
)
```

The existing schema is already perfect for auto-registration.

### DualWriteCoordinator Already Has Access

The DualWriteCoordinator already has:
- `self.postgresql_impl` - Access to PostgreSQL operations
- Can access graph manager via: `postgresql_impl.get_space_impl().get_graph_manager()`

## Proposed Solution

### Strategy: Automatic Graph Registration on Data Insert

Automatically register graphs in the `graph` table when data is first inserted, using an "upsert" pattern (insert if not exists).

### Implementation Approach

#### 1. Add Graph Auto-Registration to DualWriteCoordinator

**Location**: `dual_write_coordinator.py`

**New Method**: `_ensure_graph_registered()`
```python
async def _ensure_graph_registered(self, space_id: str, graph_uri: str) -> bool:
    """
    Ensure graph is registered in PostgreSQL graph table.
    Uses INSERT ... ON CONFLICT DO NOTHING for idempotent operation.
    
    Args:
        space_id: Space identifier
        graph_uri: Graph URI to register
        
    Returns:
        True if graph is registered (new or existing), False on error
    """
```

**Integration Points**:

1. **In `add_quads()` method** (line 177):
   - Extract unique graph URIs from quads
   - Call `_ensure_graph_registered()` for each unique graph
   - Do this BEFORE PostgreSQL transaction begins
   - Failure to register graph should NOT fail the data insert

2. **In `execute_sparql_update()` method** (line 44):
   - Extract graph URIs from parsed SPARQL operation
   - Call `_ensure_graph_registered()` for each graph
   - Do this BEFORE executing the dual-write operation

#### 2. Graph URI Extraction Helper

**New Method**: `_extract_graph_uris_from_quads()`
```python
def _extract_graph_uris_from_quads(self, quads: List[tuple]) -> List[str]:
    """
    Extract unique graph URIs from quad tuples.
    
    Args:
        quads: List of quad tuples (subject, predicate, object, graph)
        
    Returns:
        List of unique graph URI strings (excluding 'default')
    """
```

**Logic**:
- Iterate through quads
- Extract 4th element (graph URI)
- Filter out 'default' graph (no registration needed)
- Return unique graph URIs as list

#### 3. Graph URI Extraction from SPARQL Operations

**Enhance SPARQLUpdateParser** to return graph URIs:

```python
async def parse_update_operation(self, space_id: str, sparql_update: str) -> Dict[str, Any]:
    """
    Returns:
        Dictionary containing:
        - operation_type: str
        - insert_triples: List[tuple]
        - delete_triples: List[tuple]
        - graph_uris: List[str]  # NEW: Extracted graph URIs
        - raw_update: str
    """
```

**Extraction Methods**:
- Reuse existing `_extract_graph_from_delete_query()` (line 584)
- Add `_extract_graph_from_insert_query()` for INSERT operations
- Extract from both INSERT and DELETE clauses
- Return unique list of graph URIs

#### 4. PostgreSQL Graph Registration Query

**Use INSERT ... ON CONFLICT DO NOTHING**:
```sql
INSERT INTO graph (space_id, graph_uri, graph_name, created_time)
VALUES ($1, $2, $3, $4)
ON CONFLICT (space_id, graph_uri) DO NOTHING
```

**Benefits**:
- Idempotent - safe to call multiple times
- No error if graph already exists
- Atomic operation
- No separate SELECT check needed

#### 5. Graph Name Generation

**Auto-generate graph names from URIs**:
```python
def _generate_graph_name(self, graph_uri: str) -> str:
    """
    Generate a human-readable graph name from URI.
    Clips to max field size (255 characters).
    
    Examples:
        urn:multi_org_crud_graph -> multi_org_crud_graph
        http://example.org/graphs/my_graph -> my_graph
        haley:test_graph -> test_graph
    """
    # Extract last segment after '/' or ':'
    if '/' in graph_uri:
        name = graph_uri.split('/')[-1]
    elif ':' in graph_uri:
        name = graph_uri.split(':')[-1]
    else:
        name = graph_uri
    
    # Clip to max field size (graph_name VARCHAR(255))
    return name[:255] if name else graph_uri[:255]
```

**Logic**:
- Extract last segment after `/` or `:`
- Use as graph name
- Fallback to full URI if extraction fails
- **Clip to 255 characters** (max size of `graph_name` field)

## Implementation Steps

### Phase 1: Core Auto-Registration (Essential)

1. **Add `_ensure_graph_registered()` to DualWriteCoordinator**
   - Implement INSERT ... ON CONFLICT query
   - Add error handling and logging
   - Return success/failure boolean

2. **Add `_extract_graph_uris_from_quads()` helper**
   - Extract unique graph URIs from quad tuples
   - Filter out 'default' graph
   - Handle edge cases (empty lists, malformed quads)

3. **Integrate into `add_quads()` method**
   - Extract graph URIs before transaction
   - Register each unique graph
   - Log registration attempts
   - Continue with data insert even if registration fails

4. **Add graph_uris to SPARQLUpdateParser result**
   - Modify `parse_update_operation()` return value
   - Extract graph URIs from INSERT/DELETE clauses
   - Return as part of parsed operation dict

5. **Integrate into `execute_sparql_update()` method**
   - Extract graph URIs from parsed operation
   - Register each unique graph
   - Continue with SPARQL execution

### Phase 2: Enhanced Features (Optional)

6. **Add logging/metrics**
   - Track graph registration attempts
   - Monitor registration failures
   - Useful for debugging and monitoring

## Error Handling Strategy

### Registration Failures Should Not Block Data Insert

**Principle**: Graph registration is metadata management, not critical for data integrity.

**Handling**:
1. Log warning if graph registration fails
2. Continue with data insert operation
3. Graph can be manually registered later if needed
4. Subsequent inserts will retry registration

**Rationale**:
- Data insert is the primary operation
- Graph table is for discovery/listing
- Missing graph record doesn't affect data storage or queries
- Auto-retry on next insert provides self-healing

### Duplicate Registration Attempts

**Handled by ON CONFLICT DO NOTHING**:
- Multiple inserts to same graph = multiple registration attempts
- PostgreSQL handles deduplication automatically
- No performance impact (index lookup is fast)
- No error thrown on duplicate

## Testing Strategy

### Unit Tests

1. **Test `_ensure_graph_registered()`**
   - New graph registration
   - Duplicate registration (idempotent)
   - Invalid graph URI handling
   - Database error handling

2. **Test `_extract_graph_uris_from_quads()`**
   - Single graph extraction
   - Multiple unique graphs
   - Default graph filtering
   - Empty quad list
   - Malformed quads

3. **Test graph URI extraction from SPARQL**
   - INSERT DATA with GRAPH
   - DELETE WHERE with GRAPH
   - INSERT/DELETE combined
   - Multiple graphs in one query

### Integration Tests

1. **Test auto-registration in add_quads()**
   - Insert data to new graph
   - Verify graph appears in list_graphs()
   - Verify graph metadata (name, created_time)

2. **Test auto-registration in SPARQL UPDATE**
   - Execute INSERT DATA with new graph
   - Verify graph registration
   - Execute DELETE/INSERT with new graph

3. **Test multi-graph operations**
   - Insert data to multiple graphs in one operation
   - Verify all graphs registered
   - Check for duplicate registrations

4. **Test existing multi-org CRUD test**
   - Should now pass "List and Verify Graphs" test
   - Graph `urn:multi_org_crud_graph` should be found
   - Get graph info should succeed

## Benefits

1. **Eliminates manual graph creation step** - graphs auto-register on first use
2. **Fixes "List graphs" API** - all graphs with data are discoverable
3. **Improves developer experience** - one less API call to remember
4. **Self-healing** - missing graph records auto-repair on next insert
5. **Idempotent** - safe to call repeatedly, no side effects
6. **Minimal overhead** - single INSERT query per unique graph per operation
7. **Backward compatible** - manual create_graph() still works

## Risks and Mitigations

### Risk 1: Performance Impact
- **Mitigation**: Use ON CONFLICT DO NOTHING (fast index lookup)
- **Mitigation**: Only register unique graphs per operation
- **Mitigation**: Registration happens outside transaction

### Risk 2: Graph Name Collisions
- **Mitigation**: Auto-generated names are for display only
- **Mitigation**: Graph URI is the primary key
- **Mitigation**: Manual create_graph() can override name

### Risk 3: Orphaned Graph Records
- **Mitigation**: Clear/drop operations already handle graph table
- **Mitigation**: Space deletion removes all graph records
- **Mitigation**: No impact on data integrity

## Success Criteria

1. ✅ Multi-org CRUD test "List and Verify Graphs" passes
2. ✅ Graph auto-registers on first INSERT operation
3. ✅ list_graphs() returns all graphs with data
4. ✅ get_graph() succeeds for auto-registered graphs
5. ✅ No performance degradation on insert operations
6. ✅ Idempotent - multiple inserts don't create duplicates
7. ✅ Error handling - registration failure doesn't block inserts

## Next Steps

1. **Implement Phase 1 core auto-registration**
2. **Add unit tests for new methods**
3. **Run integration tests (multi-org CRUD)**
4. **Verify "List graphs" test passes**
