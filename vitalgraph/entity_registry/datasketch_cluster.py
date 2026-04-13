"""
Redis Cluster storage backend for datasketch MinHashLSH.

datasketch's built-in Redis storage uses ``redis.Redis`` which doesn't handle
cluster-mode MOVED redirections (required by AWS MemoryDB).  This module
provides clean ``RedisClusterListStorage`` and ``RedisClusterSetStorage``
implementations that use ``redis.RedisCluster`` natively.

Usage::

    from vitalgraph.entity_registry.datasketch_cluster import register_cluster_storage
    register_cluster_storage()  # call once, then use type='redis_cluster'

    storage_config = {
        'type': 'redis_cluster',
        'basename': b'{prod_dedup}',
        'redis': {'host': '...', 'port': 6379, 'ssl': True, ...},
    }
    lsh = MinHashLSH(threshold=0.3, num_perm=128, storage_config=storage_config)
"""

import logging
import os
import random
import string

import redis as redis_lib
from datasketch.storage import OrderedStorage, UnorderedStorage, Storage

logger = logging.getLogger(__name__)

_REGISTERED = False

# Shared RedisCluster client cache — avoids 76 separate TLS handshakes
# when datasketch creates ~38 storage objects per LSH index.
_client_cache: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_name(length: int) -> bytes:
    return ''.join(random.choices(string.ascii_lowercase, k=length)).encode()


def _parse_config(config: dict) -> dict:
    """Parse a datasketch redis config dict, resolving env var references."""
    cfg = {}
    for key, value in config.items():
        if isinstance(value, dict) and 'env' in value:
            value = os.getenv(value['env'], value.get('default', None))
        cfg[key] = value
    return cfg


def _get_shared_client(redis_params: dict) -> redis_lib.RedisCluster:
    """Return a shared ``RedisCluster`` client for the given connection params.

    All storage objects with the same host/port/credentials reuse one client,
    avoiding expensive repeated TLS+cluster handshakes.
    """
    # Build a hashable cache key from the connection params
    cache_key = tuple(sorted(
        (k, v) for k, v in redis_params.items()
        if k not in ('cluster',)
    ))
    if cache_key not in _client_cache:
        params = dict(redis_params)
        params.pop('cluster', None)
        _client_cache[cache_key] = redis_lib.RedisCluster(**params)
        logger.debug("Created shared RedisCluster client")
    return _client_cache[cache_key]


# ---------------------------------------------------------------------------
# Auto-flushing pipeline buffer
# ---------------------------------------------------------------------------

class ClusterBuffer:
    """Auto-flushing write buffer backed by ``ClusterPipeline``.

    When the number of queued commands reaches ``buffer_size``, the pipeline
    is automatically executed and reset.  This mirrors the role of datasketch's
    ``RedisBuffer`` but works with ``redis.RedisCluster``.
    """

    def __init__(self, client: redis_lib.RedisCluster, buffer_size: int = 50000):
        self._client = client
        self._buffer_size = buffer_size
        self._pipe = client.pipeline()
        self._count = 0

    @property
    def buffer_size(self):
        return self._buffer_size

    @buffer_size.setter
    def buffer_size(self, value):
        self._buffer_size = value

    def _auto_flush(self):
        if self._count >= self._buffer_size:
            self.execute()

    def execute(self):
        if self._count > 0:
            try:
                return self._pipe.execute()
            finally:
                self._pipe = self._client.pipeline()
                self._count = 0
        return []

    # -- Redis commands used by datasketch storage ----------------------------

    def hset(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.hset(*args, **kwargs)
        self._count += 1

    def sadd(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.sadd(*args, **kwargs)
        self._count += 1

    def rpush(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.rpush(*args, **kwargs)
        self._count += 1

    def hdel(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.hdel(*args, **kwargs)
        self._count += 1

    def delete(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.delete(*args, **kwargs)
        self._count += 1

    def srem(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.srem(*args, **kwargs)
        self._count += 1

    def lrem(self, *args, **kwargs):
        self._auto_flush()
        self._pipe.lrem(*args, **kwargs)
        self._count += 1


# ---------------------------------------------------------------------------
# Storage implementations
# ---------------------------------------------------------------------------

class _RedisClusterBase:
    """Shared init and utilities for cluster-backed storage."""

    def __init__(self, config, name=None):
        self.config = config
        self._buffer_size = 50000
        redis_param = _parse_config(config['redis'])
        self._redis = _get_shared_client(redis_param)
        self._buffer = ClusterBuffer(self._redis, buffer_size=self._buffer_size)
        self._name = name if name is not None else _random_name(11)

    @property
    def buffer_size(self):
        return self._buffer_size

    @buffer_size.setter
    def buffer_size(self, value):
        self._buffer_size = value
        self._buffer.buffer_size = value

    def redis_key(self, key):
        if isinstance(key, str):
            key = key.encode()
        if isinstance(self._name, str):
            return self._name.encode() + key
        return self._name + key

    def keys(self):
        return self._redis.hkeys(self._name)

    def status(self):
        s = _parse_config(self.config['redis'])
        s.update(Storage.status(self))
        return s

    def size(self):
        return self._redis.hlen(self._name)

    def has_key(self, key):
        return self._redis.hexists(self._name, key)

    def empty_buffer(self):
        self._buffer.execute()
        self.__init__(self.config, name=self._name)


class RedisClusterListStorage(OrderedStorage, _RedisClusterBase):
    """Ordered (list-backed) storage using ``redis.RedisCluster``."""

    def __init__(self, config, name=None):
        _RedisClusterBase.__init__(self, config, name=name)

    def keys(self):
        return self._redis.hkeys(self._name)

    def size(self):
        return self._redis.hlen(self._name)

    def has_key(self, key):
        return self._redis.hexists(self._name, key)

    def get(self, key):
        return self._redis.lrange(self.redis_key(key), 0, -1)

    def getmany(self, *keys):
        pipe = self._redis.pipeline()
        for key in keys:
            pipe.lrange(self.redis_key(key), 0, -1)
        return pipe.execute()

    def remove(self, *keys, **kwargs):
        buffer = kwargs.pop('buffer', False)
        r = self._buffer if buffer else self._redis
        r.hdel(self._name, *keys)
        for k in keys:
            r.delete(self.redis_key(k))

    def remove_val(self, key, val, **kwargs):
        buffer = kwargs.pop('buffer', False)
        r = self._buffer if buffer else self._redis
        redis_key = self.redis_key(key)
        r.lrem(redis_key, 0, val)
        if not buffer and not self._redis.exists(redis_key):
            self._redis.hdel(self._name, redis_key)

    def insert(self, key, *vals, **kwargs):
        buffer = kwargs.pop('buffer', False)
        r = self._buffer if buffer else self._redis
        redis_key = self.redis_key(key)
        r.hset(self._name, key, redis_key)
        r.rpush(redis_key, *vals)

    def itemcounts(self):
        pipe = self._redis.pipeline()
        ks = self.keys()
        for k in ks:
            pipe.llen(self.redis_key(k))
        return dict(zip(ks, pipe.execute()))


class RedisClusterSetStorage(UnorderedStorage, _RedisClusterBase):
    """Unordered (set-backed) storage using ``redis.RedisCluster``."""

    def __init__(self, config, name=None):
        _RedisClusterBase.__init__(self, config, name=name)

    def keys(self):
        return self._redis.hkeys(self._name)

    def size(self):
        return self._redis.hlen(self._name)

    def has_key(self, key):
        return self._redis.hexists(self._name, key)

    def get(self, key):
        return self._redis.smembers(self.redis_key(key))

    def getmany(self, *keys):
        pipe = self._redis.pipeline()
        for key in keys:
            pipe.smembers(self.redis_key(key))
        return pipe.execute()

    def remove(self, *keys, **kwargs):
        buffer = kwargs.pop('buffer', False)
        r = self._buffer if buffer else self._redis
        r.hdel(self._name, *keys)
        for k in keys:
            r.delete(self.redis_key(k))

    def remove_val(self, key, val, **kwargs):
        buffer = kwargs.pop('buffer', False)
        r = self._buffer if buffer else self._redis
        redis_key = self.redis_key(key)
        r.srem(redis_key, val)
        if not buffer and not self._redis.exists(redis_key):
            self._redis.hdel(self._name, redis_key)

    def insert(self, key, *vals, **kwargs):
        buffer = kwargs.pop('buffer', False)
        r = self._buffer if buffer else self._redis
        redis_key = self.redis_key(key)
        r.hset(self._name, key, redis_key)
        r.sadd(redis_key, *vals)

    def itemcounts(self):
        pipe = self._redis.pipeline()
        ks = self.keys()
        for k in ks:
            pipe.scard(self.redis_key(k))
        return dict(zip(ks, pipe.execute()))


# ---------------------------------------------------------------------------
# Per-band hash tag distribution
# ---------------------------------------------------------------------------

def distribute_lsh_hash_tags(lsh, prefix: str):
    """Rewrite storage names in an LSH so each band gets its own hash tag.

    By default datasketch puts all keys under one hash tag (the basename),
    pinning everything to a single Redis Cluster slot.  This function
    rewrites each storage object's ``_name`` so that:

    - Band *i* hashtable: ``{prefix_bNN}_bucket_<packed_i>``
    - Keys storage:       ``{prefix_keys}_keys``

    With 37 bands this gives 38 unique hash tags per LSH index, spreading
    load across cluster shards.

    Call this **after** ``MinHashLSH(...)`` construction.
    """
    import struct

    for i, ht in enumerate(lsh.hashtables):
        tag = f'{{{prefix}_b{i:02d}}}'
        ht._name = tag.encode() + b'_bucket_' + struct.pack('>H', i)

    keys_tag = f'{{{prefix}_keys}}'
    lsh.keys._name = keys_tag.encode() + b'_keys'

    logger.debug(
        "Distributed %d band hash tags with prefix '%s'",
        len(lsh.hashtables), prefix,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_cluster_storage():
    """Register ``'redis_cluster'`` as a storage type in datasketch.

    Safe to call multiple times; only registers once.  After calling this,
    ``MinHashLSH(storage_config={'type': 'redis_cluster', ...})`` will use
    the cluster-aware storage classes above.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    import datasketch.storage as ds

    _orig_ordered = ds.ordered_storage
    _orig_unordered = ds.unordered_storage

    def ordered_storage(config, name=None):
        if config['type'] == 'redis_cluster':
            return RedisClusterListStorage(config, name=name)
        return _orig_ordered(config, name=name)

    def unordered_storage(config, name=None):
        if config['type'] == 'redis_cluster':
            return RedisClusterSetStorage(config, name=name)
        return _orig_unordered(config, name=name)

    ds.ordered_storage = ordered_storage
    ds.unordered_storage = unordered_storage
    # MinHashLSH imports these at module level — patch the reference there too
    import datasketch.lsh as lsh_mod
    lsh_mod.ordered_storage = ordered_storage
    lsh_mod.unordered_storage = unordered_storage

    logger.info("datasketch 'redis_cluster' storage type registered")
