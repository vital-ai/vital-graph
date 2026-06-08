"""
Auth audit logging — structured event emitter with async DB persistence.

Emits security-relevant events (login, password change, role change, etc.)
as structured JSON to both a Python logger and the audit_log PostgreSQL table.

Usage:
    from vitalgraph.auth.audit import emit_audit_event
    emit_audit_event("auth.login.success", username, ip=get_request_ip())
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .request_context import get_request_ip, get_request_ua

audit_logger = logging.getLogger("vitalgraph.audit")

# Module-level reference to the DB pool; set once during app startup
_db_pool = None
_enabled = True


def configure_audit(db_pool=None, enabled: bool = True) -> None:
    """Configure the audit subsystem. Called once during app startup.

    Args:
        db_pool: asyncpg or compatible pool with execute() method.
        enabled: If False, audit events are silently discarded.
    """
    global _db_pool, _enabled
    _db_pool = db_pool
    _enabled = enabled


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
    """Emit a structured audit log event.

    - Logs to the vitalgraph.audit Python logger (always, for stdout/file).
    - Inserts into audit_log table asynchronously (fire-and-forget).

    Args:
        event: Dotted event name (e.g. "auth.login.success")
        actor: Username who performed the action (or "system")
        target: Who/what was affected (username, space_id, key_id)
        ip: Client IP (auto-filled from request context if None)
        user_agent: Client UA (auto-filled from request context if None)
        level: Log level string (INFO, WARN, ERROR)
        **details: Arbitrary event-specific fields stored in JSONB
    """
    if not _enabled:
        return

    # Auto-fill from request context if not explicitly provided
    if ip is None:
        ip = get_request_ip()
    if user_agent is None:
        user_agent = get_request_ua()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "actor": actor,
        "target": target,
        "ip": ip,
        "user_agent": user_agent,
        "level": level,
        "details": details if details else None,
    }
    # Remove None values for cleaner output
    clean_entry = {k: v for k, v in entry.items() if v is not None}

    # Log to Python logger
    log_level = getattr(logging, level.upper(), logging.INFO)
    audit_logger.log(log_level, json.dumps(clean_entry))

    # Persist to DB (fire-and-forget)
    if _db_pool is not None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist_audit_event(entry))
        except RuntimeError:
            # No running event loop (e.g., CLI context) — skip DB write
            pass


async def _persist_audit_event(entry: dict) -> None:
    """Insert audit entry into database. Fire-and-forget — never blocks request."""
    if _db_pool is None:
        return
    try:
        details_json = json.dumps(entry.get("details")) if entry.get("details") else None
        await _db_pool.execute(
            '''INSERT INTO audit_log (event, actor, target, ip, user_agent, details, level)
               VALUES ($1, $2, $3, $4::inet, $5, $6::jsonb, $7)''',
            entry.get("event"),
            entry.get("actor"),
            entry.get("target"),
            entry.get("ip"),
            entry.get("user_agent"),
            details_json,
            entry.get("level", "INFO"),
        )
    except Exception as e:
        audit_logger.error(f"Audit DB write failed: {e}")
