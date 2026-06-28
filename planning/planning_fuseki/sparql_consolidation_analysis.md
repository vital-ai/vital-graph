# SPARQL Query Consolidation Analysis

## Overview
Analysis of files containing SPARQL queries to identify consolidation opportunities using the centralized `GraphObjectRetriever`.

## Already Migrated (Phase 2 Complete) ✅

### 1. kg_backend_utils.py (5 methods)
- ✅ `get_entity` - Uses `GraphObjectRetriever.get_object_triples`
- ✅ `get_entity_graph` - Uses `GraphObjectRetriever.get_entity_graph`
- ✅ `get_objects_by_uris` - Uses `GraphObjectRetriever.get_objects_by_uris`
- ✅ `get_entity_by_reference_id` - Uses `GraphObjectRetriever.get_entity_by_reference_id`
- ✅ `get_entity_graph_by_reference_id` - Uses `GraphObjectRetriever.get_entity_graph_by_reference_id`

### 2. kgtypes_read_impl.py (3 methods)
- ✅ `get_kgtype_by_uri` - Uses `GraphObjectRetriever.get_object_triples`
- ✅ `get_kgtypes_by_uris` - Uses `GraphObjectRetriever.get_objects_by_uris`
- ✅ `list_kgtypes` - Uses `GraphObjectRetriever.list_objects`

### 3. kgrelations_read_impl.py (2 methods)
- ✅ `get_relation_by_uri` - Uses `GraphObjectRetriever.get_object_triples`
- ✅ `list_relations` - Uses `GraphObjectRetriever.list_objects` with property filters

## Phase 3: Pending Migration

### High Priority - Direct Consolidation Candidates

#### 1. kgentity_list_impl.py
**Current State:**
- `list_entities()` - Custom SPARQL with entity type filtering and search
- `_get_total_count()` - Count query for pagination
- `_get_entities_page()` - Two-phase: SELECT entity URIs, then retrieve objects
- `_build_count_query()` - Builds count SPARQL
- `_build_simple_entities_query()` - Simple entity properties
- `_build_entity_graph_query()` - Entity + frames + slots

**Consolidation Opportunity:**
- Can use `GraphObjectRetriever.list_objects()` with:
  - Type URI: `http://vital.ai/ontology/haley-ai-kg#KGEntity`
  - Property filter: `hasKGEntityType` for entity_type_uri
  - Search: hasName filtering
  - Pagination: page_size, offset
  - Count: include_count=True

**Complexity:** Medium
- Basic listing can be migrated directly
- `include_entity_graph` mode requires additional logic (get entity graph for each result)

#### 2. kgframe_query_impl.py
**Current State:**
- `list_frames()` - Lists frames with filtering by frame_type, entity_uri, parent_frame_uri
- `_build_frame_query()` - Builds SPARQL with multiple filters

**Consolidation Opportunity:**
- Can use `GraphObjectRetriever.list_objects()` with:
  - Type URI: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
  - Property filters:
    - `hasKGFrameType` for frame_type
    - `hasKGGraphURI` for entity_uri
    - Edge filtering for parent_frame_uri

**Complexity:** Medium
- Parent frame filtering requires edge traversal (more complex)

### Medium Priority - Partial Consolidation Candidates

#### 3. kg_sparql_query.py
**Current State:**
- `get_entity_frames()` - Complex frame listing with pagination
- `get_individual_frame()` - Single frame retrieval with frame graph
- `get_specific_frame_graphs()` - Batch frame retrieval with validation
- `get_all_triples_for_subjects()` - Batch triple retrieval
- `validate_entity_frame_relationships()` - Validation queries

**Consolidation Opportunity:**
- `get_all_triples_for_subjects()` could use `GraphObjectRetriever.get_objects_by_uris()`
- Other methods have complex multi-phase logic with validation that may not benefit

**Complexity:** High
- Heavy validation and security logic
- Multi-phase queries with ownership checks
- May not be worth migrating due to complexity

#### 4. kgentity_frame_discovery_impl.py
**Current State:**
- `discover_entity_frames()` - Finds frames belonging to entity
- Uses SPARQL to find frames with `hasKGGraphURI` matching entity

**Consolidation Opportunity:**
- Could use `GraphObjectRetriever.list_objects()` with:
  - Type URI: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
  - Property filter: `hasKGGraphURI` = entity_uri

**Complexity:** Low
- Simple query pattern, good candidate

#### 5. kgentity_frame_delete_impl.py
**Current State:**
- `delete_entity_frames()` - Validates ownership then deletes
- Uses SPARQL to find frames and validate entity-frame relationships

**Consolidation Opportunity:**
- Validation phase could use `GraphObjectRetriever.list_objects()` to find frames
- Deletion phase is already using backend delete operations

**Complexity:** Medium
- Validation logic could be simplified

#### 6. kgentity_delete_impl.py
**Current State:**
- `delete_entity_graph()` - Finds all objects with `hasKGGraphURI` and deletes
- Uses SPARQL SELECT to find URIs

**Consolidation Opportunity:**
- Could use `GraphObjectRetriever.list_objects()` with:
  - Property filter: `hasKGGraphURI` = entity_uri
  - No type filtering (get all objects in entity graph)

**Complexity:** Low
- Simple query pattern

#### 7. kgentity_update_impl.py
**Current State:**
- `update_entity()` - Finds existing entity data before update
- Uses SPARQL to get entity + related objects via `hasKGGraphURI`

**Consolidation Opportunity:**
- Could use `GraphObjectRetriever.get_entity_graph()` (already available!)

**Complexity:** Low
- Already have the method, just need to use it

#### 8. kgentity_frame_update_impl.py
**Current State:**
- `update_entity_frames()` - Validates frame ownership before update
- Uses SPARQL to validate frames belong to entity

**Consolidation Opportunity:**
- Validation phase could use `GraphObjectRetriever.list_objects()` with property filters

**Complexity:** Medium
- Complex ownership validation logic

### Low Priority - Keep As-Is (Specialized Logic)

#### 9. kgframe_graph_impl.py
**Current State:**
- `get_frame_graph()` - Gets complete frame graph using `hasFrameGraphURI`
- `_build_frame_graph_query()` - Builds specialized frame graph query
- `_build_frame_graph_delete_query()` - Deletion query

**Reason to Keep:**
- Specialized frame graph retrieval logic
- Uses `hasFrameGraphURI` grouping property
- Could add to GraphObjectRetriever as `get_frame_graph()` method if needed

#### 10. kgslot_update_impl.py
**Current State:**
- `update_slots()` - Finds existing slots before update
- Uses SPARQL to validate slot ownership

**Reason to Keep:**
- Specialized slot validation logic
- Relatively simple, not worth migrating

#### 11. kgtypes_delete_impl.py
**Current State:**
- `delete_kgtypes()` - Simple deletion by URI
- Uses backend delete operations, minimal SPARQL

**Reason to Keep:**
- Already using backend operations efficiently

#### 12. kgtypes_update_impl.py
**Current State:**
- `update_kgtypes()` - Finds existing types before update
- Uses backend get operations

**Reason to Keep:**
- Already using backend operations efficiently

## Consolidation Strategy

### Phase 3A: High-Value Migrations
1. **kgentity_list_impl.py** - Migrate `list_entities()` to use `GraphObjectRetriever.list_objects()`
2. **kgentity_frame_discovery_impl.py** - Migrate to use `GraphObjectRetriever.list_objects()`
3. **kgentity_delete_impl.py** - Migrate to use `GraphObjectRetriever.list_objects()`
4. **kgentity_update_impl.py** - Use existing `GraphObjectRetriever.get_entity_graph()`

### Phase 3B: Medium-Value Migrations
5. **kgframe_query_impl.py** - Migrate `list_frames()` to use `GraphObjectRetriever.list_objects()`
6. **kgentity_frame_delete_impl.py** - Migrate validation to use `GraphObjectRetriever.list_objects()`
7. **kgentity_frame_update_impl.py** - Migrate validation to use `GraphObjectRetriever.list_objects()`

### Phase 3C: Optional Enhancements
8. **kg_sparql_query.py** - Migrate `get_all_triples_for_subjects()` to use `GraphObjectRetriever.get_objects_by_uris()`
9. **kgframe_graph_impl.py** - Consider adding `get_frame_graph()` to GraphObjectRetriever

## Potential New GraphObjectRetriever Methods

Based on analysis, these methods could be added to GraphObjectRetriever:

1. **`list_objects_by_property()`** - List objects by single property filter (simplified version of list_objects)
2. **`get_frame_graph()`** - Get complete frame graph using hasFrameGraphURI
3. **`get_entity_components()`** - Get all objects with hasKGGraphURI = entity_uri (for deletion)

## Benefits of Consolidation

1. **Consistency**: All retrieval operations use same patterns
2. **Maintainability**: Single place to update SPARQL query logic
3. **Testing**: Centralized testing of retrieval patterns
4. **Performance**: Optimized query patterns in one place
5. **Error Handling**: Consistent error handling and logging

## Estimated Impact

- **High Priority (4 files)**: ~8 methods, significant code reduction
- **Medium Priority (3 files)**: ~6 methods, moderate code reduction
- **Total Potential**: ~14 methods across 7 files could be migrated
- **Code Reduction**: Estimated 500-800 lines of duplicate SPARQL query code

## Critical: kg_sparql_utils.py and kg_sparql_query.py Redundancy Analysis

### Overview
These two files contain significant redundant code that overlaps with `GraphObjectRetriever` and each other. Major consolidation opportunity identified.

### kg_sparql_utils.py (692 lines)

**Utility Methods (Keep - Used Across Codebase):**
1. `extract_count_from_results()` - Extract count from SPARQL results ✅
2. `extract_uris_from_results()` - Extract URIs from bindings ✅
3. `extract_subject_uris_from_results()` - Wrapper for subject URIs ✅
4. `build_search_filter()` - Build text search filters ✅
5. `build_pagination_clause()` - LIMIT/OFFSET clause ✅
6. `build_graph_clause()` - GRAPH clause ✅
7. `escape_sparql_string()` - String escaping ✅
8. `build_uri_reference()` - URI wrapping in angle brackets ✅
9. `build_prefixes()` - Standard SPARQL prefixes ✅
10. `validate_sparql_results()` - Results structure validation ✅
11. `build_type_filter()` - Type filter clause ✅
12. `build_grouping_uri_filter()` - Grouping URI filter ✅
13. `extract_triples_from_sparql_results()` - **DUPLICATE** with GraphObjectRetriever ⚠️
14. `extract_frame_uris_from_results()` - Frame-specific extraction ✅
15. `convert_triples_to_vitalsigns_frames()` - VitalSigns conversion ✅

**KGSparqlQueryBuilder Class (277 lines) - MAJOR REDUNDANCY:**

1. **`build_frame_discovery_query()`** (lines 410-441)
   - **REDUNDANT**: Can use `GraphObjectRetriever.list_objects()` with:
     - Type: `KGFrame`
     - Property filter: `hasKGGraphURI` = entity_uri
     - Search, pagination built-in
   - **Action**: MIGRATE to use GraphObjectRetriever

2. **`build_frame_count_query()`** (lines 443-468)
   - **REDUNDANT**: GraphObjectRetriever.list_objects() with `include_count=True`
   - **Action**: REMOVE - use GraphObjectRetriever

3. **`build_frame_graph_query()`** (lines 470-526)
   - **SPECIALIZED**: Gets frame + objects with `hasFrameGraphURI`
   - **Action**: Could add `get_frame_graph()` to GraphObjectRetriever
   - **Complexity**: Medium - specialized grouping property logic

4. **`build_frame_deletion_count_query()`** (lines 528-554)
   - **SPECIALIZED**: Deletion-specific count query
   - **Action**: Keep - deletion logic is specialized

5. **`build_frame_deletion_query()`** (lines 556-588)
   - **SPECIALIZED**: DELETE query (not retrieval)
   - **Action**: Keep - deletion operations

6. **`build_entity_graphs_query()`** (lines 590-642)
   - **REDUNDANT**: Can use `GraphObjectRetriever.list_objects()` with:
     - Property filter: `hasKGGraphURI` matching entity
     - Type filter for entity types
     - Search, pagination built-in
   - **Action**: MIGRATE to use GraphObjectRetriever

7. **`build_list_entities_query()`** (lines 644-692)
   - **REDUNDANT**: Can use `GraphObjectRetriever.list_objects()` with:
     - Type: `KGEntity` (or specific entity type)
     - Search by hasName
     - Pagination built-in
   - **Action**: MIGRATE to use GraphObjectRetriever

### kg_sparql_query.py (801 lines)

**KGSparqlQueryProcessor Class - Method Analysis:**

1. **`convert_query_criteria_to_sparql()`** (lines 34-101)
   - **SPECIALIZED**: Criteria conversion for complex queries
   - **Action**: Keep - complex query logic

2. **`execute_entity_query()`** (lines 103-170)
   - **SPECIALIZED**: Complex query execution with criteria
   - **Action**: Keep - uses specialized query builder

3. **`get_entity_frames()`** (lines 172-203)
   - **WRAPPER**: Delegates to `_list_entity_frames()` or `_get_specific_frames()`
   - **Action**: Review after migrating underlying methods

4. **`_list_entity_frames()`** (lines 205-234)
   - **REDUNDANT**: Uses `KGSparqlQueryBuilder.build_frame_discovery_query()`
   - **Action**: MIGRATE to use `GraphObjectRetriever.list_objects()`
   - **Replacement**:
     ```python
     triples, total_count = await retriever.list_objects(
         space_id, graph_id, 
         type_uris=["http://vital.ai/ontology/haley-ai-kg#KGFrame"],
         property_filters={"http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI": entity_uri},
         search=search,
         page_size=page_size,
         offset=offset,
         include_count=True
     )
     ```

5. **`_get_specific_frames()`** (lines 236-264)
   - **REDUNDANT**: Uses `build_frame_graph_query()`
   - **Action**: Could use `GraphObjectRetriever.get_frame_graph()` (if added)

6. **`get_individual_frame()`** (lines 266-327)
   - **REDUNDANT**: Uses `build_frame_graph_query()`
   - **Action**: Could use `GraphObjectRetriever.get_frame_graph()` (if added)

7. **`delete_frame()`** (lines 329-365)
   - **SPECIALIZED**: Deletion operations
   - **Action**: Keep - deletion logic

8. **`validate_entity_frame_relationships()`** (lines 367-456)
   - **SPECIALIZED**: Complex validation with ASK queries
   - **Action**: Keep - validation logic is specialized

9. **`get_specific_frame_graphs()`** (lines 458-586)
   - **COMPLEX**: Two-phase retrieval with validation
   - **PARTIAL REDUNDANCY**: Uses `get_individual_frame()` which could be migrated
   - **Action**: Keep wrapper, migrate underlying calls

10. **`get_all_triples_for_subjects()`** (lines 588-656)
    - **REDUNDANT**: Can use `GraphObjectRetriever.get_objects_by_uris()`
    - **Action**: MIGRATE to use GraphObjectRetriever
    - **Current**: Batched SPARQL with IN clause
    - **Replacement**: Direct call to `get_objects_by_uris()`

11. **`get_entity_frames()` (duplicate method)** (lines 658-710+)
    - **REDUNDANT**: Another frame listing method
    - **Action**: CONSOLIDATE with other frame methods

### Redundancy Summary

**Immediate Consolidation Opportunities:**

1. **KGSparqlQueryBuilder Methods → GraphObjectRetriever:**
   - `build_frame_discovery_query()` → `list_objects()` with filters
   - `build_frame_count_query()` → `list_objects(include_count=True)`
   - `build_entity_graphs_query()` → `list_objects()` with property filter
   - `build_list_entities_query()` → `list_objects()` with type filter

2. **KGSparqlQueryProcessor Methods → GraphObjectRetriever:**
   - `_list_entity_frames()` → `list_objects()`
   - `get_all_triples_for_subjects()` → `get_objects_by_uris()`

3. **New GraphObjectRetriever Method Needed:**
   - `get_frame_graph(frame_uri, include_frame_graph=True)` - Get frame + objects with `hasFrameGraphURI`

**Code Reduction Estimate:**
- **KGSparqlQueryBuilder**: ~200 lines can be removed (4 methods)
- **KGSparqlQueryProcessor**: ~150 lines can be simplified (3 methods)
- **Total**: ~350 lines of redundant SPARQL query code

**Files That Use These:**
- `kgentities_endpoint.py` - Heavy user of KGSparqlQueryProcessor
- `kgentity_frame_discovery_impl.py` - Could use GraphObjectRetriever instead
- `kgframe_query_impl.py` - Could use GraphObjectRetriever instead

### kg_validation_utils.py (637 lines)

**Overview:**
This file contains validation logic for KG entities, frames, and relationships. It has **minimal redundancy** with GraphObjectRetriever but contains **SPARQL queries that could be migrated**.

**Class Analysis:**

#### 1. KGEntityValidator (273 lines)
- **Purpose**: Structure and property validation for entities, frames, slots
- **Methods**: All validation logic (no SPARQL queries)
- **Action**: **KEEP AS-IS** - Pure validation logic, no retrieval redundancy

#### 2. KGGroupingURIManager (125 lines)
- **Purpose**: Set and validate grouping URIs (kGGraphURI, frameGraphURI)
- **Methods**: Property manipulation and validation
- **Action**: **KEEP AS-IS** - No SPARQL queries, pure object manipulation

#### 3. KGHierarchicalFrameValidator (237 lines)
- **Purpose**: Validate hierarchical frame relationships using SPARQL
- **SPARQL Queries**: Contains validation queries that could potentially use GraphObjectRetriever

**Methods with SPARQL Queries:**

1. **`validate_parent_frame()`** (lines 415-498)
   - **Current**: Uses ASK query to check if frame exists and belongs to entity
   - **Query Pattern**: Check frame type + hasKGGraphURI property
   - **Potential Migration**: Could use `GraphObjectRetriever.list_objects()` with filters
   - **Complexity**: Low - simple existence check
   - **Action**: **CONSIDER MIGRATION** - Could simplify to retrieval check
   - **Alternative**: 
     ```python
     triples, count = await retriever.list_objects(
         space_id, graph_id,
         type_uris=["http://vital.ai/ontology/haley-ai-kg#KGFrame"],
         property_filters={"http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI": entity_uri},
         include_count=True
     )
     # Check if parent_frame_uri is in results
     ```

2. **`validate_frame_ownership()`** (lines 500-549)
   - **Current**: Uses ASK queries to validate frame ownership
   - **Query Pattern**: Check frame type + hasKGGraphURI for multiple frames
   - **Potential Migration**: Could use `GraphObjectRetriever.list_objects()` once and check results
   - **Complexity**: Low - batch existence check
   - **Action**: **CONSIDER MIGRATION** - More efficient with single query
   - **Alternative**:
     ```python
     triples, count = await retriever.list_objects(
         space_id, graph_id,
         type_uris=["http://vital.ai/ontology/haley-ai-kg#KGFrame"],
         property_filters={"http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI": entity_uri},
         include_count=False
     )
     # Extract frame URIs from triples and compare with frame_uris list
     ```

3. **`validate_frame_hierarchy()`** (lines 551-636)
   - **Current**: Orchestrates validation using above methods + edge connection checks
   - **Query Pattern**: ASK queries for Edge_hasKGFrame connections
   - **Action**: **KEEP AS-IS** - Complex validation logic with edge checks
   - **Reason**: Edge connection validation is specialized, not simple retrieval

**Redundancy Assessment:**

**Minimal Redundancy:**
- Only 2 methods (`validate_parent_frame`, `validate_frame_ownership`) could potentially use GraphObjectRetriever
- These are **validation** operations, not retrieval operations
- Current ASK queries are appropriate for existence checks
- Migration would not provide significant benefit

**Recommendation: KEEP AS-IS**
- Validation logic is distinct from retrieval logic
- ASK queries are appropriate for existence checks
- No significant code duplication with GraphObjectRetriever
- Migration would add complexity without clear benefit

**Code Reduction Potential:** ~0 lines (validation logic should remain separate)

### Consolidation Action Plan

**Phase 3A - High Priority:**
1. Add `get_frame_graph()` method to GraphObjectRetriever
2. Migrate `get_all_triples_for_subjects()` to use `get_objects_by_uris()`
3. Migrate `_list_entity_frames()` to use `list_objects()`
4. Remove redundant methods from KGSparqlQueryBuilder

**Phase 3B - Medium Priority:**
5. Migrate files using KGSparqlQueryBuilder to use GraphObjectRetriever
6. Consolidate duplicate `get_entity_frames()` methods
7. Update kgentities_endpoint.py to use GraphObjectRetriever directly

**Phase 3C - Optional (Low Priority):**
8. Consider optimizing `validate_frame_ownership()` to use single list_objects query instead of multiple ASK queries

**Benefits:**
- Eliminate ~350 lines of duplicate code
- Consistent query patterns across codebase
- Single source of truth for SPARQL retrieval
- Easier maintenance and testing

**Files to Keep As-Is:**
- **kg_validation_utils.py** - Validation logic is distinct from retrieval, minimal redundancy

## Test Coverage Required

After each migration:
- Run full test suite (109+ tests)
- Run endpoint-specific tests
- Verify pagination works correctly
- Verify filtering works correctly
- Verify count queries work correctly
