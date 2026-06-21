"""
Entity Registry Vector/FTS/Geo Populator.

Reads from the entity registry's dedicated relational tables and populates
the companion pgvector, FTS, and PostGIS tables. Replaces Weaviate sync.

Supports:
  - Full rebuild (all entities + locations)
  - Incremental sync (single entity or location)
  - Delete (remove entity/location from vector/FTS/geo)
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

import asyncpg

from vitalgraph.entity_registry.entity_registry_vector_schema import (
    ENTITY_VECTOR_TABLE, LOCATION_VECTOR_TABLE, GEO_TABLE,
    FTS_ENTITY_TABLE, FTS_LOCATION_TABLE, DIMENSIONS,
)
from vitalgraph.vectorization.registry import get_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UUID generation (deterministic, matches entity_weaviate_schema.py)
# ---------------------------------------------------------------------------

_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def entity_id_to_uuid(entity_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"vitalgraph:entity:{entity_id}")


def location_id_to_uuid(location_id: int) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"vitalgraph:location:{location_id}")


def _vec_to_str(embedding: List[float]) -> str:
    """Convert embedding list to pgvector literal string '[0.1,0.2,...]'."""
    return '[' + ','.join(str(x) for x in embedding) + ']'


# ---------------------------------------------------------------------------
# Search text builders (hardcoded — same logic as entity_weaviate_schema.py)
# ---------------------------------------------------------------------------

def build_entity_search_text(entity: dict) -> str:
    """Build composite search text for an entity.

    Format: "{primary_name}. {type_label}: {type_description}. {description}.
             Categories: {category_labels}. {locality}, {region}, {country}.
             Aliases: {aliases}. Locations: {location_summaries}"
    """
    parts = []
    if entity.get('primary_name'):
        parts.append(entity['primary_name'])
    if entity.get('type_label'):
        type_str = entity['type_label']
        if entity.get('type_description'):
            type_str += f": {entity['type_description']}"
        parts.append(type_str)
    if entity.get('description'):
        parts.append(entity['description'])
    if entity.get('category_labels'):
        parts.append(f"Categories: {entity['category_labels']}")

    # Geography
    geo_parts = []
    for f in ('locality', 'region', 'country'):
        v = entity.get(f)
        if v:
            geo_parts.append(v)
    if geo_parts:
        parts.append(', '.join(geo_parts))

    # Aliases
    if entity.get('aliases_text'):
        parts.append(f"Aliases: {entity['aliases_text']}")

    # Location summaries
    if entity.get('locations_text'):
        parts.append(f"Locations: {entity['locations_text']}")

    return '. '.join(parts)


def build_location_search_text(location: dict) -> str:
    """Build composite search text for a location.

    Format: "{location_name}. {location_type_label}. {description}. {formatted_address}"
    """
    parts = []
    if location.get('location_name'):
        parts.append(location['location_name'])
    if location.get('location_type_label'):
        parts.append(location['location_type_label'])
    if location.get('description'):
        parts.append(location['description'])
    if location.get('formatted_address'):
        parts.append(location['formatted_address'])
    elif location.get('locality') or location.get('country'):
        addr_parts = []
        for f in ('locality', 'admin_area_1', 'country'):
            v = location.get(f)
            if v:
                addr_parts.append(v)
        if addr_parts:
            parts.append(', '.join(addr_parts))
    return '. '.join(parts)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class PopulateStats:
    entities_processed: int = 0
    entities_vectorized: int = 0
    locations_processed: int = 0
    locations_vectorized: int = 0
    geo_rows_inserted: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Populator class
# ---------------------------------------------------------------------------

class EntityRegistryVectorPopulator:
    """Populates vector/FTS/geo tables from entity registry relational data."""

    BATCH_SIZE = 50

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._provider = get_provider("vitalsigns", cache_key="entity_registry")

    # ==================================================================
    # Full rebuild
    # ==================================================================

    async def full_rebuild(self) -> PopulateStats:
        """Rebuild all vector/FTS/geo data from scratch.

        Truncates target tables and re-populates from entity registry source tables.
        """
        stats = PopulateStats()
        start = time.time()

        async with self.pool.acquire() as conn:
            # Truncate target tables
            await conn.execute(f"TRUNCATE {ENTITY_VECTOR_TABLE}")
            await conn.execute(f"TRUNCATE {LOCATION_VECTOR_TABLE}")
            await conn.execute(f"TRUNCATE {GEO_TABLE}")
            await conn.execute(f"TRUNCATE {FTS_ENTITY_TABLE}")
            await conn.execute(f"TRUNCATE {FTS_LOCATION_TABLE}")

        # Process entities
        await self._rebuild_entities(stats)
        # Process locations
        await self._rebuild_locations(stats)

        stats.elapsed_seconds = time.time() - start
        logger.info(
            "Full rebuild complete: %d entities, %d locations, %d geo rows (%.1fs)",
            stats.entities_vectorized, stats.locations_vectorized,
            stats.geo_rows_inserted, stats.elapsed_seconds,
        )
        return stats

    async def _rebuild_entities(self, stats: PopulateStats):
        """Fetch all active entities with denormalized data and vectorize."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT e.entity_id, e.primary_name, e.description,
                       e.country, e.region, e.locality, e.website,
                       e.latitude, e.longitude, e.status,
                       et.type_key, et.type_label, et.type_description,
                       (SELECT string_agg(a.alias_name, '|')
                        FROM entity_alias a
                        WHERE a.entity_id = e.entity_id AND a.status = 'active'
                       ) AS aliases_text,
                       (SELECT string_agg(c.category_label, '|')
                        FROM entity_category_map ecm
                        JOIN category c ON c.category_id = ecm.category_id
                        WHERE ecm.entity_id = e.entity_id AND ecm.status = 'active'
                       ) AS category_labels,
                       (SELECT string_agg(
                           COALESCE(el.location_name, '') || ': ' ||
                           COALESCE(el.formatted_address, COALESCE(el.locality, '') || ', ' || COALESCE(el.country, '')),
                           '; '
                        )
                        FROM entity_location el
                        WHERE el.entity_id = e.entity_id AND el.status = 'active'
                       ) AS locations_text
                FROM entity e
                JOIN entity_type et ON et.type_id = e.entity_type_id
                WHERE e.status = 'active'
                ORDER BY e.entity_id
            """)

        # Process in batches
        for i in range(0, len(rows), self.BATCH_SIZE):
            batch = rows[i:i + self.BATCH_SIZE]
            await self._process_entity_batch(batch, stats)

    async def _process_entity_batch(self, rows: list, stats: PopulateStats):
        """Vectorize and insert a batch of entities."""
        texts = []
        records = []

        for row in rows:
            entity_dict = dict(row)
            search_text = build_entity_search_text(entity_dict)
            entity_id = entity_dict['entity_id']
            subject_uuid = entity_id_to_uuid(entity_id)

            texts.append(search_text)
            records.append((subject_uuid, entity_id, search_text, entity_dict))
            stats.entities_processed += 1

        # Vectorize batch
        try:
            embeddings = await self._provider.vectorize_texts(texts)
        except Exception as e:
            logger.error("Vectorization failed for batch: %s", e)
            stats.errors += len(records)
            return

        # Insert into vector + FTS tables
        async with self.pool.acquire() as conn:
            # Vector table
            await conn.executemany(f"""
                INSERT INTO {ENTITY_VECTOR_TABLE} (subject_uuid, entity_id, embedding, search_text, updated_time)
                VALUES ($1, $2, $3::vector, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (subject_uuid) DO UPDATE
                SET embedding = EXCLUDED.embedding, search_text = EXCLUDED.search_text,
                    updated_time = CURRENT_TIMESTAMP
            """, [
                (str(rec[0]), rec[1], _vec_to_str(embeddings[idx]), rec[2])
                for idx, rec in enumerate(records)
            ])

            # FTS table
            await conn.executemany(f"""
                INSERT INTO {FTS_ENTITY_TABLE} (subject_uuid, entity_id, search_text, updated_time)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (subject_uuid) DO UPDATE
                SET search_text = EXCLUDED.search_text, updated_time = CURRENT_TIMESTAMP
            """, [
                (str(rec[0]), rec[1], rec[2])
                for rec in records
            ])

            # Geo table (entity-level coordinates)
            geo_records = []
            for idx, rec in enumerate(records):
                entity_dict = rec[3]
                lat = entity_dict.get('latitude')
                lon = entity_dict.get('longitude')
                if lat is not None and lon is not None:
                    geo_records.append((
                        str(rec[0]), 'entity', rec[1], rec[1],
                        lat, lon,
                    ))

            if geo_records:
                await conn.executemany(f"""
                    INSERT INTO {GEO_TABLE}
                        (subject_uuid, source_type, source_id, entity_id, location, latitude, longitude, updated_time)
                    VALUES ($1, $2, $3, $4,
                            ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography,
                            $5, $6, CURRENT_TIMESTAMP)
                    ON CONFLICT (subject_uuid, source_type) DO UPDATE
                    SET location = EXCLUDED.location, latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude, updated_time = CURRENT_TIMESTAMP
                """, geo_records)
                stats.geo_rows_inserted += len(geo_records)

        stats.entities_vectorized += len(records)

    async def _rebuild_locations(self, stats: PopulateStats):
        """Fetch all active locations and vectorize."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT el.location_id, el.entity_id, el.location_name, el.description,
                       el.address_line_1, el.address_line_2,
                       el.locality, el.admin_area_1, el.admin_area_2,
                       el.country, el.country_code, el.postal_code,
                       el.formatted_address, el.latitude, el.longitude,
                       el.is_primary, el.status,
                       elt.type_key AS location_type_key,
                       elt.type_label AS location_type_label
                FROM entity_location el
                JOIN entity_location_type elt ON elt.location_type_id = el.location_type_id
                WHERE el.status = 'active'
                ORDER BY el.location_id
            """)

        for i in range(0, len(rows), self.BATCH_SIZE):
            batch = rows[i:i + self.BATCH_SIZE]
            await self._process_location_batch(batch, stats)

    async def _process_location_batch(self, rows: list, stats: PopulateStats):
        """Vectorize and insert a batch of locations."""
        texts = []
        records = []

        for row in rows:
            loc_dict = dict(row)
            search_text = build_location_search_text(loc_dict)
            location_id = loc_dict['location_id']
            entity_id = loc_dict['entity_id']
            subject_uuid = location_id_to_uuid(location_id)

            texts.append(search_text)
            records.append((subject_uuid, location_id, entity_id, search_text, loc_dict))
            stats.locations_processed += 1

        # Vectorize batch
        try:
            embeddings = await self._provider.vectorize_texts(texts)
        except Exception as e:
            logger.error("Location vectorization failed for batch: %s", e)
            stats.errors += len(records)
            return

        async with self.pool.acquire() as conn:
            # Location vector table
            await conn.executemany(f"""
                INSERT INTO {LOCATION_VECTOR_TABLE}
                    (subject_uuid, location_id, entity_id, embedding, search_text, updated_time)
                VALUES ($1, $2, $3, $4::vector, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (subject_uuid) DO UPDATE
                SET embedding = EXCLUDED.embedding, search_text = EXCLUDED.search_text,
                    updated_time = CURRENT_TIMESTAMP
            """, [
                (str(rec[0]), rec[1], rec[2], _vec_to_str(embeddings[idx]), rec[3])
                for idx, rec in enumerate(records)
            ])

            # FTS location table
            await conn.executemany(f"""
                INSERT INTO {FTS_LOCATION_TABLE}
                    (subject_uuid, location_id, entity_id, search_text, updated_time)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (subject_uuid) DO UPDATE
                SET search_text = EXCLUDED.search_text, updated_time = CURRENT_TIMESTAMP
            """, [
                (str(rec[0]), rec[1], rec[2], rec[3])
                for rec in records
            ])

            # Geo table (location-level coordinates)
            geo_records = []
            for rec in records:
                loc_dict = rec[4]
                lat = loc_dict.get('latitude')
                lon = loc_dict.get('longitude')
                if lat is not None and lon is not None:
                    geo_records.append((
                        str(rec[0]), 'location', str(rec[1]), rec[2],
                        lat, lon,
                    ))

            if geo_records:
                await conn.executemany(f"""
                    INSERT INTO {GEO_TABLE}
                        (subject_uuid, source_type, source_id, entity_id, location, latitude, longitude, updated_time)
                    VALUES ($1, $2, $3, $4,
                            ST_SetSRID(ST_MakePoint($6, $5), 4326)::geography,
                            $5, $6, CURRENT_TIMESTAMP)
                    ON CONFLICT (subject_uuid, source_type) DO UPDATE
                    SET location = EXCLUDED.location, latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude, updated_time = CURRENT_TIMESTAMP
                """, geo_records)
                stats.geo_rows_inserted += len(geo_records)

        stats.locations_vectorized += len(records)

    # ==================================================================
    # Incremental sync (single entity)
    # ==================================================================

    async def sync_entity(self, entity_id: str):
        """Re-vectorize a single entity (after create/update)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT e.entity_id, e.primary_name, e.description,
                       e.country, e.region, e.locality, e.website,
                       e.latitude, e.longitude, e.status,
                       et.type_key, et.type_label, et.type_description,
                       (SELECT string_agg(a.alias_name, '|')
                        FROM entity_alias a
                        WHERE a.entity_id = e.entity_id AND a.status = 'active'
                       ) AS aliases_text,
                       (SELECT string_agg(c.category_label, '|')
                        FROM entity_category_map ecm
                        JOIN category c ON c.category_id = ecm.category_id
                        WHERE ecm.entity_id = e.entity_id AND ecm.status = 'active'
                       ) AS category_labels,
                       (SELECT string_agg(
                           COALESCE(el.location_name, '') || ': ' ||
                           COALESCE(el.formatted_address, COALESCE(el.locality, '') || ', ' || COALESCE(el.country, '')),
                           '; '
                        )
                        FROM entity_location el
                        WHERE el.entity_id = e.entity_id AND el.status = 'active'
                       ) AS locations_text
                FROM entity e
                JOIN entity_type et ON et.type_id = e.entity_type_id
                WHERE e.entity_id = $1
            """, entity_id)

        if not row:
            # Entity not found or deleted — remove from indexes
            await self.delete_entity(entity_id)
            return

        if row['status'] != 'active':
            await self.delete_entity(entity_id)
            return

        stats = PopulateStats()
        await self._process_entity_batch([row], stats)
        logger.debug("Synced entity %s: vec=%d, geo=%d",
                     entity_id, stats.entities_vectorized, stats.geo_rows_inserted)

    async def sync_location(self, location_id: int):
        """Re-vectorize a single location (after create/update)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT el.location_id, el.entity_id, el.location_name, el.description,
                       el.address_line_1, el.address_line_2,
                       el.locality, el.admin_area_1, el.admin_area_2,
                       el.country, el.country_code, el.postal_code,
                       el.formatted_address, el.latitude, el.longitude,
                       el.is_primary, el.status,
                       elt.type_key AS location_type_key,
                       elt.type_label AS location_type_label
                FROM entity_location el
                JOIN entity_location_type elt ON elt.location_type_id = el.location_type_id
                WHERE el.location_id = $1
            """, location_id)

        if not row:
            await self.delete_location(location_id)
            return

        if row['status'] != 'active':
            await self.delete_location(location_id)
            return

        stats = PopulateStats()
        await self._process_location_batch([row], stats)
        logger.debug("Synced location %d: vec=%d, geo=%d",
                     location_id, stats.locations_vectorized, stats.geo_rows_inserted)

    # ==================================================================
    # Delete
    # ==================================================================

    async def delete_entity(self, entity_id: str):
        """Remove entity from all vector/FTS/geo tables."""
        subject_uuid = str(entity_id_to_uuid(entity_id))
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {ENTITY_VECTOR_TABLE} WHERE subject_uuid = $1", subject_uuid)
            await conn.execute(
                f"DELETE FROM {FTS_ENTITY_TABLE} WHERE subject_uuid = $1", subject_uuid)
            await conn.execute(
                f"DELETE FROM {GEO_TABLE} WHERE subject_uuid = $1 AND source_type = 'entity'",
                subject_uuid)
        logger.debug("Deleted entity %s from vector/FTS/geo", entity_id)

    async def delete_location(self, location_id: int):
        """Remove location from all vector/FTS/geo tables."""
        subject_uuid = str(location_id_to_uuid(location_id))
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {LOCATION_VECTOR_TABLE} WHERE subject_uuid = $1", subject_uuid)
            await conn.execute(
                f"DELETE FROM {FTS_LOCATION_TABLE} WHERE subject_uuid = $1", subject_uuid)
            await conn.execute(
                f"DELETE FROM {GEO_TABLE} WHERE subject_uuid = $1 AND source_type = 'location'",
                subject_uuid)
        logger.debug("Deleted location %d from vector/FTS/geo", location_id)

    async def delete_entity_all(self, entity_id: str):
        """Remove entity AND all its locations from vector/FTS/geo tables."""
        await self.delete_entity(entity_id)
        async with self.pool.acquire() as conn:
            # Remove all locations for this entity
            await conn.execute(
                f"DELETE FROM {LOCATION_VECTOR_TABLE} WHERE entity_id = $1", entity_id)
            await conn.execute(
                f"DELETE FROM {FTS_LOCATION_TABLE} WHERE entity_id = $1", entity_id)
            await conn.execute(
                f"DELETE FROM {GEO_TABLE} WHERE entity_id = $1", entity_id)
        logger.debug("Deleted entity %s + all locations from vector/FTS/geo", entity_id)
