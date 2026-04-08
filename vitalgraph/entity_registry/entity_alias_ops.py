"""
Alias operations mixin for the Entity Registry.
"""

from typing import Any, Dict, List, Optional

from .entity_dedup import compute_dedup_hash


class AliasMixin:
    """Alias CRUD methods."""

    async def _insert_alias(
        self, conn, entity_id: str,
        alias_name: str, alias_type: str = 'aka',
        is_primary: bool = False, created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an alias within an existing connection/transaction."""
        row = await conn.fetchrow(
            "INSERT INTO entity_alias (entity_id, alias_name, alias_type, is_primary, created_by, notes) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING *",
            entity_id, alias_name, alias_type, is_primary, created_by, notes
        )
        await self._log_change(conn, entity_id, 'alias_added', {
            'alias_name': alias_name, 'alias_type': alias_type
        }, changed_by=created_by)
        return dict(row)

    async def add_alias(
        self, entity_id: str,
        alias_name: str, alias_type: str = 'aka',
        is_primary: bool = False, created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add an alias to an entity."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM entity WHERE entity_id = $1", entity_id
                )
                if not exists:
                    raise ValueError(f"Entity not found: {entity_id}")

                alias = await self._insert_alias(
                    conn, entity_id, alias_name, alias_type,
                    is_primary, created_by, notes
                )

                # Recompute dedup hash (aliases changed) and refresh index
                entity = await self.get_entity(entity_id)
                if entity:
                    new_hash = compute_dedup_hash(entity)
                    await conn.execute(
                        "UPDATE entity SET dedup_hash = $1 WHERE entity_id = $2",
                        new_hash, entity_id
                    )
                    if self.dedup_index:
                        self.dedup_index.add_entity(entity_id, entity)
                        await self._notify_dedup_change('add', entity_id)

                # Sync to Weaviate (aliases changed)
                await self._weaviate_upsert_entity(entity_id)

                return alias

    async def remove_alias(self, alias_id: int,
                           retracted_by: Optional[str] = None) -> bool:
        """Retract an alias (soft-remove)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "UPDATE entity_alias SET status = 'retracted' "
                    "WHERE alias_id = $1 AND status != 'retracted' RETURNING entity_id, alias_name",
                    alias_id
                )
                if row is None:
                    return False

                await self._log_change(conn, row['entity_id'], 'alias_retracted', {
                    'alias_id': alias_id, 'alias_name': row['alias_name']
                }, changed_by=retracted_by)

                # Recompute dedup hash (alias retracted) and refresh index
                entity = await self.get_entity(row['entity_id'])
                if entity:
                    new_hash = compute_dedup_hash(entity)
                    await conn.execute(
                        "UPDATE entity SET dedup_hash = $1 WHERE entity_id = $2",
                        new_hash, row['entity_id']
                    )
                    if self.dedup_index:
                        self.dedup_index.add_entity(row['entity_id'], entity)
                        await self._notify_dedup_change('add', row['entity_id'])

                # Sync to Weaviate (aliases changed)
                await self._weaviate_upsert_entity(row['entity_id'])

                return True

    async def list_aliases(self, entity_id: str) -> List[Dict[str, Any]]:
        """List all active aliases for an entity."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM entity_alias WHERE entity_id = $1 AND status != 'retracted' "
                "ORDER BY alias_type, alias_id",
                entity_id
            )
            return [dict(r) for r in rows]

    async def search_by_alias(self, query: str) -> List[Dict[str, Any]]:
        """Search entities via alias names (ILIKE)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ea.entity_id FROM entity_alias ea "
                "JOIN entity e ON ea.entity_id = e.entity_id "
                "WHERE ea.alias_name ILIKE $1 AND ea.status != 'retracted' AND e.status != 'deleted'",
                f"%{query}%"
            )
            entities = []
            for row in rows:
                entity = await self.get_entity(row['entity_id'])
                if entity:
                    entities.append(entity)
            return entities
