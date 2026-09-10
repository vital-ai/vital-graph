"""One structured record per query of which plan rewrites fired, and why not.

There are ~15 gated rewrites in the generator and ~20 modules that log a
decline, and until this existed **nothing recorded, per query, which of them
actually applied.** `ctx.trace` is an EMIT-time trace and is off by default; the
rewrites run before emit and report through module loggers, which interleave
across concurrent queries and are discarded at WARNING.

That gap is not hypothetical. In one session it produced, all of them silent:

  * a check whose 2,000 ms budget sat on its own 1,805 ms cost, so its verdict
    flipped run to run and the plan flipped with it, an order of magnitude apart
  * an agreement gate vacuously TRUE on an empty table, whose rewrite then
    returned zero rows on 8 integration tests
  * `semijoin.py` structurally unable to fire on a six-variable projection, so
    it had never applied to that query class at all
  * `rewrite_merge_bgp` declining TWICE on the query it was written for, while
    distribution above it fired and duplicated the pattern — all of the cost,
    none of the benefit (`issues/178`)

Every one was invisible until someone read the generated SQL. **"Wired" and
"firing" are different claims, and only a record settles which.**

Cost is a list of small tuples per query and one log line, so this is always on
rather than behind a flag — a diagnostic nobody enabled is what the situation
above already looked like.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Generation above this is reported at WARNING rather than INFO. Production
# does not run at INFO, and generation is a request-path cost that can dominate
# on its own — a gate whose verdict costs more than its own budget, or a cold
# cache — without the query itself being slow enough to notice.
SLOW_GENERATE_MS = float(os.environ.get("VG_SLOW_GENERATE_MS", "500"))


@dataclass
class Decision:
    name: str
    fired: bool
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    ms: Optional[float] = None


@dataclass
class PlanDecisions:
    """Per-query record. Attached to the AliasGenerator, which every rewrite has."""

    decisions: List[Decision] = field(default_factory=list)
    stages: Dict[str, float] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def fired(self, name: str, reason: str = "", **detail) -> None:
        self.decisions.append(Decision(name, True, reason, detail))

    def declined(self, name: str, reason: str, **detail) -> None:
        """A decline is the MORE useful half. `reason` should say what was
        missing, not merely that nothing happened — "no PROJECT below" is
        actionable, "declined" is not."""
        self.decisions.append(Decision(name, False, reason, detail))

    def timed(self, name: str, ms: float, fired: bool, reason: str = "",
              **detail) -> None:
        """For gates that cost a database round trip. A verdict whose COST
        approaches its own budget is the `slot_type_tautology` failure, and it
        is only visible when the duration is recorded next to the verdict."""
        self.decisions.append(Decision(name, fired, reason, detail, ms))

    @contextlib.contextmanager
    def stage(self, name: str):
        """Time a generation STAGE, not a decision.

        Generation is on the request path and can dominate: on the `issues/178`
        reference query it measured 2.6 s to produce SQL that executes in 39 ms.
        Attributing that needs the same treatment the plan got — per-stage
        numbers rather than a single total.
        """
        t0 = time.monotonic()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + (
                time.monotonic() - t0) * 1000

    # -- reporting ---------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        return {
            "fired": [d.name for d in self.decisions if d.fired],
            "declined": {d.name: d.reason
                         for d in self.decisions if not d.fired},
            "timings_ms": {d.name: round(d.ms, 1)
                           for d in self.decisions if d.ms is not None},
            "detail": {d.name: d.detail
                       for d in self.decisions if d.detail},
            "stage_ms": {k: round(v, 1) for k, v in sorted(
                self.stages.items(), key=lambda kv: -kv[1])},
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), default=str, sort_keys=True)

    def emit(self, space_id: str = "", extra: Optional[Dict] = None) -> None:
        """One line per query. INFO, because the whole point is that it is on."""
        payload = self.as_dict()
        payload["space"] = space_id
        generate_ms = round((time.monotonic() - self.started) * 1000, 1)
        payload["generate_ms"] = generate_ms
        if extra:
            payload.update(extra)
        line = json.dumps(payload, default=str, sort_keys=True)
        # WARNING when generation itself was expensive, so the stage and gate
        # breakdown survives a production log level that drops INFO.
        if generate_ms >= SLOW_GENERATE_MS:
            logger.warning("slow_generate %s", line)
        else:
            logger.info("plan_decisions %s", line)


def recorder_for(aliases) -> PlanDecisions:
    """The recorder on `aliases`, creating it if absent.

    Threaded through the AliasGenerator rather than passed to every rewrite:
    the rewrites already take `aliases`, so this needs no signature changes and
    a rewrite that has not been instrumented yet simply records nothing.
    """
    rec = getattr(aliases, "plan_decisions", None)
    if rec is None:
        rec = PlanDecisions()
        try:
            aliases.plan_decisions = rec
        except Exception:
            # A caller passed something that is not an AliasGenerator; the
            # record is still returned so the call site stays uniform.
            pass
    return rec
