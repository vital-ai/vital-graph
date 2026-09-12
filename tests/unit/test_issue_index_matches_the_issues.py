"""The issues index must not claim OPEN for an issue its own file calls resolved.

`issues/README.md` is the entry point — its header says the grouping is "by what
a fix would touch", and it is the first thing anyone reads before picking work.
When it drifts it does not merely go stale, it MISDIRECTS: on 2026-09-11 seven
of thirty-five rows said OPEN for issues resolved in their own files, and the
row the index labelled "Start here" (`048`) had been finished on 2026-08-17.
Four had been wrong for over three weeks.

This is the same failure as a stale `frame_entity_drift(` reference that
silently stopped a coverage test covering, and as `184` sitting OPEN after the
code it described was deleted: **a pointer that outlives what it points at.**
Those are caught by tests now; this is the same guard for the index.

Deliberately one-directional. A row may say OPEN while the file has no status
line at all, and a row may carry extra nuance ("FIXED; direction gate still
open") that no checker should try to adjudicate. The only thing asserted is the
contradiction that misdirects: index says OPEN, file says done.

WHAT THIS CANNOT CATCH, and it has already bitten
-------------------------------------------------
A HEDGED status. On 2026-09-11 the index said `088` was "partially fixed ...
still 9.7 s in 22 of 79 spaces" while its file said RESOLVED at 43.4 ms — the
row was carrying the PRE-FIX numbers. `022` said "partially resolved" against a
file saying RESOLVED. Neither says "OPEN", so neither is caught here, and both
misdirect exactly as much.

Widening the check to flag any hedged word would produce FALSE POSITIVES on the
real thing: `070` is genuinely "largely fixed" (the scaling caveat stands) and
`096` genuinely has an unbuilt direction gate despite a status line that reads
FIXED. Distinguishing "hedged and accurate" from "hedged and stale" means
reading the body, which is a judgement, not an assertion.

So this test covers the unambiguous case and the rest needs a human. Saying so
here is better than a checker that quietly adjudicates nuance and is wrong in
both directions.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ISSUES = pathlib.Path(__file__).resolve().parents[2] / "issues"
RESOLVED = re.compile(r"^(FIXED|RESOLVED|CLOSED|DECLINED)\b", re.I)
ROW = re.compile(r"^\|\s*\*{0,2}(\d{3})\*{0,2}\s*\|\s*([^|]+?)\s*\|", re.M)


def _index_rows():
    readme = ISSUES / "README.md"
    if not readme.exists():
        pytest.skip("no issues index")
    return ROW.findall(readme.read_text())


def _file_status(num: str):
    matches = list(ISSUES.glob(f"{num}_*.md"))
    if not matches:
        return None
    m = re.search(r"^##\s*Status:\s*(.+)$", matches[0].read_text(), re.M)
    return m.group(1).strip() if m else None


def test_no_row_says_open_for_a_resolved_issue():
    bad = []
    for num, index_status in _index_rows():
        real = _file_status(num)
        if real is None:
            continue
        if index_status.lower().startswith("open") and RESOLVED.match(real):
            bad.append(f"{num}: index={index_status!r} file={real[:60]!r}")
    assert not bad, (
        "the index calls these OPEN but their own files say otherwise, which "
        "sends the next person to redo finished work:\n  " + "\n  ".join(bad))


def test_every_indexed_issue_has_a_file():
    """A row pointing at nothing is the same class of defect."""
    missing = [num for num, _ in _index_rows() if not list(ISSUES.glob(f"{num}_*.md"))]
    assert not missing, f"indexed but no such issue file: {missing}"


def test_the_check_can_see_the_index():
    """Guard the guard: a regex that matches nothing would pass forever."""
    rows = _index_rows()
    assert len(rows) > 10, f"parsed only {len(rows)} rows — the row pattern broke"


def test_issue_numbers_are_unique():
    """Two files sharing a number is a silent editing hazard, not just untidy.

    Added 2026-09-12 after doing it: `194` was first written as `190`, which
    already existed. The number collided and so did the EDIT — a later script
    reached for the file with `glob("190_*.md")`, matched the other one, and its
    assertion failed, so a commit landed whose message described a body that was
    never written.

    Checking 185-189 for a free number and stopping there is what caused it; the
    highest in use was 193.
    """
    import collections
    import pathlib as _p
    import re as _re

    nums = collections.defaultdict(list)
    for f in (_p.Path(__file__).resolve().parents[2] / "issues").glob("*.md"):
        m = _re.match(r"^(\d+)_", f.name)
        if m:
            nums[m.group(1)].append(f.name)
    dupes = {n: sorted(v) for n, v in nums.items() if len(v) > 1}
    assert not dupes, f"issue numbers used more than once: {dupes}"
