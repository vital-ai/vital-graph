"""Why a pass did NOT fire — recorded as data rather than dropped in a log line.

Step 3 of `planning_performance/query_planner/rule_layer_case.md`, and the only
part of that document being built now. It does not add a rule engine. It takes
the decision points the pipeline already has and makes two things about each one
first-class: **the reason it declined**, and **which earlier stage's output that
reason was read from**.

WHY THIS AND NOT A RULE ENGINE

The rule layer case argues for declared rules with structured preconditions, and
gates the larger steps on "must find something the imperative version cannot".
This piece needs no such gate: every wrong turn in this area so far has been a
pass that declined correctly-but-quietly, and the cost was always diagnosis
time, never a wrong answer. Four from the traversal work alone:

  * `frame_entity` type absorption declined because a removed alias was still
    referenced by a constraint the remap left untouched. Right answers, no
    speed-up, no symptom — roughly an hour to find, and only by reading the
    emitted SQL.
  * `dedup_feasible` declined every FILTERED traversal because it consulted
    `text_needed`, computed at stage 2c, about a filter that stage 3's push-down
    would remove. 1-3 s on a hub start where the deduplicated form is ~100 ms.
  * The criterion gate's justifying measurement did not reproduce, was believed
    reversed for part of a day, and turned out to have been re-measured on a
    contended machine. The gate was right; nothing recorded what it was right
    ABOUT.
  * `text_needed` again: the shape decision at 2d.2 reads range stats loaded at
    2d.1, and when it was placed earlier every query reported "selectivity
    unknown" and the gate never saw a number.

Three of those four are the same bug: **a precondition read a fact that did not
exist yet.** That class is mechanically detectable if a rule says what it reads,
which is why `reads` is not decoration here — it is the point.

THE TWO DECLARATIONS

A `Rule` is declared once per module, next to the pass it belongs to::

    DEDUP = Rule("dedup_chain", stage="emit_bgp",
                 reads=("collect", "traversal_decision", "push_filters"))

`stage` is when the rule runs; `reads` is which stages' output its preconditions
consult. Both are names from `STAGES`, which is this pipeline's actual order.
A rule that reads a stage at or after its own is a stage-ordering bug and
`Rule.__init__` raises — at import, so any test run catches it, and no query has
to be slow first.

At the decline site::

    return DEDUP.decline("no DISTINCT above the traversal, so path "
                         "multiplicity is part of the answer",
                         above=[n.kind for n in above])

`decline()` returns None, so the many sites that already `return None` gain
nothing to get wrong. Keyword arguments are FACTS — the values the precondition
actually read. A reason without them ("projection is not confined to what
survives") says a rule fired; with them (`projected=['e3','score']`,
`allowed=['e3','e0']`) it says which variable to look at.

RECORDING IS FREE, AND SILENT WHEN NOBODY IS COLLECTING

`decline()` outside a `collecting()` block appends nothing and raises nothing,
so a pass stays unit-testable in isolation with no fixture. Inside one, every
decline in the task lands in one ordered log. The collector is a `ContextVar`
rather than a threaded parameter on purpose: this had to reach ~30 call sites
across four modules, several of them deep inside helpers, and a mechanism that
costs a signature change per site is a mechanism that gets skipped at the site
that later matters. `ContextVar` is per-task under asyncio, so concurrent
queries do not see each other's declines.

A CONSTRAINT THIS DOES NOT ENFORCE, AND SHOULD BE READ AS A RULE ANYWAY

Splitting a precondition from the transform it guards makes it EASIER for the
two to disagree about a fact, not harder. `dedup_feasible` once computed
"surviving variables" as everything the last hop binds, while `emit_dedup_chain`
projected exactly two of them; the mismatch returned 0 rows where 16 were
expected, on 46 of 120 cases. So: **a precondition must derive its facts from
the same function the transform uses, and hand them over** — as
`dedup_feasible` now returns the surviving set that its caller applies — rather
than re-deriving them in parallel. Nothing here checks that. It is the failure
mode this module makes more likely, and it is worth naming where it will be
read.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The pipeline's stage order
# ---------------------------------------------------------------------------

# Mirrors `generator.generate_sql` in the order the stages run there, with the
# emit-time steps that can be read FROM appended. Only relative order matters —
# the names exist so a precondition can say what it depends on and be checked.
#
# `emit` is where the tree walk begins; `push_filters` runs inside it, from
# `emit_filter` on the way down to a BGP; `emit_bgp` is that BGP. The three are
# separate entries because the one ordering bug this has to catch lives exactly
# between them: a traversal precondition asking about filters BEFORE push-down
# has removed them.
STAGES: Tuple[str, ...] = (
    "collect",                # Stage 1
    "materialize_constants",  # Stage 2
    "prune_union",            # Stage 2 post
    "pred_stats",             # Stage 2a
    "edge_rewrite",           # Stage 2a.1
    "frame_entity_rewrite",   # Stage 2a.2
    "exists_subplans",        # Stage 2a.3
    "edge_fanout",            # Stage 2a.4
    "datatype_cache",         # Stage 2b
    "text_needed",            # Stage 2c
    "vg_optimize",            # Stage 2d
    "semijoin",               # Stage 2d.1  (loads the range/text/in stats)
    "traversal_decision",     # Stage 2d.2
    "index_metadata",         # Stage 2e
    "emit",                   # Stage 3
    "push_filters",           # Stage 3, inside emit, above each BGP
    "emit_bgp",               # Stage 3, the BGP itself
)

_STAGE_INDEX: Dict[str, int] = {s: i for i, s in enumerate(STAGES)}


class StageOrderError(ValueError):
    """A rule declared it reads a stage that has not run when the rule runs."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Decline:
    """One pass, one refusal, and the values it refused on."""

    rule: str
    stage: str
    detail: str
    facts: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.facts:
            return f"{self.rule} declined: {self.detail}"
        shown = ", ".join(f"{k}={v!r}" for k, v in sorted(self.facts.items()))
        return f"{self.rule} declined: {self.detail} [{shown}]"


class DeclineLog:
    """Every decline recorded while generating one query, in order."""

    __slots__ = ("entries",)

    def __init__(self) -> None:
        self.entries: List[Decline] = []

    def __iter__(self) -> Iterator[Decline]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def for_rule(self, rule: str) -> List[Decline]:
        return [d for d in self.entries if d.rule == rule]

    def by_rule(self) -> Dict[str, List[Decline]]:
        out: Dict[str, List[Decline]] = {}
        for d in self.entries:
            out.setdefault(d.rule, []).append(d)
        return out

    def summary(self) -> str:
        """One line per decline — what to paste next to a slow query."""
        if not self.entries:
            return "no declines"
        return "\n".join(f"  {d}" for d in self.entries)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

_REGISTRY: List["Rule"] = []


class Rule:
    """A named decision point, declaring when it runs and what it reads.

    Constructed at module scope so the declarations sit together and are
    visible without reading the pass. Registration is a side effect of
    construction, which is what lets `all_rules()` check the whole set.
    """

    __slots__ = ("name", "stage", "reads")

    def __init__(self, name: str, stage: str, reads: Tuple[str, ...] = ()):
        if stage not in _STAGE_INDEX:
            raise ValueError(
                f"rule {name!r}: stage {stage!r} is not a pipeline stage. "
                f"Known: {', '.join(STAGES)}")
        here = _STAGE_INDEX[stage]
        for r in reads:
            if r not in _STAGE_INDEX:
                raise ValueError(
                    f"rule {name!r}: reads {r!r}, which is not a pipeline "
                    f"stage. Known: {', '.join(STAGES)}")
            if _STAGE_INDEX[r] >= here:
                raise StageOrderError(
                    f"rule {name!r} runs at {stage!r} but reads {r!r}, which "
                    f"runs at or after it. The precondition would consult a "
                    f"fact that does not exist yet — move the rule later or "
                    f"stop reading {r!r}.")
        self.name = name
        self.stage = stage
        self.reads = tuple(reads)
        _REGISTRY.append(self)

    def __repr__(self) -> str:
        return f"Rule({self.name!r}, stage={self.stage!r}, reads={self.reads!r})"

    def decline(self, detail: str, **facts: Any) -> None:
        """Record a refusal. Always returns None, so `return R.decline(...)` reads.

        Keyword arguments are the values the precondition read. `rule`,
        `stage`, `detail` and `reads` are reserved and must not be used as
        fact names.
        """
        entry = Decline(rule=self.name, stage=self.stage, detail=detail,
                        facts=dict(facts))
        entries = _active.get()
        if entries is not None:
            entries.append(entry)
        logger.debug("%s", entry)
        return None


def all_rules() -> Tuple["Rule", ...]:
    """Every rule declared by any imported module.

    Only complete once the modules that declare rules have been imported, which
    is why the test that walks this imports them explicitly rather than
    trusting whatever the run happened to touch.
    """
    return tuple(_REGISTRY)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

_active: ContextVar[Optional[List[Decline]]] = ContextVar(
    "vg_sparql_declines", default=None)


@contextmanager
def collecting() -> Iterator[DeclineLog]:
    """Collect declines recorded in this task until the block exits.

    Nests: an inner block collects its own declines and the outer one does not
    see them. That matters for `prepare_exists_subplans`, which generates a
    plan inside a plan — an EXISTS body's declines belong to the body.
    """
    log = DeclineLog()
    token = _active.set(log.entries)
    try:
        yield log
    finally:
        _active.reset(token)


def active() -> bool:
    """Whether anything is collecting. For tests; passes should not branch on it."""
    return _active.get() is not None
