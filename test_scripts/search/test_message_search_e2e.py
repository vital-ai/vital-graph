#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vitalgraph.client.vitalgraph_client import VitalGraphClient  # noqa: E402
from vitalgraph.model.kgentities_model import EntityQueryCriteria  # noqa: E402
from vitalgraph.model.kgqueries_model import (  # noqa: E402
    FTSCriteria,
    FTSTarget,
    KGQueryCriteria,
)


def criteria(text: str, index: str, entity_type: str, frame_type: str, slot_type: str):
    return KGQueryCriteria(
        query_type="frame_query",
        source_entity_criteria=EntityQueryCriteria(
            search_string=None,
            entity_type=entity_type,
            frame_type=None,
            slot_criteria=None,
            sort_criteria=None,
            filters=None,
            entity_property_filters=None,
            vector_criteria=None,
            multi_vector_criteria=None,
            geo_criteria=None,
        ),
        fts_criteria=FTSCriteria(
            text=text,
            index_name=index,
            targets=[
                FTSTarget(
                    slot_type=slot_type,
                    frame_type=frame_type,
                    kind="sent",
                )
            ],
            include_match_text=True,
        ),
    )


async def main() -> int:
    space = os.getenv("VG_SEARCH_SPACE")
    graph = os.getenv("VG_SEARCH_GRAPH")
    ns = os.getenv("VG_KG_NS")
    index = os.getenv("VG_FTS_INDEX", "message_content")
    if not space or not graph or not ns:
        print("Set VG_SEARCH_SPACE, VG_SEARCH_GRAPH, and VG_KG_NS.")
        return 2

    client = VitalGraphClient()
    await client.open()
    failures = []
    try:
        entity_type = f"{ns}:entity:NurtureAction"
        frame_type = f"{ns}:frame:MessageFrame"
        slot_type = f"{ns}:slot:MsgContent"

        async def search(text: str, page_size: int = 25, offset: int = 0):
            return await client.kgqueries.query_connections(
                space_id=space,
                graph_id=graph,
                criteria=criteria(text, index, entity_type, frame_type, slot_type),
                page_size=page_size,
                offset=offset,
            )

        result = await search("saved application")
        frames = result.frame_results or []
        if not frames:
            failures.append("multi-term query returned no frames")
        for frame in frames:
            if not frame.fts_matches:
                failures.append(f"{frame.frame_uri} has no FTS match metadata")
            for match in frame.fts_matches:
                if match.target_kind != "sent":
                    failures.append(f"{frame.frame_uri} returned kind {match.target_kind!r}")
                if not match.subject_uri:
                    failures.append(f"{frame.frame_uri} returned an empty slot URI")

        phrase = await search('"text me back"')
        punctuation = await search("plaid!")
        stop_words = await search("the of and")
        if punctuation.status is None:
            failures.append("punctuation query did not return a status")
        if stop_words.frame_results:
            failures.append("stop-word-only query returned frames")

        page = await search("saved application", page_size=20)
        first = await search("saved application", page_size=10)
        second = await search("saved application", page_size=10, offset=10)
        all_uris = [item.frame_uri for item in page.frame_results or []]
        split_uris = [item.frame_uri for item in first.frame_results or []]
        split_uris += [item.frame_uri for item in second.frame_results or []]
        if split_uris != all_uris:
            failures.append("two 10-row pages do not partition the 20-row page")

        print(f"multi-term frames: {len(frames)}")
        print(f"phrase frames: {len(phrase.frame_results or [])}")
        print(f"punctuation frames: {len(punctuation.frame_results or [])}")
    finally:
        await client.close()

    if failures:
        for failure in failures:
            print(f"FAIL  {failure}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
