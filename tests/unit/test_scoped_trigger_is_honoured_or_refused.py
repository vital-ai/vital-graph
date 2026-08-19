"""A scoped trigger must be honoured or refused — never silently widened.

`issues/109`. `ProcessScheduler.trigger_now` honours `space_id` by looking for
`trigger_<process_type>` on the handler, and FELL THROUGH to `run()` — the full
sweep — when there was none. The response was `triggered: true` either way, so
nothing distinguished "I did what you asked" from "I ignored your parameter and
did far more". Measured on a stack with 17 spaces:

    maintenance + space_id    109 s   ->  0.8 s once trigger_maintenance existed
    analytics   + space_id    227 s   ->  0.23 s once trigger_analytics existed

Both were found by asking the API, not by reading the code, and only because a
test timed out. The fallback is silent BY CONSTRUCTION, so the next job to gain a
process type inherits it — which is why the fix is here rather than in the two
jobs.

Now: scoping is DECLARED at registration (`supports_scope`), and a scoped request
against a handler that cannot honour it is REFUSED. A missing method stays legal
— a job may have nothing per-space to do — but it is no longer discovered per
request and answered as though the request had been met.
"""

from __future__ import annotations

import pytest

from vitalgraph.process.process_scheduler import ProcessScheduler


class _Scoped:
    """A handler that can be scoped."""

    def __init__(self):
        self.calls = []

    async def run(self):
        self.calls.append(("run", None))
        return {"swept": "everything"}

    async def trigger_widgets(self, space_id):
        self.calls.append(("scoped", space_id))
        return {"space_id": space_id}


class _Unscoped:
    """A handler with no per-space entry point."""

    def __init__(self):
        self.calls = []

    async def run(self):
        self.calls.append(("run", None))
        return {"swept": "everything"}


def _scheduler():
    # No pool or config is touched by register_job.
    return ProcessScheduler(pool=None, postgresql_config={}, enabled=False)


class TestRegistrationDeclaresScoping:

    def test_a_scopable_handler_is_recorded_as_such(self):
        sch = _scheduler()
        sch.register_job(name="w", interval_seconds=1, handler=_Scoped(),
                         process_type="widgets")
        assert sch._jobs["w"].supports_scope is True

    def test_an_unscopable_handler_is_recorded_too(self):
        """Not an error — a job may have nothing per-space to do. The point is
        that it is KNOWN at registration rather than discovered per request."""
        sch = _scheduler()
        sch.register_job(name="w", interval_seconds=1, handler=_Unscoped(),
                         process_type="widgets")
        assert sch._jobs["w"].supports_scope is False

    def test_a_bare_callable_is_unscopable(self):
        """`register_job`'s own docstring shows `handler=job.run`, a bound
        method, which cannot expose `trigger_*`."""
        async def handler():
            return {}
        sch = _scheduler()
        sch.register_job(name="w", interval_seconds=1, handler=handler,
                         process_type="widgets")
        assert sch._jobs["w"].supports_scope is False


class TestTheThreeRefusalsAreDistinct:
    """Each says something different, and a caller acts on each differently."""

    def test_unknown_type_names_what_is_registered(self):
        assert issubclass(ProcessScheduler.UnknownProcessType, ValueError)

    def test_scoping_unsupported_is_its_own_error(self):
        assert issubclass(ProcessScheduler.ScopingUnsupported, ValueError)
        assert (ProcessScheduler.ScopingUnsupported
                is not ProcessScheduler.UnknownProcessType), (
            "a type that cannot be scoped is not an unknown type — conflating "
            "them is how the old 'Lock busy or no handler registered' message "
            "misled the diagnosis of its own defect")
