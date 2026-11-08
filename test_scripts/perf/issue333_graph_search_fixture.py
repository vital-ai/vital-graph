#!/usr/bin/env python3
"""A per-graph hybrid search fixture with zh-Hant messages (`issues/333`).

Builds, through the server, a space with a vector index and an FTS index under
one name (`issue333_search_common.provision`, FTS languages including `cjk`),
and chat messages written as `KGChatUserMessage` / `KGChatBotMessage` objects
through `objects.create_objects`, so auto-sync does the real embedding and
indexing.

One graph per owner of messages, in one shared space: a HEAVY graph and many
TYPICAL ones, so a graph-scoped search can be measured at both sizes in a space
that holds all of them. Message text is the synthetic zh-Hant generator from
`issue333_cjk_scale.py`.

    python test_scripts/perf/issue333_graph_search_fixture.py \\
        --space perf_cjksearch --heavy 20000 --graphs 20 --per-graph 1000

Needs `VITALGRAPH_CLIENT_ENVIRONMENT` / `{PROFILE}_CLIENT_SERVER_URL` for the
target server (the vg test stack is http://localhost:8002).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test_scripts", "perf"))

from issue333_cjk_scale import corpus  # noqa: E402
import issue333_search_common as sc  # noqa: E402


def graph_uri(space: str, name) -> str:
    return f"urn:{space}:graph:{name}"


async def write_graph(client, space, graph, n, texts, batch, t0_day):
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
            m.kGJSON = json.dumps({"source": "issue333"})
            objs.append(m)
        r = await client.objects.create_objects(space, graph, objs)
        if not getattr(r, "success", getattr(r, "is_success", True)):
            raise RuntimeError(f"create_objects failed: {getattr(r, 'message', r)}")
        written += len(objs)
    return written


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", default="perf_cjksearch")
    ap.add_argument("--index", default="messages")
    ap.add_argument("--heavy", type=int, default=20000)
    ap.add_argument("--graphs", type=int, default=20)
    ap.add_argument("--per-graph", type=int, default=1000)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--languages", default=",".join(sc.DEFAULT_LANGUAGES))
    a = ap.parse_args()

    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space

    VitalSigns()
    client = VitalGraphClient()
    await client.open()
    try:
        listed = await client.spaces.list_spaces()
        if a.space not in {s.space for s in (getattr(listed, "spaces", None) or [])}:
            r = await client.spaces.create_space(Space(
                space=a.space, space_name=a.space,
                space_description="issues/333 graph-scoped CJK search fixture"))
            assert r.is_success, r.error_message
        languages = [x.strip() for x in a.languages.split(",") if x.strip()]
        print("provisioned:", *await sc.provision(client, a.space, a.index, languages),
              sep="\n  ")
        texts = iter(corpus(a.heavy + a.graphs * a.per_graph + 10, seed=3331))
        plan = [("heavy", a.heavy)] + [(i, a.per_graph) for i in range(a.graphs)]
        t0 = time.monotonic()
        total = 0
        for name, n in plan:
            graph = graph_uri(a.space, name)
            await client.graphs.create_graph(a.space, graph)
            total += await write_graph(client, a.space, graph, n, texts, a.batch,
                                       datetime(2026, 1, 1, tzinfo=UTC))
            rate = total / max(1e-9, time.monotonic() - t0)
            print(f"  {name}: {n:,} written ({total:,} total, {rate:,.0f}/s)", flush=True)
    finally:
        await client.close()
    print("Indexing continues in the server's queue.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
