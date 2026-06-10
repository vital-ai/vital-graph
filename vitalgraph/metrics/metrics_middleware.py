"""
FastAPI middleware that captures per-request metrics.

Extracts space_id from the URL path, classifies the endpoint,
measures duration, and fires off a metric recording to PostgreSQL
via the buffered PostgresMetricsCollector.
"""

import logging
import re
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from vitalgraph.metrics.postgres_metrics_collector import PostgresMetricsCollector

logger = logging.getLogger(__name__)

# Route patterns for endpoint classification and space_id extraction
_SPACE_PATTERNS = [
    # /api/spaces/{space_id}/... endpoints
    (re.compile(r'^/api/spaces/([^/]+)/analytics'), 'space_analytics'),
    (re.compile(r'^/api/spaces/([^/]+)/info'), 'space_info'),
    (re.compile(r'^/api/spaces/([^/]+)/metrics'), 'space_metrics'),
    (re.compile(r'^/api/spaces/([^/]+)$'), 'space_detail'),
    # SPARQL and graph endpoints: /api/graphs/sparql/... (space_id from query param)
    (re.compile(r'^/api/graphs/sparql/query'), 'sparql_query'),
    (re.compile(r'^/api/graphs/graphs'), 'graphs_list'),
    (re.compile(r'^/api/graphs/graph_counts'), 'graph_counts'),
    (re.compile(r'^/api/graphs/graph'), 'graph_op'),
    # Triples endpoint uses query param space_id
    (re.compile(r'^/api/graphs/triples'), None),  # space_id from query param
    # KG entity/frame/relation endpoints
    (re.compile(r'^/api/kg/([^/]+)/entities'), 'kgentities'),
    (re.compile(r'^/api/kg/([^/]+)/frames'), 'kgframes'),
    (re.compile(r'^/api/kg/([^/]+)/relations'), 'kgrelations'),
    (re.compile(r'^/api/kg/([^/]+)/types'), 'kgtypes'),
    (re.compile(r'^/api/kg/([^/]+)/query'), 'kgquery'),
]

# Method-based endpoint refinement
_METHOD_SUFFIX = {
    'GET': '_get',
    'POST': '_create',
    'PUT': '_update',
    'DELETE': '_delete',
    'PATCH': '_update',
}

# Paths to skip entirely (health checks, static assets, etc.)
_SKIP_PREFIXES = ('/api/health', '/api/docs', '/api/openapi', '/static', '/assets')


def classify_request(path: str, method: str, query_params: dict) -> tuple[Optional[str], str]:
    """Classify a request into (space_id, endpoint_name).

    Returns (None, '') for requests that should not be tracked.
    """
    # Skip non-trackable paths
    for prefix in _SKIP_PREFIXES:
        if path.startswith(prefix):
            return None, ''

    # Try pattern matching
    for pattern, base_endpoint in _SPACE_PATTERNS:
        match = pattern.match(path)
        if match:
            space_id = match.group(1) if match.lastindex else query_params.get('space_id')
            endpoint = base_endpoint or 'triples'

            # Refine by HTTP method for CRUD endpoints
            if endpoint in ('kgentities', 'kgframes', 'kgrelations', 'kgtypes', 'triples'):
                suffix = _METHOD_SUFFIX.get(method, '')
                # Distinguish list from get for GET requests
                if method == 'GET' and not path.rstrip('/').split('/')[-1].startswith('{'):
                    suffix = '_list'
                endpoint = endpoint + suffix

            return space_id, endpoint

    # Fallback: check for space_id in query params
    space_id = query_params.get('space_id')
    if space_id:
        # Generic classification from path
        parts = path.strip('/').split('/')
        endpoint = '_'.join(parts[-2:]) if len(parts) >= 2 else path.strip('/')
        return space_id, endpoint

    return None, ''


class MetricsMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that records per-request metrics.

    The collector is read from ``request.app.state.metrics_collector`` so that
    it can be attached after startup without needing a reference to this instance.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        collector: Optional[PostgresMetricsCollector] = getattr(
            request.app.state, 'metrics_collector', None
        )
        if not collector or not collector.enabled:
            return await call_next(request)

        start = time.perf_counter()
        error = False

        try:
            response = await call_next(request)
            if response.status_code >= 400:
                error = True
            return response
        except Exception:
            error = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000

            # Classify request
            query_params = dict(request.query_params)
            space_id, endpoint = classify_request(
                request.url.path, request.method, query_params
            )

            if space_id and endpoint:
                # Build metadata for slow query log
                metadata = None
                if duration_ms >= collector._slow_threshold_ms:
                    metadata = {
                        "method": request.method,
                        "path": request.url.path,
                    }
                    # Include query text for SPARQL queries
                    if 'query' in endpoint:
                        metadata["query_params"] = str(query_params)[:200]

                try:
                    collector.record(
                        space_id=space_id,
                        endpoint=endpoint,
                        duration_ms=duration_ms,
                        error=error,
                        metadata=metadata,
                    )
                except Exception as e:
                    logger.debug(f"Metrics middleware record failed: {e}")
