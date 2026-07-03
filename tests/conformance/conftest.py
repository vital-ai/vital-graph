"""Conformance test configuration.

Provides fixtures and markers for DAWG/ARQ SPARQL conformance tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add vitalgraph_sparql_sql_dev to import path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEV_PKG = _PROJECT_ROOT / "vitalgraph_sparql_sql_dev"
if str(_DEV_PKG) not in sys.path:
    sys.path.insert(0, str(_DEV_PKG))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "dawg: DAWG SPARQL 1.1 conformance test"
    )
    config.addinivalue_line(
        "markers", "jena_arq: Apache Jena ARQ test suite"
    )
    config.addinivalue_line(
        "markers", "sql_v2: Requires PostgreSQL + Jena sidecar"
    )
