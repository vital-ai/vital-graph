"""API latency benches for frame/slot paging.

Ported from `test_scripts/perf/measure_frame_slot_paging.py`, which stays in
place — it sweeps a range of sizes and prints a comparison table, which is the
right shape for investigation but the wrong shape for a standing gate. This
keeps the few measurements worth watching every run.

The seeding helper is **imported** from that script rather than reimplemented,
so the fixture shape cannot drift between the two.

Marked `slow`: it seeds frames over the REST path before it can measure
anything. `FRAMES` is deliberately smaller than the script's default (1000) to
keep a full perf run tractable — the scaling property being asserted does not
need the larger size to show up.

The headline bench is **deep-offset cost**. Offset paging is O(offset)
server-side, so the interesting number is not the absolute latency but the ratio
between a deep page and the first page. A regression there means paging got
worse in a way absolute timings on page 1 would never reveal.
"""

from __future__ import annotations

import os
import sys
import time

import pytest
import pytest_asyncio

from .conftest import skip_no_api

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_api,
              pytest.mark.asyncio(loop_scope="session")]

FRAMES = 400
SLOTS = 200

_SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test_scripts", "perf")
if _SCRIPT_DIR not in sys.path:
    sys.path.append(_SCRIPT_DIR)

try:
    from measure_frame_slot_paging import (  # noqa: E402
        seed as _seed, SPACE_ID, GRAPH_ID, ENTITY, FRAME_SEQ, _count)
    _HAVE_SCRIPT = True
except Exception:  # pragma: no cover - depends on test_scripts layout
    _HAVE_SCRIPT = False
    SPACE_ID = GRAPH_ID = ENTITY = FRAME_SEQ = None


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def paging_space(perf_client):
    """Seed a scratch space with FRAMES frames, drop it afterwards."""
    if not _HAVE_SCRIPT:
        pytest.skip("measure_frame_slot_paging not importable")

    from vitalgraph.model.spaces_model import Space
    try:
        await perf_client.add_space(Space(
            space=SPACE_ID, space_name=SPACE_ID,
            space_description="frame/slot paging bench"))
    except Exception:
        pass  # already exists

    await _seed(perf_client, FRAMES, SLOTS)
    yield SPACE_ID
    try:
        await perf_client.delete_space(SPACE_ID)
    except Exception:
        pass


async def _page(client, offset, sorted_by_seq=True):
    kw = {"sort_by": FRAME_SEQ, "sort_order": "asc"} if sorted_by_seq else {}
    t0 = time.perf_counter()
    resp = await client.get_kgentity_frames(
        space_id=SPACE_ID, graph_id=GRAPH_ID, entity_uri=ENTITY,
        page_size=25, offset=offset, **kw)
    return (time.perf_counter() - t0) * 1000.0, _count(resp)


@pytest.mark.bench("api.frame_paging.first_page")
async def test_first_page_latency(perf_client, perf_record, paging_space):
    # Warm up first. The first sequence-sorted page costs far more than a
    # subsequent one (term resolution / buffer warming); measuring it as if it
    # were steady-state once turned a one-off warm-up into an apparent "16x sort
    # penalty" in the original script.
    await _page(perf_client, 0)

    unsorted_ms, n1 = await _page(perf_client, 0, sorted_by_seq=False)
    sorted_ms, n2 = await _page(perf_client, 0, sorted_by_seq=True)

    perf_record(kind="api", dataset=f"synthetic:{FRAMES}frames",
                metrics={"unsorted_ms": round(unsorted_ms, 1),
                         "sorted_ms": round(sorted_ms, 1),
                         "rows": n2},
                notes=f"page 1 of {FRAMES} frames, page_size=25")

    assert n1 == 25 and n2 == 25, f"expected a full page, got {n1}/{n2}"


@pytest.mark.bench("api.frame_paging.deep_offset")
async def test_deep_offset_cost(perf_client, perf_record, paging_space):
    await _page(perf_client, 0)  # warm

    first_ms, _ = await _page(perf_client, 0)
    deep_offset = max(0, FRAMES - 25)
    deep_ms, deep_rows = await _page(perf_client, deep_offset)
    ratio = deep_ms / first_ms if first_ms else 0.0

    perf_record(kind="api", dataset=f"synthetic:{FRAMES}frames",
                metrics={"first_page_ms": round(first_ms, 1),
                         "deep_page_ms": round(deep_ms, 1),
                         "deep_offset_ratio": round(ratio, 2),
                         "offset": deep_offset,
                         "rows": deep_rows},
                notes="offset paging is O(offset); the ratio is the signal")

    assert deep_rows > 0, f"deep page at offset {deep_offset} returned nothing"
    # A generous absolute ceiling — the baseline is what detects drift. This
    # only catches paging becoming catastrophically offset-sensitive.
    assert ratio < 20, (
        f"deep page at offset {deep_offset} cost {ratio:.1f}x the first page")
