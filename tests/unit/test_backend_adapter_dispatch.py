"""`create_backend_adapter` must not fall back to the RETIRED backend.

`issues/241`. The dispatch is a substring match on the backend's CLASS NAME, and
its `else` branch returned `FusekiPostgreSQLBackendAdapter` — so a backend the
function did not recognise was silently adapted as Fuseki. Two failures in one:

  * today it adapts a live backend with an adapter written for a different store;
  * once the Fuseki package is archived the name does not resolve, so the branch
    whose entire job is to be a fallback raises `NameError`.

The default is now the live backend, matching `config_loader.py`, which resolves
`BACKEND_TYPE` to `sparql_sql` when nothing says otherwise.

These are pure dispatch tests: the adapters are constructed but never called, so
no database is needed. The stand-in classes exist to exercise the NAME matching,
which is the mechanism actually under test — a mock with the wrong class name
would pass the wrong branch, which is the point.
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.kg_backend_utils import (
    create_backend_adapter,
    SparqlSQLBackendAdapter,
    FusekiPostgreSQLBackendAdapter,
)


class SparqlSQLSpaceImpl:
    """Name matches the live backend. `postgresql_config` because the sparql_sql
    adapter reads it — via `getattr(..., None)`, so absence is tolerated, but a
    realistic stand-in carries it."""
    postgresql_config = None


class FusekiPostgreSQLSpaceImpl:
    """Name matches the retired hybrid backend, which is still dispatched
    explicitly while it exists."""


class MysteryBackend:
    """Matches NEITHER arm — the case the `else` branch decides."""


class OxigraphSpaceImpl:
    """A second unrecognised name, and not a hypothetical: `BackendType.OXIGRAPH`
    is in the enum (`backend_config.py:19`) and has no arm here."""


def test_sparql_sql_backend_gets_the_sparql_sql_adapter():
    assert isinstance(
        create_backend_adapter(SparqlSQLSpaceImpl()), SparqlSQLBackendAdapter)


def test_fuseki_backend_is_still_dispatched_explicitly_while_it_exists():
    """Not an endorsement — it pins that the EXPLICIT arm is what serves Fuseki,
    so the `else` below is genuinely the unrecognised case and not Fuseki's real
    route. When the package is archived (`issues/241` step 5) this test goes with
    it, and the assertion above plus the two below are what remain."""
    assert isinstance(
        create_backend_adapter(FusekiPostgreSQLSpaceImpl()),
        FusekiPostgreSQLBackendAdapter)


@pytest.mark.parametrize("backend", [MysteryBackend(), OxigraphSpaceImpl()])
def test_an_unrecognised_backend_does_not_fall_back_to_fuseki(backend):
    """The regression this file exists for.

    Asserted as `not FusekiPostgreSQLBackendAdapter` as well as
    `is SparqlSQLBackendAdapter`, because the two say different things: the first
    is the defect, and it would still be a defect if the default were changed
    again to some third adapter.
    """
    adapter = create_backend_adapter(backend)
    assert not isinstance(adapter, FusekiPostgreSQLBackendAdapter), (
        f"{type(backend).__name__} was adapted as Fuseki — the retired backend "
        f"is serving as the fallback again (issues/241)")
    assert isinstance(adapter, SparqlSQLBackendAdapter)
