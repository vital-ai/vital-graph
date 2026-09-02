"""Dropping a stats row without flagging the predicate re-creates the disease.

`issues/142` / `issues/062`. `pruned` is defined in the schema as "TRUE once
prune_stats_tables has removed any (predicate, object) row for this predicate",
and it is what makes ABSENCE from rdf_stats mean something. Without it, absence
is ambiguous between "no quads" and "pruned", and `sync_stats_after_insert`
resolves it the wrong way: it upserts `row_count + delta`, so a pruned pair
reappears holding only its post-prune delta. Measured at 100,000 -> 1 after a
single write, and it looks authoritative.

Caught live on prod, the same shape at a different scale:

    13:11  pruned=f  anchor=129     13:12  pruned=f  anchor=ABSENT  (drop)
                                    13:13  pruned=f  anchor=1       (write)

Two producers delete from rdf_stats. Both must flag. The maintenance job's
oversized-pair repair shipped doing only the delete -- its own comment says
"absence plus the flag is the intended state" and the code set no flag.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import inspect

from vitalgraph.db.sparql_sql import sync_stats_tables as S
from vitalgraph.process import maintenance_job as M


def test_the_oversized_repair_flags_what_it_deletes():
    """The delete without the flag IS issues/142's mechanism, not a cosmetic
    omission: it guarantees the next write re-creates a delta-only row."""
    src = inspect.getsource(M.MaintenanceJob)
    i = src.index("DELETE FROM {space_id}_rdf_stats")
    after = src[i:i + 1200]
    assert "SET pruned = TRUE" in after, (
        "the oversized repair deletes the pair but leaves pruned FALSE, so "
        "absence reads as ZERO and the next write stores a delta-only count")


def test_the_prune_reports_when_it_cannot_flag_what_it_dropped():
    """issues/142's mechanism is unresolved and inspection has already failed to
    settle it. The prune must therefore SAY when the invariant breaks, rather
    than leaving the next investigator to sample the table by hand."""
    src = inspect.getsource(S.prune_stats_tables)
    assert "flagged" in src and "dropped" in src, (
        "the prune must count both what it dropped and what it flagged")
    assert "logger.warning" in src, (
        "a mismatch between the two is the defect and must be a WARNING")
    assert "issues/142" in src


def test_the_prune_still_flags_every_predicate_it_prunes():
    """The anti-join is the thing under suspicion; pin its shape so a rewrite
    has to be deliberate."""
    src = inspect.getsource(S.prune_stats_tables)
    assert "SET pruned = TRUE WHERE predicate_uuid = ANY($1)" in src
    assert "WHERE k.predicate_uuid IS NULL" in src, (
        "the anti-join finds rows present in rdf_stats and absent from the "
        "keep set — those are exactly the drops")
