# KGEntitiesEndpoint Test Suite

This directory contains comprehensive tests for the KGEntitiesEndpoint with VitalSigns integration using direct endpoint testing.

## Prerequisites

1. **Fuseki Server**: Running on `http://localhost:3030`
2. **VitalGraph Dependencies**: Installed in the environment

### Starting Fuseki Server

```bash
# Download and start Fuseki (if not already running)
# Fuseki should be configured to accept datasets dynamically
./fuseki-server --port=3030
```

**Note**: No VitalGraph server needs to be running - the test instantiates the app components directly.

## Installation

No additional dependencies required - the test uses VitalGraph's existing dependencies:

```bash
# Ensure you're in the vitalgraph environment with all dependencies installed
# No additional pip install needed
```

## Running Tests

### Basic Test Run

```bash
# From the test directory
python test_kgentities_endpoint.py
```

### From Project Root

```bash
# From the vital-graph root directory
python test_scripts/kg_endpoint/test_kgentities_endpoint.py
```

### Custom Fuseki URL

You can modify the Fuseki URL in the `main()` function:

```python
fuseki_url = "http://localhost:3030"  # Fuseki server
```

## Test Architecture

This test suite uses **direct endpoint testing** rather than HTTP requests:

1. **VitalGraphImpl**: Instantiated with Fuseki backend configuration
2. **SpaceManager**: Retrieved from VitalGraphImpl for space operations
3. **KGEntitiesEndpoint**: Instantiated directly with space manager and mock auth
4. **Direct Method Calls**: Tests call endpoint methods directly

## Test Structure

### Current Tests

1. **Space Management Tests**
   - ✅ Create test space with Fuseki backend
   - ✅ List spaces and verify creation
   - ✅ Delete test space
   - ✅ Verify space deletion

2. **Endpoint Initialization Tests**
   - ✅ Verify KGEntitiesEndpoint properly initialized
   - ✅ Verify VitalSigns integration components loaded

### Planned Tests (Coming Soon)

3. **Entity CRUD Operations**
   - Create entities with JSON-LD via `_create_or_update_entities()`
   - Read entities via `_list_entities()` and `_get_entity_by_uri()`
   - Update entities with validation via `_create_or_update_entities()`
   - Delete entities via `_delete_entity_by_uri()` and `_delete_entities_by_uris()`

4. **VitalSigns Integration Tests**
   - JSON-LD to VitalSigns conversion validation
   - Property casting verification (`str(entity.URI)`)
   - Triple conversion accuracy
   - Backend SPARQL operations

5. **Error Handling Tests**
   - Invalid JSON-LD handling
   - Missing entity validation
   - Duplicate entity creation
   - Backend connection failures

## Test Configuration

The test suite uses:

- **Test Space ID**: `test_space_{random_id}` (auto-generated)
- **Test Graph ID**: `test_graph`
- **Backend**: Fuseki with dynamic dataset creation
- **Auth**: Mock auth dependency for testing
- **Cleanup**: Automatic test space deletion after each run

## Expected Output

```
🧪 KGEntitiesEndpoint Test Suite
Fuseki URL: http://localhost:3030
============================================================
🔧 Setting up VitalGraph app with Fuseki backend...
✅ VitalGraph app setup completed
🧪 Testing Space Management Operations
Using test space ID: test_space_a1b2c3d4
✅ PASS Create Test Space
✅ PASS List and Verify Spaces
✅ PASS Delete Test Space
✅ PASS Verify Space Deletion
✅ PASS Space Management
🧪 Testing Entity CRUD Operations
✅ PASS Entity Endpoint Initialization
============================================================
📊 Test Results Summary:
  Space Management: ✅ PASSED
  Entity CRUD Operations: ✅ PASSED
------------------------------------------------------------
🎉 All tests PASSED!
```

## Advantages of Direct Testing

1. **No Server Required**: Tests run without starting VitalGraph server
2. **Faster Execution**: Direct method calls are faster than HTTP requests
3. **Better Debugging**: Direct access to internal state and exceptions
4. **Isolated Testing**: Each test run is completely isolated
5. **VitalSigns Integration**: Direct testing of VitalSigns conversion patterns

## Troubleshooting

### Common Issues

1. **Fuseki Connection Refused**
   - Ensure Fuseki server is running on port 3030
   - Check Fuseki accepts dynamic dataset creation

2. **Import Errors**
   - Ensure you're in the correct Python environment
   - Verify VitalGraph dependencies are installed

3. **Space Creation Fails**
   - Check Fuseki server logs
   - Verify Fuseki configuration allows dataset creation

### Debug Mode

Add debug logging to see detailed operations:

```python
logging.getLogger("vitalgraph").setLevel(logging.DEBUG)
```

## Next Steps

Once the basic space management tests pass, we'll add:

1. Entity creation and validation tests using `_create_or_update_entities()`
2. VitalSigns integration verification
3. Backend SPARQL operation tests
4. Error handling and edge case tests
5. Performance tests with large datasets
