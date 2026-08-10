#!/usr/bin/env python
"""Generate a fixture of KG RELATIONS with social-network shape, plus both frame
form types.

Why this exists
---------------
Every other performance fixture is tree-shaped. `sp_lead_synth_100k` holds the
three containment edge types and `wordnet_frames` only Edge_hasKGSlot, so neither
has a relation edge — matching `issues/043`/`048`, where `build_relation_query`
requires Edge_hasKGRelation and it has essentially zero instances anywhere.

Traversal cost is decided by FAN-OUT, and fan-out is a property of the edge kind
(`issues/061`). On tree-shaped data a rule like "traverse backward, it never
amplifies" looks unconditionally correct, because a slot has exactly one parent
and a frame none or one. Relations refute it: an entity may be source or
destination in many.

Relations are simple binary relationships — `person1 --friendOf--> person2`,
`person1 --worksFor--> company1` — so this generates them with the structure such
data actually has rather than uniformly at random.

The point: fan-out varies by RELATION TYPE, not just by edge type
------------------------------------------------------------------
All of these are `Edge_hasKGRelation`, and their fan-out profiles are opposites:

    reportsTo   person -> manager    backward ~1      (one manager each: a tree)
    worksFor    person -> company    backward = company size (many-to-one hub)
    friendOf    person -> person     both directions similar, power-law tail
    mentions    person -> any        diffuse

So a metric recorded per *edge type* still pools a tree with a hub and averages
them into a number describing neither. Whatever granularity the fan-out statistic
ends up with has to reach `hasKGRelationType`, and this fixture is what
demonstrates that.

Structure generated
-------------------
* **Persons** and **Companies** — two entity types, since worksFor needs a range
  distinct from its domain.
* **friendOf** — Watts-Strogatz small world: a ring lattice of k nearest
  neighbours, each edge rewired with probability p. That yields the high
  clustering and short characteristic path length of a social graph.

  Known limitation: Watts-Strogatz produces a *tight* degree distribution
  (measured here: out max 3, in max 6), not the heavy tail real friendship
  networks have. Small-world and scale-free are different properties;
  Barabasi-Albert preferential attachment would be the model for the latter. The
  heavy tail in this fixture comes from `worksFor` instead, which is enough for
  the fan-out work — but if a bench ever needs a power-law *social* degree, this
  is the knob that does not provide it.
* **worksFor** — each person to one company, company sizes Zipf-skewed, so a few
  companies hold most employees. Backward fan-out is the company size.
* **reportsTo** — a management tree inside each company: every person except a
  root has exactly one manager. Backward fan-out is 1 by construction — a tree
  living *inside* the relation edge type, which is exactly why pooling by edge
  type loses information.
* **Assertion frames** — top-level. A fraction leave `hasKGFormType` UNSET, since
  unset defaults to assertion and a fixture that always states it cannot catch a
  reader that requires the explicit triple.
* **Aspect frames** — attached to an entity, or beneath an assertion, so both
  parent kinds appear.
* **Slots**, including `hasEntitySlotValue` pointing at entities with a skewed
  target distribution, reproducing the many-to-one shape wordnet has (measured
  there: in-degree avg 5.20, max 1,342).

The manifest records the degree distribution of every relation type in both
directions, so a test can assert them instead of recomputing them from the data
it is meant to be checking.

Usage
-----
    python scripts/generate_relation_dataset.py --out internal_data/kg_rel \\
        --entities 5000
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"
NS = "urn:acme:kg"

VITALTYPE = f"<{CORE}vitaltype>"
EDGE_SOURCE = f"<{CORE}hasEdgeSource>"
EDGE_DEST = f"<{CORE}hasEdgeDestination>"
URIPROP = f"<{CORE}URIProp>"

KGENTITY = f"<{KG}KGEntity>"
KGFRAME = f"<{KG}KGFrame>"
KGSLOT = f"<{KG}KGTextSlot>"
E_ENTITY_FRAME = f"<{KG}Edge_hasEntityKGFrame>"
E_FRAME = f"<{KG}Edge_hasKGFrame>"
E_SLOT = f"<{KG}Edge_hasKGSlot>"
E_RELATION = f"<{KG}Edge_hasKGRelation>"

HAS_ENTITY_TYPE = f"<{KG}hasKGEntityType>"
HAS_FRAME_TYPE = f"<{KG}hasKGFrameType>"
HAS_SLOT_TYPE = f"<{KG}hasKGSlotType>"
HAS_FORM_TYPE = f"<{KG}hasKGFormType>"
HAS_RELATION_TYPE = f"<{KG}hasKGRelationType>"
HAS_TEXT_VALUE = f"<{KG}hasTextSlotValue>"
HAS_ENTITY_VALUE = f"<{KG}hasEntitySlotValue>"

FORM_ASSERTION = f"<{KG}KGFormType_Assertion>"
FORM_ASPECT = f"<{KG}KGFormType_Aspect>"

# One company per this many persons. Company sizes are then Zipf-skewed on top,
# so the mean is not the typical value.
PERSONS_PER_COMPANY = 40

# Watts-Strogatz: each person starts joined to K_NEIGHBOURS on a ring, and each
# of those edges is rewired to a random target with probability REWIRE_P. Low p
# keeps clustering high while collapsing path length — the small-world regime.
K_NEIGHBOURS = 6
REWIRE_P = 0.08

# Management tree fan-out inside a company.
REPORTS_PER_MANAGER = 5

MENTIONS_PER_PERSON = (0, 0, 1, 2)

FORM_TYPE_UNSET_EVERY = 4

# Entity-valued slot targets. wordnet measures in-degree avg 5.20 / max 1,342,
# a 258x mean-to-max ratio; a hub set of a few thousandths reproduces that order.
ENTITY_VALUE_HUB_FRACTION = 0.002
ENTITY_VALUE_HUB_BIAS = 0.75


def _t(s: str, p: str, o: str) -> str:
    return f"{s} {p} {o} ."


def _lit(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _pct(vals, q: float) -> int:
    if not vals:
        return 0
    o = sorted(vals)
    return o[min(len(o) - 1, int(q * (len(o) - 1)))]


def _degree(counts: dict, population: int) -> dict:
    """Degree distribution including zeros, which are part of the shape."""
    vals = list(counts.values()) + [0] * max(0, population - len(counts))
    total = sum(vals)
    return {"total": total,
            "avg": round(total / len(vals), 3) if vals else 0,
            "p50": _pct(vals, 0.50), "p99": _pct(vals, 0.99),
            "max": max(vals) if vals else 0,
            "nonzero": len([v for v in vals if v])}


def generate(out_dir: Path, entities: int, seed: int) -> dict:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_companies = max(2, entities // PERSONS_PER_COMPANY)
    n_persons = entities - n_companies
    person = [f"<{NS}:entity:person:{i}>" for i in range(n_persons)]
    company = [f"<{NS}:entity:company:{i}>" for i in range(n_companies)]

    lines: list[str] = []
    emit = lines.append

    for u in person:
        emit(_t(u, VITALTYPE, KGENTITY))
        emit(_t(u, HAS_ENTITY_TYPE, f"<{NS}:entity_type:Person>"))
    for u in company:
        emit(_t(u, VITALTYPE, KGENTITY))
        emit(_t(u, HAS_ENTITY_TYPE, f"<{NS}:entity_type:Company>"))

    # ---- relations -------------------------------------------------------
    rel_seq = [0]
    per_type_out: dict[str, dict] = {}
    per_type_in: dict[str, dict] = {}

    def relate(src: str, dst: str, rtype: str, si: int, di: int) -> None:
        u = f"<{NS}:edge:rel:{rel_seq[0]}>"
        rel_seq[0] += 1
        emit(_t(u, VITALTYPE, E_RELATION))
        emit(_t(u, URIPROP, _lit(u[1:-1])))
        emit(_t(u, EDGE_SOURCE, src))
        emit(_t(u, EDGE_DEST, dst))
        emit(_t(u, HAS_RELATION_TYPE, f"<{NS}:rel_type:{rtype}>"))
        o = per_type_out.setdefault(rtype, {})
        i_ = per_type_in.setdefault(rtype, {})
        o[si] = o.get(si, 0) + 1
        i_[di] = i_.get(di, 0) + 1

    # friendOf: Watts-Strogatz ring lattice with rewiring.
    half = max(1, K_NEIGHBOURS // 2)
    for i in range(n_persons):
        for step in range(1, half + 1):
            j = (i + step) % n_persons
            if rng.random() < REWIRE_P:
                j = rng.randrange(n_persons)
                if j == i:
                    continue
            relate(person[i], person[j], "friendOf", i, j)

    # worksFor: Zipf-skewed company sizes, so a few employ most people.
    weights = [1.0 / (r + 1) for r in range(n_companies)]
    staff: dict[int, list[int]] = {}
    for i in range(n_persons):
        c = rng.choices(range(n_companies), weights)[0]
        relate(person[i], company[c], "worksFor", i, c)
        staff.setdefault(c, []).append(i)

    # reportsTo: a management tree inside each company. Everyone but the root
    # has exactly one manager, so BACKWARD fan-out is 1 by construction — a tree
    # nested inside the same edge type as the hubs above.
    for c, members in staff.items():
        for pos, p_idx in enumerate(members):
            if pos == 0:
                continue                     # the root reports to nobody
            mgr = members[(pos - 1) // REPORTS_PER_MANAGER]
            if mgr != p_idx:
                relate(person[p_idx], person[mgr], "reportsTo", p_idx, mgr)

    # mentions: diffuse, no structure — the control case.
    for i in range(n_persons):
        for _ in range(rng.choice(MENTIONS_PER_PERSON)):
            j = rng.randrange(n_persons)
            if j != i:
                relate(person[i], person[j], "mentions", i, j)

    # ---- frames and slots on persons -------------------------------------
    value_hubs = rng.sample(range(n_persons),
                            max(1, int(n_persons * ENTITY_VALUE_HUB_FRACTION)))
    value_in: dict[int, int] = {}
    n_assert_set = n_assert_unset = n_aspect = 0
    n_aspect_entity = n_aspect_assertion = n_slots = 0
    n_text = n_entity_vals = 0

    for i in range(n_persons):
        e = person[i]
        af = f"<{NS}:frame:assert:{i}>"
        emit(_t(af, VITALTYPE, KGFRAME))
        emit(_t(af, HAS_FRAME_TYPE, f"<{NS}:frame_type:Profile>"))
        if i % FORM_TYPE_UNSET_EVERY:
            emit(_t(af, HAS_FORM_TYPE, FORM_ASSERTION))
            n_assert_set += 1
        else:
            n_assert_unset += 1

        pf = f"<{NS}:frame:aspect:e{i}>"
        emit(_t(pf, VITALTYPE, KGFRAME))
        emit(_t(pf, HAS_FRAME_TYPE, f"<{NS}:frame_type:Contact>"))
        emit(_t(pf, HAS_FORM_TYPE, FORM_ASPECT))
        ee = f"<{NS}:edge:ef:{i}>"
        emit(_t(ee, VITALTYPE, E_ENTITY_FRAME))
        emit(_t(ee, EDGE_SOURCE, e))
        emit(_t(ee, EDGE_DEST, pf))
        n_aspect += 1
        n_aspect_entity += 1

        cf = f"<{NS}:frame:aspect:a{i}>"
        emit(_t(cf, VITALTYPE, KGFRAME))
        emit(_t(cf, HAS_FRAME_TYPE, f"<{NS}:frame_type:Detail>"))
        emit(_t(cf, HAS_FORM_TYPE, FORM_ASPECT))
        fe = f"<{NS}:edge:ff:{i}>"
        emit(_t(fe, VITALTYPE, E_FRAME))
        emit(_t(fe, EDGE_SOURCE, af))
        emit(_t(fe, EDGE_DEST, cf))
        n_aspect += 1
        n_aspect_assertion += 1

        for frame, tag in ((pf, "c"), (cf, "d")):
            s = f"<{NS}:slot:{tag}{i}>"
            emit(_t(s, VITALTYPE, KGSLOT))
            emit(_t(s, HAS_SLOT_TYPE,
                    f"<{NS}:slot_type:{'Note' if tag == 'c' else 'Ref'}>"))
            se = f"<{NS}:edge:sl:{tag}{i}>"
            emit(_t(se, VITALTYPE, E_SLOT))
            emit(_t(se, EDGE_SOURCE, frame))
            emit(_t(se, EDGE_DEST, s))
            n_slots += 1
            if tag == "c":
                emit(_t(s, HAS_TEXT_VALUE, _lit(f"note {i}")))
                n_text += 1
            else:
                tgt = (rng.choice(value_hubs)
                       if rng.random() < ENTITY_VALUE_HUB_BIAS
                       else rng.randrange(n_persons))
                emit(_t(s, HAS_ENTITY_VALUE, person[tgt]))
                value_in[tgt] = value_in.get(tgt, 0) + 1
                n_entity_vals += 1

    (out_dir / "kg_rel_0001.nt").write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")

    pop = {"friendOf": n_persons, "mentions": n_persons,
           "reportsTo": n_persons, "worksFor": n_persons}
    pop_in = {"friendOf": n_persons, "mentions": n_persons,
              "reportsTo": n_persons, "worksFor": n_companies}

    manifest = {
        "n_entities": entities,
        "n_persons": n_persons,
        "n_companies": n_companies,
        "n_triples": len(lines),
        "seed": seed,
        "small_world": {"k_neighbours": K_NEIGHBOURS, "rewire_p": REWIRE_P},
        "frames": {"assertion_explicit": n_assert_set,
                   "assertion_unset": n_assert_unset,
                   "aspect": n_aspect,
                   "aspect_under_entity": n_aspect_entity,
                   "aspect_under_assertion": n_aspect_assertion},
        "slots": {"total": n_slots, "text_values": n_text,
                  "entity_values": n_entity_vals},
        "relations": {
            "total": rel_seq[0],
            # Per RELATION TYPE, both directions. Pooling these by edge type
            # averages a tree (reportsTo, backward 1) with a hub (worksFor,
            # backward = company size) into a number describing neither.
            "by_type": {
                t: {"out_degree": _degree(per_type_out.get(t, {}), pop[t]),
                    "in_degree": _degree(per_type_in.get(t, {}), pop_in[t])}
                for t in sorted(pop)
            },
        },
        "entity_value_in_degree": _degree(value_in, n_persons),
        "form_types": {"assertion": f"{KG}KGFormType_Assertion",
                       "aspect": f"{KG}KGFormType_Aspect"},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="internal_data/kg_rel")
    ap.add_argument("--entities", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20260810)
    a = ap.parse_args()

    m = generate(Path(a.out), a.entities, a.seed)
    print(f"✅ {m['n_triples']:,} triples — {m['n_persons']:,} persons, "
          f"{m['n_companies']:,} companies -> {a.out}")
    print(f"   frames: {m['frames']['assertion_explicit']:,} assertion "
          f"(+{m['frames']['assertion_unset']:,} unset), "
          f"{m['frames']['aspect']:,} aspect")
    print(f"   relations: {m['relations']['total']:,}")
    for t, d in m["relations"]["by_type"].items():
        o, i = d["out_degree"], d["in_degree"]
        print(f"     {t:<10} out avg {o['avg']:>6} max {o['max']:>5}"
              f"   | in avg {i['avg']:>6} max {i['max']:>5}")
    v = m["entity_value_in_degree"]
    print(f"   entity-valued slot targets: avg {v['avg']} max {v['max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
