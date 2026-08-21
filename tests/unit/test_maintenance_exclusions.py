"""The maintenance job honours VG_MAINTENANCE_EXCLUDE_SPACES.

issues/112 option 3. A maintenance cycle re-ANALYZEd the benchmark fixtures
mid-session and a bench then read +91% worse with identical code, because the
plan flipped on refreshed statistics. Excluding the fixtures keeps the ground
still.

Configured, not hardcoded: the fixture names belong to a dev machine rather
than to the product, and the exclusion is a real divergence from production —
the maintenance job is part of how a served space behaves — so a deployment
opts in visibly instead of inheriting a default that makes benchmarks unlike
production everywhere.
"""

from __future__ import annotations

import pytest

from vitalgraph.process.maintenance_job import MaintenanceJob

pytestmark = [pytest.mark.unit]

STATS = {"sp_lead_synth_100k": {"n": 1}, "wordnet_frames": {"n": 2},
         "sp_customer_live": {"n": 3}}


def _job(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("VG_MAINTENANCE_EXCLUDE_SPACES", raising=False)
    else:
        monkeypatch.setenv("VG_MAINTENANCE_EXCLUDE_SPACES", value)
    return MaintenanceJob(pool=None)


def test_unset_maintains_everything(monkeypatch):
    """The default must not change production behaviour."""
    job = _job(monkeypatch, None)
    assert job._excluded == set()
    assert job._drop_excluded(dict(STATS)) == STATS


def test_empty_string_is_not_a_space_named_empty(monkeypatch):
    job = _job(monkeypatch, "")
    assert job._excluded == set()
    assert job._drop_excluded(dict(STATS)) == STATS


def test_named_spaces_are_dropped(monkeypatch):
    job = _job(monkeypatch, "sp_lead_synth_100k,wordnet_frames")
    kept = job._drop_excluded(dict(STATS))
    assert set(kept) == {"sp_customer_live"}, kept


def test_whitespace_and_trailing_commas_are_tolerated(monkeypatch):
    """A hand-edited env var should not silently fail to match."""
    job = _job(monkeypatch, " sp_lead_synth_100k , wordnet_frames ,, ")
    assert job._excluded == {"sp_lead_synth_100k", "wordnet_frames"}
    assert set(job._drop_excluded(dict(STATS))) == {"sp_customer_live"}


def test_an_exempt_space_that_is_not_present_is_harmless(monkeypatch):
    job = _job(monkeypatch, "sp_does_not_exist")
    assert job._drop_excluded(dict(STATS)) == STATS
