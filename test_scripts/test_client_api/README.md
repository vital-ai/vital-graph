# Client API Test Suite

This directory contains tests for the VitalGraph Client API functionality.

## Test Files

### `test_grouping_uri_functionality.py`
Tests the grouping URI management functionality in client API methods:

- **Method Signatures**: Verifies correct parameters for KGEntities and KGFrames methods
- **Parameter Defaults**: Ensures optional parameters have correct default values  
- **Method Calls**: Tests that methods accept correct parameters (signature validation)
- **Grouping URI Concepts**: Documents and verifies understanding of grouping URI rules

#### Key Functionality Tested:

**KGEntities Methods:**
- `create_kgentities()` - No grouping URI parameters (server extracts from document)
- `update_kgentities()` - No grouping URI parameters (server manages automatically)

**KGFrames Methods:**
- `create_kgframes()` - Requires `entity_uri` parameter for linking frames to entity
- `update_kgframes()` - Requires `entity_uri` parameter for linking frames to entity
- `create_kgframes_with_slots()` - Requires `entity_uri` parameter
- `update_kgframes_with_slots()` - Requires `entity_uri` parameter

#### Grouping URI Rules Verified:

**Entity Graph (`hasKGGraphURI`):**
- Set to entity URI for all components (entity + frames + slots + hasSlot edges + other edges)
- Server strips client-provided values and sets authoritatively
- No client parameters needed - extracted from document

**Frame Graph (`hasFrameGraphURI`):**
- Set to frame URI for frame-specific components (frame + its slots + hasSlot edges)
- Server strips client-provided values and sets authoritatively
- Client provides `entity_uri` parameter to link frames to their entity

#### Server Security Model:
- Server **strips** all client-provided grouping URIs from documents
- Server **authoritatively sets** grouping URIs based on business rules
- Client **cannot manipulate** graph relationships directly
- Prevents orphaned or incorrectly grouped components

## Running Tests

```bash
# Run the grouping URI functionality test
/opt/homebrew/anaconda3/envs/vital-graph/bin/python test_client_api/test_grouping_uri_functionality.py

# Expected output: All 5 tests should pass
# ✅ Method signatures correct
# ✅ Parameter defaults correct  
# ✅ Method calls work (fail at connection as expected)
# ✅ Grouping URI concepts verified
```

## Test Coverage

- [x] KGEntities method signatures (no grouping URI parameters)
- [x] KGFrames method signatures (entity_uri parameter required)
- [x] Optional parameter defaults (None values)
- [x] Method call parameter validation
- [x] Grouping URI assignment rules documentation
- [x] Server-side security model verification

### `test_grouping_uri_queries.py`
Tests the SPARQL query functionality for grouping URI-based graph retrieval:

- **Query Builder**: Tests SPARQL query generation for entity and frame graphs
- **Components by Type**: Tests queries that group components by ontology type
- **Graph Retriever**: Tests complete graph retrieval using grouping URIs
- **Query Structure**: Validates proper SPARQL syntax and formatting
- **Haley Ontology**: Verifies correct usage of Haley ontology prefixes

#### Key SPARQL Functionality Tested:

**Entity Graph Retrieval:**
```sparql
SELECT DISTINCT ?subject ?predicate ?object WHERE {
    GRAPH <graph_id> {
        ?subject <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <entity_uri> .
        ?subject ?predicate ?object .
    }
}
```

**Frame Graph Retrieval:**
```sparql
SELECT DISTINCT ?subject ?predicate ?object WHERE {
    GRAPH <graph_id> {
        ?subject <http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI> <frame_uri> .
        ?subject ?predicate ?object .
    }
}
```

## Running Tests

```bash
# Run the grouping URI functionality test
/opt/homebrew/anaconda3/envs/vital-graph/bin/python test_client_api/test_grouping_uri_functionality.py

# Run the SPARQL queries test
/opt/homebrew/anaconda3/envs/vital-graph/bin/python test_client_api/test_grouping_uri_queries.py

# Expected output: All tests should pass
```

## Test Coverage

- [x] KGEntities method signatures (no grouping URI parameters)
- [x] KGFrames method signatures (entity_uri parameter required)
- [x] Optional parameter defaults (None values)
- [x] Method call parameter validation
- [x] Grouping URI assignment rules documentation
- [x] Server-side security model verification
- [x] SPARQL query generation for grouping URIs
- [x] Entity graph retrieval using hasKGGraphURI
- [x] Frame graph retrieval using hasFrameGraphURI
- [x] Component type grouping queries
- [x] Haley ontology prefix usage

## Future Tests

Additional tests to add:
- Query method functionality (EntityQueryRequest/Response)
- Enhanced list methods with graph parameters
- Model serialization/deserialization
- Error handling and validation
- Mock endpoint integration tests
- Integration tests with pyoxigraph SPARQL execution
