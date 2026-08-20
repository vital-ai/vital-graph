"""Spaces that intentionally have per-space tables and NO row in `space`.

`scripts/cleanup_orphan_space_tables.py` treats "a full set of per-space tables
with no `space` row" as debris, and drops it when it holds no quads. That test is
right for the residue it was written for — half-created `inttest_*` spaces — and
wrong for a fixture that never goes through `SpaceManager` on purpose.

**This is not hypothetical.** `dawg_test` is the conformance suite's own space,
created by `dawg_space_manager.create_space` from the canonical DDL, and the
runners TRUNCATE and reload it per case — so between runs it holds zero quads and
has no registry row. It matches the sweep's drop condition exactly. Running the
sweep with `--apply` on the test stack would have deleted it.

WHY DECLARE RATHER THAN REGISTER

Giving it a `space` row would make it visible to every space-listing endpoint and
to the maintenance, analytics and metrics jobs — churn on a space rebuilt
hundreds of times in a single suite run, which is the opposite of scoping
analysis to spaces anyone manages. The registry answers "which spaces does this
deployment serve", and the honest answer for a conformance scratch space is: none
of them.

The cost of NOT declaring it is that every reconciliation of tables against the
registry reports a permanent false positive. A check with a standing false
positive is one people learn to wave through, which is how the real orphan gets
waved through too.

WHY HERE. `devtools/` is outside the shipped wheel and is what the ops scripts
already import for their target resolution, so the sweep can read it. Production
does not need it: `MaintenanceJob._only_registered` already ignores anything
without a registry row, which is the behaviour these spaces want anyway. Only the
DESTRUCTIVE path needs to know the difference between "unmanaged" and "debris".

Adding to this list is a claim that something creates the tables deliberately and
will recreate them. Anything else belongs in the sweep.
"""

from __future__ import annotations

from typing import Dict

# space_id -> why it has no registry row, and what recreates it.
UNREGISTERED_BY_DESIGN: Dict[str, str] = {
    "dawg_test":
        "the W3C conformance suite's scratch space. Created by "
        "vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_space_manager.create_space "
        "from the canonical DDL, then TRUNCATED and reloaded per test case, so it "
        "legitimately holds zero quads between runs. Deliberately outside the "
        "space registry: it bypasses the space/graph API (it has no rows in "
        "`graph` at all) and registering it would put a space rebuilt hundreds of "
        "times per run in front of every listing endpoint and background job.",
}


def is_unregistered_by_design(space_id: str) -> bool:
    return space_id in UNREGISTERED_BY_DESIGN


def reason(space_id: str) -> str:
    return UNREGISTERED_BY_DESIGN.get(space_id, "")
