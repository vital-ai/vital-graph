"""A frame-filtered page sorted by an ENTITY PROPERTY is servable (issues/203).

Two fast paths each held one half of this shape and neither held both:

    fast_prop_sort   entity-property filters   entity-property sort
    fast_slot_sort   FRAME criteria (eq)       frame/entity-frame SLOT sort only

So `frame criteria + entity-property sort` -- a filtered list ordered by name,
which is what clicking a column header on a filtered view produces -- fell to
the general pipeline. Measured on the load fixture at 335 ms against 32 ms for
the same query without the sort.

`fast_slot_sort` already learned frame criteria for `issues/172`; it simply
refused any sort key that was not a slot. It now accepts an all-entity-property
key set and draws the ordering value from `{space}_entity_prop_sort`, keeping
the frame criteria as EXISTS clauses against `{space}_entity_slot_sort`.

Unit tests over the gate, so no database. The page itself is verified against
the quads separately -- ordering, no missing property, and no entity outside the
page holding a smaller value.
"""
from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import fast_slot_sort as F

HAS_NAME = "http://vital.ai/ontology/vital-core#hasName"
MODIFIED = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
NOT_SORTABLE = "urn:acme:kg:prop:SomethingElse"
TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"


class _Sort:
    def __init__(self, sort_type, property_uri=None, slot_type=None,
                 slot_class_uri=None, frame_path=None, sort_order="asc", priority=1):
        self.sort_type = sort_type
        self.property_uri = property_uri
        self.slot_type = slot_type
        self.slot_class_uri = slot_class_uri
        self.frame_path = frame_path or []
        self.sort_order = sort_order
        self.priority = priority


class _Criteria:
    def __init__(self, sort_criteria):
        self.sort_criteria = sort_criteria


def _prop(uri=HAS_NAME, **kw):
    return _Criteria([_Sort("entity_property", property_uri=uri, **kw)])


class TestTheGateAcceptsEntityPropertySorts:

    def test_a_sortable_property_is_served(self):
        keys = F.sort_keys(_prop())
        assert keys is not None
        assert F.is_prop_sort(keys) is True

    def test_a_datetime_property_is_served(self):
        assert F.sort_keys(_prop(MODIFIED)) is not None

    def test_an_unlisted_property_is_declined(self):
        """Only properties `entity_prop_sort` actually holds can be ordered on."""
        assert F.sort_keys(_prop(NOT_SORTABLE)) is None

    def test_a_property_sort_with_no_uri_is_declined(self):
        assert F.sort_keys(_prop(None)) is None


class TestTheSlotPathIsUnchanged:

    def _slot(self):
        return _Criteria([_Sort("frame_slot", slot_type="urn:s",
                                slot_class_uri=TEXT_SLOT, frame_path=["urn:f"])])

    def test_a_slot_sort_is_still_served_and_is_not_a_prop_sort(self):
        keys = F.sort_keys(self._slot())
        assert keys is not None
        assert F.is_prop_sort(keys) is False

    def test_a_slot_sort_without_a_frame_path_is_still_declined(self):
        c = _Criteria([_Sort("frame_slot", slot_type="urn:s",
                             slot_class_uri=TEXT_SLOT)])
        assert F.sort_keys(c) is None


class TestMixedKeysAreDeclined:

    def test_a_property_key_mixed_with_a_slot_key_is_declined(self):
        """ALL or none: the two live in different tables, and half-serving a
        multi-key sort would order by the right values in the wrong precedence."""
        c = _Criteria([
            _Sort("entity_property", property_uri=HAS_NAME, priority=1),
            _Sort("frame_slot", slot_type="urn:s", slot_class_uri=TEXT_SLOT,
                  frame_path=["urn:f"], priority=2),
        ])
        assert F.sort_keys(c) is None
