#!/usr/bin/env python3
"""T0 — `vg:textSearch` / `vg:hybridSearch` parse search text with websearch_to_tsquery.

From `planning/planning_vector_geo/nurture_message_keyword_search_plan.md` §T0.

Two halves, because the defect classes are different:

  PART A  generation — what `_build_tsquery_expr` emits, and that the two
          call sites that must agree actually do. `text_search_sql` emits the
          `tsv @@ q` condition and the `ts_rank_cd(tsv, q)` scorer SEPARATELY;
          if they ever drift, a row can match and score 0, or score without
          matching. Nothing else checks that they are the same expression.

  PART B  semantics — run the generated tsquery through PostgreSQL and assert
          it means what the plan says. In particular that input yielding NO
          lexemes returns zero rows rather than raising or matching
          everything, which is the behaviour the docstring claims and which
          is the reason no empty-query guard was added.

Part B needs a database and is skipped without one. Part A is pure.

    python3 test_scripts/search/test_tsquery_parser.py
    VG_SEARCH_DSN=postgresql:///sparql_sql_graph python3 test_scripts/search/test_tsquery_parser.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from vitalgraph.db.sparql_sql.vg_functions import _build_tsquery_expr  # noqa: E402

PARSER = "websearch_to_tsquery"

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  — ' + detail) if detail and not cond else ''}")
    if not cond:
        _failures.append(name)


# ---------------------------------------------------------------------------
# PART A — generation
# ---------------------------------------------------------------------------

def part_a() -> None:
    print("\nPART A — generated SQL")

    one = _build_tsquery_expr(["english"], "saved application")
    check("single language uses websearch_to_tsquery", PARSER in one, one)
    check("single language is not wrapped", not one.startswith("("), one)
    check("regconfig cast retained", "'english'::regconfig" in one, one)

    two = _build_tsquery_expr(["english", "spanish"], "hola")
    check("multi-language ORs with ||", " || " in two, two)
    check("multi-language parenthesised", two.startswith("(") and two.endswith(")"), two)
    check("multi-language names both", "'english'::regconfig" in two
          and "'spanish'::regconfig" in two, two)
    check("multi-language uses the parser twice", two.count(PARSER) == 2, two)

    # Websearch syntax must survive into the SQL literal intact. The caller
    # escapes only `'` (vg_functions.py, `safe_text`), so quotes, `or` and a
    # leading `-` are ordinary characters here and must not be mangled.
    syntax = _build_tsquery_expr(["english"], '"saved app" or plaid -declined')
    check("double quotes survive", '"saved app"' in syntax, syntax)
    check("or survives", " or " in syntax, syntax)
    check("negation survives", "-declined" in syntax, syntax)

    # An apostrophe reaches this function already doubled. It must stay
    # doubled — halving it would end the SQL literal early.
    esc = _build_tsquery_expr(["english"], "don''t stop")
    check("pre-escaped apostrophe left alone", "don''t" in esc, esc)


# ---------------------------------------------------------------------------
# PART A2 — the two call sites agree
# ---------------------------------------------------------------------------

def _tsqueries_in(sql: str) -> list[str]:
    """Every websearch_to_tsquery(...) call in the SQL, balanced-paren aware."""
    out = []
    for m in re.finditer(re.escape(PARSER) + r"\(", sql):
        i = m.end() - 1
        depth = 0
        for j in range(i, len(sql)):
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append(sql[m.start():j + 1])
                    break
    return out


def part_a2() -> None:
    print("\nPART A2 — the match condition and the scorer use the SAME query")

    from vitalgraph.db.sparql_sql.vg_functions import (
        VG_TEXT_SEARCH, VG_HYBRID_SEARCH, text_search_sql, hybrid_search_sql,
    )
    try:
        from test_scripts.test_scripts_misc.test_vg_functions import (
            _make_ctx, _var, _lit,
        )
    except Exception as e:  # pragma: no cover
        print(f"  SKIP  cannot import the vg_functions test harness: {e}")
        return

    from vitalgraph.db.jena_sparql.jena_types import ExprFunction

    text = '"saved app" or plaid -declined'

    expr = ExprFunction(name="", function_iri=VG_TEXT_SEARCH,
                        args=[_var("entity"), _lit(text), _lit("kgtype_default")])
    sql = text_search_sql(expr, _make_ctx())
    qs = _tsqueries_in(sql or "")
    check("textSearch emits at least two tsquery calls", len(qs) >= 2,
          f"found {len(qs)}")
    check("textSearch: every tsquery call is identical", len(set(qs)) == 1,
          f"{set(qs)}")
    check("textSearch: search text reached the SQL", text in (sql or ""), sql or "")

    expr = ExprFunction(name="", function_iri=VG_HYBRID_SEARCH,
                        args=[_var("entity"), _lit(text), _lit("entity_default"),
                              _lit("0.5")])
    sql, _vr = hybrid_search_sql(expr, _make_ctx())
    qs = _tsqueries_in(sql or "")
    check("hybridSearch emits at least two tsquery calls", len(qs) >= 2,
          f"found {len(qs)}")
    check("hybridSearch: every tsquery call is identical", len(set(qs)) == 1,
          f"{set(qs)}")
    # The OR candidate condition lets a lexically-excluded row in through the
    # vector arm, so the BM25 term must be gated or a `-term` query weights a
    # document the user excluded. See the ts_rank_cd negation check in Part B.
    check("hybridSearch: BM25 term is gated on the match",
          "CASE WHEN f.tsv @@" in (sql or ""), sql or "")

    # textSearch needs no CASE — its WHERE already gates the score.
    expr = ExprFunction(name="", function_iri=VG_TEXT_SEARCH,
                        args=[_var("entity"), _lit(text), _lit("kgtype_default")])
    tsql = text_search_sql(expr, _make_ctx()) or ""
    check("textSearch gates via WHERE, so needs no CASE",
          "tsv @@" in tsql and "CASE WHEN" not in tsql, tsql)


# ---------------------------------------------------------------------------
# PART B — semantics, against a live PostgreSQL
# ---------------------------------------------------------------------------

CORPUS = "Your app is saved and just needs a couple more minutes to finish up"

# (label, search text, should the corpus sentence match?)
CASES = [
    ("bare terms AND",            "saved app",              True),
    ("bare terms AND, one absent", "saved plaid",           False),
    ("stemming",                  "saving apps",            True),
    ("quoted phrase, present",    '"app is saved"',         True),
    ("quoted phrase, wrong order", '"saved app"',           False),
    ("explicit or",               "plaid or saved",         True),
    ("negation excludes",         "saved -minutes",         False),
    ("negation of an absent term", "saved -plaid",          True),
    ("stop words only",           "the of and",             False),
    ("punctuation that breaks to_tsquery", "plaid!",        False),
    ("unbalanced paren",          "(saved",                 True),
    ("bare operators",            "a | b",                  False),
]


def part_b() -> None:
    print("\nPART B — semantics in PostgreSQL")
    dsn = os.environ.get("VG_SEARCH_DSN")
    if not dsn:
        print("  SKIP  set VG_SEARCH_DSN to run (e.g. postgresql:///sparql_sql_graph)")
        return
    try:
        import psycopg
    except ImportError:
        print("  SKIP  psycopg not importable")
        return

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for label, text, want in CASES:
            safe = text.replace("'", "''")
            q = _build_tsquery_expr(["english"], safe)
            try:
                cur.execute(
                    f"SELECT to_tsvector('english', %s) @@ {q}, "
                    # The GATED score — the form hybrid_search_sql emits. Raw
                    # ts_rank_cd is not the contract; see the negation check
                    # below for why.
                    f"       CASE WHEN to_tsvector('english', %s) @@ {q} "
                    f"            THEN ts_rank_cd(to_tsvector('english', %s), {q}) "
                    f"            ELSE 0 END",
                    (CORPUS, CORPUS, CORPUS),
                )
                matched, rank = cur.fetchone()
            except Exception as e:
                conn.rollback()
                check(f"{label}: {text!r} does not raise", False, repr(e))
                continue
            check(f"{label}: {text!r} -> match={want}", matched is want,
                  f"got {matched}")
            # A match must carry a positive gated score and a non-match zero,
            # or the fusion in hybrid_search_sql weights a row the lexical
            # query rejected.
            if matched:
                check(f"{label}: gated score > 0", rank > 0, f"rank={rank}")
            else:
                check(f"{label}: gated score is 0", rank == 0, f"rank={rank}")

        # ts_rank_cd IGNORES `!`. This is the reason hybrid_search_sql gates
        # its BM25 term with a CASE instead of calling ts_rank_cd bare. If a
        # future PostgreSQL fixes this, the gate becomes redundant but stays
        # correct — so this check documents the behaviour rather than
        # depending on it.
        cur.execute(
            "SELECT ts_rank_cd(to_tsvector('english', %s), "
            "                  websearch_to_tsquery('english','saved -minutes')), "
            "       ts_rank_cd(to_tsvector('english', %s), "
            "                  websearch_to_tsquery('english','saved'))",
            (CORPUS, CORPUS),
        )
        neg, pos = cur.fetchone()
        check("ts_rank_cd ignores negation (documents why the CASE exists)",
              neg == pos and neg > 0, f"negated={neg} plain={pos}")

        # The claim the docstring makes, stated directly.
        cur.execute(f"SELECT ({_build_tsquery_expr(['english'], 'the of and')})::text")
        check("stop-word-only input yields the EMPTY tsquery",
              cur.fetchone()[0] == "", "expected ''")

        # Multi-language: OR, so a match through either stemmer counts.
        q2 = _build_tsquery_expr(["english", "spanish"], "saved")
        cur.execute(f"SELECT to_tsvector('english', %s) @@ {q2}", (CORPUS,))
        check("multi-language still matches through english", cur.fetchone()[0] is True)


if __name__ == "__main__":
    part_a()
    part_a2()
    part_b()
    print()
    if _failures:
        print(f"FAILED — {len(_failures)} check(s): {', '.join(_failures)}")
        sys.exit(1)
    print("All checks passed.")
