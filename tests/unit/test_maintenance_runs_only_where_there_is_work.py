"""Maintenance is scheduled by NEED, never by elapsed time alone — issue 236.

Both gates were conjunctions: "skip if nothing to do AND done recently". Once
the staleness window passed, elapsed time alone made a space eligible, and the
score then ranked it by the very staleness that let it in. Measured on
production: three FIXTURE spaces with zero pending modifications and zero dead
tuples had absorbed 32,115 ANALYZEs and 13,696 VACUUMs, `prod_kg_term` —
insert-only, six lifetime deletes — had been vacuumed 9,543 times for 26.9
hours, and `prod_kg_rdf_quad` (24 GB) was ANALYZEd every ~25 minutes at
24.8s a pass with `n_mod_since_analyze = 0`.

TWO GATES, TESTED SEPARATELY
----------------------------
The pick is per SPACE; the work is per TABLE. Fixing only the first leaves the
production case unfixed — a space with real churn is correctly picked, and then
still processes all seven of its tables, so 10,000 modifications in a 40-row
`_datatype` still drags a 24 GB `_rdf_quad` through a pass. Both halves are
asserted here, and the second is the one that matters at scale.

WHAT MUST NOT REGRESS
---------------------
Staleness still ORDERS the queue and a never-touched table is still eligible —
those are the two things the original conjunction was protecting, and the easy
way to fix the defect is to break them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vitalgraph.process.maintenance_job import (
    ANALYZE_MOD_THRESHOLD,
    VACUUM_DEAD_THRESHOLD,
    MaintenanceJob,
)

pytestmark = [pytest.mark.unit]

NOW = datetime.now(timezone.utc)


def _job():
    return MaintenanceJob(pool=None)


def _space(*, mods=0, dead=0, analyzed_min_ago=None, vacuumed_min_ago=None):
    def ts(m):
        return None if m is None else NOW - timedelta(minutes=m)
    return {"n_mod_since_analyze": mods, "n_dead_tup": dead,
            "last_analyze": ts(analyzed_min_ago),
            "last_vacuum": ts(vacuumed_min_ago)}


class TestStalenessAloneNoLongerSchedulesAnalyze:

    def test_an_idle_space_is_never_picked_however_stale(self):
        """The defect: zero mods, analyzed a week ago, was eligible."""
        job = _job()
        stats = {"idle": _space(mods=0, analyzed_min_ago=60 * 24 * 7)}
        assert job._pick_worst_for_analyze(stats) is None

    @pytest.mark.parametrize("minutes_ago", [11, 60, 60 * 24, 60 * 24 * 30])
    def test_no_amount_of_staleness_makes_an_unchanged_space_eligible(self, minutes_ago):
        job = _job()
        stats = {"idle": _space(mods=0, analyzed_min_ago=minutes_ago)}
        assert job._pick_worst_for_analyze(stats) is None

    def test_below_threshold_is_not_enough_either(self):
        """The production reading: 4,270 mods against a 10,000 threshold."""
        job = _job()
        stats = {"churny": _space(mods=ANALYZE_MOD_THRESHOLD - 1,
                                  analyzed_min_ago=60 * 24)}
        assert job._pick_worst_for_analyze(stats) is None

    def test_real_need_is_picked(self):
        job = _job()
        stats = {"busy": _space(mods=ANALYZE_MOD_THRESHOLD, analyzed_min_ago=1)}
        assert job._pick_worst_for_analyze(stats) == "busy"

    def test_a_never_analyzed_space_is_still_eligible(self):
        """`last_analyze is None` must survive the fix — a fresh space needs its
        first pass, and it has no mods to prove it with."""
        job = _job()
        stats = {"fresh": _space(mods=0, analyzed_min_ago=None)}
        assert job._pick_worst_for_analyze(stats) == "fresh"

    def test_staleness_still_orders_among_spaces_that_have_work(self):
        """Need makes you eligible; staleness breaks the tie. Same mods, older
        analyze wins."""
        job = _job()
        stats = {
            "recent": _space(mods=ANALYZE_MOD_THRESHOLD, analyzed_min_ago=5),
            "older": _space(mods=ANALYZE_MOD_THRESHOLD, analyzed_min_ago=600),
        }
        assert job._pick_worst_for_analyze(stats) == "older"

    def test_more_mods_outranks_more_staleness(self):
        job = _job()
        stats = {
            "stale": _space(mods=ANALYZE_MOD_THRESHOLD, analyzed_min_ago=600),
            "hot": _space(mods=ANALYZE_MOD_THRESHOLD * 100, analyzed_min_ago=5),
        }
        assert job._pick_worst_for_analyze(stats) == "hot"


class TestStalenessAloneNoLongerSchedulesVacuum:

    def test_an_insert_only_space_is_never_picked(self):
        """`prod_kg_term`: zero dead tuples, vacuumed 9,543 times."""
        job = _job()
        stats = {"insert_only": _space(dead=0, vacuumed_min_ago=60 * 24)}
        assert job._pick_worst_for_vacuum(stats) is None

    def test_below_threshold_is_not_enough(self):
        job = _job()
        stats = {"some_dead": _space(dead=VACUUM_DEAD_THRESHOLD - 1,
                                     vacuumed_min_ago=60 * 24)}
        assert job._pick_worst_for_vacuum(stats) is None

    def test_real_garbage_is_picked(self):
        job = _job()
        stats = {"dirty": _space(dead=VACUUM_DEAD_THRESHOLD, vacuumed_min_ago=1)}
        assert job._pick_worst_for_vacuum(stats) == "dirty"

    def test_a_never_vacuumed_space_is_still_eligible(self):
        job = _job()
        stats = {"fresh": _space(dead=0, vacuumed_min_ago=None)}
        assert job._pick_worst_for_vacuum(stats) == "fresh"


class TestTheOldRuleWouldHaveScheduledThese:
    """The gates above have teeth only if the old rule fails them.

    The pre-`issues/236` conjunction, kept verbatim as an oracle. Both forms
    agree on a space that genuinely has work — which is why nothing noticed the
    defect — and disagree on exactly the cases production was paying for.
    """

    @staticmethod
    def _old_would_pick(mods, threshold, minutes_since, staleness_minutes):
        """`if mods < THRESHOLD and minutes_since < STALENESS: continue`"""
        return not (mods < threshold and minutes_since < staleness_minutes)

    def test_the_old_rule_scheduled_an_idle_space(self):
        # zero mods, analyzed a week ago, 10-minute staleness window
        assert self._old_would_pick(0, ANALYZE_MOD_THRESHOLD, 60 * 24 * 7, 10)

    def test_the_old_rule_scheduled_a_below_threshold_space(self):
        # the production reading: 4,270 mods, analyzed 25 minutes ago
        assert self._old_would_pick(4_270, ANALYZE_MOD_THRESHOLD, 25, 10)

    def test_the_old_rule_scheduled_an_insert_only_space(self):
        # zero dead tuples, vacuumed an hour ago, 30-minute window
        assert self._old_would_pick(0, VACUUM_DEAD_THRESHOLD, 60, 30)

    def test_both_rules_agree_when_there_is_real_work(self):
        """The reason this shipped: on a space that has work, the two forms are
        indistinguishable."""
        job = _job()
        stats = {"busy": _space(mods=ANALYZE_MOD_THRESHOLD * 3, analyzed_min_ago=90)}
        assert job._pick_worst_for_analyze(stats) == "busy"
        assert self._old_would_pick(ANALYZE_MOD_THRESHOLD * 3,
                                    ANALYZE_MOD_THRESHOLD, 90, 10)


def _row(name, *, mods=0, dead=0, ever_analyzed=True, ever_vacuumed=True):
    return {"relname": name, "n_mod_since_analyze": mods, "n_dead_tup": dead,
            "ever_analyzed": ever_analyzed, "ever_vacuumed": ever_vacuumed}


class TestThePerTableGate:
    """The half that fixes the production case: a picked space still must not
    process tables with nothing to do."""

    @pytest.fixture
    def job(self, monkeypatch):
        j = _job()
        self.rows = []
        monkeypatch.setattr(j, "_pg_config", None)

        async def _fetch(tables):
            return [r for r in self.rows if r["relname"] in tables]
        monkeypatch.setattr(j, "_async_fetch_table_need", _fetch)
        return j

    async def test_the_big_table_is_skipped_when_it_has_not_changed(self, job):
        """The production case exactly: churn in `_datatype`, nothing in
        `_rdf_quad`, and the 24 GB table was being analyzed anyway."""
        self.rows = [
            _row("sp_rdf_quad", mods=0),
            _row("sp_term", mods=0),
            _row("sp_datatype", mods=ANALYZE_MOD_THRESHOLD * 2),
            _row("sp_rdf_pred_stats"), _row("sp_rdf_stats"),
            _row("sp_edge"), _row("sp_frame_slot"),
        ]
        needed = await job._tables_needing("ANALYZE", "sp")
        assert needed == ["sp_datatype"]
        assert "sp_rdf_quad" not in needed

    async def test_a_table_over_threshold_is_kept(self, job):
        self.rows = [_row(t, mods=ANALYZE_MOD_THRESHOLD)
                     for t in job._space_tables("sp")]
        assert set(await job._tables_needing("ANALYZE", "sp")) == \
            set(job._space_tables("sp"))

    async def test_a_never_analyzed_table_is_kept(self, job):
        self.rows = [_row(t, mods=0) for t in job._space_tables("sp")]
        self.rows[3]["ever_analyzed"] = False
        needed = await job._tables_needing("ANALYZE", "sp")
        assert needed == [job._space_tables("sp")[3]]

    async def test_vacuum_gates_on_dead_tuples_not_mods(self, job):
        """A table with modifications but no garbage needs ANALYZE, not VACUUM."""
        self.rows = [_row(t, mods=ANALYZE_MOD_THRESHOLD * 5, dead=0)
                     for t in job._space_tables("sp")]
        assert await job._tables_needing("VACUUM", "sp") == []
        assert await job._tables_needing("ANALYZE", "sp") != []

    async def test_a_table_missing_from_pg_stat_is_kept(self, job):
        """Absence of information is not evidence of freshness — skipping on a
        missing row is how a gap becomes permanent."""
        self.rows = [_row(t, mods=0) for t in job._space_tables("sp")][:-1]
        assert await job._tables_needing("ANALYZE", "sp") == \
            [job._space_tables("sp")[-1]]

    async def test_a_failing_probe_falls_back_to_every_table(self, job, monkeypatch):
        """The gate must not be able to stop maintenance by breaking."""
        async def _boom(tables):
            raise RuntimeError("catalog unavailable")
        monkeypatch.setattr(job, "_async_fetch_table_need", _boom)
        assert await job._tables_needing("ANALYZE", "sp") == job._space_tables("sp")


class TestARunWithNothingToDoDoesNothing:

    @pytest.fixture
    def job(self, monkeypatch):
        j = _job()
        self.ran = []

        async def _none(command, space_id):
            return []
        monkeypatch.setattr(j, "_tables_needing", _none)

        async def _record(command, tables):
            self.ran.append((command, tables))
            return len(tables)
        monkeypatch.setattr(j, "_async_run_tables", _record)
        monkeypatch.setattr(j, "_pg_config", None)
        return j

    async def test_analyze_issues_no_statement(self, job):
        result = await job._run_analyze("sp")
        assert self.ran == []
        assert result["tables_analyzed"] == 0
        assert result["skipped"]

    async def test_vacuum_issues_no_statement(self, job):
        result = await job._run_vacuum("sp")
        assert self.ran == []
        assert result["tables_vacuumed"] == 0
        assert result["skipped"]
