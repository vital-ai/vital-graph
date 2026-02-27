"""
Identifier operations mixin for the Entity Registry.
"""

from typing import Any, Dict, List, Optional


class IdentifierMixin:
    """Identifier CRUD methods."""

    async def _insert_identifier(
        self, conn, entity_id: str,
        identifier_namespace: str, identifier_value: str,
        is_primary: bool = False, created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an identifier within an existing connection/transaction."""
        row = await conn.fetchrow(
            "INSERT INTO entity_identifier (entity_id, identifier_namespace, identifier_value, "
            "is_primary, created_by, notes) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING *",
            entity_id, identifier_namespace, identifier_value, is_primary, created_by, notes
        )
        await self._log_change(conn, entity_id, 'identifier_added', {
            'namespace': identifier_namespace, 'value': identifier_value
        }, changed_by=created_by)
        return dict(row)

    async def add_identifier(
        self, entity_id: str,
        identifier_namespace: str, identifier_value: str,
        is_primary: bool = False, created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add an external identifier to an entity."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Verify entity exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM entity WHERE entity_id = $1", entity_id
                )
                if not exists:
                    raise ValueError(f"Entity not found: {entity_id}")

                return await self._insert_identifier(
                    conn, entity_id, identifier_namespace, identifier_value,
                    is_primary, created_by, notes
                )

    async def remove_identifier(self, identifier_id: int,
                                retracted_by: Optional[str] = None) -> bool:
        """Retract an identifier (soft-remove)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "UPDATE entity_identifier SET status = 'retracted' "
                    "WHERE identifier_id = $1 AND status != 'retracted' "
                    "RETURNING entity_id, identifier_namespace, identifier_value",
                    identifier_id
                )
                if row is None:
                    return False

                await self._log_change(conn, row['entity_id'], 'identifier_retracted', {
                    'identifier_id': identifier_id,
                    'namespace': row['identifier_namespace'],
                    'value': row['identifier_value'],
                }, changed_by=retracted_by)
                return True

    async def list_identifiers(self, entity_id: str) -> List[Dict[str, Any]]:
        """List all active identifiers for an entity."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM entity_identifier WHERE entity_id = $1 AND status != 'retracted' "
                "ORDER BY identifier_namespace, identifier_id",
                entity_id
            )
            return [dict(r) for r in rows]

    async def lookup_by_identifier(
        self, namespace: str, value: str
    ) -> List[Dict[str, Any]]:
        """Find entities by external identifier (namespace + value).

        Returns a list since identifiers are not necessarily unique across entities.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ei.entity_id FROM entity_identifier ei "
                "JOIN entity e ON ei.entity_id = e.entity_id "
                "WHERE ei.identifier_namespace = $1 AND ei.identifier_value = $2 "
                "AND ei.status = 'active' AND e.status != 'deleted'",
                namespace, value
            )
            entities = []
            for row in rows:
                entity = await self.get_entity(row['entity_id'])
                if entity:
                    entities.append(entity)
            return entities

    async def lookup_by_identifier_value(self, value: str) -> List[Dict[str, Any]]:
        """Find entities by identifier value across all namespaces."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ei.entity_id FROM entity_identifier ei "
                "JOIN entity e ON ei.entity_id = e.entity_id "
                "WHERE ei.identifier_value = $1 "
                "AND ei.status = 'active' AND e.status != 'deleted'",
                value
            )
            entities = []
            for row in rows:
                entity = await self.get_entity(row['entity_id'])
                if entity:
                    entities.append(entity)
            return entities
