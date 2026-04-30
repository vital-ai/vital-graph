"""
Weaviate sync helper mixin for the Entity Registry.
"""

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WeaviateMixin:
    """Weaviate upsert/delete helper methods for entities and locations."""

    async def _weaviate_upsert_entity(self, entity_id: str):
        """Upsert an entity to Weaviate (non-blocking, logs errors).

        Fetches the full entity with aliases and categories, then upserts.
        Also ensures all locations exist in LocationIndex before setting
        Entity→Location cross-references.
        """
        if not self.weaviate_index:
            return
        t0 = time.time()
        logger.info(f"[weaviate-ops] upsert entity START entity_id={entity_id}")
        try:
            entity = await self.get_entity(entity_id)
            if not entity:
                logger.warning(f"[weaviate-ops] entity not found for weaviate upsert: {entity_id}")
                return
            # Fetch categories and identifiers for this entity
            entity['categories'] = await self.list_entity_categories(entity_id)
            entity['identifiers'] = await self.list_identifiers(entity_id)
            logger.info(f"[weaviate-ops] entity data fetched: entity_id={entity_id} "
                        f"name={entity.get('primary_name')!r} "
                        f"aliases={len(entity.get('aliases', []))} "
                        f"categories={len(entity.get('categories', []))} "
                        f"locations={len(entity.get('locations', []))} "
                        f"identifiers={len(entity.get('identifiers', []))}")
            await self.weaviate_index.upsert_entity(entity)

            # Ensure all locations exist in LocationIndex, then set cross-refs
            locations = entity.get('locations', [])
            if locations:
                for loc in locations:
                    if loc.get('location_id'):
                        await self.weaviate_index.upsert_location(loc)
                loc_ids = [loc['location_id'] for loc in locations if loc.get('location_id')]
                if loc_ids:
                    await self.weaviate_index.set_entity_location_refs(entity_id, loc_ids)

            elapsed = time.time() - t0
            logger.info(f"[weaviate-ops] upsert entity DONE entity_id={entity_id} ({elapsed:.3f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"[weaviate-ops] upsert entity FAILED entity_id={entity_id} "
                           f"({elapsed:.3f}s): {e}", exc_info=True)

    async def _weaviate_delete_entity(self, entity_id: str):
        """Delete an entity from Weaviate (non-blocking, logs errors)."""
        if not self.weaviate_index:
            return
        t0 = time.time()
        logger.info(f"[weaviate-ops] delete entity START entity_id={entity_id}")
        try:
            await self.weaviate_index.delete_entity(entity_id)
            elapsed = time.time() - t0
            logger.info(f"[weaviate-ops] delete entity DONE entity_id={entity_id} ({elapsed:.3f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"[weaviate-ops] delete entity FAILED entity_id={entity_id} "
                           f"({elapsed:.3f}s): {e}", exc_info=True)

    async def _weaviate_upsert_location(self, location: Dict[str, Any]):
        """Upsert a location to Weaviate LocationIndex (non-blocking, logs errors).

        Also refreshes the Entity→Location cross-refs for the owning entity.
        """
        if not self.weaviate_index:
            return
        loc_id = location.get('location_id', '?')
        entity_id = location.get('entity_id', '?')
        t0 = time.time()
        logger.info(f"[weaviate-ops] upsert location START loc_id={loc_id} entity_id={entity_id}")
        try:
            await self.weaviate_index.upsert_location(location)

            # Refresh Entity→Location cross-refs
            if entity_id and entity_id != '?':
                entity_locations = await self.list_locations(entity_id)
                loc_ids = [loc['location_id'] for loc in entity_locations if loc.get('location_id')]
                if loc_ids:
                    await self.weaviate_index.set_entity_location_refs(entity_id, loc_ids)
                    logger.info(f"[weaviate-ops] refreshed location refs for entity {entity_id}: "
                                f"{len(loc_ids)} locations")

            elapsed = time.time() - t0
            logger.info(f"[weaviate-ops] upsert location DONE loc_id={loc_id} ({elapsed:.3f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"[weaviate-ops] upsert location FAILED loc_id={loc_id} "
                           f"({elapsed:.3f}s): {e}", exc_info=True)

    async def _weaviate_delete_location(self, location_id: int, entity_id: str):
        """Delete a location from Weaviate LocationIndex (non-blocking, logs errors).

        Also refreshes the Entity→Location cross-refs for the owning entity.
        """
        if not self.weaviate_index:
            return
        t0 = time.time()
        logger.info(f"[weaviate-ops] delete location START loc_id={location_id} entity_id={entity_id}")
        try:
            await self.weaviate_index.delete_location(location_id)

            # Refresh Entity→Location cross-refs
            if entity_id:
                entity_locations = await self.list_locations(entity_id)
                loc_ids = [loc['location_id'] for loc in entity_locations if loc.get('location_id')]
                await self.weaviate_index.set_entity_location_refs(entity_id, loc_ids)
                logger.info(f"[weaviate-ops] refreshed location refs for entity {entity_id}: "
                            f"{len(loc_ids)} locations remaining")

            elapsed = time.time() - t0
            logger.info(f"[weaviate-ops] delete location DONE loc_id={location_id} ({elapsed:.3f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"[weaviate-ops] delete location FAILED loc_id={location_id} "
                           f"({elapsed:.3f}s): {e}", exc_info=True)
