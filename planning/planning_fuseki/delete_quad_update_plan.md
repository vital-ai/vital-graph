# Delete Entity Graph Optimization Plan
## Using Direct Quad Updates Instead of SPARQL Parsing

**Date:** 2026-02-05  
**Objective:** Eliminate the 29+ second SPARQL parsing bottleneck in delete_entity_graph operations by using the direct quad update path that bypasses SPARQL parsing entirely.

---

## Current Implementation Analysis

### Current Delete Flow (SLOW - 30+ seconds)

**File:** `vitalgraph/kg_impl/kgentity_delete_impl.py::delete_entity_graph()`

1. **Step 1:** Find subjects with `hasKGGraphURI` via SPARQL SELECT (~0.1s) ✅
2. **Step 2:** Query all triples for those subjects via SPARQL SELECT (~0.6s) ✅
3. **Step 3:** Build massive DELETE DATA SPARQL query string (~0.0s) ✅
4. **Step 4:** Call `backend.execute_sparql_update(space_id, delete_query)` ❌
   - Enters `dual_write_coordinator.execute_sparql_update()`
   - Calls `sparql_parser.parse_update_operation()` 
   - **BOTTLENECK 1:** `_extract_patterns_from_query()` - RDFLib parseUpdate/translateUpdate (~29s) ❌
   - **BOTTLENECK 2:** `_extract_delete_data_triples()` - RDFLib processor.update() (additional time) ❌
   - Extracts triples from parsed result
   - Finally deletes from PostgreSQL and Fuseki

**Total Time:** 30+ seconds (exceeds client timeout)

---

## Direct Quad Update Path Analysis

### How `add_quads()` Works (FAST - No SPARQL Parsing)

**File:** `vitalgraph/db/fuseki_postgresql/dual_write_coordinator.py::add_quads()`

**Flow:**
1. **Input:** List of quad tuples: `[(subject, predicate, object, graph), ...]`
2. **Auto-register graphs** in graph table
3. **Begin PostgreSQL transaction**
4. **Filter materialized triples** (edges that exist only in Fuseki)
5. **Write to PostgreSQL** via `_store_quads_to_postgresql()`
   - Calls `postgresql_impl.store_quads_to_postgresql()`
   - Batch inserts using `executemany()`
6. **Commit PostgreSQL transaction**
7. **Write to Fuseki** via `fuseki_manager.add_quads_to_dataset()`
   - Direct quad insertion, no SPARQL parsing
8. **Materialize edge properties** (optional)

**Key Insight:** No SPARQL parsing! Direct quad manipulation.

---

### How `remove_quads()` Works (FAST - No SPARQL Parsing)

**File:** `vitalgraph/db/fuseki_postgresql/dual_write_coordinator.py::remove_quads()`

**Flow:**
1. **Input:** List of quad tuples: `[(subject, predicate, object, graph), ...]`
2. **Begin PostgreSQL transaction**
3. **Remove from Fuseki** via `_remove_quads_from_fuseki()`
   - Calls `fuseki_manager.remove_quads_from_dataset()`
   - Direct quad deletion, no SPARQL parsing
4. **Filter materialized triples**
5. **Remove from PostgreSQL** via `_remove_quads_from_postgresql()`
   - Calls `postgresql_impl.remove_quads_from_postgresql()`
   - Batch deletes using `executemany()`
6. **Commit PostgreSQL transaction**
7. **Materialize edge properties** (cleanup)

**Key Insight:** No SPARQL parsing! Direct quad manipulation.

---

## Proposed New Delete Flow (FAST)

### Modified `delete_entity_graph()` Implementation

**File:** `vitalgraph/kg_impl/kgentity_delete_impl.py::delete_entity_graph()`

**New Flow:**
1. **Step 1:** Find subjects with `hasKGGraphURI` via SPARQL SELECT (~0.1s) ✅ **(KEEP AS-IS)**
2. **Step 2:** Query all triples for those subjects via SPARQL SELECT (~0.6s) ✅ **(KEEP AS-IS)**
3. **Step 3:** Convert triples to quad tuples (~0.0s) ✅ **(NEW)**
   ```python
   quads = []
   for s, p, o, o_type in all_triples:
       # Convert to quad tuple format
       quad = (s, p, o, graph_id)  # graph_id is already known
       quads.append(quad)
   ```
4. **Step 4:** Call `backend.remove_quads(space_id, quads)` ✅ **(NEW - BYPASSES SPARQL PARSING)**
   - Goes directly to `dual_write_coordinator.remove_quads()`
   - **NO SPARQL PARSING!**
   - Direct PostgreSQL batch delete
   - Direct Fuseki quad removal

**Expected Total Time:** ~0.7-1.0 seconds (well within 30-second timeout)

---

## Implementation Plan

### THE REAL ISSUE: `remove_rdf_quads_batch()` Doesn't Follow the Pattern!

**Current Code Analysis:**

**File:** `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_db_ops.py`

**`add_rdf_quads_batch()` (CORRECT PATTERN - line 54-56):**
```python
# Bypass SPARQL parser entirely for simple INSERT operations
# Call dual-write coordinator directly with RDFLib quads
success = await self.dual_write_coordinator.add_quads(space_id, quads)
```
✅ **NO SPARQL PARSING!** Direct call to `add_quads()`

**`remove_rdf_quads_batch()` (BROKEN PATTERN - line 94-127):**
```python
# Convert quads to SPARQL DELETE DATA format
graph_blocks = {}
for quad in quads:
    # ... build SPARQL string ...
    graph_blocks[graph].append(f"<{subject}> <{predicate}> {obj_str} .")

delete_sparql = f"""
DELETE DATA {{
    {chr(10).join(delete_blocks)}
}}
"""

# Execute via dual-write coordinator
success = await self.dual_write_coordinator.execute_sparql_update(space_id, delete_sparql)
```
❌ **BUILDS SPARQL QUERY!** Then calls `execute_sparql_update()` which triggers parsing!

---

### The Fix: Make `remove_rdf_quads_batch()` Follow the Same Pattern as `add_rdf_quads_batch()`

**File:** `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_db_ops.py::remove_rdf_quads_batch()`

**OLD CODE (lines 87-138):**
```python
async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple], 
                               transaction=None, auto_commit: bool = True) -> int:
    try:
        if not quads:
            self.logger.debug("No quads provided for removal")
            return 0
        
        self.logger.debug(f"Removing {len(quads)} RDF quads from space {space_id} via dual-write")
        
        # Convert quads to SPARQL DELETE DATA format
        graph_blocks = {}
        for quad in quads:
            # Handle tuple format: (subject, predicate, object, graph)
            if len(quad) >= 4:
                subject, predicate, obj, graph = quad[:4]
            else:
                subject, predicate, obj = quad[:3]
                graph = 'default'
            
            if graph not in graph_blocks:
                graph_blocks[graph] = []
            
            # Format object based on its type
            obj_str = self._format_sparql_term(obj)
            graph_blocks[graph].append(f"<{subject}> <{predicate}> {obj_str} .")
        
        # Build SPARQL DELETE DATA query
        delete_blocks = []
        for graph, triples in graph_blocks.items():
            triples_str = "\n                ".join(triples)
            if graph == 'default':
                delete_blocks.append(triples_str)
            else:
                delete_blocks.append(f"GRAPH <{graph}> {{\n                {triples_str}\n            }}")
        
        delete_sparql = f"""
        DELETE DATA {{
            {chr(10).join(delete_blocks)}
        }}
        """
        
        # Execute via dual-write coordinator
        success = await self.dual_write_coordinator.execute_sparql_update(space_id, delete_sparql)
        
        if success:
            self.logger.debug(f"Successfully removed {len(quads)} quads via dual-write")
            return len(quads)
        else:
            self.logger.error(f"Failed to remove quads via dual-write coordinator")
            return 0
            
    except Exception as e:
        self.logger.error(f"Error removing RDF quads batch: {e}")
        return 0
```

**NEW CODE (FOLLOW THE add_rdf_quads_batch PATTERN):**
```python
async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple], 
                               transaction=None, auto_commit: bool = True) -> int:
    """
    Remove RDF quads in batch using dual-write coordinator for consistency.
    
    Args:
        space_id: Space identifier
        quads: List of quad tuples (subject, predicate, object, graph)
        transaction: Optional transaction context (for compatibility)
        auto_commit: Whether to auto-commit (ignored, handled by dual-write coordinator)
        
    Returns:
        Number of quads successfully removed
    """
    try:
        if not quads:
            self.logger.debug("No quads provided for removal")
            return 0
        
        self.logger.debug(f"Removing {len(quads)} RDF quads from space {space_id} via dual-write")
        
        # Bypass SPARQL parser entirely for simple DELETE operations
        # Call dual-write coordinator directly with quads (SAME AS add_rdf_quads_batch!)
        success = await self.dual_write_coordinator.remove_quads(space_id, quads)
        
        if success:
            self.logger.debug(f"Successfully removed {len(quads)} quads via dual-write")
            return len(quads)
        else:
            self.logger.error(f"Failed to remove quads via dual-write coordinator")
            return 0
            
    except Exception as e:
        self.logger.error(f"Error removing RDF quads batch: {e}")
        return 0
```

**That's it!** No changes needed to `delete_entity_graph()` - it already uses the correct pattern!

---

## Testing Plan

### Test 1: Single Lead Entity Delete (Local)
**File:** `vitalgraph_client_test/test_lead_entity_graph.py`

**Expected Results:**
- Delete completes in < 5 seconds (vs 30+ seconds timeout)
- All 397 objects deleted successfully
- All 2,832 triples removed from PostgreSQL
- All triples removed from Fuseki

**Verification:**
```bash
# Run test
python vitalgraph_client_test/test_lead_entity_graph.py

# Check Docker logs for timing
docker logs vitalgraph-app 2>&1 | grep "🔥"
```

---

### Test 2: Multiple Entity Delete (Batch)
**Test:** Delete all 3 lead entities in sequence

**Expected Results:**
- Each delete completes in < 5 seconds
- No timeouts
- All data removed correctly

---

### Test 3: Production Environment
**Environment:** `VITALGRAPH_CLIENT_ENVIRONMENT=prod`

**Expected Results:**
- Delete operations complete successfully
- No 414 errors (using direct quads, not URL parameters)
- PostgreSQL checkpoints handled gracefully

---

## Rollback Plan

If issues arise, revert changes to `kgentity_delete_impl.py`:
1. Restore original Step 3-4 (build SPARQL query + execute_sparql_update)
2. Remove `remove_quads()` call
3. Git revert the commit

**Backup:** Create branch before changes:
```bash
git checkout -b feature/delete-direct-quads
```

---

## Performance Expectations

### Before Optimization
- **Step 1 (find subjects):** 0.1s
- **Step 2 (query triples):** 0.6s
- **Step 3 (build SPARQL):** 0.0s
- **Step 4 (parse + delete):** 29+ seconds ❌
- **Total:** 30+ seconds (TIMEOUT)

### After Optimization
- **Step 1 (find subjects):** 0.1s
- **Step 2 (query triples):** 0.6s
- **Step 3 (convert to quads):** 0.0s
- **Step 4 (direct delete):** 0.5-1.0s ✅
- **Total:** 1.2-1.7 seconds ✅

**Expected Improvement:** ~95% faster (30s → 1.7s)

---

## Key Benefits

1. ✅ **Eliminates SPARQL parsing bottleneck** (~29 seconds saved)
2. ✅ **Uses proven direct quad update path** (already working for add_quads)
3. ✅ **Maintains data consistency** (same dual-write coordinator)
4. ✅ **Preserves transaction safety** (PostgreSQL transactions still used)
5. ✅ **No changes to query logic** (Steps 1-2 remain unchanged)
6. ✅ **Minimal code changes** (only modify Step 3-4 in delete_entity_graph)

---

## Risks and Mitigations

### Risk 1: Quad Format Mismatch
**Risk:** Quad tuple format might differ between query results and remove_quads expectations

**Mitigation:** 
- Review quad format in `remove_quads()` implementation
- Add validation/logging in Step 3 conversion
- Test with small dataset first

### Risk 2: Graph URI Handling
**Risk:** Graph URI might need special formatting

**Mitigation:**
- Use `full_graph_uri` directly (already validated in Steps 1-2)
- Match format used in `add_quads()` operations

### Risk 3: Materialized Triples
**Risk:** Some triples might be materialized (edges) and need special handling

**Mitigation:**
- `remove_quads()` already handles materialized triple filtering
- EdgeMaterializationManager will filter them automatically

---

## Success Criteria

1. ✅ Delete entity graph completes in < 5 seconds
2. ✅ No client timeouts (30-second limit)
3. ✅ All objects deleted from PostgreSQL
4. ✅ All triples deleted from Fuseki
5. ✅ No SPARQL parsing in delete path
6. ✅ All tests pass (local and production)
7. ✅ No data consistency issues

---

## Next Steps

1. **Review this plan** with team
2. **Verify quad format** compatibility
3. **Implement Phase 1** (add remove_quads to backend adapter)
4. **Implement Phase 2** (modify delete_entity_graph)
5. **Test locally** with single entity
6. **Test with multiple entities**
7. **Deploy to production**
8. **Monitor performance** and verify improvements

---

## Notes

- **CRITICAL:** Do NOT modify `_extract_patterns_from_query()` - user explicitly forbade this
- The optimization bypasses SPARQL parsing entirely by using direct quad operations
- This approach is already proven to work for `add_quads()` operations
- The dual-write coordinator handles all consistency and transaction management
