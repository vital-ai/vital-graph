"""
Weaviate sync helper mixin for the Entity Registry.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WeaviateMixin:
    """Weaviate upsert/delete helper methods for entities and locations."""

    async def _weaviate_upsert_entity(self, entity_id: str):
        """Upsert an entity to Weaviate (non-blocking, logs errors).

        Fetches the full entity with aliases and categories, then upserts.
        Inserts all data objects first (entity + locations), then sets
        cross-references once both sides exist in Weaviate.
        """
        if not self.weaviate_index:
            return
        try:
            entity = await self.get_entity(entity_id)
            if not entity:
                return
            # Fetch categories and identifiers for this entity
            entity['categories'] = await self.list_entity_categories(entity_id)
            entity['identifiers'] = await self.list_identifiers(entity_id)

            # Step 1: Insert entity data
            await self.weaviate_index.upsert_entity(entity)

            # Step 2: Insert location data (no cross-refs yet)
            locations = entity.get('locations', [])
            loc_ids = []
            if locations:
                for loc in locations:
                    if loc.get('location_id'):
                        await self.weaviate_index.upsert_location(loc)
                        loc_ids.append(loc['location_id'])

            # Step 3: Set cross-refs now that both entity and locations exist
            if loc_ids:
                await self.weaviate_index.set_entity_location_refs(entity_id, loc_ids)
                for lid in loc_ids:
                    await self.weaviate_index.set_location_entity_ref(lid, entity_id)
        except Exception as e:
            logger.warning(f"Weaviate upsert failed for {entity_id} (non-critical): {e}")

    async def _weaviate_delete_entity(self, entity_id: str):
        """Delete an entity from Weaviate (non-blocking, logs errors)."""
        if not self.weaviate_index:
            return
        try:
            await self.weaviate_index.delete_entity(entity_id)
        except Exception as e:
            logger.warning(f"Weaviate delete failed for {entity_id} (non-critical): {e}")

    async def _weaviate_upsert_location(self, location: Dict[str, Any]):
        """Upsert a location to Weaviate LocationIndex (non-blocking, logs errors).

        Also refreshes the Entity→Location cross-refs for the owning entity.
        """
        if not self.weaviate_index:
            return
        try:
            await self.weaviate_index.upsert_location(location)

            # Refresh Entity→Location cross-refs
            entity_id = location.get('entity_id')
            if entity_id:
                entity_locations = await self.list_locations(entity_id)
                loc_ids = [loc['location_id'] for loc in entity_locations if loc.get('location_id')]
                if loc_ids:
                    await self.weaviate_index.set_entity_location_refs(entity_id, loc_ids)
        except Exception as e:
            logger.warning(f"Weaviate location upsert failed for {location.get('location_id')} (non-critical): {e}")

    async def _weaviate_delete_location(self, location_id: int, entity_id: str):
        """Delete a location from Weaviate LocationIndex (non-blocking, logs errors).

        Also refreshes the Entity→Location cross-refs for the owning entity.
        """
        if not self.weaviate_index:
            return
        try:
            await self.weaviate_index.delete_location(location_id)

            # Refresh Entity→Location cross-refs
            if entity_id:
                entity_locations = await self.list_locations(entity_id)
                loc_ids = [loc['location_id'] for loc in entity_locations if loc.get('location_id')]
                await self.weaviate_index.set_entity_location_refs(entity_id, loc_ids)
        except Exception as e:
            logger.warning(f"Weaviate location delete failed for {location_id} (non-critical): {e}")
