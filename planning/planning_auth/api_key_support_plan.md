# API Key Support Plan

## Implementation Status

| Step | Task | Status |
|------|------|--------|
| 1 | `vitalgraph/auth/api_key.py` — key generation + validation | ✅ Done |
| 2 | `vitalgraph/model/api_key_model.py` — Pydantic models | ✅ Done |
| 3 | API key DB methods in `UserManagementMixin` | ✅ Done |
| 4 | `VitalGraphAuth` — detect `vg_` prefix, validate, return user | ✅ Done |
| 5 | `vitalgraph/endpoint/api_keys_endpoint.py` — CRUD routes (self-service) | ✅ Done |
| 6 | Register API keys router in app init | ✅ Done |
| 7 | CLI `apikey` commands (list, create, revoke, info) | ✅ Done |
| 8 | `VitalGraphClient` — `api_key` param, skip JWT flow | ✅ Done |
| 9 | DB migration (`api_key` table + indexes) | ✅ Done |
| 10 | Remove `passlib` dependency, use `bcrypt` directly | ✅ Done |
| 11 | Frontend admin panel (optional) | ✅ Done |

### Database Deployment
- Migration applied to `sparql_sql_graph` (local dev) on 2026-06-07
- Run: `python -m vitalgraph.db.migrations.migrate_auth_schema --database <db_name>`

### Files Created
- `vitalgraph/auth/api_key.py`
- `vitalgraph/model/api_key_model.py`
- `vitalgraph/endpoint/api_keys_endpoint.py`

### Files Modified
- `vitalgraph/auth/password.py` — replaced `passlib` with direct `bcrypt` calls
- `vitalgraph/db/user_management.py` — API key CRUD methods
- `vitalgraph/db/migrations/migrate_auth_schema.py` — `api_key` table DDL
- `vitalgraph/auth/vitalgraph_auth.py` — `_validate_api_key()` + detection in `get_current_user`
- `vitalgraph/impl/vitalgraphapp_impl.py` — router registration
- `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` — `apikey` CLI commands
- `vitalgraph/client/vitalgraph_client.py` — `api_key` constructor param

---

## 1. Overview

Add long-lived API key authentication for programmatic access (CLI tools, CI/CD pipelines, external integrations, `VitalGraphClient`). API keys complement JWT tokens — they trade the short-lived security properties of JWTs for operational convenience in automated scenarios.

**Design decisions** (from the main auth modernization plan):
- API keys **inherit** the owning user's role and per-space access — no independent permission model
- Keys are prefixed with `vg_` for identification in the auth layer
- Only the bcrypt hash is stored; the full key is shown once at creation time
- Deactivating the owning user deactivates all their keys (CASCADE behavior)

---

## 2. Database Schema (Already Deployed)

The `api_key` table was created by the `migrate auth` migration:

```sql
CREATE TABLE IF NOT EXISTS api_key (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_prefix VARCHAR(8) NOT NULL,        -- first 8 chars (after 'vg_') for lookup
    key_hash VARCHAR(255) NOT NULL,         -- bcrypt hash of full key
    user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,             -- human-readable label
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_time TIMESTAMPTZ DEFAULT now(),
    last_used TIMESTAMPTZ,
    expires_at TIMESTAMPTZ                  -- NULL = never expires
);

CREATE INDEX IF NOT EXISTS idx_apikey_prefix ON api_key(key_prefix);
CREATE INDEX IF NOT EXISTS idx_apikey_user ON api_key(user_id);
```

No additional migration is needed.

---

## 3. Key Format

```
vg_<prefix><random_suffix>
```

- **Total length**: 40 characters (e.g. `vg_Ab3kLm92_7xQwPzR4nYhJcTfV8gUeWdK0sA1`)
- **Prefix**: 8 characters after `vg_` — stored in `key_prefix` for fast lookup
- **Full key**: hashed with bcrypt and stored in `key_hash`
- **Display**: Only shown once at creation; subsequent views show `vg_Ab3kLm92...`

Generation:

```python
import secrets
import string

def generate_api_key() -> tuple[str, str]:
    """Generate an API key and return (full_key, prefix)."""
    alphabet = string.ascii_letters + string.digits
    prefix = ''.join(secrets.choice(alphabet) for _ in range(8))
    suffix = ''.join(secrets.choice(alphabet) for _ in range(29))
    full_key = f"vg_{prefix}{suffix}"
    return full_key, prefix
```

---

## 4. Authentication Flow

### 4.1 Detection

The auth layer inspects the `Authorization: Bearer <token>` value:
- If the token starts with `vg_` → API key flow
- Otherwise → JWT flow (existing)

### 4.2 Validation Steps

```
1. Extract prefix (chars 3-11 of the key)
2. Query: SELECT * FROM api_key WHERE key_prefix = $1 AND is_active = true
3. For each matching row, verify_password(full_key, row.key_hash)
4. If match found:
   a. Check expires_at (if set) > now()
   b. Load owning user: SELECT * FROM "user" WHERE user_id = row.user_id AND is_active = true
   c. Load user's spaces from user_space_access
   d. Update last_used timestamp (fire-and-forget)
   e. Return user dict with role + spaces (same shape as JWT current_user)
5. If no match → 401
```

### 4.3 Integration Point

In `VitalGraphAuth.create_get_current_user_dependency()`, before calling `jwt_auth.verify_token()`:

```python
async def get_current_user(token: str = Depends(self.oauth2_scheme)):
    if token.startswith("vg_"):
        return await self._validate_api_key(token)
    # existing JWT path...
```

---

## 5. API Endpoints

### 5.1 Routes

API key management supports **self-service** — authenticated users can create and revoke their own keys. Admins can manage any user's keys.

| Method | Path | Description | Access |
|--------|------|-------------|--------|
| POST | `/api/keys` | Create a new API key | Self (own keys) or Admin (any user) |
| GET | `/api/keys` | List API keys (masked) | Self (own keys) or Admin (all/filtered) |
| GET | `/api/keys/key?key_id=<id>` | Get API key details | Owner or Admin |
| DELETE | `/api/keys?key_id=<id>` | Revoke (deactivate) a key | Owner or Admin |

### 5.1.1 Access Control Rules

- **Non-admin users**: Can only create keys for themselves (the `username` field in the request body is ignored or must match their own username). Can only list/view/revoke their own keys.
- **Admin users**: Can specify any `username` when creating a key, list all keys or filter by user, and revoke any key.
- A non-admin attempting to operate on another user's key receives **403 Forbidden**.

### 5.2 Request/Response Models

```python
# vitalgraph/model/api_key_model.py

class ApiKeyCreateRequest(BaseModel):
    username: Optional[str] = None  # target user (admin-only; omit for self)
    name: str                       # human-readable label
    expires_in_days: Optional[int] = None  # None = no expiry

class ApiKeyCreateResponse(BaseModel):
    key_id: str                 # UUID
    key: str                    # full key (shown ONCE)
    prefix: str                 # vg_<prefix>...
    name: str
    username: str
    expires_at: Optional[str]
    message: str = "API key created. Save the key — it cannot be retrieved again."

class ApiKeyInfo(BaseModel):
    key_id: str
    prefix: str                 # masked display: vg_Ab3kLm92...
    name: str
    username: str
    is_active: bool
    created_time: str
    last_used: Optional[str]
    expires_at: Optional[str]

class ApiKeyListResponse(BaseModel):
    keys: List[ApiKeyInfo]
    total_count: int

class ApiKeyDeleteResponse(BaseModel):
    message: str
    key_id: str
```

### 5.3 Endpoint Implementation

```python
# vitalgraph/endpoint/api_keys_endpoint.py

class ApiKeysEndpoint:
    def __init__(self, db_impl, auth_dependency):
        self.db = db_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter(prefix="/api/keys", tags=["API Keys"])
        self._setup_routes()

    async def create_key(self, request: ApiKeyCreateRequest, current_user: Dict):
        # Determine target user
        target_username = request.username or current_user["username"]
        if target_username != current_user["username"]:
            # Only admins can create keys for other users
            if current_user.get("role") != "admin":
                raise HTTPException(403, "Cannot create keys for other users")
        # Enforce max keys per user
        ...

    async def list_keys(self, current_user: Dict, username: Optional[str] = None):
        if current_user.get("role") != "admin":
            # Non-admins can only see their own keys
            username = current_user["username"]
        ...

    async def revoke_key(self, key_id: str, current_user: Dict):
        key = await self.db.get_api_key(key_id)
        if not key:
            raise HTTPException(404)
        # Check ownership or admin
        if key["username"] != current_user["username"] and current_user.get("role") != "admin":
            raise HTTPException(403, "Cannot revoke another user's key")
        ...
```

---

## 6. Database Methods

Add to `UserManagementMixin` (or create separate `ApiKeyMixin`):

```python
async def create_api_key(self, user_id: int, name: str, key_prefix: str,
                         key_hash: str, expires_at=None) -> Dict:
    """Insert a new API key record. Returns the created record."""

async def list_api_keys(self, user_id: Optional[int] = None) -> List[Dict]:
    """List API keys, optionally filtered by user. Never returns key_hash."""

async def get_api_key_by_prefix(self, prefix: str) -> Optional[Dict]:
    """Lookup API key by prefix. Returns full record including key_hash."""

async def deactivate_api_key(self, key_id: str) -> bool:
    """Set is_active = false for the key."""

async def update_api_key_last_used(self, key_id: str) -> None:
    """Update last_used timestamp. Best-effort, no error on failure."""
```

---

## 7. CLI Commands

Extend the admin REPL with `apikey` subcommands:

```
apikey list [username];                    - List all keys (or for a specific user)
apikey create <username> <name> [days];    - Create a key (optional expiry in days)
apikey revoke <key_id>;                    - Deactivate a key
apikey info <key_id>;                      - Show key details
```

### CLI Flow for `apikey create`:

```
vitalgraphadmin> apikey create jsmith "CI Pipeline" 90;
✅ API key created for user 'jsmith':
   Key:     vg_Ab3kLm92_7xQwPzR4nYhJcTfV8gUeWdK0sA1
   Name:    CI Pipeline
   Expires: 2026-09-05T07:00:00Z
   ⚠️  Save this key now — it cannot be retrieved again.
```

---

## 8. VitalGraphClient Integration

The Python client should accept API key auth as an alternative to username/password:

```python
# Option A: API key auth (no login step needed)
client = VitalGraphClient(
    base_url="https://vitalgraph.example.com",
    api_key="vg_Ab3kLm92_7xQwPzR4nYhJcTfV8gUeWdK0sA1"
)

# Option B: JWT auth (existing)
client = VitalGraphClient(
    base_url="https://vitalgraph.example.com",
    username="admin",
    password="secret"
)
```

When `api_key` is provided:
- Skip the login/token refresh flow entirely
- Set `Authorization: Bearer <api_key>` on every request
- No token refresh timer needed

---

## 9. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Key leakage | Show full key only at creation; store only bcrypt hash |
| Brute force | 8-char prefix narrows to 1-2 rows; bcrypt is slow by design |
| Stolen key | `expires_at` limits blast radius; admin can revoke instantly |
| User deactivation | CASCADE delete on `user_id` FK removes all keys |
| Rate limiting | Future: add per-key rate limit tracking via `last_used` frequency |
| Key rotation | Create new key → update client → revoke old key (no built-in rotation) |
| Prefix collision | 8 alphanumeric chars = 62^8 ≈ 218 trillion combinations; collision unlikely |

---

## 10. Implementation Order

| Step | Task | Files |
|------|------|-------|
| 1 | Create `vitalgraph/auth/api_key.py` — key generation + validation functions | New |
| 2 | Create `vitalgraph/model/api_key_model.py` — Pydantic request/response models | New |
| 3 | Add API key DB methods to `UserManagementMixin` | `vitalgraph/db/user_management.py` |
| 4 | Update `VitalGraphAuth` — detect `vg_` prefix, validate, return user | `vitalgraph/auth/vitalgraph_auth.py` |
| 5 | Create `vitalgraph/endpoint/api_keys_endpoint.py` — CRUD routes | New |
| 6 | Register API keys router in app init | `vitalgraph/impl/vitalgraphapp_impl.py` |
| 7 | Add `apikey` CLI commands | `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` |
| 8 | Update `VitalGraphClient` to accept `api_key` param | `vitalgraph/client/vitalgraph_client.py` |
| 9 | Update frontend admin panel to show/manage API keys (optional) | `frontend/src/` |

---

## 11. Testing Plan

### Unit Tests
- Key generation produces correct format and length
- Prefix extraction is correct
- Hash verification succeeds for valid key, fails for invalid
- Expired key is rejected
- Deactivated key is rejected
- Deactivated user's key is rejected

### Integration Tests
- Create key via API → use key to authenticate → access endpoint
- Revoke key → subsequent requests fail with 401
- Key inherits owning user's role (try admin operation with reader's key → 403)
- Key inherits owning user's space access (access denied space → 403)
- Create key with expiry → wait → key rejected after expiry
- Delete user → all their keys are gone (CASCADE)

### Self-Service Tests
- Non-admin user creates own key → success
- Non-admin user lists keys → sees only own keys
- Non-admin user revokes own key → success
- Non-admin user tries to create key for another user → 403
- Non-admin user tries to revoke another user's key → 403
- Non-admin user tries to list another user's keys → gets only own keys (filter ignored)
- Admin creates key for another user → success
- Admin lists all keys → sees all users' keys
- Admin revokes another user's key → success
- Max keys per user enforced (11th creation attempt → 400)

### CLI Tests
- `apikey create` → key displayed → `apikey list` shows it
- `apikey revoke` → key no longer works
- `apikey list <username>` → only that user's keys shown

---

## 12. Open Questions

| # | Question | Proposed Answer |
|---|----------|----------------|
| 1 | Should users be able to create their own API keys (self-service)? | **Yes** — users can create/revoke their own keys; admins can manage any user's keys. |
| 2 | Maximum keys per user? | **10** — configurable, prevents key sprawl |
| 3 | Should key creation emit an audit log event? | **Yes** — log user, key name, creator, timestamp |
| 4 | Should there be a "rotate key" endpoint that atomically creates new + revokes old? | **No** — manual create + revoke is sufficient for now |
| 5 | Should API keys support scope restriction (subset of user's spaces)? | **No** — full inheritance keeps it simple. Revisit if needed. |
