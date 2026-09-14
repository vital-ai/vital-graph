"""A bench declared in the tree must appear in a baseline.

This is the guard for a failure mode that costs nothing at the time and
everything later: a bench whose FIXTURE errors never reaches the status
machinery, so its id is never stamped and it leaves the run file silently. It is
not recorded as failed — it is not recorded at all. The next promotion bakes the
absence in, and `compare_bench` cannot warn about a bench that is missing from
BOTH sides, so the coverage loss is invisible from then on.

That is not hypothetical. `query.partition.graph_scoped_pruning` disappeared
exactly this way, and what it was covering was a production defect: `frame_slot`
was never declared partitioned, so creating any space with `partition_quads > 0`
failed outright (`issues/190`). The bench that would have caught it was absent
rather than red, so nothing said so.

Run as a unit test rather than at promotion time deliberately. A promotion is
rare and deliberate; this condition can arrive with any commit, and catching it
one commit after it appears is worth far more than catching it whenever someone
next promotes.
"""
from __future__ import annotations

import json
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PERF = _ROOT / "tests" / "performance"
_BASELINES = _PERF / "baselines"

# Only `test_*.py`. `perf_record.py`'s module docstring shows the mark in a usage
# example, and a scan that reads it as a declaration reports a bench that does
# not exist — which is the same class of false signal this test exists to avoid.
_BENCH = re.compile(r'@pytest\.mark\.bench\(\s*["\']([^"\']+)')


def _declared() -> dict:
    out = {}
    for p in sorted(_PERF.glob("test_*.py")):
        for m in _BENCH.finditer(p.read_text(encoding="utf-8")):
            out.setdefault(m.group(1), p.name)
    return out


def _recorded() -> set:
    """Every bench id across ALL baselines — query, ingest and coverage.

    Globbed rather than named, so adding a tier does not silently narrow this
    check to the tiers someone remembered to list.
    """
    ids = set()
    for b in sorted(_BASELINES.glob("*.json")):
        for entry in json.loads(b.read_text(encoding="utf-8"))["benches"]:
            # A parametrised bench is stored as `id[param]`; the declaration is
            # the bare id, so compare on that.
            ids.add(entry["bench_id"].split("[")[0])
    return ids


def test_every_declared_bench_appears_in_some_baseline():
    declared, recorded = _declared(), _recorded()
    assert declared, "found no bench declarations — the scan is broken, not the tree"
    assert recorded, "found no baselines — the scan is broken, not the tree"

    missing = sorted((b, f) for b, f in declared.items() if b not in recorded)
    assert not missing, (
        "bench(es) declared in the tree but absent from every baseline:\n"
        + "\n".join(f"  {b}  ({f})" for b, f in missing)
        + "\n\nA bench is ABSENT rather than failed when its fixture errors: the "
          "status machinery never runs, so nothing is stamped. Check that file "
          "for a fixture that raises. If the bench was deliberately removed, "
          "remove its `@pytest.mark.bench` too, so the declaration and the "
          "baseline cannot disagree."
    )
