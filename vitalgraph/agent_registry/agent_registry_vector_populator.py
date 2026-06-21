"""
Agent Registry Vector/FTS Populator.

Reads from the agent registry's dedicated relational tables and populates
the companion pgvector and FTS tables.

Supports:
  - Full rebuild (all agents)
  - Incremental sync (single agent)
  - Delete (remove agent from vector/FTS)
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

import asyncpg

from vitalgraph.agent_registry.agent_registry_vector_schema import (
    AGENT_VECTOR_TABLE, FTS_AGENT_TABLE,
)
from vitalgraph.vectorization.registry import get_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UUID generation
# ---------------------------------------------------------------------------

_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def agent_id_to_uuid(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"vitalgraph:agent:{agent_id}")


# ---------------------------------------------------------------------------
# Search text builder (hardcoded)
# ---------------------------------------------------------------------------

def build_agent_search_text(agent: dict) -> str:
    """Build composite search text for an agent.

    Format: "{agent_name}. {agent_type_label}: {type_description}. {description}.
             Functions: {function_names}. Capabilities: {capabilities}"
    """
    parts = []
    if agent.get('agent_name'):
        parts.append(agent['agent_name'])
    if agent.get('type_label'):
        type_str = agent['type_label']
        if agent.get('type_description'):
            type_str += f": {agent['type_description']}"
        parts.append(type_str)
    if agent.get('description'):
        parts.append(agent['description'])
    if agent.get('function_names'):
        parts.append(f"Functions: {agent['function_names']}")
    if agent.get('capabilities_text'):
        parts.append(f"Capabilities: {agent['capabilities_text']}")
    return '. '.join(parts)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class PopulateStats:
    agents_processed: int = 0
    agents_vectorized: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Populator class
# ---------------------------------------------------------------------------

class AgentRegistryVectorPopulator:
    """Populates vector/FTS tables from agent registry relational data."""

    BATCH_SIZE = 50

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._provider = get_provider("vitalsigns", cache_key="agent_registry")

    # ==================================================================
    # Full rebuild
    # ==================================================================

    async def full_rebuild(self) -> PopulateStats:
        """Rebuild all vector/FTS data from scratch."""
        stats = PopulateStats()
        start = time.time()

        async with self.pool.acquire() as conn:
            await conn.execute(f"TRUNCATE {AGENT_VECTOR_TABLE}")
            await conn.execute(f"TRUNCATE {FTS_AGENT_TABLE}")

        await self._rebuild_agents(stats)

        stats.elapsed_seconds = time.time() - start
        logger.info(
            "Full rebuild complete: %d agents vectorized (%.1fs)",
            stats.agents_vectorized, stats.elapsed_seconds,
        )
        return stats

    async def _rebuild_agents(self, stats: PopulateStats):
        """Fetch all active agents with denormalized data and vectorize."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT a.agent_id, a.agent_name, a.description,
                       a.agent_uri, a.version, a.status,
                       a.capabilities,
                       at.type_key, at.type_label, at.type_description,
                       (SELECT string_agg(af.function_name, ', ')
                        FROM agent_function af
                        WHERE af.agent_id = a.agent_id AND af.status = 'active'
                       ) AS function_names
                FROM agent a
                JOIN agent_type at ON at.type_id = a.agent_type_id
                WHERE a.status = 'active'
                ORDER BY a.agent_id
            """)

        for i in range(0, len(rows), self.BATCH_SIZE):
            batch = rows[i:i + self.BATCH_SIZE]
            await self._process_agent_batch(batch, stats)

    async def _process_agent_batch(self, rows: list, stats: PopulateStats):
        """Vectorize and insert a batch of agents."""
        texts = []
        records = []

        for row in rows:
            agent_dict = dict(row)
            # Extract capabilities text from JSONB list
            caps = agent_dict.get('capabilities') or []
            if isinstance(caps, list):
                agent_dict['capabilities_text'] = ', '.join(str(c) for c in caps)
            else:
                agent_dict['capabilities_text'] = ''

            search_text = build_agent_search_text(agent_dict)
            agent_id = agent_dict['agent_id']
            subject_uuid = agent_id_to_uuid(agent_id)

            texts.append(search_text)
            records.append((subject_uuid, agent_id, search_text))
            stats.agents_processed += 1

        # Vectorize batch
        try:
            embeddings = await self._provider.vectorize_texts(texts)
        except Exception as e:
            logger.error("Agent vectorization failed for batch: %s", e)
            stats.errors += len(records)
            return

        # Insert into vector + FTS tables
        async with self.pool.acquire() as conn:
            await conn.executemany(f"""
                INSERT INTO {AGENT_VECTOR_TABLE} (subject_uuid, agent_id, embedding, search_text, updated_time)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (subject_uuid) DO UPDATE
                SET embedding = EXCLUDED.embedding, search_text = EXCLUDED.search_text,
                    updated_time = CURRENT_TIMESTAMP
            """, [
                (str(rec[0]), rec[1], embeddings[idx], rec[2])
                for idx, rec in enumerate(records)
            ])

            await conn.executemany(f"""
                INSERT INTO {FTS_AGENT_TABLE} (subject_uuid, agent_id, search_text, updated_time)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (subject_uuid) DO UPDATE
                SET search_text = EXCLUDED.search_text, updated_time = CURRENT_TIMESTAMP
            """, [
                (str(rec[0]), rec[1], rec[2])
                for rec in records
            ])

        stats.agents_vectorized += len(records)

    # ==================================================================
    # Incremental sync
    # ==================================================================

    async def sync_agent(self, agent_id: str):
        """Re-vectorize a single agent (after create/update)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT a.agent_id, a.agent_name, a.description,
                       a.agent_uri, a.version, a.status,
                       a.capabilities,
                       at.type_key, at.type_label, at.type_description,
                       (SELECT string_agg(af.function_name, ', ')
                        FROM agent_function af
                        WHERE af.agent_id = a.agent_id AND af.status = 'active'
                       ) AS function_names
                FROM agent a
                JOIN agent_type at ON at.type_id = a.agent_type_id
                WHERE a.agent_id = $1
            """, agent_id)

        if not row:
            await self.delete_agent(agent_id)
            return

        if row['status'] != 'active':
            await self.delete_agent(agent_id)
            return

        stats = PopulateStats()
        await self._process_agent_batch([row], stats)
        logger.debug("Synced agent %s", agent_id)

    # ==================================================================
    # Delete
    # ==================================================================

    async def delete_agent(self, agent_id: str):
        """Remove agent from vector/FTS tables."""
        subject_uuid = str(agent_id_to_uuid(agent_id))
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {AGENT_VECTOR_TABLE} WHERE subject_uuid = $1", subject_uuid)
            await conn.execute(
                f"DELETE FROM {FTS_AGENT_TABLE} WHERE subject_uuid = $1", subject_uuid)
        logger.debug("Deleted agent %s from vector/FTS", agent_id)
