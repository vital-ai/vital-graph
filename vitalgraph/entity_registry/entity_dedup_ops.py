"""
Dedup operations mixin for the Entity Registry.

Near-duplicate detection and cross-worker dedup sync via PostgreSQL NOTIFY.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class DedupMixin:
    """Near-duplicate detection and cross-worker dedup sync methods."""

    def find_similar(
        self,
        name: str,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        type_key: Optional[str] = None,
        limit: int = 10,
        min_score: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """Find entities similar to the given name/location.

        Uses the MinHash LSH index for candidate blocking and RapidFuzz for scoring.

        Returns:
            List of scored candidate dicts, or empty list if dedup is not enabled.
        """
        if not self.dedup_index:
            return []
        return self.dedup_index.find_similar_by_name(
            name=name, country=country, region=region, locality=locality,
            type_key=type_key, limit=limit, min_score=min_score,
        )

    def find_duplicates_for_entity(
        self,
        entity: Dict[str, Any],
        limit: int = 5,
        min_score: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """Find potential duplicates for an existing entity.

        Returns:
            Scored candidates excluding the entity itself.
        """
        if not self.dedup_index:
            return []
        return self.dedup_index.find_similar(
            entity, limit=limit, min_score=min_score,
            exclude_ids={entity.get('entity_id')},
        )

    # ------------------------------------------------------------------
    # Cross-worker dedup sync via PostgreSQL NOTIFY
    # ------------------------------------------------------------------

    async def _notify_dedup_change(self, action: str, entity_id: str):
        """Send a pg NOTIFY so other workers update their local dedup index.

        Args:
            action: 'add' or 'remove'
            entity_id: The entity that changed.
        """
        if not self.signal_manager:
            return
        try:
            from vitalgraph.signal.signal_manager import CHANNEL_ENTITY_DEDUP
            payload = json.dumps({'action': action, 'entity_id': entity_id})
            await self.signal_manager._send_notification(CHANNEL_ENTITY_DEDUP, payload)
        except Exception as e:
            logger.debug(f"Dedup notify failed (non-critical): {e}")

    async def _notify_dedup_reload(self):
        """Send a pg NOTIFY telling all workers to do a full dedup index rebuild."""
        if not self.signal_manager:
            return
        try:
            from vitalgraph.signal.signal_manager import CHANNEL_ENTITY_DEDUP
            payload = json.dumps({'action': 'reload_full'})
            await self.signal_manager._send_notification(CHANNEL_ENTITY_DEDUP, payload)
            logger.info("Sent reload_full notification to all workers")
        except Exception as e:
            logger.warning(f"Dedup reload notify failed: {e}")

    async def _handle_dedup_notification(self, data: dict):
        """Callback for incoming dedup notifications from other workers.

        Re-fetches the entity from PostgreSQL and updates the local
        in-memory dedup index. Safe to call even if this instance
        already applied the change (add_entity is idempotent,
        remove_entity is a no-op for missing IDs).

        Supports actions: 'add', 'remove', 'reload_full'.
        """
        if not self.dedup_index:
            return
        action = data.get('action')

        try:
            if action == 'reload_full':
                count = await self.dedup_index.initialize(self.pool)
                logger.info(f"Dedup sync: full reload complete — {count} entities indexed")
                return

            entity_id = data.get('entity_id')
            if not entity_id:
                return

            if action == 'remove':
                self.dedup_index.remove_entity(entity_id)
                logger.debug(f"Dedup sync: removed {entity_id}")
            elif action == 'add':
                entity = await self.get_entity(entity_id)
                if entity:
                    self.dedup_index.add_entity(entity_id, entity)
                    logger.debug(f"Dedup sync: added/updated {entity_id}")
                else:
                    # Entity may have been deleted between notify and handler
                    self.dedup_index.remove_entity(entity_id)
        except Exception as e:
            logger.warning(f"Dedup sync error for {data}: {e}")
