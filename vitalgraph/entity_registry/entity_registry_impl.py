"""
Core Entity Registry implementation.

Async operations using asyncpg, sharing the connection pool
from the Fuseki-PostgreSQL hybrid backend.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from .entity_registry_id import generate_entity_id, entity_id_to_uri, uri_to_entity_id
from .entity_registry_schema import EntityRegistrySchema


logger = logging.getLogger(__name__)

MAX_RESOLVE_DEPTH = 10


class EntityRegistryImpl:
    """
    Core entity registry operations.

    All methods are async and use the shared asyncpg connection pool.
    """

    def __init__(self, connection_pool: asyncpg.Pool):
        """
        Initialize with an asyncpg connection pool.

        Args:
            connection_pool: Shared asyncpg pool from FusekiPostgreSQLDbImpl.
        """
        self.pool = connection_pool
        self.schema = EntityRegistrySchema()

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    async def ensure_tables(self) -> bool:
        """Create registry tables, indexes, and seed data if they don't exist."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    for sql in self.schema.create_tables_sql():
                        await conn.execute(sql)
                    for sql in self.schema.create_indexes_sql():
                        await conn.execute(sql)
                    await conn.execute(self.schema.seed_entity_types_sql())
            logger.info("Entity registry tables ensured")
            return True
        except Exception as e:
            logger.error(f"Failed to ensure entity registry tables: {e}")
            return False

    # ------------------------------------------------------------------
    # Entity Type operations
    # ------------------------------------------------------------------

    async def list_entity_types(self) -> List[Dict[str, Any]]:
        """List all entity types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT type_id, type_key, type_label, type_description, created_time, updated_time "
                "FROM entity_type ORDER BY type_id"
            )
            return [dict(r) for r in rows]

    async def create_entity_type(self, type_key: str, type_label: str,
                                 type_description: Optional[str] = None) -> Dict[str, Any]:
        """Create a new entity type."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO entity_type (type_key, type_label, type_description) "
                "VALUES ($1, $2, $3) RETURNING *",
                type_key, type_label, type_description
            )
            await self._log_change(conn, None, 'entity_type_created', {
                'type_key': type_key, 'type_label': type_label
            })
            return dict(row)

    async def _get_entity_type_id(self, conn, type_key: str) -> Optional[int]:
        """Resolve type_key to type_id."""
        return await conn.fetchval(
            "SELECT type_id FROM entity_type WHERE type_key = $1", type_key
        )

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    async def create_entity(
        self,
        type_key: str,
        primary_name: str,
        description: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        website: Optional[str] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
        aliases: Optional[List[Dict[str, Any]]] = None,
        identifiers: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new entity with a generated unique ID.

        Optionally creates initial aliases and identifiers in the same transaction.

        Returns:
            Entity dict including entity_id and entity_uri.

        Raises:
            ValueError: If type_key is invalid.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                type_id = await self._get_entity_type_id(conn, type_key)
                if type_id is None:
                    raise ValueError(f"Unknown entity type: {type_key}")

                # Generate unique ID with retry on collision
                entity_id = None
                for _ in range(5):
                    candidate = generate_entity_id()
                    exists = await conn.fetchval(
                        "SELECT 1 FROM entity WHERE entity_id = $1", candidate
                    )
                    if not exists:
                        entity_id = candidate
                        break
                if entity_id is None:
                    raise RuntimeError("Failed to generate unique entity ID after 5 attempts")

                row = await conn.fetchrow(
                    "INSERT INTO entity (entity_id, entity_type_id, primary_name, description, "
                    "country, region, locality, website, created_by, notes) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *",
                    entity_id, type_id, primary_name, description,
                    country, region, locality, website, created_by, notes
                )
                entity = dict(row)
                entity['entity_uri'] = entity_id_to_uri(entity_id)

                await self._log_change(conn, entity_id, 'entity_created', {
                    'type_key': type_key, 'primary_name': primary_name
                }, changed_by=created_by)

                # Create initial aliases
                if aliases:
                    for alias_data in aliases:
                        await self._insert_alias(conn, entity_id, **alias_data)

                # Create initial identifiers
                if identifiers:
                    for ident_data in identifiers:
                        await self._insert_identifier(conn, entity_id, **ident_data)

                return entity

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Get entity by ID, including type info, identifiers, and aliases.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT e.*, et.type_key, et.type_label "
                "FROM entity e JOIN entity_type et ON e.entity_type_id = et.type_id "
                "WHERE e.entity_id = $1",
                entity_id
            )
            if row is None:
                return None

            entity = dict(row)
            entity['entity_uri'] = entity_id_to_uri(entity_id)

            # Fetch identifiers
            ident_rows = await conn.fetch(
                "SELECT * FROM entity_identifier WHERE entity_id = $1 AND status != 'retracted' "
                "ORDER BY identifier_namespace, identifier_id",
                entity_id
            )
            entity['identifiers'] = [dict(r) for r in ident_rows]

            # Fetch aliases
            alias_rows = await conn.fetch(
                "SELECT * FROM entity_alias WHERE entity_id = $1 AND status != 'retracted' "
                "ORDER BY alias_type, alias_id",
                entity_id
            )
            entity['aliases'] = [dict(r) for r in alias_rows]

            return entity

    async def get_entity_by_uri(self, uri: str) -> Optional[Dict[str, Any]]:
        """Get entity by URN (urn:entity:<id>)."""
        entity_id = uri_to_entity_id(uri)
        return await self.get_entity(entity_id)

    async def update_entity(
        self,
        entity_id: str,
        primary_name: Optional[str] = None,
        description: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        website: Optional[str] = None,
        status: Optional[str] = None,
        updated_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update entity fields. Only provided (non-None) fields are updated.

        Returns:
            Updated entity dict, or None if entity not found.
        """
        # Build dynamic SET clause
        fields = {}
        if primary_name is not None:
            fields['primary_name'] = primary_name
        if description is not None:
            fields['description'] = description
        if country is not None:
            fields['country'] = country
        if region is not None:
            fields['region'] = region
        if locality is not None:
            fields['locality'] = locality
        if website is not None:
            fields['website'] = website
        if status is not None:
            valid_statuses = ('active', 'inactive', 'merged', 'deleted')
            if status not in valid_statuses:
                raise ValueError(f"Invalid entity status: {status}. Must be one of {valid_statuses}")
            fields['status'] = status
        if notes is not None:
            fields['notes'] = notes

        if not fields:
            return await self.get_entity(entity_id)

        fields['updated_time'] = datetime.now(timezone.utc)

        set_parts = []
        values = []
        for i, (col, val) in enumerate(fields.items(), 1):
            set_parts.append(f"{col} = ${i}")
            values.append(val)

        values.append(entity_id)
        param_idx = len(values)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    f"UPDATE entity SET {', '.join(set_parts)} WHERE entity_id = ${param_idx}",
                    *values
                )

                if result == 'UPDATE 0':
                    return None

                await self._log_change(conn, entity_id, 'entity_updated', {
                    'fields': list(fields.keys())
                }, changed_by=updated_by)

        return await self.get_entity(entity_id)

    async def delete_entity(self, entity_id: str, deleted_by: Optional[str] = None,
                            comment: Optional[str] = None) -> bool:
        """
        Soft-delete an entity (set status='deleted').

        Returns:
            True if entity was found and deleted, False otherwise.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    "UPDATE entity SET status = 'deleted', updated_time = $1 WHERE entity_id = $2 AND status != 'deleted'",
                    datetime.now(timezone.utc), entity_id
                )
                if result == 'UPDATE 0':
                    return False

                await self._log_change(conn, entity_id, 'entity_deleted', None,
                                       changed_by=deleted_by, comment=comment)
                return True

    async def search_entities(
        self,
        query: Optional[str] = None,
        type_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        status: Optional[str] = 'active',
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Search/list entities with filters and pagination.

        Name search uses ILIKE on primary_name and alias_name.

        Returns:
            Tuple of (entities list, total count).
        """
        conditions = []
        params = []
        param_idx = 0

        if status:
            param_idx += 1
            conditions.append(f"e.status = ${param_idx}")
            params.append(status)

        if type_key:
            param_idx += 1
            conditions.append(f"et.type_key = ${param_idx}")
            params.append(type_key)

        if country:
            param_idx += 1
            conditions.append(f"e.country ILIKE ${param_idx}")
            params.append(f"%{country}%")

        if region:
            param_idx += 1
            conditions.append(f"e.region ILIKE ${param_idx}")
            params.append(f"%{region}%")

        if query:
            param_idx += 1
            query_param = f"%{query}%"
            conditions.append(
                f"(e.primary_name ILIKE ${param_idx} OR "
                f"EXISTS (SELECT 1 FROM entity_alias ea WHERE ea.entity_id = e.entity_id "
                f"AND ea.status != 'retracted' AND ea.alias_name ILIKE ${param_idx}))"
            )
            params.append(query_param)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        async with self.pool.acquire() as conn:
            # Count
            count_sql = (
                f"SELECT COUNT(DISTINCT e.entity_id) FROM entity e "
                f"JOIN entity_type et ON e.entity_type_id = et.type_id {where}"
            )
            total = await conn.fetchval(count_sql, *params)

            # Fetch page
            offset = (page - 1) * page_size
            param_idx += 1
            params.append(page_size)
            limit_param = param_idx
            param_idx += 1
            params.append(offset)
            offset_param = param_idx

            data_sql = (
                f"SELECT DISTINCT e.*, et.type_key, et.type_label FROM entity e "
                f"JOIN entity_type et ON e.entity_type_id = et.type_id {where} "
                f"ORDER BY e.primary_name "
                f"LIMIT ${limit_param} OFFSET ${offset_param}"
            )
            rows = await conn.fetch(data_sql, *params)

            entities = []
            for row in rows:
                entity = dict(row)
                entity['entity_uri'] = entity_id_to_uri(entity['entity_id'])
                entities.append(entity)

            return entities, total

    async def list_entities(
        self,
        type_key: Optional[str] = None,
        status: Optional[str] = 'active',
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Convenience wrapper around search_entities with no text query."""
        return await self.search_entities(
            type_key=type_key, status=status, page=page, page_size=page_size
        )

    # ------------------------------------------------------------------
    # Identifier operations
    # ------------------------------------------------------------------

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
                    "WHERE identifier_id = $1 AND status != 'retracted' RETURNING entity_id, identifier_namespace, identifier_value",
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

    # ------------------------------------------------------------------
    # Alias operations
    # ------------------------------------------------------------------

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

                return await self._insert_alias(
                    conn, entity_id, alias_name, alias_type,
                    is_primary, created_by, notes
                )

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

    # ------------------------------------------------------------------
    # Same-As operations
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Change Log
    # ------------------------------------------------------------------

    async def _log_change(
        self, conn, entity_id: Optional[str], change_type: str,
        change_detail: Optional[Dict] = None,
        changed_by: Optional[str] = None,
        comment: Optional[str] = None,
    ):
        """Insert a change log entry within an existing connection/transaction."""
        detail_json = json.dumps(change_detail) if change_detail else None
        await conn.execute(
            "INSERT INTO entity_change_log (entity_id, change_type, change_detail, changed_by, comment) "
            "VALUES ($1, $2, $3::jsonb, $4, $5)",
            entity_id, change_type, detail_json, changed_by, comment
        )

    async def get_change_log(
        self, entity_id: str,
        change_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get change log for a specific entity."""
        conditions = ["entity_id = $1"]
        params: list = [entity_id]
        param_idx = 1

        if change_type:
            param_idx += 1
            conditions.append(f"change_type = ${param_idx}")
            params.append(change_type)

        where = "WHERE " + " AND ".join(conditions)

        async with self.pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM entity_change_log {where}", *params
            )

            param_idx += 1
            params.append(limit)
            limit_p = param_idx
            param_idx += 1
            params.append(offset)
            offset_p = param_idx

            rows = await conn.fetch(
                f"SELECT * FROM entity_change_log {where} "
                f"ORDER BY created_time DESC LIMIT ${limit_p} OFFSET ${offset_p}",
                *params
            )
            return [self._parse_row(dict(r)) for r in rows], total

    async def get_recent_changes(
        self,
        limit: int = 50,
        change_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent changes across all entities."""
        if change_type:
            rows_raw = await self._fetch(
                "SELECT * FROM entity_change_log WHERE change_type = $1 "
                "ORDER BY created_time DESC LIMIT $2",
                change_type, limit
            )
        else:
            rows_raw = await self._fetch(
                "SELECT * FROM entity_change_log ORDER BY created_time DESC LIMIT $1",
                limit
            )
        return [self._parse_row(r) for r in rows_raw]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_row(row_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure JSONB fields are dicts, not strings."""
        cd = row_dict.get('change_detail')
        if isinstance(cd, str):
            row_dict['change_detail'] = json.loads(cd)
        return row_dict

    async def _fetch(self, sql: str, *args) -> List[Dict[str, Any]]:
        """Simple fetch helper."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]
