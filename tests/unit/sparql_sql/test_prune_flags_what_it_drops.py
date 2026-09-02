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


def test_the_keep_set_is_not_truncated_below_the_cap():
    """`issues/147`. The prune used to apply `rn <= per_predicate_n` on top of
    `ORDER BY rn ASC ... LIMIT keep_top_n`. The ORDER BY already delivers
    round-robin fairness cut at exactly the depth that fits; the extra WHERE
    truncated long before the cap was reached.

    Measured on production, same table and cap: 8,854 rows kept against 50,000
    slots, and because the ordering is `row_count ASC` the 41,146 it discarded
    were the LARGEST pairs — the ones the semi-join gate most needs. `issues/141`
    then detected the damage and rebuilt, and the next prune undid it, on a
    ~10 minute loop.
    """
    src = inspect.getsource(S.prune_stats_tables)
    keep = src[src.index("CREATE TEMP TABLE _keep_stats"):]
    keep = keep[:keep.index("STATS_MIN_ROW_COUNT")]

    assert "rn <= " not in keep, (
        "a fixed per-predicate cut truncates the keep set below the cap")
    assert "ORDER BY r.rn ASC" in keep, (
        "rn-ordering IS the fairness mechanism — without it LIMIT would take "
        "every row of one predicate before reaching the next")
    assert "LIMIT $3" in keep, "the cap must be what cuts, and nothing else"


def test_the_prune_still_flags_every_predicate_it_prunes():
    """The anti-join is the thing under suspicion; pin its shape so a rewrite
    has to be deliberate."""
    src = inspect.getsource(S.prune_stats_tables)
    assert "SET pruned = TRUE WHERE predicate_uuid = ANY($1)" in src
    assert "WHERE k.predicate_uuid IS NULL" in src, (
        "the anti-join finds rows present in rdf_stats and absent from the "
        "keep set — those are exactly the drops")
