#!/usr/bin/env python3
"""Item 1 — populating an FTS index can be narrowed to ONE slot type.

Plan §3.2. Before this, the narrowest subject filter `populate_fts_index`
offered was `type_uri`, matched against rdf:type. Every text-bearing KG slot
has the same rdf:type (haley-ai-kg#KGTextSlot), so a "message index" built
that way held every text slot in the graph — company names, lead statuses,
everything — which is both 56x too big on the measured space and a corruption
of the IDF that ranking depends on.

This asserts the three selectors pick what they claim, by running the actual
SQL the populator runs. It does NOT populate an index: the point is the
subject SELECTION, and running it as SQL keeps the test fast and independent
of mapping configuration.

    VG_SEARCH_DSN=postgresql:///<db> VG_SEARCH_SPACE=<space> VG_KG_NS=<ns>:kg \\
        python3 test_scripts/search/test_slot_type_filter.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from vitalgraph.vectorization.fts_populator import (  # noqa: E402
    ALL_SUBJECTS_SQL,
    SLOT_AND_TYPE_SUBJECTS_SQL,
    SLOT_TYPED_SUBJECTS_SQL,
    TYPED_SUBJECTS_SQL,
)

KG_TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def main() -> int:
    dsn = os.environ.get("VG_SEARCH_DSN")
    space = os.environ.get("VG_SEARCH_SPACE")
    ns = os.environ.get("VG_KG_NS")
    if not (dsn and space and ns):
        print("Set VG_SEARCH_DSN, VG_SEARCH_SPACE and VG_KG_NS.")
        return 2

    slot_msg = f"{ns}:slot:MsgContent"
    tables = {"rdf_quad": f"{space}_rdf_quad", "term": f"{space}_term"}

    import psycopg

    def count(sql: str, *params) -> int:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM ({sql}) s",
                        params)
            return cur.fetchone()[0]

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT context_uuid FROM {space}_rdf_quad LIMIT 2")
            ctxs = [r[0] for r in cur.fetchall()]
        if len(ctxs) != 1:
            print(f"  expected one context in {space}, found {len(ctxs)} — "
                  f"pass a specific one before trusting these counts")
            if not ctxs:
                return 2
        ctx = ctxs[0]

        # asyncpg uses $1/$2; psycopg uses %s. Same SQL, different marker.
        def pg(sql: str) -> str:
            out = sql
            for i in range(4, 0, -1):
                out = out.replace(f"${i}", "%s")
            return out.format(**tables)

        n_all = count(pg(ALL_SUBJECTS_SQL), ctx)
        n_type = count(pg(TYPED_SUBJECTS_SQL), ctx, KG_TEXT_SLOT)
        n_slot = count(pg(SLOT_TYPED_SUBJECTS_SQL), ctx, slot_msg)
        n_both = count(pg(SLOT_AND_TYPE_SUBJECTS_SQL), ctx, slot_msg, KG_TEXT_SLOT)

        print(f"\nspace={space}  slot={slot_msg}\n")
        print(f"    no filter                     {n_all:>10,}")
        print(f"    type_uri = KGTextSlot         {n_type:>10,}")
        print(f"    slot_type_uri = MsgContent    {n_slot:>10,}")
        print(f"    both                          {n_both:>10,}")
        if n_slot:
            print(f"\n    the filter this adds narrows by {n_type / n_slot:.1f}x")
        print()

        check("slot_type_uri finds something at all", n_slot > 0,
              "no subjects — wrong VG_KG_NS, or this space has no messages")
        check("slot_type_uri is strictly narrower than type_uri", n_slot < n_type,
              f"{n_slot:,} vs {n_type:,}")
        check("type_uri is narrower than no filter", n_type < n_all,
              f"{n_type:,} vs {n_all:,}")

        # Message slots are text slots, so combining the two filters must not
        # lose any of them. If this fails the AND is wrong, not the data.
        check("both filters == slot filter alone (messages ARE text slots)",
              n_both == n_slot, f"both={n_both:,} slot={n_slot:,}")

        # The selected subjects must all really carry that slot type — a
        # filter that merely returns FEWER rows is not the same as a filter
        # that returns the RIGHT rows.
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(*) FROM ({pg(SLOT_TYPED_SUBJECTS_SQL)}) s
                WHERE NOT EXISTS (
                  SELECT 1 FROM {space}_rdf_quad q
                  JOIN {space}_term tp ON tp.term_uuid = q.predicate_uuid
                  JOIN {space}_term to_ ON to_.term_uuid = q.object_uuid
                  WHERE q.subject_uuid = s.subject_uuid
                    AND tp.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType'
                    AND to_.term_text = %s)
                """,
                (ctx, slot_msg, slot_msg),
            )
            wrong = cur.fetchone()[0]
        check("every selected subject really has that slot type", wrong == 0,
              f"{wrong:,} do not")

        # DISTINCT matters on any space whose quad PK carries quad_uuid.
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM ({pg(SLOT_TYPED_SUBJECTS_SQL)}) s",
                        (ctx, slot_msg))
            rows = cur.fetchone()[0]
            cur.execute(
                f"SELECT count(DISTINCT subject_uuid) FROM ({pg(SLOT_TYPED_SUBJECTS_SQL)}) s",
                (ctx, slot_msg))
            uniq = cur.fetchone()[0]
        check("selection returns no duplicate subjects", rows == uniq,
              f"{rows:,} rows for {uniq:,} subjects — DISTINCT was dropped")

    print()
    if _failures:
        print(f"FAILED — {len(_failures)}: {', '.join(_failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
