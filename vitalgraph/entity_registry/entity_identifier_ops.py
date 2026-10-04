"""
Identifier operations mixin for the Entity Registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from .entity_status import ACTIVE, DELETED, RETRACTED

if TYPE_CHECKING:
    import asyncpg


DECLARED_INDEX_PREFIX = "uq_ident_"


class IdentifierClaimed(ValueError):
    """A DECLARED-unique identifier is already held by another entity (`issues/227`).

    A domain outcome, not a fault: answered in a 200 body naming the entity that
    holds the value, so the caller can use that entity instead of minting a
    duplicate. Raised by every write path, because the declaration is a unique
    index and the database enforces it whoever writes.
    """

    def __init__(self, namespace: str, value: str, holder: Optional[str]):
        self.namespace = namespace
        self.value = value
        self.holder = holder
        super().__init__(
            f"{namespace} {value!r} is declared unique and is already held by entity "
            f"{holder}; nothing was written")


class IdentifierNotDeclared(ValueError):
    """`resolve_or_create_entity` on a pair that is not declared unique (`issues/227`).

    It refuses rather than guess: for an undeclared pair `lookup_by_identifier`
    legitimately returns a LIST, and picking one is the defect this exists to stop.
    """


def is_declared_violation(exc: BaseException) -> bool:
    """Is this a unique violation of a DECLARATION index (not some other constraint)?"""
    import asyncpg as _asyncpg
    return (isinstance(exc, _asyncpg.UniqueViolationError)
            and str(getattr(exc, 'constraint_name', '') or '').startswith(DECLARED_INDEX_PREFIX))


async def holder_of(conn, namespace: str, value: str, entity_type_id: Optional[int]) -> Optional[str]:
    """The entity holding an ACTIVE declared identifier."""
    return await conn.fetchval(
        "SELECT entity_id FROM entity_identifier WHERE identifier_namespace = $1 "
        "AND identifier_value = $2 AND entity_type_id IS NOT DISTINCT FROM $3 "
        f"AND status = '{ACTIVE}' LIMIT 1",
        namespace, value, entity_type_id)


class IdentifierMixin:
    """Identifier CRUD methods."""

    pool: asyncpg.Pool

    async def _log_change(self, conn: asyncpg.Connection, entity_id: str,
                          change_type: str, details: Dict[str, Any],
                          changed_by: Optional[str] = None) -> None: ...

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]: ...

    async def _insert_identifier(
        self, conn, entity_id: str,
        identifier_namespace: str, identifier_value: str,
        is_primary: bool = False, created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an identifier within an existing connection/transaction."""
        # Auto-register the namespace in identifier_type on first use, preserving
        # the old free-text "new type appears by being used" behavior now that a
        # managed table exists. Idempotent; label defaults to the key.
        await conn.execute(
            "INSERT INTO identifier_type (type_key, type_label) VALUES ($1, $1) "
            "ON CONFLICT (type_key) DO NOTHING",
            identifier_namespace
        )
        # The entity's TYPE goes on the row (`issues/227`), so a declaration —
        # a partial unique index on (namespace, value, entity_type_id) — covers
        # it. A declared value held by another entity fails HERE, for every
        # write path; the callers turn that into `IdentifierClaimed`.
        row = await conn.fetchrow(
            "INSERT INTO entity_identifier (entity_id, identifier_namespace, identifier_value, "
            "is_primary, created_by, notes, entity_type_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, "
            "(SELECT entity_type_id FROM entity WHERE entity_id = $1::varchar)) RETURNING *",
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
        """Add an external identifier to an entity.

        Raises `IdentifierClaimed` if the pair is DECLARED unique and another
        entity already holds the value (`issues/227`).
        """
        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    # Verify entity exists
                    type_id = await conn.fetchval(
                        "SELECT entity_type_id FROM entity WHERE entity_id = $1", entity_id
                    )
                    if type_id is None:
                        raise ValueError(f"Entity not found: {entity_id}")

                    return await self._insert_identifier(
                        conn, entity_id, identifier_namespace, identifier_value,
                        is_primary, created_by, notes
                    )
            except Exception as e:
                if not is_declared_violation(e):
                    raise
                # The transaction is rolled back; read who holds it.
                raise IdentifierClaimed(
                    identifier_namespace, identifier_value,
                    await holder_of(conn, identifier_namespace, identifier_value, type_id)
                ) from None

    async def retract_identifier(self, identifier_id: int,
                                retracted_by: Optional[str] = None) -> bool:
        """Retract an identifier (soft-remove)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"UPDATE entity_identifier SET status = '{RETRACTED}' "
                    f"WHERE identifier_id = $1 AND status != '{RETRACTED}' "
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
                f"SELECT * FROM entity_identifier WHERE entity_id = $1 AND status != '{RETRACTED}' "
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
                f"AND ei.status = '{ACTIVE}' AND e.status != '{DELETED}'",
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
                f"AND ei.status = '{ACTIVE}' AND e.status != '{DELETED}'",
                value
            )
            entities = []
            for row in rows:
                entity = await self.get_entity(row['entity_id'])
                if entity:
                    entities.append(entity)
            return entities
