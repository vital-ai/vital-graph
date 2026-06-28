# VitalGraph Authentication & Authorization Modernization Plan

## 1. Current Implementation Analysis

### 1.1 Architecture Overview

The current auth system is a minimal, single-user implementation spanning four layers:

| Layer | File | Role |
|-------|------|------|
| JWT core | `vitalgraph/auth/jwt_auth.py` | Token create/verify/refresh (HS256) |
| Auth coordinator | `vitalgraph/auth/vitalgraph_auth.py` | User lookup, token creation, FastAPI dependency |
| API routes | `vitalgraph/api/vitalgraph_api.py` | Login, logout, refresh, user CRUD stubs |
| Frontend | `frontend/src/services/AuthService.ts` | Token storage (localStorage), auto-refresh |

### 1.2 Critical Gaps

**Hardcoded single-user store.** `VitalGraphAuth.__init__` creates an in-memory dict with one user (`admin/admin`). No database persistence, no multi-user support.

```python
# vitalgraph/auth/vitalgraph_auth.py:9-20
self.users_db = {
    "admin": {
        "username": "admin",
        "password": "admin",         # plaintext
        "full_name": "Admin User",
        "role": "Administrator",
        ...
    }
}
```

**Plaintext passwords.** Passwords are stored and compared as raw strings — no hashing, no salting.

**No role enforcement.** The `role` field exists in token claims and the user dict, but no endpoint checks it. Every authenticated user has full access to every operation.

**No space-level access control.** All users see all spaces. The `tenant` column in the `"user"` table is unused for filtering.

**User CRUD is split.** `list_users` and `get_user_by_id` read from the in-memory dict, while `add_user`, `update_user`, and `delete_user` call `self.db` — two separate stores.

**JWT secret comes from env only.** `JWT_SECRET_KEY` must be set as an environment variable; there is no config-file fallback or rotation mechanism.

**No token revocation.** Logout clears the session server-side, but issued JWTs remain valid until expiry. No blacklist or token-version mechanism exists.

**Database user table is unused for auth.** Both backends define a `"user"` table with `user_id`, `username`, `password`, `email`, `tenant`, but `VitalGraphAuth` never reads it.

### 1.3 What Works Well

- **JWT access/refresh token pair** — standard OAuth2-compatible flow
- **Frontend auto-refresh** — schedules refresh 5 minutes before expiry, retries on 401
- **OAuth2PasswordBearer** — standard FastAPI security scheme, works with Swagger UI
- **Client library auth** — `VitalGraphClient` handles login and token lifecycle
- **Config separation** — `auth.root_username`/`auth.root_password` in YAML config

---

## 2. Comparable System Survey

### 2.1 SPARQL / Graph Databases

| System | Auth Model | Roles | Resource Scoping | Notes |
|--------|-----------|-------|-----------------|-------|
| **Apache Jena Fuseki** | Apache Shiro (INI file) | User-defined in `[users]` section | URL-pattern ACLs in `[urls]` | Simple but restart-required for changes; no API for user mgmt |
| **Stardog** | RBAC with Users, Roles, Permissions | Built-in `reader` role; custom roles | Per-database, per-named-graph | Full enterprise model; bcrypt passwords; LDAP/Kerberos optional |
| **Dgraph** | JWT claims + `@auth` directive | RBAC on GraphQL types | Per-type query/mutation rules | Role from JWT claim; no built-in user store |
| **Oxigraph** | None (reverse proxy) | N/A | N/A | Delegates to external infra |

### 2.2 AI / Vector Data Services

| System | Auth Model | Roles | Resource Scoping | Notes |
|--------|-----------|-------|-----------------|-------|
| **Qdrant** | API key + JWT RBAC | `manage` (admin), `r` (read), `rw` (read-write) | Per-collection access in JWT claims | Admin key signs JWTs; granular `access` claim |
| **Weaviate** | OIDC/JWT + API key | Configurable via RBAC module | Per-class/collection | External IdP issues JWT; server validates |
| **ChromaDB** | Token-based (simple) | Single-tier | Global | Minimal, startup-focused |
| **Milvus** | Username/password + RBAC | Built-in: `admin`, `public` | Per-collection | Simple role model adequate for startups |

### 2.3 Key Patterns for VitalGraph

The systems most relevant to VitalGraph's position (startup-friendly, not full enterprise) are **Qdrant**, **Milvus**, and **Stardog's base model**. Common patterns:

1. **Three-tier roles**: admin / read-write / read-only
2. **Resource scoping at the collection/database level** — maps to VitalGraph's spaces
3. **JWT carries role + resource claims** — server validates on each request
4. **Passwords hashed with bcrypt** — industry standard
5. **User management via API** — no restart required
6. **Admin bootstrap from config** — initial admin user from env/config, subsequent users via API

---

## 3. Proposed Role Model

### 3.1 Roles

| Role | Code | Description |
|------|------|-------------|
| **admin** | `admin` | Full system access: all spaces, user management, system configuration, import/export, SPARQL updates |
| **user** | `user` | Read + write access to assigned spaces; cannot manage users or system config |
| **reader** | `reader` | Read-only access to assigned spaces; can query, list, get — cannot create, update, delete data |

### 3.2 Space Access

Non-admin users have a per-space access map that defines which spaces they can access and their access level in each:

- **Per-space roles**: `{"space_a": "rw", "space_b": "r"}` — read-write in space_a, read-only in space_b
- **Wildcard**: `{"*": "rw"}` or `{"*": "r"}` — access to all spaces at the specified level (useful for service accounts)

**Global role constrains maximum access level:**
- `admin` — full access to all spaces + admin functions
- `user` — may have `rw` or `r` per space (per-space map determines actual level)
- `reader` — **always read-only**. The `user_space_access` table must only contain `access_level = 'r'` entries for a reader. Enforced at both write time (reject `rw` assignment) and read time (cap to `r`).

Admin users implicitly have full access to all spaces. The per-space map allows a `user` role to have different access levels across different spaces (e.g., a developer with rw on their team's space but read-only on shared reference data).

### 3.3 Permission Matrix

| Operation | admin | user (own spaces) | reader (own spaces) | user/reader (other spaces) |
|-----------|-------|-------------------|---------------------|---------------------------|
| List spaces (filtered) | all | assigned only | assigned only | hidden |
| Create/delete/configure spaces | all | **denied** | **denied** | denied |
| SPARQL SELECT/CONSTRUCT | all | assigned | assigned | denied |
| SPARQL INSERT/UPDATE/DELETE | all | assigned | **denied** | denied |
| KGEntity/Frame/Type CRUD | all | assigned | read ops only | denied |
| Object CRUD | all | assigned | read ops only | denied |
| Graph management (create/delete) | all | assigned | **denied** | denied |
| Import/Export | all | **denied** | **denied** | denied |
| Triples browse | all | assigned | assigned | denied |
| Files (upload/download/delete) | all | assigned | read (download) only | denied |
| KG Query (structured queries) | all | assigned | assigned | denied |
| KG Relations | all | assigned | assigned | denied |
| MetaQL Query | all | assigned | assigned | denied |
| MetaQL Update | all | assigned | **denied** | denied |
| Process (background jobs) | all | assigned | read ops only | denied |
| Metrics | all | all | all | all |
| Entity registry | all | assigned | read ops only | denied |
| User management | all | **denied** | **denied** | denied |
| System admin (DB ops) | all | **denied** | **denied** | denied |
| Agent registry | all | assigned | read ops only | denied |

### 3.4 JWT Claims

```json
{
  "sub": "jsmith",
  "role": "user",
  "spaces": {"customer_data": "rw", "analytics": "r", "staging": "rw"},
  "full_name": "Jane Smith",
  "email": "jsmith@example.com",
  "type": "access",
  "exp": 1720000000
}
```

The `spaces` claim is a map of space_id → access level (`"rw"` or `"r"`). It is authoritative for the token's lifetime. If an admin changes a user's space access, existing tokens remain valid until expiry (max 30 minutes). A forced refresh picks up the new claims.

---

## 4. Implementation Phases

### Phase 1: Secure Foundation (password hashing + DB-backed users)

**Goal**: Eliminate plaintext passwords and the in-memory user store.

#### 4.1.1 Password Hashing

All passwords stored as bcrypt hashes using the `bcrypt` library directly (no `passlib` wrapper).

```python
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
```

#### 4.1.2 Database User Table Enhancement

Extend the existing `"user"` table (both backends already define it):

```sql
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'user';
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_time TIMESTAMPTZ DEFAULT now();
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
```

Per-space access is stored in a separate join table:

```sql
CREATE TABLE IF NOT EXISTS user_space_access (
    user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
    space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
    access_level VARCHAR(2) NOT NULL CHECK (access_level IN ('rw', 'r')),
    granted_by VARCHAR(255),
    granted_time TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, space_id)
);

CREATE INDEX IF NOT EXISTS idx_usa_space ON user_space_access(space_id);
CREATE INDEX IF NOT EXISTS idx_usa_user ON user_space_access(user_id);
```

A wildcard entry uses `space_id = '*'` (not a real FK, but checked in application logic).

Deprecate the plaintext `password` column; new code reads `password_hash`. Migration script hashes existing passwords.

#### 4.1.3 Admin Bootstrap

On startup, if no users exist in the database:
1. Read `auth.root_username` / `auth.root_password` from config (or env vars)
2. Create the admin user with bcrypt-hashed password and `role='admin'`
3. Log a warning if using the default `admin/admin` credentials

This replaces the hardcoded dict.

#### 4.1.4 VitalGraphAuth Refactor

Replace the in-memory dict with database queries:

```python
class VitalGraphAuth:
    def __init__(self, secret_key: str, db_impl):
        self.jwt_auth = JWTAuth(secret_key)
        self.db = db_impl  # database implementation
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

    async def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        user = await self.db.get_user_by_username(username)
        if user and verify_password(password, user['password_hash']):
            await self.db.update_last_login(username)
            return user
        return None
```

**Files to modify**:
- `vitalgraph/auth/vitalgraph_auth.py` — remove `users_db`, add `db_impl` param
- `vitalgraph/auth/jwt_auth.py` — no changes needed
- `vitalgraph/impl/vitalgraphapp_impl.py` — pass `db_impl` to `VitalGraphAuth`
- `vitalgraph/api/vitalgraph_api.py` — unify user CRUD to use `db_impl` exclusively
- `vitalgraph/db/common/models.py` — extend `UserData` with new fields
- `vitalgraph/db/fuseki_postgresql/postgresql_schema.py` — add columns
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — add columns

### Phase 2: Role Enforcement

**Goal**: Enforce role-based access on every endpoint.

#### 4.2.1 Role Dependency Functions

Create reusable FastAPI dependencies:

```python
# vitalgraph/auth/role_dependencies.py

def require_role(*allowed_roles: str):
    """FastAPI dependency that checks user role."""
    def dependency(current_user: Dict = Depends(get_current_user)):
        if current_user.get('role') not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return dependency

def get_space_access(current_user: Dict, space_id: str) -> Optional[str]:
    """Return user's effective access level for a space: 'rw', 'r', or None.
    Enforced at both write time and read time."""
    if current_user.get('role') == 'admin':
        return 'rw'
    spaces = current_user.get('spaces', {})
    level = spaces.get('*') or spaces.get(space_id)
    if level is None:
        return None
    # Defense in depth: reader role is always capped at 'r'
    if current_user.get('role') == 'reader':
        return 'r'
    return level

def require_space_read(current_user: Dict, space_id: str):
    """Check user has at least read access to the space."""
    access = get_space_access(current_user, space_id)
    if access not in ('r', 'rw'):
        raise HTTPException(status_code=403, detail="Access denied for this space")

def require_space_write(current_user: Dict, space_id: str):
    """Check user has write access to the space."""
    access = get_space_access(current_user, space_id)
    if access != 'rw':
        raise HTTPException(status_code=403, detail="Write access denied for this space")

require_admin = require_role('admin')
```

#### 4.2.2 Endpoint Annotations

Each endpoint class adds the appropriate dependency. Example pattern:

```python
# Read endpoints — requires at least 'r' on the space
@self.router.get("/spaces/{space_id}/kgentities", ...)
async def list_entities(space_id: str, current_user = Depends(get_current_user)):
    require_space_read(current_user, space_id)
    ...

# Write endpoints — requires 'rw' on the space
@self.router.post("/spaces/{space_id}/kgentities", ...)
async def create_entity(space_id: str, current_user = Depends(get_current_user)):
    require_space_write(current_user, space_id)
    ...

# Admin endpoints — requires admin role
@self.router.post("/users", ...)
async def create_user(current_user = Depends(require_admin)):
    ...
```

#### 4.2.3 Space Filtering

`list_spaces` returns only spaces the user has access to:

```python
async def list_spaces(self, current_user: Dict):
    all_spaces = self.space_manager.list_space_records()
    if current_user.get('role') == 'admin':
        return all_spaces
    spaces_map = current_user.get('spaces', {})
    if '*' in spaces_map:
        return all_spaces
    return [s for s in all_spaces if s.space_id in spaces_map]
```

**Files to modify**:
- New file: `vitalgraph/auth/role_dependencies.py`
- All endpoint files in `vitalgraph/endpoint/` (~20 files) — add role dependency
- `vitalgraph/api/vitalgraph_api.py` — add space filtering

### Phase 3: User Management API

**Goal**: Full CRUD for users via the REST API, admin-only.

#### 4.3.1 API Endpoints

| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | `/api/users` | admin | List all users (excluding password hashes) |
| GET | `/api/users/{user_id}` | admin | Get user details |
| POST | `/api/users` | admin | Create user (username, password, role, spaces, email) |
| PUT | `/api/users/{user_id}` | admin | Update user fields (password change hashes new value) |
| DELETE | `/api/users/{user_id}` | admin | Deactivate user (set `is_active=false`) |
| POST | `/api/users/{user_id}/reset-password` | admin | Reset password (generates temporary or sets new) |
| PUT | `/api/users/me/password` | any | Change own password (requires current password) |
| GET | `/api/users/me` | any | Get own profile |

#### 4.3.2 Database Methods

Add to `PostgreSQLDbImpl` (both backends):

```python
async def get_user_by_username(self, username: str) -> Optional[Dict]
async def create_user(self, username, password_hash, role, spaces, email, full_name) -> Dict
async def update_user(self, user_id, **fields) -> Dict
async def deactivate_user(self, user_id) -> bool
async def list_users(self) -> List[Dict]
async def update_last_login(self, username) -> None
async def update_password(self, user_id, password_hash) -> bool
```

#### 4.3.3 CLI User Management (`vitalgraphadmin`)

Extend the existing `vitalgraphadmin` CLI with user management commands:

```bash
# List users
vitalgraphadmin user list

# Create user (spaces as space:level pairs)
vitalgraphadmin user create --username jsmith --role user --space "space_a:rw" --space "space_b:r" --email jsmith@example.com

# Update user spaces
vitalgraphadmin user update jsmith --space "space_a:rw" --space "space_b:rw" --space "space_c:r"

# Reset password
vitalgraphadmin user reset-password jsmith

# Deactivate user
vitalgraphadmin user deactivate jsmith

# Create API key
vitalgraphadmin apikey create --user jsmith --name "CI Pipeline" --role user --spaces "space_a"

# List API keys
vitalgraphadmin apikey list

# Revoke API key
vitalgraphadmin apikey revoke <key_id>
```

The CLI connects directly to the database (same as existing `vitalgraphadmin` commands for space/graph management), bypassing the API layer. This allows user management even when the server is down.

**Files to modify**:
- `vitalgraph/endpoint/users_endpoint.py` — real CRUD with role checks
- `vitalgraph/api/vitalgraph_api.py` — delegate to db methods
- `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` — add `user` and `apikey` subcommands
- `vitalgraph/db/fuseki_postgresql/postgresql_db_impl.py` — add user queries
- `vitalgraph/db/sparql_sql/sparql_sql_db_impl.py` — add user queries (if applicable)
- `vitalgraph/model/users_model.py` — add request/response models for new endpoints

### Phase 4: Token Hardening

**Goal**: Add token revocation, rotation support, and API key access.

#### 4.4.1 Token Version / Revocation

Add a `token_version` integer column to the user table. Include it in JWT claims. On password change or explicit revocation, increment the version. During token verification, check that the token's version matches the current database value.

```python
# In verify flow:
payload = jwt.decode(token, ...)
user = await db.get_user_by_username(payload['sub'])
if user['token_version'] != payload.get('token_version'):
    raise HTTPException(401, "Token has been revoked")
```

This provides O(1) revocation without a token blacklist.

#### 4.4.2 API Keys (Service Accounts)

For programmatic access (CI/CD, scripts, external integrations), support long-lived API keys:

```sql
CREATE TABLE IF NOT EXISTS api_key (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_prefix VARCHAR(8) NOT NULL,       -- first 8 chars for identification
    key_hash VARCHAR(255) NOT NULL,        -- bcrypt hash of full key
    user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_time TIMESTAMPTZ DEFAULT now(),
    last_used TIMESTAMPTZ,
    expires_at TIMESTAMPTZ                 -- NULL = never expires
);
```

API keys inherit the owning user's role and per-space access map. They are sent as `Authorization: Bearer vg_xxxx...` (prefixed with `vg_` for identification). The auth layer detects the prefix, validates via hash lookup, then loads the owning user's role/spaces for authorization.

#### 4.4.3 JWT Secret Rotation

Support dual secrets during rotation:

```yaml
auth:
  jwt_secret: "new-secret-key"
  jwt_secret_previous: "old-secret-key"   # optional, accepted during rotation window
```

During verification, try the primary secret first, then fall back to the previous secret. This allows zero-downtime rotation.

**Files to modify**:
- `vitalgraph/auth/jwt_auth.py` — add dual-secret support
- `vitalgraph/auth/vitalgraph_auth.py` — API key detection and validation
- Schema files — add `api_key` table and `token_version` column
- `vitalgraph/model/` — add API key request/response models
- New endpoint: `vitalgraph/endpoint/api_keys_endpoint.py`

### Phase 5: Frontend & Client Updates

**Goal**: Support multi-user login, role-aware UI, and self-service password change.

#### 4.5.1 Frontend Changes

- **Login page**: No changes needed (username/password form already exists)
- **Role-aware navigation**: Hide admin-only pages (Users, System) for non-admin users based on `role` from login response
- **Space filtering**: UI already fetches spaces from `/api/spaces` — server-side filtering handles access control automatically
- **Password change**: Add "Change Password" form in user profile (calls `PUT /api/users/me/password`)
- **User management page**: Admin-only page for CRUD on users (list, create, edit roles/spaces, deactivate)

#### 4.5.2 Client Library Changes

- `VitalGraphClient` — already handles JWT login/refresh; minimal changes needed
- Add `api_key` auth mode: if config provides `api_key` instead of `username/password`, use bearer token directly without login flow
- Add user management methods for admin operations

**Files to modify**:
- `frontend/src/services/AuthService.ts` — pass role to UI context
- `frontend/src/contexts/AuthContext.tsx` — expose role for conditional rendering
- `frontend/src/App.tsx` — conditional routes based on role
- `vitalgraph/client/vitalgraph_client.py` — API key auth mode
- `vitalgraph/client/config/client_config_loader.py` — `api_key` config field

---

## 5. Database Migration Strategy

### 5.1 Migration Script

A migration script handles the transition from the current schema:

```python
async def migrate_auth_schema(conn):
    """Migrate user table to support modern auth."""
    # 1. Add new columns to user table
    await conn.execute('''
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'user';
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_time TIMESTAMPTZ DEFAULT now();
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
    ''')

    # 2. Create user_space_access table
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS user_space_access (
            user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
            space_id VARCHAR(255) NOT NULL,
            access_level VARCHAR(2) NOT NULL CHECK (access_level IN ('rw', 'r')),
            granted_by VARCHAR(255),
            granted_time TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, space_id)
        )
    ''')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_usa_space ON user_space_access(space_id)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_usa_user ON user_space_access(user_id)')

    # 3. Hash existing plaintext passwords
    rows = await conn.fetch('SELECT user_id, password FROM "user" WHERE password IS NOT NULL AND password_hash IS NULL')
    for row in rows:
        hashed = hash_password(row['password'])
        await conn.execute('UPDATE "user" SET password_hash = $1 WHERE user_id = $2', hashed, row['user_id'])

    # 4. Create API key table (inherits role/spaces from owning user)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS api_key (
            key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_prefix VARCHAR(8) NOT NULL,
            key_hash VARCHAR(255) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_time TIMESTAMPTZ DEFAULT now(),
            last_used TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        )
    ''')

    # 5. Create indexes
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_apikey_prefix ON api_key(key_prefix)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_apikey_user ON api_key(user_id)')
```

---

## 6. Security Considerations

### 6.1 Password Requirements

Enforce minimum standards on user creation/password change:
- Minimum 8 characters
- Configurable via `auth.min_password_length` in config
- No complexity rules initially (keep it startup-friendly)

### 6.2 Rate Limiting

Add login attempt rate limiting:
- 5 failed attempts per username within 15 minutes triggers a 30-second delay
- Tracked in-memory (no DB writes for failed attempts)
- Configurable via `auth.max_login_attempts` and `auth.lockout_seconds`

### 6.3 Token Lifetimes

| Token Type | Default | Configurable |
|-----------|---------|-------------|
| Access token | 30 minutes | `auth.access_token_expire_minutes` |
| Refresh token | 7 days | `auth.refresh_token_expire_days` |
| API key | No expiry | Per-key `expires_at` |

### 6.4 Audit Logging

Log auth events to the application log:
- Login success/failure (username, IP, timestamp)
- User creation/modification/deactivation
- Password changes
- API key creation/revocation
- Token refresh events

No separate audit table initially — structured log entries are sufficient for startup usage.

---

## 7. Configuration Changes

### 7.1 Extended Config Template

```yaml
auth:
  root_username: "admin"
  root_password: "change-me-in-production"    # only used for initial bootstrap
  jwt_secret: ""                               # REQUIRED (or JWT_SECRET_KEY env var)
  jwt_secret_previous: ""                      # optional, for rotation
  access_token_expire_minutes: 30
  refresh_token_expire_days: 7
  min_password_length: 8
  max_login_attempts: 5
  lockout_seconds: 30
```

### 7.2 Environment Variables

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET_KEY` | Primary JWT signing secret (required) |
| `JWT_SECRET_KEY_PREVIOUS` | Previous secret for rotation |
| `AUTH_ROOT_USERNAME` | Bootstrap admin username |
| `AUTH_ROOT_PASSWORD` | Bootstrap admin password |

---

## 8. Implementation Priority & Effort Estimates

| Phase | Priority | Effort | Dependencies |
|-------|----------|--------|-------------|
| Phase 1: Secure Foundation | **Critical** | 2-3 days | None |
| Phase 2: Role Enforcement | **High** | 2-3 days | Phase 1 |
| Phase 3: User Management API | **High** | 1-2 days | Phase 1 |
| Phase 4: Token Hardening | Medium | 2-3 days | Phase 1 |
| Phase 5: Frontend & Client | Medium | 2-3 days | Phases 1-3 |

**Recommended order**: Phase 1 → Phase 3 → Phase 2 → Phase 5 → Phase 4

Phase 3 before Phase 2 because you need user management to create users with roles before you can enforce those roles.

---

## 9. Testing Plan

### 9.1 Unit Tests

- Password hashing round-trip
- JWT creation with role + spaces claims
- Role dependency functions (allowed/denied for each role)
- Space access filtering logic
- Token version revocation check

### 9.2 Integration Tests

- Admin bootstrap on fresh database
- Login flow → access token → API call → success
- Login with wrong password → 401
- User with `reader` role → write attempt → 403
- User with `user` role for space_a → access space_b → 403
- Token refresh after password change → old tokens rejected
- API key authentication flow
- Migration script on existing database

### 9.3 Client Tests

- `VitalGraphClient` login with new user
- Client with API key auth mode
- Client space operations filtered by role

---

## 10. Comparison Summary

| Feature | Current VitalGraph | After Modernization | Qdrant | Stardog | Fuseki |
|---------|-------------------|---------------------|--------|---------|--------|
| Password storage | Plaintext | bcrypt | N/A (API key) | bcrypt | SHA-256 |
| Multi-user | No | Yes | Yes (JWT) | Yes | Yes (INI) |
| Roles | None enforced | admin/user/reader | manage/rw/r | Custom RBAC | URL ACLs |
| Resource scoping | None | Per-space | Per-collection | Per-database | URL patterns |
| API keys | No | Yes | Yes | No | No |
| Token revocation | No | Version-based | Claim-based | Session | N/A |
| User mgmt API | Stubs only | Full CRUD (API + CLI) | No | CLI + API | No (file) |
| External IdP | No | Future (OIDC) | No | LDAP/Kerberos | Shiro plugins |

The proposed model is most similar to **Qdrant's granular RBAC** approach — JWT with role and resource claims, three access levels, admin key for management — adapted to VitalGraph's space-based architecture. It avoids the complexity of Stardog's fine-grained permission matrix while providing meaningful access control for startup/small-team usage.

---

## 11. Open Questions

| # | Question | Decision |
|---|----------|----------|
| 1 | Should API keys have independent role/spaces or inherit from the owning user? | **Inherit from owning user** |
| 2 | Should deactivating a user immediately invalidate all their tokens? | **Yes** — bump token_version on deactivate |
| 3 | Does the `tenant` column on the user table have a role in access control? | **No** — tenant is unused for auth, kept for future multi-org |
| 4 | Should `user` role be able to create/delete graphs within their assigned spaces? | **Yes** |
| 5 | Token version check — hit DB on every request or cache with short TTL? | **Cache** (60s TTL) |
| 6 | Should there be a distinct "service account" type vs regular user with API key? | **No** — regular user + API key (simpler model) |
| 7 | Export — should `reader` role be able to export data from their spaces? | **No** — export denied for reader |
| 8 | Is OIDC/external IdP in scope for initial implementation? | **No** — future phase |
| 9 | Password on create — admin sets password, or invite-link with user-set password? | **Admin sets** initially, self-service change later |
| 10 | Should the system support per-space role overrides? | **Yes** — user may have rw in one space and read-only in another, on a per-space basis |

---

## 12. Implementation Status

**Status: Core implementation complete** (June 2026)

### 12.1 Completed

| Step | Description | Files |
|------|-------------|-------|
| 1 | Password hashing utilities (bcrypt directly, no passlib) | `vitalgraph/auth/password.py` |
| 3 | Role & space access dependency functions | `vitalgraph/auth/role_dependencies.py` |
| 4 | Extended `UserData` model (role, is_active, token_version, timestamps) + `UserSpaceAccess` | `vitalgraph/db/common/models.py` |
| 5 | DB schema updates — new user columns + `user_space_access` table | `vitalgraph/db/sparql_sql/sparql_sql_schema.py`, `vitalgraph/db/fuseki_postgresql/postgresql_schema.py` |
| 6 | `VitalGraphAuth` full rewrite — DB-backed, bcrypt, bootstrap admin, per-space JWT claims, token versioning | `vitalgraph/auth/vitalgraph_auth.py` |
| 7 | `UserManagementMixin` — DB user CRUD + space access, integrated into both DB impls | `vitalgraph/db/user_management.py`, both `*_db_impl.py` |
| 8 | `VitalGraphAPI` updates — async login, DB-backed user CRUD, token revocation on refresh, space-filtered `list_spaces` | `vitalgraph/api/vitalgraph_api.py` |
| 9 | Auth schema migration script (standalone CLI + importable) | `vitalgraph/db/migrations/migrate_auth_schema.py` |
| 10 | CLI user management — `user list/add/delete/password/role/deactivate/activate/grant/revoke/spaces` + `migrate auth` | `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` |
| 11 | Users endpoint role enforcement — all user CRUD endpoints require admin | `vitalgraph/endpoint/users_endpoint.py` |
| 12 | App init wiring — db_impl passed to auth, bootstrap admin from config | `vitalgraph/impl/vitalgraphapp_impl.py` |
| 13 | Fixed `jwt_auth.py` type annotation (`expiry_seconds: int | None`) | `vitalgraph/auth/jwt_auth.py` |
| 14 | Space access enforcement on all data endpoints — `require_space_read`/`require_space_write` wired into every route handler | `kgentities_endpoint.py`, `kgframes_endpoint.py`, `kgtypes_endpoint.py`, `objects_endpoint.py`, `kgrelations_endpoint.py`, `kgquery_endpoint.py`, `triples_endpoint.py`, `files_endpoint.py`, `sparql_query_endpoint.py`, `sparql_insert_endpoint.py`, `sparql_delete_endpoint.py`, `sparql_update_endpoint.py`, `sparql_graph_endpoint.py`, `spaces_endpoint.py` |
| 15 | Import/export endpoints enforced as admin-only (`require_admin` on all routes) | `export_endpoint.py`, `import_endpoint.py` |
| 16 | Space listing/filtering restricted to accessible spaces only (admins see all; non-admins filtered by `get_space_access`) | `spaces_endpoint.py` (`_filter_accessible_spaces` helper) |
| 17 | Spaces endpoint — `require_admin` for create/delete, `require_space_write` for update, `require_space_read` for get/info/analytics | `spaces_endpoint.py` |
| 18 | Token version cache (60s TTL) — in-memory cache checking `token_version` on every request with DB fallback on miss; immediate invalidation on password change | `vitalgraph/auth/token_version_cache.py` (new), `vitalgraph/auth/vitalgraph_auth.py` |
| 19 | Self-service password change endpoint (`POST /me/password`) with current password verification, token_version bump, and cache invalidation | `vitalgraph/endpoint/users_endpoint.py`, `vitalgraph/model/users_model.py` |

### 12.2 Sub-Plans (Completed)

Detailed plans for the following features are in separate documents:

| Sub-Plan | Document | Status |
|----------|----------|--------|
| **API Key Support** | [`api_key_support_plan.md`](api_key_support_plan.md) | ✅ Complete (11/11 steps) |
| **Auth Audit Logging** | [`auth_audit_logging_plan.md`](auth_audit_logging_plan.md) | ✅ Complete (13/13 steps — API key audit events instrumented) |

#### API Key Support Summary
Full implementation: key generation (`vg_` prefix, 40 chars), bcrypt hashing, DB CRUD, auth flow detection, self-service REST endpoints, CLI commands, `VitalGraphClient` `api_key` param. Migration applied to `sparql_sql_graph`. `passlib` dependency removed — uses `bcrypt` directly.

#### Auth Audit Logging Summary
Structured `audit_log` table with `emit_audit_event()`, middleware for IP/UA context, instrumented login/logout/user CRUD/space access/role enforcement events, CLI `audit tail/purge/count` commands.

### 12.3 Not Yet Implemented (Future Work)

| Item | Notes |
|------|-------|
| ~~API key authentication~~ | **DONE** — see [`api_key_support_plan.md`](api_key_support_plan.md) |
| ~~Audit logging for auth events~~ | **DONE** — see [`auth_audit_logging_plan.md`](auth_audit_logging_plan.md) |
| ~~Space access enforcement on data endpoints~~ | **DONE** — wired into all 16 endpoint files (see step 14-17 above) |
| ~~Token version cache (60s TTL)~~ | **DONE** — `TokenVersionCache` class + integration into `get_current_user` dependency (see section 14) |
| ~~Self-service password change endpoint~~ | **DONE** — `POST /me/password` in `users_endpoint.py` (see section 15) |
| ~~Frontend login flow updates~~ | **DONE** — `AuthService.ts` extracts `role` from login response; `AuthContext.tsx` exposes via `useAuth()`; `Layout.tsx` conditionally hides admin sidebar (`user?.role === 'admin'`) |
| ~~Frontend API key admin panel~~ | **DONE** — `pages/ApiKeys.tsx` implements full CRUD; accessible from user dropdown + admin sidebar |
| OIDC / external IdP | Out of scope for initial phase |

### 12.4 Deployment Steps

1. Install updated dependencies: `pip install -e ".[server]"`
2. Run auth migration: `python -m vitalgraph.db.migrations.migrate_auth_schema --database <db_name>` (or `--dsn <dsn>`)
3. Create first admin user: `vitalgraphadmin` → `connect;` → `user add admin <password> admin;`
4. Grant space access as needed: `user grant <username> <space_id> rw;`
5. Set `JWT_SECRET_KEY` and optionally `AUTH_ROOT_USERNAME` / `AUTH_ROOT_PASSWORD` env vars
6. Restart server — bootstrap admin is used only until DB users exist

---

## 13. Space Access Enforcement on Data Endpoints

### 13.1 Goal

Wire the existing `require_space_read` and `require_space_write` helpers (from `vitalgraph/auth/role_dependencies.py`) into **every endpoint that accesses data within a space** so that:
- **Read** operations (GET, LIST) require at least `r` access to the target space
- **Write** operations (POST, PUT, DELETE) require `rw` access to the target space
- **Admin** role bypasses all space checks (already handled inside the helpers)

**Out of scope for space access** — these resources are global (not space-scoped). They use role-based access only:

| Resource | Access Rule |
|----------|-------------|
| **Entity Registry** (`/api/entity-registry/...`) | `user`/`admin` = rw, `reader` = read-only |
| **Agent Registry** (`/api/agents/...`) | `user`/`admin` = rw, `reader` = read-only |
| **Process Endpoint** (`/processes/...`) | `admin` only (system maintenance) |
| **Metrics Endpoint** (`/spaces/{space_id}/metrics`) | Observability — any authenticated user (read-only) |
| **Admin Endpoint** (`/resync`) | `admin` only |
| **Users Endpoint** (`/api/users/...`) | `admin` only (already enforced) |

**In scope** — all data stored within spaces requires space access enforcement:

### 13.2 Affected Endpoints

| Endpoint File | Routes | Access Required |
|---------------|--------|-----------------|
| `kgentities_endpoint.py` | GET (list/get) | read |
| | POST / PUT / DELETE | write |
| `kgframes_endpoint.py` | GET (list/get) | read |
| | POST / PUT / DELETE | write |
| `kgtypes_endpoint.py` | GET (list/get) | read |
| | POST / PUT / DELETE | write |
| `objects_endpoint.py` | GET (list/get) | read |
| | POST / PUT / DELETE | write |
| `kgrelations_endpoint.py` | GET (list/get), POST /kgrelations/query | read |
| | POST (create/update) / DELETE | write |
| `kgquery_endpoint.py` | POST /kgqueries | read |
| `triples_endpoint.py` | GET /triples | read |
| | POST / DELETE | write |
| `files_endpoint.py` | GET (list/get/download) | read |
| | POST / PUT / DELETE / upload | write |
| `sparql_query_endpoint.py` | GET/POST `/{space_id}/query` | read |
| `sparql_insert_endpoint.py` | POST `/{space_id}/insert` | write |
| `sparql_delete_endpoint.py` | POST `/{space_id}/delete` | write |
| `sparql_update_endpoint.py` | POST `/{space_id}/update` | write |
| `sparql_graph_endpoint.py` | GET `/{space_id}/graphs` | read |
| | PUT/DELETE `/{space_id}/graph/{uri}` | write |
| `spaces_endpoint.py` | GET /spaces/{space_id}, GET .../info, GET .../analytics | read |
| | PUT /spaces/{space_id} | write |
| | POST /spaces (create), DELETE /spaces/{space_id} | admin |
| `export_endpoint.py` | All routes (create/list/get/update/delete/execute/status/download) | **admin only** |
| `import_endpoint.py` | All routes (create/list/get/update/delete/execute/status/log/upload) | **admin only** |

**Not yet routed** (future — will need enforcement when implemented):
- `metaql_query_endpoint.py` — empty
- `metaql_update_endpoint.py` — empty

### 13.2.1 Implementation Status

**Status: COMPLETE** (June 7, 2026)

All endpoints listed above have been wired with the appropriate enforcement calls. See section 12.1, steps 14–17 for the full file list.

Additional behaviors implemented:
- **Space listing/filtering** (`list_spaces`, `filter_spaces`) now filters results to only expose spaces the user has access to. Admins see all spaces; non-admin users see only spaces where `get_space_access()` returns `'r'` or `'rw'`.
- **Import/Export** are admin-only (not per-space) since they are system-level operations.
- **Space create/delete** are admin-only via `require_admin`.

### 13.3 Integration Pattern

Each endpoint already receives `current_user` from the auth dependency. The `space_id` is a path parameter. Add the check at the top of each handler:

```python
from vitalgraph.auth.role_dependencies import require_space_read, require_space_write

# Read endpoint example
async def list_entities(
    space_id: str,
    graph_id: str,
    current_user: Dict = Depends(auth_dependency),
):
    require_space_read(current_user, space_id)
    # ... existing logic ...

# Write endpoint example
async def create_entity(
    space_id: str,
    graph_id: str,
    body: ...,
    current_user: Dict = Depends(auth_dependency),
):
    require_space_write(current_user, space_id)
    # ... existing logic ...
```

No new dependencies or middleware needed — it's a single function call per handler.

### 13.4 SPARQL Endpoint Special Case

The SPARQL endpoint accepts arbitrary queries. Determining read vs write:
- Parse the SPARQL operation type (already done for routing to Fuseki)
- `SELECT`, `ASK`, `DESCRIBE`, `CONSTRUCT` → `require_space_read`
- `INSERT`, `DELETE`, `LOAD`, `CLEAR` → `require_space_write`

If the query targets multiple graphs across spaces, each space must be individually checked.

### 13.5 Implementation Steps

| Step | Task | Files |
|------|------|-------|
| 1 | Add `require_space_read(current_user, space_id)` to all GET/LIST handlers | `kgentities_endpoint.py`, `kgframes_endpoint.py`, `kgtypes_endpoint.py`, `objects_endpoint.py` |
| 2 | Add `require_space_write(current_user, space_id)` to all POST/PUT/DELETE handlers | Same files |
| 3 | Add space check to SPARQL endpoint based on operation type | `sparql_endpoint.py` |
| 4 | Add space check to spaces GET/PUT endpoints | `spaces_endpoint.py` |
| 5 | Verify admin bypass works (admin role → no 403) | Integration test |
| 6 | Test reader role → write attempt → 403 | Integration test |
| 7 | Test user with access to space_a → access space_b → 403 | Integration test |

### 13.6 Error Response

All space access denials return:

```json
{
  "detail": "Access denied for space 'space_xyz'"
}
```
or
```json
{
  "detail": "Write access denied for space 'space_xyz'"
}
```

HTTP status: **403 Forbidden**

### 13.7 JWT Claims Reference

The `current_user` dict (decoded from JWT) contains the space map:

```json
{
  "sub": "jsmith",
  "role": "user",
  "spaces": {
    "space_a": "rw",
    "space_b": "r"
  },
  "token_version": 3
}
```

The `get_space_access()` helper checks `spaces[space_id]` or `spaces["*"]` (wildcard), capping readers at `r` regardless of stored value.

---

## 14. Token Version Cache (60s TTL)

### 14.1 Problem

Currently, token version is only verified during `refresh_token` (which hits the DB). Access tokens are validated purely from their JWT signature and expiry — there is no DB check on every request (by design, for performance). However, this means a deactivated user or password-changed user's **existing access tokens remain valid** for up to 30 minutes (the access token lifetime).

The tradeoff:
- **No cache**: Check DB on every authenticated request → adds ~2-5ms latency per request, increases DB load
- **No check at all** (current): Revocation takes up to 30 min to propagate
- **Cache with TTL** (proposed): Revocation propagates within 60s, negligible performance cost

### 14.2 Design

A lightweight in-memory cache mapping `username → token_version`, with entries expiring after 60 seconds.

```python
# vitalgraph/auth/token_version_cache.py

import time
from typing import Dict, Optional, Tuple


class TokenVersionCache:
    """In-memory cache for user token versions with TTL expiry."""

    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[int, float]] = {}  # username → (version, expires_at)

    def get(self, username: str) -> Optional[int]:
        """Get cached token version, or None if expired/missing."""
        entry = self._cache.get(username)
        if entry is None:
            return None
        version, expires_at = entry
        if time.monotonic() > expires_at:
            del self._cache[username]
            return None
        return version

    def set(self, username: str, version: int) -> None:
        """Cache a token version with TTL."""
        self._cache[username] = (version, time.monotonic() + self.ttl)

    def invalidate(self, username: str) -> None:
        """Force-evict a user (called on password change, deactivation)."""
        self._cache.pop(username, None)

    def clear(self) -> None:
        """Clear entire cache (e.g. on server restart)."""
        self._cache.clear()
```

### 14.3 Integration into Auth Flow

In `VitalGraphAuth.create_get_current_user_dependency()`, after JWT signature validation:

```python
async def get_current_user(token: str = Depends(self.oauth2_scheme)):
    # 1. Decode JWT (existing)
    payload = self.jwt_auth.verify_token(token)
    username = payload["sub"]
    token_version_in_jwt = payload.get("token_version", 0)

    # 2. Check token version against cache (NEW)
    cached_version = self._token_version_cache.get(username)
    if cached_version is None:
        # Cache miss — fetch from DB and populate
        user = await self.db_impl.get_user_by_username(username)
        if user is None or not user.get("is_active", True):
            raise HTTPException(status_code=401, detail="User not found or inactive")
        cached_version = user.get("token_version", 0)
        self._token_version_cache.set(username, cached_version)

    if token_version_in_jwt < cached_version:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    # 3. Return user info from JWT claims (no DB hit on cache hit)
    return {
        "username": username,
        "role": payload.get("role", "user"),
        "spaces": payload.get("spaces", {}),
        ...
    }
```

### 14.4 Cache Invalidation

The cache must be invalidated when a user's token version changes:

| Event | Action |
|-------|--------|
| Password changed | `cache.invalidate(username)` |
| User deactivated | `cache.invalidate(username)` |
| Role changed | `cache.invalidate(username)` |
| Token version bumped (explicit revoke) | `cache.invalidate(username)` |

These invalidation calls are added to the `UserManagementMixin` methods and the CLI commands.

### 14.5 Performance Characteristics

| Scenario | DB Queries per Request |
|----------|----------------------|
| Cache hit (common case) | **0** |
| Cache miss (first request or after TTL) | **1** (fetch user record) |
| After revocation | **1** (next request refills cache, then rejects) |

Worst-case propagation delay: **60 seconds** (TTL). This is acceptable because:
- Access tokens already have a 30-minute lifetime
- Reducing revocation window from 30 min to 60s is a major improvement
- Critical revocations (e.g. compromised account) can also be handled by shortening TTL to 0 temporarily

### 14.6 Configuration

```yaml
# vitalgraphdb-config.yaml
auth:
  token_version_cache_ttl_seconds: 60   # 0 = check DB on every request
```

Setting TTL to `0` disables caching entirely (useful for high-security deployments willing to pay the latency cost).

### 14.7 Cross-Instance Invalidation via PostgreSQL NOTIFY (Required)

The cache is **per-process** (in-memory). Cross-instance invalidation **must** use the existing `SignalManager` infrastructure (`vitalgraph/signal/signal_manager.py`) which is already used for:

| Channel | Purpose | Used by |
|---------|---------|--------|
| `vitalgraph_users` | User list changed | NotificationBridge → WebSocket |
| `vitalgraph_user` | Specific user changed | NotificationBridge → WebSocket |
| `vitalgraph_spaces` | Space list changed | NotificationBridge → WebSocket |
| `vitalgraph_space` | Specific space changed | SpaceManager cross-instance sync |
| `vitalgraph_graphs` | Graph list changed | NotificationBridge → WebSocket |
| `vitalgraph_graph` | Specific graph changed | Entity graph cache invalidation |
| `vitalgraph_entity_dedup` | Dedup index sync | EntityRegistryImpl |
| `vitalgraph_cache_invalidate` | Datatype/stats cache | generator.py invalidate functions |
| `vitalgraph_entity_graph` | Entity graph cache | entity_graph_cache |

**New channel for auth cache:**

```python
# In signal_manager.py
CHANNEL_TOKEN_VERSION = "vitalgraph_token_version"
```

**Pattern:**
1. Any process that bumps `token_version` (server endpoint, CLI) sends:
   ```python
   await signal_manager.notify_token_version_changed(username)
   ```
2. All server instances listen on `CHANNEL_TOKEN_VERSION` and call:
   ```python
   auth.invalidate_token_cache(username)
   ```
3. This gives **instant** cross-instance propagation (sub-second) instead of waiting for TTL expiry.

**CLI integration:**
The CLI (`vitalgraphadmin`) runs as a separate process. It must also send the NOTIFY signal after token_version-bumping operations (password, deactivate, role change). The CLI already has `self.db_impl` — the same object `SignalManager.__init__` requires. The CLI can instantiate `SignalManager` directly:

```python
from vitalgraph.signal.signal_manager import SignalManager

# Initialize once per CLI session (e.g., in connect command):
self.signal_manager = SignalManager(self.db_impl)

# After bumping token_version:
await self.signal_manager.notify_token_version_changed(username)
```

This ensures that even CLI-initiated changes propagate instantly to all running server instances via the same NOTIFY infrastructure used by the server.

**Fallback:** The TTL (60s) remains as a safety net in case a NOTIFY is missed (e.g., PostgreSQL connection drop during signal send). The combination provides both correctness and availability.

### 14.8 Implementation Steps

| Step | Task | Files |
|------|------|-------|
| 1 | ~~Create `vitalgraph/auth/token_version_cache.py`~~ | **DONE** |
| 2 | ~~Initialize cache in `VitalGraphAuth.__init__()`~~ | **DONE** |
| 3 | ~~Add cache check in `get_current_user` dependency~~ | **DONE** |
| 4 | ~~Add `CHANNEL_TOKEN_VERSION` to SignalManager + `notify_token_version_changed()`~~ | **DONE** |
| 5 | ~~Register callback in app init: `signal_manager.register_callback(CHANNEL_TOKEN_VERSION, ...)` → `auth.invalidate_token_cache(username)`~~ | **DONE** |
| 6 | ~~Add SignalManager NOTIFY to CLI password/deactivate/role commands~~ | **DONE** |
| 7 | ~~Add `signal_manager.notify_token_version_changed(username)` to password change endpoint~~ | **DONE** |
| 8 | ~~Add TTL config option to config loader~~ | **DONE** |
| 9 | ~~Unit test: cache hit/miss/expiry/invalidation~~ | **DONE** |
| 10 | ~~Integration test: password change → server rejects old token immediately~~ | **DONE** |

---

## 15. Self-Service Password Change Endpoint

### 15.1 Goal

Allow authenticated users to change their own password without admin intervention. The admin-only `user password` CLI command and REST API remain for forced resets; this adds a user-facing endpoint where the caller must prove knowledge of their current password.

### 15.2 Endpoint

```
POST /api/me/password
```

**Authentication**: Standard bearer token (access token required).

### 15.3 Request / Response Models

```python
# vitalgraph/model/users_model.py (additions)

class PasswordChangeRequest(BaseModel):
    current_password: str     # must match stored hash
    new_password: str         # minimum 8 characters

class PasswordChangeResponse(BaseModel):
    message: str = "Password changed successfully"
    tokens_invalidated: bool = True
```

### 15.4 Validation Rules

| Rule | Detail |
|------|--------|
| Current password must match | Verify against stored `password_hash` |
| New password minimum length | 8 characters (configurable) |
| New password ≠ current password | Prevent no-op changes |
| User must be active | Inactive users cannot change password |
| Rate limit | Max 5 attempts per minute per user (prevent brute-force of current password) |

### 15.5 Server-Side Flow

```python
@router.post("/api/me/password", response_model=PasswordChangeResponse)
async def change_password(
    body: PasswordChangeRequest,
    current_user: Dict = Depends(auth_dependency),
):
    username = current_user["username"]

    # 1. Fetch user from DB (need the stored hash)
    user = await db.get_user_by_username(username)
    if not user or not user.get("is_active"):
        raise HTTPException(401, "User not found or inactive")

    # 2. Verify current password
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")

    # 3. Validate new password
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if body.current_password == body.new_password:
        raise HTTPException(400, "New password must differ from current password")

    # 4. Hash and store new password
    new_hash = hash_password(body.new_password)
    await db.update_user_password_hash(username, new_hash)
    # update_user_password_hash bumps token_version internally

    # 5. Invalidate token version cache
    token_version_cache.invalidate(username)

    # 6. Emit audit event
    emit_audit_event("auth.password.changed", username, changed_by=username)

    return PasswordChangeResponse()
```

### 15.6 Token Invalidation Behavior

After password change:
- `token_version` is incremented in the DB (done by `update_user_password_hash`)
- Token version cache is invalidated
- All existing access tokens for this user will be rejected within 60s (cache TTL)
- All existing refresh tokens will fail immediately (DB check on refresh)
- The client should re-login after receiving the success response

### 15.7 Frontend Integration

The frontend password change dialog should:
1. Collect current password + new password + confirm new password
2. `POST /api/me/password` with `{ current_password, new_password }`
3. On success → clear tokens → redirect to login page
4. On `400` → display error message (wrong current password, too short, etc.)

```typescript
// frontend/src/services/AuthService.ts (addition)
async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.makeAuthenticatedRequest('/api/me/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    // Force re-login since all tokens are now invalid
    this.logout();
}
```

### 15.8 Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Brute-force current password | Rate limit: 5 attempts/min/user |
| Weak new password | Minimum 8 chars; optionally add complexity check later |
| Token reuse after change | token_version bump + cache invalidation |
| CSRF | Bearer token auth (not cookie-based) — CSRF not applicable |
| Password in transit | HTTPS required (enforced at deployment level) |
| Audit trail | `auth.password.changed` event logged with actor = self |

### 15.9 Implementation Steps

| Step | Task | Files |
|------|------|-------|
| 1 | ~~Add `PasswordChangeRequest` / `PasswordChangeResponse` models~~ | **DONE** — `vitalgraph/model/users_model.py` |
| 2 | ~~Create `/api/me/password` endpoint~~ | **DONE** — `vitalgraph/endpoint/users_endpoint.py` |
| 3 | ~~Implement handler with current password verification + hash update~~ | **DONE** |
| 4 | ~~Add rate limiting (per-user, 5/min)~~ | **DONE** — in-handler counter |
| 5 | ~~Add frontend password change dialog~~ | **DONE** — `frontend/src/components/` |
| 6 | ~~Add frontend `changePassword()` method to AuthService~~ | **DONE** — `frontend/src/services/AuthService.ts` |
| 7 | ~~Integration test: change password → old token rejected → re-login works~~ | **DONE** |
| 8 | ~~Integration test: wrong current password → 400~~ | **DONE** |
