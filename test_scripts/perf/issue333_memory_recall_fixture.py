#!/usr/bin/env python3
"""A memory-service recall fixture with zh-Hant messages (`issues/333`).

Builds what vital-saas-memory's recall runs against, through the server: a
space provisioned by `vital_saas_memory.config.provision` (its vector + FTS
indexes and mappings), with the FTS languages extended by `cjk`, and chat
messages written the way `vital_saas_api_app.memory.vitalgraph_store` writes
them (`KGChatUserMessage` / `KGChatBotMessage` domain objects, through
`objects.create_objects`), so auto-sync does the real embedding and indexing.

One graph per member, as production does: a HEAVY member and many TYPICAL
ones, so recall can be measured at both sizes in a space that holds all of
them. Message text is the synthetic zh-Hant generator from
`issue333_cjk_scale.py`.

    python test_scripts/perf/issue333_memory_recall_fixture.py \
        --space perf_memcjk --heavy 20000 --members 50 --per-member 1000

Needs `VITALGRAPH_CLIENT_ENVIRONMENT` / `{PROFILE}_CLIENT_SERVER_URL` for the
target server (the vg test stack is http://localhost:8002), and the
vital-saas-memory checkout (`--memory-repo`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test_scripts", "perf"))

from issue333_cjk_scale import corpus  # noqa: E402

DEFAULT_MEMORY_REPO = os.path.expanduser(
    "~/Local/vital-git/vital-saas-api-app/vital-saas-memory")


def member_graph(space: str, i) -> str:
    return f"urn:{space}:member:{i}"


async def write_member(client, space, graph, n, texts, batch, t0_day):
    from ai_haley_kg_domain.model.KGChatBotMessage import KGChatBotMessage
    from ai_haley_kg_domain.model.KGChatUserMessage import KGChatUserMessage
    interaction = f"{graph}:interaction:1"
    written = 0
    while written < n:
        objs = []
        for j in range(written, min(n, written + batch)):
            m = KGChatUserMessage() if j % 2 == 0 else KGChatBotMessage()
            m.URI = f"{graph}:msg:{j}"
            m.kGChatInteractionURI = interaction
            m.kGChatMessageSequence = j + 1
            m.kGChatMessageDateTime = t0_day + timedelta(minutes=j)
            m.kGChatMessageText = next(texts)
            m.kGIdentifier = m.URI
            m.kGJSON = json.dumps({"agent": "celeste"})
            objs.append(m)
        r = await client.objects.create_objects(space, graph, objs)
        if not getattr(r, "success", getattr(r, "is_success", True)):
            raise RuntimeError(f"create_objects failed: {getattr(r, 'message', r)}")
        written += len(objs)
    return written


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", default="perf_memcjk")
    ap.add_argument("--heavy", type=int, default=20000)
    ap.add_argument("--members", type=int, default=50)
    ap.add_argument("--per-member", type=int, default=1000)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--memory-repo", default=DEFAULT_MEMORY_REPO)
    ap.add_argument("--languages", default="english,spanish,portuguese,cjk")
    a = ap.parse_args()

    sys.path.insert(0, a.memory_repo)
    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    from vital_saas_memory import config, kinds, types as t
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space

    t.FTS_LANGUAGES = tuple(x.strip() for x in a.languages.split(",") if x.strip())
    VitalSigns()
    client = VitalGraphClient()
    await client.open()
    try:
        listed = await client.spaces.list_spaces()
        if a.space not in {s.space for s in (getattr(listed, "spaces", None) or [])}:
            r = await client.spaces.create_space(Space(
                space=a.space, space_name=a.space,
                space_description="issues/333 memory recall fixture"))
            assert r.is_success, r.error_message
        done = await config.provision(client, a.space, kinds.PLATFORM_KINDS)
        print("provisioned:", *done, sep="\n  ")
        texts = iter(corpus(a.heavy + a.members * a.per_member + 10, seed=3331))
        plan = [("heavy", a.heavy)] + [(i, a.per_member) for i in range(a.members)]
        t0 = time.monotonic()
        total = 0
        for who, n in plan:
            graph = member_graph(a.space, who)
            r = await client.graphs.create_graph(a.space, graph)
            total += await write_member(client, a.space, graph, n, texts, a.batch,
                                        datetime(2026, 1, 1, tzinfo=UTC))
            rate = total / max(1e-9, time.monotonic() - t0)
            print(f"  {who}: {n:,} written ({total:,} total, {rate:,.0f}/s)", flush=True)
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
