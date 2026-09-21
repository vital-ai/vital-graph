#!/usr/bin/env python3
"""Item 2 / issues/216 — `search text` reads the FTS table and parses safely.

The defect this guards against had two halves:

  1. `cmd_search_text` selected `tsv` and `search_text` FROM {space}_vec_{idx}.
     The FTS decoupling moved both columns to {space}_fts_{idx}, so the query
     referenced columns that do not exist and could not return a row on any
     space created since. It also resolved its default index from
     {space}_vector_index, the wrong registry.

  2. It built a tsquery with `" & ".join(text.split())` and `to_tsquery` —
     the operator-syntax parser, which RAISES on ordinary input like `plaid!`.

Neither was caught because the command wraps its body in
`except Exception: print(...)` and returns True, so a broken query prints a
line and the CLI carries on. Nothing in tests/ covered it. That is the actual
lesson, so this test asserts BOTH the SQL shape (statically, against the
source) and its behaviour (against a real FTS table).

    VG_SEARCH_DSN=postgresql:///<db> python3 test_scripts/search/test_search_text_cmd.py
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def part_a() -> None:
    """The command's own source — cheap, needs no database."""
    print("\nPART A — what cmd_search_text references")
    from vitalgraph.search_cmd.vitalgraphsearchutil_cmd import VitalGraphSearchUtilREPL

    src = inspect.getsource(VitalGraphSearchUtilREPL.cmd_search_text)
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))

    check("reads the FTS data table", "_fts_{index_name}" in body or "fts_table" in body)
    check("does NOT read the vector data table", "_vec_" not in body, body[:200])
    check("resolves the default index from the FTS registry",
          "_fts_index" in body)
    check("does NOT use the vector registry", "_vector_index" not in body)
    check("uses websearch_to_tsquery", "websearch_to_tsquery" in body)
    check("does NOT use to_tsquery", not re.search(r"(?<!websearch_)(?<!plainto_)to_tsquery", body))
    check("no hand-rolled ' & ' tokenizer", '" & ".join' not in body)


def part_b() -> None:
    """The SQL it builds, against a real FTS table."""
    print("\nPART B — the query runs and behaves")
    dsn = os.environ.get("VG_SEARCH_DSN")
    if not dsn:
        print("  SKIP  set VG_SEARCH_DSN")
        return
    try:
        import psycopg
    except ImportError:
        print("  SKIP  psycopg not importable")
        return

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name LIKE %s
              AND table_name NOT LIKE %s
            ORDER BY table_name LIMIT 1
        """, ('%\\_fts\\_%', '%\\_fts\\_index'))
        row = cur.fetchone()
        if not row:
            print("  SKIP  no FTS data table in this database")
            return
        table = row[0]

        cur.execute(f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s
        """, (table,))
        cols = {r[0] for r in cur.fetchall()}
        print(f"    table {table}: {sorted(cols)}")
        check("FTS table really has tsv and search_text",
              {"tsv", "search_text", "subject_uuid"} <= cols, str(sorted(cols)))

        tsq = "websearch_to_tsquery('english'::regconfig, %s)"
        sql = (f"SELECT subject_uuid, ts_rank_cd(tsv, {tsq}) AS rank, "
               f"LEFT(search_text, 80) FROM {table} "
               f"WHERE tsv @@ ({tsq}) ORDER BY rank DESC LIMIT %s")

        # The inputs that broke the old parser must not raise now.
        for text in ["the", "plaid!", "(x", "a | b", "AT&T", "don't",
                     '"a phrase" or thing -excluded', "the of and"]:
            try:
                cur.execute(sql, (text, text, 5))
                cur.fetchall()
                check(f"query {text!r} does not raise", True)
            except Exception as e:
                conn.rollback()
                check(f"query {text!r} does not raise", False, repr(e))

        # And a term drawn from the table's own text must actually match, or
        # the query could be "safe" by matching nothing at all.
        cur.execute(f"SELECT search_text FROM {table} "
                    f"WHERE search_text IS NOT NULL AND length(search_text) > 20 LIMIT 1")
        got = cur.fetchone()
        if got:
            words = [w for w in re.findall(r"[A-Za-z]{5,}", got[0])][:1]
            if words:
                cur.execute(sql, (words[0], words[0], 5))
                hits = cur.fetchall()
                check(f"a term from the corpus ({words[0]!r}) matches",
                      len(hits) > 0)
                check("matches carry a positive rank",
                      all(h[1] > 0 for h in hits) if hits else False)


if __name__ == "__main__":
    part_a()
    part_b()
    print()
    if _failures:
        print(f"FAILED — {len(_failures)}: {', '.join(_failures)}")
        sys.exit(1)
    print("All checks passed.")
