"""
Same-As operations mixin for the Entity Registry.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAX_RESOLVE_DEPTH = 10


class SameAsMixin:
    """Same-as mapping and entity resolution methods."""

    async def create_same_as(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: str = 'same_as',
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a same-as mapping between two entities.

        Validates that both entities exist and checks for cycles.

        Raises:
            ValueError: If entities don't exist, are the same, or would create a cycle.
        """
        if source_entity_id == target_entity_id:
            raise ValueError("Cannot create same-as mapping to self")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Verify both entities exist
                for eid in (source_entity_id, target_entity_id):
                    exists = await conn.fetchval(
                        "SELECT 1 FROM entity WHERE entity_id = $1", eid
                    )
                    if not exists:
                        raise ValueError(f"Entity not found: {eid}")

                # Check for cycles: would target eventually resolve back to source?
                if await self._would_create_cycle(conn, source_entity_id, target_entity_id):
                    raise ValueError(
                        f"Creating same-as {source_entity_id} -> {target_entity_id} would create a cycle"
                    )

                row = await conn.fetchrow(
                    "INSERT INTO entity_same_as (source_entity_id, target_entity_id, "
                    "relationship_type, confidence, reason, created_by, notes) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
                    source_entity_id, target_entity_id, relationship_type,
                    confidence, reason, created_by, notes
                )

                await self._log_change(conn, source_entity_id, 'same_as_created', {
                    'target_entity_id': target_entity_id,
                    'relationship_type': relationship_type,
                }, changed_by=created_by)

                return dict(row)

    async def _would_create_cycle(self, conn, source_id: str, target_id: str) -> bool:
        """Check if adding source -> target would create a cycle."""
        visited = {source_id}
        current = target_id
        for _ in range(MAX_RESOLVE_DEPTH):
            if current in visited:
                return True
            visited.add(current)
            next_id = await conn.fetchval(
                "SELECT target_entity_id FROM entity_same_as "
                "WHERE source_entity_id = $1 AND status = 'active' LIMIT 1",
                current
            )
            if next_id is None:
                return False
            current = next_id
        # Exceeded depth — treat as potential cycle
        return True

    async def retract_same_as(
        self, same_as_id: int,
        retracted_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Retract a same-as mapping."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "UPDATE entity_same_as SET status = 'retracted', "
                    "retracted_time = $1, retracted_by = $2 "
                    "WHERE same_as_id = $3 AND status = 'active' "
                    "RETURNING source_entity_id, target_entity_id",
                    datetime.now(timezone.utc), retracted_by, same_as_id
                )
                if row is None:
                    return False

                await self._log_change(conn, row['source_entity_id'], 'same_as_retracted', {
                    'same_as_id': same_as_id,
                    'target_entity_id': row['target_entity_id'],
                }, changed_by=retracted_by, comment=reason)
                return True

    async def get_same_as(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get all active same-as mappings for an entity (as source or target)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM entity_same_as "
                "WHERE (source_entity_id = $1 OR target_entity_id = $1) AND status = 'active' "
                "ORDER BY created_time",
                entity_id
            )
            return [dict(r) for r in rows]

    async def resolve_entity(self, entity_id: str) -> Dict[str, Any]:
        """
        Follow transitive same-as chain to the canonical entity.

        A -> B -> C returns C.
        If no same-as mapping exists, returns the entity itself.

        Raises:
            ValueError: If entity not found.
        """
        async with self.pool.acquire() as conn:
            current_id = entity_id
            visited = set()

            for _ in range(MAX_RESOLVE_DEPTH):
                if current_id in visited:
                    break  # cycle detected, stop
                visited.add(current_id)

                next_id = await conn.fetchval(
                    "SELECT target_entity_id FROM entity_same_as "
                    "WHERE source_entity_id = $1 AND status = 'active' LIMIT 1",
                    current_id
                )
                if next_id is None:
                    break
                current_id = next_id

        entity = await self.get_entity(current_id)
        if entity is None:
            raise ValueError(f"Entity not found: {entity_id}")
        return entity
