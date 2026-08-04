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


# ---------------------------------------------------------------------------
# Strict unresolved-variable mode — issue 028 ratchet
#
# In production, a variable the emitter cannot resolve compiles to the literal
# NULL. That is the SPARQL-specified result when the variable is legitimately
# unbound, and silently widening when the translator merely failed to wire it
# (issues 023 and 027 were both the latter, and both produced whole-graph
# deletes). The emitter cannot yet tell the two apart, so production stays
# permissive — see generator.set_strict_unresolved_vars.
#
# Under pytest it raises instead. Every legitimate occurrence in the corpus is
# listed below, so a NEW unresolvable variable — i.e. a new translation gap —
# fails the suite instead of being swallowed.
#
# If a test lands here: work out which case it is. A variable that is genuinely
# unbound (bound nowhere, or only in a scope SPARQL evaluates independently)
# gets an allowlist entry WITH A REASON. Anything else is a translation gap —
# fix the wiring, do not add an entry.
# ---------------------------------------------------------------------------

_STRICT_UNRESOLVED_ALLOWLIST = {
    # W3C DAWG cases where the variable is legitimately unbound. Each is
    # documented as such by the test material itself.
    "tests/conformance/test_dawg_sql_v2.py::TestDAWGSqlV2::test_sql_v2[bind/bind04 - BIND]":
        "BIND(?nova AS ?z) — ?nova is bound nowhere in the query; per SPARQL "
        "1.1 §16.2 BIND of an unbound expression leaves the target unbound",
    "tests/conformance/test_dawg_sql_v2.py::TestDAWGSqlV2::test_sql_v2[bind/bind07 - BIND]":
        "?o is out of scope at the point the BIND expression is evaluated",
    "tests/conformance/test_dawg_sql_v2.py::TestDAWGSqlV2::test_sql_v2[bind/bind10 - BIND scoping - Variable in filter not in scope]":
        "the test's own name and its inline comment say it: '?z is not "
        "in-scope at the time of filter execution'",
    "tests/conformance/test_dawg_sql_v2.py::TestDAWGSqlV2::test_sql_v2[functions/COALESCE()]":
        "coalesce01.rq annotates its own cases — '(COALESCE(?z, -3) AS ?def) "
        "# always unbound -> -3'. NULL is what makes COALESCE work",
}


def pytest_runtest_setup(item):
    """Enable strict mode unless this test is a known-legitimate exception."""
    from vitalgraph.db.sparql_sql.generator import set_strict_unresolved_vars
    set_strict_unresolved_vars(item.nodeid not in _STRICT_UNRESOLVED_ALLOWLIST)


def pytest_runtest_teardown(item, nextitem):
    from vitalgraph.db.sparql_sql.generator import set_strict_unresolved_vars
    set_strict_unresolved_vars(False)
