"""A killed query must not be reported as an empty one (`issues/215`).

Observed on the dev instance, same endpoint, same space, ninety seconds apart:

    query=56070ms ... (0 entities, 0 quads)   HTTP 200   <- statement timeout
    query=2595ms  ... (25 entities, 200 quads) HTTP 200  <- warm

`execute_sparql_query` reported the failure correctly — it returns
`{'results': {'bindings': []}, 'success': False, 'error': ...}`. Three separate
`_extract_bindings` helpers then read `results.bindings` and never looked at
`success`, so the distinction was gone before any caller could act on it, and
an empty space and a dead query produced byte-identical responses.

The three helpers are tested TOGETHER because they are three copies of the same
function with the same flaw; fixing one and leaving the others is how this
comes back.
"""

from __future__ import annotations

import pytest

from vitalgraph.utils.db_retry import SparqlQueryFailed

FAILED = {"results": {"bindings": []}, "success": False,
          "error": "canceling statement due to statement timeout"}
EMPTY = {"results": {"bindings": []}}
ONE_ROW = {"results": {"bindings": [{"s": {"value": "urn:x"}}]}}


def _helpers():
    from vitalgraph.kg_impl.kgentity_list_impl import _extract_bindings as a
    from vitalgraph.kg_impl.kgtypes_read_impl import KGTypesReadProcessor as B
    from vitalgraph.db.sparql_sql.sparql_sql_db_objects import (
        SparqlSQLDbObjects as C)
    return [("kgentity_list", a),
            ("kgtypes_read", B._extract_bindings),
            ("db_objects", C._extract_bindings)]


@pytest.mark.parametrize("name,fn", _helpers(), ids=[n for n, _ in _helpers()])
def test_a_failed_result_raises(name, fn):
    with pytest.raises(SparqlQueryFailed) as exc:
        fn(FAILED)
    assert "statement timeout" in str(exc.value), (
        "the reason must survive — an error the caller cannot read is barely "
        "better than the silence it replaced")


@pytest.mark.parametrize("name,fn", _helpers(), ids=[n for n, _ in _helpers()])
def test_a_genuinely_empty_result_still_returns_empty(name, fn):
    """The control. Without it, raising on everything would also pass above."""
    assert fn(EMPTY) == [], f"{name} must still report an empty read as empty"


@pytest.mark.parametrize("name,fn", _helpers(), ids=[n for n, _ in _helpers()])
def test_rows_are_unaffected(name, fn):
    assert len(fn(ONE_ROW)) == 1, f"{name} must still return bindings"


def test_query_failed_is_not_a_success_status():
    """`success` derives from `status`, so this cannot be set inconsistently."""
    from vitalgraph.model.result_status import OperationStatus, ResultStatus
    r = ResultStatus(status=OperationStatus.QUERY_FAILED)
    assert r.success is False, (
        "QUERY_FAILED must derive success=False, or the new status reintroduces "
        "the bug it was added to fix")
    assert ResultStatus(status=OperationStatus.EMPTY).success is True, (
        "EMPTY is a SUCCESS — that is the whole distinction being drawn")
