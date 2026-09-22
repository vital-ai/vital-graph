from __future__ import annotations

import pytest
from pydantic import ValidationError

from vitalgraph.model.kgentities_model import EntityPropertyFilter, SortCriteria
from vitalgraph.client.endpoint.kgqueries_endpoint import (
    KGQueriesEndpoint as ClientKGQueriesEndpoint,
)
from vitalgraph.client.utils.client_utils import VitalGraphClientError
from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
from vitalgraph.model.kgqueries_model import (
    FTSCriteria,
    FTSTarget,
    KGQueryCriteria,
    KGQueryRequest,
    KGQueryResponse,
    TotalCountMode,
)
from vitalgraph.sparql.kg_query_builder import (
    EntityPropertyFilter as BuilderEntityPropertyFilter,
    FTSCriteria as BuilderFTSCriteria,
    FTSTarget as BuilderFTSTarget,
    FrameQueryCriteria,
    KGQueryCriteriaBuilder,
    SortCriteria as BuilderSortCriteria,
)

CREATED = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
ENTITY_TYPE = "urn:acme:kg:entity:NurtureAction"
MESSAGE_FRAME = "urn:acme:kg:frame:MessageFrame"
MESSAGE_SLOT = "urn:acme:kg:slot:MsgContent"
DRAFT_FRAME = "urn:acme:kg:frame:GeneratedMessageFrame"
DRAFT_SLOT = "urn:acme:kg:slot:GenMsgContent"


def api_fts() -> FTSCriteria:
    return FTSCriteria(
        text='"saved application" or reschedule -spam',
        index_name="message_content",
        targets=[
            FTSTarget(slot_type=MESSAGE_SLOT, frame_type=MESSAGE_FRAME, kind="sent"),
            FTSTarget(slot_type=DRAFT_SLOT, frame_type=DRAFT_FRAME, kind="draft"),
        ],
    )


def request_for(
    criteria: KGQueryCriteria,
    include_total_count: TotalCountMode = TotalCountMode.NO,
) -> KGQueryRequest:
    return KGQueryRequest(
        criteria=criteria,
        page_size=25,
        offset=0,
        include_frame_graph=False,
        include_entity_graph=False,
        count_only=False,
        slot_projection=None,
        property_projection=None,
        include_total_count=include_total_count,
    )


def builder_fts() -> BuilderFTSCriteria:
    return BuilderFTSCriteria(
        text='"saved application" or reschedule -spam',
        index_name="message_content",
        targets=[
            BuilderFTSTarget(MESSAGE_SLOT, MESSAGE_FRAME, "sent"),
            BuilderFTSTarget(DRAFT_SLOT, DRAFT_FRAME, "draft"),
        ],
    )


def test_fts_is_composable_kgquery_criteria() -> None:
    criteria = KGQueryCriteria(
        query_type="frame_query",
        fts_criteria=api_fts(),
        entity_property_filters=[
            EntityPropertyFilter(property_uri=CREATED, operator="gte", value="2026-08-01T00:00:00Z")
        ],
        sort_criteria=[
            SortCriteria(sort_type="entity_property", property_uri=CREATED, sort_order="desc")
        ],
    )
    assert criteria.fts_criteria is not None
    assert criteria.fts_criteria.targets[1].kind == "draft"


def test_fts_rejects_blank_text_duplicate_targets_and_wrong_grain() -> None:
    with pytest.raises(ValidationError, match="fts text cannot be blank"):
        FTSCriteria(
            text="  ", index_name="message_content", targets=[FTSTarget(slot_type=MESSAGE_SLOT)]
        )
    with pytest.raises(ValidationError, match="invalid RFC3986 URI"):
        FTSTarget(slot_type="not a URI")
    target = FTSTarget(slot_type=MESSAGE_SLOT, frame_type=MESSAGE_FRAME, kind="sent")
    with pytest.raises(ValidationError, match="slot/frame targets must not overlap"):
        FTSCriteria(text="saved", index_name="message_content", targets=[target, target])
    with pytest.raises(ValidationError, match="slot/frame targets must not overlap"):
        FTSCriteria(
            text="saved",
            index_name="message_content",
            targets=[target, target.model_copy(update={"kind": "other"})],
        )
    with pytest.raises(ValidationError, match="slot/frame targets must not overlap"):
        FTSCriteria(
            text="saved",
            index_name="message_content",
            targets=[target, target.model_copy(update={"frame_type": None})],
        )
    with pytest.raises(ValidationError, match="supported only"):
        KGQueryCriteria(query_type="relation", fts_criteria=api_fts())


def test_frame_builder_emits_boolean_fts_with_owner_filters_and_sort() -> None:
    builder = KGQueryCriteriaBuilder()
    criteria = FrameQueryCriteria(
        entity_type=ENTITY_TYPE,
        entity_property_filters=[
            BuilderEntityPropertyFilter(CREATED, "gte", "2026-08-01T00:00:00Z")
        ],
        sort_criteria=[
            BuilderSortCriteria(
                sort_type="entity_property",
                property_uri=CREATED,
                sort_order="desc",
            )
        ],
        fts_criteria=builder_fts(),
    )
    query = builder.build_frame_query_sparql(criteria, "urn:acme_kg", 25, 0)

    assert "textMatch>" in query
    assert "textSearch>" not in query
    assert "ts_rank" not in query
    assert f"<{MESSAGE_SLOT}>" in query
    assert f"<{DRAFT_SLOT}>" in query
    assert f"<{MESSAGE_FRAME}>" in query
    assert f"<{DRAFT_FRAME}>" in query
    assert f"?entity <{CREATED}> ?sort_val_0" in query
    assert "ORDER BY DESC(?sort_val_0)" in query
    assert "?entity haley:hasKGEntityType <urn:acme:kg:entity:NurtureAction>" in query
    # The FTS/target block is written BEFORE the owner patterns. This assertion
    # used to require the opposite, which pinned the defect: written after, a
    # multi-target VALUES splits the group into BGP(entity) JOIN VALUES JOIN
    # BGP(slots) with null-tolerant join guards — 84,476 entities x 14 matches,
    # 788,438 rows removed by join filter, 1.8 s for 14 rows; first, 6.3 ms.
    assert query.index("VALUES (?fts_slot_type") < query.index("hasKGEntityType")
    assert query.index("textMatch>") < query.index("hasKGEntityType")


def test_single_target_fts_uses_direct_constants() -> None:
    builder = KGQueryCriteriaBuilder()
    criteria = FrameQueryCriteria(
        fts_criteria=BuilderFTSCriteria(
            text="saved",
            index_name="message_content",
            targets=[BuilderFTSTarget(MESSAGE_SLOT, MESSAGE_FRAME, "sent")],
        )
    )

    query = builder.build_frame_query_sparql(criteria, "urn:acme_kg", 25, 0)

    assert "VALUES (?fts_slot_type" not in query
    assert "SELECT DISTINCT ?frame" in query
    assert f"?fts_slot haley:hasKGSlotType <{MESSAGE_SLOT}>" in query
    assert f"?frame haley:hasKGFrameType <{MESSAGE_FRAME}>" in query
    assert "?frame haley:hasKGGraphURI ?entity" not in query


def test_an_unsorted_fts_page_is_one_row_per_frame_not_per_slot() -> None:
    """A page of frames must be DISTINCT on the frame in SQL, not de-duplicated
    in Python afterwards.

    Without DISTINCT the rows are per matching SLOT. A frame whose text matches
    in two slots spent two of the 25 rows, the endpoint collapsed them after the
    page, and the caller received 24 — with every later offset shifted, so some
    frames were never reachable. Both targets here are broad enough for that to
    be the common case, not the corner.
    """
    builder = KGQueryCriteriaBuilder()
    for criteria in (
        FrameQueryCriteria(fts_criteria=builder_fts()),
        FrameQueryCriteria(fts_criteria=builder_fts(), entity_type=ENTITY_TYPE),
    ):
        query = builder.build_frame_query_sparql(criteria, "urn:acme_kg", 25, 0)
        assert "SELECT DISTINCT ?frame WHERE" in query, query
        # ...and still no ORDER BY: the SQL layer synthesizes the paging order,
        # by the frame uuid that IS the DISTINCT key. A builder-written
        # `ORDER BY ?frame` is indistinguishable from one the caller asked for,
        # which costs 117x because it sorts on term text (entity path, D1).
        assert "ORDER BY" not in query, query


def test_match_metadata_query_is_bounded_to_page_frames() -> None:
    builder = KGQueryCriteriaBuilder()
    query = builder.build_fts_matches_sparql(
        builder_fts(), ["urn:frame:1", "urn:frame:2"], "frame", "urn:acme_kg"
    )

    # Bounded to the page by a FILTER INSIDE the group, and with NO target
    # VALUES: joined to the BGP that table cannot be merged, its join carries
    # null-tolerant guards, and the plan drove from every frame in the space —
    # 429 BILLION estimated rows, a 60 s timeout for 2 frames on the test stack,
    # 2.2 s on production for a 14-row phrase. The slot type is projected and
    # the endpoint maps it back to the target's `kind`.
    assert "FILTER(?frame IN (<urn:frame:1>, <urn:frame:2>))" in query
    assert "VALUES" not in query
    assert "?fts_slot haley:hasFrameGraphURI ?frame" in query
    assert "?fts_slot haley:hasKGGraphURI ?entity" in query
    assert "?fts_slot_type" in query
    assert f"FILTER(?fts_slot_type IN (<{MESSAGE_SLOT}>, <{DRAFT_SLOT}>))" in query
    assert "UNION" not in query
    assert "?fts_slot haley:hasTextSlotValue ?match_text" in query
    assert "textMatch>" in query
    assert "textSearch>" not in query


def test_fts_escapes_literals_and_iris() -> None:
    builder = KGQueryCriteriaBuilder()
    criteria = BuilderFTSCriteria(
        text='he said "hi" \\ later',
        index_name="message_content",
        targets=[BuilderFTSTarget("urn:slot:x> ?s ?p ?o . <y")],
    )
    query = builder.build_fts_matches_sparql(
        criteria, ["urn:frame:x> ?s ?p ?o . <y"], "frame", "urn:g> } UNION {"
    )

    assert "x%3E%20?s%20?p%20?o%20.%20%3Cy" in query
    assert "urn:g%3E%20%7D%20UNION%20%7B" in query
    assert r"he said \"hi\" \\ later" in query


class FakeBackend:
    async def execute_sparql_query(self, space_id: str, query: str, **kwargs):
        if "COUNT(DISTINCT ?frame)" in query:
            return {"results": {"bindings": [{"count": {"value": "1"}}]}}
        if "FILTER(?frame IN" in query and "?fts_slot" in query:
            return {
                "results": {
                    "bindings": [
                        {
                            "frame": {"value": "urn:frame:1"},
                            "fts_slot": {"value": "urn:slot:1"},
                            "owner_entity": {"value": "urn:entity:1"},
                            "fts_slot_type": {"value": MESSAGE_SLOT},
                            "match_text": {"value": "saved application"},
                        }
                    ]
                }
            }
        if "?entity_ref" in query:
            return {
                "results": {
                    "bindings": [
                        {
                            "frame": {"value": "urn:frame:1"},
                            "frame_type": {"value": MESSAGE_FRAME},
                            "slot_type": {"value": "urn:slot:Person"},
                            "entity_ref": {"value": "urn:entity:1"},
                        }
                    ]
                }
            }
        return {"results": {"bindings": [{"frame": {"value": "urn:frame:1"}}]}}


@pytest.mark.asyncio
async def test_frame_endpoint_attaches_fts_metadata_after_page_selection() -> None:
    endpoint = KGQueriesEndpoint(None, None)
    request = request_for(
        KGQueryCriteria(
            query_type="frame_query",
            fts_criteria=api_fts(),
        )
    )

    response = await endpoint._execute_frame_query_case(
        FakeBackend(), "acme_kg", "urn:acme_kg", request
    )

    assert response.fts_applied is True
    assert len(response.frame_results or []) == 1
    result = response.frame_results[0]
    assert result.frame_uri == "urn:frame:1"
    assert len(result.fts_matches) == 1
    match = result.fts_matches[0]
    assert match.subject_uri == "urn:slot:1"
    assert match.owner_entity_uri == "urn:entity:1"
    assert match.target_kind == "sent"
    assert match.text == "saved application"


class CappedBackend(FakeBackend):
    async def execute_sparql_query(self, space_id: str, query: str, **kwargs):
        if "COUNT(*)" in query:
            assert "LIMIT 1001" in query
            return {"results": {"bindings": [{"count": {"value": "1001"}}]}}
        return await super().execute_sparql_query(space_id, query, **kwargs)


@pytest.mark.asyncio
async def test_frame_endpoint_bounds_opt_in_total_count() -> None:
    endpoint = KGQueriesEndpoint(None, None)
    request = request_for(
        KGQueryCriteria(
            query_type="frame_query",
            fts_criteria=api_fts(),
        ),
        include_total_count=TotalCountMode.YES,
    )

    response = await endpoint._execute_frame_query_case(
        CappedBackend(), "acme_kg", "urn:acme_kg", request
    )

    assert response.total_count == 1000
    assert response.total_count_capped is True


class EntityBackend:
    async def execute_sparql_query(self, space_id: str, query: str, **kwargs):
        if "COUNT(DISTINCT ?entity)" in query:
            return {"results": {"bindings": [{"count": {"value": "1"}}]}}
        if "FILTER(?entity IN" in query and "?fts_slot" in query:
            return {
                "results": {
                    "bindings": [
                        {
                            "entity": {"value": "urn:entity:1"},
                            "fts_frame": {"value": "urn:frame:1"},
                            "fts_slot": {"value": "urn:slot:1"},
                            "owner_entity": {"value": "urn:entity:1"},
                            "fts_slot_type": {"value": MESSAGE_SLOT},
                            "match_text": {"value": "saved application"},
                        }
                    ]
                }
            }
        return {"results": {"bindings": [{"entity": {"value": "urn:entity:1"}}]}}


@pytest.mark.asyncio
async def test_entity_endpoint_returns_fts_matches_keyed_by_entity() -> None:
    endpoint = KGQueriesEndpoint(None, None)
    request = request_for(
        KGQueryCriteria(
            query_type="entity",
            fts_criteria=api_fts(),
        )
    )

    response = await endpoint._execute_entity_query(
        EntityBackend(), "acme_kg", "urn:acme_kg", request
    )

    assert response.fts_applied is True
    assert response.entity_uris == ["urn:entity:1"]
    assert response.entity_fts_matches is not None
    matches = response.entity_fts_matches["urn:entity:1"]
    assert len(matches) == 1
    assert matches[0].frame_uri == "urn:frame:1"
    assert matches[0].subject_uri == "urn:slot:1"


class CappedEntityBackend(EntityBackend):
    async def execute_sparql_query(self, space_id: str, query: str, **kwargs):
        if "COUNT(*)" in query:
            assert "LIMIT 1001" in query
            return {"results": {"bindings": [{"count": {"value": "1001"}}]}}
        return await super().execute_sparql_query(space_id, query, **kwargs)


@pytest.mark.asyncio
async def test_entity_endpoint_bounds_opt_in_total_count() -> None:
    endpoint = KGQueriesEndpoint(None, None)
    request = request_for(
        KGQueryCriteria(
            query_type="entity",
            fts_criteria=api_fts(),
        ),
        include_total_count=TotalCountMode.YES,
    )

    response = await endpoint._execute_entity_query(
        CappedEntityBackend(), "acme_kg", "urn:acme_kg", request
    )

    assert response.total_count == 1000
    assert response.total_count_capped is True
    assert response.fts_applied is True


class FakeClientConfig:
    def get_server_url(self) -> str:
        return "http://example.test"


class FakeClient:
    config = FakeClientConfig()

    def is_connected(self) -> bool:
        return True


class CompatibilityEndpoint(ClientKGQueriesEndpoint):
    def __init__(self, response: KGQueryResponse):
        super().__init__(FakeClient())
        self.response = response

    async def _make_typed_request(self, *args, **kwargs):
        return self.response


@pytest.mark.asyncio
async def test_client_refuses_server_that_ignores_fts_criteria() -> None:
    endpoint = CompatibilityEndpoint(
        KGQueryResponse(
            query_type="frame_query",
            frame_results=[],
            total_count=0,
            page_size=25,
            offset=0,
            fts_applied=False,
        )
    )

    with pytest.raises(VitalGraphClientError, match="did not acknowledge"):
        await endpoint.query_connections(
            "acme_kg",
            "urn:acme_kg",
            KGQueryCriteria(query_type="frame_query", fts_criteria=api_fts()),
            page_size=25,
        )


@pytest.mark.asyncio
async def test_client_preserves_non_success_response_without_fts_acknowledgement() -> None:
    from vitalgraph.model.result_status import OperationStatus

    endpoint = CompatibilityEndpoint(
        KGQueryResponse(
            status=OperationStatus.NOT_FOUND,
            message="Space missing",
            query_type="frame_query",
            frame_results=None,
            total_count=0,
            page_size=25,
            offset=0,
            fts_applied=False,
        )
    )

    response = await endpoint.query_connections(
        "missing",
        "urn:missing",
        KGQueryCriteria(query_type="frame_query", fts_criteria=api_fts()),
        page_size=25,
    )

    assert response.status == OperationStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_client_accepts_server_fts_acknowledgement() -> None:
    endpoint = CompatibilityEndpoint(
        KGQueryResponse(
            query_type="frame_query",
            frame_results=[],
            total_count=0,
            page_size=25,
            offset=0,
            fts_applied=True,
        )
    )

    response = await endpoint.query_connections(
        "acme_kg",
        "urn:acme_kg",
        KGQueryCriteria(query_type="frame_query", fts_criteria=api_fts()),
        page_size=25,
    )

    assert response.fts_applied is True
