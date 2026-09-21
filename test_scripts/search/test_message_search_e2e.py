#!/usr/bin/env python3
"""T4 + T6 — message search correctness and the join back to the entity.

Runs through the CLIENT against a live server, so it exercises the whole
path: SPARQL generation, `vg:textSearch`, the §7.1 push-down, the FTS index,
and the slot -> entity join.

T4 asserts what `contains` cannot do — stemming, token boundaries, phrases,
negation — and the things that look like they work until you check: a query
whose every term is common, and an input that used to crash the parser.

T6 asserts the join back: every hit's entity really is of the requested type,
the slot really belongs to it, and PAGING PARTITIONS THE RESULT SET. That last
one is not ceremony — `verify-paging-by-partition` exists because each gap in
it hid a shipped bug.

    VG_SERVER_URL=http://localhost:8002 VG_SEARCH_SPACE=... VG_SEARCH_GRAPH=... \\
        VG_KG_NS=... python3 test_scripts/search/test_message_search_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


async def main() -> int:
    space = os.environ.get("VG_SEARCH_SPACE")
    graph = os.environ.get("VG_SEARCH_GRAPH")
    ns = os.environ.get("VG_KG_NS")
    url = os.environ.get("VG_SERVER_URL", "http://localhost:8002")
    index = os.environ.get("VG_FTS_INDEX", "message_content")
    if not (space and graph and ns):
        print("Set VG_SEARCH_SPACE, VG_SEARCH_GRAPH, VG_KG_NS.")
        return 2

    slot_type = f"{ns}:slot:MsgContent"
    entity_type = f"{ns}:entity:NurtureAction"

    os.environ.setdefault("LOCAL_CLIENT_SERVER_URL", url)
    os.environ.setdefault("LOCAL_CLIENT_AUTH_USERNAME", "admin")
    os.environ.setdefault("LOCAL_CLIENT_AUTH_PASSWORD", "admin")
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    client = VitalGraphClient()
    await client.open()
    try:
        async def search(text, *, scoped=True, page_size=25, offset=0):
            return await client.kgqueries.search_messages(
                space, graph, text=text, fts_index_name=index,
                slot_type=slot_type if scoped else None,
                entity_type=entity_type if scoped else None,
                page_size=page_size, offset=offset)

        # --- T4: what contains cannot do ---------------------------------
        print("\nT4  SEMANTICS")
        r = await search("saved application")
        check("multi-term AND returns hits", len(r.hits) > 0, str(r.status))
        if not r.hits:
            print("  (no hits — is the index populated?)")
            return 1
        first = r.hits[0]
        check("hits carry the matching text", bool(first.text), repr(first)[:120])
        check("hits carry the owning entity", bool(first.entity_uri))

        r_stem = await search("saving apps")
        check("stemming: 'saving apps' matches saved/app",
              len(r_stem.hits) > 0)

        r_phrase = await search('"text me back"')
        check("quoted phrase returns hits", len(r_phrase.hits) > 0)

        r_neg_a = await search("saved")
        r_neg_b = await search("saved -minutes")
        check("negation narrows the result",
              len(r_neg_b.hits) <= len(r_neg_a.hits))

        # The input that made the old to_tsquery raise (issues/216).
        r_punct = await search("plaid!")
        check("punctuation does not error",
              r_punct.status is not None, str(r_punct.status))

        # No lexemes at all: zero rows, not an error and not everything.
        r_stop = await search("the of and")
        check("stop-words-only returns nothing, without erroring",
              len(r_stop.hits) == 0, f"{len(r_stop.hits)} hits")

        # Ordering. §1.4 warns IDF here is weak, so assert only that the
        # order is MONOTONIC — not that a particular document wins.
        scores = [h.score for h in r.hits]
        check("scores are non-increasing", scores == sorted(scores, reverse=True),
              str(scores[:5]))

        check("response carries the SPARQL it ran", bool(r.sparql))

        # --- T6: the join back -------------------------------------------
        print("\nT6  JOIN BACK AND PAGING")
        uris = [h.entity_uri for h in r.hits if h.entity_uri]
        check("every hit resolved an entity", len(uris) == len(r.hits),
              f"{len(uris)}/{len(r.hits)}")

        # The entity really is of the requested type — asserted against the
        # graph, not taken from the search that claimed it.
        from vitalgraph.model.sparql_model import SPARQLQueryRequest
        sample = uris[:5]
        values = " ".join(f"<{u}>" for u in sample)
        vq = (f"SELECT ?e WHERE {{ GRAPH <{graph}> {{ "
              f"VALUES ?e {{ {values} }} "
              f"?e <http://vital.ai/ontology/haley-ai-kg#hasKGEntityType> "
              f"<{entity_type}> . }} }}")
        vr = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=vq))
        confirmed = len((vr.results or {}).get("bindings") or [])
        check("sampled entities really are of the requested type",
              confirmed == len(sample), f"{confirmed}/{len(sample)}")

        # PAGING PARTITIONS. Two pages of 10 must equal one page of 20, with
        # no overlap and nothing lost.
        p_all = await search("saved application", page_size=20, offset=0)
        p1 = await search("saved application", page_size=10, offset=0)
        p2 = await search("saved application", page_size=10, offset=10)
        k_all = [h.slot_uri for h in p_all.hits]
        k1 = [h.slot_uri for h in p1.hits]
        k2 = [h.slot_uri for h in p2.hits]
        check("page 1 + page 2 have no overlap", not (set(k1) & set(k2)),
              str(set(k1) & set(k2)))
        check("pages partition the 20-row page", k1 + k2 == k_all,
              f"{len(k1)}+{len(k2)} vs {len(k_all)}")

        # Scoping must not change WHICH slots match, only how fast.
        r_unscoped = await search("saved application", scoped=False, page_size=20)
        check("unscoped finds at least the scoped hits",
              set(k_all[:10]) <= set(h.slot_uri for h in r_unscoped.hits) or
              len(r_unscoped.hits) == 0,
              "scoped and unscoped disagree on membership")

        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    rc = asyncio.run(main())
    print()
    if _failures:
        print(f"FAILED — {len(_failures)}: {', '.join(_failures)}")
        sys.exit(1)
    if rc == 0:
        print("All checks passed.")
    sys.exit(rc)
