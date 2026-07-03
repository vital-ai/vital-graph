"""Root conftest — pytest markers, shared fixtures, and DB connection helpers.

Markers
-------
- ``unit``         — fast tests, no external dependencies
- ``conformance``  — DAWG / ARQ SPARQL conformance (needs PostgreSQL)
- ``integration``  — end-to-end through SparqlSQLDbImpl (needs PostgreSQL)
- ``api``          — REST API tests (needs running VitalGraph server)
- ``performance``  — benchmark tests (not gating)
- ``slow``         — tests taking > 10 s
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast tests, no external deps")
    config.addinivalue_line("markers", "conformance: DAWG/ARQ SPARQL conformance")
    config.addinivalue_line("markers", "integration: needs PostgreSQL")
    config.addinivalue_line("markers", "api: needs running VitalGraph server")
    config.addinivalue_line("markers", "performance: benchmark tests")
    config.addinivalue_line("markers", "slow: tests taking >10s")
