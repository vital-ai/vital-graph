"""
Admin REST API endpoint for VitalGraph.

Provides administrative operations such as resyncing auxiliary tables
(edge, frame_entity, stats) for the sparql_sql backend, and audit log querying.
"""

import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field


class ResyncResponse(BaseModel):
    """Response model for resync operation."""
    space_id: str
    edge_rows: int
    frame_entity_rows: int
    pred_stats_rows: int
    quad_stats_rows: int
    elapsed_ms: float


class AuditLogEntry(BaseModel):
    """Single audit log entry."""
    id: int
    timestamp: str
    event: str
    actor: str
    target: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[dict] = None
    level: str = "INFO"


class AuditLogResponse(BaseModel):
    """Paginated audit log response."""
    entries: List[AuditLogEntry]
    total_count: int
    limit: int
    offset: int


class AdminEndpoint:
    """REST API endpoint for VitalGraph admin operations."""

    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(__name__)
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Set up FastAPI routes for admin operations."""

        @self.router.post("/resync", response_model=ResyncResponse, tags=["Admin"])
        async def resync_auxiliary_tables(
            space_id: str = Query(..., description="Space ID to resync"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Resync all auxiliary tables (edge, frame_entity, stats) from rdf_quad.

            Rebuilds the maintained tables from scratch, runs ANALYZE on all
            space tables, and invalidates the in-memory stats cache.
            Use after bulk loads, disaster recovery, or manual DB edits.
            """
            # Get backend implementation
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=404, detail=f"Space {space_id} not found")

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")

            # Check that this is the sparql_sql backend
            db_impl = getattr(backend, 'db_impl', None)
            if not db_impl:
                raise HTTPException(
                    status_code=400,
                    detail="Resync is only available for the sparql_sql backend"
                )

            pool = getattr(db_impl, 'connection_pool', None)
            if not pool:
                raise HTTPException(status_code=500, detail="No connection pool available")

            try:
                from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables

                t0 = _time.monotonic()
                async with pool.acquire() as conn:
                    result = await resync_all_auxiliary_tables(conn, space_id)
                elapsed_ms = (_time.monotonic() - t0) * 1000

                self.logger.info(
                    "Admin resync [%s]: edge=%d, frame_entity=%d, pred_stats=%d, quad_stats=%d (%.0fms)",
                    space_id,
                    result['edge_rows'], result['frame_entity_rows'],
                    result['pred_stats_rows'], result['quad_stats_rows'],
                    elapsed_ms,
                )

                return ResyncResponse(
                    space_id=space_id,
                    edge_rows=result['edge_rows'],
                    frame_entity_rows=result['frame_entity_rows'],
                    pred_stats_rows=result['pred_stats_rows'],
                    quad_stats_rows=result['quad_stats_rows'],
                    elapsed_ms=round(elapsed_ms, 1),
                )

            except Exception as e:
                self.logger.error(f"Resync failed for space {space_id}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Resync failed: {str(e)}"
                )


        @self.router.get("/audit", response_model=AuditLogResponse, tags=["Admin"])
        async def get_audit_log(
            event: Optional[str] = Query(None, description="Filter by event name (prefix match)"),
            actor: Optional[str] = Query(None, description="Filter by actor username"),
            level: Optional[str] = Query(None, description="Filter by level (INFO, WARN, ERROR)"),
            last: Optional[str] = Query(None, description="Duration filter, e.g. '24h', '7d'"),
            limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Query the audit log with filters and pagination (admin only)."""
            from ..auth.role_dependencies import require_admin
            require_admin(current_user)

            # Get connection pool from space_manager's db_impl
            pool = None
            if hasattr(self.space_manager, 'db_impl'):
                pool = getattr(self.space_manager.db_impl, 'connection_pool', None)
            if not pool:
                # Try from auth audit module
                from ..auth.audit import _db_pool
                pool = _db_pool
            if not pool:
                raise HTTPException(status_code=503, detail="Database pool not available")

            conditions = []
            params = []
            idx = 1

            if event:
                conditions.append(f"event LIKE ${idx}")
                params.append(f"{event}%")
                idx += 1
            if actor:
                conditions.append(f"actor = ${idx}")
                params.append(actor)
                idx += 1
            if level:
                conditions.append(f"level = ${idx}")
                params.append(level.upper())
                idx += 1
            if last:
                # Parse duration like '24h', '7d', '30m'
                duration_str = last.strip()
                unit = duration_str[-1].lower()
                try:
                    value = int(duration_str[:-1])
                except (ValueError, IndexError):
                    raise HTTPException(status_code=400, detail=f"Invalid duration: {last}")
                if unit == 'h':
                    delta = timedelta(hours=value)
                elif unit == 'd':
                    delta = timedelta(days=value)
                elif unit == 'm':
                    delta = timedelta(minutes=value)
                else:
                    raise HTTPException(status_code=400, detail=f"Unknown duration unit: {unit}")
                cutoff = datetime.now(timezone.utc) - delta
                conditions.append(f"timestamp >= ${idx}")
                params.append(cutoff)
                idx += 1

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            try:
                async with pool.acquire() as conn:
                    # Get total count
                    count_query = f"SELECT COUNT(*) FROM audit_log {where}"
                    total_count = await conn.fetchval(count_query, *params)

                    # Get paginated entries
                    data_query = (
                        f"SELECT id, timestamp, event, actor, target, "
                        f"host(ip) as ip, user_agent, details, level "
                        f"FROM audit_log {where} "
                        f"ORDER BY timestamp DESC LIMIT ${idx} OFFSET ${idx + 1}"
                    )
                    rows = await conn.fetch(data_query, *params, limit, offset)

                entries = []
                for row in rows:
                    import json as _json
                    details = row['details']
                    if isinstance(details, str):
                        try:
                            details = _json.loads(details)
                        except Exception:
                            details = None
                    entries.append(AuditLogEntry(
                        id=row['id'],
                        timestamp=row['timestamp'].isoformat() if row['timestamp'] else '',
                        event=row['event'] or '',
                        actor=row['actor'] or '',
                        target=row['target'],
                        ip=row['ip'],
                        user_agent=row['user_agent'],
                        details=details,
                        level=row['level'] or 'INFO',
                    ))

                return AuditLogResponse(
                    entries=entries,
                    total_count=total_count or 0,
                    limit=limit,
                    offset=offset,
                )
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Audit log query failed: {e}")
                raise HTTPException(status_code=500, detail=f"Audit log query failed: {str(e)}")


def create_admin_router(space_manager, auth_dependency) -> APIRouter:
    """Factory function to create the admin router."""
    endpoint = AdminEndpoint(space_manager, auth_dependency)
    return endpoint.router
