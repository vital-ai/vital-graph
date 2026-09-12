"""The perf runner class must come from the DATABASE, not from a flag.

`issues/189`. `runner.class` is what `perf_compare` uses to decide whether two
runs are comparable at all, and it was the one field taken on trust from an
environment variable. The committed `baselines/query.json` is stamped
`vg-test-docker-clean` while its own `stats` block records 126,128,097 live
tuples across 260 fixture tables — a clean container mounts no volume and holds
none of that — and twelve of its cells read spaces that exist only on a seeded
stack. Both facts were in the same file and nothing compared them.

The rule these pin: the database decides, the flags are recorded beside it, and
a DISAGREEMENT BLOCKS PROMOTION. Preferring either side silently is the failure
— a run that cannot say which environment it measured is not a baseline,
whichever way the mismatch points.
"""

from __future__ import annotations

from tests.performance.perf_record import (
    reconcile_runner, shared_buffers_bytes)

_CLEAN_FLAGS = {"class": "vg-test-docker-clean", "persist": False,
                "seeded": False, "pg_port": "5433"}

# Seeded is proved by the SEED-ONLY spaces holding bytes, not by a row estimate.
_SEEDED_SIZES = {"space_bytes": {"wordnet_frames": 5962 * 1024 ** 2},
                 "largest_gated_fixture": "wordnet_frames",
                 "largest_gated_fixture_bytes": 5962 * 1024 ** 2}
_EMPTY_SIZES = {"space_bytes": {}}


def test_the_committed_baselines_exact_case_is_caught():
    """The stamp that motivated this: flags say clean, database says 126M rows."""
    out = reconcile_runner(
        _CLEAN_FLAGS,
        {"fixture_tables": 260, "fixture_live_tuples": 126128097},
        _SEEDED_SIZES, None)
    assert out["class"] == "vg-test-docker-persist", (
        "the class must follow the database, not the flag")
    assert out["persist"] is True and out["seeded"] is True
    assert "promotion_blocked" in out, (
        "and a run that disagrees with itself must not be promotable")


def test_a_genuinely_clean_run_is_still_clean():
    out = reconcile_runner(
        _CLEAN_FLAGS, {"fixture_tables": 0, "fixture_live_tuples": 0},
        _EMPTY_SIZES, None)
    assert out["class"] == "vg-test-docker-clean"
    assert "promotion_blocked" not in out, "no disagreement, nothing to block"


def test_flags_claiming_persist_on_an_empty_database_also_disagree():
    """The mismatch is refused in BOTH directions. A run flagged persist that
    measured an empty stack is equally unable to say what it measured."""
    out = reconcile_runner(
        {**_CLEAN_FLAGS, "persist": True, "seeded": True},
        {"fixture_tables": 0, "fixture_live_tuples": 0}, _EMPTY_SIZES, None)
    assert out["class"] == "vg-test-docker-clean"
    assert "promotion_blocked" in out


def test_the_flags_are_kept_for_the_record():
    """Recorded, not discarded — the disagreement is the evidence."""
    out = reconcile_runner(
        _CLEAN_FLAGS, {"fixture_tables": 260, "fixture_live_tuples": 1},
        _SEEDED_SIZES, None)
    assert out["flags"] == {"persist": False, "seeded": False}
    assert out["observed"]["fixture_tables"] == 260


def test_host_pg_is_not_mislabelled_as_the_docker_stack():
    out = reconcile_runner(
        {"pg_port": "5432", "persist": False, "seeded": False},
        {"fixture_tables": 12, "fixture_live_tuples": 5}, _SEEDED_SIZES, None)
    assert out["class"] == "host-pg-persist"


# --- the residency property, asserted rather than inherited ----------------

def test_the_largest_gated_fixture_is_compared_to_shared_buffers():
    out = reconcile_runner(
        _CLEAN_FLAGS, {"fixture_tables": 1, "fixture_live_tuples": 1},
        {"space_bytes": {"wordnet_frames": 1},
         "largest_gated_fixture": "sp_lead_synth_100k",
         "largest_gated_fixture_bytes": 35 * 1024 ** 3},
        16 * 1024 ** 3)
    assert out["exceeds_shared_buffers"] is True
    assert out["largest_gated_fixture"] == "sp_lead_synth_100k"


def test_an_all_resident_suite_is_recorded_as_such():
    """If every gated fixture fits in memory the suite measures only in-memory
    plans. True of all but one space, and true by accident — so it is recorded
    rather than assumed."""
    out = reconcile_runner(
        _CLEAN_FLAGS, {"fixture_tables": 1, "fixture_live_tuples": 1},
        _SEEDED_SIZES, 16 * 1024 ** 3)
    assert out["exceeds_shared_buffers"] is False


# --- shared_buffers parsing -------------------------------------------------

def test_shared_buffers_in_blocks():
    """`current_setting('shared_buffers')` returns 8 kB BLOCKS by default, which
    is why a naive int() read 16GB as 2,097,152 bytes."""
    assert shared_buffers_bytes({"shared_buffers": "2097152"}) == 16 * 1024 ** 3


def test_shared_buffers_with_a_unit():
    assert shared_buffers_bytes({"shared_buffers": "16GB"}) == 16 * 1024 ** 3
    assert shared_buffers_bytes({"shared_buffers": "1024MB"}) == 1024 * 1024 ** 2


def test_shared_buffers_absent_or_junk_is_None():
    assert shared_buffers_bytes({}) is None
    assert shared_buffers_bytes({"shared_buffers": "lots"}) is None


# --- the comparison refuses in ONE line -------------------------------------

def _run(cls, *, blocked=None, benches=("a", "b", "c")):
    r = {"class": cls}
    if blocked:
        r["promotion_blocked"] = blocked
    return {"env": {"runner": r, "pg": {"server_version": "18.4"}, "git": {}},
            "benches": [{"bench_id": b, "status": "ok",
                         "metrics": {"exec_ms": 1.0}} for b in benches]}


def _report(run, base):
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "perf_compare",
        pathlib.Path(__file__).resolve().parents[2] / "scripts" / "perf_compare.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.report(run, base, {})


def test_a_class_mismatch_is_ONE_finding_not_one_per_bench():
    """103 restatements of one problem make the real signal unreadable."""
    code, findings = _report(_run("vg-test-docker-clean"),
                             _run("vg-test-docker-persist"))
    refusals = [f for f in findings if "COMPARISON REFUSED" in f["detail"]]
    assert len(refusals) == 1, findings
    assert not [f for f in findings if f["bench"] in ("a", "b", "c")], (
        "no per-bench findings may be emitted for an incomparable pair")
    assert code == 1


def test_an_unpromotable_baseline_is_refused_even_at_the_same_class():
    """The committed baselines are stamped clean and hold 126M rows. Same class
    on both sides would otherwise read as comparable."""
    code, findings = _report(
        _run("vg-test-docker-clean"),
        _run("vg-test-docker-clean", blocked="flags disagree with the database"))
    assert [f for f in findings if "COMPARISON REFUSED" in f["detail"]]
    assert code == 1


def test_a_matching_environment_still_compares_normally():
    """Guard the guard: an over-eager refusal would disable the whole suite."""
    code, findings = _report(_run("vg-test-docker-persist"),
                             _run("vg-test-docker-persist"))
    assert not [f for f in findings if "COMPARISON REFUSED" in f["detail"]]


def test_a_never_analyzed_seeded_stack_is_NOT_read_as_clean():
    """THE DEFECT THE LIVE STACK EXPOSED.

    `n_live_tup` is a statistics estimate and reads 0 for a table that has never
    been ANALYZEd. On the real 105 GB seeded stack, 286 fixture tables are in
    exactly that state — so a detector keyed on row counts called it CLEAN,
    reproducing the bug it was written to fix. Bytes need no statistics.
    """
    out = reconcile_runner(
        _CLEAN_FLAGS,
        {"fixture_tables": 286, "fixture_live_tuples": 0},   # never ANALYZEd
        {"space_bytes": {"lead_nurture_grouped": 45 * 1024 ** 3}}, None)
    assert out["class"] == "vg-test-docker-persist", (
        "seeded must be proved by bytes, not by a row estimate that ANALYZE "
        "has not populated")
    assert out["observed"]["seed_space_bytes"] > 0


def test_a_clean_run_creating_its_own_fixtures_is_still_clean():
    """Fixture TABLES prove nothing — a clean run creates them as it goes. Only
    the seed-only spaces holding data prove the volume persisted."""
    out = reconcile_runner(
        _CLEAN_FLAGS,
        {"fixture_tables": 40, "fixture_live_tuples": 1000},
        {"space_bytes": {"sp_graph_skew_2k": 300 * 1024 ** 2}}, None)
    assert out["class"] == "vg-test-docker-clean"
