# VitalGraph Client Configuration Refactoring Plan

## Overview
Refactor the VitalGraph **client** configuration system to use **profile-based environment variable configuration** instead of YAML config files. This follows the same approach recently implemented for the VitalGraph server, enabling easy switching between different environments (local, dev, staging, prod) using profile-prefixed environment variables.

## Current State

### Current Client Configuration File
Location: `/vitalgraphclient_config/vitalgraphclient-config.yaml`

Current structure:
```yaml
server:
  url: "http://localhost:8001"
  api_base_path: "/api/v1"
  
auth:
  username: "admin"
  password: "admin"
  
client:
  timeout: 30
  max_retries: 3
  retry_delay: 1
  use_mock_client: false
  
  mock:
    use_temp_storage: true
    filePath: null
```

### Current Client Implementation
- **Config Loader**: `vitalgraph/client/config/client_config_loader.py`
- **Client Class**: `vitalgraph/client/vitalgraph_client.py`
- **Usage Pattern**: 
  ```python
  client = VitalGraphClient(config_path="path/to/config.yaml")
  # OR
  config = VitalGraphClientConfig(config_path)
  client = VitalGraphClient(config=config)
  ```

## Architecture Decision

**No YAML Config Files** - All client configuration will come from:
1. **Profile-prefixed environment variables** (e.g., `LOCAL_CLIENT_*`, `PROD_CLIENT_*`)
2. **VITALGRAPH_CLIENT_ENVIRONMENT** variable to select profile
3. **Application defaults** (hardcoded sensible defaults in code)

**No Backward Compatibility** - YAML config files will be completely removed. This is a breaking change.

**Naming Convention**: Profile-prefixed flat structure
```
{PROFILE}_CLIENT_<SETTING>=value
```

Examples:
```bash
VITALGRAPH_CLIENT_ENVIRONMENT=local
LOCAL_CLIENT_SERVER_URL=http://localhost:8001
LOCAL_CLIENT_AUTH_USERNAME=admin
LOCAL_CLIENT_AUTH_PASSWORD=admin

PROD_CLIENT_SERVER_URL=https://api.vitalgraph.production.com
PROD_CLIENT_AUTH_USERNAME=prod_user
PROD_CLIENT_AUTH_PASSWORD=secure_password
```

## Configuration Mapping

### Server Configuration
**YAML Path** → **Environment Variable**

- `server.url` → `{PROFILE}_CLIENT_SERVER_URL`
- `server.api_base_path` → `{PROFILE}_CLIENT_API_BASE_PATH`

### Authentication Configuration
- `auth.username` → `{PROFILE}_CLIENT_AUTH_USERNAME`
- `auth.password` → `{PROFILE}_CLIENT_AUTH_PASSWORD`

### Client Settings
- `client.timeout` → `{PROFILE}_CLIENT_TIMEOUT`
- `client.max_retries` → `{PROFILE}_CLIENT_MAX_RETRIES`
- `client.retry_delay` → `{PROFILE}_CLIENT_RETRY_DELAY`
- `client.use_mock_client` → `{PROFILE}_CLIENT_USE_MOCK_CLIENT`

### Mock Client Settings
- `client.mock.use_temp_storage` → `{PROFILE}_CLIENT_MOCK_USE_TEMP_STORAGE`
- `client.mock.filePath` → `{PROFILE}_CLIENT_MOCK_FILE_PATH`

## Security Classification

### Sensitive Values (Should be in secrets/secure env vars)
- `{PROFILE}_CLIENT_AUTH_USERNAME` - Authentication username
- `{PROFILE}_CLIENT_AUTH_PASSWORD` - Authentication password

### Environment-Specific Values
- `{PROFILE}_CLIENT_SERVER_URL` - Server endpoint (changes per environment)
- `{PROFILE}_CLIENT_API_BASE_PATH` - API base path (may vary)

### Static Configuration Values (with sensible defaults)
- `{PROFILE}_CLIENT_TIMEOUT` - Default: 30
- `{PROFILE}_CLIENT_MAX_RETRIES` - Default: 3
- `{PROFILE}_CLIENT_RETRY_DELAY` - Default: 1
- `{PROFILE}_CLIENT_USE_MOCK_CLIENT` - Default: false
- `{PROFILE}_CLIENT_MOCK_USE_TEMP_STORAGE` - Default: true
- `{PROFILE}_CLIENT_MOCK_FILE_PATH` - Default: null

## Implementation Plan

### Phase 1: Update Client Config Loader

**File**: `vitalgraph/client/config/client_config_loader.py`

**Changes**:
1. Add profile environment variable support similar to server config loader
2. Implement `_get_profile_env()` method for profile-prefixed variable lookup
3. Update `_load_from_env()` to use profile-based loading
4. Remove all YAML config file loading code
5. Priority order: Profile env vars → Unprefixed env vars → Defaults

**Implementation**:
```python
class VitalGraphClientConfig:
    def __init__(self):
        self.environment = os.getenv('VITALGRAPH_CLIENT_ENVIRONMENT', 'local').upper()
        self.config_data = self._load_from_env()
        logger.info(f"Loaded client configuration from {self.environment}_CLIENT_* environment variables")
    
    def _get_profile_env(self, key: str, default: str = '') -> str:
        """Get environment variable with profile prefix."""
        # Try profile-prefixed (e.g., LOCAL_CLIENT_SERVER_URL)
        profile_key = f"{self.environment}_CLIENT_{key}"
        value = os.getenv(profile_key)
        if value is not None:
            return value
        
        # Fall back to unprefixed (e.g., CLIENT_SERVER_URL)
        unprefixed_key = f"CLIENT_{key}"
        value = os.getenv(unprefixed_key)
        if value is not None:
            return value
        
        # Use default
        return default
    
    def _load_from_env(self) -> Dict[str, Any]:
        """Load configuration from profile-prefixed environment variables."""
        return {
            'server': {
                'url': self._get_profile_env('SERVER_URL', 'http://localhost:8001'),
                'api_base_path': self._get_profile_env('API_BASE_PATH', '/api/v1')
            },
            'auth': {
                'username': self._get_profile_env('AUTH_USERNAME', 'admin'),
                'password': self._get_profile_env('AUTH_PASSWORD', 'admin')
            },
            'client': {
                'timeout': int(self._get_profile_env('TIMEOUT', '30')),
                'max_retries': int(self._get_profile_env('MAX_RETRIES', '3')),
                'retry_delay': int(self._get_profile_env('RETRY_DELAY', '1')),
                'use_mock_client': self._get_profile_env('USE_MOCK_CLIENT', 'false').lower() == 'true',
                'mock': {
                    'use_temp_storage': self._get_profile_env('MOCK_USE_TEMP_STORAGE', 'true').lower() == 'true',
                    'filePath': self._get_profile_env('MOCK_FILE_PATH', '')
                }
            }
        }
```

### Phase 2: Update Client Class

**File**: `vitalgraph/client/vitalgraph_client.py`

**Changes**:
1. Remove `config_path` parameter completely
2. Update docstring to reflect environment variable configuration only
3. Config loader will automatically use environment variables

**Implementation**:
```python
def __init__(self, *, config: Optional[VitalGraphClientConfig] = None, 
             token_expiry_seconds: Optional[int] = None,
             disable_proactive_refresh: bool = False):
    """
    Initialize the VitalGraph client.
    
    Configuration is loaded from profile-prefixed environment variables.
    Set VITALGRAPH_CLIENT_ENVIRONMENT to select profile (local, dev, staging, prod).
    
    Args:
        config: Pre-configured VitalGraphClientConfig object (optional, for testing)
        token_expiry_seconds: Optional token expiry override for testing
        disable_proactive_refresh: Skip proactive token refresh (testing only)
    
    Environment Variables (profile-prefixed):
        {PROFILE}_CLIENT_SERVER_URL: Server endpoint URL
        {PROFILE}_CLIENT_AUTH_USERNAME: Authentication username
        {PROFILE}_CLIENT_AUTH_PASSWORD: Authentication password
        {PROFILE}_CLIENT_TIMEOUT: Request timeout in seconds
        {PROFILE}_CLIENT_MAX_RETRIES: Maximum retry attempts
        
    Example:
        # Use LOCAL profile
        export VITALGRAPH_CLIENT_ENVIRONMENT=local
        export LOCAL_CLIENT_SERVER_URL=http://localhost:8001
        export LOCAL_CLIENT_AUTH_USERNAME=admin
        export LOCAL_CLIENT_AUTH_PASSWORD=admin
        client = VitalGraphClient()
        
        # Use PROD profile
        export VITALGRAPH_CLIENT_ENVIRONMENT=prod
        export PROD_CLIENT_SERVER_URL=https://api.production.com
        client = VitalGraphClient()
    """
    # ... rest of implementation
```

### Phase 3: Create Environment Variable Templates

**File**: `.env.example` (update existing)

Add client configuration section:
```bash
# =============================================================================
# VitalGraph Client Profile-Based Configuration
# =============================================================================
# Set VITALGRAPH_CLIENT_ENVIRONMENT to select which profile to use
VITALGRAPH_CLIENT_ENVIRONMENT=local

# =============================================================================
# LOCAL Client Profile Configuration
# =============================================================================
LOCAL_CLIENT_SERVER_URL=http://localhost:8001
LOCAL_CLIENT_API_BASE_PATH=/api/v1
LOCAL_CLIENT_AUTH_USERNAME=admin
LOCAL_CLIENT_AUTH_PASSWORD=admin
LOCAL_CLIENT_TIMEOUT=30
LOCAL_CLIENT_MAX_RETRIES=3
LOCAL_CLIENT_RETRY_DELAY=1
LOCAL_CLIENT_USE_MOCK_CLIENT=false
LOCAL_CLIENT_MOCK_USE_TEMP_STORAGE=true
LOCAL_CLIENT_MOCK_FILE_PATH=

# =============================================================================
# PROD Client Profile Configuration
# =============================================================================
# PROD_CLIENT_SERVER_URL=https://api.vitalgraph.production.com
# PROD_CLIENT_API_BASE_PATH=/api/v1
# PROD_CLIENT_AUTH_USERNAME=prod_user
# PROD_CLIENT_AUTH_PASSWORD=secure_prod_password
# PROD_CLIENT_TIMEOUT=60
# PROD_CLIENT_MAX_RETRIES=5
# PROD_CLIENT_RETRY_DELAY=2
# PROD_CLIENT_USE_MOCK_CLIENT=false

# =============================================================================
# DEV Client Profile Configuration
# =============================================================================
# DEV_CLIENT_SERVER_URL=https://api.vitalgraph.dev.com
# DEV_CLIENT_AUTH_USERNAME=dev_user
# DEV_CLIENT_AUTH_PASSWORD=dev_password

# =============================================================================
# STAGING Client Profile Configuration
# =============================================================================
# STAGING_CLIENT_SERVER_URL=https://api.vitalgraph.staging.com
# STAGING_CLIENT_AUTH_USERNAME=staging_user
# STAGING_CLIENT_AUTH_PASSWORD=staging_password
```

### Phase 4: Update Test Scripts

**Files to Update**:
- All test scripts in `vitalgraph_client_test/`
- Example: `test_multiple_organizations_crud.py`

**Changes**:
1. Remove hardcoded config file paths
2. Use environment variables for test configuration
3. Update test documentation

**Example**:
```python
# OLD:
# client = VitalGraphClient(config_path="vitalgraphclient_config/vitalgraphclient-config.yaml")

# NEW:
# Configuration loaded from environment variables
# Set VITALGRAPH_CLIENT_ENVIRONMENT=local in .env
client = VitalGraphClient()
```

### Phase 5: Update Documentation

**Files to Update**:
1. `README.md` - Update client usage examples
2. `vitalgraphclient_config/README.md` - Document new env var approach
3. Client docstrings - Update with env var examples

**Documentation Content**:
```markdown
## Client Configuration

The VitalGraph client uses profile-based environment variables for configuration.

### Quick Start

1. Set your environment profile:
   ```bash
   export VITALGRAPH_CLIENT_ENVIRONMENT=local
   ```

2. Configure profile-specific variables:
   ```bash
   export LOCAL_CLIENT_SERVER_URL=http://localhost:8001
   export LOCAL_CLIENT_AUTH_USERNAME=admin
   export LOCAL_CLIENT_AUTH_PASSWORD=admin
   ```

3. Initialize the client:
   ```python
   from vitalgraph.client import VitalGraphClient
   
   client = VitalGraphClient()
   client.open()
   ```

### Switching Environments

Simply change the profile environment variable:
```bash
# Local development
export VITALGRAPH_CLIENT_ENVIRONMENT=local

# Production
export VITALGRAPH_CLIENT_ENVIRONMENT=prod
```
```

### Phase 6: Remove YAML Config Files

**Actions**:
1. Delete `vitalgraphclient_config/vitalgraphclient-config.yaml`
2. Delete `vitalgraphclient_config/vitalgraphclient-config.yaml.template`
3. Remove all YAML file loading code from `client_config_loader.py`
4. Update README to remove YAML references

**Migration Guide**:
Create `MIGRATION.md` with step-by-step instructions for users to migrate from YAML to env vars. This is a breaking change.

## Testing Strategy

### Unit Tests
1. Test profile-prefixed variable loading
2. Test fallback to unprefixed variables
3. Test fallback to defaults
4. Test profile switching
5. Test error handling when required env vars are missing

### Integration Tests
1. Test client connection with env var config
2. Test all client operations with different profiles
3. Test mock client with env var config

### Test Files to Update
- `vitalgraph_client_test/test_multiple_organizations_crud.py`
- All other test files in `vitalgraph_client_test/`

## Rollout Plan

### Step 1: Implementation (Week 1)
- [ ] Update `client_config_loader.py` with profile support
- [ ] Remove all YAML file loading code
- [ ] Update `vitalgraph_client.py` - remove `config_path` parameter
- [ ] Add unit tests for new config loading

### Step 2: Documentation (Week 1)
- [ ] Update `.env` with client profile variables
- [ ] Update `.env.example` with client variables
- [ ] Create `MIGRATION.md` guide
- [ ] Update README with new usage examples

### Step 3: Test Migration (Week 2)
- [ ] Update all test scripts to use env vars
- [ ] Remove config file references from tests
- [ ] Verify all tests pass with new config approach
- [ ] Test profile switching

### Step 4: Cleanup (Week 2)
- [ ] Delete YAML config files
- [ ] Delete `vitalgraphclient_config/` directory
- [ ] Update all documentation to remove YAML references

### Step 5: Validation & Release (Week 2)
- [ ] Test local development workflow
- [ ] Test production deployment scenario
- [ ] Create release notes documenting breaking change
- [ ] Release with migration guide

## Benefits

1. **Consistency**: Client and server use the same configuration approach
2. **Simplicity**: No config files to manage, just environment variables
3. **Flexibility**: Easy switching between environments
4. **Security**: Sensitive values can be injected via secrets management
5. **Cloud-Native**: Works seamlessly with container orchestration
6. **12-Factor**: Follows 12-factor app methodology

## Example Usage

### Local Development
```bash
# .env file
VITALGRAPH_CLIENT_ENVIRONMENT=local
LOCAL_CLIENT_SERVER_URL=http://localhost:8001
LOCAL_CLIENT_AUTH_USERNAME=admin
LOCAL_CLIENT_AUTH_PASSWORD=admin

# Python code
from vitalgraph.client import VitalGraphClient
client = VitalGraphClient()
client.open()
```

### Production Deployment
```bash
# Environment variables (from secrets manager)
VITALGRAPH_CLIENT_ENVIRONMENT=prod
PROD_CLIENT_SERVER_URL=https://api.production.com
PROD_CLIENT_AUTH_USERNAME=prod_service_account
PROD_CLIENT_AUTH_PASSWORD=<from-secrets-manager>
PROD_CLIENT_TIMEOUT=60
PROD_CLIENT_MAX_RETRIES=5

# Python code (same as local!)
from vitalgraph.client import VitalGraphClient
client = VitalGraphClient()
client.open()
```

### Multiple Profiles in Same Environment
```bash
# All profiles can coexist in .env
VITALGRAPH_CLIENT_ENVIRONMENT=local

LOCAL_CLIENT_SERVER_URL=http://localhost:8001
LOCAL_CLIENT_AUTH_USERNAME=admin

PROD_CLIENT_SERVER_URL=https://api.production.com
PROD_CLIENT_AUTH_USERNAME=prod_user

DEV_CLIENT_SERVER_URL=https://api.dev.com
DEV_CLIENT_AUTH_USERNAME=dev_user

# Switch by changing one variable
export VITALGRAPH_CLIENT_ENVIRONMENT=prod
```

## Files to Modify

### Core Implementation
- [ ] `vitalgraph/client/config/client_config_loader.py` - Add profile support
- [ ] `vitalgraph/client/vitalgraph_client.py` - Update docstrings

### Configuration Files
- [ ] `.env` - Add client profile variables
- [ ] `.env.example` - Document client configuration
- [ ] `vitalgraphclient_config/vitalgraphclient-config.yaml.template` - Mark as deprecated

### Documentation
- [ ] `README.md` - Update client usage examples
- [ ] `vitalgraphclient_config/README.md` - Document env var approach
- [ ] `MIGRATION.md` - Create migration guide

### Tests
- [ ] `vitalgraph_client_test/test_multiple_organizations_crud.py`
- [ ] All other test files using client config

## Success Criteria

1. ✅ Client config loader supports profile-prefixed environment variables
2. ✅ All YAML config files and loading code removed
3. ✅ All existing tests pass with new configuration approach
4. ✅ Documentation updated with clear examples
5. ✅ `.env` and `.env.example` include client configuration templates
6. ✅ Easy switching between environments (local, dev, staging, prod)
7. ✅ Consistent with server configuration approach
8. ✅ Migration guide created for breaking change

## Notes

- This plan follows the same pattern successfully implemented for the server configuration
- Profile-prefixed variables provide clean separation between environments
- **Breaking Change**: YAML config files will be completely removed - no backward compatibility
- Users must migrate to environment variables before upgrading
- The approach is cloud-native and works well with container orchestration platforms
- Migration guide will help users transition smoothly
