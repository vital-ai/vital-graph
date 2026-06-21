"""
Role-based access control dependencies for VitalGraph FastAPI endpoints.

Provides reusable dependency functions for checking user roles and
per-space access levels.
"""

from typing import Dict, Optional

from fastapi import HTTPException, status

from .audit import emit_audit_event


# ---------------------------------------------------------------------------
# Role checks
# ---------------------------------------------------------------------------

def require_role(*allowed_roles: str):
    """Return a function that checks if the current user has one of the allowed roles.

    Usage:
        require_admin = require_role('admin')
        require_write_capable = require_role('admin', 'user')
    """
    def check(current_user: Dict) -> Dict:
        if current_user.get('role') not in allowed_roles:
            emit_audit_event("auth.access.denied",
                             current_user.get("username", "unknown"),
                             level="WARN",
                             reason="insufficient_role",
                             required=str(allowed_roles))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return check


# Pre-built role checkers
require_admin = require_role('admin')


# ---------------------------------------------------------------------------
# Space access checks
# ---------------------------------------------------------------------------

def get_space_access(current_user: Dict, space_id: str) -> Optional[str]:
    """Return user's effective access level for a space: 'rw', 'r', or None.

    Access logic:
      - admin role always gets 'rw'
      - Non-admin users check their spaces map (from JWT claims or DB)
      - Wildcard '*' entry applies to all spaces
      - Reader role is capped at 'r' (defense in depth; data should already
        be correct since rw assignment is rejected for readers at write time)

    Args:
        current_user: Dict with 'role' and 'spaces' keys.
        space_id: The space to check access for.

    Returns:
        'rw', 'r', or None (no access).
    """
    if current_user.get('role') == 'admin':
        return 'rw'

    spaces = current_user.get('spaces', {})
    level = spaces.get(space_id) or spaces.get('*')

    if level is None:
        return None

    # Defense in depth: reader role is always capped at 'r'
    if current_user.get('role') == 'reader':
        return 'r'

    return level


def require_space_read(current_user: Dict, space_id: str) -> None:
    """Raise 403 if user does not have at least read access to the space.

    Args:
        current_user: Authenticated user dict.
        space_id: Target space identifier.

    Raises:
        HTTPException 403 if access is denied.
    """
    access = get_space_access(current_user, space_id)
    if access not in ('r', 'rw'):
        emit_audit_event("auth.access.denied",
                         current_user.get("username", "unknown"),
                         level="WARN",
                         reason="no_space_read",
                         space_id=space_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied for space '{space_id}'"
        )


def require_system_space_write(current_user: Dict, space_id: str) -> None:
    """Raise 403 if a non-admin user tries to write to a system space.

    System spaces (e.g. sp_kg_types) are admin-only for writes.
    Must be called **before** require_space_write for system spaces.

    Args:
        current_user: Authenticated user dict.
        space_id: Target space identifier.

    Raises:
        HTTPException 403 if user is not admin.
    """
    from vitalgraph.constants import PROTECTED_SPACES
    if space_id in PROTECTED_SPACES and current_user.get('role') != 'admin':
        emit_audit_event("auth.access.denied",
                         current_user.get("username", "unknown"),
                         level="WARN",
                         reason="system_space_admin_only",
                         space_id=space_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Write access to system space '{space_id}' requires admin role"
        )


def require_space_write(current_user: Dict, space_id: str) -> None:
    """Raise 403 if user does not have write access to the space.

    Args:
        current_user: Authenticated user dict.
        space_id: Target space identifier.

    Raises:
        HTTPException 403 if write access is denied.
    """
    access = get_space_access(current_user, space_id)
    if access != 'rw':
        emit_audit_event("auth.access.denied",
                         current_user.get("username", "unknown"),
                         level="WARN",
                         reason="no_space_write",
                         space_id=space_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Write access denied for space '{space_id}'"
        )
