#!/usr/bin/env python
"""Generate a scaled literal-slot fixture by cloning the lead entity graphs.

Step 1 of planning/planning_performance/kgquery_o_page_paging_generator_plan.md.
`wordnet_frames` cannot exercise the range-comparator work (W2/W4) because every
slot in it is a `KGEntitySlot` — there is not a single literal-valued slot in the
space. `internal_data/lead_test_data` has exactly the right shape (nine literal
slot-value predicates) but only 100 entities, which is far too few to separate
O(matches) from O(page). This closes that gap.

Why cloning rather than a synthetic generator: the existing bench criteria
(`mql`, `state_ca`, `high_rated` in tests/performance/test_kgquery_generated_sql_plans.py)
transfer **unchanged and already verified**. Hand-authored criteria have produced
silently-zero-row benches twice in this work, so not writing new ones is worth
more than the elegance of generating from scratch.

Cloning is a string substitution. Every URI in a lead file is derived from the
lead id:

    urn:acme:lead:00QUg00000Xzjy8MAB
    urn:acme:lead:00QUg00000Xzjy8MAB:frame:leadstatusframe:0:frame:...:slot:mqlrating
    urn:acme:lead:00QUg00000Xzjy8MAB:edge:entity_to_leadstatusframe_0

so replacing that id yields a disjoint, self-consistent entity graph.

CONTROLLED SELECTIVITY is the point of the exercise, and the reason values are
resampled rather than copied. A growth curve needs match count to vary while
everything else is held constant, so the criteria slots are drawn from
distributions whose quantiles are known in closed form:

    MQLRating         uniform[0,100)   ->  P(value >= t) = (100 - t) / 100
    MQLv2             Bernoulli(p)     ->  P(true)       = p
    CompanyStateCode  weighted choice  ->  P(= 'CA')     = the CA weight

So `MQLRating >= 99.9` selects ~0.1% and `>= 0` selects 100%, from one fixture,
with the expected count computable analytically rather than measured. The
manifest written alongside the data records these so a bench can assert against
them instead of hardcoding observed numbers.

Every other slot value is copied verbatim — the fixture stays as close to the
real data as possible except where selectivity control demands otherwise.

    # 10,000 entities, criteria frames only (~10x smaller than full graphs)
    python scripts/generate_lead_dataset.py --entities 10000 --trim \
        --out internal_data/lead_synth

    # then the validated fast path:
    python test_scripts/import/... (uuid_only_quads=True)  ->  slim CSVs
    python scripts/load_wordnet_csv.py --space <id> --quads-csv ... --terms-csv ...

Output is N-Triples shards deliberately, not CSV: the .nt -> slim CSV -> COPY
path already exists and is validated, and duplicating the uuid5/datatype-id
logic here would be a second place for it to drift.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

XSD = "http://www.w3.org/2001/XMLSchema#"
KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

TRIPLE_RE = re.compile(r"^<([^>]*)> <([^>]*)> (.+) \.$")
SLOT_LOCAL_RE = re.compile(r":slot:([a-z0-9_]+)$")

# Frame subtrees the bench criteria actually touch. --trim keeps only these,
# which is the difference between ~2,700 quads per entity and a few hundred.
# The fixture exists to vary selectivity, not to be realistic.
CRITERIA_FRAMES = ("leadstatusframe", "companyframe")

# US state codes with deliberate weights — CA is pinned at 10% so `= 'CA'`
# has a known, non-trivial selectivity that is not a round 1/n.
STATE_WEIGHTS = {
    "CA": 10.0, "TX": 8.0, "FL": 7.0, "NY": 6.0, "PA": 4.0, "IL": 4.0,
    "OH": 3.5, "GA": 3.5, "NC": 3.0, "MI": 3.0, "NJ": 2.5, "VA": 2.5,
    "WA": 2.5, "AZ": 2.5, "MA": 2.0, "TN": 2.0, "IN": 2.0, "MO": 2.0,
    "MD": 2.0, "WI": 2.0, "CO": 2.0, "MN": 2.0, "SC": 1.5, "AL": 1.5,
    "LA": 1.5, "KY": 1.5, "OR": 1.5, "OK": 1.5, "CT": 1.5, "UT": 1.5,
    "NV": 1.5, "AR": 1.0, "MS": 1.0, "KS": 1.0, "NM": 1.0, "NE": 1.0,
    "ID": 1.0, "WV": 1.0, "HI": 1.0, "NH": 1.0, "ME": 1.0, "MT": 1.0,
    "RI": 1.0, "DE": 1.0, "SD": 1.0, "ND": 1.0, "AK": 1.0, "VT": 1.0,
    "WY": 1.0,
}

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Christopher",
    "Lisa", "Daniel", "Nancy", "Matthew", "Betty", "Anthony", "Margaret",
    "Mark", "Sandra", "Donald", "Ashley", "Steven", "Kimberly", "Andrew",
    "Emily", "Paul", "Donna", "Joshua", "Michelle", "Kenneth", "Carol",
    "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa", "Timothy",
    "Deborah",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts",
]

# --- The Nurture shape, FITTED TO PRODUCTION ------------------------------
#
# `planning/planning_performance/lead_fixture_production_shape_plan.md`.
#
# The fixture could not express the query that broke production:
#
#     entity_type = X, plus TWO frame criteria —
#       a campaign URI  COMMON, shared by many entities
#       an SF lead id   RARE, and ZERO for a lead that is new
#
# MEASURED AGAINST THE PRODUCTION SPACE 2026-09-04, because the first version of
# this was built from the bench script's *shape* and got the mechanism wrong:
#
#     hasUriSlotValue      53,937 rows / 5,176 distinct values
#       head               42,399  = 78.6% of rows   <- the campaign
#       singletons          2,679  = 52% of values   <- per-entity URIs
#     hasTextSlotValue  1,082,018                    <- lead ids live here
#     hasEntitySlotValue        0                    <- NONE. frame_entity is 0.
#
# THREE THINGS THAT VERSION GOT WRONG, all corrected here:
#
#   1. It used `hasEntitySlotValue`. Production has ZERO of them and its
#      `frame_entity` table is empty. The campaign is a URI-VALUED LITERAL slot
#      (`hasUriSlotValue`), not an entity reference. Adding an entity connector
#      made the fixture LESS like production, not more.
#   2. Zipf(s=1.1) over 40 values gave a 26% head. Production's head is 78.6%
#      over 5,176 values. Not the same distribution in any useful sense.
#   3. It missed the singleton tail entirely — half of production's distinct URI
#      values occur exactly once, which is the per-entity URI case.
#
# So the model here is an explicit three-part mixture rather than a pure Zipf,
# because production is not one: a dominant campaign, a short head of secondary
# campaigns, and a long singleton tail. Each share is a named constant so the
# manifest can report it and a bench can assert against it.
NURTURE_HEAD_SHARE = 0.786      # one campaign, matching prod's 42,399/53,937
NURTURE_SINGLETON_SHARE = 0.05  # per-entity URIs — prod's 52% of DISTINCT values
NURTURE_CAMPAIGNS = 40          # the secondary head; the rest of the mass
NURTURE_ZIPF_EXPONENT = 1.1     # ...distributed over those, as prod's tail is
NURTURE_FRAME_TYPE = "urn:acme:kg:frame:NurtureInfoFrame"
NURTURE_CAMPAIGN_SLOT = "urn:acme:kg:slot:NurtureCampaignURI"
NURTURE_LEADID_SLOT = "urn:acme:kg:slot:SFLeadId"
CAMPAIGN_URI = "urn:acme:campaign:{n:03d}"

# Lead ids the generator deliberately does NOT emit. The production failure is a
# query for a lead that does not exist yet, and without a declared absent id
# there is no way to write that test down — any id you invent might collide with
# a generated one, and "0 rows" then means "collided" rather than "absent".
ABSENT_LEAD_IDS = 25

# Thresholds the manifest reports counts for. A growth-curve bench sweeps
# these to vary match count while the dataset stays fixed.
GTE_THRESHOLDS = (0, 50, 65, 90, 99, 99.9)

# Integer thresholds, reported exactly like the double ones so `gte`/`lt` on an
# integer slot can be asserted rather than guessed at.
INT_GTE_THRESHOLDS = (0, 25, 50, 75, 90, 100)

# Datetimes are drawn from a BOUNDED set of days rather than uniformly over a
# range at second resolution. Second resolution made every value distinct, so
# `eq` on a datetime matched exactly one row and every range threshold had an
# unknown count — the slot existed but no operator over it could be asserted.
# A day grid gives eq a real bucket and makes range selectivity computable.
DT_DAYS = 200
DT_GTE_DAYS = (0, 50, 100, 150, 190)

# Choice slots hold enum URIs, not bare labels. Weighted so `eq` has a
# non-round selectivity and `ne` has a large complement.
LEAD_STATUS_WEIGHTS = {
    "Assigned": 45.0, "Working": 25.0, "Qualified": 15.0,
    "Nurturing": 10.0, "Disqualified": 5.0,
}

# Currency: a long-tailed distribution, since revenue is not uniform and a
# uniform one would make every threshold equally selective.
CURRENCY_BUCKETS = (1_000, 10_000, 50_000, 250_000, 1_000_000)

# A needle planted in a known fraction of company names so `contains` has an
# expected count instead of "whatever the random names happened to contain".
CONTAINS_NEEDLE = "Zyx"
CONTAINS_EVERY = 7

# One slot in this many is emitted WITHOUT a value, so `is_empty` and
# `not_exists` select a known non-trivial subset. Every slot having a value is
# why those comparators returned nothing and their tests compared empty sets.
EMPTY_EVERY = 8
EMPTY_SLOT = "mqlratingpoints"

DT_START = datetime(2020, 1, 1)
DT_END = datetime(2026, 1, 1)


def lit(value: str, dtype: str) -> str:
    return f'"{value}"^^<{XSD}{dtype}>'


DROP_VALUE = object()


class Sampler:
    """Draws the resampled slot values for one synthetic entity.

    Keyed by the slot's local name, which the URI carries directly
    (`...:slot:mqlrating`), so no lookup of hasKGSlotType is needed.
    """

    def __init__(self, rng: random.Random, mql_true_rate: float):
        self.rng = rng
        self.mql_true_rate = mql_true_rate
        self.states = list(STATE_WEIGHTS)
        self.state_weights = [STATE_WEIGHTS[s] for s in self.states]
        # Tallies of what was actually emitted. The analytic prediction is an
        # expectation, so a bench asserting against it would be flaky by
        # construction (at n=2,000 the >= 90 bucket landed 231 against a
        # predicted 200 — ordinary binomial noise). These are exact.
        self.n_mqlrating = 0
        self.mqlrating_gte = {t: 0 for t in GTE_THRESHOLDS}
        self.mqlv2_true = 0
        self.mqlv2_total = 0
        self.state_counts: dict[str, int] = {}
        # Every other type now carries the same kind of exact tally, so a bench
        # can assert a number for each operator rather than "more than zero".
        self.n_ratingpoints = 0
        self.ratingpoints_gte = {t: 0 for t in INT_GTE_THRESHOLDS}
        self.n_datetime = 0
        self.datetime_gte = {d: 0 for d in DT_GTE_DAYS}
        self.leadstatus_counts: dict[str, int] = {}
        self.currency_gte = {c: 0 for c in CURRENCY_BUCKETS}
        self.n_currency = 0
        self.contains_hits = 0
        self.n_names = 0
        self.empty_slots = 0
        self.valued_slots = 0
        self._statuses = list(LEAD_STATUS_WEIGHTS)
        self._status_weights = [LEAD_STATUS_WEIGHTS[k] for k in self._statuses]
        self._empty_seen = 0
        # Zipf weights over the campaign set: rank 1 gets the most, and the tail
        # is long. Precomputed once — `random.choices` renormalises per call
        # otherwise, which at 100k entities is measurable.
        self._campaigns = [CAMPAIGN_URI.format(n=i)
                           for i in range(NURTURE_CAMPAIGNS)]
        self._campaign_weights = [1.0 / ((i + 1) ** NURTURE_ZIPF_EXPONENT)
                                  for i in range(NURTURE_CAMPAIGNS)]
        self.campaign_counts: dict[str, int] = {}
        self.campaign_singletons = 0

    def campaign(self, new_id: str) -> str:
        """One URI-slot value, matching production's three-part mixture.

        Production is not a pure Zipf and modelling it as one produced a 26%
        head against its actual 78.6%. It is: one dominant campaign, a short
        head of secondary ones, and a long tail of per-entity URIs that occur
        exactly once (52% of its distinct values).
        """
        r = self.rng.random()
        if r < NURTURE_HEAD_SHARE:
            c = self._campaigns[0]
        elif r < NURTURE_HEAD_SHARE + NURTURE_SINGLETON_SHARE:
            # The singleton tail: a URI unique to this entity. Never collides,
            # so `eq` on one of these selects exactly 1.
            self.campaign_singletons += 1
            return f"urn:acme:entityref:{new_id}"
        else:
            c = self.rng.choices(self._campaigns[1:],
                                 self._campaign_weights[1:])[0]
        self.campaign_counts[c] = self.campaign_counts.get(c, 0) + 1
        return c

    def value_for(self, slot: str, predicate: str) -> str | None:
        """Return a replacement literal, or None to keep the original."""
        if slot == "mqlrating":
            # Uniform so P(>= t) = (100 - t)/100 exactly. One decimal place
            # keeps the term table's distinct-value count sane while leaving
            # 1,000 distinct thresholds to choose from.
            v = round(self.rng.uniform(0.0, 100.0), 1)
            self.n_mqlrating += 1
            for t in GTE_THRESHOLDS:
                if v >= t:
                    self.mqlrating_gte[t] += 1
            return lit(f"{v:.1f}", "float")
        if slot == "mqlratingpoints":
            # Emitted WITHOUT a value one time in EMPTY_EVERY. `is_empty` and
            # `not_exists` are unanswerable otherwise: with every slot valued
            # they select nothing, so a test over them passes while comparing
            # empty sets. Returning the sentinel drops the value triple and
            # leaves the slot node, which is what "empty" means here.
            self._empty_seen += 1
            if self._empty_seen % EMPTY_EVERY == 0:
                self.empty_slots += 1
                return DROP_VALUE
            self.valued_slots += 1
            v = self.rng.randint(0, 100)
            self.n_ratingpoints += 1
            for t in INT_GTE_THRESHOLDS:
                if v >= t:
                    self.ratingpoints_gte[t] += 1
            return lit(str(v), "integer")
        if slot == "leadstatus":
            st = self.rng.choices(self._statuses, self._status_weights)[0]
            self.leadstatus_counts[st] = self.leadstatus_counts.get(st, 0) + 1
            # A LITERAL, not a URI node. The source data stores enum values as
            # term_type 'L' — emitting <...> instead produced a URI term that no
            # criterion matched, and the slot silently answered nothing.
            return lit(f"urn:acme:kg:enum:LeadStatus:{st}", "string")
        if slot in ("monthlygrosssales", "verifiedrevenue"):
            # Log-uniform: revenue is long-tailed, and a uniform draw would make
            # every threshold equally selective, which tests nothing about
            # estimation.
            v = round(self.rng.lognormvariate(10.5, 1.2), 2)
            self.n_currency += 1
            for c in CURRENCY_BUCKETS:
                if v >= c:
                    self.currency_gte[c] += 1
            return lit(f"{v:.2f}", "decimal")
        if slot == "mqlv2":
            is_true = self.rng.random() < self.mql_true_rate
            self.mqlv2_total += 1
            self.mqlv2_true += int(is_true)
            return lit("true" if is_true else "false", "boolean")
        if slot == "companystatecode":
            st = self.rng.choices(self.states, self.state_weights)[0]
            self.state_counts[st] = self.state_counts.get(st, 0) + 1
            return lit(st, "string")
        if predicate == f"{KG}hasDateTimeSlotValue":
            # A day grid, not seconds. At second resolution every value was
            # distinct, so `eq` matched one row and no range threshold had a
            # known count — the slot was present but no operator over it could
            # be asserted. DT_DAYS buckets give eq a real selectivity and make
            # every range computable.
            day = self.rng.randrange(DT_DAYS)
            dt = DT_START + timedelta(days=day)
            self.n_datetime += 1
            for d in DT_GTE_DAYS:
                if day >= d:
                    self.datetime_gte[d] += 1
            return lit(dt.strftime("%Y-%m-%dT00:00:00"), "dateTime")
        return None

    def name(self) -> str:
        # A known fraction carries CONTAINS_NEEDLE, so `contains` has an
        # expected count rather than whatever the random names happened to
        # share.
        self.n_names += 1
        first = self.rng.choice(FIRST_NAMES)
        last = self.rng.choice(LAST_NAMES)
        if self.n_names % CONTAINS_EVERY == 0:
            self.contains_hits += 1
            last = f"{last}{CONTAINS_NEEDLE}"
        return f"{first} {last}"


def _node(uri: str, vitaltype: str) -> list[str]:
    """The four triples every node in this model carries.

    URIProp / vitaltype / rdf:type are not decoration — the loader and the
    derived-table syncs all key off them, and a node missing one is invisible to
    whichever of them reads it.
    """
    return [
        f"<{uri}> <{VC}URIProp> <{uri}> .",
        f"<{uri}> <{VC}vitaltype> <{KG}{vitaltype}> .",
        f"<{uri}> <{RDF_TYPE}> <{KG}{vitaltype}> .",
    ]


def _edge(uri: str, src: str, dst: str, vitaltype: str) -> list[str]:
    return _node(uri, vitaltype) + [
        f"<{uri}> <{VC}hasEdgeSource> <{src}> .",
        f"<{uri}> <{VC}hasEdgeDestination> <{dst}> .",
    ]


def nurture_triples(entity_uri: str, new_id: str, sampler: Sampler) -> list[str]:
    """The nurture frame: one COMMON entity-valued slot, one UNIQUE text slot.

    This is the shape the fixture existed without — see the block comment at
    NURTURE_CAMPAIGNS. The campaign slot uses `hasEntitySlotValue`, which is
    what makes `frame_entity` non-empty and frame criteria answerable at all.
    """
    frame = f"{entity_uri}:frame:nurtureinfoframe:0"
    c_slot = f"{frame}:slot:nurturecampaign"
    l_slot = f"{frame}:slot:sfleadid"
    campaign = sampler.campaign(new_id)

    out = _node(frame, "KGFrame")
    out.append(f"<{frame}> <{KG}hasKGFrameType> <{NURTURE_FRAME_TYPE}> .")
    out += _edge(f"{entity_uri}:edge:entity_to_nurtureinfoframe_0",
                 entity_uri, frame, "Edge_hasEntityKGFrame")

    # COMMON end: a URI-VALUED LITERAL slot, not an entity reference.
    # Production carries zero `hasEntitySlotValue` and an empty frame_entity
    # table; its campaign is `hasUriSlotValue`. Emitting an entity connector
    # here made the fixture less faithful, not more, and is why frame_entity
    # went from 0 to 5,000 in a way production never does.
    # `KGURISlot`, not `KGUriSlot`. The ontology spells the PREDICATE
    # `hasUriSlotValue` and the CLASS `KGURISlot`, and `kg_query_builder.py:108`
    # maps only the latter. Emitting `KGUriSlot` produced a slot the query
    # builder could not resolve to a value predicate, so the criterion matched
    # nothing while the data looked correct.
    out += _node(c_slot, "KGURISlot")
    out.append(f"<{c_slot}> <{KG}hasKGSlotType> <{NURTURE_CAMPAIGN_SLOT}> .")
    out.append(f"<{c_slot}> <{KG}hasUriSlotValue> <{campaign}> .")
    out += _edge(f"{frame}:edge:to_slot_nurturecampaign",
                 frame, c_slot, "Edge_hasKGSlot")

    # RARE end: the lead id, unique per entity. `eq` on this selects exactly one
    # — and on a DECLARED-ABSENT id, exactly zero.
    out += _node(l_slot, "KGTextSlot")
    out.append(f"<{l_slot}> <{KG}hasKGSlotType> <{NURTURE_LEADID_SLOT}> .")
    out.append(f"<{l_slot}> <{KG}hasTextSlotValue> {lit(new_id, 'string')} .")
    out += _edge(f"{frame}:edge:to_slot_sfleadid",
                 frame, l_slot, "Edge_hasKGSlot")
    return out


def load_templates(template_dir: Path, limit: int | None) -> list[tuple[str, list[str]]]:
    """Return [(lead_id, [lines])] for each template graph."""
    out = []
    for path in sorted(template_dir.glob("lead_*.nt")):
        lead_id = path.stem[len("lead_"):]
        with open(path, "r", encoding="utf-8") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        out.append((lead_id, lines))
        if limit and len(out) >= limit:
            break
    return out


def keep_subject(subject: str, entity_uri: str) -> bool:
    """Trim predicate: is this subject inside a criteria frame subtree?

    Relies on the URI hierarchy encoding containment. Edges are named for the
    frame they attach (`:edge:entity_to_leadstatusframe_0`), so the same
    substring test covers them; an edge to a dropped frame is itself dropped,
    and its destination triples go with it.
    """
    if subject == entity_uri:
        return True
    if not subject.startswith(entity_uri + ":"):
        return True          # not entity-scoped (shared vocabulary) — keep
    tail = subject[len(entity_uri) + 1:]
    return any(f in tail for f in CRITERIA_FRAMES)


def render_entity(lead_id: str, lines: list[str], new_id: str,
                  sampler: Sampler, trim: bool) -> list[str]:
    """Clone one template graph under a new entity id, resampling values."""
    entity_uri = f"urn:acme:lead:{new_id}"
    name_literal = lit(sampler.name(), "string")
    out = []

    for line in lines:
        line = line.replace(lead_id, new_id)
        m = TRIPLE_RE.match(line)
        if not m:
            continue
        subj, pred, obj = m.group(1), m.group(2), m.group(3)

        if trim and not keep_subject(subj, entity_uri):
            continue

        # Distinct names: 100 templates over N entities would otherwise make
        # sorting and pagination benches degenerate.
        if subj == entity_uri and pred.endswith("#hasName"):
            obj = name_literal
        elif obj.startswith('"'):
            sm = SLOT_LOCAL_RE.search(subj)
            if sm:
                repl = sampler.value_for(sm.group(1), pred)
                if repl is DROP_VALUE:
                    continue        # slot stays, value triple is not emitted
                if repl is not None:
                    obj = repl

        out.append(f"<{subj}> <{pred}> {obj} .")

    # Appended, not woven in: the templates have no nurture frame to clone, so
    # this is synthesised rather than substituted. It survives --trim on purpose
    # — trimming exists to drop frames the criteria do not touch, and this one
    # is the reason the fixture can express the criteria at all.
    out += nurture_triples(entity_uri, new_id, sampler)

    return out


def expected_selectivity(n: int, mql_true_rate: float) -> dict:
    """Analytic match counts — what a growth-curve bench should assert."""
    total_w = sum(STATE_WEIGHTS.values())
    return {
        "mqlrating_gte": {str(t): round(n * (100 - t) / 100.0)
                          for t in GTE_THRESHOLDS},
        "mqlv2_true": round(n * mql_true_rate),
        "companystatecode_eq": {
            s: round(n * w / total_w) for s, w in
            sorted(STATE_WEIGHTS.items(), key=lambda kv: -kv[1])[:5]
        },
    }


def generate(template_dir: Path, out_dir: Path, n_entities: int, seed: int,
             trim: bool, shard_entities: int, mql_true_rate: float,
             templates_limit: int | None) -> int:
    templates = load_templates(template_dir, templates_limit)
    if not templates:
        print(f"❌ no lead_*.nt templates in {template_dir}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("lead_syn_*.nt"):
        stale.unlink()

    rng = random.Random(seed)
    sampler = Sampler(rng, mql_true_rate)

    print(f"📚 {len(templates)} template graphs → {n_entities:,} entities "
          f"({'trimmed to ' + '/'.join(CRITERIA_FRAMES) if trim else 'full graphs'})")

    t0 = time.time()
    total_lines = 0
    shard_idx = 0
    fh = None
    for i in range(n_entities):
        if i % shard_entities == 0:
            if fh:
                fh.close()
            shard_idx += 1
            fh = open(out_dir / f"lead_syn_{shard_idx:04d}.nt", "w",
                      encoding="utf-8")

        lead_id, lines = templates[i % len(templates)]
        new_id = f"SYN{i:09d}"
        rendered = render_entity(lead_id, lines, new_id, sampler, trim)
        fh.write("\n".join(rendered))
        fh.write("\n")
        total_lines += len(rendered)

        if (i + 1) % 5000 == 0:
            rate = (i + 1) / max(time.time() - t0, 0.001)
            print(f"   {i+1:,}/{n_entities:,} entities  "
                  f"{total_lines:,} triples  {rate:,.0f} ent/s")
    if fh:
        fh.close()

    manifest = {
        "n_entities": n_entities,
        "n_triples": total_lines,
        "triples_per_entity": round(total_lines / max(n_entities, 1), 1),
        "seed": seed,
        "trim": trim,
        "criteria_frames": list(CRITERIA_FRAMES) if trim else "all",
        "templates_used": len(templates),
        "distributions": {
            "MQLRating": "uniform[0,100) 1dp, xsd:float",
            "MQLRatingPoints": "uniform int [0,100], xsd:integer",
            "MQLv2": f"Bernoulli(p={mql_true_rate}), xsd:boolean",
            "CompanyStateCode": "weighted choice over 49 states, xsd:string",
            "NurtureCampaignURI": (
                f"mixture fitted to production: {NURTURE_HEAD_SHARE:.1%} one "
                f"dominant campaign, {NURTURE_SINGLETON_SHARE:.1%} per-entity "
                f"singletons, remainder Zipf(s={NURTURE_ZIPF_EXPONENT}) over "
                f"{NURTURE_CAMPAIGNS - 1} secondary campaigns; hasUriSlotValue"),
            "SFLeadId": "unique per entity, xsd:string",
            "*DateTimeSlotValue": f"uniform [{DT_START.date()}, {DT_END.date()}), xsd:dateTime",
            "_other": "copied verbatim from the template graph",
        },
        "expected_matches": expected_selectivity(n_entities, mql_true_rate),
        # Ids this run deliberately did NOT emit. The production failure is a
        # query for a lead that does not exist yet; without a DECLARED absent id
        # there is no way to write that test, because any id you invent might
        # collide with a generated one and "0 rows" would then mean "collided".
        # These are outside the SYN%09d space by construction.
        "absent_lead_ids": [f"ABSENT{i:09d}" for i in range(ABSENT_LEAD_IDS)],
        "connector": {
            "predicate": f"{KG}hasUriSlotValue",
            "frame_type": NURTURE_FRAME_TYPE,
            "campaign_slot": NURTURE_CAMPAIGN_SLOT,
            "leadid_slot": NURTURE_LEADID_SLOT,
            "note": ("synthesised — the templates carry no nurture frame. "
                     "URI-VALUED, matching production, which has zero "
                     "hasEntitySlotValue and an empty frame_entity table."),
            "fitted_to": {
                "space": "prod_kg", "measured": "2026-09-04",
                "uri_slot_rows": 53937, "uri_slot_distinct": 5176,
                "head_share": 0.786, "singleton_values": 2679,
            },
        },
        # Exact tallies of what was emitted — assert against THESE, not the
        # analytic expectation above, which is only a distributional target.
        "actual_matches": {
            "mqlrating_total": sampler.n_mqlrating,
            "mqlrating_gte": {str(t): c
                              for t, c in sampler.mqlrating_gte.items()},
            "mqlv2_true": sampler.mqlv2_true,
            "mqlv2_total": sampler.mqlv2_total,
            "companystatecode_eq": dict(sorted(sampler.state_counts.items(),
                                               key=lambda kv: -kv[1])),
            # THE NURTURE SHAPE. A bench pairs a head of this list (COMMON,
            # thousands of entities) with an sfleadid (RARE, exactly one) or an
            # absent id (ZERO) — the two-ended query the fixture could not
            # express before.
            "nurturecampaign_eq": dict(sorted(sampler.campaign_counts.items(),
                                              key=lambda kv: -kv[1])),
            "sfleadid_eq": 1,
            "nurturecampaign_singletons": sampler.campaign_singletons,
            "ratingpoints_total": sampler.n_ratingpoints,
            "ratingpoints_gte": {str(t): c
                                 for t, c in sampler.ratingpoints_gte.items()},
            "datetime_total": sampler.n_datetime,
            "datetime_gte_day": {str(d): c
                                 for d, c in sampler.datetime_gte.items()},
            "datetime_day_grid": DT_DAYS,
            "datetime_start": DT_START.strftime("%Y-%m-%dT00:00:00"),
            "leadstatus_eq": dict(sorted(sampler.leadstatus_counts.items(),
                                         key=lambda kv: -kv[1])),
            "currency_total": sampler.n_currency,
            "currency_gte": {str(c): n for c, n in sampler.currency_gte.items()},
            "name_contains": {CONTAINS_NEEDLE: sampler.contains_hits,
                              "of": sampler.n_names},
            "empty_slots": {"slot": EMPTY_SLOT,
                            "empty": sampler.empty_slots,
                            "valued": sampler.valued_slots},
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    dt = time.time() - t0
    print(f"\n🏁 {n_entities:,} entities / {total_lines:,} triples "
          f"({manifest['triples_per_entity']} per entity) "
          f"in {shard_idx} shard(s), {dt:.1f}s")
    print(f"📄 manifest: {out_dir / 'manifest.json'}")
    print("   MQLRating >= t (exact): "
          + ", ".join(f"{t}→{c:,}" for t, c in
                      manifest["actual_matches"]["mqlrating_gte"].items()))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template-dir", default="internal_data/lead_test_data")
    ap.add_argument("--out", default="internal_data/lead_synth")
    ap.add_argument("--entities", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20260806)
    ap.add_argument("--trim", action="store_true",
                    help="emit only the frame subtrees the bench criteria "
                         "touch (leadstatusframe, companyframe) — roughly 10x "
                         "smaller per entity")
    ap.add_argument("--shard-entities", type=int, default=5000,
                    help="entities per output .nt shard")
    ap.add_argument("--mql-true-rate", type=float, default=0.5,
                    help="P(MQLv2 = true)")
    ap.add_argument("--templates", type=int, default=None,
                    help="use only the first N template graphs")
    a = ap.parse_args()

    return generate(Path(a.template_dir), Path(a.out), a.entities, a.seed,
                    a.trim, a.shard_entities, a.mql_true_rate, a.templates)


if __name__ == "__main__":
    sys.exit(main())
