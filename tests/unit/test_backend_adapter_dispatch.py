"""`create_backend_adapter` dispatches on TYPE and refuses what it cannot serve.

`issues/241`. This started as a guard against the `else` branch returning the
RETIRED backend's adapter — an unrecognised backend was silently adapted as a
store it had nothing to do with. That branch is gone now, along with the backend,
so the guard has moved with the defect rather than being deleted with it:

    before   substring of class name, `else` -> the retired adapter
    interim  substring of class name, `else` -> SparqlSQLBackendAdapter
    now      isinstance, unknown -> TypeError

The interim step was still wrong in the same shape. A rename of
`SparqlSQLSpaceImpl` would have silently fallen through to the `else` and been
adapted anyway — correct by accident, because the fallback happened to name the
only adapter left. Guessing was the defect, not which way it guessed.

Pure dispatch tests: adapters are constructed but never called, so no database is
needed.
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.kg_backend_utils import (
    create_backend_adapter,
    SparqlSQLBackendAdapter,
)
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl


class _NotABackend:
    """Matches nothing. The case the old `else` decided and this one refuses."""


class SparqlSQLSpaceImplLookalike:
    """The reason NAME matching had to go.

    Its class name contains `SparqlSQL`, so the old substring dispatch would have
    handed it the sparql_sql adapter. It is not a `SparqlSQLSpaceImpl`, so this
    one refuses it. Asserting on the LOOKALIKE rather than only on an obviously
    foreign object is what distinguishes the two mechanisms — a test using only
    `_NotABackend` would pass against the old substring form too.
    """


def test_the_live_backend_gets_the_sparql_sql_adapter():
    impl = SparqlSQLSpaceImpl.__new__(SparqlSQLSpaceImpl)
    assert isinstance(create_backend_adapter(impl), SparqlSQLBackendAdapter)


@pytest.mark.parametrize(
    "backend", [_NotABackend(), SparqlSQLSpaceImplLookalike()],
    ids=["unrelated-object", "name-lookalike"])
def test_an_unsupported_backend_raises_instead_of_being_guessed_at(backend):
    """Raising is the point.

    With one adapter in the module, returning it for anything that arrives looks
    harmless and is how the original defect read right up until the adapter it
    returned was the wrong store's. A caller holding something this function does
    not know about needs to be told.
    """
    with pytest.raises(TypeError, match="No KG backend adapter"):
        create_backend_adapter(backend)


def test_the_error_names_what_was_passed():
    """So the failure is actionable without a debugger — the old silent path gave
    the caller nothing to go on, which is why it survived as long as it did."""
    with pytest.raises(TypeError, match="SparqlSQLSpaceImplLookalike"):
        create_backend_adapter(SparqlSQLSpaceImplLookalike())
