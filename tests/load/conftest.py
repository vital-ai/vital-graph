"""Fixtures for the load tests, REUSED from the integration suite.

Not copied. `tests/integration/conftest.py` owns the connection settings —
including the `issues/099` correction that made the fixture loaders and the
readers agree on port 5433 — and a second copy of that would drift silently and
end up measuring a different cluster than it seeded.
"""

from __future__ import annotations

from tests.integration.conftest import (  # noqa: F401
    pg_pool, pg_conn,
)
