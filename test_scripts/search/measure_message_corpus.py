#!/usr/bin/env python3
"""T1 — characterise the message corpus before building any index.

From `planning/planning_vector_geo/nurture_message_keyword_search_plan.md` §T1.

This runs BEFORE an FTS index exists and decides whether one is worth building.
Direct SQL against the quad/term tables; no server, no client.

THE GATE THIS EXISTS TO ANSWER

Nurture messages are templated, and the term table dedupes identical literals.
So the number of message SLOTS says nothing about how much lexical corpus there
is. If the distinct text count is small, the whole problem may be servable by
the trigram path that already works (plan §2.1) and an FTS index is maintenance
for nothing. `distinct / total` is the templating factor and it is the first
number in the report.

IT ALSO ASSERTS AN INVARIANT THE PLAN DEPENDS ON

Plan §2.4 records that two `contains` criteria on the same slot type AND on the
SAME message — which is only true because a message-history frame carries
exactly one `MsgContent` slot. If that ever stops holding, those queries start
silently matching one word in one message and another word in a different one.
Measured here rather than assumed; a violation exits non-zero.

USAGE

    VG_SEARCH_DSN=postgresql:///<db> VG_SEARCH_SPACE=<space> VG_KG_NS=<ns>:kg \\
        python3 test_scripts/search/measure_message_corpus.py

    --slot-type URI     override ${VG_KG_NS}:slot:MsgContent
    --terms N           top-N terms by document frequency (0 to skip; default 25)
    --terms-sample N    cap the tsvector pass at N slots (default 20000, 0 = all)

`--terms` uses `ts_stat`, which builds a tsvector per sampled row. It is the
only expensive step here, so it is sampled by default and capped separately
from the rest of the report.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

P_SLOT_TYPE = HALEY + "hasKGSlotType"
P_TEXT_VALUE = HALEY + "hasTextSlotValue"
P_FRAME_URI = HALEY + "hasFrameGraphURI"
P_GRAPH_URI = HALEY + "hasKGGraphURI"
P_ENTITY_TYPE = HALEY + "hasKGEntityType"
C_TEXT_SLOT = HALEY + "KGTextSlot"

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else ("—" if n is None else str(n))


def _row(label: str, value, note: str = "") -> None:
    print(f"    {label:<42}{_fmt(value):>14}  {note}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("VG_SEARCH_DSN"))
    ap.add_argument("--space", default=os.environ.get("VG_SEARCH_SPACE"))
    ap.add_argument("--ns", default=os.environ.get("VG_KG_NS"))
    ap.add_argument("--slot-type", default=None)
    ap.add_argument("--terms", type=int, default=25)
    ap.add_argument("--terms-sample", type=int, default=20000)
    ap.add_argument("--sections", default="corpus,sizing,channel,invariants,terms",
                    help="comma-separated subset to run; the corpus pass is the "
                         "expensive one — minutes on a large corpus)")
    a = ap.parse_args()

    if not a.dsn or not a.space:
        print("Set VG_SEARCH_DSN and VG_SEARCH_SPACE (or pass --dsn/--space).")
        return 2
    if not a.slot_type and not a.ns:
        print("Set VG_KG_NS (e.g. 'urn:acme:kg') or pass --slot-type.")
        return 2

    slot_msg = a.slot_type or f"{a.ns}:slot:MsgContent"
    slot_chan = f"{a.ns}:slot:MsgChannel" if a.ns else None
    slot_subj = f"{a.ns}:slot:MsgSubject" if a.ns else None
    entity_na = f"{a.ns}:entity:NurtureAction" if a.ns else None

    want = {x.strip() for x in a.sections.split(",") if x.strip()}

    import psycopg

    q = f"{a.space}_rdf_quad"
    t = f"{a.space}_term"

    print(f"\nspace={a.space}  slot={slot_msg}")

    with psycopg.connect(a.dsn) as conn, conn.cursor() as cur:
        # --- resolve every URI to a term uuid in one round trip -------------
        uris = [P_SLOT_TYPE, P_TEXT_VALUE, P_FRAME_URI, P_GRAPH_URI,
                P_ENTITY_TYPE, RDF_TYPE, C_TEXT_SLOT, slot_msg]
        uris += [u for u in (slot_chan, slot_subj, entity_na) if u]
        cur.execute(
            f"SELECT term_text, term_uuid FROM {t} WHERE term_text = ANY(%s)",
            (uris,),
        )
        u = dict(cur.fetchall())
        missing = [x for x in (P_SLOT_TYPE, P_TEXT_VALUE, slot_msg) if x not in u]
        if missing:
            print(f"\nNo term row for: {missing}")
            print("Wrong space, or this space holds no message slots.")
            return 2

        # --- 1. the gate: slots vs distinct text ----------------------------
        # `slots` is needed by later sections, and is cheap on its own.
        cur.execute(
            f"SELECT count(DISTINCT subject_uuid) FROM {q} "
            f"WHERE predicate_uuid = %s AND object_uuid = %s",
            (u[P_SLOT_TYPE], u[slot_msg]),
        )
        slots = cur.fetchone()[0]
        distinct = None

        print("\n1. CORPUS SIZE — the gate")
        if "corpus" not in want:
            _row("message slots", slots)
            print("    (skipped: --sections has no 'corpus'; it is the ~5 min pass)")
        else:
          t0 = time.monotonic()
          cur.execute(
              f"""
              WITH mc AS (
                SELECT DISTINCT subject_uuid FROM {q}
                WHERE predicate_uuid = %s AND object_uuid = %s
              ), v AS (
                SELECT mc.subject_uuid, tv.term_text
                FROM mc
                JOIN {q} qv ON qv.subject_uuid = mc.subject_uuid
                           AND qv.predicate_uuid = %s
                JOIN {t} tv ON tv.term_uuid = qv.object_uuid
              )
              SELECT (SELECT count(*) FROM mc),
                     (SELECT count(*) FROM v),
                     (SELECT count(DISTINCT term_text) FROM v),
                     (SELECT count(*) FROM v WHERE btrim(term_text) = ''),
                     (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY length(term_text)) FROM v),
                     (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY length(term_text)) FROM v),
                     (SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY length(term_text)) FROM v),
                     (SELECT max(length(term_text)) FROM v)
              """,
              (u[P_SLOT_TYPE], u[slot_msg], u[P_TEXT_VALUE]),
          )
          (slots, values, distinct, empty,
           p50, p90, p99, maxlen) = cur.fetchone()
          elapsed = time.monotonic() - t0

          _row("message slots", slots)
          _row("values on them", values,
               "" if values == slots else f"{values - slots:+,} vs slots")
          _row("DISTINCT texts", distinct,
               f"templating factor {values / distinct:.1f}x" if distinct else "")
          _row("empty / whitespace-only values", empty,
               "must not be indexed" if empty else "")
          print()
          _row("length p50", int(p50) if p50 is not None else None, "chars")
          _row("length p90", int(p90) if p90 is not None else None, "chars")
          _row("length p99", int(p99) if p99 is not None else None, "chars")
          _row("length max", maxlen, "chars")
          print(f"    ({elapsed:.1f}s)")

        # --- 2. index sizing / inflation ------------------------------------
        if "sizing" in want:
         print("\n2. INDEX SIZING")
         all_text_slots = None
         if C_TEXT_SLOT in u and RDF_TYPE in u:
             cur.execute(
                 f"SELECT count(DISTINCT subject_uuid) FROM {q} WHERE predicate_uuid = %s AND object_uuid = %s",
                 (u[RDF_TYPE], u[C_TEXT_SLOT]),
             )
             all_text_slots = cur.fetchone()[0]
         _row("all KGTextSlot subjects", all_text_slots,
              f"{all_text_slots / slots:.1f}x inflation" if all_text_slots and slots else "")
         print("    ^ what an FTS index populated by type_uri would hold (plan §3.2);")
         print("      the message slots above are what it actually needs.")

         if entity_na and entity_na in u and P_ENTITY_TYPE in u:
             cur.execute(
                 f"SELECT count(DISTINCT subject_uuid) FROM {q} WHERE predicate_uuid = %s AND object_uuid = %s",
                 (u[P_ENTITY_TYPE], u[entity_na]),
             )
             n = cur.fetchone()[0]
             _row("NurtureAction entities", n,
                  f"{slots / n:.1f} messages each" if n else "")

        # --- 3. channel / subject -------------------------------------------
        if "channel" in want:
         print("\n3. CHANNEL AND SUBJECT")
         if slot_chan and slot_chan in u:
             cur.execute(
                 f"""
                 WITH ch AS (
                   SELECT DISTINCT subject_uuid FROM {q}
                   WHERE predicate_uuid = %s AND object_uuid = %s
                 )
                 SELECT tv.term_text, count(*)
                 FROM ch
                 JOIN {q} qv ON qv.subject_uuid = ch.subject_uuid
                            AND qv.predicate_uuid = %s
                 JOIN {t} tv ON tv.term_uuid = qv.object_uuid
                 GROUP BY 1 ORDER BY 2 DESC LIMIT 10
                 """,
                 (u[P_SLOT_TYPE], u[slot_chan], u[P_TEXT_VALUE]),
             )
             for text, n in cur.fetchall():
                 _row(f"channel = {text}", n)
         if slot_subj and slot_subj in u:
             cur.execute(
                 f"SELECT count(DISTINCT subject_uuid) FROM {q} WHERE predicate_uuid = %s AND object_uuid = %s",
                 (u[P_SLOT_TYPE], u[slot_subj]),
             )
             ns_ = cur.fetchone()[0]
             _row("MsgSubject slots", ns_,
                  f"{ns_ / slots * 100:.1f}% of messages" if slots else "")

        # --- 4. invariants ---------------------------------------------------
        if "invariants" in want:
         print("\n4. INVARIANTS")

         # (a) one MsgContent slot per frame — plan §2.4 depends on it.
         if P_FRAME_URI in u:
             cur.execute(
                 f"""
                 WITH mc AS (
                   SELECT DISTINCT subject_uuid FROM {q}
                   WHERE predicate_uuid = %s AND object_uuid = %s
                 ), fr AS (
                   SELECT mc.subject_uuid AS slot, qf.object_uuid AS frame_uuid
                   FROM mc
                   JOIN {q} qf ON qf.subject_uuid = mc.subject_uuid
                              AND qf.predicate_uuid = %s
                 ), f AS (
                   -- count DISTINCT slots, not join rows. A slot carrying a
                   -- duplicated hasFrameGraphURI (see the next check) produces
                   -- several rows for ONE message, and counting rows reports it
                   -- as a frame holding several messages. That false positive
                   -- cost a retraction on 2026-09-21; do not "simplify" this
                   -- back to count(*).
                   SELECT frame_uuid, count(DISTINCT slot) AS n
                   FROM fr GROUP BY 1
                 )
                 SELECT (SELECT count(*) FROM f),
                        (SELECT coalesce(max(n), 0) FROM f),
                        (SELECT count(*) FROM f WHERE n > 1),
                        (SELECT count(*) FROM (
                           SELECT slot FROM fr GROUP BY slot HAVING count(*) > 1) d)
                 """,
                 (u[P_SLOT_TYPE], u[slot_msg], u[P_FRAME_URI]),
             )
             frames, max_per_frame, multi, dup_frame_uri = cur.fetchone()
             _row("distinct frames holding a message", frames)
             _row("max messages in one frame", max_per_frame)
             check("one MsgContent slot per frame (plan §2.4 rests on this)",
                   multi == 0,
                   f"{multi:,} frames hold more than one — the two-`contains` "
                   f"workaround in §2.4 is NO LONGER equivalent to a "
                   f"single-message AND")
             _row("slots with >1 hasFrameGraphURI row", dup_frame_uri,
                  "see the note below" if dup_frame_uri else "")

         # (b) one value per slot — issues/175 duplicates.
         cur.execute(
             f"""
             WITH mc AS (
               SELECT DISTINCT subject_uuid FROM {q}
               WHERE predicate_uuid = %s AND object_uuid = %s
             ), n AS (
               -- Two DIFFERENT things, and conflating them overstates the
               -- corruption. `nrows` counts storage rows: where the PK carries
               -- a quad_uuid column the same value stored twice is two rows
               -- and means nothing semantically. `nvals` counts DISTINCT
               -- objects — a slot really holding two different message texts,
               -- which is the issues/175 defect.
               SELECT mc.subject_uuid,
                      count(*)                       AS nrows,
                      count(DISTINCT qv.object_uuid) AS nvals
               FROM mc
               JOIN {q} qv ON qv.subject_uuid = mc.subject_uuid
                          AND qv.predicate_uuid = %s
               GROUP BY 1
             )
             SELECT count(*) FILTER (WHERE nvals > 1), coalesce(max(nvals), 0),
                    count(*) FILTER (WHERE nrows > 1)
             FROM n
             """,
             (u[P_SLOT_TYPE], u[slot_msg], u[P_TEXT_VALUE]),
         )
         dup_slots, max_vals, dup_rows = cur.fetchone()
         _row("slots with >1 DISTINCT text value", dup_slots,
              f"max {max_vals} (issues/175)" if dup_slots else "")
         _row("slots with >1 storage row", dup_rows,
              "duplicate rows, not extra values" if dup_rows else "")
         # Not a failure — issues/175 documents these as known and rare. But an
         # FTS populator concatenating them silently changes the indexed text,
         # so the count belongs in the report.
         #
         # `nrows` and `nvals` are deliberately separate. On a space whose
         # quad PK carries a quad_uuid column the same triple can be stored
         # more than once, so a row count reports duplicate STORAGE as
         # duplicate VALUES and overstates the issues/175 corruption several
         # times over. Observed once on a dataset since dropped; the guard
         # stays because the PK shape that allows it still exists in the wild.
         # On a space with the 4-column PK the two columns agree and this
         # costs nothing.

         # (c) every message slot carries the entity link the plan relies on.
         if P_GRAPH_URI in u:
             cur.execute(
                 f"""
                 WITH mc AS (
                   SELECT DISTINCT subject_uuid FROM {q}
                   WHERE predicate_uuid = %s AND object_uuid = %s
                 )
                 SELECT count(*) FROM mc
                 WHERE NOT EXISTS (
                   SELECT 1 FROM {q} g
                   WHERE g.subject_uuid = mc.subject_uuid
                     AND g.predicate_uuid = %s)
                 """,
                 (u[P_SLOT_TYPE], u[slot_msg], u[P_GRAPH_URI]),
             )
             orphans = cur.fetchone()[0]
             check("every message slot has hasKGGraphURI (the §1.1 entity link)",
                   orphans == 0,
                   f"{orphans:,} slots cannot be joined back to an entity")

        # --- 5. term frequency ----------------------------------------------
        if a.terms and "terms" in want:
            print(f"\n5. TOP {a.terms} TERMS BY DOCUMENT FREQUENCY")
            lim = f"LIMIT {a.terms_sample}" if a.terms_sample else ""
            t0 = time.monotonic()
            cur.execute(
                f"""
                SELECT word, ndoc FROM ts_stat($q$
                  WITH mc AS (
                    SELECT DISTINCT subject_uuid FROM {q}
                    WHERE predicate_uuid = '{u[P_SLOT_TYPE]}'
                      AND object_uuid = '{u[slot_msg]}'
                    {lim}
                  )
                  SELECT to_tsvector('english', tv.term_text)
                  FROM mc
                  JOIN {q} qv ON qv.subject_uuid = mc.subject_uuid
                             AND qv.predicate_uuid = '{u[P_TEXT_VALUE]}'
                  JOIN {t} tv ON tv.term_uuid = qv.object_uuid
                $q$) ORDER BY ndoc DESC LIMIT %s
                """,
                (a.terms,),
            )
            rows = cur.fetchall()
            sampled = min(a.terms_sample, slots) if a.terms_sample else slots
            print(f"    over {sampled:,} sampled messages ({time.monotonic() - t0:.1f}s)")
            over_half = 0
            for word, ndoc in rows:
                pct = ndoc / sampled * 100
                if pct > 50:
                    over_half += 1
                print(f"    {word:<24}{ndoc:>10,}  {pct:5.1f}% of documents")
            print()
            print(f"    {over_half} of the top {len(rows)} appear in >50% of messages.")
            print("    A term in most documents carries almost no IDF, so ranking")
            print("    between those documents comes down to ts_rank_cd's cover")
            print("    density — the proximity signal (plan §2.4). Many such terms")
            print("    means single-word queries will rank near-arbitrarily.")

    # --- verdict -------------------------------------------------------------
    print("\nGATE")
    if distinct is None:
        print("    not evaluated — the corpus pass was skipped.")
    elif slots < 20_000:
        print(f"    NOT DECIDABLE HERE — {slots:,} messages is a correctness")
        print("    fixture, not a corpus. The templating factor is the part that")
        print(f"    does carry over: {values / distinct:.1f}x. Everything else needs a")
        print("    dataset two orders of magnitude larger (plan §1.6).")
    elif distinct < 10_000:
        print(f"    {distinct:,} distinct texts is SMALL. The trigram path (plan §2.1)")
        print("    may serve this corpus without an FTS index at all. Weigh the")
        print("    semantic gains (stemming, tokens, ranking, multi-word) against")
        print("    maintaining a second index before proceeding to T3.")
    else:
        print(f"    {distinct:,} distinct texts is a real corpus. An FTS index is")
        print("    justified on size; proceed to T3.")

    print()
    if _failures:
        print(f"FAILED — {len(_failures)} invariant(s): {', '.join(_failures)}")
        return 1
    print("Invariants hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
