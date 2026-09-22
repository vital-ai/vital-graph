#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nurture_portal_fts_cases import (  # noqa: E402
    CASES,
    DRAFT_FRAME,
    DRAFT_SLOT,
    ENTITY_TYPE,
    MESSAGE_FRAME,
    MESSAGE_SLOT,
    PortalFTSCase,
)
from vitalgraph.client.vitalgraph_client import VitalGraphClient  # noqa: E402
from vitalgraph.model.kgentities_model import (  # noqa: E402
    EntityPropertyFilter,
    EntityQueryCriteria,
    SortCriteria,
)
from vitalgraph.model.kgqueries_model import (  # noqa: E402
    FTSCriteria,
    FTSTarget,
    KGQueryCriteria,
    TotalCountMode,
)


def build_criteria(case: PortalFTSCase, index_name: str) -> KGQueryCriteria:
    targets = []
    if "sent" in case.populations:
        targets.append(FTSTarget(slot_type=MESSAGE_SLOT, frame_type=MESSAGE_FRAME, kind="sent"))
    if "draft" in case.populations:
        targets.append(FTSTarget(slot_type=DRAFT_SLOT, frame_type=DRAFT_FRAME, kind="draft"))

    filters = []
    lower = case.lower_bound()
    if case.date_property and lower:
        filters.append(
            EntityPropertyFilter(property_uri=case.date_property, operator="gte", value=lower)
        )

    sorts = None
    if case.sort_property:
        sorts = [
            SortCriteria(
                sort_type="entity_property",
                property_uri=case.sort_property,
                sort_order=case.sort_order,
            )
        ]

    return KGQueryCriteria(
        query_type="frame_query",
        source_entity_criteria=EntityQueryCriteria(
            entity_type=ENTITY_TYPE,
            entity_property_filters=filters or None,
        ),
        entity_property_filters=filters or None,
        sort_criteria=sorts,
        fts_criteria=FTSCriteria(
            text=case.text,
            index_name=index_name,
            targets=targets,
            include_match_text=False,
        ),
    )


async def run_case(
    client: VitalGraphClient,
    space: str,
    graph: str,
    index_name: str,
    case: PortalFTSCase,
    page_size: int,
) -> dict:
    started = time.perf_counter()
    response = await client.kgqueries.query_connections(
        space_id=space,
        graph_id=graph,
        criteria=build_criteria(case, index_name),
        page_size=page_size,
        offset=0,
        include_total_count=TotalCountMode(case.include_total_count),
    )
    wall_ms = (time.perf_counter() - started) * 1000
    frames = response.frame_results or []
    result = {
        "case": case.name,
        "query": case.text,
        "populations": list(case.populations),
        "status": response.status.value,
        "wall_ms": round(wall_ms, 1),
        "result_count": len(frames),
        "total_count": response.total_count,
        "total_count_capped": response.total_count_capped,
        "frame_uris": [frame.frame_uri for frame in frames],
        "match_counts": {frame.frame_uri: len(frame.fts_matches) for frame in frames},
        "target_kinds": sorted(
            {
                match.target_kind
                for frame in frames
                for match in frame.fts_matches
                if match.target_kind
            }
        ),
    }
    expected = set(case.populations)
    actual = set(result["target_kinds"])
    if not actual.issubset(expected):
        raise AssertionError(f"{case.name}: unexpected target kinds {sorted(actual - expected)}")
    if any(match.text is not None for frame in frames for match in frame.fts_matches):
        raise AssertionError(f"{case.name}: include_match_text=False returned text")
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_names")
    parser.add_argument("--page-size", type=int, default=25)
    args = parser.parse_args()

    space = os.getenv("VG_SEARCH_SPACE")
    graph = os.getenv("VG_SEARCH_GRAPH")
    index_name = os.getenv("VG_FTS_INDEX", "message_content")
    if not space or not graph:
        print("Set VG_SEARCH_SPACE and VG_SEARCH_GRAPH.", file=sys.stderr)
        return 2

    selected = [case for case in CASES if not args.case_names or case.name in args.case_names]
    unknown = set(args.case_names or []) - {case.name for case in CASES}
    if unknown:
        print(f"Unknown cases: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    client = VitalGraphClient()
    await client.open()
    try:
        for case in selected:
            result = await run_case(client, space, graph, index_name, case, args.page_size)
            print(json.dumps(result, sort_keys=True))
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
