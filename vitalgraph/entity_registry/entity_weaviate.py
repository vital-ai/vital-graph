"""
Weaviate integration for the Entity Registry.

Provides EntityWeaviateIndex for syncing entities to Weaviate and
performing semantic topic search via vector similarity.
"""

import asyncio
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Force native DNS resolver for async gRPC — the default c-ares resolver
# does not respect VPN/system DNS on some platforms.
os.environ.setdefault('GRPC_DNS_RESOLVER', 'native')

import requests
import weaviate
from weaviate.classes.data import DataObject
from weaviate.classes.init import Auth
import weaviate.classes.query as wvq

from .entity_weaviate_schema import (
    get_collection_name,
    get_location_collection_name,
    entity_id_to_weaviate_uuid,
    location_id_to_weaviate_uuid,
    entity_to_weaviate_properties,
    location_to_weaviate_properties,
    get_collection_config,
    get_location_collection_config,
)

logger = logging.getLogger(__name__)


class EntityWeaviateIndex:
    """Weaviate vector index for Entity Registry entities and locations.

    Supports:
    - Connecting to Weaviate with Keycloak JWT auth
    - Creating/validating EntityIndex and LocationIndex collections
    - Upserting and deleting entities and locations
    - Full sync from PostgreSQL (entities + locations with cross-refs)
    - Semantic topic search with property filters
    - Geo-radius queries on locations
    - Combined topic + geo queries via cross-reference traversal
    """

    def __init__(self, client, collection_name: str = None,
                 location_collection_name: str = None):
        self.client = client
        self.collection_name = collection_name or get_collection_name()
        self.location_collection_name = location_collection_name or get_location_collection_name()
        self._collection = None
        self._location_collection = None
        self._refresh_thread = None
        self._stop_refresh = threading.Event()
        # Connection params for reconnect (set by from_env)
        self._connect_params = None
        self._token_expires_in = 60
        # Lazy reconnect support for async token refresh
        self._needs_reconnect = False
        self._pending_client = None

    @staticmethod
    def _create_client(token_data: dict, http_host: str, grpc_host: str,
                       grpc_port: int):
        """Create an async Weaviate client (not yet connected)."""
        auth_creds = Auth.bearer_token(
            token_data['access_token'],
            expires_in=86400,  # Large fake value; we manage refresh ourselves
        )
        from weaviate.config import AdditionalConfig, ConnectionConfig
        return weaviate.use_async_with_custom(
            http_host=http_host,
            http_port=443,
            http_secure=True,
            grpc_host=grpc_host,
            grpc_port=grpc_port,
            grpc_secure=False,
            auth_credentials=auth_creds,
            skip_init_checks=True,
            additional_config=AdditionalConfig(
                connection=ConnectionConfig(
                    session_pool_connections=100,
                    session_pool_maxsize=200,
                ),
            ),
        )

    def _reconnect(self):
        """Get a fresh token and prepare a new async client for lazy reconnect."""
        if not self._connect_params:
            return
        try:
            token_data = EntityWeaviateIndex._get_jwt_token()
            if not token_data:
                logger.error("Token refresh failed: could not get new JWT")
                return
            self._pending_client = self._create_client(token_data, **self._connect_params)
            self._needs_reconnect = True
            logger.info("Weaviate token refreshed — reconnect pending")
        except Exception as e:
            logger.error(f"Weaviate reconnect failed: {e}")

    async def _ensure_connected(self):
        """If a token refresh created a pending client, swap and connect it.

        Retries up to 3 times with exponential backoff on transient errors
        (e.g. ConnectTimeout) so long-running jobs aren't killed by blips.
        """
        if self._needs_reconnect and self._pending_client:
            import asyncio
            import warnings
            old_client = self.client
            self.client = self._pending_client
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    await self.client.connect()
                    break
                except Exception as e:
                    if attempt == max_retries:
                        raise
                    wait = 5 * attempt
                    logger.warning(f"Weaviate reconnect attempt {attempt}/{max_retries} failed: {e} "
                                   f"— retrying in {wait}s")
                    await asyncio.sleep(wait)
            self._collection = None
            self._location_collection = None
            self._needs_reconnect = False
            self._pending_client = None
            logger.info("Weaviate async client reconnected")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", ResourceWarning)
                    await old_client.close()
            except Exception:
                pass

    def _start_token_refresh(self, expires_in: int):
        """Start a daemon thread that refreshes the token before expiry."""
        self._token_expires_in = expires_in
        refresh_interval = max(expires_in - 30, 30)  # refresh 30s before expiry

        def _refresh_loop():
            while not self._stop_refresh.wait(timeout=refresh_interval):
                self._reconnect()

        self._refresh_thread = threading.Thread(
            target=_refresh_loop, daemon=True, name="WeaviateTokenRefresh",
        )
        self._refresh_thread.start()
        logger.info(f"Weaviate token refresh thread started "
                    f"(interval={refresh_interval}s, token_expires_in={expires_in}s)")

    @staticmethod
    async def from_env() -> Optional['EntityWeaviateIndex']:
        """Create an EntityWeaviateIndex from environment variables.

        Returns None if ENTITY_WEAVIATE_ENABLED is not 'true'.

        Uses ``get_scoped_env`` so that env vars are scoped by
        ``VITALGRAPH_ENVIRONMENT`` (e.g. ``PROD_WEAVIATE_HTTP_HOST``
        when ``VITALGRAPH_ENVIRONMENT=prod``), falling back to the
        unprefixed name.

        Gets a token from Keycloak using client_id + client_secret (supports
        confidential clients). Starts a background thread that periodically
        gets a fresh token and reconnects the client before expiry.

        Required env vars:
            ENTITY_WEAVIATE_ENABLED - 'true' to enable
            WEAVIATE_KEYCLOAK_URL - Keycloak token endpoint
            WEAVIATE_CLIENT_ID - OAuth client ID
            WEAVIATE_CLIENT_SECRET - OAuth client secret
            WEAVIATE_USERNAME - Keycloak username
            WEAVIATE_PASSWORD - Keycloak password
            WEAVIATE_HTTP_HOST - Weaviate HTTP host
            WEAVIATE_GRPC_HOST - Weaviate gRPC host
            WEAVIATE_GRPC_PORT - Weaviate gRPC port (default 50051)
        """
        from vitalgraph.config.config_loader import get_scoped_env

        enabled = get_scoped_env('ENTITY_WEAVIATE_ENABLED', 'false').lower() == 'true'
        if not enabled:
            logger.info("Entity Weaviate indexing is disabled (ENTITY_WEAVIATE_ENABLED != true)")
            return None

        try:
            token_data = EntityWeaviateIndex._get_jwt_token()
            if not token_data:
                logger.error("Failed to obtain JWT token for Weaviate")
                return None

            http_host = get_scoped_env('WEAVIATE_HTTP_HOST')
            grpc_host = get_scoped_env('WEAVIATE_GRPC_HOST')
            grpc_port = int(get_scoped_env('WEAVIATE_GRPC_PORT', '50051'))

            if not http_host or not grpc_host:
                logger.error("WEAVIATE_HTTP_HOST and WEAVIATE_GRPC_HOST are required")
                return None

            connect_params = {
                'http_host': http_host,
                'grpc_host': grpc_host,
                'grpc_port': grpc_port,
            }

            client = EntityWeaviateIndex._create_client(token_data, **connect_params)
            await client.connect()

            collection_name = get_collection_name()
            location_collection_name = get_location_collection_name()
            index = EntityWeaviateIndex(
                client, collection_name=collection_name,
                location_collection_name=location_collection_name,
            )
            index._connect_params = connect_params

            expires_in = token_data.get('expires_in', 60)
            index._start_token_refresh(expires_in)

            logger.info(f"Entity Weaviate index connected to {http_host} "
                         f"(entity={collection_name}, location={location_collection_name})")
            return index

        except Exception as e:
            logger.error(f"Failed to connect to Weaviate: {e}")
            return None

    @staticmethod
    def _get_jwt_token() -> Optional[str]:
        """Get a JWT token from Keycloak for Weaviate auth."""
        from vitalgraph.config.config_loader import get_scoped_env

        keycloak_url = get_scoped_env('WEAVIATE_KEYCLOAK_URL')
        client_id = get_scoped_env('WEAVIATE_CLIENT_ID')
        client_secret = get_scoped_env('WEAVIATE_CLIENT_SECRET')
        username = get_scoped_env('WEAVIATE_USERNAME')
        password = get_scoped_env('WEAVIATE_PASSWORD')

        if not all([keycloak_url, client_id, client_secret, username, password]):
            logger.error("Missing Weaviate Keycloak credentials in environment")
            return None

        try:
            response = requests.post(
                keycloak_url,
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                    "scope": "openid profile email offline_access",
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get Weaviate JWT token: {e}")
            return None

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    async def ensure_collection(self) -> bool:
        """Create EntityIndex and LocationIndex collections if they don't exist.

        Creates both collections first (without cross-references), then adds
        the bidirectional cross-references once both exist.
        Returns True if both collections exist or were created successfully.
        """
        await self._ensure_connected()
        try:
            loc_created = False
            ent_created = False

            # Create LocationIndex
            if await self.client.collections.exists(self.location_collection_name):
                logger.info(f"Weaviate collection '{self.location_collection_name}' already exists")
            else:
                loc_config = get_location_collection_config(self.location_collection_name)
                await self.client.collections.create(**loc_config)
                logger.info(f"Weaviate collection '{self.location_collection_name}' created")
                loc_created = True

            # Create EntityIndex
            if await self.client.collections.exists(self.collection_name):
                logger.info(f"Weaviate collection '{self.collection_name}' already exists")
            else:
                config = get_collection_config(self.collection_name)
                await self.client.collections.create(**config)
                logger.info(f"Weaviate collection '{self.collection_name}' created")
                ent_created = True

            # Add cross-references after both collections exist
            await self._ensure_cross_references(ent_created, loc_created)

            return True
        except Exception as e:
            logger.error(f"Failed to ensure Weaviate collections: {e}")
            return False

    async def _ensure_cross_references(self, entity_is_new: bool = False, location_is_new: bool = False):
        """Add cross-references between EntityIndex and LocationIndex.

        Always checks for and adds missing references (safe to call repeatedly).
        Handles the case where collections existed before Phase 5 cross-refs.
        """
        import weaviate.classes.config as wvc

        # EntityIndex → LocationIndex ("locations")
        try:
            await self.collection.config.add_reference(
                wvc.ReferenceProperty(
                    name="locations",
                    target_collection=self.location_collection_name,
                )
            )
            logger.info(f"Added 'locations' cross-ref on {self.collection_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug(f"'locations' cross-ref on {self.collection_name} already exists")
            else:
                logger.warning(f"Could not add 'locations' cross-ref: {e}")

        # LocationIndex → EntityIndex ("entity")
        try:
            await self.location_collection.config.add_reference(
                wvc.ReferenceProperty(
                    name="entity",
                    target_collection=self.collection_name,
                )
            )
            logger.info(f"Added 'entity' cross-ref on {self.location_collection_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug(f"'entity' cross-ref on {self.location_collection_name} already exists")
            else:
                logger.warning(f"Could not add 'entity' cross-ref: {e}")

    async def rebuild_collection(self) -> bool:
        """Drop and recreate EntityIndex and LocationIndex collections.

        Provides a clean slate for a full rebuild — faster than upserting
        10M+ objects over existing data.

        Returns True if collections were successfully recreated.
        """
        await self._ensure_connected()
        try:
            # Delete both and wait for removal to propagate
            for name in [self.collection_name, self.location_collection_name]:
                if await self.client.collections.exists(name):
                    await self.client.collections.delete(name)
                    logger.info(f"Weaviate collection '{name}' deleted")
                    # Wait until Weaviate confirms it's gone
                    for _ in range(30):
                        if not await self.client.collections.exists(name):
                            break
                        await asyncio.sleep(0.5)
                    else:
                        raise RuntimeError(f"Collection '{name}' still exists after delete")

            # Recreate both
            loc_config = get_location_collection_config(self.location_collection_name)
            await self.client.collections.create(**loc_config)
            logger.info(f"Weaviate collection '{self.location_collection_name}' recreated")

            config = get_collection_config(self.collection_name)
            await self.client.collections.create(**config)
            logger.info(f"Weaviate collection '{self.collection_name}' recreated")

            # Reset cached collection handles
            self._collection = None
            self._location_collection = None

            # Add cross-references
            await self._ensure_cross_references(entity_is_new=True, location_is_new=True)

            return True
        except Exception as e:
            logger.error(f"Failed to rebuild Weaviate collections: {e}")
            return False

    @property
    def collection(self):
        """Get the EntityIndex collection handle (sync, local only)."""
        if self._collection is None:
            self._collection = self.client.collections.use(self.collection_name)
        return self._collection

    @property
    def location_collection(self):
        """Get the LocationIndex collection handle (sync, local only)."""
        if self._location_collection is None:
            self._location_collection = self.client.collections.use(self.location_collection_name)
        return self._location_collection

    # ------------------------------------------------------------------
    # Entity upsert / delete
    # ------------------------------------------------------------------

    async def upsert_entity(self, entity: dict) -> bool:
        """Upsert a single entity into Weaviate.

        Args:
            entity: Entity dict with aliases and categories included.

        Returns True on success.
        """
        await self._ensure_connected()
        try:
            entity_id = entity['entity_id']
            obj_uuid = entity_id_to_weaviate_uuid(entity_id)
            properties = entity_to_weaviate_properties(entity)

            # Check if object exists
            try:
                existing = await self.collection.query.fetch_object_by_id(obj_uuid)
                if existing:
                    await self.collection.data.update(
                        uuid=obj_uuid,
                        properties=properties,
                    )
                    logger.debug(f"Updated entity {entity_id} in Weaviate")
                    return True
            except Exception:
                pass

            # Insert new
            await self.collection.data.insert(
                uuid=obj_uuid,
                properties=properties,
            )
            logger.debug(f"Inserted entity {entity_id} into Weaviate")
            return True

        except Exception as e:
            logger.error(f"Failed to upsert entity {entity.get('entity_id')} in Weaviate: {e}")
            return False

    async def delete_entity(self, entity_id: str) -> bool:
        """Delete a single entity from Weaviate.

        Returns True if deleted or didn't exist.
        """
        await self._ensure_connected()
        try:
            obj_uuid = entity_id_to_weaviate_uuid(entity_id)
            await self.collection.data.delete_by_id(obj_uuid)
            logger.debug(f"Deleted entity {entity_id} from Weaviate")
            return True
        except Exception as e:
            logger.error(f"Failed to delete entity {entity_id} from Weaviate: {e}")
            return False

    async def upsert_entities_batch(self, entities: List[dict]) -> int:
        """Batch upsert entities into Weaviate using insert_many.

        Args:
            entities: List of entity dicts with aliases and categories.

        Returns count of successfully upserted entities.
        """
        await self._ensure_connected()
        if not entities:
            return 0
        try:
            objects = []
            for entity in entities:
                try:
                    obj_uuid = entity_id_to_weaviate_uuid(entity['entity_id'])
                    properties = entity_to_weaviate_properties(entity)
                    objects.append(DataObject(properties=properties, uuid=obj_uuid))
                except Exception as e:
                    logger.error(f"Failed to prepare entity {entity.get('entity_id')}: {e}")
            response = await self.collection.data.insert_many(objects)
            if response.has_errors:
                for i, err in enumerate(response.errors):
                    logger.error(f"Entity batch insert error at index {i}: {err}")
            return len(objects) - len(response.errors) if response.errors else len(objects)
        except Exception as e:
            logger.error(f"Batch upsert failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # Location upsert / delete
    # ------------------------------------------------------------------

    async def upsert_location(self, location: dict) -> bool:
        """Upsert a single location into LocationIndex with cross-ref to EntityIndex.

        Args:
            location: Location dict with entity_id, location_id, and address fields.

        Returns True on success.
        """
        await self._ensure_connected()
        try:
            loc_id = location['location_id']
            entity_id = location['entity_id']
            obj_uuid = location_id_to_weaviate_uuid(loc_id)
            entity_uuid = entity_id_to_weaviate_uuid(entity_id)
            properties = location_to_weaviate_properties(location)

            # Cross-reference to the owning entity
            references = {"entity": entity_uuid}

            try:
                existing = await self.location_collection.query.fetch_object_by_id(obj_uuid)
                if existing:
                    await self.location_collection.data.update(
                        uuid=obj_uuid,
                        properties=properties,
                        references=references,
                    )
                    logger.debug(f"Updated location {loc_id} in Weaviate")
                    return True
            except Exception:
                pass

            await self.location_collection.data.insert(
                uuid=obj_uuid,
                properties=properties,
                references=references,
            )
            logger.debug(f"Inserted location {loc_id} into Weaviate")
            return True

        except Exception as e:
            logger.error(f"Failed to upsert location {location.get('location_id')} in Weaviate: {e}")
            return False

    async def delete_location(self, location_id: int) -> bool:
        """Delete a single location from LocationIndex.

        Returns True if deleted or didn't exist.
        """
        await self._ensure_connected()
        try:
            obj_uuid = location_id_to_weaviate_uuid(location_id)
            await self.location_collection.data.delete_by_id(obj_uuid)
            logger.debug(f"Deleted location {location_id} from Weaviate")
            return True
        except Exception as e:
            logger.error(f"Failed to delete location {location_id} from Weaviate: {e}")
            return False

    async def upsert_locations_batch(self, locations: List[dict]) -> int:
        """Batch upsert locations into LocationIndex using insert_many.

        Args:
            locations: List of location dicts with entity_id.

        Returns count of successfully upserted locations.
        """
        await self._ensure_connected()
        if not locations:
            return 0
        try:
            objects = []
            for loc in locations:
                try:
                    obj_uuid = location_id_to_weaviate_uuid(loc['location_id'])
                    entity_uuid = entity_id_to_weaviate_uuid(loc['entity_id'])
                    properties = location_to_weaviate_properties(loc)
                    objects.append(DataObject(
                        properties=properties,
                        uuid=obj_uuid,
                        references={"entity": entity_uuid},
                    ))
                except Exception as e:
                    logger.error(f"Failed to prepare location {loc.get('location_id')}: {e}")
            response = await self.location_collection.data.insert_many(objects)
            if response.has_errors:
                for i, err in enumerate(response.errors):
                    logger.error(f"Location batch insert error at index {i}: {err}")
            return len(objects) - len(response.errors) if response.errors else len(objects)
        except Exception as e:
            logger.error(f"Location batch upsert failed: {e}")
            return 0

    async def set_entity_location_refs(self, entity_id: str, location_ids: List[int]):
        """Set the locations cross-reference on an EntityIndex object.

        Replaces any existing location refs with the given list.
        """
        await self._ensure_connected()
        try:
            entity_uuid = entity_id_to_weaviate_uuid(entity_id)
            loc_uuids = [location_id_to_weaviate_uuid(lid) for lid in location_ids]
            # Replace all location refs
            await self.collection.data.reference_replace(
                from_uuid=entity_uuid,
                from_property="locations",
                to=loc_uuids,
            )
            logger.debug(f"Set {len(loc_uuids)} location refs on entity {entity_id}")
        except Exception as e:
            logger.error(f"Failed to set location refs for entity {entity_id}: {e}")

    # ------------------------------------------------------------------
    # Full sync from PostgreSQL
    # ------------------------------------------------------------------

    async def full_sync(self, pool, batch_size: int = 500, since=None,
                        chunk_size: int = 5000,
                        entity_vectors=None,
                        resume_after: str = None,
                        ) -> Tuple[int, int]:
        """Sync entities from PostgreSQL → Weaviate.

        Uses a single bulk query (entity + aliases + categories via LEFT JOINs)
        and processes rows via a cursor in chunks to stay memory-efficient at
        scale (10M+ entities).

        Args:
            pool: asyncpg connection pool
            batch_size: Number of entities per Weaviate batch upsert
            since: Optional datetime — if provided, only sync entities whose
                   updated_time >= since (incremental). Full sync if None.
            chunk_size: Number of rows to fetch per cursor chunk.
            entity_vectors: Optional StreamingVectorLookup or dict mapping
                entity_id → vector list. If provided, vectors are passed
                directly to Weaviate and server-side vectorization is
                skipped for those entities.
            resume_after: Optional entity_id — skip all entities up to and
                including this ID (keyset start point for resume).

        Returns:
            Tuple of (upserted_count, deleted_count)
        """
        import time as _time
        start = _time.time()
        mode = 'incremental' if since else 'full'
        logger.info(f"Starting Weaviate {mode} sync...")

        # Keyset pagination: fetch pages of entity_ids, then joined data
        # for each page.  Each query is short-lived — no long transactions.
        entity_data_sql = (
            "SELECT e.entity_id, e.primary_name, e.description, e.country, "
            "e.region, e.locality, e.website, e.latitude, e.longitude, e.status, "
            "et.type_key, et.type_label, et.type_description, "
            "ea.alias_name, ea.alias_type, "
            "ec.category_key, ec.category_label "
            "FROM entity e "
            "JOIN entity_type et ON e.entity_type_id = et.type_id "
            "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
            "AND ea.status = 'active' "
            "LEFT JOIN entity_category_map ecm ON ecm.entity_id = e.entity_id "
            "AND ecm.status = 'active' "
            "LEFT JOIN category ec ON ec.category_id = ecm.category_id "
            "WHERE e.entity_id = ANY($1) "
            "ORDER BY e.entity_id"
        )

        pg_ids = set()
        upserted_count = 0
        pending_batch = []

        current_entity_id = None
        current_entity = None
        seen_aliases = None
        seen_categories = None

        def _flush_entity():
            """Add the current entity to the pending batch."""
            nonlocal upserted_count
            if current_entity is not None:
                pending_batch.append(current_entity)

        async def _enrich_with_locations(conn):
            """Fetch locations for all entities in the pending batch and merge."""
            if not pending_batch:
                return
            eids = [e['entity_id'] for e in pending_batch]
            loc_rows = await conn.fetch(
                "SELECT el.entity_id, el.location_name, el.formatted_address, "
                "el.locality, el.admin_area_1, el.country "
                "FROM entity_location el "
                "WHERE el.entity_id = ANY($1) AND el.status = 'active' "
                "ORDER BY el.entity_id, el.is_primary DESC, el.location_id",
                eids
            )
            # Group locations by entity_id
            loc_map = {}
            for lr in loc_rows:
                loc_map.setdefault(lr['entity_id'], []).append(dict(lr))
            for entity in pending_batch:
                entity['locations'] = loc_map.get(entity['entity_id'], [])

        async def _enrich_with_identifiers(conn):
            """Fetch identifiers for all entities in the pending batch and merge."""
            if not pending_batch:
                return
            eids = [e['entity_id'] for e in pending_batch]
            id_rows = await conn.fetch(
                "SELECT entity_id, identifier_namespace, identifier_value "
                "FROM entity_identifier "
                "WHERE entity_id = ANY($1) AND status = 'active' "
                "ORDER BY entity_id",
                eids
            )
            id_map = {}
            for ir in id_rows:
                id_map.setdefault(ir['entity_id'], []).append(dict(ir))
            for entity in pending_batch:
                entity['identifiers'] = id_map.get(entity['entity_id'], [])

        async def _flush_batch():
            """Enrich with locations and identifiers, then insert_many to Weaviate."""
            nonlocal upserted_count
            if pending_batch:
                await self._ensure_connected()
                batch_len = len(pending_batch)
                async with pool.acquire() as enrich_conn:
                    await _enrich_with_locations(enrich_conn)
                    await _enrich_with_identifiers(enrich_conn)
                # Get vectors for this batch
                vec_batch = None
                if entity_vectors is not None:
                    batch_ids = [e['entity_id'] for e in pending_batch]
                    if hasattr(entity_vectors, 'get_batch'):
                        vec_batch = entity_vectors.get_batch(batch_ids)
                    else:
                        vec_batch = {eid: entity_vectors[eid] for eid in batch_ids
                                     if eid in entity_vectors}
                objects = []
                for entity in pending_batch:
                    try:
                        obj_uuid = entity_id_to_weaviate_uuid(entity['entity_id'])
                        properties = entity_to_weaviate_properties(entity)
                        vec = vec_batch.get(entity['entity_id']) if vec_batch else None
                        objects.append(DataObject(properties=properties, uuid=obj_uuid,
                                                  vector=vec))
                    except Exception as e:
                        logger.error(f"Failed to prepare entity {entity.get('entity_id')}: {e}")
                if objects:
                    await self._ensure_connected()
                    response = await self.collection.data.insert_many(objects)
                    inserted = len(objects) - len(response.errors) if response.errors else len(objects)
                    upserted_count += inserted
                    if response.has_errors:
                        for i, err in enumerate(response.errors):
                            logger.error(f"Entity insert error at index {i}: {err}")
                elapsed = _time.time() - start
                rate = upserted_count / elapsed if elapsed > 0 else 0
                if upserted_count % 5000 < batch_len or upserted_count < batch_len * 2:
                    logger.info(f"  Entities: {upserted_count:,} upserted "
                                f"({rate:.0f}/s, {elapsed:.0f}s elapsed)")
                pending_batch.clear()

        await self._ensure_connected()

        last_entity_id = resume_after or ''
        if resume_after:
            logger.info(f"Resuming entity sync after entity_id={resume_after!r}")
        while True:
            # Fetch next page of entity IDs (short-lived connection)
            async with pool.acquire() as conn:
                if since is not None:
                    id_rows = await conn.fetch(
                        "SELECT entity_id FROM entity WHERE status = 'active' "
                        "AND updated_time >= $1 AND entity_id > $2 "
                        "ORDER BY entity_id LIMIT $3",
                        since, last_entity_id, chunk_size
                    )
                else:
                    id_rows = await conn.fetch(
                        "SELECT entity_id FROM entity WHERE status = 'active' "
                        "AND entity_id > $1 ORDER BY entity_id LIMIT $2",
                        last_entity_id, chunk_size
                    )
            if not id_rows:
                break
            batch_eids = [r['entity_id'] for r in id_rows]
            last_entity_id = batch_eids[-1]
            pg_ids.update(batch_eids)

            # Fetch full joined data for these entity IDs
            async with pool.acquire() as conn:
                rows = await conn.fetch(entity_data_sql, batch_eids)

            for row in rows:
                entity_id = row['entity_id']

                if entity_id != current_entity_id:
                    # Flush previous entity
                    _flush_entity()

                    # Flush batch when it hits batch_size
                    if len(pending_batch) >= batch_size:
                        await _flush_batch()

                    # Start new entity
                    current_entity_id = entity_id
                    seen_aliases = set()
                    seen_categories = set()
                    current_entity = {
                        'entity_id': entity_id,
                        'primary_name': row['primary_name'],
                        'description': row['description'],
                        'country': row['country'],
                        'region': row['region'],
                        'locality': row['locality'],
                        'website': row['website'],
                        'latitude': row['latitude'],
                        'longitude': row['longitude'],
                        'status': row['status'],
                        'type_key': row['type_key'],
                        'type_label': row['type_label'],
                        'type_description': row['type_description'],
                        'aliases': [],
                        'categories': [],
                    }

                # Deduplicate aliases (cross-join with categories produces duplicates)
                alias_name = row['alias_name']
                if alias_name and alias_name not in seen_aliases:
                    seen_aliases.add(alias_name)
                    current_entity['aliases'].append({
                        'alias_name': alias_name,
                        'alias_type': row['alias_type'],
                    })

                # Deduplicate categories
                cat_key = row['category_key']
                if cat_key and cat_key not in seen_categories:
                    seen_categories.add(cat_key)
                    current_entity['categories'].append({
                        'category_key': cat_key,
                        'category_label': row['category_label'],
                    })

        # Flush remaining
        _flush_entity()
        await _flush_batch()

        # Remove stale Weaviate objects (only for full sync, not resume)
        deleted_count = 0
        if since is None and resume_after is None:
            try:
                weaviate_ids = set()
                cursor_uuid = None
                while True:
                    kwargs = {"limit": 1000, "include_vector": False}
                    if cursor_uuid:
                        kwargs["after"] = cursor_uuid
                    response = await self.collection.query.fetch_objects(**kwargs)
                    if not response.objects:
                        break
                    for obj in response.objects:
                        weaviate_ids.add(obj.properties.get('entity_id'))
                        cursor_uuid = obj.uuid

                logger.info(f"Fetched {len(weaviate_ids):,} entity IDs from Weaviate for stale detection")
                stale_ids = weaviate_ids - pg_ids
                if stale_ids:
                    logger.info(f"Deleting {len(stale_ids):,} stale entities from Weaviate...")
                for stale_id in stale_ids:
                    await self.delete_entity(stale_id)
                    deleted_count += 1
                    if deleted_count % 500 == 0:
                        logger.info(f"  Stale entities deleted: {deleted_count:,}/{len(stale_ids):,}")

                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} stale entities from Weaviate")
            except Exception as e:
                logger.warning(f"Could not check for stale Weaviate objects: {e}")

        duration = _time.time() - start
        logger.info(f"Weaviate {mode} sync complete: {upserted_count:,} upserted, "
                     f"{deleted_count:,} deleted in {duration:.1f}s")
        return upserted_count, deleted_count

    async def location_sync(self, pool, batch_size: int = 1000, since=None,
                            chunk_size: int = 5000,
                            location_vectors=None,
                            ) -> Tuple[int, int]:
        """Sync locations from PostgreSQL → Weaviate LocationIndex.

        Also sets the Entity→Location cross-references on EntityIndex.

        Args:
            pool: asyncpg connection pool
            batch_size: Number of locations per Weaviate batch upsert
            since: Optional datetime — incremental sync if provided.
            chunk_size: Number of rows per cursor chunk.
            location_vectors: Optional StreamingVectorLookup or dict mapping
                location_id (int) → vector list. If provided, vectors are
                passed directly to Weaviate and server-side vectorization
                is skipped for those locations.

        Returns:
            Tuple of (upserted_count, deleted_count)
        """
        import time as _time
        start = _time.time()
        mode = 'incremental' if since else 'full'
        logger.info(f"Starting Weaviate location {mode} sync...")

        # Base SQL for location data (keyset pagination adds WHERE clause)
        loc_select = (
            "SELECT el.location_id, el.entity_id, el.location_name, el.description, "
            "el.address_line_1, el.address_line_2, el.locality, el.admin_area_1, el.country, "
            "el.country_code, el.postal_code, el.formatted_address, "
            "el.latitude, el.longitude, el.is_primary, el.status, "
            "el.external_location_id, "
            "elt.type_key AS location_type_key, elt.type_label AS location_type_label "
            "FROM entity_location el "
            "JOIN entity_location_type elt ON el.location_type_id = elt.location_type_id "
            "WHERE el.status = 'active' "
        )

        pg_loc_ids = set()
        upserted_count = 0
        pending_batch = []
        # Track entity_id → {location_id} for cross-ref setting (set prevents dupes)
        entity_loc_map: Dict[str, set] = {}

        async def _flush_loc_batch():
            nonlocal upserted_count
            if pending_batch:
                await self._ensure_connected()
                batch_len = len(pending_batch)
                # Get vectors for this batch
                vec_batch = None
                if location_vectors is not None:
                    batch_ids = [loc['location_id'] for loc in pending_batch]
                    if hasattr(location_vectors, 'get_batch'):
                        vec_batch = location_vectors.get_batch(batch_ids)
                    else:
                        vec_batch = {lid: location_vectors[lid] for lid in batch_ids
                                     if lid in location_vectors}
                objects = []
                for loc in pending_batch:
                    try:
                        obj_uuid = location_id_to_weaviate_uuid(loc['location_id'])
                        entity_uuid = entity_id_to_weaviate_uuid(loc['entity_id'])
                        properties = location_to_weaviate_properties(loc)
                        vec = vec_batch.get(loc['location_id']) if vec_batch else None
                        objects.append(DataObject(
                            properties=properties,
                            uuid=obj_uuid,
                            references={"entity": entity_uuid},
                            vector=vec,
                        ))
                    except Exception as e:
                        logger.error(f"Failed to prepare location {loc.get('location_id')}: {e}")
                if objects:
                    await self._ensure_connected()
                    response = await self.location_collection.data.insert_many(objects)
                    inserted = len(objects) - len(response.errors) if response.errors else len(objects)
                    upserted_count += inserted
                    if response.has_errors:
                        for i, err in enumerate(response.errors):
                            logger.error(f"Location insert error at index {i}: {err}")
                elapsed = _time.time() - start
                rate = upserted_count / elapsed if elapsed > 0 else 0
                if upserted_count % 5000 < batch_len or upserted_count < batch_len * 2:
                    logger.info(f"  Locations: {upserted_count:,} upserted "
                                f"({rate:.0f}/s, {elapsed:.0f}s elapsed)")
                pending_batch.clear()

        await self._ensure_connected()

        # Keyset pagination — short-lived connections, no long transactions
        last_location_id = 0
        while True:
            async with pool.acquire() as conn:
                if since is not None:
                    rows = await conn.fetch(
                        loc_select +
                        "AND el.updated_time >= $1 AND el.location_id > $2 "
                        "ORDER BY el.location_id LIMIT $3",
                        since, last_location_id, chunk_size
                    )
                else:
                    rows = await conn.fetch(
                        loc_select +
                        "AND el.location_id > $1 "
                        "ORDER BY el.location_id LIMIT $2",
                        last_location_id, chunk_size
                    )
            if not rows:
                break
            last_location_id = rows[-1]['location_id']
            for row in rows:
                loc = dict(row)
                pg_loc_ids.add(loc['location_id'])
                entity_loc_map.setdefault(loc['entity_id'], set()).add(loc['location_id'])
                pending_batch.append(loc)

                if len(pending_batch) >= batch_size:
                    await _flush_loc_batch()

        # Flush remaining
        await _flush_loc_batch()

        # Set Entity→Location cross-references using reference_replace
        # (idempotent — replaces all refs rather than appending, so re-runs
        # produce clean data with no duplicates)
        import asyncio
        import logging as _logging
        ref_count = 0
        ref_errors = 0
        total_refs = len(entity_loc_map)
        sem = asyncio.Semaphore(100)

        _logging.getLogger("httpx").setLevel(_logging.WARNING)

        async def _replace_one(eid: str, loc_ids: set):
            nonlocal ref_count, ref_errors
            entity_uuid = entity_id_to_weaviate_uuid(eid)
            loc_uuids = [location_id_to_weaviate_uuid(lid) for lid in loc_ids]
            async with sem:
                try:
                    await self.collection.data.reference_replace(
                        from_uuid=entity_uuid,
                        from_property="locations",
                        to=loc_uuids,
                    )
                    ref_count += 1
                except Exception as e:
                    ref_errors += 1
                    if ref_errors <= 5:
                        logger.error(f"Cross-ref replace error for {eid}: {e}")

        items = list(entity_loc_map.items())
        chunk_size = 1000
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            await self._ensure_connected()
            await asyncio.gather(*[_replace_one(eid, lids) for eid, lids in chunk])
            elapsed = _time.time() - start
            rate = ref_count / elapsed if elapsed > 0 else 0
            logger.info(f"  Cross-refs: {ref_count:,}/{total_refs:,} "
                        f"({rate:.0f}/s, {elapsed:.0f}s elapsed)")

        _logging.getLogger("httpx").setLevel(_logging.INFO)
        if ref_count:
            logger.info(f"Set location cross-refs on {ref_count:,} entities"
                        f"{f' ({ref_errors} errors)' if ref_errors else ''}")

        # Remove stale location objects (full sync only)
        deleted_count = 0
        if since is None:
            try:
                weaviate_loc_ids = set()
                cursor_uuid = None
                while True:
                    kwargs = {"limit": 1000, "include_vector": False}
                    if cursor_uuid:
                        kwargs["after"] = cursor_uuid
                    response = await self.location_collection.query.fetch_objects(**kwargs)
                    if not response.objects:
                        break
                    for obj in response.objects:
                        lid = obj.properties.get('location_id')
                        if lid:
                            weaviate_loc_ids.add(int(lid))
                        cursor_uuid = obj.uuid

                stale_ids = weaviate_loc_ids - pg_loc_ids
                for stale_id in stale_ids:
                    await self.delete_location(stale_id)
                    deleted_count += 1

                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} stale locations from Weaviate")
            except Exception as e:
                logger.warning(f"Could not check for stale Weaviate locations: {e}")

        duration = _time.time() - start
        logger.info(f"Weaviate location {mode} sync complete: {upserted_count:,} upserted, "
                     f"{deleted_count:,} deleted in {duration:.1f}s")
        return upserted_count, deleted_count

    # ------------------------------------------------------------------
    # Cross-reference repair
    # ------------------------------------------------------------------

    async def _load_entity_loc_map(self, pool) -> tuple:
        """Build entity→location_id set mapping from PostgreSQL."""
        entity_loc_map: Dict[str, set] = {}
        last_location_id = 0
        total_locs = 0
        while True:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT entity_id, location_id FROM entity_location "
                    "WHERE status = 'active' AND location_id > $1 "
                    "ORDER BY location_id LIMIT $2",
                    last_location_id, 5000
                )
            if not rows:
                break
            last_location_id = rows[-1]['location_id']
            for row in rows:
                entity_loc_map.setdefault(row['entity_id'], set()).add(row['location_id'])
            total_locs += len(rows)
        return entity_loc_map, total_locs

    async def set_cross_refs(self, pool, batch_size: int = 500, skip: int = 0,
                             error_log_path: Optional[str] = None) -> int:
        """Set Entity→Location cross-references from PostgreSQL mapping.

        Use this to repair cross-refs without re-inserting entities/locations.
        Args:
            skip: Number of entities to skip (for resuming interrupted runs).
            error_log_path: Path to write failed entity IDs (one per line).
                            Defaults to crossref_errors_<timestamp>.log.
        """
        import time as _time
        from datetime import datetime
        start = _time.time()
        await self._ensure_connected()

        logger.info("Building entity→location mapping from PostgreSQL...")
        entity_loc_map, total_locs = await self._load_entity_loc_map(pool)
        logger.info(f"Found {total_locs:,} locations across {len(entity_loc_map):,} entities")

        import asyncio
        import logging as _logging

        # Set up error log file
        if not error_log_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            error_log_path = f"crossref_errors_{ts}.log"
        error_log = open(error_log_path, "w")
        logger.info(f"Error log: {error_log_path}")

        total_refs = len(entity_loc_map)
        ref_count = 0
        ref_errors = 0
        sem = asyncio.Semaphore(100)

        # Suppress per-request httpx logging for speed
        _logging.getLogger("httpx").setLevel(_logging.WARNING)

        async def _replace_one(eid: str, loc_ids: set):
            nonlocal ref_count, ref_errors
            entity_uuid = entity_id_to_weaviate_uuid(eid)
            loc_uuids = [location_id_to_weaviate_uuid(lid) for lid in loc_ids]
            async with sem:
                for attempt in range(1, 4):
                    try:
                        await self.collection.data.reference_replace(
                            from_uuid=entity_uuid,
                            from_property="locations",
                            to=loc_uuids,
                        )
                        ref_count += 1
                        return
                    except Exception as e:
                        if attempt < 3:
                            await asyncio.sleep(1 * attempt)
                            continue
                        ref_errors += 1
                        error_log.write(f"{eid}\t{e}\n")
                        error_log.flush()
                        if ref_errors <= 5:
                            logger.error(f"Cross-ref replace error for {eid}: {e}")

        items = list(entity_loc_map.items())
        if skip > 0:
            logger.info(f"Skipping first {skip:,} entities (already processed)")
            items = items[skip:]
            total_refs = len(items)
            logger.info(f"Resuming with {total_refs:,} remaining entities")
        chunk_size = 1000
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            await self._ensure_connected()
            await asyncio.gather(*[_replace_one(eid, lids) for eid, lids in chunk])
            elapsed = _time.time() - start
            rate = ref_count / elapsed if elapsed > 0 else 0
            logger.info(f"  Cross-refs: {ref_count:,}/{total_refs:,} "
                        f"({rate:.0f}/s, {elapsed:.0f}s elapsed)")

        error_log.close()
        _logging.getLogger("httpx").setLevel(_logging.INFO)
        duration = _time.time() - start
        logger.info(f"Cross-refs complete: {ref_count:,} entities linked in {duration:.1f}s"
                    f"{f' ({ref_errors} errors — see {error_log_path})' if ref_errors else ''}")
        return ref_count

    async def verify_cross_refs(self, pool, batch_size: int = 500) -> Dict[str, Any]:
        """Verify Entity→Location cross-references exist without rewriting.

        Reads each entity from Weaviate and checks its location refs match
        what PostgreSQL expects.  Much faster than set_cross_refs since it
        only reads — no writes.

        Returns dict with counts and list of mismatched entity IDs.
        """
        import time as _time
        from datetime import datetime
        start = _time.time()
        await self._ensure_connected()

        logger.info("Building entity→location mapping from PostgreSQL...")
        entity_loc_map, total_locs = await self._load_entity_loc_map(pool)
        logger.info(f"Found {total_locs:,} locations across {len(entity_loc_map):,} entities")

        import asyncio
        import logging as _logging
        import weaviate.classes.query as wvq

        _logging.getLogger("httpx").setLevel(_logging.WARNING)

        total = len(entity_loc_map)
        ok_count = 0
        mismatch_count = 0
        missing_count = 0
        mismatched_ids: List[str] = []
        sem = asyncio.Semaphore(100)

        location_ref = wvq.QueryReference(link_on="locations",
                                          return_properties=["location_id"])

        async def _check_one(eid: str, expected_loc_ids: set):
            nonlocal ok_count, mismatch_count, missing_count
            entity_uuid = entity_id_to_weaviate_uuid(eid)
            expected_uuids = {location_id_to_weaviate_uuid(lid) for lid in expected_loc_ids}
            async with sem:
                try:
                    obj = await self.collection.query.fetch_object_by_id(
                        entity_uuid,
                        return_references=[location_ref],
                    )
                    if obj is None:
                        missing_count += 1
                        mismatched_ids.append(eid)
                        return

                    actual_uuids = set()
                    refs = obj.references.get("locations")
                    if refs and refs.objects:
                        actual_uuids = {str(o.uuid) for o in refs.objects}

                    if actual_uuids == expected_uuids:
                        ok_count += 1
                    else:
                        mismatch_count += 1
                        mismatched_ids.append(eid)
                except Exception:
                    mismatch_count += 1
                    mismatched_ids.append(eid)

        items = list(entity_loc_map.items())
        chunk_size = 1000
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            await self._ensure_connected()
            await asyncio.gather(*[_check_one(eid, lids) for eid, lids in chunk])
            elapsed = _time.time() - start
            checked = ok_count + mismatch_count + missing_count
            rate = checked / elapsed if elapsed > 0 else 0
            logger.info(f"  Verify: {checked:,}/{total:,} "
                        f"(ok={ok_count:,} mismatch={mismatch_count:,} "
                        f"missing={missing_count:,}, {rate:.0f}/s)")

        _logging.getLogger("httpx").setLevel(_logging.INFO)
        duration = _time.time() - start
        logger.info(f"Verify complete in {duration:.1f}s: "
                    f"ok={ok_count:,}, mismatch={mismatch_count:,}, missing={missing_count:,}")

        # Write mismatched IDs to file for targeted repair
        if mismatched_ids:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            repair_path = f"crossref_repair_{ts}.txt"
            with open(repair_path, "w") as f:
                for eid in mismatched_ids:
                    f.write(f"{eid}\n")
            logger.info(f"Wrote {len(mismatched_ids)} entity IDs to {repair_path} for targeted repair")

        return {
            "ok": ok_count,
            "mismatch": mismatch_count,
            "missing": missing_count,
            "mismatched_ids": mismatched_ids,
            "duration_s": duration,
        }

    # ------------------------------------------------------------------
    # Topic search
    # ------------------------------------------------------------------

    async def search_topic(
        self,
        query: str,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
        limit: int = 10,
        min_certainty: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Semantic topic search using Weaviate vector similarity.

        Args:
            query: Free-text query (vectorized by Weaviate)
            type_key: Optional entity type filter
            category_key: Optional category filter
            country: Optional country filter
            region: Optional region filter
            locality: Optional locality filter
            latitude: Optional center latitude for geo range filter
            longitude: Optional center longitude for geo range filter
            radius_km: Optional radius in km for geo range filter
            identifier_value: Optional identifier value filter
            identifier_namespace: Optional identifier namespace (requires identifier_value)
            limit: Max results
            min_certainty: Minimum certainty threshold (0-1)

        Returns:
            List of result dicts with entity fields + score + distance.
        """
        await self._ensure_connected()
        try:
            # Build filters
            filters = self._build_filters(
                type_key=type_key, category_key=category_key,
                country=country, region=region, locality=locality,
                latitude=latitude, longitude=longitude, radius_km=radius_km,
                identifier_value=identifier_value, identifier_namespace=identifier_namespace,
            )

            response = await self.collection.query.near_text(
                query=query,
                filters=filters,
                limit=limit,
                certainty=min_certainty,
                return_metadata=wvq.MetadataQuery(distance=True, certainty=True),
            )

            results = []
            for obj in response.objects:
                props = obj.properties
                result = {
                    "entity_id": props.get("entity_id"),
                    "primary_name": props.get("primary_name"),
                    "description": props.get("description"),
                    "type_key": props.get("type_key"),
                    "type_label": props.get("type_label"),
                    "country": props.get("country"),
                    "region": props.get("region"),
                    "locality": props.get("locality"),
                    "category_keys": props.get("category_keys", []),
                    "latitude": getattr(props.get("geo_location"), "latitude", None) if props.get("geo_location") else None,
                    "longitude": getattr(props.get("geo_location"), "longitude", None) if props.get("geo_location") else None,
                    "score": obj.metadata.certainty if obj.metadata.certainty else 0.0,
                    "distance": obj.metadata.distance if obj.metadata.distance else 0.0,
                }
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Weaviate topic search failed: {e}")
            return []

    async def search_by_identifier(
        self,
        identifier_value: str,
        identifier_namespace: Optional[str] = None,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Filter-only identifier search using Weaviate (no vector similarity).

        Uses fetch_objects with exact-match filters on identifier_keys or
        identifier_values properties.
        """
        await self._ensure_connected()
        try:
            filters = self._build_filters(
                type_key=type_key, category_key=category_key,
                country=country, region=region, locality=locality,
                identifier_value=identifier_value,
                identifier_namespace=identifier_namespace,
            )

            response = await self.collection.query.fetch_objects(
                filters=filters,
                limit=limit,
            )

            results = []
            for obj in response.objects:
                props = obj.properties
                result = {
                    "entity_id": props.get("entity_id"),
                    "primary_name": props.get("primary_name"),
                    "description": props.get("description"),
                    "type_key": props.get("type_key"),
                    "type_label": props.get("type_label"),
                    "country": props.get("country"),
                    "region": props.get("region"),
                    "locality": props.get("locality"),
                    "category_keys": props.get("category_keys", []),
                    "latitude": getattr(props.get("geo_location"), "latitude", None) if props.get("geo_location") else None,
                    "longitude": getattr(props.get("geo_location"), "longitude", None) if props.get("geo_location") else None,
                    "score": 1.0,
                    "distance": 0.0,
                }
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Weaviate identifier search failed: {e}")
            return []

    async def search_hybrid(
        self,
        query: str,
        alpha: float = 0.5,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining BM25 keyword + vector similarity.

        Args:
            query: Free-text query
            alpha: 0=pure BM25, 1=pure vector (default 0.5)
            type_key: Optional entity type filter
            category_key: Optional category filter
            country: Optional country filter
            region: Optional region filter
            locality: Optional locality filter
            limit: Max results

        Returns:
            List of result dicts with entity fields + score.
        """
        try:
            filters = self._build_filters(
                type_key=type_key, category_key=category_key,
                country=country, region=region, locality=locality,
            )

            response = await self.collection.query.hybrid(
                query=query,
                alpha=alpha,
                filters=filters,
                limit=limit,
                return_metadata=wvq.MetadataQuery(score=True),
            )

            results = []
            for obj in response.objects:
                props = obj.properties
                result = {
                    "entity_id": props.get("entity_id"),
                    "primary_name": props.get("primary_name"),
                    "description": props.get("description"),
                    "type_key": props.get("type_key"),
                    "type_label": props.get("type_label"),
                    "country": props.get("country"),
                    "region": props.get("region"),
                    "locality": props.get("locality"),
                    "category_keys": props.get("category_keys", []),
                    "score": obj.metadata.score if obj.metadata.score else 0.0,
                    "distance": 0.0,
                }
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Weaviate hybrid search failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Geo search (LocationIndex)
    # ------------------------------------------------------------------

    async def search_locations_near(
        self,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        q: Optional[str] = None,
        address: Optional[str] = None,
        location_type_key: Optional[str] = None,
        country_code: Optional[str] = None,
        locality: Optional[str] = None,
        admin_area_1: Optional[str] = None,
        postal_code: Optional[str] = None,
        location_name: Optional[str] = None,
        entity_id: Optional[str] = None,
        is_primary: Optional[bool] = None,
        external_location_id: Optional[str] = None,
        min_certainty: float = 0.5,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Find locations within a radius of a lat/long point.

        Supports three search modes (combinable with geo + property filters):
          - q: semantic vector search on location name, description, search_text
          - address: BM25 keyword search on address_line_1, address_line_2
          - neither: geo + property filters only

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Radius in kilometers
            q: Optional semantic query (near_text on name/description)
            address: Optional keyword query (BM25 on address_line_1, address_line_2)
            location_type_key: Optional filter (headquarters, branch, etc.)
            country_code: Optional country code filter (e.g. US, GB)
            locality: Optional city/locality filter
            admin_area_1: Optional state/province filter
            postal_code: Optional postal code filter
            location_name: Optional exact location name filter
            entity_id: Optional filter to a specific entity
            is_primary: Optional filter for primary locations only
            min_certainty: Minimum certainty for semantic search (default 0.5)
            limit: Max results

        Returns:
            List of location dicts with entity_id.
        """
        await self._ensure_connected()
        try:
            filters = self._build_location_filters(
                latitude=latitude, longitude=longitude, radius_km=radius_km,
                location_type_key=location_type_key,
                country_code=country_code, locality=locality,
                admin_area_1=admin_area_1, postal_code=postal_code,
                location_name=location_name, entity_id=entity_id,
                is_primary=is_primary,
                external_location_id=external_location_id,
            )

            if q and address:
                # Semantic search first, then post-filter BM25 matches
                # (Weaviate doesn't support near_text + bm25 in one query)
                response = await self.location_collection.query.near_text(
                    query=q,
                    filters=filters,
                    limit=limit * 3,
                    certainty=min_certainty,
                )
                # Post-filter: keep only results where address fields match
                addr_lower = address.lower()
                filtered_objects = []
                for obj in response.objects:
                    p = obj.properties
                    a1 = (p.get("address_line_1") or "").lower()
                    a2 = (p.get("address_line_2") or "").lower()
                    if addr_lower in a1 or addr_lower in a2:
                        filtered_objects.append(obj)
                response_objects = filtered_objects[:limit]
            elif q:
                response = await self.location_collection.query.near_text(
                    query=q,
                    filters=filters,
                    limit=limit,
                    certainty=min_certainty,
                )
                response_objects = response.objects
            elif address:
                response = await self.location_collection.query.bm25(
                    query=address,
                    query_properties=["address_line_1", "address_line_2"],
                    filters=filters,
                    limit=limit,
                )
                response_objects = response.objects
            else:
                response = await self.location_collection.query.fetch_objects(
                    filters=filters,
                    limit=limit,
                )
                response_objects = response.objects

            results = []
            for obj in response_objects:
                props = obj.properties
                geo = props.get('geo_location')
                results.append({
                    "location_id": int(props.get("location_id", 0)),
                    "entity_id": props.get("entity_id"),
                    "location_name": props.get("location_name"),
                    "location_type_key": props.get("location_type_key"),
                    "formatted_address": props.get("formatted_address"),
                    "address_line_1": props.get("address_line_1"),
                    "address_line_2": props.get("address_line_2"),
                    "locality": props.get("locality"),
                    "admin_area_1": props.get("admin_area_1"),
                    "country_code": props.get("country_code"),
                    "postal_code": props.get("postal_code"),
                    "latitude": getattr(geo, 'latitude', None) if geo else None,
                    "longitude": getattr(geo, 'longitude', None) if geo else None,
                    "external_location_id": props.get("external_location_id"),
                    "is_primary": props.get("is_primary", False),
                })

            return results

        except Exception as e:
            logger.error(f"Weaviate locations-near search failed: {e}")
            return []

    async def search_topic_near(
        self,
        query: str,
        latitude: float,
        longitude: float,
        radius_km: float,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
        limit: int = 20,
        min_certainty: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Combined semantic entity search + geo-radius filter via cross-reference.

        Performs a single Weaviate query that:
        1. Runs near_text vector search on EntityIndex
        2. Filters via the 'locations' cross-ref to require at least one
           LocationIndex object with geo_location within the radius
        3. Returns entities with their matching locations inline

        Example: search_topic_near('plumbers', 37.78, -122.42, 10)

        Args:
            query: Free-text topic query (vectorized)
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Radius in kilometers
            type_key: Optional entity type filter
            category_key: Optional category filter
            identifier_value: Optional identifier value filter
            identifier_namespace: Optional identifier namespace (requires identifier_value)
            limit: Max results
            min_certainty: Minimum certainty threshold (0-1)

        Returns:
            List of entity dicts with 'locations' list and score.
        """
        try:
            from weaviate.classes.query import Filter, GeoCoordinate, QueryReference

            # Build entity-level filters
            filter_parts = []
            filter_parts.append(Filter.by_property("status").equal("active"))
            if type_key:
                filter_parts.append(Filter.by_property("type_key").equal(type_key))
            if category_key:
                filter_parts.append(Filter.by_property("category_keys").contains_any([category_key]))
            if identifier_value:
                if identifier_namespace:
                    composite_key = f"{identifier_namespace}:{identifier_value}"
                    filter_parts.append(Filter.by_property("identifier_keys").contains_any([composite_key]))
                else:
                    filter_parts.append(Filter.by_property("identifier_values").contains_any([identifier_value]))

            # Cross-reference geo filter: Entity → locations → geo_location
            filter_parts.append(
                Filter.by_ref("locations").by_property("geo_location").within_geo_range(
                    coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
                    distance=radius_km * 1000,
                )
            )

            combined_filter = filter_parts[0]
            for f in filter_parts[1:]:
                combined_filter = combined_filter & f

            # Include location properties via cross-reference return
            location_ref = QueryReference(
                link_on="locations",
                return_properties=[
                    "location_id", "location_name", "location_type_key",
                    "formatted_address", "address_line_1", "address_line_2",
                    "locality", "admin_area_1",
                    "country_code", "postal_code", "geo_location", "is_primary",
                ],
            )

            response = await self.collection.query.near_text(
                query=query,
                filters=combined_filter,
                limit=limit,
                certainty=min_certainty,
                return_metadata=wvq.MetadataQuery(distance=True, certainty=True),
                return_references=[location_ref],
            )

            results = []
            for obj in response.objects:
                props = obj.properties
                # Extract locations from cross-reference
                locations = []
                if obj.references and "locations" in obj.references:
                    for loc_obj in obj.references["locations"].objects:
                        lp = loc_obj.properties
                        geo = lp.get('geo_location')
                        locations.append({
                            "location_id": int(lp.get("location_id", 0)),
                            "location_name": lp.get("location_name"),
                            "location_type_key": lp.get("location_type_key"),
                            "formatted_address": lp.get("formatted_address"),
                            "address_line_1": lp.get("address_line_1"),
                            "address_line_2": lp.get("address_line_2"),
                            "locality": lp.get("locality"),
                            "admin_area_1": lp.get("admin_area_1"),
                            "country_code": lp.get("country_code"),
                            "postal_code": lp.get("postal_code"),
                            "latitude": getattr(geo, 'latitude', None) if geo else None,
                            "longitude": getattr(geo, 'longitude', None) if geo else None,
                            "is_primary": lp.get("is_primary", False),
                        })

                result = {
                    "entity_id": props.get("entity_id"),
                    "primary_name": props.get("primary_name"),
                    "description": props.get("description"),
                    "type_key": props.get("type_key"),
                    "type_label": props.get("type_label"),
                    "country": props.get("country"),
                    "region": props.get("region"),
                    "locality": props.get("locality"),
                    "category_keys": props.get("category_keys", []),
                    "score": obj.metadata.certainty if obj.metadata.certainty else 0.0,
                    "distance": obj.metadata.distance if obj.metadata.distance else 0.0,
                    "locations": locations,
                }
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Weaviate topic-near search failed: {e}")
            return []

    async def search_entities_near(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        type_key: Optional[str] = None,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Find entities that have at least one location within a radius.

        Uses the Entity→Location cross-reference with a geo filter.
        No vector search — returns entities ordered by the collection default.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Radius in kilometers
            type_key: Optional entity type filter
            identifier_value: Optional identifier value filter
            identifier_namespace: Optional identifier namespace (requires identifier_value)
            limit: Max results

        Returns:
            List of entity dicts with 'locations' list.
        """
        try:
            from weaviate.classes.query import Filter, GeoCoordinate, QueryReference

            filter_parts = []
            filter_parts.append(Filter.by_property("status").equal("active"))
            if type_key:
                filter_parts.append(Filter.by_property("type_key").equal(type_key))
            if identifier_value:
                if identifier_namespace:
                    composite_key = f"{identifier_namespace}:{identifier_value}"
                    filter_parts.append(Filter.by_property("identifier_keys").contains_any([composite_key]))
                else:
                    filter_parts.append(Filter.by_property("identifier_values").contains_any([identifier_value]))

            # Cross-reference geo filter
            filter_parts.append(
                Filter.by_ref("locations").by_property("geo_location").within_geo_range(
                    coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
                    distance=radius_km * 1000,
                )
            )

            combined_filter = filter_parts[0]
            for f in filter_parts[1:]:
                combined_filter = combined_filter & f

            location_ref = QueryReference(
                link_on="locations",
                return_properties=[
                    "location_id", "location_name", "location_type_key",
                    "formatted_address", "address_line_1", "address_line_2",
                    "locality", "admin_area_1",
                    "country_code", "postal_code", "geo_location", "is_primary",
                ],
            )

            response = await self.collection.query.fetch_objects(
                filters=combined_filter,
                limit=limit,
                return_references=[location_ref],
            )

            results = []
            for obj in response.objects:
                props = obj.properties
                locations = []
                if obj.references and "locations" in obj.references:
                    for loc_obj in obj.references["locations"].objects:
                        lp = loc_obj.properties
                        geo = lp.get('geo_location')
                        locations.append({
                            "location_id": int(lp.get("location_id", 0)),
                            "location_name": lp.get("location_name"),
                            "location_type_key": lp.get("location_type_key"),
                            "formatted_address": lp.get("formatted_address"),
                            "address_line_1": lp.get("address_line_1"),
                            "address_line_2": lp.get("address_line_2"),
                            "locality": lp.get("locality"),
                            "admin_area_1": lp.get("admin_area_1"),
                            "country_code": lp.get("country_code"),
                            "postal_code": lp.get("postal_code"),
                            "latitude": getattr(geo, 'latitude', None) if geo else None,
                            "longitude": getattr(geo, 'longitude', None) if geo else None,
                            "is_primary": lp.get("is_primary", False),
                        })

                results.append({
                    "entity_id": props.get("entity_id"),
                    "primary_name": props.get("primary_name"),
                    "description": props.get("description"),
                    "type_key": props.get("type_key"),
                    "type_label": props.get("type_label"),
                    "country": props.get("country"),
                    "region": props.get("region"),
                    "locality": props.get("locality"),
                    "locations": locations,
                })

            return results

        except Exception as e:
            logger.error(f"Weaviate entities-near search failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------

    async def get_status(self) -> Dict[str, Any]:
        """Get status info about the Weaviate collections."""
        await self._ensure_connected()
        try:
            entity_info = {"exists": False, "object_count": 0}
            location_info = {"exists": False, "object_count": 0}

            if await self.client.collections.exists(self.collection_name):
                agg = await self.collection.aggregate.over_all(total_count=True)
                entity_info = {
                    "exists": True,
                    "collection_name": self.collection_name,
                    "object_count": agg.total_count,
                }
                try:
                    cfg = await self.collection.config.get()
                    entity_info["properties"] = [p.name for p in cfg.properties]
                    entity_info["references"] = [r.name for r in cfg.references]
                    entity_info["vectorizer"] = str(cfg.vectorizer_config) if cfg.vectorizer_config else "none"
                except Exception:
                    pass

            if await self.client.collections.exists(self.location_collection_name):
                agg = await self.location_collection.aggregate.over_all(total_count=True)
                location_info = {
                    "exists": True,
                    "collection_name": self.location_collection_name,
                    "object_count": agg.total_count,
                }
                try:
                    cfg = await self.location_collection.config.get()
                    location_info["properties"] = [p.name for p in cfg.properties]
                    location_info["references"] = [r.name for r in cfg.references]
                    location_info["vectorizer"] = str(cfg.vectorizer_config) if cfg.vectorizer_config else "none"
                except Exception:
                    pass

            return {
                "entity_index": entity_info,
                "location_index": location_info,
            }
        except Exception as e:
            logger.error(f"Failed to get Weaviate status: {e}")
            return {"entity_index": {"exists": False, "error": str(e)},
                    "location_index": {"exists": False, "error": str(e)}}

    async def list_all_collections(self) -> List[Dict[str, Any]]:
        """List all collections on the Weaviate instance with basic stats."""
        await self._ensure_connected()
        results = []
        try:
            all_collections = await self.client.collections.list_all()
            for name, col_config in all_collections.items():
                info = {"name": name}
                try:
                    col = self.client.collections.use(name)
                    agg = await col.aggregate.over_all(total_count=True)
                    info["object_count"] = agg.total_count
                except Exception:
                    info["object_count"] = "?"
                try:
                    info["properties"] = len(col_config.properties)
                    info["references"] = len(col_config.references)
                except Exception:
                    pass
                results.append(info)
        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filters(
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
    ):
        """Build Weaviate filter chain for EntityIndex."""
        from weaviate.classes.query import Filter, GeoCoordinate

        parts = []

        # Always filter for active status
        parts.append(Filter.by_property("status").equal("active"))

        if type_key:
            parts.append(Filter.by_property("type_key").equal(type_key))
        if category_key:
            parts.append(Filter.by_property("category_keys").contains_any([category_key]))
        if country:
            parts.append(Filter.by_property("country").equal(country))
        if region:
            parts.append(Filter.by_property("region").equal(region))
        if locality:
            parts.append(Filter.by_property("locality").equal(locality))

        # Identifier filter
        if identifier_value:
            if identifier_namespace:
                # Exact namespace:value lookup
                composite_key = f"{identifier_namespace}:{identifier_value}"
                parts.append(Filter.by_property("identifier_keys").contains_any([composite_key]))
            else:
                # Value across all namespaces
                parts.append(Filter.by_property("identifier_values").contains_any([identifier_value]))

        # Geo range filter (radius search on entity-level coords)
        if latitude is not None and longitude is not None and radius_km is not None:
            parts.append(
                Filter.by_property("geo_location").within_geo_range(
                    coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
                    distance=radius_km * 1000,  # convert km to meters
                )
            )

        if not parts:
            return None

        combined = parts[0]
        for f in parts[1:]:
            combined = combined & f
        return combined

    @staticmethod
    def _build_location_filters(
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        location_type_key: Optional[str] = None,
        country_code: Optional[str] = None,
        locality: Optional[str] = None,
        admin_area_1: Optional[str] = None,
        postal_code: Optional[str] = None,
        location_name: Optional[str] = None,
        entity_id: Optional[str] = None,
        is_primary: Optional[bool] = None,
        external_location_id: Optional[str] = None,
    ):
        """Build Weaviate filter chain for LocationIndex."""
        from weaviate.classes.query import Filter, GeoCoordinate

        parts = []
        parts.append(Filter.by_property("status").equal("active"))
        if latitude is not None and longitude is not None and radius_km is not None:
            parts.append(
                Filter.by_property("geo_location").within_geo_range(
                    coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
                    distance=radius_km * 1000,
                )
            )
        if location_type_key:
            parts.append(Filter.by_property("location_type_key").equal(location_type_key))
        if country_code:
            parts.append(Filter.by_property("country_code").equal(country_code))
        if locality:
            parts.append(Filter.by_property("locality").equal(locality))
        if admin_area_1:
            parts.append(Filter.by_property("admin_area_1").equal(admin_area_1))
        if postal_code:
            parts.append(Filter.by_property("postal_code").equal(postal_code))
        if location_name:
            parts.append(Filter.by_property("location_name").equal(location_name))
        if entity_id:
            parts.append(Filter.by_property("entity_id").equal(entity_id))
        if is_primary is not None:
            parts.append(Filter.by_property("is_primary").equal(is_primary))
        if external_location_id:
            parts.append(Filter.by_property("external_location_id").equal(external_location_id))

        combined = parts[0]
        for f in parts[1:]:
            combined = combined & f
        return combined

    async def close(self):
        """Close the Weaviate client connection."""
        try:
            self._stop_refresh.set()
            await self.client.close()
            logger.info("Weaviate client closed")
        except Exception as e:
            logger.warning(f"Error closing Weaviate client: {e}")
