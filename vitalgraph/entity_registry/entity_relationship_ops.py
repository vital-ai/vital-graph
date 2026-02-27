"""
Relationship operations mixin for the Entity Registry.

Includes relationship types and relationship CRUD.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class RelationshipMixin:
    """Relationship type and relationship CRUD methods."""

    # ------------------------------------------------------------------
    # Relationship Type operations
    # ------------------------------------------------------------------

    async def list_relationship_types(self) -> List[Dict[str, Any]]:
        """List all relationship types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT relationship_type_id, type_key, type_label, type_description, "
                "inverse_key, created_time, updated_time "
                "FROM relationship_type ORDER BY relationship_type_id"
            )
            return [dict(r) for r in rows]

    async def create_relationship_type(
        self, type_key: str, type_label: str,
        type_description: Optional[str] = None,
        inverse_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new relationship type."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO relationship_type (type_key, type_label, type_description, inverse_key) "
                "VALUES ($1, $2, $3, $4) RETURNING *",
                type_key, type_label, type_description, inverse_key
            )
            await self._log_change(conn, None, 'relationship_type_created', {
                'type_key': type_key, 'type_label': type_label
            })
            return dict(row)

    async def _get_relationship_type_id(self, conn, type_key: str) -> Optional[int]:
        """Resolve relationship type_key to relationship_type_id."""
        return await conn.fetchval(
            "SELECT relationship_type_id FROM relationship_type WHERE type_key = $1", type_key
        )

    # ------------------------------------------------------------------
    # Relationship CRUD
    # ------------------------------------------------------------------

    async def create_relationship(
        self,
        entity_source: str,
        entity_destination: str,
        relationship_type_key: str,
        start_datetime=None,
        end_datetime=None,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a relationship between two entities."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for eid in (entity_source, entity_destination):
                    exists = await conn.fetchval(
                        "SELECT 1 FROM entity WHERE entity_id = $1", eid
                    )
                    if not exists:
                        raise ValueError(f"Entity not found: {eid}")

                type_id = await self._get_relationship_type_id(conn, relationship_type_key)
                if type_id is None:
                    raise ValueError(f"Unknown relationship type: {relationship_type_key}")

                row = await conn.fetchrow(
                    "INSERT INTO entity_relationship "
                    "(entity_source, entity_destination, relationship_type_id, "
                    "start_datetime, end_datetime, description, created_by, notes) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *",
                    entity_source, entity_destination, type_id,
                    start_datetime, end_datetime, description, created_by, notes
                )
                rel = dict(row)

                await self._log_change(conn, entity_source, 'relationship_created', {
                    'relationship_id': rel['relationship_id'],
                    'type_key': relationship_type_key,
                    'dest_id': entity_destination,
                }, changed_by=created_by)

                return await self._get_relationship_response(conn, rel['relationship_id'])

    async def _get_relationship_response(self, conn, relationship_id: int) -> Optional[Dict[str, Any]]:
        """Build a full relationship response dict from the view."""
        row = await conn.fetchrow(
            "SELECT rv.*, rt.type_key AS relationship_type_key, "
            "rt.type_label AS relationship_type_label, rt.inverse_key "
            "FROM entity_relationship_view rv "
            "JOIN relationship_type rt ON rv.relationship_type_id = rt.relationship_type_id "
            "WHERE rv.relationship_id = $1",
            relationship_id
        )
        if row is None:
            return None
        return dict(row)

    async def get_relationship(self, relationship_id: int) -> Optional[Dict[str, Any]]:
        """Get a single relationship by ID with type info."""
        async with self.pool.acquire() as conn:
            return await self._get_relationship_response(conn, relationship_id)

    async def update_relationship(self, relationship_id: int,
                                  updated_by: Optional[str] = None,
                                  **kwargs) -> Optional[Dict[str, Any]]:
        """Update relationship fields."""
        allowed = {'status', 'start_datetime', 'end_datetime', 'description', 'notes'}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}

        if 'status' in fields:
            valid = ('active', 'retracted')
            if fields['status'] not in valid:
                raise ValueError(f"Invalid relationship status: {fields['status']}. Must be one of {valid}")

        if not fields:
            return await self.get_relationship(relationship_id)

        fields['updated_time'] = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rel_row = await conn.fetchrow(
                    "SELECT entity_source FROM entity_relationship WHERE relationship_id = $1",
                    relationship_id
                )
                if rel_row is None:
                    return None

                set_parts = []
                values = []
                for i, (col, val) in enumerate(fields.items(), 1):
                    set_parts.append(f"{col} = ${i}")
                    values.append(val)

                values.append(relationship_id)
                param_idx = len(values)

                result = await conn.execute(
                    f"UPDATE entity_relationship SET {', '.join(set_parts)} "
                    f"WHERE relationship_id = ${param_idx}",
                    *values
                )
                if result == 'UPDATE 0':
                    return None

                await self._log_change(conn, rel_row['entity_source'], 'relationship_updated', {
                    'relationship_id': relationship_id,
                    'changed_fields': list(fields.keys()),
                }, changed_by=updated_by)

                return await self._get_relationship_response(conn, relationship_id)

    async def remove_relationship(self, relationship_id: int,
                                  removed_by: Optional[str] = None) -> bool:
        """Retract a relationship (set status='retracted')."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "UPDATE entity_relationship SET status = 'retracted', updated_time = $1 "
                    "WHERE relationship_id = $2 AND status = 'active' "
                    "RETURNING entity_source, entity_destination, relationship_type_id",
                    datetime.now(timezone.utc), relationship_id
                )
                if row is None:
                    return False

                type_key = await conn.fetchval(
                    "SELECT type_key FROM relationship_type WHERE relationship_type_id = $1",
                    row['relationship_type_id']
                )
                await self._log_change(conn, row['entity_source'], 'relationship_removed', {
                    'relationship_id': relationship_id,
                    'type_key': type_key,
                    'dest_id': row['entity_destination'],
                }, changed_by=removed_by)
                return True

    async def list_relationships(
        self, entity_id: str,
        direction: str = 'both',
        include_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """List relationships for an entity.

        Args:
            direction: 'outgoing', 'incoming', or 'both'.
            include_expired: If True, includes non-current relationships.
        """
        if direction == 'outgoing':
            where_dir = "rv.entity_source = $1"
        elif direction == 'incoming':
            where_dir = "rv.entity_destination = $1"
        else:
            where_dir = "(rv.entity_source = $1 OR rv.entity_destination = $1)"

        if include_expired:
            where_current = ""
        else:
            where_current = " AND rv.is_current = TRUE"

        sql = (
            "SELECT rv.*, rt.type_key AS relationship_type_key, "
            "rt.type_label AS relationship_type_label, rt.inverse_key "
            "FROM entity_relationship_view rv "
            "JOIN relationship_type rt ON rv.relationship_type_id = rt.relationship_type_id "
            f"WHERE {where_dir}{where_current} "
            "ORDER BY rv.relationship_id"
        )

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, entity_id)
            return [dict(r) for r in rows]
