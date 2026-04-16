"""
Core Entity Registry implementation.

Async operations using asyncpg, sharing the connection pool
from the Fuseki-PostgreSQL hybrid backend.

This class composes domain-specific mixins:
  - ChangeLogMixin:    change log + helpers
  - IdentifierMixin:   external identifier CRUD
  - AliasMixin:        alias CRUD
  - CategoryMixin:     entity category operations
  - LocationMixin:     location types, location CRUD, location categories
  - RelationshipMixin: relationship types, relationship CRUD
  - SameAsMixin:       same-as mappings + entity resolution
  - DedupMixin:        near-duplicate detection + cross-worker sync
  - WeaviateMixin:     Weaviate upsert/delete helpers
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from vitalgraph.utils.db_retry import with_db_retry

from .entity_alias_ops import AliasMixin
from .entity_category_ops import CategoryMixin
from .entity_changelog_ops import ChangeLogMixin
from .entity_dedup import EntityDedupIndex, compute_dedup_hash
from .entity_dedup_ops import DedupMixin
from .entity_identifier_ops import IdentifierMixin
from .entity_location_ops import LocationMixin
from .entity_registry_id import generate_entity_id, entity_id_to_uri, uri_to_entity_id
from .entity_registry_schema import EntityRegistrySchema
from .entity_relationship_ops import RelationshipMixin
from .entity_same_as_ops import SameAsMixin
from .entity_weaviate import EntityWeaviateIndex
from .entity_weaviate_ops import WeaviateMixin


logger = logging.getLogger(__name__)


class EntityRegistryImpl(
    ChangeLogMixin,
    IdentifierMixin,
    AliasMixin,
    CategoryMixin,
    LocationMixin,
    RelationshipMixin,
    SameAsMixin,
    DedupMixin,
    WeaviateMixin,
):
    """
    Core entity registry operations.

    All methods are async and use the shared asyncpg connection pool.
    Domain-specific operations are provided by the mixin base classes.
    """

    def __init__(self, connection_pool: asyncpg.Pool, dedup_index: Optional[EntityDedupIndex] = None,
                 signal_manager=None, weaviate_index: Optional[EntityWeaviateIndex] = None):
        """
        Initialize with an asyncpg connection pool.

        Args:
            connection_pool: Shared asyncpg pool from FusekiPostgreSQLDbImpl.
            dedup_index: Optional EntityDedupIndex for near-duplicate detection.
            signal_manager: Optional SignalManager for cross-worker dedup sync.
            weaviate_index: Optional EntityWeaviateIndex for vector search.
        """
        self.pool = connection_pool
        self.schema = EntityRegistrySchema()
        self.dedup_index = dedup_index
        self.signal_manager = signal_manager
        self.weaviate_index = weaviate_index

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    @with_db_retry()
    async def ensure_tables(self) -> bool:
        """Verify that entity registry tables exist. Does NOT create or modify schema.

        Run entity_registry/migrate.py to create tables and apply migrations.
        """
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'entity')"
                )
                if not exists:
                    raise RuntimeError(
                        "Entity registry tables not found. "
                        "Run 'python entity_registry/migrate.py' to create them."
                    )
            logger.info("Entity registry tables verified")

            # Initialize dedup index if configured
            if self.dedup_index:
                if self.dedup_index.storage_config:
                    # Persistent backend (Redis/MemoryDB): skip bulk init at
                    # startup — the index is populated by the standalone
                    # sync_dedup_index.py script. Just mark as initialized
                    # so incremental updates via add_entity/remove_entity work.
                    self.dedup_index._initialized = True
                    logger.info("Entity dedup index: using existing MemoryDB data "
                                "(run sync_dedup_index.py for full sync)")
                else:
                    # In-memory backend: must load from DB on every startup
                    try:
                        count = await self.dedup_index.initialize(self.pool)
                        logger.info(f"Entity dedup index loaded {count} entities")
                    except Exception as e:
                        logger.error(f"Failed to initialize entity dedup index: {e}")

            # Ensure Weaviate collection if configured
            if self.weaviate_index:
                try:
                    await self.weaviate_index.ensure_collection()
                except Exception as e:
                    logger.error(f"Failed to ensure Weaviate collection: {e}")

            return True
        except Exception as e:
            logger.error(f"Failed to ensure entity registry tables: {e}")
            return False

    # ------------------------------------------------------------------
    # Entity Type operations
    # ------------------------------------------------------------------

    @with_db_retry()
    async def list_entity_types(self) -> List[Dict[str, Any]]:
        """List all entity types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT type_id, type_key, type_label, type_description, created_time, updated_time "
                "FROM entity_type ORDER BY type_id"
            )
            return [dict(r) for r in rows]

    @with_db_retry()
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

    @with_db_retry()
    async def create_entity(
        self,
        type_key: str,
        primary_name: str,
        description: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        website: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        aliases: Optional[List[Dict[str, Any]]] = None,
        identifiers: Optional[List[Dict[str, Any]]] = None,
        locations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new entity with a generated unique ID.

        Optionally creates initial aliases, identifiers, and locations
        in the same transaction.

        Returns:
            Entity dict including entity_id and entity_uri.

        Raises:
            ValueError: If type_key is invalid.
        """
        metadata_json = json.dumps(metadata) if metadata else '{}'

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

                # Compute dedup hash from the fields that will be indexed
                alias_list = [
                    {'alias_name': a.get('alias_name', a.get('name', ''))} for a in (aliases or [])
                ]
                dedup_hash = compute_dedup_hash({
                    'type_key': type_key, 'primary_name': primary_name,
                    'country': country, 'region': region, 'locality': locality,
                    'aliases': alias_list,
                })

                row = await conn.fetchrow(
                    "INSERT INTO entity (entity_id, entity_type_id, primary_name, description, "
                    "country, region, locality, website, latitude, longitude, "
                    "metadata, created_by, notes, dedup_hash) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14) "
                    "RETURNING *",
                    entity_id, type_id, primary_name, description,
                    country, region, locality, website, latitude, longitude,
                    metadata_json, created_by, notes, dedup_hash
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

                # Create initial locations
                if locations:
                    for loc_data in locations:
                        loc_type_key = loc_data.pop('location_type_key', None)
                        if loc_type_key:
                            await self._insert_location(
                                conn, entity_id, loc_type_key,
                                created_by=created_by, **loc_data,
                            )

                # Update dedup index and notify other workers
                if self.dedup_index:
                    entity_for_index = dict(entity)
                    entity_for_index['type_key'] = type_key
                    entity_for_index['aliases'] = alias_list
                    await self.dedup_index.async_add_entity(entity_id, entity_for_index)
                    await self._notify_dedup_change('add', entity_id)

                # Sync to Weaviate
                await self._weaviate_upsert_entity(entity_id)

                return entity

    @with_db_retry()
    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Get entity by ID, including type info, identifiers, aliases,
        locations, and relationships.
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

            # Ensure metadata is a dict
            md = entity.get('metadata')
            if isinstance(md, str):
                entity['metadata'] = json.loads(md)
            elif md is None:
                entity['metadata'] = {}

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

            # Fetch active locations (with is_active from view)
            loc_rows = await conn.fetch(
                "SELECT lv.*, lt.type_key AS location_type_key, "
                "lt.type_label AS location_type_label "
                "FROM entity_location_view lv "
                "JOIN entity_location_type lt ON lv.location_type_id = lt.location_type_id "
                "WHERE lv.entity_id = $1 AND lv.status = 'active' "
                "ORDER BY lv.is_primary DESC, lv.location_id",
                entity_id
            )
            locations = []
            for lr in loc_rows:
                loc = dict(lr)
                cat_rows = await conn.fetch(
                    "SELECT c.category_key, c.category_label "
                    "FROM entity_location_category_map lcm "
                    "JOIN category c ON lcm.category_id = c.category_id "
                    "WHERE lcm.location_id = $1 AND lcm.status = 'active' "
                    "ORDER BY c.category_key",
                    loc['location_id']
                )
                loc['categories'] = [dict(r) for r in cat_rows]
                locations.append(loc)
            entity['locations'] = locations

            # Fetch current relationships (from view)
            rel_rows = await conn.fetch(
                "SELECT rv.*, rt.type_key AS relationship_type_key, "
                "rt.type_label AS relationship_type_label, rt.inverse_key "
                "FROM entity_relationship_view rv "
                "JOIN relationship_type rt ON rv.relationship_type_id = rt.relationship_type_id "
                "WHERE (rv.entity_source = $1 OR rv.entity_destination = $1) "
                "AND rv.is_current = TRUE "
                "ORDER BY rv.relationship_id",
                entity_id
            )
            entity['relationships'] = [dict(r) for r in rel_rows]

            return entity

    @with_db_retry()
    async def get_entity_by_uri(self, uri: str) -> Optional[Dict[str, Any]]:
        """Get entity by URN (urn:entity:<id>)."""
        entity_id = uri_to_entity_id(uri)
        return await self.get_entity(entity_id)

    @with_db_retry()
    async def update_entity(
        self,
        entity_id: str,
        primary_name: Optional[str] = None,
        description: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        website: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        status: Optional[str] = None,
        updated_by: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        verified: Optional[bool] = None,
        verified_by: Optional[str] = None,
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
        if latitude is not None:
            fields['latitude'] = latitude
        if longitude is not None:
            fields['longitude'] = longitude
        if status is not None:
            valid_statuses = ('active', 'inactive', 'merged', 'deleted')
            if status not in valid_statuses:
                raise ValueError(f"Invalid entity status: {status}. Must be one of {valid_statuses}")
            fields['status'] = status
        if notes is not None:
            fields['notes'] = notes
        if metadata is not None:
            fields['metadata'] = json.dumps(metadata)
        if verified is not None:
            fields['verified'] = verified
            if verified:
                fields['verified_by'] = verified_by or updated_by
                fields['verified_time'] = datetime.now(timezone.utc)

        if not fields:
            return await self.get_entity(entity_id)

        fields['updated_time'] = datetime.now(timezone.utc)

        set_parts = []
        values = []
        for i, (col, val) in enumerate(fields.items(), 1):
            cast = '::jsonb' if col == 'metadata' else ''
            set_parts.append(f"{col} = ${i}{cast}")
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

        updated = await self.get_entity(entity_id)

        # Refresh dedup index and hash if name or location fields changed
        dedup_fields = {'primary_name', 'country', 'region', 'locality'}
        if updated and dedup_fields & set(fields.keys()):
            new_hash = compute_dedup_hash(updated)
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE entity SET dedup_hash = $1 WHERE entity_id = $2",
                    new_hash, entity_id
                )
            if self.dedup_index:
                await self.dedup_index.async_add_entity(entity_id, updated)
                await self._notify_dedup_change('add', entity_id)

        # Sync to Weaviate
        await self._weaviate_upsert_entity(entity_id)

        return updated

    @with_db_retry()
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

                # Remove from dedup index and notify other workers
                if self.dedup_index:
                    await self.dedup_index.async_remove_entity(entity_id)
                    await self._notify_dedup_change('remove', entity_id)

                # Remove from Weaviate
                await self._weaviate_delete_entity(entity_id)

                return True

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @with_db_retry()
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

    @with_db_retry()
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
