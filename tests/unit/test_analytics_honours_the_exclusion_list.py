"""AnalyticsJob must skip excluded spaces, like the three jobs beside it.

`issues/213`: `AnalyticsJob.run()` iterated every space. Three other jobs that
walk every space read `VG_MAINTENANCE_EXCLUDE_SPACES` —
`maintenance_job.py:545`, `resync_all.py:238`, and
`backfill_server_properties_task.py:153`, which falls back to it deliberately —
and this one did not. On dev that meant multi-GB benchmark fixtures nobody
queries were walked once a day, including a COUNT(DISTINCT predicate_uuid)
measured at 4.1 s on a 50.5M-quad space.

The contract copied from the backfill task is the part worth testing: an
explicit `ANALYTICS_EXCLUDE_SPACES` wins, and an explicit EMPTY value means
"compute everything" rather than falling back. Without that, a space cannot opt
this job back in without also opting maintenance back in.
"""

from __future__ import annotations

import pytest


class _Job:
    """The real run() against a stub `_list_spaces` and `_compute_and_store`."""

    def __init__(self, spaces):
        self._spaces = spaces
        self.computed = []

    async def _list_spaces(self):
        return list(self._spaces)

    async def _compute_and_store(self, space_id, graph_uri=None):
        self.computed.append(space_id)
        return {"space_id": space_id}


async def _run(monkeypatch, env, spaces):
    from vitalgraph.process.analytics_job import AnalyticsJob
    for k in ("ANALYTICS_EXCLUDE_SPACES", "VG_MAINTENANCE_EXCLUDE_SPACES"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    job = _Job(spaces)
    await AnalyticsJob.run(job)
    return job.computed


@pytest.mark.asyncio
async def test_it_falls_back_to_the_maintenance_list(monkeypatch):
    done = await _run(monkeypatch, {"VG_MAINTENANCE_EXCLUDE_SPACES": "big_fixture,other"},
                      ["real_space", "big_fixture", "other"])
    assert done == ["real_space"], (
        "a space excluded from maintenance must not be walked here either")


@pytest.mark.asyncio
async def test_an_explicit_empty_value_means_compute_everything(monkeypatch):
    """The contract the backfill task states, and the reason it is testable.

    Without this, a deployment could not re-enable analytics for a space
    without also re-enabling maintenance for it.
    """
    done = await _run(monkeypatch,
                      {"VG_MAINTENANCE_EXCLUDE_SPACES": "big_fixture",
                       "ANALYTICS_EXCLUDE_SPACES": ""},
                      ["real_space", "big_fixture"])
    assert done == ["real_space", "big_fixture"], (
        "an explicit empty ANALYTICS_EXCLUDE_SPACES must WIN over the "
        "maintenance list, not fall back to it")


@pytest.mark.asyncio
async def test_an_explicit_list_overrides_the_maintenance_one(monkeypatch):
    done = await _run(monkeypatch,
                      {"VG_MAINTENANCE_EXCLUDE_SPACES": "big_fixture",
                       "ANALYTICS_EXCLUDE_SPACES": "only_this"},
                      ["real_space", "big_fixture", "only_this"])
    assert done == ["real_space", "big_fixture"]


@pytest.mark.asyncio
async def test_no_setting_walks_everything(monkeypatch):
    done = await _run(monkeypatch, {}, ["a", "b"])
    assert done == ["a", "b"], "absence of a list must not exclude anything"
