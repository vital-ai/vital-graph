"""
Near-duplicate detection for the Entity Registry.

Uses datasketch MinHash LSH for candidate blocking and
RapidFuzz for precise string similarity scoring.

Supports two storage backends:
- In-memory (default): rebuilt on startup from PostgreSQL
- Redis: persistent, shared across workers
"""

import logging
import os
import pickle
from typing import Any, Dict, List, Optional, Set

import jellyfish
from datasketch import MinHash, MinHashLSH
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Default tuning parameters
DEFAULT_NUM_PERM = 128
DEFAULT_LSH_THRESHOLD = 0.3
DEFAULT_SHINGLE_K = 3
DEFAULT_MIN_SCORE = 50.0
DEFAULT_PHONETIC_BONUS = 10.0
DEFAULT_PHONETIC_LSH_THRESHOLD = 0.15


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

    def _create_lsh(self, threshold: float, storage_config: Optional[Dict[str, Any]] = None) -> MinHashLSH:
        """Create a MinHashLSH instance."""
        kwargs: Dict[str, Any] = {
            'threshold': threshold,
            'num_perm': self.num_perm,
        }
        if storage_config:
            kwargs['storage_config'] = storage_config
        return MinHashLSH(**kwargs)

    def _phonetic_storage_config(self) -> Optional[Dict[str, Any]]:
        """Build storage config for the phonetic LSH with a distinct Redis namespace."""
        if not self.storage_config:
            return None
        config = dict(self.storage_config)
        base = config.get('basename', b'dedup')
        if isinstance(base, str):
            base = base.encode()
        config['basename'] = base + b'_phonetic'
        return config

    @classmethod
    def from_env(cls) -> 'EntityDedupIndex':
        """Create an EntityDedupIndex from environment variables.

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
        backend = os.environ.get('ENTITY_DEDUP_BACKEND', 'memory').lower()
        num_perm = int(os.environ.get('ENTITY_DEDUP_NUM_PERM', str(DEFAULT_NUM_PERM)))
        threshold = float(os.environ.get('ENTITY_DEDUP_THRESHOLD', str(DEFAULT_LSH_THRESHOLD)))

        storage_config = None
        if backend == 'redis':
            redis_host = os.environ.get('ENTITY_DEDUP_REDIS_HOST', 'localhost')
            redis_port = int(os.environ.get('ENTITY_DEDUP_REDIS_PORT', '6379'))
            redis_params = {'host': redis_host, 'port': redis_port}

            # Optional auth (MemoryDB ACL / ElastiCache AUTH)
            redis_username = os.environ.get('ENTITY_DEDUP_REDIS_USERNAME')
            redis_password = os.environ.get('ENTITY_DEDUP_REDIS_PASSWORD')
            if redis_username:
                redis_params['username'] = redis_username
            if redis_password:
                redis_params['password'] = redis_password

            # TLS (required for MemoryDB)
            use_ssl = os.environ.get('ENTITY_DEDUP_REDIS_SSL', 'false').lower() in ('true', '1', 'yes')
            if use_ssl:
                redis_params['ssl'] = True
                redis_params['ssl_cert_reqs'] = None  # MemoryDB uses Amazon-managed certs

            env_name = os.environ.get('VITALGRAPH_ENVIRONMENT', '').strip().lower()
            basename = f"{env_name}_dedup" if env_name else 'dedup'

            storage_config = {
                'type': 'redis',
                'basename': basename.encode(),
                'redis': redis_params,
            }
            logger.info(f"Entity dedup using Redis backend: {redis_host}:{redis_port} "
                         f"(ssl={use_ssl}, env='{env_name or '(none)'}')")
        else:
            logger.info("Entity dedup using in-memory backend")

        return cls(num_perm=num_perm, threshold=threshold, storage_config=storage_config)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def clear_index(self):
        """Wipe the LSH index and entity cache, creating a fresh empty state.

        For in-memory backend: simply replaces the LSH object.
        For Redis backend: creates a new LSH (datasketch clears Redis keys
        associated with the previous index prefix automatically on new init).
        """
        self.lsh = self._create_lsh(self.threshold, self.storage_config)
        self.phonetic_lsh = self._create_lsh(
            self.phonetic_threshold, self._phonetic_storage_config(),
        )
        self._entity_cache.clear()
        self._initialized = False
        logger.info("Dedup index cleared")

    async def initialize(self, pool, since=None, chunk_size: int = 5000) -> int:
        """Load entities from the database and build/update the LSH index.

        Uses a single bulk query (entity + aliases via LEFT JOIN) and processes
        rows in chunks to stay memory-efficient at scale (10M+ entities).

        For persistent backends (Redis / MemoryDB), also removes stale entries
        that exist in the index but no longer exist as active entities in
        PostgreSQL. For the in-memory backend this is a no-op since the index
        starts empty on each process start.

        Args:
            pool: asyncpg connection pool.
            since: Optional datetime — if provided, only sync entities whose
                   updated_time >= since (incremental sync). Full sync if None.
            chunk_size: Number of entity rows to fetch per chunk.

        Returns:
            Number of entities indexed.
        """
        import time as _time
        start = _time.time()

        # Track IDs that existed in the index before this sync (for stale detection)
        pre_existing_ids = set(self._entity_cache.keys())

        # Build the bulk query: entities LEFT JOIN aliases in one round-trip.
        # Rows are ordered by entity_id so we can group sequentially.
        if since is not None:
            entity_sql = (
                "SELECT e.entity_id, e.primary_name, et.type_key, e.country, e.region, e.locality, "
                "ea.alias_name "
                "FROM entity e "
                "JOIN entity_type et ON et.type_id = e.entity_type_id "
                "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                "AND ea.status != 'retracted' "
                "WHERE e.status != 'deleted' AND e.updated_time >= $1 "
                "ORDER BY e.entity_id"
            )
            query_args = [since]
        else:
            entity_sql = (
                "SELECT e.entity_id, e.primary_name, et.type_key, e.country, e.region, e.locality, "
                "ea.alias_name "
                "FROM entity e "
                "JOIN entity_type et ON et.type_id = e.entity_type_id "
                "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                "AND ea.status != 'retracted' "
                "WHERE e.status != 'deleted' "
                "ORDER BY e.entity_id"
            )
            query_args = []

        active_ids = set()
        count = 0
        current_entity_id = None
        current_entity = None

        async with pool.acquire() as conn:
            # Use a cursor for chunked streaming — avoids loading all rows at once
            async with conn.transaction():
                cursor = await conn.cursor(entity_sql, *query_args)

                while True:
                    rows = await cursor.fetch(chunk_size)
                    if not rows:
                        break

                    for row in rows:
                        entity_id = row['entity_id']

                        if entity_id != current_entity_id:
                            # Flush previous entity
                            if current_entity_id is not None:
                                try:
                                    self.add_entity(current_entity_id, current_entity)
                                    count += 1
                                except Exception as e:
                                    logger.warning(f"Failed to index entity {current_entity_id}: {e}")

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

        # Flush last entity
        if current_entity_id is not None:
            try:
                self.add_entity(current_entity_id, current_entity)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to index entity {current_entity_id}: {e}")

        # Remove stale entries (only meaningful for full sync on persistent backends)
        if since is None:
            stale_ids = pre_existing_ids - active_ids
            for stale_id in stale_ids:
                self.remove_entity(stale_id)
            if stale_ids:
                logger.info(f"Removed {len(stale_ids)} stale entities from dedup index")

        self._initialized = True
        duration = _time.time() - start
        logger.info(f"Entity dedup index: {count:,} entities indexed in {duration:.1f}s"
                     f"{' (incremental)' if since else ' (full)'}")
        return count

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

    def add_entity(self, entity_id: str, entity: Dict[str, Any]):
        """Add or update an entity in the LSH index.

        Each name variant (primary_name + aliases) is indexed as a separate
        LSH entry so that short names like 'IBM' get their own MinHash and
        match queries with high Jaccard similarity.

        Args:
            entity_id: The entity ID.
            entity: Entity dict with primary_name, aliases, country, region, locality.
        """
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
                self.lsh.insert(lsh_key, mh)
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

        # Insert into phonetic LSH (one entry per name variant, phonetic codes as shingles)
        for idx_p, name in enumerate(all_names):
            codes = self._phonetic_codes(name)
            if not codes:
                continue
            mh = self._build_minhash(set(codes))
            p_key = self._phonetic_lsh_key(entity_id, idx_p)
            try:
                self.phonetic_lsh.insert(p_key, mh)
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

        # Phase 1: Candidate retrieval (union of all methods)
        candidate_ids = set()

        # 1a. MinHash LSH candidates
        for name in query_names:
            shingles = self._name_shingles(name, entity)
            if not shingles:
                continue
            mh = self._build_minhash(shingles)
            try:
                raw_keys = self.lsh.query(mh)
            except ValueError:
                continue
            for key in raw_keys:
                candidate_ids.add(self._entity_id_from_lsh_key(key))

        # 1b. Phonetic candidates (Double Metaphone code lookup)
        candidate_ids.update(self._phonetic_candidates(query_names))

        # 1c. Typo candidates (edit-distance-1 query variants → primary LSH)
        candidate_ids.update(self._typo_candidates(query_names, entity))

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
        """Get candidate entity IDs via phonetic LSH query."""
        candidates = set()
        for name in query_names:
            codes = self._phonetic_codes(name)
            if not codes:
                continue
            mh = self._build_minhash(set(codes))
            try:
                raw_keys = self.phonetic_lsh.query(mh)
            except ValueError:
                continue
            for key in raw_keys:
                # Extract entity_id from P::entity_id::idx
                candidates.add(self._entity_id_from_lsh_key(key.split('::', 1)[1]))
        return candidates

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

    def _typo_candidates(self, query_names: List[str], entity: Dict[str, Any]) -> Set[str]:
        """Get candidate entity IDs by querying the primary LSH with
        edit-distance-1 variants of the query words.

        For each query name, each word (len 3–8) is varied one edit away.
        The variant word replaces the original in the full name, the result
        is shingled and its MinHash is collected.  All MinHashes are then
        batch-queried against the primary LSH using _batch_query_lsh(),
        which costs O(B) Redis round-trips regardless of variant count
        (B = number of LSH bands, typically ~37).
        """
        all_minhashes: List[MinHash] = []
        for name in query_names:
            words = name.split()
            for word_idx, word in enumerate(words):
                lower_word = word.lower().strip()
                if len(lower_word) < 3 or len(lower_word) > 8:
                    continue
                for variant in self._edit_distance_1(lower_word):
                    variant_words = list(words)
                    variant_words[word_idx] = variant
                    variant_name = ' '.join(variant_words)
                    shingles = self._name_shingles(variant_name, entity)
                    if not shingles:
                        continue
                    all_minhashes.append(self._build_minhash(shingles))

        if not all_minhashes:
            return set()

        raw_keys = self._batch_query_lsh(self.lsh, all_minhashes)
        return {self._entity_id_from_lsh_key(k) for k in raw_keys}
