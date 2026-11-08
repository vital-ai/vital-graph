#!/usr/bin/env python3
"""Recall ranking on real Traditional Chinese: DRCD (`issues/333`, decision D2).

DRCD (Delta Reading Comprehension Dataset, https://github.com/DRCKnowledgeTeam/DRCD,
CC-BY-SA 3.0, from Taiwan Wikipedia) has 30,000+ annotator-written questions,
each tied to a paragraph and to the answer's character offset in it. Split into
sentences, the paragraphs become message-sized items (median 38 characters), and
each question's RELEVANT item is the sentence holding its answer. That is a
recall test with a known right answer per question, in zh-Hant, which the memory
service has nothing of its own to provide yet.

Three steps; the data never enters the repo:

    prepare  --drcd DIR --out OUT   sentences + questions as JSONL
    load     --out OUT              write the sentences into one member graph of a
                                    space provisioned the memory service's way (its
                                    own `config.provision`, FTS languages + `cjk`),
                                    as KGChatUserMessage objects through the server,
                                    so auto-sync embeds and indexes them for real
    eval     --out OUT              score every ranking variant

Ranking variants:

  through the SERVER, the memory service's own query (`vital_saas_memory.query`):
    vector       hybridSearch alpha 1.0: the vector arm alone. What recall
                 effectively is TODAY for Chinese, since its FTS cannot match it.
    vector+reorder  the same 12 candidates re-sorted by `cjk_first`, the memory
                 service's own shared-pair workaround: TODAY'S PRODUCTION BEHAVIOUR.
    hybrid       alpha 0.5 with the `cjk` index, as built (`build_query`).
    fts          alpha 0.0: the `cjk` full-text arm alone.

  as SQL on the FTS table (the D2 candidates for the full-text arm; same index):
    rank         ts_rank_cd over the ORed pairs: what `fts` computes
    rank-norm1   ts_rank_cd with length normalization 1
    idf          sum of ln(N/df) over the pairs a sentence contains (rarity-weighted)
    idf-prune5   idf, ignoring pairs in more than 5% of sentences
    idf-min2     idf, requiring at least 2 matching pairs

Metrics per variant, over the sampled questions: hit@1, hit@3 (the memory
service returns 3 per kind), hit@12 (its candidate count), MRR@12, and a lenient
hit@3 that accepts any sentence of the answer's paragraph. Server variants also
report latency.

Needs the vg test stack (server on :8002, Postgres on :5433), the `cjk`
functions installed, and the vital-saas-memory checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import statistics
import sys
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from devtools.target import add_pg_arguments  # noqa: E402

DEFAULT_MEMORY_REPO = os.path.expanduser(
    "~/Local/vital-git/vital-saas-api-app/vital-saas-memory")
SPACE = "eval_drcd333"
GRAPH = f"urn:{SPACE}:member:all"
INDEX = "member_messages"
_SENT = re.compile(r"(?<=[。！？])")


def item_uri(item_id: str) -> str:
    return f"urn:{SPACE}:msg:{item_id}"


# ---------------------------------------------------------------- prepare

def prepare(a) -> int:
    items, questions = [], []
    for split in ("dev", "test"):
        path = os.path.join(a.drcd, f"DRCD_{split}.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for art in data["data"]:
            for para in art["paragraphs"]:
                ctx, pid = para["context"], f"{split}-{para['id']}"
                spans, pos = [], 0
                for k, s in enumerate(p for p in _SENT.split(ctx) if p):
                    start = ctx.index(s, pos)
                    pos = start + len(s)
                    if s.strip():
                        iid = f"{pid}-{k}"
                        spans.append((start, pos, iid))
                        items.append({"id": iid, "paragraph": pid, "text": s.strip()})
                for q in para["qas"]:
                    off = q["answers"][0]["answer_start"]
                    hit = [iid for s0, s1, iid in spans if s0 <= off < s1]
                    if hit:
                        questions.append({"id": f"{split}-{q['id']}", "question": q["question"],
                                          "answer": q["answers"][0]["text"],
                                          "item": hit[0], "paragraph": pid})
    os.makedirs(a.out, exist_ok=True)
    for name, rows in (("items", items), ("questions", questions)):
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(items):,} items, {len(questions):,} questions -> {a.out}")
    return 0


def _read(a, name):
    with open(os.path.join(a.out, f"{name}.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


# ---------------------------------------------------------------- load

async def load(a) -> int:
    sys.path.insert(0, a.memory_repo)
    from ai_haley_kg_domain.model.KGChatUserMessage import KGChatUserMessage
    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    from vital_saas_memory import config, kinds, types as t
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space

    t.FTS_LANGUAGES = tuple(t.FTS_LANGUAGES) + ("cjk",)
    VitalSigns()
    items = _read(a, "items")
    c = VitalGraphClient()
    await c.open()
    try:
        listed = await c.spaces.list_spaces()
        if SPACE not in {s.space for s in (getattr(listed, "spaces", None) or [])}:
            r = await c.spaces.create_space(Space(
                space=SPACE, space_name=SPACE,
                space_description="issues/333 D2 ranking eval: DRCD sentences (CC-BY-SA 3.0)"))
            assert r.is_success, r.error_message
        print("provisioned:", *(await config.provision(c, SPACE, kinds.PLATFORM_KINDS)), sep="\n  ")
        await c.graphs.create_graph(SPACE, GRAPH)
        t0 = time.monotonic()
        for i in range(0, len(items), a.batch):
            objs = []
            for j, it in enumerate(items[i:i + a.batch], start=i):
                m = KGChatUserMessage()
                m.URI = item_uri(it["id"])
                m.kGChatInteractionURI = f"{GRAPH}:interaction:1"
                m.kGChatMessageSequence = j + 1
                # Production always writes one, and the message kind's query
                # REQUIRES it (`?s hasKGChatMessageDateTime ?at`).
                m.kGChatMessageDateTime = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=j)
                m.kGChatMessageText = it["text"]
                m.kGIdentifier = m.URI
                m.kGJSON = "{}"
                objs.append(m)
            r = await c.objects.create_objects(SPACE, GRAPH, objs)
            if not getattr(r, "success", getattr(r, "is_success", True)):
                raise RuntimeError(getattr(r, "message", r))
            print(f"  {i + len(objs):,} written ({(i + len(objs)) / (time.monotonic() - t0):,.0f}/s)",
                  flush=True)
    finally:
        await c.close()
    print("Indexing continues in the server's queue; eval waits for it.")
    return 0


# ---------------------------------------------------------------- eval

def _metrics(ranked_lists, questions, para_of):
    h1 = h3 = h12 = mrr = lenient3 = 0
    for q, ranked in zip(questions, ranked_lists):
        ids = ranked[:12]
        if ids[:1] == [q["item"]]:
            h1 += 1
        if q["item"] in ids[:3]:
            h3 += 1
        if q["item"] in ids:
            h12 += 1
            mrr += 1.0 / (ids.index(q["item"]) + 1)
        if any(para_of.get(i) == q["paragraph"] for i in ids[:3]):
            lenient3 += 1
    n = len(questions)
    return {"hit@1": h1 / n, "hit@3": h3 / n, "hit@12": h12 / n, "mrr@12": mrr / n,
            "para-hit@3": lenient3 / n}


async def _wait_indexed(conn, prefix, n_items):
    while True:
        q = await conn.fetchval(f"SELECT count(*) FROM {prefix}_index_sync_queue")
        v = await conn.fetchval(f"SELECT count(*) FROM {prefix}_vec_{INDEX}")
        f = await conn.fetchval(f"SELECT count(*) FROM {prefix}_fts_{INDEX}")
        if q == 0 and v >= n_items and f >= n_items:
            return
        print(f"  waiting for indexing: queue {q:,}, vectors {v:,}/{n_items:,}, fts {f:,}", flush=True)
        await asyncio.sleep(30)


async def evaluate(a) -> int:
    sys.path.insert(0, a.memory_repo)
    import asyncpg
    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    from vital_saas_memory import kinds, query
    from vital_saas_memory.scope import MemoryScope
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from vitalgraph.model.sparql_model import SPARQLQueryRequest

    items = _read(a, "items")
    para_of = {it["id"]: it["paragraph"] for it in items}
    by_uri = {item_uri(it["id"]): it["id"] for it in items}
    by_uuid = {str(_generate_term_uuid(u, "U")): i for u, i in by_uri.items()}
    questions = _read(a, "questions")
    random.Random(a.seed).shuffle(questions)
    questions = questions[:a.n]
    print(f"{len(questions):,} questions (seed {a.seed}) against {len(items):,} items\n")

    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    await load_storage_keys(conn)
    p = space_prefix(SPACE)
    await _wait_indexed(conn, p, len(items))
    fts = f"{p}_fts_{INDEX}"
    ctx = str(_generate_term_uuid(GRAPH, "U"))
    results = {}

    # -- full-text ranking variants, as SQL on the index ------------------
    n_docs = await conn.fetchval(f"SELECT count(*) FROM {fts} WHERE context_uuid = $1::uuid", ctx)
    df = {r["word"]: r["ndoc"] for r in await conn.fetch(
        f"SELECT word, ndoc FROM ts_stat($q$SELECT tsv FROM {fts} "
        f"WHERE context_uuid = '{ctx}'::uuid$q$)")}

    async def pairs_of(text):
        runs = await conn.fetchval("SELECT vitalgraph_cjk_runs($1)", text) or []
        out = []
        for r in runs:
            out += [r] if len(r) == 1 else [r[i:i + 2] for i in range(len(r) - 1)]
        return list(dict.fromkeys(out))

    def lit(term):
        return "'" + term.replace("'", "''") + "'::tsquery"

    async def sql_rank(score_sql, where_sql):
        rows = await conn.fetch(
            f"SELECT subject_uuid FROM {fts} WHERE context_uuid = '{ctx}'::uuid AND ({where_sql}) "
            f"ORDER BY {score_sql} DESC, subject_uuid LIMIT 12")
        return [by_uuid.get(str(r["subject_uuid"])) for r in rows]

    variants = {k: [] for k in ("rank", "rank-norm1", "idf", "idf-prune5", "idf-min2")}
    timings = {k: [] for k in variants}
    for q in questions:
        ps = await pairs_of(q["question"])
        if not ps:
            for k in variants:
                variants[k].append([])
            continue
        any_q = "(" + " || ".join(lit(x) for x in ps) + ")"
        idf = {x: math.log(n_docs / max(1, df.get(x, 0))) for x in ps if df.get(x)}
        idf_sum = " + ".join(f"(CASE WHEN tsv @@ {lit(x)} THEN {w:.6f} ELSE 0 END)"
                             for x, w in idf.items()) or "0"
        kept = [x for x in idf if df[x] / n_docs <= 0.05]
        kept_sum = " + ".join(f"(CASE WHEN tsv @@ {lit(x)} THEN {idf[x]:.6f} ELSE 0 END)"
                              for x in kept) or "0"
        kept_q = "(" + " || ".join(lit(x) for x in kept) + ")" if kept else "FALSE"
        cnt = " + ".join(f"(tsv @@ {lit(x)})::int" for x in idf) or "0"
        specs = {
            "rank": (f"ts_rank_cd(tsv, {any_q})", f"tsv @@ {any_q}"),
            "rank-norm1": (f"ts_rank_cd(tsv, {any_q}, 1)", f"tsv @@ {any_q}"),
            "idf": (idf_sum, f"tsv @@ {any_q}"),
            "idf-prune5": (kept_sum, f"tsv @@ {kept_q}" if kept else "FALSE"),
            "idf-min2": (idf_sum, f"tsv @@ {any_q} AND ({cnt}) >= 2"),
        }
        for k, (score, where) in specs.items():
            t0 = time.monotonic()
            variants[k].append(await sql_rank(score, where))
            timings[k].append((time.monotonic() - t0) * 1000)
    for k in variants:
        results[f"sql:{k}"] = (_metrics(variants[k], questions, para_of),
                               statistics.median(timings[k]))

    # -- the memory service's own query, through the server ---------------
    VitalSigns()
    c = VitalGraphClient()
    await c.open()
    # The first load of `eval_drcd333` wrote no message dates, and the message
    # kind's query REQUIRES one (`?s hasKGChatMessageDateTime ?at`), so it
    # matched nothing. The date only feeds a date-range filter, which these
    # questions do not use, so the pattern is dropped here rather than
    # re-writing (and re-embedding) 19,910 messages. `load` now writes dates.
    kind = replace(kinds.MESSAGE, date_property=None) if a.no_date else kinds.MESSAGE
    scope = MemoryScope(SPACE, GRAPH)
    try:
        for name, alpha, reorder in (("vector", 1.0, False), ("vector+reorder", 1.0, True),
                                     ("hybrid", 0.5, False), ("fts", 0.0, False)):
            query.ALPHA = alpha
            ranked, lat = [], []
            for q in questions:
                req = query.RecallRequest(cues=q["question"], locale="zh-Hant")
                sparql = query.build_query(kind, scope, req)
                t0 = time.monotonic()
                resp = await c.sparql.execute_sparql_query(SPACE, SPARQLQueryRequest(query=sparql))
                lat.append((time.monotonic() - t0) * 1000)
                hits = query.fold(kind, query._bindings(resp))
                if reorder:
                    hits = query.cjk_first(hits, req.cues)
                ranked.append([by_uri.get(h.uri) for h in hits])
            results[f"server:{name}"] = (_metrics(ranked, questions, para_of), statistics.median(lat))
    finally:
        query.ALPHA = 0.5
        await c.close()
        await conn.close()

    cols = ("hit@1", "hit@3", "hit@12", "mrr@12", "para-hit@3")
    print(f"{'variant':<22}" + "".join(f"{c_:>11}" for c_ in cols) + f"{'median ms':>11}")
    for k, (m, ms) in results.items():
        print(f"{k:<22}" + "".join(f"{m[c_]:>11.3f}" for c_ in cols) + f"{ms:>11.1f}")
    with open(os.path.join(a.out, f"results_n{a.n}_seed{a.seed}.json"), "w") as f:
        json.dump({k: {"metrics": m, "median_ms": ms} for k, (m, ms) in results.items()}, f, indent=1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--drcd", required=True, help="directory holding DRCD_dev.json and DRCD_test.json")
    p.add_argument("--out", required=True)
    l_ = sub.add_parser("load")
    l_.add_argument("--out", required=True)
    l_.add_argument("--batch", type=int, default=500)
    l_.add_argument("--memory-repo", default=DEFAULT_MEMORY_REPO)
    e = sub.add_parser("eval")
    e.add_argument("--out", required=True)
    e.add_argument("--n", type=int, default=1000)
    e.add_argument("--seed", type=int, default=333)
    e.add_argument("--no-date", action="store_true",
                   help="drop the message date pattern (a space loaded without dates)")
    e.add_argument("--memory-repo", default=DEFAULT_MEMORY_REPO)
    add_pg_arguments(e)
    a = ap.parse_args()
    if a.cmd == "prepare":
        return prepare(a)
    return asyncio.run(load(a) if a.cmd == "load" else evaluate(a))


if __name__ == "__main__":
    sys.exit(main())
