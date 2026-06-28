# VitalGraphServiceImpl Test Suite

This directory contains comprehensive tests for the `VitalGraphServiceImpl` class, which implements the `VitalGraphService` interface using the `VitalGraphClient` backend.

## Test Structure

### Test Files

- **`test_vitalgraph_service_impl.py`** - Main unit tests using real VitalGraphClient
- **`test_integration.py`** - Integration tests for end-to-end functionality  
- **`run_tests.py`** - Test runner script with various options
- **`test_config.yaml`** - Configuration file for test environment
- **`README.md`** - This documentation file

### Test Classes

1. **TestServiceManagement** - Tests for service lifecycle and status
2. **TestServiceLifecycle** - Tests for service initialization and destruction
3. **TestHelperMethods** - Tests for internal helper methods
4. **TestGraphManagement** - Tests for graph creation, deletion, and listing

## Configuration

### Environment Variables

You can override test configuration using environment variables:

```bash
export VITALGRAPH_TEST_CONFIG="path/to/your/config.yaml"
export VITALGRAPH_TEST_SPACE_ID="your_test_space"
export VITALGRAPH_TEST_BASE_URI="http://your.domain.com/test"
export VITALGRAPH_TEST_NAMESPACE="your_test_namespace"
```

### Configuration File

The `test_config.yaml` file contains:
- Client connection settings
- Authentication configuration
- Test-specific parameters
- Backend configurations for different environments
- Feature flags for enabling/disabling test categories

## Running Tests

### Using the Test Runner

```bash
# Run unit tests only (default)
python run_tests.py

# Run with verbose output
python run_tests.py --verbose

# Run integration tests
python run_tests.py --integration

# Run all tests
python run_tests.py --all

# Run with debug logging
python run_tests.py --debug
```

### Using unittest directly

```bash
# Run all tests
python -m unittest discover -s . -p "test_*.py" -v

# Run specific test class
python -m unittest test_vitalgraph_service_impl.TestServiceManagement -v

# Run specific test method
python -m unittest test_vitalgraph_service_impl.TestServiceManagement.test_service_initialization -v
```

## Test Requirements

### Prerequisites

1. **VitalGraphClient** - The tests use the real VitalGraphClient, not mocks
2. **Configuration File** - A valid `test_config.yaml` file must exist
3. **Backend Server** - For integration tests, a running VitalGraph backend is required
4. **Test Environment** - Tests should run in an isolated test environment

### Dependencies

The tests require the following Python packages:
- `unittest` (standard library)
- `vitalgraph` (the main package being tested)
- `vitalgraph_client` (the client library)
- `vital_ai_vitalsigns` (VitalSigns library)

## Test Categories

### Unit Tests (Default)

- Test individual methods and components
- Use real VitalGraphClient but may skip tests if backend unavailable
- Focus on service logic and client integration
- Safe to run frequently during development

### Integration Tests

- Test end-to-end functionality with real backend
- Require running VitalGraph server
- Test actual data persistence and retrieval
- Should be run before releases and major changes

### Performance Tests (Future)

- Test performance characteristics
- Measure response times and throughput
- Currently disabled by default
- Will be implemented in future phases

## Test Data Management

### Cleanup

- Tests use a dedicated test namespace to avoid conflicts
- Automatic cleanup is performed after each test
- The `destroy_service()` method is called during teardown
- Test data is isolated from production data

### Safety

- Tests only run against test namespaces (containing "test")
- Configuration validation prevents accidental production runs
- All test operations are logged for traceability

## Troubleshooting

### Common Issues

1. **Config file not found**
   - Ensure `test_config.yaml` exists in the test directory
   - Check the `VITALGRAPH_TEST_CONFIG` environment variable

2. **Client connection failed**
   - Verify the backend server is running
   - Check connection settings in `test_config.yaml`
   - Ensure authentication credentials are correct

3. **Tests skipped**
   - Tests are automatically skipped if prerequisites aren't met
   - Check test output for skip reasons
   - Verify configuration and backend availability

### Debugging

1. **Enable debug logging**
   ```bash
   python run_tests.py --debug
   ```

2. **Run specific test**
   ```bash
   python -m unittest test_vitalgraph_service_impl.TestServiceManagement.test_service_initialization -v
   ```

3. **Check configuration**
   ```bash
   python -c "import yaml; print(yaml.safe_load(open('test_config.yaml')))"
   ```

## Contributing

When adding new tests:

1. Follow the existing test structure and naming conventions
2. Use the real VitalGraphClient, not mocks
3. Include proper cleanup in tearDown methods
4. Add appropriate logging for debugging
5. Update this README if adding new test categories

## Future Enhancements

- Performance benchmarking tests
- Stress testing with large datasets
- Multi-threaded test scenarios
- Automated test data generation
- Test coverage reporting
