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

# Thresholds the manifest reports counts for. A growth-curve bench sweeps
# these to vary match count while the dataset stays fixed.
GTE_THRESHOLDS = (0, 50, 65, 90, 99, 99.9)

DT_START = datetime(2020, 1, 1)
DT_END = datetime(2026, 1, 1)


def lit(value: str, dtype: str) -> str:
    return f'"{value}"^^<{XSD}{dtype}>'


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
            return lit(str(self.rng.randint(0, 100)), "integer")
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
            span = int((DT_END - DT_START).total_seconds())
            dt = DT_START + timedelta(seconds=self.rng.randrange(span))
            return lit(dt.strftime("%Y-%m-%dT%H:%M:%S"), "dateTime")
        return None

    def name(self) -> str:
        return (f"{self.rng.choice(FIRST_NAMES)} "
                f"{self.rng.choice(LAST_NAMES)}")


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
                if repl is not None:
                    obj = repl

        out.append(f"<{subj}> <{pred}> {obj} .")

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
            "*DateTimeSlotValue": f"uniform [{DT_START.date()}, {DT_END.date()}), xsd:dateTime",
            "_other": "copied verbatim from the template graph",
        },
        "expected_matches": expected_selectivity(n_entities, mql_true_rate),
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
