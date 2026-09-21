#!/usr/bin/env python3
"""Item 3 — the SPARQL that `client.kgqueries.search_messages()` generates.

Plan §6.3. Tests the builder, not a live search: the query text is the whole
contract here, and it can be checked without a server or an FTS index.

The plan gates this API on T5 because `vg:textSearch` compiles to a correlated
scalar subquery — the call site looks cheap while the cost tracks the candidate
set. Two of the checks below exist purely to keep that from being hidden: the
narrowing patterns must precede the BIND, and the response must carry the
generated SPARQL.

    python3 test_scripts/search/test_search_messages_builder.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from vitalgraph.client.endpoint.kgqueries_endpoint import KGQueriesEndpoint  # noqa: E402

H = "http://vital.ai/ontology/haley-ai-kg#"
SLOT = "urn:ns:kg:slot:MsgContent"
ETYPE = "urn:ns:kg:entity:NurtureAction"

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)



def _raw_text_arg(q: str) -> str:
    """The first argument of the textSearch BIND, verbatim."""
    line = [l for l in q.splitlines() if "textSearch>" in l][0]
    after = line.split("(?slot, ", 1)[1]
    # the literal ends at the `, "index"` that follows it
    return after.rsplit(', "', 1)[0]


def _text_literal(q: str) -> str:
    """The search text as the SPARQL parser would read it (unescaped)."""
    raw = _raw_text_arg(q)
    assert raw.startswith('"') and raw.endswith('"'), raw
    inner = raw[1:-1]
    out, i = [], 0
    while i < len(inner):
        if inner[i] == "\\" and i + 1 < len(inner):
            out.append(inner[i + 1]); i += 2
        else:
            out.append(inner[i]); i += 1
    return "".join(out)


def build(**kw) -> str:
    b = KGQueriesEndpoint.__new__(KGQueriesEndpoint)
    args = dict(graph_id="urn:g", text="saved application",
                fts_index_name="message_content", slot_type=None,
                entity_type=None, entity_uris=None, include_text=True,
                page_size=25, offset=0)
    args.update(kw)
    return b._build_message_search_sparql(**args)


def _paging_checks():
    print("\nKEYSET PAGING")
    q = build(after=(0.05, "urn:s:123"))
    check("keyset form drops OFFSET", "OFFSET" not in q, q)
    check("keyset form keeps LIMIT", "LIMIT 25" in q, q)
    # Both arms: advance past lower scores AND walk the tie at the boundary.
    # Without the second, every row sharing the cursor's score is skipped.
    check("cursor filters on score", "?score < 0.05" in q, q)
    check("cursor breaks the tie on ?slot",
          '?score = 0.05 && STR(?slot) > "urn:s:123"' in q, q)
    check("offset form still available", "OFFSET 0" in build(), build())
    # A quote in the cursor URI must not break the query.
    qq = build(after=(0.1, 'urn:s:a"b'))
    check("cursor URI is escaped", r'\"b' in qq, qq)



def _unranked_checks():
    print("\nUNRANKED MODE")
    r = build(order_by="relevance")
    u = build(order_by="slot")
    check("relevance projects ?score", "?score" in r.splitlines()[0], r.splitlines()[0])
    # Projecting the score would compute the correlated subquery per candidate
    # and hand back exactly the cost this mode exists to avoid.
    check("slot does NOT project ?score", "?score" not in u.splitlines()[0], u.splitlines()[0])
    check("slot orders by ?slot", "ORDER BY ?slot" in u, u)
    check("slot is still a TOTAL order (paging partitions)",
          "ORDER BY ?slot" in u and "DESC" not in u.split("ORDER BY")[1], u)
    # The BIND and its FILTER must survive: push_text_search consumes the
    # filter into the BGP, and without it there is no FTS restriction at all.
    # vg:textMatch, not vg:textSearch. A BIND would emit an EXTEND, and
    # `emit_extend` computes its companion columns whether or not the outer
    # SELECT reads them — so dropping ?score from the projection alone left
    # ts_rank_cd running twice per row and measured no faster.
    check("slot uses vg:textMatch", "textMatch>" in u, u)
    check("slot emits NO textSearch BIND", "textSearch>" not in u, u)
    check("slot needs no FILTER(BOUND(...))", "BOUND(" not in u, u)
    check("relevance still uses textSearch", "textSearch>" in r, r)
    check("default is relevance", build() == build(order_by="relevance"))


def main() -> int:
    print("\nSHAPE")
    q = build(slot_type=SLOT, entity_type=ETYPE)
    check("scoped to the requested graph", "GRAPH <urn:g> {" in q)
    check("binds textSearch on the SLOT, not the entity",
          "textSearch>(?slot," in q, q)
    check("names the requested index", '"message_content"' in q)
    # ?entity is bound DIRECTLY from hasKGGraphURI — its object IS the
    # entity's subject term, so the `?entity vc:URIProp ?entityUri` hop that
    # used to sit here joined a term to itself and made the planner walk all
    # 84,291 entities to serve 4,320 rows (issues/218 cause 2).
    check("binds entity directly from hasKGGraphURI",
          f"?slot <{H}hasKGGraphURI> ?entity" in q, q)
    check("no URIProp self-join", "URIProp" not in q, q)
    check("orders by score descending", "ORDER BY DESC(?score)" in q)
    check("pages", "LIMIT 25 OFFSET 0" in q)

    # BOUND, not `> 0`. A match whose every term is common can legitimately
    # score 0.0, and `> 0` would drop it while looking like a relevance filter.
    check("filters on BOUND, not score > 0",
          "FILTER(BOUND(?score))" in q and "?score > 0" not in q, q)

    print("\nCOST IS NOT HIDDEN")
    # The narrowing triples must be emitted BEFORE the BIND. vg:textSearch
    # scores rows the BGP already produced, so pattern order is the only place
    # the intent to narrow can be expressed.
    i_slot = q.index("hasKGSlotType")
    i_etype = q.index("hasKGEntityType")
    i_bind = q.index("textSearch>")
    check("slot-type filter precedes the textSearch BIND", i_slot < i_bind)
    check("entity-type filter precedes the textSearch BIND", i_etype < i_bind)

    print("\nSCOPING OPTIONS")
    q_no_scope = build()
    check("unscoped query omits both filters",
          "hasKGSlotType" not in q_no_scope and "hasKGEntityType" not in q_no_scope)
    q_uris = build(entity_uris=["urn:e:1", "urn:e:2"])
    check("entity_uris becomes a VALUES clause",
          "VALUES ?entity { <urn:e:1> <urn:e:2> }" in q_uris, q_uris)
    q_notext = build(include_text=False)
    check("include_text=False drops the text projection",
          "?text" not in q_notext, q_notext)
    check("include_text=True projects text", "?text" in build())

    print("\nESCAPING (websearch syntax must survive intact)")
    q_ws = build(text='"saved app" or plaid -declined')
    line = [l for l in q_ws.splitlines() if "textSearch>" in l][0]
    check("quoted phrase escaped, not dropped", r'\"saved app\"' in line, line)
    check("or survives", " or plaid" in line, line)
    check("negation survives", "-declined" in line, line)
    # The real contract is a round trip: whatever the user typed must come
    # back out of the generated literal unchanged. Counting quote characters
    # was a worse test — it failed on correct SPARQL, because an escaped quote
    # butting against the closing quote legitimately reads as `""`.
    for original in ['"saved app" or plaid -declined', 'he said "hi"',
                     r"a\b", "plain words", r'mixed "q" and \ slash']:
        lit = _text_literal(build(text=original))
        check(f"round-trips {original!r}", lit == original, f"got {lit!r}")

    # The bug this guards against: escape_sparql_string already returns a
    # QUOTED literal, so adding another pair produced `""..."" ` and a
    # syntactically broken query.
    for original in ['"saved app"', "plain"]:
        raw = _raw_text_arg(build(text=original))
        check(f"literal not double-wrapped for {original!r}",
              not raw.startswith('""'), raw)

    print("\nPAGING")
    q_p = build(page_size=10, offset=30)
    check("offset honoured", "LIMIT 10 OFFSET 30" in q_p)
    # Ints are forced, so a string page_size cannot reach the query text.
    try:
        build(page_size="10; DROP")
        check("non-numeric page_size rejected", False, "accepted a string")
    except (ValueError, TypeError):
        check("non-numeric page_size rejected", True)

    _paging_checks()
    _unranked_checks()

    print()
    if _failures:
        print(f"FAILED — {len(_failures)}: {', '.join(_failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())




