"""
Query metrics collection using Redis/MemoryDB.

Records per-request metrics (counts, latency, errors) into Redis HASH keys
bucketed by minute. Keys auto-expire after 24h. A separate rollup job
aggregates these into PostgreSQL for long-term storage.

Supports both standalone Redis and Redis Cluster (AWS MemoryDB).
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Union

import redis as redis_lib

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_SLOW_THRESHOLD_MS = 500
DEFAULT_SLOW_LOG_SIZE = 100
DEFAULT_KEY_TTL = 86400  # 24h


class QueryMetricsCollector:
    """Collects per-request metrics and writes to Redis asynchronously.

    Uses fire-and-forget pipeline writes for minimal latency impact.
    All keys use the {metrics} hash tag to colocate on the same Redis shard.
    """

    def __init__(
        self,
        redis_client: Union[redis_lib.Redis, redis_lib.RedisCluster],
        prefix: str = "metrics",
        slow_threshold_ms: float = DEFAULT_SLOW_THRESHOLD_MS,
        slow_log_size: int = DEFAULT_SLOW_LOG_SIZE,
        key_ttl: int = DEFAULT_KEY_TTL,
    ):
        self._redis = redis_client
        self._prefix = prefix
        self._slow_threshold_ms = slow_threshold_ms
        self._slow_log_size = slow_log_size
        self._key_ttl = key_ttl
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def _key(self, space_id: str, category: str, bucket_ts: int) -> str:
        """Build a Redis key with hash tag for cluster colocation."""
        return f"{{{self._prefix}}}:{space_id}:{category}:{bucket_ts}"

    def _slow_key(self, space_id: str) -> str:
        return f"{{{self._prefix}}}:{space_id}:slow_log"

    def _active_spaces_key(self) -> str:
        return f"{{{self._prefix}}}:active_spaces"

    def record(
        self,
        space_id: str,
        endpoint: str,
        duration_ms: float,
        error: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record a request metric. Fire-and-forget — errors are logged, not raised.

        Args:
            space_id: Space that was accessed.
            endpoint: Classified endpoint name (e.g. 'sparql_query', 'kgentities_list').
            duration_ms: Request duration in milliseconds.
            error: Whether the request resulted in an error.
            metadata: Optional extra data for slow query log (e.g. query text).
        """
        if not self._enabled:
            return

        try:
            minute_ts = int(time.time()) // 60 * 60  # round to minute boundary

            pipe = self._redis.pipeline(transaction=False)

            # Request count
            qpm_key = self._key(space_id, "qpm", minute_ts)
            pipe.hincrby(qpm_key, endpoint, 1)
            pipe.expire(qpm_key, self._key_ttl)

            # Latency: sum and count (for computing avg), plus max
            lat_key = self._key(space_id, "lat", minute_ts)
            pipe.hincrby(lat_key, f"{endpoint}:sum", int(duration_ms))
            pipe.hincrby(lat_key, f"{endpoint}:cnt", 1)
            pipe.expire(lat_key, self._key_ttl)

            # Track max latency via Lua CAS (compare-and-set)
            max_field = f"{endpoint}:max"
            pipe.eval(
                """
                local key = KEYS[1]
                local field = ARGV[1]
                local new_val = tonumber(ARGV[2])
                local cur = tonumber(redis.call("hget", key, field) or "0")
                if new_val > (cur or 0) then
                    redis.call("hset", key, field, new_val)
                end
                return 1
                """,
                1, lat_key, max_field, int(duration_ms)
            )

            # Error count
            if error:
                err_key = self._key(space_id, "err", minute_ts)
                pipe.hincrby(err_key, endpoint, 1)
                pipe.expire(err_key, self._key_ttl)

            # Slow query log
            if duration_ms >= self._slow_threshold_ms:
                slow_entry = {
                    "ts": time.time(),
                    "space_id": space_id,
                    "endpoint": endpoint,
                    "ms": round(duration_ms, 1),
                }
                if metadata:
                    # Truncate large metadata (e.g. query text)
                    for k, v in metadata.items():
                        if isinstance(v, str) and len(v) > 500:
                            slow_entry[k] = v[:500] + "..."
                        else:
                            slow_entry[k] = v

                slow_key = self._slow_key(space_id)
                pipe.lpush(slow_key, json.dumps(slow_entry))
                pipe.ltrim(slow_key, 0, self._slow_log_size - 1)
                pipe.expire(slow_key, self._key_ttl)

            # Track active spaces (for rollup job to know which spaces to scan)
            pipe.sadd(self._active_spaces_key(), space_id)
            pipe.expire(self._active_spaces_key(), self._key_ttl)

            pipe.execute()

        except Exception as e:
            # Never let metrics recording break a request
            logger.debug(f"Metrics record failed (non-fatal): {e}")

    def get_minute_counts(self, space_id: str, minute_ts: int) -> Dict[str, int]:
        """Read request counts for a specific minute bucket."""
        key = self._key(space_id, "qpm", minute_ts)
        raw = self._redis.hgetall(key)
        return {k.decode() if isinstance(k, bytes) else k: int(v)
                for k, v in raw.items()}

    def get_minute_latency(self, space_id: str, minute_ts: int) -> Dict[str, Dict[str, int]]:
        """Read latency data for a specific minute bucket.

        Returns: {endpoint: {sum: int, cnt: int, max: int}}
        """
        key = self._key(space_id, "lat", minute_ts)
        raw = self._redis.hgetall(key)

        result: Dict[str, Dict[str, int]] = {}
        for k, v in raw.items():
            field = k.decode() if isinstance(k, bytes) else k
            # Fields are like "sparql_query:sum", "sparql_query:cnt", "sparql_query:max"
            parts = field.rsplit(":", 1)
            if len(parts) == 2:
                endpoint, metric = parts
                if endpoint not in result:
                    result[endpoint] = {}
                result[endpoint][metric] = int(v)
        return result

    def get_minute_errors(self, space_id: str, minute_ts: int) -> Dict[str, int]:
        """Read error counts for a specific minute bucket."""
        key = self._key(space_id, "err", minute_ts)
        raw = self._redis.hgetall(key)
        return {k.decode() if isinstance(k, bytes) else k: int(v)
                for k, v in raw.items()}

    def get_slow_log(self, space_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Read recent slow queries for a space."""
        key = self._slow_key(space_id)
        raw_entries = self._redis.lrange(key, 0, limit - 1)
        results = []
        for entry in raw_entries:
            try:
                data = json.loads(entry.decode() if isinstance(entry, bytes) else entry)
                results.append(data)
            except (json.JSONDecodeError, AttributeError):
                continue
        return results

    def get_active_spaces(self) -> List[str]:
        """Get list of spaces that have had recent activity."""
        members = self._redis.smembers(self._active_spaces_key())
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def get_realtime_series(
        self, space_id: str, minutes: int = 60
    ) -> Dict[str, Any]:
        """Get time-series data for the last N minutes directly from Redis.

        Returns a structure ready for the API response with per-endpoint series.
        """
        now_minute = int(time.time()) // 60 * 60
        timestamps = []
        endpoint_data: Dict[str, Dict[str, List]] = {}

        for i in range(minutes - 1, -1, -1):
            ts = now_minute - (i * 60)
            timestamps.append(ts)

            counts = self.get_minute_counts(space_id, ts)
            latency = self.get_minute_latency(space_id, ts)
            errors = self.get_minute_errors(space_id, ts)

            # Collect all endpoints seen
            all_endpoints = set(counts.keys()) | set(latency.keys()) | set(errors.keys())

            for ep in all_endpoints:
                if ep not in endpoint_data:
                    endpoint_data[ep] = {
                        "counts": [0] * (minutes - 1 - i),
                        "avg_ms": [0] * (minutes - 1 - i),
                        "max_ms": [0] * (minutes - 1 - i),
                        "errors": [0] * (minutes - 1 - i),
                    }
                endpoint_data[ep]["counts"].append(counts.get(ep, 0))

                lat = latency.get(ep, {})
                cnt = lat.get("cnt", 0)
                avg = int(lat.get("sum", 0) / cnt) if cnt > 0 else 0
                endpoint_data[ep]["avg_ms"].append(avg)
                endpoint_data[ep]["max_ms"].append(lat.get("max", 0))
                endpoint_data[ep]["errors"].append(errors.get(ep, 0))

        # Pad any endpoint series that didn't exist for early minutes
        for ep, data in endpoint_data.items():
            for key in ("counts", "avg_ms", "max_ms", "errors"):
                while len(data[key]) < minutes:
                    data[key].append(0)

        # Compute totals
        total_requests = sum(sum(d["counts"]) for d in endpoint_data.values())
        total_errors = sum(sum(d["errors"]) for d in endpoint_data.values())
        all_avg = [v for d in endpoint_data.values() for v in d["avg_ms"] if v > 0]
        avg_latency = int(sum(all_avg) / len(all_avg)) if all_avg else 0

        return {
            "timestamps": timestamps,
            "series": endpoint_data,
            "totals": {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "avg_latency_ms": avg_latency,
            },
        }

    @classmethod
    def from_env(cls) -> Optional['QueryMetricsCollector']:
        """Create a QueryMetricsCollector from environment variables.

        Returns None if metrics are disabled or Redis is not configured.

        Env vars (scoped by VITALGRAPH_ENVIRONMENT):
            QUERY_METRICS_ENABLED: 'true' (default) or 'false'
            QUERY_METRICS_REDIS_HOST: defaults to ENTITY_FUZZY_REDIS_HOST or 'localhost'
            QUERY_METRICS_REDIS_PORT: defaults to ENTITY_FUZZY_REDIS_PORT or 6379
            QUERY_METRICS_REDIS_USERNAME: optional auth
            QUERY_METRICS_REDIS_PASSWORD: optional auth
            QUERY_METRICS_REDIS_SSL: 'false' (default)
            QUERY_METRICS_REDIS_CLUSTER: 'false' (default)
            QUERY_METRICS_SLOW_THRESHOLD_MS: 500 (default)
        """
        from vitalgraph.config.config_loader import get_scoped_env

        enabled = get_scoped_env('QUERY_METRICS_ENABLED', 'true').lower()
        if enabled in ('false', '0', 'no'):
            logger.info("Query metrics disabled")
            return None

        # Allow sharing config with entity fuzzy Redis
        redis_host = (get_scoped_env('QUERY_METRICS_REDIS_HOST') or
                      get_scoped_env('ENTITY_FUZZY_REDIS_HOST', 'localhost'))
        redis_port = int(get_scoped_env('QUERY_METRICS_REDIS_PORT') or
                         get_scoped_env('ENTITY_FUZZY_REDIS_PORT', '6379'))

        redis_params: Dict[str, Any] = {'host': redis_host, 'port': redis_port}

        # Auth
        redis_username = (get_scoped_env('QUERY_METRICS_REDIS_USERNAME') or
                          get_scoped_env('ENTITY_FUZZY_REDIS_USERNAME') or None)
        redis_password = (get_scoped_env('QUERY_METRICS_REDIS_PASSWORD') or
                          get_scoped_env('ENTITY_FUZZY_REDIS_PASSWORD') or None)
        if redis_username:
            redis_params['username'] = redis_username
        if redis_password:
            redis_params['password'] = redis_password

        # TLS
        use_ssl = (get_scoped_env('QUERY_METRICS_REDIS_SSL') or
                   get_scoped_env('ENTITY_FUZZY_REDIS_SSL', 'false')).lower() in ('true', '1', 'yes')
        if use_ssl:
            redis_params['ssl'] = True
            redis_params['ssl_cert_reqs'] = None

        # Cluster mode
        use_cluster = (get_scoped_env('QUERY_METRICS_REDIS_CLUSTER') or
                       get_scoped_env('ENTITY_FUZZY_REDIS_CLUSTER', 'false')).lower() in ('true', '1', 'yes')

        # Environment-scoped prefix
        env_name = os.environ.get('VITALGRAPH_ENVIRONMENT', '').strip().lower()
        if env_name in ('', 'prod', 'production'):
            prefix = "metrics"
        else:
            prefix = f"{env_name}_metrics"

        slow_threshold = float(get_scoped_env('QUERY_METRICS_SLOW_THRESHOLD_MS', '500'))

        try:
            if use_cluster:
                redis_params['decode_responses'] = False
                client = redis_lib.RedisCluster(**redis_params)
            else:
                redis_params['decode_responses'] = False
                client = redis_lib.Redis(**redis_params)

            # Quick connectivity check
            client.ping()
            logger.info(f"Query metrics Redis connected: {redis_host}:{redis_port} "
                        f"(ssl={use_ssl}, cluster={use_cluster}, prefix='{prefix}')")

        except Exception as e:
            logger.warning(f"Query metrics Redis connection failed (metrics disabled): {e}")
            return None

        return cls(
            redis_client=client,
            prefix=prefix,
            slow_threshold_ms=slow_threshold,
        )
