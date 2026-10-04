"""Frame `create` refuses an existing frame — when switched on (`issues/256` item 3).

Decided, and gated by `VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING` (default off)
until the callers that rely on create overwriting move to upsert.
"""

import asyncio
import uuid

import pytest

from vitalgraph.kg_impl import kg_backend_utils as kbu


@pytest.mark.parametrize("value,expected", [
    (None, False), ("", False), ("0", False), ("false", False),
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True)])
def test_the_switch(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING", raising=False)
    else:
        monkeypatch.setenv("VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING", value)
    assert kbu.create_refuses_existing() is expected


class _Conn:
    """Answers `_present`'s query with the subjects it is told exist."""

    def __init__(self, existing_uris):
        from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        self.existing = {_generate_term_uuid(u, 'U') for u in existing_uris}

    async def fetch(self, sql, uuids, *_a):
        return [{"subject_uuid": u} for u in uuids if u in self.existing]


def test_a_create_naming_an_existing_slot_is_refused():
    check = kbu.refuse_existing_precheck("sp", "urn:g", ["urn:frame", "urn:slot"])
    with pytest.raises(kbu.AlreadyExists) as e:
        asyncio.run(check(_Conn(["urn:slot"])))
    assert e.value.status == "already_exists" and "urn:slot" in str(e.value)
    assert isinstance(e.value, kbu.RequestRefused)


def test_a_create_of_new_objects_passes():
    check = kbu.refuse_existing_precheck("sp", "urn:g", ["urn:frame", "urn:slot"])
    asyncio.run(check(_Conn([])))


def test_prechecks_combine_and_skip_none():
    seen = []

    async def a(conn):
        seen.append("a")

    async def b(conn):
        seen.append("b")
    asyncio.run(kbu.all_prechecks(a, None, b)(None))
    assert seen == ["a", "b"]
    assert kbu.all_prechecks(None, None) is None
