"""
Common data models for VitalGraph admin table records.

These dataclasses represent rows in the shared admin tables (install, space,
graph, user, process).  They are used by admin modules, the CLI, and the
API layer to pass structured data instead of raw dicts.

Note: ``SpaceData`` is a *data-record* model (maps to the ``space`` DB table).
The existing ``SpaceRecord`` in ``space/space_manager.py`` is a *runtime*
wrapper that pairs a space_id with its ``SpaceImpl`` — they serve different
purposes and coexist without conflict.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

@dataclass
class InstallData:
    """Row in the ``install`` admin table."""
    id: Optional[int] = None
    install_datetime: Optional[datetime] = None
    update_datetime: Optional[datetime] = None
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Space
# ---------------------------------------------------------------------------

@dataclass
class SpaceData:
    """Row in the ``space`` admin table."""
    space_id: str = ""
    space_name: Optional[str] = None
    space_description: Optional[str] = None
    tenant: Optional[str] = None
    update_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "SpaceData":
        return SpaceData(
            space_id=row.get("space_id", ""),
            space_name=row.get("space_name"),
            space_description=row.get("space_description"),
            tenant=row.get("tenant"),
            update_time=row.get("update_time"),
        )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

@dataclass
class GraphData:
    """Row in the ``graph`` admin table."""
    graph_id: Optional[int] = None
    space_id: str = ""
    graph_uri: Optional[str] = None
    graph_name: Optional[str] = None
    created_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "GraphData":
        return GraphData(
            graph_id=row.get("graph_id"),
            space_id=row.get("space_id", ""),
            graph_uri=row.get("graph_uri"),
            graph_name=row.get("graph_name"),
            created_time=row.get("created_time"),
        )


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

@dataclass
class UserData:
    """Row in the ``user`` admin table."""
    user_id: Optional[int] = None
    username: str = ""
    password: Optional[str] = None
    password_hash: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "user"
    is_active: bool = True
    token_version: int = 0
    tenant: Optional[str] = None
    created_time: Optional[datetime] = None
    last_login: Optional[datetime] = None
    update_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Never expose password fields in serialization
        d.pop("password", None)
        d.pop("password_hash", None)
        return d

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return user data safe for API responses (no secrets)."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "tenant": self.tenant,
            "created_time": self.created_time,
            "last_login": self.last_login,
        }

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "UserData":
        return UserData(
            user_id=row.get("user_id"),
            username=row.get("username", ""),
            password=row.get("password"),
            password_hash=row.get("password_hash"),
            email=row.get("email"),
            full_name=row.get("full_name"),
            role=row.get("role", "user"),
            is_active=row.get("is_active", True),
            token_version=row.get("token_version", 0),
            tenant=row.get("tenant"),
            created_time=row.get("created_time"),
            last_login=row.get("last_login"),
            update_time=row.get("update_time"),
        )


# ---------------------------------------------------------------------------
# User Space Access
# ---------------------------------------------------------------------------

@dataclass
class UserSpaceAccess:
    """Row in the ``user_space_access`` table."""
    user_id: int = 0
    space_id: str = ""
    access_level: str = "r"  # 'rw' or 'r'
    granted_by: Optional[str] = None
    granted_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "UserSpaceAccess":
        return UserSpaceAccess(
            user_id=row.get("user_id", 0),
            space_id=row.get("space_id", ""),
            access_level=row.get("access_level", "r"),
            granted_by=row.get("granted_by"),
            granted_time=row.get("granted_time"),
        )


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------

@dataclass
class ProcessData:
    """Row in the ``process`` admin table."""
    process_id: Optional[str] = None  # UUID as string
    process_type: str = ""
    process_subtype: Optional[str] = None
    status: str = "pending"
    instance_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress_percent: float = 0.0
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    result_details: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "ProcessData":
        return ProcessData(
            process_id=str(row["process_id"]) if row.get("process_id") else None,
            process_type=row.get("process_type", ""),
            process_subtype=row.get("process_subtype"),
            status=row.get("status", "pending"),
            instance_id=row.get("instance_id"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            progress_percent=row.get("progress_percent", 0.0),
            progress_message=row.get("progress_message"),
            error_message=row.get("error_message"),
            result_details=row.get("result_details"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
