"""
PostgreSQL storage backend for the Entity Dedup MinHash LSH index.

Replaces datasketch's Redis/MemoryDB storage with direct asyncpg SQL,
eliminating the Redis dependency entirely. Band hashes are stored in
PostgreSQL tables (entity_dedup_band, entity_dedup_phonetic_band) with
B-tree indexes for fast band lookups.

All operations are natively async — no thread offloading needed.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Table names
TABLE_PRIMARY = 'entity_dedup_band'
TABLE_PHONETIC = 'entity_dedup_phonetic_band'
TABLE_HASH = 'entity_dedup_hash'


def compute_band_ranges(num_perm: int, threshold: float) -> List[Tuple[int, int]]:
    """Compute optimal band ranges for MinHash LSH.

    Uses datasketch's MinHashLSH to determine the optimal band parameters
    (number of bands b and rows per band r) for the given threshold and
    permutation count, then extracts the hashranges.

    Returns:
        List of (start, end) index pairs into the MinHash hashvalues array.
    """
    from datasketch import MinHashLSH
    # Create a temporary in-memory LSH just to extract its hashranges
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    return list(lsh.hashranges)


def compute_band_hash(hashvalues: np.ndarray, start: int, end: int) -> bytes:
    """Compute the band hash for a slice of MinHash hashvalues.

    Replicates datasketch's MinHashLSH._H() logic: SHA1 of the packed
    band values.

    Args:
        hashvalues: The MinHash.hashvalues array (uint32 or uint64).
        start: Start index of the band slice.
        end: End index of the band slice.

    Returns:
        SHA1 digest bytes (20 bytes).
    """
    return hashlib.sha1(hashvalues[start:end].tobytes()).digest()


class PostgreSQLDedupStorage:
    """PostgreSQL-backed storage for MinHash LSH band data.

    Replaces datasketch's Redis/MemoryDB storage with direct SQL,
    eliminating the Redis dependency entirely.

    All methods are async (use asyncpg pool).
    """

    def __init__(self, pool):
        """Initialize with an asyncpg connection pool.

        Args:
            pool: asyncpg.Pool instance (shared with entity registry).
        """
        self.pool = pool

    # ------------------------------------------------------------------
    # Band operations
    # ------------------------------------------------------------------

    async def insert_bands(
        self,
        table: str,
        entries: List[Tuple[int, bytes, str]],
    ):
        """Batch insert band entries for one or more entities.

        Uses a single multi-row INSERT with ON CONFLICT DO NOTHING
        for idempotent inserts (safe to re-run).

        Args:
            table: Table name (TABLE_PRIMARY or TABLE_PHONETIC).
            entries: List of (band_id, band_hash, entity_key) tuples.
        """
        if not entries:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                f"INSERT INTO {table} (band_id, band_hash, entity_key) "
                f"VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                entries,
            )

    async def insert_bands_copy(
        self,
        table: str,
        entries: List[Tuple[int, bytes, str]],
    ):
        """Bulk insert band entries using COPY for maximum throughput.

        Faster than executemany for large batches (>1000 rows).
        Does not handle conflicts — use only on clean tables (after truncate).

        Args:
            table: Table name (TABLE_PRIMARY or TABLE_PHONETIC).
            entries: List of (band_id, band_hash, entity_key) tuples.
        """
        if not entries:
            return
        async with self.pool.acquire() as conn:
            await conn.copy_records_to_table(
                table,
                records=entries,
                columns=['band_id', 'band_hash', 'entity_key'],
            )

    async def query_bands(
        self,
        table: str,
        band_queries: List[Tuple[int, List[bytes]]],
    ) -> Dict[str, int]:
        """Batch band lookup across multiple bands.

        For each (band_id, [hash1, hash2, ...]) pair, finds all entity_keys
        that match any of the hashes in that band. Returns a mapping of
        entity_key → number of bands it matched in.

        This is the core query for candidate retrieval — equivalent to
        datasketch's hashtable.getmany() but done in a single SQL call.

        Args:
            table: Table name (TABLE_PRIMARY or TABLE_PHONETIC).
            band_queries: List of (band_id, hashes) tuples.

        Returns:
            Dict mapping entity_key → band hit count.
        """
        if not band_queries:
            return {}

        # Build a single query with UNION ALL for each band
        # Each band contributes its matching entity_keys
        parts = []
        params = []
        param_idx = 1

        for band_id, hashes in band_queries:
            if not hashes:
                continue
            parts.append(
                f"SELECT entity_key FROM {table} "
                f"WHERE band_id = ${param_idx} AND band_hash = ANY(${param_idx + 1}::bytea[])"
            )
            params.append(band_id)
            params.append(hashes)
            param_idx += 2

        if not parts:
            return {}

        # Combine: count how many bands each entity_key appeared in
        inner = " UNION ALL ".join(parts)
        sql = f"SELECT entity_key, COUNT(*) AS hits FROM ({inner}) sub GROUP BY entity_key"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return {row['entity_key']: row['hits'] for row in rows}

    async def query_bands_progressive(
        self,
        table: str,
        band_queries: List[Tuple[int, List[bytes]]],
        band_batch_size: int = 3,
        min_candidates: int = 20,
        max_candidates: int = 5000,
    ) -> Dict[str, int]:
        """Progressive band query with early stopping.

        Queries bands in small batches. After each batch, checks whether
        enough strong candidates have been found and stops early if so.

        Args:
            table: Table name.
            band_queries: All (band_id, hashes) pairs to query.
            band_batch_size: How many bands to query per SQL call.
            min_candidates: Target candidate count for early stop.
            max_candidates: Hard cap.

        Returns:
            Dict mapping entity_key → band hit count.
        """
        if not band_queries:
            return {}

        from collections import Counter
        band_hits: Counter = Counter()
        bands_queried = 0

        for batch_start in range(0, len(band_queries), band_batch_size):
            batch = band_queries[batch_start:batch_start + band_batch_size]
            batch_result = await self.query_bands(table, batch)

            for key, hits in batch_result.items():
                band_hits[key] += hits
            bands_queried += len(batch)

            # Early exit check
            if bands_queried >= 3:
                min_hits = max(2, bands_queried // 2)
                strong = sum(1 for cnt in band_hits.values() if cnt >= min_hits)
                if strong >= min_candidates:
                    logger.debug(
                        "progressive_query: early stop after %d/%d bands "
                        "(%d strong candidates, target=%d)",
                        bands_queried, len(band_queries), strong, min_candidates)
                    break

        return dict(band_hits)

    async def remove_entity_bands(
        self,
        table: str,
        entity_keys: List[str],
    ):
        """Remove all band entries for specific entity keys.

        Args:
            table: Table name.
            entity_keys: List of entity keys to remove (e.g. ['eid::0', 'eid::1']).
        """
        if not entity_keys:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {table} WHERE entity_key = ANY($1::text[])",
                entity_keys,
            )

    async def remove_entity_bands_by_prefix(
        self,
        table: str,
        entity_id: str,
    ):
        """Remove all band entries for an entity using prefix match.

        Use this when you don't know exact variant keys. Matches
        entity_id::* pattern.

        Args:
            table: Table name.
            entity_id: The entity ID (without ::variant_idx suffix).
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {table} WHERE entity_key LIKE $1",
                f"{entity_id}::%",
            )

    async def truncate(self, table: str):
        """Truncate a band table (for full rebuild).

        Args:
            table: Table name to truncate.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(f"TRUNCATE {table}")

    # ------------------------------------------------------------------
    # Dedup hash operations
    # ------------------------------------------------------------------

    async def get_dedup_hash(self, entity_id: str) -> Optional[str]:
        """Get the stored dedup hash for an entity.

        Args:
            entity_id: The entity ID.

        Returns:
            32-char hex hash string, or None if not found.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                f"SELECT dedup_hash FROM {TABLE_HASH} WHERE entity_id = $1",
                entity_id,
            )

    async def set_dedup_hash(self, entity_id: str, hash_val: str):
        """Set the dedup hash for an entity (upsert).

        Args:
            entity_id: The entity ID.
            hash_val: 32-char hex hash string.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {TABLE_HASH} (entity_id, dedup_hash) "
                f"VALUES ($1, $2) "
                f"ON CONFLICT (entity_id) DO UPDATE SET dedup_hash = EXCLUDED.dedup_hash",
                entity_id, hash_val,
            )

    async def set_dedup_hashes_batch(self, hashes: Dict[str, str]):
        """Batch upsert dedup hashes.

        Args:
            hashes: Mapping of entity_id → hash_val.
        """
        if not hashes:
            return
        records = [(eid, h) for eid, h in hashes.items()]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                f"INSERT INTO {TABLE_HASH} (entity_id, dedup_hash) "
                f"VALUES ($1, $2) "
                f"ON CONFLICT (entity_id) DO UPDATE SET dedup_hash = EXCLUDED.dedup_hash",
                records,
            )

    async def delete_dedup_hash(self, entity_id: str):
        """Delete the dedup hash for an entity.

        Args:
            entity_id: The entity ID.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {TABLE_HASH} WHERE entity_id = $1",
                entity_id,
            )

    async def delete_dedup_hashes_batch(self, entity_ids: List[str]):
        """Batch delete dedup hashes.

        Args:
            entity_ids: List of entity IDs to delete.
        """
        if not entity_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {TABLE_HASH} WHERE entity_id = ANY($1::text[])",
                entity_ids,
            )

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    async def truncate_all(self):
        """Truncate all dedup tables (for full rebuild)."""
        async with self.pool.acquire() as conn:
            await conn.execute(f"TRUNCATE {TABLE_PRIMARY}")
            await conn.execute(f"TRUNCATE {TABLE_PHONETIC}")
            await conn.execute(f"TRUNCATE {TABLE_HASH}")

    async def get_band_count(self, table: str) -> int:
        """Get total number of band entries in a table.

        Args:
            table: Table name.

        Returns:
            Row count.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(f"SELECT COUNT(*) FROM {table}")

    async def get_entity_count(self) -> int:
        """Get number of distinct entities in the dedup hash table.

        Returns:
            Number of entities with stored dedup hashes.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE_HASH}")

    # ------------------------------------------------------------------
    # Advisory lock (replaces Redis distributed lock)
    # ------------------------------------------------------------------

    async def try_advisory_lock(self) -> bool:
        """Try to acquire a PostgreSQL advisory lock for dedup operations.

        Uses pg_try_advisory_lock with a fixed lock ID derived from
        'entity_dedup_init'. Returns immediately (non-blocking).

        Returns:
            True if lock acquired, False if held by another session.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT pg_try_advisory_lock(hashtext('entity_dedup_init'))"
            )

    async def release_advisory_lock(self):
        """Release the PostgreSQL advisory lock for dedup operations."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT pg_advisory_unlock(hashtext('entity_dedup_init'))"
            )
