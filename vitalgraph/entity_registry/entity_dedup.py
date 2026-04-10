"""
Near-duplicate detection for the Entity Registry.

Uses datasketch MinHash LSH for candidate blocking and
RapidFuzz for precise string similarity scoring.

Supports two storage backends:
- In-memory (default): rebuilt on startup from PostgreSQL
- Redis: persistent, shared across workers
"""

import asyncio
import hashlib
import logging
import os
import pickle
import time as _time_mod
import uuid
from typing import Any, Dict, List, Optional, Set

import jellyfish
import redis as redis_lib
from datasketch import MinHash, MinHashLSH
from rapidfuzz import fuzz

from vitalgraph.entity_registry.datasketch_cluster import register_cluster_storage, distribute_lsh_hash_tags

logger = logging.getLogger(__name__)

# Default tuning parameters
DEFAULT_NUM_PERM = 64
DEFAULT_LSH_THRESHOLD = 0.3
DEFAULT_SHINGLE_K = 3
DEFAULT_MIN_SCORE = 50.0
DEFAULT_PHONETIC_BONUS = 10.0
DEFAULT_PHONETIC_LSH_THRESHOLD = 0.3
DEFAULT_MAX_CANDIDATES = 5000
DEFAULT_MIN_CANDIDATES = 20   # relax band threshold until we hit this many
BULK_BATCH_SIZE = 1000  # entities per pipeline flush during bulk init

# Distributed lock parameters (Redis / MemoryDB)
LOCK_KEY_SUFFIX = b'_init_lock'
LOCK_TTL_SECONDS = 600       # 10-minute safety TTL
LOCK_RETRY_INTERVAL = 2      # seconds between retries
LOCK_MAX_WAIT = 300           # 5 minutes max wait

# Lua script for atomic release: only delete if we still own the lock
_LUA_RELEASE = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def build_shingles(entity: Dict[str, Any], k: int = DEFAULT_SHINGLE_K) -> set:
    """Build character n-gram shingle set from entity fields for MinHash.

    Includes:
    - primary_name (shingled)
    - All alias_name values (shingled)
    - country, region, locality (as prefixed whole tokens)
    """
    shingles = set()

    # Collect all name variants
    names = []
    primary_name = entity.get('primary_name')
    if primary_name:
        names.append(primary_name)
    for alias in (entity.get('aliases') or []):
        alias_name = alias.get('alias_name') if isinstance(alias, dict) else None
        if alias_name:
            names.append(alias_name)

    # Character n-gram shingles from names
    for name in names:
        normalized = name.lower().strip()
        if len(normalized) < k:
            shingles.add(normalized)
        else:
            for i in range(len(normalized) - k + 1):
                shingles.add(normalized[i:i + k])

    # Location tokens (whole values, prefixed to avoid collision with name shingles)
    for field in ('country', 'region', 'locality'):
        val = entity.get(field)
        if val:
            shingles.add(f"{field}:{val.lower().strip()}")

    return shingles


def compute_dedup_hash(entity: Dict[str, Any]) -> str:
    """Compute a deterministic MD5 hash of the dedup-relevant fields.

    Fields: type_key, primary_name, country, region, locality, sorted aliases.
    Returns a 32-char hex string.  Used to detect changes between PostgreSQL
    and the MemoryDB dedup index without comparing full entity data.
    """
    parts = [
        (entity.get('type_key') or '').lower().strip(),
        (entity.get('primary_name') or '').lower().strip(),
        (entity.get('country') or '').lower().strip(),
        (entity.get('region') or '').lower().strip(),
        (entity.get('locality') or '').lower().strip(),
    ]
    # Collect and sort alias names for deterministic ordering
    aliases = []
    for alias in (entity.get('aliases') or []):
        name = alias.get('alias_name') if isinstance(alias, dict) else None
        if name:
            aliases.append(name.lower().strip())
    aliases.sort()
    parts.append(','.join(aliases))
    return hashlib.md5('|'.join(parts).encode('utf-8')).hexdigest()


class EntityDedupIndex:
    """Near-duplicate detection index for the Entity Registry.

    Two-layer approach:
    1. MinHash LSH for fast candidate retrieval (sub-linear)
    2. RapidFuzz for precise scoring of candidates

    Args:
        num_perm: Number of MinHash permutations (higher = more accurate, more memory).
        threshold: Jaccard similarity threshold for LSH candidate retrieval.
                   Intentionally low — RapidFuzz refines afterwards.
        shingle_k: Character n-gram size for shingling.
        storage_config: Optional dict for Redis backend. If None, uses in-memory.
            Example: {'type': 'redis', 'redis': {'host': 'localhost', 'port': 6379}}
    """

    def __init__(
        self,
        num_perm: int = DEFAULT_NUM_PERM,
        threshold: float = DEFAULT_LSH_THRESHOLD,
        shingle_k: int = DEFAULT_SHINGLE_K,
        storage_config: Optional[Dict[str, Any]] = None,
        phonetic_bonus: float = DEFAULT_PHONETIC_BONUS,
        phonetic_threshold: float = DEFAULT_PHONETIC_LSH_THRESHOLD,
    ):
        self.num_perm = num_perm
        self.threshold = threshold
        self.phonetic_threshold = phonetic_threshold
        self.shingle_k = shingle_k
        self.storage_config = storage_config
        self.phonetic_bonus = phonetic_bonus

        # Primary LSH index (character trigram shingles)
        self.lsh = self._create_lsh(self.threshold, self.storage_config)

        # Phonetic LSH index (phonetic code shingles)
        self.phonetic_lsh = self._create_lsh(
            self.phonetic_threshold,
            self._phonetic_storage_config(),
        )

        # In-memory cache: entity_id -> {primary_name, aliases (name list), country, ...}
        # Used for RapidFuzz scoring (avoids DB round-trips during query)
        self._entity_cache: Dict[str, Dict[str, Any]] = {}

        self._initialized = False

        # Distributed lock state (Redis / MemoryDB only)
        self._redis_client: Optional[redis_lib.Redis] = None
        self._lock_id: Optional[str] = None

    def _create_lsh(self, threshold: float, storage_config: Optional[Dict[str, Any]] = None) -> MinHashLSH:
        """Create a MinHashLSH instance."""
        kwargs: Dict[str, Any] = {
            'threshold': threshold,
            'num_perm': self.num_perm,
        }
        if storage_config:
            kwargs['storage_config'] = storage_config
            if storage_config.get('type') == 'redis_cluster':
                kwargs['prepickle'] = True
        lsh = MinHashLSH(**kwargs)
        # Distribute bands across cluster slots with per-band hash tags
        if storage_config and storage_config.get('type') == 'redis_cluster':
            prefix = storage_config.get('hash_tag_prefix', 'dedup')
            distribute_lsh_hash_tags(lsh, prefix)
        return lsh

    def _phonetic_storage_config(self) -> Optional[Dict[str, Any]]:
        """Build storage config for the phonetic LSH with a distinct Redis namespace."""
        if not self.storage_config:
            return None
        config = dict(self.storage_config)
        base = config.get('basename', b'dedup')
        if isinstance(base, str):
            base = base.encode()
        config['basename'] = base + b'_phonetic'
        # Distinct hash tag prefix so phonetic bands use different slots
        if 'hash_tag_prefix' in config:
            config['hash_tag_prefix'] = config['hash_tag_prefix'] + '_ph'
        return config

    @classmethod
    def from_env(cls) -> 'EntityDedupIndex':
        """Create an EntityDedupIndex from environment variables.

        Uses ``get_scoped_env`` so that env vars are scoped by
        ``VITALGRAPH_ENVIRONMENT`` (e.g. ``PROD_ENTITY_DEDUP_BACKEND``
        when ``VITALGRAPH_ENVIRONMENT=prod``), falling back to the
        unprefixed name.

        Reads:
            ENTITY_DEDUP_BACKEND: 'memory' (default) or 'redis'
            ENTITY_DEDUP_REDIS_HOST: Redis host (default 'localhost')
            ENTITY_DEDUP_REDIS_PORT: Redis port (default 6379)
            ENTITY_DEDUP_NUM_PERM: Number of permutations (default 128)
            ENTITY_DEDUP_THRESHOLD: LSH threshold (default 0.3)
            VITALGRAPH_ENVIRONMENT: Environment name used as Redis key prefix
                (e.g. 'local', 'dev', 'prod').  Results in keys like
                ``dev_dedup_bucket_...`` and ``dev_dedup_phonetic_bucket_...``
        """
        from vitalgraph.config.config_loader import get_scoped_env

        backend = get_scoped_env('ENTITY_DEDUP_BACKEND', 'memory').lower()
        num_perm = int(get_scoped_env('ENTITY_DEDUP_NUM_PERM', str(DEFAULT_NUM_PERM)))
        threshold = float(get_scoped_env('ENTITY_DEDUP_THRESHOLD', str(DEFAULT_LSH_THRESHOLD)))

        storage_config = None
        if backend == 'redis':
            redis_host = get_scoped_env('ENTITY_DEDUP_REDIS_HOST', 'localhost')
            redis_port = int(get_scoped_env('ENTITY_DEDUP_REDIS_PORT', '6379'))
            redis_params = {'host': redis_host, 'port': redis_port}

            # Optional auth (MemoryDB ACL / ElastiCache AUTH)
            redis_username = get_scoped_env('ENTITY_DEDUP_REDIS_USERNAME') or None
            redis_password = get_scoped_env('ENTITY_DEDUP_REDIS_PASSWORD') or None
            if redis_username:
                redis_params['username'] = redis_username
            if redis_password:
                redis_params['password'] = redis_password

            # TLS (required for MemoryDB)
            use_ssl = get_scoped_env('ENTITY_DEDUP_REDIS_SSL', 'false').lower() in ('true', '1', 'yes')
            if use_ssl:
                redis_params['ssl'] = True
                redis_params['ssl_cert_reqs'] = None  # MemoryDB uses Amazon-managed certs

            # Redis Cluster mode (MemoryDB / ElastiCache cluster)
            use_cluster = get_scoped_env('ENTITY_DEDUP_REDIS_CLUSTER', 'false').lower() in ('true', '1', 'yes')
            if use_cluster:
                register_cluster_storage()
                storage_type = 'redis_cluster'
            else:
                storage_type = 'redis'

            env_name = os.environ.get('VITALGRAPH_ENVIRONMENT', '').strip().lower()
            # For cluster mode, per-band hash tags distribute bands across
            # shards (set via hash_tag_prefix, applied in _create_lsh).
            # For standalone Redis, use a simple hash-tagged basename.
            # Production (and empty) use the bare 'dedup' prefix; other
            # environments (dev, staging, etc.) get a prefixed namespace.
            if env_name in ('', 'prod', 'production'):
                tag_prefix = 'dedup'
            else:
                tag_prefix = f"{env_name}_dedup"
            basename = f"{{{tag_prefix}}}"

            storage_config = {
                'type': storage_type,
                'basename': basename.encode(),
                'redis': redis_params,
            }
            if use_cluster:
                storage_config['hash_tag_prefix'] = tag_prefix
            logger.info(f"Entity dedup using Redis backend: {redis_host}:{redis_port} "
                         f"(ssl={use_ssl}, cluster={use_cluster}, "
                         f"env='{env_name or '(none)'}')")
        else:
            logger.info("Entity dedup using in-memory backend")

        return cls(num_perm=num_perm, threshold=threshold, storage_config=storage_config)

    # ------------------------------------------------------------------
    # Distributed lock (Redis / MemoryDB)
    # ------------------------------------------------------------------

    def _get_redis_client(self) -> Optional[redis_lib.Redis]:
        """Get or create a Redis client for distributed locking.

        Tries RedisCluster first (required for MemoryDB / ElastiCache
        cluster mode), falls back to standalone Redis for local dev.
        """
        if not self.storage_config:
            return None
        if self._redis_client is not None:
            return self._redis_client
        redis_params = dict(self.storage_config.get('redis', {}))
        redis_params.setdefault('decode_responses', False)
        try:
            self._redis_client = redis_lib.RedisCluster(**redis_params)
            logger.debug("Dedup lock using RedisCluster client")
        except (redis_lib.exceptions.RedisClusterException, Exception):
            self._redis_client = redis_lib.Redis(**redis_params)
            logger.debug("Dedup lock using standalone Redis client")
        return self._redis_client

    def _lock_key(self) -> bytes:
        """Redis key for the distributed init/rebuild lock."""
        base = self.storage_config.get('basename', b'dedup') if self.storage_config else b'dedup'
        if isinstance(base, str):
            base = base.encode()
        return base + LOCK_KEY_SUFFIX

    def _dedup_hash_key(self) -> bytes:
        """Redis HASH key that maps entity_id → dedup_hash for fast comparison."""
        base = self.storage_config.get('basename', b'dedup') if self.storage_config else b'dedup'
        if isinstance(base, str):
            base = base.encode()
        return base + b'_dedup_hashes'

    def _try_acquire_lock(self, ttl: int = LOCK_TTL_SECONDS) -> bool:
        """Single non-blocking attempt to acquire the lock. Returns True if acquired."""
        client = self._get_redis_client()
        if client is None:
            return True  # in-memory backend — no lock needed
        self._lock_id = str(uuid.uuid4())
        acquired = client.set(self._lock_key(), self._lock_id.encode(), nx=True, ex=ttl)
        if acquired:
            logger.info(f"Acquired dedup init lock (id={self._lock_id[:8]})")
        return bool(acquired)

    def _release_lock(self):
        """Release the distributed lock (only if we still own it)."""
        client = self._get_redis_client()
        if client is None or self._lock_id is None:
            return
        try:
            client.eval(_LUA_RELEASE, 1, self._lock_key(), self._lock_id.encode())
            logger.info(f"Released dedup init lock (id={self._lock_id[:8]})")
        except Exception as e:
            logger.warning(f"Error releasing dedup lock: {e}")
        finally:
            self._lock_id = None

    def _acquire_lock_sync(self, ttl: int = LOCK_TTL_SECONDS,
                           max_wait: int = LOCK_MAX_WAIT) -> bool:
        """Blocking sync lock acquisition with retries (for clear_index)."""
        deadline = _time_mod.time() + max_wait
        while _time_mod.time() < deadline:
            if self._try_acquire_lock(ttl):
                return True
            logger.info("Dedup init lock held by another process, waiting...")
            _time_mod.sleep(LOCK_RETRY_INTERVAL)
        logger.warning(f"Could not acquire dedup init lock after {max_wait}s")
        return False

    async def _acquire_lock_async(self, ttl: int = LOCK_TTL_SECONDS,
                                  max_wait: int = LOCK_MAX_WAIT) -> bool:
        """Non-blocking async lock acquisition with retries (for initialize)."""
        deadline = _time_mod.time() + max_wait
        while _time_mod.time() < deadline:
            if self._try_acquire_lock(ttl):
                return True
            logger.info("Dedup init lock held by another process, waiting...")
            await asyncio.sleep(LOCK_RETRY_INTERVAL)
        logger.warning(f"Could not acquire dedup init lock after {max_wait}s")
        return False

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _delete_redis_keys(self):
        """Delete all datasketch keys for this index from Redis.

        Handles both the legacy single-hash-tag pattern and the distributed
        per-band hash tag patterns.
        """
        if not self.storage_config:
            return
        client = self._get_redis_client()
        if not client:
            return

        # Collect all patterns to scan — legacy basename + per-band tags
        patterns = []
        basename = self.storage_config.get('basename', b'dedup')
        if isinstance(basename, str):
            basename = basename.encode()
        patterns.append(basename + b'*')

        # Per-band distributed patterns (primary + phonetic LSH)
        tag_prefix = self.storage_config.get('hash_tag_prefix')
        if tag_prefix:
            for pfx in [tag_prefix, tag_prefix + '_ph']:
                patterns.append(f'{{{pfx}_b*'.encode())
                patterns.append(f'{{{pfx}_keys}}*'.encode())

        deleted = 0
        BATCH = 5000
        for pattern in patterns:
            batch = []
            for key in client.scan_iter(match=pattern, count=2000):
                batch.append(key)
                if len(batch) >= BATCH:
                    pipe = client.pipeline()
                    for k in batch:
                        pipe.unlink(k)
                    pipe.execute()
                    deleted += len(batch)
                    batch.clear()
                    if deleted % 50000 == 0:
                        logger.info(f"  ... deleted {deleted:,} keys so far")
            if batch:
                pipe = client.pipeline()
                for k in batch:
                    pipe.unlink(k)
                pipe.execute()
                deleted += len(batch)
        if deleted:
            logger.info(f"Deleted {deleted:,} Redis keys")

    def clear_index(self):
        """Wipe the LSH index and entity cache, creating a fresh empty state.

        For in-memory backend: simply replaces the LSH object.
        For Redis/cluster backend: deletes all existing Redis keys for this
        index, then creates fresh LSH objects.

        Acquires a distributed lock (Redis backends) to prevent concurrent
        clear/initialize races across processes.
        """
        if not self._acquire_lock_sync():
            raise RuntimeError("Could not acquire dedup init lock for clear_index")
        try:
            self._delete_redis_keys()
            # Delete the dedup hash comparison key
            client = self._get_redis_client()
            if client:
                try:
                    client.delete(self._dedup_hash_key())
                except Exception as e:
                    logger.warning(f"Error deleting dedup hash key: {e}")
            self.lsh = self._create_lsh(self.threshold, self.storage_config)
            self.phonetic_lsh = self._create_lsh(
                self.phonetic_threshold, self._phonetic_storage_config(),
            )
            self._entity_cache.clear()
            self._initialized = False
            logger.info("Dedup index cleared")
        finally:
            self._release_lock()

    async def initialize(self, pool, since=None, chunk_size: int = 5000,
                         skip_lock: bool = False,
                         batch_delay: float = 0.0,
                         num_workers: int = 1) -> int:
        """Load entities from the database and build/update the LSH index.

        Uses a single bulk query (entity + aliases via LEFT JOIN) and processes
        rows in chunks to stay memory-efficient at scale (10M+ entities).

        For persistent backends (Redis / MemoryDB), also removes stale entries
        that exist in the index but no longer exist as active entities in
        PostgreSQL. For the in-memory backend this is a no-op since the index
        starts empty on each process start.

        Acquires a distributed lock (Redis backends) so that concurrent
        processes (e.g. multiple ECS tasks) don't duplicate work or race
        during stale-entry cleanup.

        Args:
            pool: asyncpg connection pool.
            since: Optional datetime — if provided, only sync entities whose
                   updated_time >= since (incremental sync). Full sync if None.
            chunk_size: Number of entity rows to fetch per chunk.
            skip_lock: If True, skip the distributed lock (for read-only
                       operations like --status / --check).
            batch_delay: Seconds to sleep between each pipeline flush
                (rate-limits Redis writes so bulk sync doesn't monopolize
                MemoryDB). Use 0 for maximum speed.
            num_workers: Number of parallel worker threads for batch
                processing. Each worker computes minhashes (CPU) and flushes
                a pipeline to Redis (I/O) concurrently. Higher values improve
                throughput on multi-shard clusters.

        Returns:
            Number of entities indexed.
        """
        if skip_lock:
            return await self._do_initialize(pool, since=since,
                                             chunk_size=chunk_size,
                                             batch_delay=batch_delay,
                                             num_workers=num_workers)

        if not await self._acquire_lock_async():
            raise RuntimeError("Could not acquire dedup init lock for initialize")

        try:
            return await self._do_initialize(pool, since=since,
                                             chunk_size=chunk_size,
                                             batch_delay=batch_delay,
                                             num_workers=num_workers)
        finally:
            self._release_lock()

    async def _do_initialize(self, pool, since=None, chunk_size: int = 5000,
                             batch_delay: float = 0.0, num_workers: int = 1) -> int:
        """Inner initialize logic (called under the distributed lock).

        When num_workers > 1, uses a producer-consumer pattern:
        - Producer: streams entity rows from PostgreSQL, groups into batches
        - Workers: N async tasks consume batches, each running
          _bulk_insert_entities in a thread (CPU + Redis I/O) concurrently
        """
        start = _time_mod.time()

        # Track IDs that existed in the index before this sync (for stale detection)
        pre_existing_ids = set(self._entity_cache.keys())

        active_ids = set()
        count = 0
        current_entity_id = None
        current_entity = None

        # -- Worker infrastructure for parallel batch processing --
        batch_queue: asyncio.Queue = asyncio.Queue(maxsize=num_workers * 2)
        batches_submitted = 0
        batches_done = 0
        worker_error = None

        async def _worker(worker_id: int):
            """Consume batches from the queue and process them in a thread."""
            nonlocal batches_done, worker_error
            while True:
                batch = await batch_queue.get()
                if batch is None:  # poison pill
                    batch_queue.task_done()
                    break
                try:
                    await asyncio.to_thread(self._bulk_insert_entities, batch)
                    batches_done += 1
                    if batch_delay > 0:
                        await asyncio.sleep(batch_delay)
                except Exception as e:
                    worker_error = e
                    logger.error(f"Worker {worker_id} error: {e}")
                finally:
                    batch_queue.task_done()

        # Start worker tasks
        entity_batch: List[tuple] = []
        workers = [asyncio.create_task(_worker(i)) for i in range(num_workers)]
        if num_workers > 1:
            logger.info(f"Bulk sync: {num_workers} parallel workers")

        # Use keyset pagination instead of a long-lived cursor so we don't
        # hold a PG connection open for the entire (potentially 50+ minute) sync.
        PAGE_SIZE = 50000  # rows per page (entities × aliases)
        last_entity_id = ''  # keyset cursor

        try:
            while True:
                # Fetch one page of rows, release connection immediately
                if since is not None:
                    page_sql = (
                        "SELECT e.entity_id, e.primary_name, et.type_key, "
                        "e.country, e.region, e.locality, ea.alias_name "
                        "FROM entity e "
                        "JOIN entity_type et ON et.type_id = e.entity_type_id "
                        "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                        "AND ea.status != 'retracted' "
                        "WHERE e.status != 'deleted' AND e.updated_time >= $1 "
                        "AND e.entity_id > $2 "
                        "ORDER BY e.entity_id LIMIT $3"
                    )
                    page_args = [since, last_entity_id, PAGE_SIZE]
                else:
                    page_sql = (
                        "SELECT e.entity_id, e.primary_name, et.type_key, "
                        "e.country, e.region, e.locality, ea.alias_name "
                        "FROM entity e "
                        "JOIN entity_type et ON et.type_id = e.entity_type_id "
                        "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                        "AND ea.status != 'retracted' "
                        "WHERE e.status != 'deleted' AND e.entity_id > $1 "
                        "ORDER BY e.entity_id LIMIT $2"
                    )
                    page_args = [last_entity_id, PAGE_SIZE]

                async with pool.acquire() as conn:
                    rows = await conn.fetch(page_sql, *page_args)

                if not rows:
                    break

                for row in rows:
                    entity_id = row['entity_id']

                    if entity_id != current_entity_id:
                        # Flush previous entity into batch
                        if current_entity_id is not None:
                            entity_batch.append((current_entity_id, current_entity))
                            count += 1

                        # Submit batch when it reaches threshold
                        if len(entity_batch) >= BULK_BATCH_SIZE:
                            await batch_queue.put(list(entity_batch))
                            batches_submitted += 1
                            entity_batch.clear()

                            if count % 10000 == 0:
                                elapsed = _time_mod.time() - start
                                rate = count / elapsed if elapsed > 0 else 0
                                logger.info(
                                    f"  ... {count:,} entities indexed "
                                    f"({rate:.0f}/s, {elapsed:.0f}s elapsed, "
                                    f"{batches_submitted} batches submitted, "
                                    f"{batches_done} flushed)")

                            if worker_error:
                                raise worker_error

                        # Start new entity
                        current_entity_id = entity_id
                        active_ids.add(entity_id)
                        current_entity = {
                            'entity_id': entity_id,
                            'primary_name': row['primary_name'],
                            'type_key': row['type_key'],
                            'country': row['country'],
                            'region': row['region'],
                            'locality': row['locality'],
                            'aliases': [],
                        }

                    # Append alias (LEFT JOIN may produce NULL)
                    alias_name = row['alias_name']
                    if alias_name:
                        current_entity['aliases'].append({'alias_name': alias_name})

                # Advance keyset cursor to last entity_id seen in this page
                last_entity_id = rows[-1]['entity_id']

                # If page was smaller than PAGE_SIZE, we've reached the end
                if len(rows) < PAGE_SIZE:
                    break

            # Flush last entity + remaining batch
            if current_entity_id is not None:
                entity_batch.append((current_entity_id, current_entity))
                count += 1
            if entity_batch:
                await batch_queue.put(list(entity_batch))
                batches_submitted += 1

        finally:
            # Send poison pills to stop workers
            for _ in range(num_workers):
                await batch_queue.put(None)
            # Wait for all workers to finish
            await asyncio.gather(*workers, return_exceptions=True)

        if worker_error:
            raise worker_error

        # Remove stale entries (only meaningful for full sync on persistent backends)
        if since is None:
            stale_ids = pre_existing_ids - active_ids
            for stale_id in stale_ids:
                self.remove_entity(stale_id)
            if stale_ids:
                logger.info(f"Removed {len(stale_ids)} stale entities from dedup index")

        self._initialized = True
        duration = _time_mod.time() - start
        logger.info(f"Entity dedup index: {count:,} entities indexed in {duration:.1f}s"
                     f" ({num_workers} workers)"
                     f"{' (incremental)' if since else ' (full)'}")
        return count

    def _bulk_insert_entities(self, batch: List[tuple]):
        """Insert a batch of entities into both LSH indexes via a single pipeline flush.

        Pre-computes all minhashes (CPU), then writes all Redis commands for
        the entire batch in one pipeline round-trip per LSH index.

        Args:
            batch: List of (entity_id, entity_dict) tuples.
        """
        # Phase 1: Pre-compute all minhashes (pure CPU, no Redis)
        lsh_entries = []       # [(pickled_key, minhash), ...]
        phonetic_entries = []  # [(pickled_key, minhash), ...]
        for entity_id, entity in batch:
            alias_names = []
            for alias in (entity.get('aliases') or []):
                name = alias.get('alias_name') if isinstance(alias, dict) else None
                if name:
                    alias_names.append(name)

            all_names = []
            primary = entity.get('primary_name', '')
            if primary:
                all_names.append(primary)
            all_names.extend(alias_names)

            variant_count = 0
            for idx, name in enumerate(all_names):
                shingles = self._name_shingles(name, entity)
                if not shingles:
                    continue
                mh = self._build_minhash(shingles)
                lsh_key = self._lsh_key(entity_id, idx)
                lsh_entries.append((lsh_key, mh))
                variant_count += 1

            if variant_count == 0:
                continue

            # Cache for scoring
            self._entity_cache[entity_id] = {
                'primary_name': primary,
                'type_key': entity.get('type_key'),
                'alias_names': alias_names,
                'country': entity.get('country'),
                'region': entity.get('region'),
                'locality': entity.get('locality'),
                '_variant_count': len(all_names),
            }

            for idx_p, name in enumerate(all_names):
                codes = self._phonetic_codes(name)
                if not codes:
                    continue
                mh = self._build_minhash(set(codes))
                p_key = self._phonetic_lsh_key(entity_id, idx_p)
                phonetic_entries.append((p_key, mh))

        # Phase 2: Write LSH entries
        if self.storage_config:
            # Redis / MemoryDB: bulk pipeline flush
            if lsh_entries:
                self._bulk_write_lsh(self.lsh, lsh_entries)
            if phonetic_entries:
                self._bulk_write_lsh(self.phonetic_lsh, phonetic_entries)
        else:
            # In-memory: use normal datasketch insert
            for raw_key, mh in lsh_entries:
                self.lsh.insert(raw_key, mh)
            for raw_key, mh in phonetic_entries:
                self.phonetic_lsh.insert(raw_key, mh)

        # Phase 3: Batch-store dedup hashes in Redis HASH
        client = self._get_redis_client()
        if client and batch:
            try:
                hash_key = self._dedup_hash_key()
                pipe = client.pipeline()
                for entity_id, entity in batch:
                    if entity_id in self._entity_cache:  # only if actually indexed
                        h = compute_dedup_hash(entity)
                        pipe.hset(hash_key, entity_id, h)
                pipe.execute()
            except Exception as e:
                logger.warning(f"Error storing batch dedup hashes: {e}")

    def _bulk_write_lsh(self, lsh: MinHashLSH, entries: List[tuple]):
        """Write pre-computed (key, minhash) pairs to an LSH's Redis storage
        in a single pipeline flush.

        Replicates datasketch's _insert logic but batches all commands.
        """
        # Get the shared Redis client from any hashtable's storage
        client = lsh.hashtables[0]._redis
        pipe = client.pipeline()

        for raw_key, minhash in entries:
            key = pickle.dumps(raw_key) if lsh.prepickle else raw_key
            Hs = [lsh._H(minhash.hashvalues[start:end])
                  for start, end in lsh.hashranges]

            # keys storage (ordered list): map key → band hashes
            keys_store = lsh.keys
            rk = keys_store.redis_key(key)
            pipe.hset(keys_store._name, key, rk)
            pipe.rpush(rk, *Hs)

            # hashtable storage (unordered sets): map band_hash → key
            for H, ht in zip(Hs, lsh.hashtables):
                rk_ht = ht.redis_key(H)
                pipe.hset(ht._name, H, rk_ht)
                pipe.sadd(rk_ht, key)

        pipe.execute()

    def _name_shingles(self, name: str, entity: Dict[str, Any]) -> set:
        """Build shingles for a single name variant, including location tokens."""
        shingles = set()
        normalized = name.lower().strip()
        if not normalized:
            return shingles
        if len(normalized) < self.shingle_k:
            shingles.add(normalized)
        else:
            for i in range(len(normalized) - self.shingle_k + 1):
                shingles.add(normalized[i:i + self.shingle_k])
        # Include location tokens so same-name different-location gets lower Jaccard
        for field in ('country', 'region', 'locality'):
            val = entity.get(field)
            if val:
                shingles.add(f"{field}:{val.lower().strip()}")
        return shingles

    def _lsh_key(self, entity_id: str, idx: int) -> str:
        """Compound LSH key: entity_id::variant_index."""
        return f"{entity_id}::{idx}"

    @staticmethod
    def _entity_id_from_lsh_key(lsh_key: str) -> str:
        """Extract entity_id from a compound LSH key."""
        return lsh_key.rsplit('::', 1)[0]

    def _phonetic_lsh_key(self, entity_id: str, idx: int) -> str:
        """Compound phonetic LSH key: P::entity_id::variant_index."""
        return f"P::{entity_id}::{idx}"

    def _remove_from_phonetic_lsh(self, entity_id: str, variant_count: int):
        """Remove all phonetic LSH entries for an entity."""
        for i in range(variant_count):
            try:
                self.phonetic_lsh.remove(self._phonetic_lsh_key(entity_id, i))
            except ValueError:
                pass

    def add_entity(self, entity_id: str, entity: Dict[str, Any],
                   _lsh_session=None, _phonetic_session=None,
                   _check_duplication=True):
        """Add or update an entity in the LSH index.

        Each name variant (primary_name + aliases) is indexed as a separate
        LSH entry so that short names like 'IBM' get their own MinHash and
        match queries with high Jaccard similarity.

        Args:
            entity_id: The entity ID.
            entity: Entity dict with primary_name, aliases, country, region, locality.
            _lsh_session: Optional insertion session for pipelined primary LSH inserts.
            _phonetic_session: Optional insertion session for pipelined phonetic LSH inserts.
            _check_duplication: If False, skip per-key HEXISTS checks (use during
                bulk init from a clean index to avoid individual round-trips).
        """
        lsh_target = _lsh_session if _lsh_session is not None else self.lsh
        phonetic_target = _phonetic_session if _phonetic_session is not None else self.phonetic_lsh

        # Remove existing entries if present (for updates)
        if entity_id in self._entity_cache:
            old_variant_count = self._entity_cache[entity_id].get('_variant_count', 1)
            self._remove_from_lsh(entity_id)
            self._remove_from_phonetic_lsh(entity_id, old_variant_count)

        # Collect name variants
        alias_names = []
        for alias in (entity.get('aliases') or []):
            name = alias.get('alias_name') if isinstance(alias, dict) else None
            if name:
                alias_names.append(name)

        all_names = []
        primary = entity.get('primary_name', '')
        if primary:
            all_names.append(primary)
        all_names.extend(alias_names)

        # Insert one LSH entry per name variant
        variant_count = 0
        for idx, name in enumerate(all_names):
            shingles = self._name_shingles(name, entity)
            if not shingles:
                continue
            mh = self._build_minhash(shingles)
            lsh_key = self._lsh_key(entity_id, idx)
            try:
                lsh_target.insert(lsh_key, mh, check_duplication=_check_duplication)
                variant_count += 1
            except ValueError:
                pass  # duplicate key, skip

        if variant_count == 0:
            return

        # Cache for scoring
        self._entity_cache[entity_id] = {
            'primary_name': primary,
            'type_key': entity.get('type_key'),
            'alias_names': alias_names,
            'country': entity.get('country'),
            'region': entity.get('region'),
            'locality': entity.get('locality'),
            '_variant_count': len(all_names),
        }

        # Store dedup hash in Redis for PG ↔ MemoryDB comparison
        client = self._get_redis_client()
        if client:
            try:
                h = compute_dedup_hash(entity)
                client.hset(self._dedup_hash_key(), entity_id, h)
            except Exception as e:
                logger.warning(f"Error storing dedup hash for {entity_id}: {e}")

        # Insert into phonetic LSH (one entry per name variant, phonetic codes as shingles)
        for idx_p, name in enumerate(all_names):
            codes = self._phonetic_codes(name)
            if not codes:
                continue
            mh = self._build_minhash(set(codes))
            p_key = self._phonetic_lsh_key(entity_id, idx_p)
            try:
                phonetic_target.insert(p_key, mh, check_duplication=_check_duplication)
            except ValueError:
                pass  # duplicate key, skip

    def remove_entity(self, entity_id: str):
        """Remove an entity from all indexes (primary LSH, phonetic LSH)."""
        cached = self._entity_cache.get(entity_id)
        if cached:
            all_names = [cached['primary_name']] + (cached.get('alias_names') or [])
            self._remove_from_phonetic_lsh(entity_id, len(all_names))
        self._remove_from_lsh(entity_id)
        self._entity_cache.pop(entity_id, None)
        # Remove dedup hash from Redis
        client = self._get_redis_client()
        if client:
            try:
                client.hdel(self._dedup_hash_key(), entity_id)
            except Exception:
                pass

    def _remove_from_lsh(self, entity_id: str):
        """Remove all LSH entries for an entity (one per name variant)."""
        cached = self._entity_cache.get(entity_id)
        variant_count = (cached or {}).get('_variant_count', 1)
        # Try to remove all variant keys; also try the bare entity_id
        # for backward compatibility with older index entries
        keys_to_try = [self._lsh_key(entity_id, i) for i in range(variant_count)]
        keys_to_try.append(entity_id)
        for key in keys_to_try:
            try:
                self.lsh.remove(key)
            except ValueError:
                pass

    @property
    def entity_count(self) -> int:
        """Number of entities currently in the index."""
        return len(self._entity_cache)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_candidate_ids(
        self,
        entity: Dict[str, Any],
        query_names: Optional[List[str]] = None,
    ) -> set:
        """Phase 1: Retrieve candidate entity IDs from LSH indexes.

        Uses MinHash LSH, phonetic, and typo-variant lookups.
        Does NOT require _entity_cache — only queries the LSH indexes.

        Args:
            entity: Dict with primary_name and optional aliases/location.
            query_names: Pre-computed name variants (optimization to avoid
                         recomputing when called from find_similar).

        Returns:
            Set of candidate entity_id strings.
        """
        if query_names is None:
            query_names = self._get_name_variants(entity)
        if not query_names:
            return set()

        # Build minhashes for primary and phonetic LSH
        primary_mh = []
        for name in query_names:
            shingles = self._name_shingles(name, entity)
            if shingles:
                primary_mh.append(self._build_minhash(shingles))

        phonetic_mh = []
        for name in query_names:
            codes = self._phonetic_codes(name)
            if codes:
                phonetic_mh.append(self._build_minhash(set(codes)))

        # Progressive cascade: strict → relaxed, stopping as soon as
        # we have enough candidates.  Each step is a separate LSH
        # query that only runs if prior steps didn't find enough.
        candidate_ids: Set[str] = set()

        # Step 1: Primary LSH (progressive band query)
        if primary_mh:
            candidate_ids = self._progressive_query(
                self.lsh, primary_mh,
                min_candidates=DEFAULT_MIN_CANDIDATES,
                max_candidates=DEFAULT_MAX_CANDIDATES,
            )
        if len(candidate_ids) >= DEFAULT_MIN_CANDIDATES:
            return candidate_ids

        # Step 2: Phonetic LSH (progressive band query)
        if phonetic_mh:
            ph_ids = self._progressive_query(
                self.phonetic_lsh, phonetic_mh,
                min_candidates=DEFAULT_MIN_CANDIDATES,
                max_candidates=DEFAULT_MAX_CANDIDATES,
                phonetic_keys=True,
            )
            candidate_ids.update(ph_ids)
        if len(candidate_ids) >= DEFAULT_MIN_CANDIDATES:
            return candidate_ids

        # Step 3: Typo variants (progressive band query, limited variants)
        typo_mh = self._build_typo_minhashes(query_names, entity,
                                              max_variants=50)
        if typo_mh:
            typo_ids = self._progressive_query(
                self.lsh, typo_mh,
                min_candidates=DEFAULT_MIN_CANDIDATES,
                max_candidates=DEFAULT_MAX_CANDIDATES,
            )
            candidate_ids.update(typo_ids)

        return candidate_ids

    def score_candidates(
        self,
        entity: Dict[str, Any],
        candidate_data: Dict[str, Dict[str, Any]],
        limit: int = 10,
        min_score: float = DEFAULT_MIN_SCORE,
        exclude_ids: Optional[set] = None,
        type_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Score pre-fetched candidate entities against the query entity.

        Used by the async mixin for persistent backends where candidate
        data is fetched from PostgreSQL on demand (no local cache).

        Args:
            entity: Query entity dict with primary_name, aliases, location.
            candidate_data: Mapping of entity_id → entity dict (from PG).
            limit: Maximum number of results.
            min_score: Minimum composite score (0-100).
            exclude_ids: Entity IDs to skip.
            type_key: Optional type filter.

        Returns:
            Scored candidate list, sorted by score descending.
        """
        exclude_ids = exclude_ids or set()
        query_names = self._get_name_variants(entity)
        if not query_names:
            return []

        results = []
        for cid, cached in candidate_data.items():
            if cid in exclude_ids:
                continue
            if type_key and cached.get('type_key') != type_key:
                continue

            score_info = self._score_pair(query_names, cached)
            score = score_info['score']

            is_phonetic = self._phonetic_match(query_names, cached)
            if is_phonetic and self.phonetic_bonus > 0:
                score = min(score + self.phonetic_bonus, 100.0)
            score_info['detail']['phonetic_match'] = is_phonetic

            if score >= min_score:
                results.append({
                    'entity_id': cid,
                    'primary_name': cached['primary_name'],
                    'type_key': cached.get('type_key'),
                    'score': round(score, 1),
                    'match_level': self._match_level(score),
                    'score_detail': score_info['detail'],
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    def find_similar(
        self,
        entity: Dict[str, Any],
        limit: int = 10,
        min_score: float = DEFAULT_MIN_SCORE,
        exclude_ids: Optional[set] = None,
        type_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find entities similar to the given entity data.

        Args:
            entity: Dict with primary_name, aliases (optional), country/region/locality (optional).
            limit: Maximum number of results.
            min_score: Minimum composite score (0-100) to include.
            exclude_ids: Entity IDs to exclude from results (e.g. self).
            type_key: Optional entity type filter — only return candidates of this type.

        Returns:
            List of scored candidate dicts, sorted by score descending:
            [
                {
                    'entity_id': str,
                    'primary_name': str,
                    'score': float,
                    'match_level': str,   # 'high', 'likely', 'possible'
                    'score_detail': {
                        'ratio': float,
                        'partial_ratio': float,
                        'token_sort_ratio': float,
                        'token_set_ratio': float,
                    },
                },
                ...
            ]
        """
        exclude_ids = exclude_ids or set()
        query_names = self._get_name_variants(entity)
        if not query_names:
            return []

        candidate_ids = self.get_candidate_ids(entity, query_names=query_names)

        # Phase 2: RapidFuzz scoring + phonetic bonus
        results = []

        for cid in candidate_ids:
            if cid in exclude_ids:
                continue
            cached = self._entity_cache.get(cid)
            if not cached:
                continue
            if type_key and cached.get('type_key') != type_key:
                continue

            score_info = self._score_pair(query_names, cached)
            score = score_info['score']

            # Phonetic bonus
            is_phonetic = self._phonetic_match(query_names, cached)
            if is_phonetic and self.phonetic_bonus > 0:
                score = min(score + self.phonetic_bonus, 100.0)
            score_info['detail']['phonetic_match'] = is_phonetic

            if score >= min_score:
                results.append({
                    'entity_id': cid,
                    'primary_name': cached['primary_name'],
                    'type_key': cached.get('type_key'),
                    'score': round(score, 1),
                    'match_level': self._match_level(score),
                    'score_detail': score_info['detail'],
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    def find_similar_by_name(
        self,
        name: str,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        type_key: Optional[str] = None,
        limit: int = 10,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> List[Dict[str, Any]]:
        """Convenience method to find similar entities by name string.

        Args:
            name: The entity name to search for.
            country: Optional country filter/boost.
            region: Optional region filter/boost.
            locality: Optional locality filter/boost.
            type_key: Optional entity type filter.
            limit: Maximum number of results.
            min_score: Minimum composite score (0-100).

        Returns:
            List of scored candidate dicts.
        """
        entity = {
            'primary_name': name,
            'country': country,
            'region': region,
            'locality': locality,
        }
        return self.find_similar(entity, limit=limit, min_score=min_score, type_key=type_key)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_minhash(self, shingles: set) -> MinHash:
        """Build a MinHash signature from a shingle set."""
        mh = MinHash(num_perm=self.num_perm)
        for s in shingles:
            mh.update(s.encode('utf-8'))
        return mh

    def _batch_query_lsh(self, lsh: MinHashLSH, minhashes: List[MinHash]) -> Set[str]:
        """Query an LSH index with multiple MinHash signatures in batch.

        Instead of calling lsh.query() N times (N × B Redis calls, where
        B = number of bands), this method batches all band-hash lookups
        per band into a single getmany() call.

        Cost: O(B) Redis round-trips regardless of N, because datasketch's
        Redis storage uses a pipeline inside getmany().

        Args:
            lsh: The MinHashLSH index to query.
            minhashes: List of MinHash signatures to query.

        Returns:
            Set of raw LSH keys (entity_id::variant_index format).
        """
        if not minhashes:
            return set()

        candidates = set()
        for (start, end), hashtable in zip(lsh.hashranges, lsh.hashtables):
            # Compute band hash for each MinHash
            band_hashes = [lsh._H(mh.hashvalues[start:end]) for mh in minhashes]
            # Single getmany() call per band — one Redis pipeline
            results = hashtable.getmany(*band_hashes)
            for result_set in results:
                for key in result_set:
                    candidates.add(key)

        if lsh.prepickle:
            return {pickle.loads(k) for k in candidates}
        return candidates

    def _progressive_query(
        self,
        lsh: MinHashLSH,
        minhashes: List[MinHash],
        min_candidates: int = DEFAULT_MIN_CANDIDATES,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        band_batch_size: int = 3,
        phonetic_keys: bool = False,
    ) -> Set[str]:
        """Progressive band query with early stopping.

        Queries LSH bands in small batches.  After each batch, checks
        whether enough strong candidates have been found and stops
        early if so.  This avoids the full O(B) Redis sweep for queries
        where high-quality matches exist in the first few bands.

        A candidate is "strong" after *N* bands queried if it appeared
        in >= max(2, N // 2) of them.

        Args:
            lsh: The MinHashLSH index to query.
            minhashes: MinHash signatures to query.
            min_candidates: Target candidate count for early stop.
            max_candidates: Hard cap on returned candidates.
            band_batch_size: Bands to query per Redis round-trip.
            phonetic_keys: If True, strip ``P::`` prefix from keys.

        Returns:
            Set of candidate entity_id strings.
        """
        if not minhashes:
            return set()

        from collections import Counter

        bands = list(zip(lsh.hashranges, lsh.hashtables))
        band_hits: Counter = Counter()  # raw_key → band count
        bands_queried = 0

        for batch_start in range(0, len(bands), band_batch_size):
            batch = bands[batch_start:batch_start + band_batch_size]

            for (start, end), hashtable in batch:
                band_hashes = [lsh._H(mh.hashvalues[start:end])
                               for mh in minhashes]
                results = hashtable.getmany(*band_hashes)
                band_keys: set = set()
                for result_set in results:
                    for key in result_set:
                        band_keys.add(key)
                for key in band_keys:
                    band_hits[key] += 1

            bands_queried += len(batch)

            # Early exit: check if we have enough strong candidates
            if bands_queried >= 3:
                min_hits = max(2, bands_queried // 2)
                strong = sum(1 for cnt in band_hits.values()
                             if cnt >= min_hits)
                if strong >= min_candidates:
                    logger.debug(
                        "progressive_query: early stop after %d/%d bands "
                        "(%d strong candidates, target=%d)",
                        bands_queried, len(bands), strong, min_candidates)
                    break

        if not band_hits:
            return set()

        # Unpickle if needed
        if lsh.prepickle:
            band_hits = Counter(
                {pickle.loads(k): v for k, v in band_hits.items()}
            )

        # Extract entity_ids with adaptive threshold
        def _extract_eid(k: str) -> str:
            if phonetic_keys and '::' in k:
                k = k.split('::', 1)[1]
            return self._entity_id_from_lsh_key(k)

        id_best: Dict[str, int] = {}
        for k, cnt in band_hits.items():
            eid = _extract_eid(k)
            if cnt > id_best.get(eid, 0):
                id_best[eid] = cnt

        # Adaptive filter: strict → relaxed
        max_level = max(id_best.values())
        min_level = 2
        entity_ids: Set[str] = set()
        chosen_level = min_level

        for level in range(max_level, min_level - 1, -1):
            entity_ids = {eid for eid, cnt in id_best.items()
                          if cnt >= level}
            chosen_level = level
            if len(entity_ids) >= min_candidates:
                break

        # Cap
        if len(entity_ids) > max_candidates:
            ranked = sorted(entity_ids,
                            key=lambda eid: id_best[eid], reverse=True)
            entity_ids = set(ranked[:max_candidates])

        logger.debug(
            "progressive_query: %d/%d bands, %d raw keys, "
            "level=%d → %d ids (target=%d, cap=%d)",
            bands_queried, len(bands), len(band_hits),
            chosen_level, len(entity_ids),
            min_candidates, max_candidates)
        return entity_ids

    def _get_name_variants(self, entity: Dict[str, Any]) -> List[str]:
        """Extract all name variants from an entity dict."""
        names = []
        primary = entity.get('primary_name')
        if primary:
            names.append(primary)
        for alias in (entity.get('aliases') or []):
            name = alias.get('alias_name') if isinstance(alias, dict) else None
            if name:
                names.append(name)
        return names

    def _score_pair(
        self, query_names: List[str], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Score a query against a candidate using RapidFuzz.

        Computes the best score across all query name × candidate name combinations.
        The composite score is max(token_sort_ratio, token_set_ratio).

        Returns:
            {
                'score': float,       # composite 0-100
                'match_level': str,   # 'high', 'likely', 'possible'
                'detail': {           # best individual scores
                    'ratio': float,
                    'partial_ratio': float,
                    'token_sort_ratio': float,
                    'token_set_ratio': float,
                },
            }
        """
        candidate_names = [candidate['primary_name']]
        candidate_names.extend(candidate.get('alias_names') or [])

        best_score = 0.0
        best_detail = {
            'ratio': 0.0,
            'partial_ratio': 0.0,
            'token_sort_ratio': 0.0,
            'token_set_ratio': 0.0,
        }

        for qn in query_names:
            for cn in candidate_names:
                r = fuzz.ratio(qn, cn)
                pr = fuzz.partial_ratio(qn, cn)
                tsr = fuzz.token_sort_ratio(qn, cn)
                tsetr = fuzz.token_set_ratio(qn, cn)
                composite = max(tsr, tsetr)

                if composite > best_score:
                    best_score = composite
                    best_detail = {
                        'ratio': round(r, 1),
                        'partial_ratio': round(pr, 1),
                        'token_sort_ratio': round(tsr, 1),
                        'token_set_ratio': round(tsetr, 1),
                    }

        return {
            'score': round(best_score, 1),
            'match_level': self._match_level(best_score),
            'detail': best_detail,
        }

    @staticmethod
    def _match_level(score: float) -> str:
        """Determine match level from score."""
        if score >= 90:
            return 'high'
        elif score >= 70:
            return 'likely'
        return 'possible'

    # ------------------------------------------------------------------
    # Phonetic matching (Double Metaphone via jellyfish)
    # ------------------------------------------------------------------

    @staticmethod
    def _phonetic_codes(name: str) -> List[str]:
        """Get phonetic codes for a name using Metaphone and Soundex.

        Encodes each word individually (so multi-word names produce
        codes for each word). Returns deduplicated non-empty codes.
        Both encoders are used to maximize recall.
        """
        codes = set()
        for word in name.split():
            word = word.strip()
            if len(word) < 2:
                continue
            try:
                mp = jellyfish.metaphone(word)
                if mp:
                    codes.add(f"M:{mp}")
                sx = jellyfish.soundex(word)
                if sx:
                    codes.add(f"S:{sx}")
            except Exception:
                pass
        return list(codes)

    def _phonetic_candidates(self, query_names: List[str]) -> Set[str]:
        """Get candidate entity IDs via phonetic LSH (progressive)."""
        minhashes = []
        for name in query_names:
            codes = self._phonetic_codes(name)
            if codes:
                minhashes.append(self._build_minhash(set(codes)))
        if not minhashes:
            return set()
        return self._progressive_query(
            self.phonetic_lsh, minhashes,
            min_candidates=DEFAULT_MIN_CANDIDATES,
            max_candidates=DEFAULT_MAX_CANDIDATES,
            phonetic_keys=True,
        )

    def _phonetic_match(self, query_names: List[str], candidate: Dict[str, Any]) -> bool:
        """Check if any query name shares a phonetic code with any candidate name."""
        query_codes = set()
        for qn in query_names:
            query_codes.update(self._phonetic_codes(qn))
        if not query_codes:
            return False

        candidate_names = [candidate['primary_name']] + (candidate.get('alias_names') or [])
        for cn in candidate_names:
            if cn:
                for code in self._phonetic_codes(cn):
                    if code in query_codes:
                        return True
        return False

    # ------------------------------------------------------------------
    # Typo matching (edit-distance-1 + name index)
    # ------------------------------------------------------------------

    @staticmethod
    def _edit_distance_1(word: str) -> set:
        """Generate all strings within edit distance 1 of word."""
        letters = 'abcdefghijklmnopqrstuvwxyz'
        splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
        deletes    = {L + R[1:]                for L, R in splits if R}
        transposes = {L + R[1] + R[0] + R[2:]  for L, R in splits if len(R) > 1}
        replaces   = {L + c + R[1:]            for L, R in splits if R for c in letters}
        inserts    = {L + c + R                for L, R in splits for c in letters}
        return deletes | transposes | replaces | inserts

    def _build_typo_minhashes(
        self,
        query_names: List[str],
        entity: Dict[str, Any],
        max_variants: int = 50,
    ) -> List[MinHash]:
        """Build MinHash signatures for edit-distance-1 typo variants.

        Generates deletion and transposition variants first (cheapest and
        most common typos), then replacements, stopping at *max_variants*
        to bound Redis I/O in the progressive query.
        """
        all_minhashes: List[MinHash] = []
        for name in query_names:
            words = name.split()
            for word_idx, word in enumerate(words):
                lower_word = word.lower().strip()
                if len(lower_word) < 3 or len(lower_word) > 8:
                    continue
                # Prioritise deletions + transpositions (common typos)
                splits = [(lower_word[:i], lower_word[i:])
                          for i in range(len(lower_word) + 1)]
                variants = (
                    {L + R[1:] for L, R in splits if R}  # deletes
                    | {L + R[1] + R[0] + R[2:] for L, R in splits
                       if len(R) > 1}  # transposes
                )
                for variant in variants:
                    variant_words = list(words)
                    variant_words[word_idx] = variant
                    variant_name = ' '.join(variant_words)
                    shingles = self._name_shingles(variant_name, entity)
                    if shingles:
                        all_minhashes.append(self._build_minhash(shingles))
                    if len(all_minhashes) >= max_variants:
                        return all_minhashes
        return all_minhashes

    def _typo_candidates(self, query_names: List[str], entity: Dict[str, Any]) -> Set[str]:
        """Get candidate entity IDs via typo-variant LSH (progressive)."""
        minhashes = self._build_typo_minhashes(query_names, entity)
        if not minhashes:
            return set()
        return self._progressive_query(
            self.lsh, minhashes,
            min_candidates=DEFAULT_MIN_CANDIDATES,
            max_candidates=DEFAULT_MAX_CANDIDATES,
        )
