"""A KGType lookup that fails must not read as "the type does not exist".

`issues/261`. `execute_sparql_query` reports failure in its RESULT rather than
raising, and the processors' `kgtype_exists` read only the bindings. On dev, with
the compiler sidecar down, a batch delete answered "No KGTypes found for
deletion" — success — and deleted nothing. A create over the same failure would
proceed over a type it could not check.
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.kgtype_lookup import KGTypeLookupFailed, kgtype_exists
from vitalgraph.kg_impl.kgtypes_delete_impl import KGTypesDeleteProcessor

pytestmark = [pytest.mark.unit]

URI = "http://vital.ai/test/kgtype/probe"
FAILED = {"success": False, "error": "ConnectError: [Errno -2] Name or service not known",
          "results": {"bindings": []}}
EMPTY = {"success": True, "results": {"bindings": []}}
FOUND = {"success": True, "results": {"bindings": [{"s": {"type": "uri", "value": URI}}]}}


class _Backend:
    def __init__(self, result):
        self.result = result
        self.deleted: list = []

    async def execute_sparql_query(self, space_id, query):
        return self.result

    async def update_subjects_graph(self, space_id, graph_id, delete_uris, insert):
        self.deleted.extend(delete_uris)
        return True


async def test_a_failed_lookup_raises():
    with pytest.raises(KGTypeLookupFailed, match="could not run"):
        await kgtype_exists(_Backend(FAILED), "sp", "urn:g", URI)


async def test_an_absent_type_is_still_absent():
    assert await kgtype_exists(_Backend(EMPTY), "sp", "urn:g", URI) is False


async def test_a_present_type_is_present():
    assert await kgtype_exists(_Backend(FOUND), "sp", "urn:g", URI) is True


async def test_the_batch_delete_does_not_report_success_on_a_failed_lookup():
    """The dev observation, exactly: this returned 0 ("nothing to delete")."""
    backend = _Backend(FAILED)
    with pytest.raises(KGTypeLookupFailed):
        await KGTypesDeleteProcessor().delete_kgtypes_batch(backend, "sp", "urn:g", [URI])
    assert backend.deleted == []


async def test_the_single_delete_does_not_report_not_found_on_a_failed_lookup():
    with pytest.raises(KGTypeLookupFailed):
        await KGTypesDeleteProcessor().delete_kgtype(_Backend(FAILED), "sp", "urn:g", URI)


async def test_the_batch_delete_still_deletes_a_present_type():
    backend = _Backend(FOUND)
    assert await KGTypesDeleteProcessor().delete_kgtypes_batch(
        backend, "sp", "urn:g", [URI]) == 1
    assert backend.deleted == [URI]


async def test_create_does_not_proceed_over_a_failed_lookup():
    from vitalgraph.kg_impl.kgtypes_create_impl import KGTypesCreateProcessor
    from ai_haley_kg_domain.model.KGType import KGType
    t = KGType()
    t.URI = URI
    with pytest.raises(KGTypeLookupFailed):
        await KGTypesCreateProcessor().create_kgtype(_Backend(FAILED), "sp", "urn:g", t)


def test_the_failure_is_reported_as_a_store_failure_not_an_absence():
    """The KGType endpoints map any exception whose text contains "not found"
    to NOT_FOUND. The lookup's message must not contain it, or the request
    would still answer as though the type were missing."""
    msg = str(KGTypeLookupFailed(
        f"existence check for KGType {URI} in sp could not run: {FAILED['error']}"))
    assert "not found" not in msg.lower()


def test_no_processor_reads_bindings_without_checking_success():
    """The three hand copies are gone; each processor delegates to the checked
    helper, and the unused update copy (whose dict branch read a FAILURE as
    'exists') is deleted."""
    import inspect
    from vitalgraph.kg_impl import kgtypes_create_impl, kgtypes_delete_impl, kgtypes_update_impl
    for mod in (kgtypes_create_impl, kgtypes_delete_impl):
        src = inspect.getsource(mod)
        assert "from .kgtype_lookup import kgtype_exists" in src, mod.__name__
        assert "get('bindings'" not in src.split("def kgtype_exists")[1].split("def ")[0]
    assert "def kgtype_exists" not in inspect.getsource(kgtypes_update_impl)
