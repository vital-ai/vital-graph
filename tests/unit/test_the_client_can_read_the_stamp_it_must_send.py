"""The other half of the conditional write: reading the stamp (`issues/253`).

The client could already SEND `if_unmodified_since`; it had no way to READ the
value to send. Every caller would have had to know
`http://vital.ai/ontology/vital#hasObjectModificationDateTime`, and two test
scripts in this repository had already hardcoded it.

The trap this exists to close is in `test_the_obvious_way_to_read_it_is_wrong`
below, and it is not hypothetical: `str()` on the property gives a value the
server can never match, so a caller doing the natural thing would see a
permanent conflict with nothing it could do about it.
"""
import json

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

from vitalgraph.client.response.client_response import (
    EntityGraph, EntityGraphResponse, EntityResponse, MultiEntityGraphResponse,
    find_modification_stamp, modification_stamp,
)
from vitalgraph.model.server_properties import MODIFICATION_TIME_URI

STAMP = "2026-10-01T12:23:37.333100+00:00"


def _entity(uri, stamp=STAMP):
    e = KGEntity()
    e.URI = uri
    e.name = "Host"
    if stamp is not None:
        e.objectModificationDateTime = stamp
    return e


def _frame(uri, stamp):
    f = KGFrame()
    f.URI = uri
    f.objectModificationDateTime = stamp
    return f


class TestReadingTheStamp:
    def test_it_comes_back_in_the_form_the_server_compares(self):
        assert modification_stamp(_entity("urn:e")) == STAMP

    def test_the_obvious_way_to_read_it_is_wrong(self):
        """Why the accessor exists at all.

        VitalSigns parses the literal into a `datetime`, so `str()` renders it
        SPACE-separated while the stored term text keeps the ISO `T`. The server
        compares the stored string deliberately — a datetime comparison would
        forgive a formatting difference, and a formatting difference means
        something rewrote the value. So the space form is refused every time.
        """
        e = _entity("urn:e")
        naive = str(e[MODIFICATION_TIME_URI])
        assert naive != STAMP
        assert naive == STAMP.replace("T", " ")       # the whole difference
        assert modification_stamp(e) == STAMP

    @pytest.mark.parametrize("stamp", [
        "2026-10-01T12:23:37.333100+00:00",           # microseconds
        "2026-10-01T12:23:37+00:00",                  # none
        "2026-10-01T12:23:37.100000+00:00",           # trailing zeros
    ])
    def test_it_round_trips_unchanged(self, stamp):
        # A stamp that comes back altered is worse than no stamp: the caller
        # sends it in good faith and the write is refused forever.
        assert modification_stamp(_entity("urn:e", stamp)) == stamp

    def test_an_unstamped_object_answers_none_rather_than_raising(self):
        # Legitimate for an entity written before stamping. The caller then has
        # nothing to be conditional on, which is a decision it can make.
        assert modification_stamp(_entity("urn:e", stamp=None)) is None

    def test_it_matches_what_the_wire_actually_carried(self):
        # Pinned against the serialization rather than a literal, so a change in
        # how the server writes the value fails here instead of in production.
        e = _entity("urn:e")
        assert modification_stamp(e) == json.loads(e.to_json())[MODIFICATION_TIME_URI]


class TestPickingTheRightObject:
    def test_it_takes_the_entity_and_not_the_first_stamp_in_the_graph(self):
        # The guard keys on the OWNING ENTITY. An entity graph holds its frames,
        # slots and edges, each with its own stamp, and frames are written more
        # often than the entity — so "the first stamp" is usually the wrong one
        # and would be refused for a reason the caller cannot see.
        frame_stamp = "2026-10-02T09:00:00+00:00"
        graph = EntityGraph(entity_uri="urn:e", objects=[
            _frame("urn:f", frame_stamp), _entity("urn:e")])
        assert graph.modification_stamp == STAMP
        assert graph.modification_stamp != frame_stamp

    def test_an_absent_entity_answers_none(self):
        graph = EntityGraph(entity_uri="urn:missing",
                            objects=[_frame("urn:f", STAMP)])
        assert graph.modification_stamp is None

    def test_find_tolerates_nothing_to_look_in(self):
        assert find_modification_stamp(None, "urn:e") is None
        assert find_modification_stamp([], "urn:e") is None
        assert find_modification_stamp([_entity("urn:e")], None) is None


class TestTheResponsesACallerActuallyHolds:
    def test_the_entity_graph_read(self):
        r = EntityGraphResponse(
            error_code=0, status_code=200, status="found",
            objects=EntityGraph(entity_uri="urn:e", objects=[_entity("urn:e")]))
        assert r.modification_stamp == STAMP

    def test_an_empty_entity_graph_read(self):
        r = EntityGraphResponse(error_code=0, status_code=200, status="not_found")
        assert r.modification_stamp is None

    def test_the_flat_read_which_is_the_cheaper_one(self):
        # `get_kgentity` without `include_entity_graph`: enough to open the
        # read-modify-write loop without pulling the whole graph.
        r = EntityResponse(error_code=0, status_code=200, status="found",
                           objects=[_entity("urn:e")])
        assert r.modification_stamp_for("urn:e") == STAMP
        assert r.modification_stamp_for("urn:other") is None

    def test_the_batch_read_keys_by_entity(self):
        # A dict, because the per-entity writes that follow each need THEIR
        # stamp and the two orders need not agree.
        other = "2026-10-03T08:00:00+00:00"
        r = MultiEntityGraphResponse(
            error_code=0, status_code=200, status="found",
            graph_list=[
                EntityGraph(entity_uri="urn:a", objects=[_entity("urn:a")]),
                EntityGraph(entity_uri="urn:b", objects=[_entity("urn:b", other)]),
                EntityGraph(entity_uri="urn:c", objects=[_entity("urn:c", None)]),
            ])
        assert r.modification_stamps == {
            "urn:a": STAMP, "urn:b": other,
            # Present with None, not dropped — it is still an entity the caller
            # read, and silently losing a key reads as "no such entity".
            "urn:c": None}

    def test_an_empty_batch_read(self):
        r = MultiEntityGraphResponse(error_code=0, status_code=200, status="empty")
        assert r.modification_stamps == {}


class TestTheUriHasOneDefinition:
    def test_the_client_and_the_server_read_the_same_constant(self):
        # Not two copies kept in step by hand — this repo's own note on the
        # success-status set says that is how the two drift.
        from vitalgraph.kg_impl.kg_server_properties import (
            MODIFICATION_TIME_URI as server_uri)
        assert server_uri is MODIFICATION_TIME_URI

    def test_the_guard_compares_against_that_same_constant(self):
        # The server's compare-and-set must read the predicate from the shared
        # definition too, or the client can be right and still never match.
        import inspect
        from vitalgraph.kg_impl import kg_backend_utils
        src = inspect.getsource(kg_backend_utils._stamp_keys)
        assert "MODIFICATION_TIME_URI" in src
        assert "hasObjectModificationDateTime" not in src
