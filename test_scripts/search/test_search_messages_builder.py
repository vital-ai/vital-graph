#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vitalgraph.sparql.kg_query_builder import (  # noqa: E402
    FTSCriteria,
    FTSTarget,
    FrameQueryCriteria,
    KGQueryCriteriaBuilder,
)

MESSAGE_FRAME = "urn:acme:kg:frame:MessageFrame"
MESSAGE_SLOT = "urn:acme:kg:slot:MsgContent"
DRAFT_FRAME = "urn:acme:kg:frame:GeneratedMessageFrame"
DRAFT_SLOT = "urn:acme:kg:slot:GenMsgContent"


def main() -> int:
    builder = KGQueryCriteriaBuilder()
    criteria = FrameQueryCriteria(
        fts_criteria=FTSCriteria(
            text='"saved application" or reschedule -spam',
            index_name="message_content",
            targets=[
                FTSTarget(MESSAGE_SLOT, MESSAGE_FRAME, "sent"),
                FTSTarget(DRAFT_SLOT, DRAFT_FRAME, "draft"),
            ],
        )
    )
    query = builder.build_frame_query_sparql(
        criteria, "urn:acme_kg", page_size=25, offset=0)

    checks = {
        "uses boolean textMatch": "textMatch>" in query,
        "does not use scored textSearch": "textSearch>" not in query,
        "does not compute rank": "ts_rank" not in query,
        "contains sent target": MESSAGE_SLOT in query and MESSAGE_FRAME in query,
        "contains draft target": DRAFT_SLOT in query and DRAFT_FRAME in query,
        "uses one VALUES target table": "VALUES (?fts_slot_type ?fts_frame_type ?target_kind)" in query,
        "avoids UNION around FTS": "UNION" not in query,
    }
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    if not all(checks.values()):
        print(query)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
