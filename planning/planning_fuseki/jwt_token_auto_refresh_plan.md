---
description: Plan for implementing automatic JWT token refresh with retry logic in VitalGraph client
---

# JWT Token Auto-Refresh Implementation Plan

## Executive Summary

This plan outlines the implementation of automatic JWT token refresh in the VitalGraph Python client, following industry best practices for OAuth2/JWT token management. The goal is to provide seamless, transparent token refresh that prevents authentication failures during long-running operations.

## Current State Analysis

### Existing Implementation

The VitalGraph client already has **partial token refresh infrastructure** in place:

**✅ Already Implemented:**
- JWT token storage (`access_token`, `refresh_token`, `token_expiry`)
- Token expiry checking (`_is_token_expired()` with 5-minute buffer)
- Token refresh method (`_refresh_access_token()`)
- Proactive token validation (`_ensure_valid_token()`)
- Centralized request methods (`_make_authenticated_request()`, `_make_authenticated_request_async()`)

**❌ Missing:**
- **Retry logic on 401 Unauthorized responses**
- **Re-authentication for client credentials flow** (no refresh token available)
- **Thread-safe token refresh/re-auth** (prevents concurrent attempts)
- **Async token refresh/re-auth** (currently only sync refresh exists)
- **Configurable retry behavior**
- **Metrics/logging for token refresh events**

### Critical Discovery: OAuth2 Password Grant with Refresh Tokens

**IMPORTANT:** After reviewing the authentication implementation, VitalGraph uses **OAuth2 Password Grant flow** (Resource Owner Password Credentials), which:
- ✅ Issues `access_token` with expiry (30 minutes)
- ✅ **DOES** issue `refresh_token` (7 days expiry)
- ✅ Has `/api/refresh` endpoint for token refresh
- 🔄 Supports **token refresh** using refresh token

**Server Implementation Evidence:**
```python
# vitalgraph/auth/jwt_auth.py
def create_refresh_token(self, data: dict) -> str:
    """Create JWT refresh token with longer expiration."""
    expire = datetime.utcnow() + timedelta(days=self.refresh_token_expire_days)  # 7 days
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

# vitalgraph/api/vitalgraph_api.py
async def login(self, form_data: OAuth2PasswordRequestForm):
    tokens = self.auth.create_tokens(user)  # Creates both access and refresh tokens
    return {
        **tokens,  # Includes access_token AND refresh_token
        "username": user["username"],
        # ...
    }

async def refresh_token(self, refresh_token: str = Body(..., embed=True)):
    """Refresh access token using refresh token"""
    # Validates refresh token and creates new access token
```

**Client Implementation:**
```python
# vitalgraph/client/vitalgraph_client.py (line 186)
self.refresh_token = auth_result.get('refresh_token')

if self.refresh_token:
    logger.info("Refresh token stored for automatic renewal")
else:
    logger.warning("No refresh token provided - manual re-authentication will be required on expiry")
```

**Conclusion:** The existing `_refresh_access_token()` method **should work** if the server is returning refresh tokens. The 401 errors are likely due to missing reactive retry logic, not missing refresh tokens.

### Architecture Assessment

**Good News:** The client has an **excellent centralized architecture**:
- All HTTP requests flow through `_make_authenticated_request()` and `_make_authenticated_request_async()`
- All endpoints inherit from `BaseEndpoint` and use these methods
- Token refresh logic can be added in **one place** and benefit all endpoints

**Request Flow:**
```
Endpoint Method (e.g., kgentities.create_kgentities)
    ↓
BaseEndpoint._make_typed_request()
    ↓
BaseEndpoint._make_authenticated_request()
    ↓
VitalGraphClient._make_authenticated_request()  ← ADD RETRY LOGIC HERE
    ↓
httpx.Client.request()
```

## Industry Best Practices for JWT Token Refresh

### 1. **Proactive Refresh (Pre-emptive)**
- Check token expiry **before** making requests
- Refresh if token expires within a buffer period (e.g., 5 minutes)
- **Status:** ✅ Already implemented in `_ensure_valid_token()`

### 2. **Reactive Refresh (On-Failure)**
- Catch 401 Unauthorized responses
- Attempt token refresh
- Retry the original request **once** with new token
- **Status:** ❌ Not implemented - **PRIMARY GAP**

### 3. **Thread Safety**
- Use locks to prevent concurrent refresh attempts
- Multiple threads should wait for single refresh to complete
- **Status:** ❌ Not implemented

### 4. **Exponential Backoff**
- For transient failures (network issues, server errors)
- Separate from authentication retry
- **Status:** ❌ Not implemented

### 5. **Refresh Token Rotation**
- Handle refresh token rotation (new refresh token on each refresh)
- **Status:** ✅ Partially implemented (stores new access_token, but should also update refresh_token if provided)

## Why 401 Errors Occur Despite Proactive Refresh

The current implementation has proactive token checking (`_ensure_valid_token()`), but **still gets 401 errors** because:

1. **No reactive retry on 401 responses** (PRIMARY ISSUE)
   - When 401 occurs, code just raises `VitalGraphClientError` (line 415)
   - No attempt to refresh token and retry the request
   - This is the **main gap** that needs to be fixed

2. **Possible proactive refresh failures**
   - `_refresh_access_token()` might be failing silently
   - Need to verify server is actually returning refresh tokens
   - Check client logs for "Refresh token stored" vs "No refresh token provided"

3. **Race conditions**
   - Token expires between `_ensure_valid_token()` check and actual request
   - Clock skew between client and server
   - Network delays causing token to expire mid-request

4. **Refresh token might not be returned**
   - If server isn't returning `refresh_token` in login response
   - `_refresh_access_token()` returns `False` (line 323: `if not self.refresh_token`)
   - `_ensure_valid_token()` raises error (line 387)
   - Need to verify with actual login response

## Detailed Implementation Plan

### Phase 1: Add Reactive Token Refresh with Retry Logic

**Goal:** Catch 401 errors and retry with refreshed token. Support both OAuth2 Password Grant (with refresh token) and fallback re-authentication if refresh token is unavailable.

**Changes Required:**

#### 1.1 Update `_make_authenticated_request()` (Sync)

**File:** `vitalgraph/client/vitalgraph_client.py`

**Current Implementation:**
```python
def _make_authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
    if not self.is_connected():
        raise VitalGraphClientError("Client is not connected")
    
    # Ensure we have a valid access token
    self._ensure_valid_token()
    
    try:
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response
    except httpx.HTTPError as e:
        raise VitalGraphClientError(f"Request failed: {e}")
```

**New Implementation:**
```python
def _make_authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
    if not self.is_connected():
        raise VitalGraphClientError("Client is not connected")
    
    # Proactive: Ensure we have a valid access token
    self._ensure_valid_token()
    
    try:
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as e:
        # Reactive: Handle 401 Unauthorized
        if e.response.status_code == 401:
            logger.warning("Received 401 Unauthorized - attempting re-auth/refresh and retry")
            
            # Determine authentication mode and handle accordingly
            if self.refresh_token:
                # User delegation flow: refresh token
                logger.info("Attempting token refresh with refresh token")
                if not self._refresh_access_token():
                    raise VitalGraphClientError("Token refresh failed after 401")
            else:
                # Client credentials flow: re-authenticate
                logger.info("No refresh token - re-authenticating with credentials")
                self._reauthenticate()
            
            # Retry the request ONCE with new token
            logger.info("Retrying request with new token")
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPError as retry_error:
                raise VitalGraphClientError(f"Request failed after re-auth/refresh: {retry_error}")
        else:
            # Not a 401 error, re-raise
            raise VitalGraphClientError(f"Request failed: {e}")
    except httpx.HTTPError as e:
        raise VitalGraphClientError(f"Request failed: {e}")
```

**Key Changes:**
- Catch `httpx.HTTPStatusError` specifically to check status code
- On 401, check authentication mode (refresh token vs client credentials)
- **Client credentials:** Re-authenticate with username/password
- **User delegation:** Refresh with refresh token
- Retry request **once** if re-auth/refresh succeeds
- Fail fast if re-auth/refresh fails or retry fails
- Log all token refresh/re-auth attempts for observability

#### 1.2 Add `_reauthenticate()` Method (Fallback)

**File:** `vitalgraph/client/vitalgraph_client.py`

**Purpose:** Fallback method for cases where refresh token is not available (e.g., if server configuration changes or for future client credentials support)

**New Method:**
```python
def _reauthenticate(self) -> None:
    """
    Re-authenticate with the server using stored credentials.
    Fallback method when refresh token is not available.
    
    Raises:
        VitalGraphClientError: If re-authentication fails
    """
    try:
        logger.info("Re-authenticating with server (no refresh token available)...")
        
        server_url = self.config.get_server_url()
        api_base_path = self.config.get_api_base_path()
        timeout = self.config.get_timeout()
        
        # Call existing authenticate method
        self._authenticate(server_url, api_base_path, timeout)
        
        logger.info("Re-authentication successful")
        
    except Exception as e:
        logger.error(f"Re-authentication failed: {e}")
        raise VitalGraphClientError(f"Failed to re-authenticate: {e}")
```

**Note:** For VitalGraph's current OAuth2 Password Grant implementation, this method should rarely be needed since refresh tokens are issued. However, it provides a robust fallback.

#### 1.3 Update `_ensure_valid_token()` Method

**File:** `vitalgraph/client/vitalgraph_client.py`

**Current Implementation:**
```python
def _ensure_valid_token(self) -> None:
    if not self.access_token:
        raise VitalGraphClientError("No access token available")
    
    if self._is_token_expired():
        logger.info("Access token expired or expiring soon, attempting refresh...")
        
        if not self._refresh_access_token():
            raise VitalGraphClientError("Failed to refresh access token - please re-authenticate")
```

**New Implementation:**
```python
def _ensure_valid_token(self) -> None:
    """
    Ensure we have a valid access token, refreshing/re-authenticating if necessary.
    Supports both client credentials and user delegation flows.
    
    Raises:
        VitalGraphClientError: If token refresh/re-auth fails
    """
    if not self.access_token:
        raise VitalGraphClientError("No access token available")
    
    if self._is_token_expired():
        if self.refresh_token:
            # User delegation flow: refresh token
            logger.info("Access token expired or expiring soon, attempting refresh...")
            if not self._refresh_access_token():
                raise VitalGraphClientError("Failed to refresh access token")
        else:
            # Client credentials flow: re-authenticate
            logger.info("Access token expired or expiring soon, re-authenticating...")
            self._reauthenticate()
```

**Key Changes:**
- Detect authentication mode by checking `self.refresh_token`
- **If refresh token exists:** Use `_refresh_access_token()` (user delegation)
- **If no refresh token:** Use `_reauthenticate()` (client credentials)
- Both proactive (before request) and reactive (on 401) paths now work correctly

#### 1.2 Update `_make_authenticated_request_async()` (Async)

**File:** `vitalgraph/client/vitalgraph_client.py`

**Similar changes for async version:**
- Add async token refresh method `_refresh_access_token_async()`
- Implement same 401 retry logic in async context

**New Method Required:**
```python
async def _refresh_access_token_async(self) -> bool:
    """
    Async version of token refresh.
    
    Returns:
        True if refresh was successful, False otherwise
    """
    if not self.refresh_token or not self.async_session:
        logger.warning("Cannot refresh token: no refresh token or session available")
        return False
    
    try:
        logger.info("Refreshing access token (async)...")
        
        # Build refresh URL
        server_url = self.config.get_server_url()
        refresh_url = f"{server_url.rstrip('/')}/api/refresh"
        
        # Send refresh request with refresh token as Bearer token
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.refresh_token}'
        }
        
        refresh_data = {"refresh_token": self.refresh_token}
        response = await self.async_session.post(refresh_url, json=refresh_data, headers=headers)
        
        if response.status_code == 200:
            # Refresh successful
            refresh_result = response.json()
            
            if 'access_token' in refresh_result:
                self.access_token = refresh_result['access_token']
                
                # Update refresh token if provided (token rotation)
                if 'refresh_token' in refresh_result:
                    self.refresh_token = refresh_result['refresh_token']
                
                # Update token expiry
                expires_in = refresh_result.get('expires_in', 1800)
                self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                
                # Update both session headers with new access token
                auth_header = {'Authorization': f'Bearer {self.access_token}'}
                self.session.headers.update(auth_header)
                self.async_session.headers.update(auth_header)
                
                logger.info("Access token refreshed successfully (async)")
                logger.info(f"New token expires in {expires_in} seconds")
                return True
            else:
                logger.error("Refresh response missing access_token")
                return False
        else:
            logger.error(f"Token refresh failed with status {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error refreshing access token (async): {e}")
        return False
```

### Phase 2: Add Thread Safety

**Goal:** Prevent concurrent token refresh attempts

**Changes Required:**

#### 2.1 Add Refresh Lock

**File:** `vitalgraph/client/vitalgraph_client.py`

**In `__init__()` method:**
```python
import threading

def __init__(self, config_path: Optional[str] = None, *, config: Optional[VitalGraphClientConfig] = None):
    # ... existing code ...
    
    # Thread safety for token refresh
    self._refresh_lock = threading.Lock()
    self._refresh_in_progress = False
```

#### 2.2 Update `_refresh_access_token()` with Lock

```python
def _refresh_access_token(self) -> bool:
    """
    Refresh the access token using the refresh token (thread-safe).
    
    Returns:
        True if refresh was successful, False otherwise
    """
    # Acquire lock to prevent concurrent refresh attempts
    with self._refresh_lock:
        # Check if another thread already refreshed the token
        if not self._is_token_expired():
            logger.info("Token already refreshed by another thread")
            return True
        
        if not self.refresh_token or not self.session or not self.async_session:
            logger.warning("Cannot refresh token: no refresh token or session available")
            return False
        
        try:
            logger.info("Refreshing access token...")
            self._refresh_in_progress = True
            
            # ... existing refresh logic ...
            
            self._refresh_in_progress = False
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing access token: {e}")
            self._refresh_in_progress = False
            return False
```

**For Async:** Use `asyncio.Lock()` instead of `threading.Lock()`

### Phase 3: Add Refresh Token Rotation Support

**Goal:** Handle servers that rotate refresh tokens

**Changes Required:**

#### 3.1 Update Both Refresh Methods

**In `_refresh_access_token()` and `_refresh_access_token_async()`:**

```python
# After successful refresh
if 'access_token' in refresh_result:
    self.access_token = refresh_result['access_token']
    
    # Handle refresh token rotation
    if 'refresh_token' in refresh_result:
        old_refresh_token = self.refresh_token
        self.refresh_token = refresh_result['refresh_token']
        logger.info("Refresh token rotated")
    
    # ... rest of logic ...
```

**Status:** Partially implemented - just needs to check for new `refresh_token` in response

### Phase 4: Add Configuration Options

**Goal:** Make token refresh behavior configurable

**Changes Required:**

#### 4.1 Add Config Options

**File:** `vitalgraph/client/config/client_config_loader.py`

**Add to YAML config:**
```yaml
client:
  timeout: 30
  max_retries: 3
  token_refresh:
    enabled: true
    buffer_minutes: 5  # Refresh if token expires within this time
    retry_on_401: true  # Retry requests on 401 after refresh
    max_refresh_attempts: 1  # How many times to retry refresh on failure
```

**Add getter methods:**
```python
def get_token_refresh_config(self) -> Dict[str, Any]:
    """Get token refresh configuration."""
    client_config = self.get_client_config()
    return client_config.get('token_refresh', {
        'enabled': True,
        'buffer_minutes': 5,
        'retry_on_401': True,
        'max_refresh_attempts': 1
    })

def is_token_refresh_enabled(self) -> bool:
    """Check if automatic token refresh is enabled."""
    return self.get_token_refresh_config().get('enabled', True)

def get_token_buffer_minutes(self) -> int:
    """Get token expiry buffer in minutes."""
    return self.get_token_refresh_config().get('buffer_minutes', 5)
```

#### 4.2 Use Config in Client

**Update `_is_token_expired()`:**
```python
def _is_token_expired(self) -> bool:
    if not self.token_expiry:
        return True
    
    # Get buffer time from config
    buffer_minutes = self.config.get_token_buffer_minutes()
    buffer_time = timedelta(minutes=buffer_minutes)
    return datetime.now() >= (self.token_expiry - buffer_time)
```

**Update `_make_authenticated_request()`:**
```python
def _make_authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
    # ... existing code ...
    
    except httpx.HTTPStatusError as e:
        # Check if retry on 401 is enabled
        if e.response.status_code == 401 and self.config.is_token_refresh_enabled():
            # ... retry logic ...
```

### Phase 5: Add Metrics and Observability

**Goal:** Track token refresh events for monitoring

**Changes Required:**

#### 5.1 Add Metrics Tracking

**File:** `vitalgraph/client/vitalgraph_client.py`

**In `__init__()`:**
```python
# Token refresh metrics
self._token_refresh_count = 0
self._token_refresh_failures = 0
self._last_refresh_time: Optional[datetime] = None
```

**Update refresh methods to track metrics:**
```python
def _refresh_access_token(self) -> bool:
    # ... existing code ...
    
    if response.status_code == 200:
        self._token_refresh_count += 1
        self._last_refresh_time = datetime.now()
        # ... rest of success logic ...
    else:
        self._token_refresh_failures += 1
        # ... rest of failure logic ...
```

**Add getter for metrics:**
```python
def get_token_metrics(self) -> Dict[str, Any]:
    """Get token refresh metrics."""
    return {
        'refresh_count': self._token_refresh_count,
        'refresh_failures': self._token_refresh_failures,
        'last_refresh': self._last_refresh_time.isoformat() if self._last_refresh_time else None,
        'token_expires_at': self.token_expiry.isoformat() if self.token_expiry else None,
        'is_expired': self._is_token_expired()
    }
```

## Implementation Priority

### Must Have (Phase 1)
1. ✅ **Reactive token refresh on 401** - Critical for preventing auth failures
2. ✅ **Async token refresh method** - Required for async endpoints
3. ✅ **Single retry on 401** - Prevents infinite loops

### Should Have (Phase 2-3)
4. ✅ **Thread safety** - Important for multi-threaded applications
5. ✅ **Refresh token rotation** - Required for some OAuth2 servers

### Nice to Have (Phase 4-5)
6. ⭐ **Configuration options** - Allows customization
7. ⭐ **Metrics/observability** - Helps with debugging and monitoring

## Testing Strategy

### Unit Tests

**File:** `tests/test_vitalgraph_client_token_refresh.py`

**Test Cases:**
1. `test_proactive_refresh_before_expiry` - Token refreshed before request
2. `test_reactive_refresh_on_401` - Token refreshed after 401 response
3. `test_retry_after_refresh` - Request retried with new token
4. `test_refresh_failure_raises_error` - Proper error on refresh failure
5. `test_concurrent_refresh_thread_safe` - Multiple threads don't cause duplicate refresh
6. `test_refresh_token_rotation` - New refresh token stored
7. `test_async_token_refresh` - Async refresh works correctly
8. `test_config_disabled_refresh` - Refresh can be disabled via config

### Integration Tests

**File:** `tests/integration/test_token_refresh_integration.py`

**Test Cases:**
1. `test_long_running_operation_with_expiry` - Token refreshes during long operation
2. `test_multiple_requests_with_expiry` - Multiple requests trigger single refresh
3. `test_401_recovery_real_server` - Real 401 response triggers refresh

### Manual Testing

**Scenarios:**
1. Set token expiry to 30 seconds, run operations for 5 minutes
2. Manually invalidate token on server, verify client recovers
3. Run concurrent operations from multiple threads
4. Test with server that rotates refresh tokens

## Rollout Plan

### Stage 1: Development (Week 1)
- Implement Phase 1 (reactive refresh + retry)
- Implement Phase 2 (thread safety)
- Write unit tests

### Stage 2: Testing (Week 2)
- Integration testing with real server
- Performance testing (overhead of token checks)
- Concurrent operation testing

### Stage 3: Documentation (Week 2)
- Update client documentation
- Add configuration examples
- Document token refresh behavior

### Stage 4: Deployment (Week 3)
- Release as minor version (backward compatible)
- Monitor token refresh metrics
- Gather user feedback

## Risk Assessment

### Low Risk
- ✅ Centralized request architecture makes changes isolated
- ✅ Existing proactive refresh already works
- ✅ Changes are backward compatible

### Medium Risk
- ⚠️ Thread safety in async context (use `asyncio.Lock()`)
- ⚠️ Potential for race conditions if not properly locked

### Mitigation
- Comprehensive unit tests for concurrency
- Integration tests with real server
- Gradual rollout with monitoring

## Success Criteria

1. ✅ **Zero authentication failures** during long-running operations
2. ✅ **Transparent to users** - no code changes required
3. ✅ **Thread-safe** - works correctly with concurrent requests
4. ✅ **Configurable** - users can customize behavior
5. ✅ **Observable** - metrics available for monitoring

## Configurable Token Expiry for Testing

To facilitate testing of token refresh functionality, an optional `token_expiry_seconds` parameter can be passed when instantiating the client. This parameter flows through to the server's authentication endpoint to create tokens with custom expiry times.

### Implementation

**Design Principle:** Runtime parameter, not configuration-based. The expiry override is passed as an optional parameter during client instantiation and sent to the server during authentication.

**Files Modified:**
1. `vitalgraph/client/vitalgraph_client.py` - Added `token_expiry_seconds` parameter to `__init__()`
2. `vitalgraph/client/vitalgraph_client.py` - Pass `token_expiry_seconds` in login form data
3. `vitalgraph/impl/vitalgraphapp_impl.py` - Accept `token_expiry_seconds` from form data
4. `vitalgraph/api/vitalgraph_api.py` - Validate and pass `token_expiry_seconds` to auth handler
5. `vitalgraph/auth/vitalgraph_auth.py` - Accept and pass `token_expiry_seconds` to JWT handler
6. `vitalgraph/auth/jwt_auth.py` - Use `expiry_seconds` parameter in token creation

### Client-Side Usage

**Instantiate client with custom token expiry:**
```python
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# Create client with 15-second token expiry for testing
client = VitalGraphClient(
    config_path="/path/to/config.yaml",
    token_expiry_seconds=15  # Optional: for testing, max 1800
)

client.open()  # Token will be created with 15-second expiry

# Use client normally - 401 retry logic will handle token refresh
response = client.kgtypes.list_kgtypes("space", "graph")
```

**Default behavior (no parameter):**
```python
# Standard 30-minute token expiry
client = VitalGraphClient(config_path="/path/to/config.yaml")
client.open()
```

### Server-Side Validation

**Validation Rules:**
- `token_expiry_seconds` must be between 1 and 1800 (30 minutes)
- Values > 1800 return HTTP 400 Bad Request
- Values < 1 return HTTP 400 Bad Request
- If not provided, defaults to 30 minutes (1800 seconds)

**Server Logging:**
```
INFO: Authenticating with VitalGraph server at http://localhost:8001/api/login
INFO: Requesting custom token expiry: 15 seconds
INFO: Creating tokens with custom expiry: 15 seconds
```

### Testing Strategy

**Test with very short expiry (15 seconds):**
```python
import time
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# Create client with 15-second token expiry
client = VitalGraphClient(
    config_path="/path/to/config.yaml",
    token_expiry_seconds=15
)
client.open()

# Initial request (token valid)
response1 = client.kgtypes.list_kgtypes("space", "graph")
print(f"Request 1: {response1.is_success}")

# Wait for token to expire
print("Waiting 20 seconds for token to expire...")
time.sleep(20)

# Request after expiry (should trigger 401 → refresh → retry → success)
response2 = client.kgtypes.list_kgtypes("space", "graph")
print(f"Request 2: {response2.is_success}")

client.close()
```

### Benefits

- ✅ **No configuration needed** - pure runtime parameter
- ✅ **Production safe** - upper limit enforced (max 30 minutes)
- ✅ **Easy testing** - set to 15 seconds for rapid testing
- ✅ **Logged** - custom expiry logged on both client and server
- ✅ **Optional** - defaults to standard 30 minutes if not provided
- ✅ **Works with 401 retry** - automatic token refresh still functions

## Diagnostic Steps Before Implementation

Before implementing the fix, verify the current state:

### 1. Check if Refresh Tokens Are Being Returned

**Create test script:** `test_scripts/auth/test_login_response.py`
```python
import httpx
import json

# Test login to see actual response
response = httpx.post(
    "http://localhost:8001/api/login",
    data={"username": "admin", "password": "admin"},
    headers={'Content-Type': 'application/x-www-form-urlencoded'}
)

print("Status:", response.status_code)
print("\nResponse JSON:")
print(json.dumps(response.json(), indent=2))

# Check specifically for refresh_token
response_data = response.json()
if 'refresh_token' in response_data:
    print("\n✅ Refresh token IS present in response")
    print(f"   Access token expires in: {response_data.get('expires_in')} seconds")
else:
    print("\n❌ Refresh token NOT present in response")
    print("   Available keys:", list(response_data.keys()))
```

### 2. Check Client Logs During Connection

Look for these log messages when client connects:
- ✅ "Refresh token stored for automatic renewal" → Refresh tokens working
- ❌ "No refresh token provided - manual re-authentication will be required on expiry" → Refresh tokens not returned

### 3. Test Proactive Refresh

**Create test script:** `test_scripts/auth/test_proactive_refresh.py`
```python
from vitalgraph.client.vitalgraph_client import VitalGraphClient
import time

client = VitalGraphClient(config_path="vitalgraphclient_config/vitalgraphclient-config.yaml")
client.open()

# Check initial state
print("Initial token state:")
print(f"  Has access token: {client.access_token is not None}")
print(f"  Has refresh token: {client.refresh_token is not None}")
print(f"  Token expiry: {client.token_expiry}")

# Manually set token to expired
from datetime import datetime, timedelta
client.token_expiry = datetime.now() - timedelta(minutes=1)
print("\n⏰ Manually expired token")

# Try to make a request (should trigger proactive refresh)
try:
    spaces = client.spaces.list_spaces()
    print("\n✅ Request succeeded after proactive refresh")
except Exception as e:
    print(f"\n❌ Request failed: {e}")

client.close()
```

## Open Questions for Discussion

1. **Retry Strategy:** Should we retry on other status codes (502, 503, 504)?
2. **Exponential Backoff:** Should we add exponential backoff for transient failures?
3. **Refresh Token Expiry:** How to handle refresh token expiration (requires full re-auth)?
4. **Token Storage:** Should we support persistent token storage (cache to disk)?
5. **Multiple Refresh Attempts:** Should we allow multiple refresh attempts with backoff?
6. **Metrics Export:** Should we export metrics to Prometheus/StatsD?
7. **Circuit Breaker:** Should we add circuit breaker pattern for repeated auth failures?
8. **Verify Refresh Token:** Is the server actually returning refresh tokens in production?

## References

### Industry Standards
- [RFC 6749 - OAuth 2.0](https://datatracker.ietf.org/doc/html/rfc6749)
- [RFC 7519 - JWT](https://datatracker.ietf.org/doc/html/rfc7519)
- [OAuth 2.0 Token Refresh Best Practices](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation)

### Similar Implementations
- [requests-oauthlib](https://github.com/requests/requests-oauthlib) - Python OAuth2 library
- [httpx-auth](https://github.com/Colin-b/httpx_auth) - HTTPX authentication
- [google-auth-library-python](https://github.com/googleapis/google-auth-library-python) - Google's auth library

## Conclusion

### Current State Summary

**Authentication Type:** OAuth2 Password Grant (Resource Owner Password Credentials)
- ✅ Server issues both `access_token` (30 min) and `refresh_token` (7 days)
- ✅ Server has `/api/refresh` endpoint
- ✅ Client has `_refresh_access_token()` method
- ✅ Client stores refresh token
- ❌ **Missing:** Reactive retry on 401 errors

**Root Cause of 401 Errors:**
The primary issue is **missing reactive retry logic**. When a 401 occurs (due to race conditions, clock skew, or proactive refresh failure), the client immediately raises an error instead of attempting to refresh the token and retry the request.

### Recommended Implementation Path

**Phase 1: Reactive Refresh (CRITICAL - Highest Impact)**
1. Add 401 detection and retry logic to `_make_authenticated_request()`
2. Add 401 detection and retry logic to `_make_authenticated_request_async()`
3. Add `_refresh_access_token_async()` method
4. Add `_reauthenticate()` as fallback (for cases where refresh token unavailable)

**Phase 2: Thread Safety (Important)**
5. Add `threading.Lock()` for sync refresh
6. Add `asyncio.Lock()` for async refresh

**Phase 3: Configuration & Observability (Nice to Have)**
7. Add configuration options
8. Add metrics tracking

### Before Implementation

**Run diagnostics first** to verify:
1. Server is returning refresh tokens (check login response)
2. Client is storing refresh tokens (check client logs)
3. Proactive refresh is working (test with expired token)

This will confirm whether the issue is purely missing reactive retry, or if there are additional problems with the refresh token flow.

### Architecture Advantage

The VitalGraph client has **excellent centralized architecture** - all HTTP requests flow through two methods (`_make_authenticated_request()` and `_make_authenticated_request_async()`). This means the fix can be implemented in **one place** and automatically benefits all endpoints with minimal risk.

This approach follows industry best practices and provides a robust, production-ready token refresh implementation.
