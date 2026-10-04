"""Server-minted edge URIs are determined by their endpoints (`issues/253`).

A random URI made the write non-idempotent in exactly one place: the
subject-level delete removes the quads of the subjects about to be written, and a
freshly invented edge URI is not one of them — so the PREVIOUS edge survived and
the same write applied twice attached the frame twice. That is also why the
client (correctly) refuses to replay a timed-out POST, which is what turns a
stall into an uncertain write.
"""
import pytest

from vitalgraph.kg_impl.edge_uris import EDGE_URI_BASE, edge_local_id, edge_uri

ENTITY = "http://vital.ai/haley.ai/domain/KGEntity/lead-1"
FRAME = "http://vital.ai/haley.ai/domain/KGFrame/frame-1"


class TestEdgeUri:
    def test_the_same_pair_always_gets_the_same_uri(self):
        # The whole point: replaying a write must not mint a second edge.
        assert (edge_uri("Edge_hasEntityKGFrame", ENTITY, FRAME)
                == edge_uri("Edge_hasEntityKGFrame", ENTITY, FRAME))

    def test_different_pairs_get_different_uris(self):
        a = edge_uri("Edge_hasEntityKGFrame", ENTITY, FRAME)
        b = edge_uri("Edge_hasEntityKGFrame", ENTITY, FRAME + "-other")
        c = edge_uri("Edge_hasEntityKGFrame", ENTITY + "-other", FRAME)
        assert len({a, b, c}) == 3

    def test_direction_matters(self):
        # An edge A->B is not the edge B->A, and collapsing them would merge two
        # attachments into one.
        assert (edge_uri("Edge_hasKGFrame", ENTITY, FRAME)
                != edge_uri("Edge_hasKGFrame", FRAME, ENTITY))

    def test_edge_type_is_part_of_the_key(self):
        assert (edge_uri("Edge_hasEntityKGFrame", ENTITY, FRAME)
                != edge_uri("Edge_hasKGFrame", ENTITY, FRAME))

    def test_reproduces_the_pre_existing_parent_child_form(self):
        # NOT a new scheme. `_create_parent_child_edges` already composed the
        # local ids this way, and that site now calls this helper; if the string
        # changed, existing parent/child edges would be duplicated on rewrite.
        parent = "http://vital.ai/haley.ai/domain/KGFrame/parent-9"
        child = "http://vital.ai/haley.ai/domain/KGFrame/child-4"
        legacy = (f"http://vital.ai/haley.ai/app/Edge_hasKGFrame/"
                  f"{parent.split('/')[-1]}_{child.split('/')[-1]}_edge")
        assert edge_uri("Edge_hasKGFrame", parent, child) == legacy

    def test_lives_under_the_edge_namespace(self):
        assert edge_uri("Edge_hasKGSlot", FRAME, "urn:slot:1").startswith(
            f"{EDGE_URI_BASE}/Edge_hasKGSlot/")

    def test_accepts_non_string_uris(self):
        # Callers pass `obj.URI`, which is a VitalSigns/rdflib value, not a str.
        class URIish:
            def __str__(self):
                return FRAME

        assert (edge_uri("Edge_hasEntityKGFrame", ENTITY, URIish())
                == edge_uri("Edge_hasEntityKGFrame", ENTITY, FRAME))


class TestLocalId:
    def test_trailing_slash_is_the_same_object(self):
        assert edge_local_id(FRAME + "/") == edge_local_id(FRAME)

    @pytest.mark.parametrize("uri", ["/", "//", ""])
    def test_a_uri_with_no_segment_does_not_collapse_to_empty(self, uri):
        # "" + "_" + "" would make every unusable URI the same edge, which is
        # the failure this helper exists to prevent, sign-flipped.
        assert edge_local_id(uri)

    def test_distinct_unusable_uris_stay_distinct(self):
        assert edge_local_id("/") != edge_local_id("//")

    def test_urn_style_uri_keeps_its_whole_value(self):
        assert edge_local_id("urn:example:slot:1") == "urn:example:slot:1"


class TestTheRealCreatePath:
    """Through the processor, not the helper — the helper being right is not the
    claim, the write being replayable is."""

    @pytest.mark.asyncio
    async def test_the_same_frame_write_twice_produces_one_edge_uri(self):
        from ai_haley_kg_domain.model.KGFrame import KGFrame

        from vitalgraph.kg_impl.kgentity_frame_create_impl import (
            KGEntityFrameCreateProcessor)

        frame = KGFrame()
        frame.URI = FRAME
        processor = KGEntityFrameCreateProcessor()

        first = await processor.create_entity_frame_edges(ENTITY, [frame])
        second = await processor.create_entity_frame_edges(ENTITY, [frame])

        assert len(first) == len(second) == 1
        # Before the fix these differed on every call, so the subject-level
        # delete could not reach the earlier edge and the frame ended up
        # attached twice.
        assert str(first[0].URI) == str(second[0].URI)
        # Still an edge between the two things the caller named.
        assert str(first[0].edgeSource) == ENTITY
        assert str(first[0].edgeDestination) == FRAME


class TestNoRandomnessLeftOnTheWritePaths:
    def test_the_live_mint_sites_are_deterministic(self):
        # A guard, not a style check: any of these regaining a uuid4 restores
        # ~190 uncertain writes a week. Named per site so a failure says which.
        #
        # Over the AST rather than the text, because the text mentions `uuid4()`
        # in the comments that explain why it is gone — a guard a COMMENT can
        # trip is a guard that gets deleted.
        import ast
        import inspect

        # `kgslot_create_impl` was the third site, and was deleted 2026-10-04
        # (`issues/256`): its only route was `KGFramesEndpoint._create_slots`,
        # which nothing called. The live slot route mints through the endpoint.
        from vitalgraph.kg_impl import (kgentity_create_impl,
                                        kgentity_frame_create_impl)

        def randomness_in(mod):
            tree = ast.parse(inspect.getsource(mod))
            return [
                node.lineno for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (getattr(node.func, "attr", None) == "uuid4"
                     or getattr(node.func, "id", None) == "uuid4")
            ]

        for mod in (kgentity_frame_create_impl, kgentity_create_impl):
            lines = randomness_in(mod)
            assert not lines, f"{mod.__name__} mints a random URI at {lines}"
