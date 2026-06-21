"""
PostgreSQL-backed near-duplicate detection for the Entity Registry.

Uses MinHash for signature computation and PostgreSQL tables for LSH
band storage. Replaces the Redis/MemoryDB backend with direct SQL —
all operations are natively async.

Refactored to use shared fuzzy_core.py algorithms and lazy-load
scoring metadata from the database (no in-memory cache rebuild).
"""

import asyncio
import hashlib
import logging
import time as _time_mod
from typing import Any, Dict, List, Optional, Set, Tuple

from datasketch import MinHash

from vitalgraph.vectorization.fuzzy_core import (
    build_band_entries,
    build_band_queries as core_build_band_queries,
    build_minhash,
    build_typo_variants,
    compute_band_hash,
    compute_band_ranges,
    compute_phonetic_codes,
    compute_shingles,
    entity_id_from_lsh_key,
    extract_entity_ids as core_extract_entity_ids,
    make_lsh_key,
    make_phonetic_lsh_key,
    match_level,
    phonetic_match,
    score_pair,
)

from .entity_fuzzy_storage import (
    TABLE_PHONETIC,
    TABLE_PRIMARY,
    PostgreSQLFuzzyStorage,
)

logger = logging.getLogger(__name__)

# Default tuning parameters
DEFAULT_NUM_PERM = 64
DEFAULT_LSH_THRESHOLD = 0.3
DEFAULT_SHINGLE_K = 3
DEFAULT_MIN_SCORE = 50.0
DEFAULT_PHONETIC_BONUS = 10.0
DEFAULT_PHONETIC_LSH_THRESHOLD = 0.3
DEFAULT_MAX_CANDIDATES = 5000
DEFAULT_MIN_CANDIDATES = 20
BULK_BATCH_SIZE = 1000


def compute_fuzzy_hash(entity: Dict[str, Any]) -> str:
    """Compute a deterministic MD5 hash of the fuzzy-relevant fields.

    Fields: type_key, primary_name, country, region, locality, sorted aliases.
    Returns a 32-char hex string.
    """
    parts = [
        (entity.get('type_key') or '').lower().strip(),
        (entity.get('primary_name') or '').lower().strip(),
        (entity.get('country') or '').lower().strip(),
        (entity.get('region') or '').lower().strip(),
        (entity.get('locality') or '').lower().strip(),
    ]
    aliases = []
    for alias in (entity.get('aliases') or []):
        name = alias.get('alias_name') if isinstance(alias, dict) else None
        if name:
            aliases.append(name.lower().strip())
    aliases.sort()
    parts.append(','.join(aliases))
    return hashlib.md5('|'.join(parts).encode('utf-8')).hexdigest()


class EntityFuzzyIndexPG:
    """PostgreSQL-backed near-duplicate detection index.

    Two-layer approach:
    1. MinHash LSH (stored in PostgreSQL tables) for fast candidate retrieval
    2. RapidFuzz for precise scoring of candidates

    All index operations are natively async — no thread offloading needed.
    """

    def __init__(
        self,
        pool,
        num_perm: int = DEFAULT_NUM_PERM,
        threshold: float = DEFAULT_LSH_THRESHOLD,
        shingle_k: int = DEFAULT_SHINGLE_K,
        phonetic_bonus: float = DEFAULT_PHONETIC_BONUS,
        phonetic_threshold: float = DEFAULT_PHONETIC_LSH_THRESHOLD,
    ):
        """Initialize the PostgreSQL-backed fuzzy index.

        Args:
            pool: asyncpg connection pool.
            num_perm: Number of MinHash permutations.
            threshold: Jaccard similarity threshold for primary LSH.
            shingle_k: Character n-gram size.
            phonetic_bonus: Score bonus for phonetic matches.
            phonetic_threshold: Jaccard threshold for phonetic LSH.
        """
        self.pool = pool
        self.storage = PostgreSQLFuzzyStorage(pool)
        self.num_perm = num_perm
        self.threshold = threshold
        self.phonetic_threshold = phonetic_threshold
        self.shingle_k = shingle_k
        self.phonetic_bonus = phonetic_bonus

        # Pre-compute band ranges (determined by num_perm + threshold)
        self.primary_band_ranges = compute_band_ranges(num_perm, threshold)
        self.phonetic_band_ranges = compute_band_ranges(num_perm, phonetic_threshold)

        # In-memory cache: entity_id -> scoring metadata
        # Used for RapidFuzz scoring (avoids DB round-trips during query)
        self._entity_cache: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    @classmethod
    def from_env(cls, pool) -> 'EntityFuzzyIndexPG':
        """Create an EntityFuzzyIndexPG from environment variables.

        Args:
            pool: asyncpg connection pool.

        Reads:
            ENTITY_FUZZY_NUM_PERM: Number of permutations (default 64)
            ENTITY_FUZZY_THRESHOLD: LSH threshold (default 0.3)
        """
        from vitalgraph.config.config_loader import get_scoped_env

        num_perm = int(get_scoped_env('ENTITY_FUZZY_NUM_PERM', str(DEFAULT_NUM_PERM)))
        threshold = float(get_scoped_env('ENTITY_FUZZY_THRESHOLD', str(DEFAULT_LSH_THRESHOLD)))

        logger.info(f"Entity fuzzy using PostgreSQL backend (num_perm={num_perm}, threshold={threshold})")
        return cls(pool=pool, num_perm=num_perm, threshold=threshold)

    @property
    def entity_count(self) -> int:
        """Number of entities currently in the local scoring cache."""
        return len(self._entity_cache)

    async def get_entity_count_db(self) -> int:
        """Get the total number of entities indexed (from PostgreSQL)."""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(DISTINCT entity_key) FROM entity_fuzzy_band"
            )
            return count or 0

    # ------------------------------------------------------------------
    # Entity lifecycle (async)
    # ------------------------------------------------------------------

    async def add_entity(self, entity_id: str, entity: Dict[str, Any]):
        """Add or update an entity in the fuzzy index.

        Computes MinHash band hashes and stores them in PostgreSQL.
        Also updates the in-memory scoring cache.

        Args:
            entity_id: The entity ID.
            entity: Entity dict with primary_name, aliases, country, region, locality.
        """
        # Remove existing entries if present (for updates)
        if entity_id in self._entity_cache:
            await self.remove_entity(entity_id)

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

        # Compute band entries for primary LSH
        primary_entries: List[Tuple[int, bytes, str]] = []
        for idx, name in enumerate(all_names):
            shingles = self._name_shingles(name, entity)
            if not shingles:
                continue
            mh = self._build_minhash(shingles)
            entity_key = self._lsh_key(entity_id, idx)
            for band_id, (start, end) in enumerate(self.primary_band_ranges):
                bh = compute_band_hash(mh.hashvalues, start, end)
                primary_entries.append((band_id, bh, entity_key))

        if not primary_entries:
            return

        # Compute band entries for phonetic LSH
        phonetic_entries: List[Tuple[int, bytes, str]] = []
        for idx, name in enumerate(all_names):
            codes = self._phonetic_codes(name)
            if not codes:
                continue
            mh = self._build_minhash(set(codes))
            entity_key = self._phonetic_lsh_key(entity_id, idx)
            for band_id, (start, end) in enumerate(self.phonetic_band_ranges):
                bh = compute_band_hash(mh.hashvalues, start, end)
                phonetic_entries.append((band_id, bh, entity_key))

        # Write to PostgreSQL
        await self.storage.insert_bands(TABLE_PRIMARY, primary_entries)
        if phonetic_entries:
            await self.storage.insert_bands(TABLE_PHONETIC, phonetic_entries)

        # Store fuzzy hash
        h = compute_fuzzy_hash(entity)
        await self.storage.set_fuzzy_hash(entity_id, h)

        # Update local scoring cache
        self._entity_cache[entity_id] = {
            'primary_name': primary,
            'type_key': entity.get('type_key'),
            'alias_names': alias_names,
            'country': entity.get('country'),
            'region': entity.get('region'),
            'locality': entity.get('locality'),
            '_variant_count': len(all_names),
        }

    async def remove_entity(self, entity_id: str):
        """Remove an entity from all indexes.

        Args:
            entity_id: The entity ID to remove.
        """
        cached = self._entity_cache.get(entity_id)
        variant_count = (cached or {}).get('_variant_count', 1)

        # Build all keys to remove
        primary_keys = [self._lsh_key(entity_id, i) for i in range(variant_count)]
        phonetic_keys = [self._phonetic_lsh_key(entity_id, i) for i in range(variant_count)]

        # Remove from PostgreSQL
        await self.storage.remove_entity_bands(TABLE_PRIMARY, primary_keys)
        await self.storage.remove_entity_bands(TABLE_PHONETIC, phonetic_keys)
        await self.storage.delete_fuzzy_hash(entity_id)

        # Remove from local cache
        self._entity_cache.pop(entity_id, None)

    # ------------------------------------------------------------------
    # Query (async)
    # ------------------------------------------------------------------

    async def get_candidate_ids(
        self,
        entity: Dict[str, Any],
        query_names: Optional[List[str]] = None,
    ) -> Set[str]:
        """Retrieve candidate entity IDs from LSH indexes.

        Uses progressive band queries with early stopping across
        primary LSH, phonetic LSH, and typo-variant lookups.

        Args:
            entity: Dict with primary_name and optional aliases/location.
            query_names: Pre-computed name variants (optimization).

        Returns:
            Set of candidate entity_id strings.
        """
        if query_names is None:
            query_names = self._get_name_variants(entity)
        if not query_names:
            return set()

        # Build MinHashes for primary and phonetic queries
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

        candidate_ids: Set[str] = set()

        # Step 1: Primary LSH progressive query
        if primary_mh:
            band_queries = self._build_band_queries(primary_mh, self.primary_band_ranges)
            hits = await self.storage.query_bands_progressive(
                TABLE_PRIMARY, band_queries,
                min_candidates=DEFAULT_MIN_CANDIDATES,
                max_candidates=DEFAULT_MAX_CANDIDATES,
            )
            candidate_ids = self._extract_entity_ids(hits)

        if len(candidate_ids) >= DEFAULT_MIN_CANDIDATES:
            return candidate_ids

        # Step 2: Phonetic LSH progressive query
        if phonetic_mh:
            band_queries = self._build_band_queries(phonetic_mh, self.phonetic_band_ranges)
            hits = await self.storage.query_bands_progressive(
                TABLE_PHONETIC, band_queries,
                min_candidates=DEFAULT_MIN_CANDIDATES,
                max_candidates=DEFAULT_MAX_CANDIDATES,
            )
            ph_ids = self._extract_entity_ids(hits, phonetic_keys=True)
            candidate_ids.update(ph_ids)

        if len(candidate_ids) >= DEFAULT_MIN_CANDIDATES:
            return candidate_ids

        # Step 3: Typo variants progressive query
        typo_mh = self._build_typo_minhashes(query_names, entity, max_variants=50)
        if typo_mh:
            band_queries = self._build_band_queries(typo_mh, self.primary_band_ranges)
            hits = await self.storage.query_bands_progressive(
                TABLE_PRIMARY, band_queries,
                min_candidates=DEFAULT_MIN_CANDIDATES,
                max_candidates=DEFAULT_MAX_CANDIDATES,
            )
            typo_ids = self._extract_entity_ids(hits)
            candidate_ids.update(typo_ids)

        return candidate_ids

    async def find_similar(
        self,
        entity: Dict[str, Any],
        limit: int = 10,
        min_score: float = DEFAULT_MIN_SCORE,
        exclude_ids: Optional[set] = None,
        type_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find entities similar to the given entity.

        Args:
            entity: Dict with primary_name, aliases, country/region/locality.
            limit: Maximum number of results.
            min_score: Minimum composite score (0-100).
            exclude_ids: Entity IDs to exclude from results.
            type_key: Optional entity type filter.

        Returns:
            List of scored candidate dicts, sorted by score descending.
        """
        exclude_ids = exclude_ids or set()
        query_names = self._get_name_variants(entity)
        if not query_names:
            return []

        candidate_ids = await self.get_candidate_ids(entity, query_names=query_names)

        # Phase 2: Lazy-load scoring metadata from DB for candidates
        # Try local cache first, fall back to DB
        candidate_data = await self._load_candidate_data(
            candidate_ids - exclude_ids, type_key=type_key
        )

        # Phase 3: RapidFuzz scoring + phonetic bonus
        results = []
        for cid, cached in candidate_data.items():
            score_result = score_pair(query_names, self._candidate_names(cached))
            score_val = score_result.score

            candidate_names = self._candidate_names(cached)
            is_phonetic = phonetic_match(query_names, candidate_names)
            if is_phonetic and self.phonetic_bonus > 0:
                score_val = min(score_val + self.phonetic_bonus, 100.0)

            if score_val >= min_score:
                results.append({
                    'entity_id': cid,
                    'primary_name': cached['primary_name'],
                    'type_key': cached.get('type_key'),
                    'score': round(score_val, 1),
                    'match_level': match_level(score_val),
                    'score_detail': {
                        **score_result.detail,
                        'phonetic_match': is_phonetic,
                    },
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    async def _load_candidate_data(
        self,
        candidate_ids: Set[str],
        type_key: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Lazy-load scoring metadata for candidate entities.

        Checks the local cache first; fetches missing entities from
        the database to avoid full cache rebuilds on restart.
        """
        if not candidate_ids:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        missing_ids: List[str] = []

        for cid in candidate_ids:
            cached = self._entity_cache.get(cid)
            if cached is not None:
                if type_key and cached.get('type_key') != type_key:
                    continue
                result[cid] = cached
            else:
                missing_ids.append(cid)

        if not missing_ids:
            return result

        # Lazy-load from PostgreSQL
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT e.entity_id, e.primary_name, et.type_key, "
                "e.country, e.region, e.locality, ea.alias_name "
                "FROM entity e "
                "JOIN entity_type et ON et.type_id = e.entity_type_id "
                "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                "AND ea.status != 'retracted' "
                "WHERE e.status != 'deleted' AND e.entity_id = ANY($1)",
                missing_ids,
            )

        # Group by entity_id
        loaded: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            eid = row['entity_id']
            if eid not in loaded:
                loaded[eid] = {
                    'primary_name': row['primary_name'],
                    'type_key': row['type_key'],
                    'alias_names': [],
                    'country': row['country'],
                    'region': row['region'],
                    'locality': row['locality'],
                }
            alias = row['alias_name']
            if alias:
                loaded[eid]['alias_names'].append(alias)

        # Cache loaded entities and filter by type
        for eid, data in loaded.items():
            self._entity_cache[eid] = data
            if type_key and data.get('type_key') != type_key:
                continue
            result[eid] = data

        return result

    @staticmethod
    def _candidate_names(cached: Dict[str, Any]) -> List[str]:
        """Extract all name variants from cached entity data."""
        names = []
        if cached.get('primary_name'):
            names.append(cached['primary_name'])
        names.extend(cached.get('alias_names') or [])
        return names

    async def find_similar_by_name(
        self,
        name: str,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        type_key: Optional[str] = None,
        limit: int = 10,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> List[Dict[str, Any]]:
        """Find similar entities by name string."""
        entity = {
            'primary_name': name,
            'country': country,
            'region': region,
            'locality': locality,
        }
        return await self.find_similar(entity, limit=limit, min_score=min_score, type_key=type_key)

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

        Used by the async mixin where candidate data is fetched from
        PostgreSQL on demand.
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

            cand_names = self._candidate_names(cached)
            score_result = score_pair(query_names, cand_names)
            score_val = score_result.score

            is_phonetic = phonetic_match(query_names, cand_names)
            if is_phonetic and self.phonetic_bonus > 0:
                score_val = min(score_val + self.phonetic_bonus, 100.0)

            if score_val >= min_score:
                results.append({
                    'entity_id': cid,
                    'primary_name': cached['primary_name'],
                    'type_key': cached.get('type_key'),
                    'score': round(score_val, 1),
                    'match_level': match_level(score_val),
                    'score_detail': {
                        **score_result.detail,
                        'phonetic_match': is_phonetic,
                    },
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Initialization (bulk load from PostgreSQL entity tables)
    # ------------------------------------------------------------------

    async def initialize(self, pool=None, since=None, chunk_size: int = 5000,
                         skip_lock: bool = False) -> int:
        """Load entities from the database and build the LSH index.

        For full rebuild: truncates band tables, streams all entities,
        computes MinHash bands, bulk inserts via COPY.

        For incremental (since != None): only processes recently updated
        entities.

        Args:
            pool: Optional pool override (uses self.pool if None).
            since: Optional datetime for incremental sync.
            chunk_size: Entities per batch for bulk insert.
            skip_lock: If True, skip advisory lock.

        Returns:
            Number of entities indexed.
        """
        pool = pool or self.pool

        if not skip_lock:
            acquired = await self.storage.try_advisory_lock()
            if not acquired:
                raise RuntimeError("Could not acquire advisory lock for fuzzy initialize")

        try:
            return await self._do_initialize(pool, since=since, chunk_size=chunk_size)
        finally:
            if not skip_lock:
                await self.storage.release_advisory_lock()

    async def _do_initialize(self, pool, since=None, chunk_size: int = 5000) -> int:
        """Inner initialization logic."""
        start = _time_mod.time()

        # For full rebuild, truncate tables first
        if since is None:
            await self.storage.truncate_all()
            self._entity_cache.clear()

        count = 0
        current_entity_id = None
        current_entity = None

        # Buffers for bulk insert
        primary_buffer: List[Tuple[int, bytes, str]] = []
        phonetic_buffer: List[Tuple[int, bytes, str]] = []
        hash_buffer: Dict[str, str] = {}

        PAGE_SIZE = 50000
        last_entity_id = ''

        while True:
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
                    # Process previous entity
                    if current_entity_id is not None and current_entity is not None:
                        self._compute_entity_bands(
                            current_entity_id, current_entity,
                            primary_buffer, phonetic_buffer, hash_buffer,
                        )
                        count += 1

                    # Flush buffers when large enough
                    if len(primary_buffer) >= chunk_size * 20:
                        await self._flush_buffers(
                            primary_buffer, phonetic_buffer, hash_buffer,
                            use_copy=(since is None),
                        )
                        if count % 10000 == 0:
                            elapsed = _time_mod.time() - start
                            rate = count / elapsed if elapsed > 0 else 0
                            logger.info(f"  ... {count:,} entities indexed ({rate:.0f}/s)")

                    # Start new entity
                    current_entity_id = entity_id
                    current_entity = {
                        'entity_id': entity_id,
                        'primary_name': row['primary_name'],
                        'type_key': row['type_key'],
                        'country': row['country'],
                        'region': row['region'],
                        'locality': row['locality'],
                        'aliases': [],
                    }

                # Append alias
                alias_name = row['alias_name']
                if alias_name and current_entity is not None:
                    current_entity['aliases'].append({'alias_name': alias_name})

            last_entity_id = rows[-1]['entity_id']
            if len(rows) < PAGE_SIZE:
                break

        # Process last entity
        if current_entity_id is not None and current_entity is not None:
            self._compute_entity_bands(
                current_entity_id, current_entity,
                primary_buffer, phonetic_buffer, hash_buffer,
            )
            count += 1

        # Final flush
        if primary_buffer or phonetic_buffer or hash_buffer:
            await self._flush_buffers(
                primary_buffer, phonetic_buffer, hash_buffer,
                use_copy=(since is None),
            )

        self._initialized = True
        duration = _time_mod.time() - start
        logger.info(
            f"Entity fuzzy index (PG): {count:,} entities indexed in {duration:.1f}s"
            f"{' (incremental)' if since else ' (full)'}"
        )
        return count

    def _compute_entity_bands(
        self,
        entity_id: str,
        entity: Dict[str, Any],
        primary_buffer: List[Tuple[int, bytes, str]],
        phonetic_buffer: List[Tuple[int, bytes, str]],
        hash_buffer: Dict[str, str],
    ):
        """Compute band hashes for an entity and append to buffers.

        Pure CPU work — no I/O.
        """
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
            entity_key = self._lsh_key(entity_id, idx)
            for band_id, (start, end) in enumerate(self.primary_band_ranges):
                bh = compute_band_hash(mh.hashvalues, start, end)
                primary_buffer.append((band_id, bh, entity_key))
            variant_count += 1

        if variant_count == 0:
            return

        # Phonetic bands
        for idx, name in enumerate(all_names):
            codes = self._phonetic_codes(name)
            if not codes:
                continue
            mh = self._build_minhash(set(codes))
            entity_key = self._phonetic_lsh_key(entity_id, idx)
            for band_id, (start, end) in enumerate(self.phonetic_band_ranges):
                bh = compute_band_hash(mh.hashvalues, start, end)
                phonetic_buffer.append((band_id, bh, entity_key))

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

        # Fuzzy hash
        hash_buffer[entity_id] = compute_fuzzy_hash(entity)

    async def _flush_buffers(
        self,
        primary_buffer: List[Tuple[int, bytes, str]],
        phonetic_buffer: List[Tuple[int, bytes, str]],
        hash_buffer: Dict[str, str],
        use_copy: bool = False,
    ):
        """Flush accumulated band entries to PostgreSQL."""
        if primary_buffer:
            if use_copy:
                await self.storage.insert_bands_copy(TABLE_PRIMARY, primary_buffer)
            else:
                await self.storage.insert_bands(TABLE_PRIMARY, primary_buffer)
            primary_buffer.clear()

        if phonetic_buffer:
            if use_copy:
                await self.storage.insert_bands_copy(TABLE_PHONETIC, phonetic_buffer)
            else:
                await self.storage.insert_bands(TABLE_PHONETIC, phonetic_buffer)
            phonetic_buffer.clear()

        if hash_buffer:
            await self.storage.set_fuzzy_hashes_batch(hash_buffer)
            hash_buffer.clear()

    async def clear_index(self):
        """Wipe all fuzzy tables and local cache."""
        acquired = await self.storage.try_advisory_lock()
        if not acquired:
            raise RuntimeError("Could not acquire advisory lock for clear_index")
        try:
            await self.storage.truncate_all()
            self._entity_cache.clear()
            self._initialized = False
            logger.info("Fuzzy index cleared (PostgreSQL)")
        finally:
            await self.storage.release_advisory_lock()

    # ------------------------------------------------------------------
    # Internal: band query helpers
    # ------------------------------------------------------------------

    def _build_band_queries(
        self,
        minhashes: List[MinHash],
        band_ranges: List[Tuple[int, int]],
    ) -> List[Tuple[int, List[bytes]]]:
        """Build band query parameters from MinHash signatures.

        For each band, computes the band hash for every MinHash and
        groups them into a single query.

        Returns:
            List of (band_id, [hash1, hash2, ...]) tuples.
        """
        queries = []
        for band_id, (start, end) in enumerate(band_ranges):
            hashes = []
            for mh in minhashes:
                bh = compute_band_hash(mh.hashvalues, start, end)
                hashes.append(bh)
            queries.append((band_id, hashes))
        return queries

    def _extract_entity_ids(
        self,
        hits: Dict[str, int],
        phonetic_keys: bool = False,
        min_candidates: int = DEFAULT_MIN_CANDIDATES,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> Set[str]:
        """Extract entity IDs from band hit counts with adaptive threshold.

        Applies the same adaptive filter logic as the original
        progressive_query: strict → relaxed until min_candidates reached.
        """
        if not hits:
            return set()

        def _extract_eid(k: str) -> str:
            if phonetic_keys and '::' in k:
                k = k.split('::', 1)[1]
            return self._entity_id_from_lsh_key(k)

        # Map entity_id → best hit count across all its variants
        id_best: Dict[str, int] = {}
        for k, cnt in hits.items():
            eid = _extract_eid(k)
            if cnt > id_best.get(eid, 0):
                id_best[eid] = cnt

        if not id_best:
            return set()

        # Adaptive filter: strict → relaxed
        max_level = max(id_best.values())
        min_level = 1
        entity_ids: Set[str] = set()

        for level in range(max_level, min_level - 1, -1):
            entity_ids = {eid for eid, cnt in id_best.items() if cnt >= level}
            if len(entity_ids) >= min_candidates:
                break

        # Cap
        if len(entity_ids) > max_candidates:
            ranked = sorted(entity_ids, key=lambda eid: id_best[eid], reverse=True)
            entity_ids = set(ranked[:max_candidates])

        return entity_ids

    # ------------------------------------------------------------------
    # Internal: shingling, MinHash, keys (delegates to fuzzy_core)
    # ------------------------------------------------------------------

    def _name_shingles(self, name: str, entity: Dict[str, Any]) -> set:
        """Build shingles for a single name variant, including location tokens."""
        context_tokens = {}
        for field in ('country', 'region', 'locality'):
            val = entity.get(field)
            if val:
                context_tokens[field] = val
        return compute_shingles(name, self.shingle_k, context_tokens=context_tokens)

    def _build_minhash(self, shingles: set) -> MinHash:
        """Build a MinHash signature from a shingle set."""
        return build_minhash(shingles, self.num_perm)

    @staticmethod
    def _lsh_key(entity_id: str, idx: int) -> str:
        """Compound LSH key: entity_id::variant_index."""
        return make_lsh_key(entity_id, idx)

    @staticmethod
    def _entity_id_from_lsh_key(lsh_key: str) -> str:
        """Extract entity_id from a compound LSH key."""
        return entity_id_from_lsh_key(lsh_key)

    @staticmethod
    def _phonetic_lsh_key(entity_id: str, idx: int) -> str:
        """Compound phonetic LSH key: P::entity_id::variant_index."""
        return make_phonetic_lsh_key(entity_id, idx)

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

    # ------------------------------------------------------------------
    # Internal: scoring (delegates to fuzzy_core)
    # ------------------------------------------------------------------

    def _score_pair(
        self, query_names: List[str], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Score a query against a candidate using RapidFuzz (via fuzzy_core)."""
        candidate_names = self._candidate_names(candidate)
        result = score_pair(query_names, candidate_names)
        return {
            'score': result.score,
            'match_level': result.match_level,
            'detail': result.detail,
        }

    @staticmethod
    def _match_level(score: float) -> str:
        """Determine match level from score."""
        return match_level(score)

    # ------------------------------------------------------------------
    # Internal: phonetic matching (delegates to fuzzy_core)
    # ------------------------------------------------------------------

    @staticmethod
    def _phonetic_codes(name: str) -> List[str]:
        """Get phonetic codes for a name using Metaphone and Soundex."""
        return compute_phonetic_codes(name)

    def _phonetic_match(self, query_names: List[str], candidate: Dict[str, Any]) -> bool:
        """Check if any query name shares a phonetic code with any candidate name."""
        candidate_names = self._candidate_names(candidate)
        return phonetic_match(query_names, candidate_names)

    # ------------------------------------------------------------------
    # Internal: typo matching (delegates to fuzzy_core)
    # ------------------------------------------------------------------

    def _build_typo_minhashes(
        self,
        query_names: List[str],
        entity: Dict[str, Any],
        max_variants: int = 50,
    ) -> List[MinHash]:
        """Build MinHash signatures for edit-distance-1 typo variants."""
        return build_typo_variants(
            query_names,
            shingle_k=self.shingle_k,
            num_perm=self.num_perm,
            max_variants=max_variants,
        )
