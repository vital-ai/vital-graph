# Auth Audit Logging Plan

## Implementation Status

| Step | Task | Status |
|------|------|--------|
| 1 | `audit_log` table DDL in migration script | ✅ Done |
| 2 | `vitalgraph/auth/audit.py` — `emit_audit_event()` + async DB insert | ✅ Done |
| 3 | `vitalgraph/auth/request_context.py` — context vars for IP/UA | ✅ Done |
| 4 | Audit context middleware in `vitalgraphapp_impl.py` | ✅ Done |
| 5 | Audit config in `config_loader.py` | ✅ Done |
| 6 | Instrument `authenticate_user()` — login success/failure/bootstrap | ✅ Done |
| 7 | Instrument `VitalGraphAPI` — logout + token revocation | ✅ Done |
| 8 | Instrument user CRUD — create, delete, deactivate, activate, role, password (API + CLI) | ✅ Done |
| 9 | Instrument space access — grant, revoke (CLI) | ✅ Done |
| 10 | Instrument `role_dependencies` — 403 denied events | ✅ Done |
| 11 | Instrument API key events — create, revoke, used, failure (expired/inactive/mismatch) | ✅ Done |
| 12–13 | CLI `audit tail`, `audit purge`, `audit count` commands | ✅ Done |

### Files Modified/Created

- **New**: `vitalgraph/auth/audit.py`, `vitalgraph/auth/request_context.py`
- **Modified**: `vitalgraph/db/migrations/migrate_auth_schema.py`, `vitalgraph/impl/vitalgraphapp_impl.py`, `vitalgraph/config/config_loader.py`, `vitalgraph/auth/vitalgraph_auth.py`, `vitalgraph/api/vitalgraph_api.py`, `vitalgraph/endpoint/users_endpoint.py`, `vitalgraph/auth/role_dependencies.py`, `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py`

---

## 1. Overview

Add structured audit logging for security-relevant authentication and authorization events. This provides an observable trail for debugging access issues, compliance, and detecting suspicious activity.

**Scope**: Auth-layer events only — not data-plane operations (CRUD on entities/frames/types). Data-plane audit is a separate concern.

---

## 2. Events to Log

| Event | Trigger | Severity | Key Fields |
|-------|---------|----------|------------|
| `auth.login.success` | Successful login | INFO | username, ip, user_agent |
| `auth.login.failure` | Failed login attempt | WARN | username (attempted), ip, reason |
| `auth.logout` | Explicit logout | INFO | username |
| `auth.token.refresh` | Token refresh | DEBUG | username |
| `auth.token.revoked` | Token rejected (version mismatch) | WARN | username, token_version |
| `auth.password.changed` | Password updated (self or admin) | INFO | username, changed_by |
| `auth.user.created` | New user created | INFO | username, role, created_by |
| `auth.user.deleted` | User deleted | WARN | username, deleted_by |
| `auth.user.deactivated` | User deactivated | WARN | username, deactivated_by |
| `auth.user.activated` | User reactivated | INFO | username, activated_by |
| `auth.role.changed` | User role modified | WARN | username, old_role, new_role, changed_by |
| `auth.space_access.granted` | Space access added/changed | INFO | username, space_id, level, granted_by |
| `auth.space_access.revoked` | Space access removed | INFO | username, space_id, revoked_by |
| `auth.apikey.created` | API key created | INFO | key_name, key_prefix, username, created_by |
| `auth.apikey.revoked` | API key deactivated | WARN | key_id, key_name, username, revoked_by |
| `auth.apikey.used` | API key used for auth | DEBUG | key_prefix, username, ip |
| `auth.access.denied` | 403 Forbidden raised | WARN | username, resource, reason |
| `auth.bootstrap.used` | Bootstrap admin login (no DB users) | WARN | username |

---

## 3. Log Entry Structure

Each audit event is a structured JSON log entry:

```json
{
  "timestamp": "2026-06-07T11:08:00.000Z",
  "level": "INFO",
  "event": "auth.login.success",
  "actor": "admin",
  "target": null,
  "ip": "192.168.1.100",
  "user_agent": "Mozilla/5.0 ...",
  "details": {
    "method": "password"
  }
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 | UTC timestamp |
| `level` | string | INFO, WARN, ERROR |
| `event` | string | Dotted event identifier |
| `actor` | string | Who performed the action (username or "system") |
| `target` | string | Who/what was affected (username, key_id, space_id) |
| `ip` | string | Client IP address (when available) |
| `user_agent` | string | Client user-agent header (when available) |
| `details` | object | Event-specific key/value pairs |

---

## 4. Implementation Design

### 4.1 Dedicated Logger

Use a dedicated Python logger (`vitalgraph.audit`) separate from application logs:

```python
# vitalgraph/auth/audit.py

import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

audit_logger = logging.getLogger("vitalgraph.audit")


def emit_audit_event(
    event: str,
    actor: str,
    *,
    target: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    level: str = "INFO",
    **details: Any,
) -> None:
    """Emit a structured audit log event."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "actor": actor,
        "target": target,
        "ip": ip,
        "user_agent": user_agent,
        "details": details if details else None,
    }
    # Remove None values for cleaner output
    entry = {k: v for k, v in entry.items() if v is not None}

    log_level = getattr(logging, level.upper(), logging.INFO)
    audit_logger.log(log_level, json.dumps(entry))
```

### 4.2 Logger Configuration

The audit logger should:
- Write to a **separate file** (`vitalgraph-audit.log`) for easy parsing
- Also propagate to stdout (for container/ECS deployments)
- Use JSON format (one JSON object per line = easy to ingest into log aggregators)
- Be configurable via `vitalgraphdb-config.yaml`

```yaml
# vitalgraphdb-config.yaml
logging:
  audit:
    enabled: true
    file: /var/log/vitalgraph/audit.log   # null = stdout only
    level: INFO                            # minimum level to emit
    max_size_mb: 100                       # rotate at this size
    backup_count: 10                       # keep this many rotated files
```

### 4.3 Request Context

To capture IP and user-agent, use FastAPI middleware or a dependency that extracts request context:

```python
# vitalgraph/auth/request_context.py

from contextvars import ContextVar
from typing import Optional

_request_ip: ContextVar[Optional[str]] = ContextVar("request_ip", default=None)
_request_ua: ContextVar[Optional[str]] = ContextVar("request_ua", default=None)


def set_request_context(ip: Optional[str], user_agent: Optional[str]) -> None:
    _request_ip.set(ip)
    _request_ua.set(user_agent)


def get_request_ip() -> Optional[str]:
    return _request_ip.get()


def get_request_ua() -> Optional[str]:
    return _request_ua.get()
```

Middleware sets this early in the request lifecycle:

```python
@app.middleware("http")
async def audit_context_middleware(request, call_next):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    set_request_context(ip, ua)
    response = await call_next(request)
    return response
```

---

## 5. Integration Points

### 5.1 VitalGraphAuth

```python
# In authenticate_user():
if success:
    emit_audit_event("auth.login.success", username, ip=get_request_ip(), method="password")
else:
    emit_audit_event("auth.login.failure", username, ip=get_request_ip(),
                     level="WARN", reason="invalid_credentials")

# In bootstrap admin path:
emit_audit_event("auth.bootstrap.used", username, level="WARN", ip=get_request_ip())
```

### 5.2 VitalGraphAPI

```python
# In login():
await self.db.update_last_login(user["username"])
# (audit emitted inside authenticate_user)

# In refresh_token() on revocation:
emit_audit_event("auth.token.revoked", username, level="WARN",
                 token_version=token_ver_in_jwt)
```

### 5.3 UserManagementMixin / CLI

```python
# In create_user():
emit_audit_event("auth.user.created", created_by, target=username, role=role)

# In update_user() when role changes:
emit_audit_event("auth.role.changed", changed_by, target=username,
                 level="WARN", old_role=old_role, new_role=new_role)

# In deactivate:
emit_audit_event("auth.user.deactivated", deactivated_by, target=username, level="WARN")
```

### 5.4 Role Dependencies

```python
# In require_admin / require_space_read / require_space_write on 403:
emit_audit_event("auth.access.denied", current_user.get("username", "unknown"),
                 level="WARN", resource=space_id, reason="insufficient_role")
```

---

## 6. Storage — Database Table

Audit events are written directly to a PostgreSQL table from the start. No file-based phase.

### 6.1 Schema

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    event VARCHAR(50) NOT NULL,
    actor VARCHAR(255),
    target VARCHAR(255),
    ip INET,
    user_agent TEXT,
    details JSONB,
    level VARCHAR(10) NOT NULL DEFAULT 'INFO'
);

CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_event ON audit_log(event);
CREATE INDEX idx_audit_actor ON audit_log(actor);
```

This table is created by the auth schema migration (`migrate auth;`).

### 6.2 Write Path

`emit_audit_event()` inserts asynchronously using the existing DB connection pool:

```python
async def _persist_audit_event(pool, entry: dict) -> None:
    """Insert audit entry into database. Fire-and-forget."""
    try:
        await pool.execute(
            '''INSERT INTO audit_log (event, actor, target, ip, user_agent, details, level)
               VALUES ($1, $2, $3, $4::inet, $5, $6::jsonb, $7)''',
            entry['event'], entry.get('actor'), entry.get('target'),
            entry.get('ip'), entry.get('user_agent'),
            json.dumps(entry.get('details')) if entry.get('details') else None,
            entry.get('level', 'INFO'),
        )
    except Exception as e:
        # Fallback: log to stderr if DB write fails (never block the request)
        logging.getLogger('vitalgraph.audit').error(f"Audit write failed: {e}")
```

The insert is fire-and-forget (wrapped in `asyncio.create_task`) so it never blocks the request path.

### 6.3 Retention

Automatic cleanup via a scheduled task or CLI command:

```sql
DELETE FROM audit_log WHERE timestamp < now() - interval '90 days';
```

Configurable retention period in `vitalgraphdb-config.yaml`.

### 6.4 Benefits

- **Queryable**: SQL filtering by event, actor, time range, IP
- **Integrated**: Same backup/restore as all other VitalGraph data
- **No extra infra**: No log files to manage, rotate, or ship
- **Structured**: JSONB `details` column supports arbitrary event-specific fields
- **CLI queryable**: `audit` commands query the table directly

---

## 7. Implementation Order

| Step | Task | Files |
|------|------|-------|
| 1 | Add `audit_log` table DDL to migration script | `vitalgraph/db/migrations/migrate_auth_schema.py` |
| 2 | Create `vitalgraph/auth/audit.py` — `emit_audit_event()` with async DB insert | New |
| 3 | Create `vitalgraph/auth/request_context.py` — context vars for IP/UA | New |
| 4 | Add audit context middleware to app init | `vitalgraph/impl/vitalgraphapp_impl.py` |
| 5 | Add audit config section to config loader | `vitalgraph/config/config_loader.py` |
| 6 | Instrument `VitalGraphAuth.authenticate_user()` — login success/failure | `vitalgraph/auth/vitalgraph_auth.py` |
| 7 | Instrument `VitalGraphAPI` — logout, refresh, token revocation | `vitalgraph/api/vitalgraph_api.py` |
| 8 | Instrument user CRUD — create, delete, deactivate, role change, password change | `vitalgraph/db/user_management.py`, CLI |
| 9 | Instrument space access — grant, revoke | `vitalgraph/db/user_management.py` |
| 10 | Instrument role dependencies — 403 denied events | `vitalgraph/auth/role_dependencies.py` |
| 11 | Instrument API key events (after API key implementation) | `vitalgraph/auth/vitalgraph_auth.py` |
| 12 | Add `audit` CLI commands: `audit tail`, `audit purge` | `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` |
| 13 | Add retention purge (scheduled or CLI: `audit purge --older-than 90d`) | `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` |

---

## 8. Configuration Example

```yaml
# vitalgraphdb-config.yaml
logging:
  audit:
    enabled: true
    level: INFO                    # DEBUG includes token refreshes and API key usage
    retention_days: 90             # auto-purge entries older than this
    also_log_to_stdout: false      # additionally emit to stdout (useful for containers)
```

For local development, `enabled: false` suppresses all audit writes.

---

## 9. Querying Audit Logs

### SQL (direct)

```sql
-- All failed logins in the last hour
SELECT * FROM audit_log
WHERE event = 'auth.login.failure'
  AND timestamp > now() - interval '1 hour'
ORDER BY timestamp DESC;

-- All role changes
SELECT * FROM audit_log WHERE event = 'auth.role.changed' ORDER BY timestamp DESC;

-- All actions by a specific user
SELECT * FROM audit_log WHERE actor = 'jsmith' ORDER BY timestamp DESC LIMIT 50;

-- All WARN-level events today
SELECT * FROM audit_log
WHERE level = 'WARN' AND timestamp > CURRENT_DATE
ORDER BY timestamp DESC;
```

### CLI commands

```
vitalgraphadmin> audit tail --event auth.login.failure --last 24h;
vitalgraphadmin> audit tail --user jsmith --last 7d;
vitalgraphadmin> audit purge --older-than 90d;
```

---

## 10. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Log injection | JSON encoding prevents newline/field injection |
| Sensitive data | Never log passwords, tokens, or key material |
| Log tampering | DB access controls; row-level immutability (no UPDATE grants on audit_log) |
| Volume attacks | Rate-limited login attempts prevent log flooding |
| PII in logs | Only username and IP — configurable to hash IP if needed |
| Retention | Configurable TTL purge (default 90 days); `audit purge` CLI command |

---

## 11. Testing

- **Unit**: `emit_audit_event` produces correct entry dict and calls DB insert
- **Integration**: Login → verify audit row in `audit_log` table
- **Negative**: Failed login → WARN-level row with reason in details
- **CLI**: `audit tail` command queries and formats correctly
- **Performance**: Audit logging does not add measurable latency (async fire-and-forget insert)
- **Retention**: `audit purge --older-than 7d` removes expected rows
