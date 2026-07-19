"""Integration: CONTAINS/STRSTARTS/STRENDS use the GIN trigram index, and the
LIKE-metacharacter escaping preserves both index usage and correctness.

This is the EXPLAIN-based gate for
planning/planning_vector_geo/contains_like_metachar_escaping.md: it proves the
claim that escaping the needle (collect._like_escape) does NOT disable the
`idx_{space}_term_trgm` GIN index that makes substring search fast (the whole
reason CONTAINS compiles to LIKE rather than POSITION). Patterns are built with
the SAME helpers the emitter uses, so a regression in the escaping shows up here.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra, TEST_SPACE_PREFIX
from tests.performance.harness import (
    explain_json, uses_index, has_seq_scan_on, node_types)
from vitalgraph.db.sparql_sql.collect import _esc, _like_escape

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

# Enough rows that the planner prefers the GIN trigram index over a seq scan
# (proving it is *naturally chosen*, not forced).
N_FILLER = 15_000


def _needle(term: str) -> str:
    """The inlined LIKE needle exactly as filter_pushdown builds it."""
    return _esc(_like_escape(term))


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def trgm_space(pg_pool, make_space):
    sid = await make_space(f"{TEST_SPACE_PREFIX}trgm_{uuid.uuid4().hex[:8]}")
    async with pg_pool.acquire() as conn:
        rows = [(uuid.uuid4(), f"filler record {i} lorem ipsum dolor sit", "L")
                for i in range(N_FILLER)]
        rows += [
            (uuid.uuid4(), "promo save50%off today only", "L"),   # literal "50%"
            (uuid.uuid4(), "promo save500 off today only", "L"),  # wildcard decoy
            (uuid.uuid4(), "prefixtoken alpha starts here", "L"),  # STRSTARTS target
            (uuid.uuid4(), "beta ends with suffixtoken", "L"),     # STRENDS target
        ]
        await conn.copy_records_to_table(
            f"{sid}_term", records=rows,
            columns=["term_uuid", "term_text", "term_type"])
        await conn.execute(f"ANALYZE {sid}_term")
    yield sid


async def _assert_uses_trgm(conn, sid, pattern):
    idx = f"idx_{sid}_term_trgm"
    sql = f"SELECT term_uuid FROM {sid}_term WHERE term_text LIKE '{pattern}'"
    plan = await explain_json(conn, sql, analyze=True)
    assert uses_index(plan, idx), f"trgm index not used; nodes={node_types(plan)}\n{sql}"
    assert has_seq_scan_on(plan, [f"{sid}_term"]) is None, (
        f"seq scan on term table; nodes={node_types(plan)}\n{sql}")
    return plan


async def test_contains_escaped_uses_trigram_index_and_is_correct(pg_pool, trgm_space):
    sid = trgm_space
    pattern = f"%{_needle('save50%off')}%"          # -> %save50\%off%
    async with pg_pool.acquire() as conn:
        await _assert_uses_trgm(conn, sid, pattern)
        # Correctness: the escaped % matches literally — the "save500" decoy,
        # which the old unescaped '%save50%off%' would have wrongly matched, is
        # excluded.
        texts = [r["term_text"] for r in await conn.fetch(
            f"SELECT term_text FROM {sid}_term WHERE term_text LIKE '{pattern}'")]
    assert texts == ["promo save50%off today only"], texts


async def test_contains_plain_uses_trigram_index(pg_pool, trgm_space):
    sid = trgm_space
    async with pg_pool.acquire() as conn:
        await _assert_uses_trgm(conn, sid, f"%{_needle('save500')}%")


async def test_strstarts_uses_trigram_index(pg_pool, trgm_space):
    sid = trgm_space
    async with pg_pool.acquire() as conn:
        await _assert_uses_trgm(conn, sid, f"{_needle('prefixtoken')}%")


async def test_strends_uses_trigram_index(pg_pool, trgm_space):
    sid = trgm_space
    async with pg_pool.acquire() as conn:
        await _assert_uses_trgm(conn, sid, f"%{_needle('suffixtoken')}")
