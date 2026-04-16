"""
Category operations mixin for the Entity Registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    import asyncpg


class CategoryMixin:
    """Category CRUD methods (entity categories)."""

    pool: asyncpg.Pool

    async def _log_change(self, conn: asyncpg.Connection, entity_id: Optional[str],
                          change_type: str, details: Dict[str, Any],
                          changed_by: Optional[str] = None) -> None: ...

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]: ...

    async def _weaviate_upsert_entity(self, entity_id: str) -> None: ...

    async def list_categories(self) -> List[Dict[str, Any]]:
        """List all entity categories."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT category_id, category_key, category_label, category_description, "
                "created_time, updated_time FROM category ORDER BY category_id"
            )
            return [dict(r) for r in rows]

    async def create_category(self, category_key: str, category_label: str,
                              category_description: Optional[str] = None) -> Dict[str, Any]:
        """Create a new entity category."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO category (category_key, category_label, category_description) "
                "VALUES ($1, $2, $3) RETURNING *",
                category_key, category_label, category_description
            )
            await self._log_change(conn, None, 'category_created', {
                'category_key': category_key, 'category_label': category_label
            })
            return dict(row)

    async def add_entity_category(
        self, entity_id: str, category_key: str,
        created_by: Optional[str] = None, notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assign a category to an entity."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM entity WHERE entity_id = $1", entity_id
                )
                if not exists:
                    raise ValueError(f"Entity not found: {entity_id}")

                cat_id = await conn.fetchval(
                    "SELECT category_id FROM category WHERE category_key = $1",
                    category_key
                )
                if cat_id is None:
                    raise ValueError(f"Category not found: {category_key}")

                row = await conn.fetchrow(
                    "INSERT INTO entity_category_map (entity_id, category_id, created_by, notes) "
                    "VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT (entity_id, category_id) DO UPDATE SET status = 'active' "
                    "RETURNING *",
                    entity_id, cat_id, created_by, notes
                )
                await self._log_change(conn, entity_id, 'category_added', {
                    'category_key': category_key
                }, changed_by=created_by)
                result = dict(row)
                result['category_key'] = category_key

                # Sync to Weaviate (categories changed)
                await self._weaviate_upsert_entity(entity_id)

                return result

    async def remove_entity_category(
        self, entity_id: str, category_key: str,
        removed_by: Optional[str] = None,
    ) -> bool:
        """Remove a category from an entity (soft-remove)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                cat_id = await conn.fetchval(
                    "SELECT category_id FROM category WHERE category_key = $1",
                    category_key
                )
                if cat_id is None:
                    raise ValueError(f"Category not found: {category_key}")

                result = await conn.execute(
                    "UPDATE entity_category_map SET status = 'removed' "
                    "WHERE entity_id = $1 AND category_id = $2 AND status = 'active'",
                    entity_id, cat_id
                )
                if result == 'UPDATE 0':
                    return False

                await self._log_change(conn, entity_id, 'category_removed', {
                    'category_key': category_key
                }, changed_by=removed_by)

                # Sync to Weaviate (categories changed)
                await self._weaviate_upsert_entity(entity_id)

                return True

    async def list_entity_categories(self, entity_id: str) -> List[Dict[str, Any]]:
        """List all active categories for an entity."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT ecm.entity_category_id, ecm.entity_id, ecm.status, ecm.created_time, "
                "ecm.created_by, ecm.notes, ec.category_key, ec.category_label, ec.category_description "
                "FROM entity_category_map ecm "
                "JOIN category ec ON ecm.category_id = ec.category_id "
                "WHERE ecm.entity_id = $1 AND ecm.status = 'active' "
                "ORDER BY ec.category_key",
                entity_id
            )
            return [dict(r) for r in rows]

    async def list_entities_by_category(self, category_key: str) -> List[Dict[str, Any]]:
        """List all active entities in a given category."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ecm.entity_id FROM entity_category_map ecm "
                "JOIN category ec ON ecm.category_id = ec.category_id "
                "JOIN entity e ON ecm.entity_id = e.entity_id "
                "WHERE ec.category_key = $1 AND ecm.status = 'active' AND e.status != 'deleted'",
                category_key
            )
            entities = []
            for row in rows:
                entity = await self.get_entity(row['entity_id'])
                if entity:
                    entities.append(entity)
            return entities
