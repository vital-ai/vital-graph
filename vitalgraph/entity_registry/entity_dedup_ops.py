"""
Dedup operations mixin for the Entity Registry.

Near-duplicate detection and cross-worker dedup sync via PostgreSQL NOTIFY.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .entity_dedup import EntityDedupIndex

if TYPE_CHECKING:
    import asyncpg
    from vitalgraph.signal.signal_manager import SignalManager

logger = logging.getLogger(__name__)


class DedupMixin:
    """Near-duplicate detection and cross-worker dedup sync methods."""

    pool: asyncpg.Pool
    dedup_index: Optional[EntityDedupIndex]
    signal_manager: Optional[SignalManager]

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]: ...

    async def find_similar(
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
        For persistent backends (MemoryDB), fetches missing entity scoring data
        from PostgreSQL on demand rather than caching the entire database.

        Returns:
            List of scored candidate dicts, or empty list if dedup is not enabled.
        """
        if not self.dedup_index:
            return []

        entity = {
            'primary_name': name,
            'country': country,
            'region': region,
            'locality': locality,
        }

        # Phase 1: Get candidate IDs from LSH (hits MemoryDB)
        candidate_ids = self.dedup_index.get_candidate_ids(entity)
        if not candidate_ids:
            logger.info("find_similar(%s): 0 LSH candidates", name)
            return []

        # Phase 1.5: Fetch candidate entity data from PG
        candidate_data = await self._fetch_entities_for_scoring(list(candidate_ids))
        logger.info("find_similar(%s): %d LSH candidates, %d fetched from PG",
                    name, len(candidate_ids), len(candidate_data))

        # Phase 2: Score with RapidFuzz
        results = self.dedup_index.score_candidates(
            entity, candidate_data,
            limit=limit, min_score=min_score, type_key=type_key,
        )
        logger.info("find_similar(%s): %d results (min_score=%.1f)",
                    name, len(results), min_score)
        return results

    async def _fetch_entities_for_scoring(self, entity_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch-fetch entity scoring data from PostgreSQL.

        Returns:
            Mapping of entity_id → dict with primary_name, type_key,
            alias_names, country, region, locality.
        """
        if not entity_ids:
            return {}
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT e.entity_id, e.primary_name, et.type_key, "
                "e.country, e.region, e.locality, ea.alias_name "
                "FROM entity e "
                "LEFT JOIN entity_type et ON et.type_id = e.entity_type_id "
                "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                "AND ea.status != 'retracted' "
                "WHERE e.entity_id = ANY($1) AND e.status != 'deleted'",
                entity_ids,
            )

        entities: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            eid = row['entity_id']
            if eid not in entities:
                entities[eid] = {
                    'primary_name': row['primary_name'],
                    'type_key': row['type_key'],
                    'alias_names': [],
                    'country': row['country'],
                    'region': row['region'],
                    'locality': row['locality'],
                }
            alias = row['alias_name']
            if alias:
                entities[eid]['alias_names'].append(alias)

        return entities

    async def find_duplicates_for_entity(
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

        exclude_ids = {entity.get('entity_id')}
        candidate_ids = self.dedup_index.get_candidate_ids(entity)
        if not candidate_ids:
            return []

        candidate_data = await self._fetch_entities_for_scoring(list(candidate_ids))

        return self.dedup_index.score_candidates(
            entity, candidate_data,
            limit=limit, min_score=min_score, exclude_ids=exclude_ids,
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
