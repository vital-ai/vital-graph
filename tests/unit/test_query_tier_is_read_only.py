"""The query performance tier must stay read-only.

The performance suite is split in two, and the split is on whether a test
WRITES: imports, exports and modifications carry `ingest_bench` and get their
own baseline; everything else is read-only. The read-only tier is the one that
stays fast enough to run and promote on every query fix, so a mutating test
that sneaks into it costs exactly the property the split exists to protect.

This is a static scan, deliberately: it catches a new file added without the
marker, which is the way the tier has drifted before, and it costs nothing to
run. A file carrying `ingest_bench` anywhere is treated as ingest-tier.
"""
import pathlib
import re

import pytest

PERF = pathlib.Path(__file__).resolve().parents[1] / "performance"

# Executing statements, not strings that merely mention them: `create_space_indexes_sql`
# builds SQL to compare against pg_indexes and never runs it, and `_load_manifest`
# reads a JSON file. Both are read-only and must not trip this.
# `resync_*` is in here because a test can mutate through a HELPER without any
# SQL of its own: `test_entity_fanout` called `resync_entity_fanout`, which
# TRUNCATEs and re-INSERTs, and this scan passed it as read-only. A guard that
# only reads literal SQL sees the shape of the write, not the write.
MUTATORS = re.compile(
    r"create_space_with_tables|drop_space|DROP\s+INDEX|INSERT\s+INTO"
    r"|\.executemany\(|\bresync_[a-z_]+\("
)


def _query_tier_files():
    for p in sorted(PERF.glob("test_*.py")):
        text = p.read_text()
        if "ingest_bench" not in text:
            yield p, text


@pytest.mark.parametrize("path,text", list(_query_tier_files()),
                         ids=lambda v: v.name if isinstance(v, pathlib.Path) else "")
def test_query_tier_file_does_not_mutate(path, text):
    hits = sorted({m.group(0).strip() for m in MUTATORS.finditer(text)})
    assert not hits, (
        f"{path.name} is in the read-only query tier but mutates the database "
        f"({', '.join(hits)}). Either make it read-only, or mark it "
        f"`pytest.mark.ingest_bench` so it runs in the ingest tier against its "
        f"own baseline."
    )
