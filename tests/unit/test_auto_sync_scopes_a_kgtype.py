"""Auto-sync classifies a KGType as `kgtype` (`issues/256`, found 2026-10-04).

`_subject_scopes` had no branch for a type, so a new KGType fell through to the
`kgentity` fallback, matched no mapping in an index whose mappings are all
`kgtype`, and was skipped: nothing indexed a new or changed type. The five
index-backed type searches passed locally only against rows from August.
"""

import uuid

import pytest

from vitalgraph.vectorization.auto_sync import _subject_scopes

pytestmark = pytest.mark.asyncio

HALEY = "http://vital.ai/ontology/haley-ai-kg#"


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, *_a, **_k):
        return self.rows


def _row(rdf_type=None, slot_type=None, entity_type=None):
    return {"subject_uuid": uuid.uuid4(), "slot_type": slot_type,
            "entity_type": entity_type, "rdf_type": rdf_type,
            "segment_index": None, "document_type": None}


@pytest.mark.parametrize("cls", ["KGEntityType", "KGFrameType", "KGSlotType", "KGType"])
async def test_a_type_is_in_kgtype_scope(cls):
    r = _row(rdf_type=HALEY + cls)
    out = await _subject_scopes(_Conn([r]), "sp", [r["subject_uuid"]], uuid.uuid4())
    assert out[str(r["subject_uuid"])] == ("kgtype", HALEY + cls)


async def test_an_entity_is_still_an_entity():
    r = _row(rdf_type=HALEY + "KGEntity", entity_type="urn:type:Person")
    out = await _subject_scopes(_Conn([r]), "sp", [r["subject_uuid"]], uuid.uuid4())
    assert out[str(r["subject_uuid"])] == ("kgentity", "urn:type:Person")


async def test_a_slot_is_still_a_slot():
    r = _row(rdf_type=HALEY + "KGTextSlot", slot_type="urn:slot:Name")
    out = await _subject_scopes(_Conn([r]), "sp", [r["subject_uuid"]], uuid.uuid4())
    assert out[str(r["subject_uuid"])] == ("kgslot", "urn:slot:Name")
