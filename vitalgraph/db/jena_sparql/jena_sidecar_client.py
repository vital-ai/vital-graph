"""
HTTP client for the Jena SPARQL compiler sidecar.

Sends SPARQL strings to the sidecar's /v1/sparql/compile endpoint
and returns the raw JSON response dict.
"""

import os
import logging
import time
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:7070"
DEFAULT_TIMEOUT = 10.0
MAX_INPUT_BYTES = 1_000_000  # 1 MB


class SidecarClient:
    """
    Synchronous HTTP client for the Jena SPARQL compiler sidecar.

    Usage:
        client = SidecarClient()
        result = client.compile("SELECT ?s WHERE { ?s ?p ?o } LIMIT 10")
        # result is the full JSON dict from the sidecar
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = (
            base_url
            or os.environ.get("SPARQL_COMPILER_URL", DEFAULT_URL)
        )
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        logger.info("SidecarClient: %s (timeout=%.1fs)", self.base_url, self.timeout)

    def close(self):
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def compile(self, sparql: str) -> Dict[str, Any]:
        """
        Send a SPARQL string to the sidecar for parsing and compilation.

        Args:
            sparql: SPARQL query or update string.

        Returns:
            The full JSON response dict from the sidecar. On success the dict
            has ``ok=True`` and ``phases`` containing the parsed/compiled
            artifacts. On parse error ``ok=False`` with ``error`` details.

        Raises:
            ValueError: If the input exceeds the size limit.
            httpx.HTTPStatusError: On non-2xx HTTP responses.
            httpx.RequestError: On connection or timeout errors.
        """
        if not sparql:
            raise ValueError("SPARQL input must be a non-empty string")
        if len(sparql.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(
                f"SPARQL input exceeds {MAX_INPUT_BYTES} byte limit"
            )

        t0 = time.monotonic()
        resp = self._client.post(
            "/v1/sparql/compile",
            json={"sparql": sparql},
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        resp.raise_for_status()
        data = resp.json()

        logger.debug(
            "sidecar compile %.1fms ok=%s hash=%s",
            elapsed_ms,
            data.get("ok"),
            data.get("input", {}).get("sparqlHash", "?"),
        )
        return data


class AsyncSidecarClient:
    """
    Async HTTP client for the Jena SPARQL compiler sidecar.

    Usage:
        client = AsyncSidecarClient()
        result = await client.compile("SELECT ?s WHERE { ?s ?p ?o } LIMIT 10")
        await client.close()
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = (
            base_url
            or os.environ.get("SPARQL_COMPILER_URL", DEFAULT_URL)
        )
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        logger.info("AsyncSidecarClient: %s (timeout=%.1fs)", self.base_url, self.timeout)

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def compile(self, sparql: str) -> Dict[str, Any]:
        """
        Send a SPARQL string to the sidecar for parsing and compilation.

        Args:
            sparql: SPARQL query or update string.

        Returns:
            The full JSON response dict from the sidecar.

        Raises:
            ValueError: If the input exceeds the size limit.
            httpx.HTTPStatusError: On non-2xx HTTP responses.
            httpx.RequestError: On connection or timeout errors.
        """
        if not sparql:
            raise ValueError("SPARQL input must be a non-empty string")
        if len(sparql.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(
                f"SPARQL input exceeds {MAX_INPUT_BYTES} byte limit"
            )

        t0 = time.monotonic()
        resp = await self._client.post(
            "/v1/sparql/compile",
            json={"sparql": sparql},
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        resp.raise_for_status()
        data = resp.json()

        logger.debug(
            "async sidecar compile %.1fms ok=%s hash=%s",
            elapsed_ms,
            data.get("ok"),
            data.get("input", {}).get("sparqlHash", "?"),
        )
        return data
