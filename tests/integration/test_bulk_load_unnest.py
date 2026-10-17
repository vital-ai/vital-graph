"""The set-based incremental insert stores exactly what executemany does — issues/271.

`insert_terms_quads_unnest` replaces one INSERT per row with one
`INSERT … SELECT FROM unnest(arrays)` per table for large incremental writes.
It must be a pure speed change: the same term rows (including the generated
`num_val` / `dt_val`), the same quads, the same skips of rows already stored,
and the same handling of a batch that repeats a row — which DO NOTHING settles
inside one statement, where a `NOT EXISTS` check would not.

Checked against executemany on two fresh spaces fed identical batches.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

G = URIRef("urn:unnest:g")


def _batch(lo, hi):
    out = []
    for i in range(lo, hi):
        s = URIRef(f"urn:unnest:s{i % 300}")
        out += [
            (s, URIRef("urn:unnest:name"), Literal(f"name {i}"), G),
            (s, URIRef("urn:unnest:n"), Literal(str(i), datatype=XSD.integer), G),
            (s, URIRef("urn:unnest:at"),
             Literal(f"2026-10-{1 + i % 28:02d}T00:00:00Z", datatype=XSD.dateTime), G),
            (s, URIRef("urn:unnest:label"), Literal(f"label {i % 7}", lang="en"), G),
            (s, URIRef("urn:unnest:knows"), URIRef(f"urn:unnest:s{(i + 1) % 300}"), G),
        ]
    return out


@pytest_asyncio.fixture(loop_scope="session")
async def two_spaces(make_space):
    return [await make_space(f"{TEST_SPACE_PREFIX}un{k}_{uuid.uuid4().hex[:4]}")
            for k in ("set", "row")]


async def _contents(pool, sid):
    async with pool.acquire() as c:
        terms = sorted(tuple(r) for r in await c.fetch(
            f"SELECT term_uuid::text, term_text, term_type, lang, datatype_id, "
            f"num_val::text, dt_val::text FROM {sid}_term"))
        quads = sorted(tuple(r) for r in await c.fetch(
            f"SELECT subject_uuid::text, predicate_uuid::text, object_uuid::text, "
            f"context_uuid::text FROM {sid}_rdf_quad"))
    return terms, quads


async def test_unnest_matches_executemany(space_impl, two_spaces, pg_pool, monkeypatch):
    from vitalgraph.db.sparql_sql import bulk_load
    set_sid, row_sid = two_spaces

    # The same three writes into each space: a first batch, then one that
    # overlaps it by half (rows already stored), then one that repeats rows
    # within itself.
    first, overlap = _batch(0, 400), _batch(200, 600)
    repeated = _batch(600, 700) + _batch(600, 700)
    for sid, threshold in ((set_sid, 1), (row_sid, 10**9)):
        monkeypatch.setattr(bulk_load, "UNNEST_MIN_ROWS", threshold)
        for b in (first, overlap, repeated):
            await space_impl.add_rdf_quads_batch_bulk(sid, b, rebuild_indexes=False)

    set_terms, set_quads = await _contents(pg_pool, set_sid)
    row_terms, row_quads = await _contents(pg_pool, row_sid)
    assert set_quads == row_quads
    assert set_terms == row_terms
    assert len(set_quads) == len({q[:3] for q in first + overlap + repeated})
    assert any(t[5] is not None for t in set_terms), "no numeric value was derived"
    assert any(t[6] is not None for t in set_terms), "no datetime value was derived"


async def test_a_large_write_takes_the_set_based_path(space_impl, make_space, caplog):
    import logging
    sid = await make_space(f"{TEST_SPACE_PREFIX}unpath_{uuid.uuid4().hex[:4]}")
    await space_impl.add_rdf_quads_batch_bulk(sid, _batch(0, 10))      # not empty
    with caplog.at_level(logging.INFO):
        await space_impl.add_rdf_quads_batch_bulk(sid, _batch(10, 400))
    lines = [r.getMessage() for r in caplog.records if "BULK insert" in r.getMessage()]
    assert lines and "[unnest]" in lines[-1], lines
    assert "wal=" in lines[-1] and "slot_sort_sync=" in lines[-1], lines[-1]
