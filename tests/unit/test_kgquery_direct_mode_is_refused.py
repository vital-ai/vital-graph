"""KGQuery's direct mode is gone: `query_mode="direct"` is refused with a reason (`issues/298`).

Direct mode read the materialized `vg-direct:` predicates (`hasEntityFrame`,
`hasFrame`, `hasSlot`). No space has them and nothing writes them, so a
direct-mode query compiled to a join on a term that does not exist and returned
nothing, silently. It was removed; the field stays for one release so a caller
still sending "direct" gets told, in the 200 body like every other domain
outcome, rather than being silently served edge mode or nothing.
"""
from __future__ import annotations

import asyncio
import logging

from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
from vitalgraph.model.kgentities_model import EntityQueryCriteria
from vitalgraph.model.kgqueries_model import KGQueryCriteria, KGQueryRequest
from vitalgraph.model.result_status import OperationStatus
from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder


def _endpoint():
    ep = KGQueriesEndpoint.__new__(KGQueriesEndpoint)   # no router wiring needed
    ep.logger = logging.getLogger(__name__)
    ep.query_builder = KGQueryCriteriaBuilder()
    return ep


def _request(mode):
    return KGQueryRequest(
        criteria=KGQueryCriteria(
            query_type="entity", query_mode=mode,
            source_entity_criteria=EntityQueryCriteria(entity_type="urn:T")),
        page_size=25, offset=0)


def test_direct_mode_is_an_invalid_request_naming_the_removal():
    resp = asyncio.run(_endpoint()._query_connections("sp", "urn:g", _request("direct"), {}))
    assert resp.status == OperationStatus.INVALID_REQUEST
    assert "direct mode was removed" in resp.message


def test_the_builder_emits_no_direct_predicates():
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria as BuilderCriteria, FrameCriteria as BFrame,
        SlotCriteria as BSlot, SortCriteria as BSort)
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        BuilderCriteria(
            frame_criteria=[BFrame(frame_type="urn:F", frame_criteria=[BFrame(frame_type="urn:C")],
                                   slot_criteria=[BSlot(slot_type="urn:S", value="x",
                                                        comparator="eq")])],
            slot_criteria=[BSlot(slot_type="urn:S2", comparator="not_exists")],
            sort_criteria=[BSort(sort_type="frame_slot", slot_type="urn:S",
                                 frame_path=["urn:F"])]),
        "urn:g", 25, 0)
    assert "vg-direct" not in sparql and "vitalgraph/direct#" not in sparql
