#!/usr/bin/env python
"""Generate a fixture containing KG RELATIONS and both frame form types.

Why this exists
---------------
Every performance fixture is tree-shaped. `sp_lead_synth_100k` holds only
containment edges — Edge_hasKGSlot, Edge_hasKGFrame, Edge_hasEntityKGFrame — and
`wordnet_frames` only Edge_hasKGSlot. Neither has a single relation edge, which
matches `issues/043`/`048`: `build_relation_query` requires Edge_hasKGRelation
and it has zero instances anywhere outside a handful of tiny test spaces holding
96 of them.

That matters because traversal cost is decided by FAN-OUT, and fan-out is a
property of the edge kind (`issues/061`). Measured:

    edge kind                         forward           backward
    containment (Edge_hasKGSlot)      avg 2.00 max 2    avg 1.00 max 1
    slot value (hasEntitySlotValue)   avg 1.00 max 1    avg 5.20 max 1,342

Containment is a tree — a slot has exactly one parent, a frame none or one — so
walking it backward never amplifies. On the tree-shaped fixtures alone, "always
traverse backward" looks unconditionally correct. It is not: on a slot-value hop
the safe direction is forward, and backward hits 1,342x.

Relations are the case with **no safe direction at all**. An entity may be source
or destination in many, so both directions fan out. A direction-choosing rewrite
validated only against the existing fixtures would ship a rule that is wrong here
and no test would notice.

What this generates
-------------------
* **Entities** — plain KGEntity anchors.
* **Assertion frames** — top-level, no parent, `hasKGFormType KGFormType_Assertion`.
  A fraction leave the property UNSET, because unset defaults to assertion and a
  fixture where the default is never exercised cannot catch a reader that
  requires the explicit triple.
* **Aspect frames** — `hasKGFormType KGFormType_Aspect`, attached either to an
  entity (Edge_hasEntityKGFrame) or beneath an assertion (Edge_hasKGFrame), so
  both parent kinds appear.
* **Slots** on frames, including `hasEntitySlotValue` pointing at entities with a
  SKEWED target distribution, reproducing the many-to-one shape wordnet has.
* **Relations** — Edge_hasKGRelation with hasEdgeSource / hasEdgeDestination both
  entities, a hasKGRelationType, and a skewed degree distribution in both roles.

Skew is the point. A uniform degree would make average and tail agree, and the
whole reason fan-out needs recording is that they do not: wordnet's slot-value
in-degree averages 5.20 with a maximum of 1,342, so a plan chosen on the mean can
be 250x off. This fixture is generated with hubs so a bench can tell a
tail-aware cost model from a mean-based one.

The manifest records the exact degree distributions, so a test can assert them
rather than recompute them from the data it is meant to be checking.

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

RELATION_TYPES = ["knows", "worksWith", "reportsTo", "mentions"]

# One assertion frame in this many omits hasKGFormType entirely. Unset defaults
# to assertion, and a fixture that always states it cannot catch a reader that
# requires the explicit triple.
FORM_TYPE_UNSET_EVERY = 4

# Relation degree. Most entities get a few; HUB_FRACTION of them get a large
# number, so the distribution has the heavy tail that makes a mean useless.
BASE_REL_DEGREE = (0, 1, 2, 3)
HUB_FRACTION = 0.01
HUB_REL_DEGREE = (40, 120, 400)

# Destinations are skewed too, and separately from sources. A first version drew
# them uniformly, which gave out-degree a max of 400 and in-degree a max of 12 —
# so the fixture had a tail in one direction only and would have let a rewrite
# that always drives from the destination side look safe. Real relation graphs
# are preferentially attached in both roles: some entities are popular targets.
REL_DEST_HUB_FRACTION = 0.005
REL_DEST_HUB_BIAS = 0.55

# Slot values that point at entities. Targets are drawn from a small hub set most
# of the time, so in-degree is skewed the way wordnet's is: there, in-degree
# averages 5.20 with a maximum of 1,342 — a 258x mean-to-max ratio. A hub set of
# a few thousandths of the population reproduces that order; 2% did not, giving
# a max of only 49.
ENTITY_VALUE_HUB_FRACTION = 0.002
ENTITY_VALUE_HUB_BIAS = 0.75


def _t(s: str, p: str, o: str) -> str:
    return f"{s} {p} {o} ."


def _lit(v: str) -> str:
    esc = v.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'


def _pct(values, q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * (len(ordered) - 1)))
    return ordered[idx]


def _degree_stats(counts: dict, population: int) -> dict:
    """Degree distribution including the zeros, which are part of the shape."""
    vals = list(counts.values()) + [0] * max(0, population - len(counts))
    total = sum(vals)
    return {
        "total": total,
        "avg": round(total / len(vals), 3) if vals else 0,
        "p50": _pct(vals, 0.50),
        "p99": _pct(vals, 0.99),
        "max": max(vals) if vals else 0,
        "nonzero": len([v for v in vals if v]),
    }


def generate(out_dir: Path, entities: int, seed: int) -> dict:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "kg_rel_0001.nt"

    ent = [f"<{NS}:entity:{i}>" for i in range(entities)]
    hubs = set(rng.sample(range(entities),
                          max(1, int(entities * HUB_FRACTION))))
    value_hubs = rng.sample(range(entities),
                            max(1, int(entities * ENTITY_VALUE_HUB_FRACTION)))
    dest_hubs = rng.sample(range(entities),
                           max(1, int(entities * REL_DEST_HUB_FRACTION)))

    rel_out: dict[int, int] = {}
    rel_in: dict[int, int] = {}
    value_in: dict[int, int] = {}
    n_assertion = n_assertion_unset = n_aspect = 0
    n_aspect_under_entity = n_aspect_under_assertion = 0
    n_slots = n_entity_values = n_text_values = 0
    rel_by_type: dict[str, int] = {}

    lines: list[str] = []
    emit = lines.append

    for i in range(entities):
        e = ent[i]
        emit(_t(e, VITALTYPE, KGENTITY))
        emit(_t(e, HAS_ENTITY_TYPE, f"<{NS}:entity_type:Person>"))

        # --- one assertion frame (top-level, no parent) ---
        af = f"<{NS}:frame:assert:{i}>"
        emit(_t(af, VITALTYPE, KGFRAME))
        emit(_t(af, HAS_FRAME_TYPE, f"<{NS}:frame_type:Profile>"))
        if i % FORM_TYPE_UNSET_EVERY:
            emit(_t(af, HAS_FORM_TYPE, FORM_ASSERTION))
            n_assertion += 1
        else:
            n_assertion_unset += 1   # unset: defaults to assertion

        # --- an aspect frame enclosed by the entity ---
        pf = f"<{NS}:frame:aspect:e{i}>"
        emit(_t(pf, VITALTYPE, KGFRAME))
        emit(_t(pf, HAS_FRAME_TYPE, f"<{NS}:frame_type:Contact>"))
        emit(_t(pf, HAS_FORM_TYPE, FORM_ASPECT))
        ee = f"<{NS}:edge:ef:{i}>"
        emit(_t(ee, VITALTYPE, E_ENTITY_FRAME))
        emit(_t(ee, EDGE_SOURCE, e))
        emit(_t(ee, EDGE_DEST, pf))
        n_aspect += 1
        n_aspect_under_entity += 1

        # --- an aspect frame beneath the assertion (frame -> frame) ---
        cf = f"<{NS}:frame:aspect:a{i}>"
        emit(_t(cf, VITALTYPE, KGFRAME))
        emit(_t(cf, HAS_FRAME_TYPE, f"<{NS}:frame_type:Detail>"))
        emit(_t(cf, HAS_FORM_TYPE, FORM_ASPECT))
        fe = f"<{NS}:edge:ff:{i}>"
        emit(_t(fe, VITALTYPE, E_FRAME))
        emit(_t(fe, EDGE_SOURCE, af))
        emit(_t(fe, EDGE_DEST, cf))
        n_aspect += 1
        n_aspect_under_assertion += 1

        # --- slots: one text, one pointing at an entity ---
        for frame, tag in ((pf, "c"), (cf, "d")):
            s = f"<{NS}:slot:{tag}{i}>"
            emit(_t(s, VITALTYPE, KGSLOT))
            emit(_t(s, HAS_SLOT_TYPE, f"<{NS}:slot_type:{'Note' if tag == 'c' else 'Ref'}>"))
            se = f"<{NS}:edge:sl:{tag}{i}>"
            emit(_t(se, VITALTYPE, E_SLOT))
            emit(_t(se, EDGE_SOURCE, frame))
            emit(_t(se, EDGE_DEST, s))
            n_slots += 1
            if tag == "c":
                emit(_t(s, HAS_TEXT_VALUE, _lit(f"note {i}")))
                n_text_values += 1
            else:
                # Skewed: most references land on a small hub set, which is what
                # gives the target in-degree its heavy tail.
                if rng.random() < ENTITY_VALUE_HUB_BIAS:
                    tgt = rng.choice(value_hubs)
                else:
                    tgt = rng.randrange(entities)
                emit(_t(s, HAS_ENTITY_VALUE, ent[tgt]))
                value_in[tgt] = value_in.get(tgt, 0) + 1
                n_entity_values += 1

        # --- relations: entity -> entity, skewed degree ---
        degree = (rng.choice(HUB_REL_DEGREE) if i in hubs
                  else rng.choice(BASE_REL_DEGREE))
        for k in range(degree):
            # Skewed destination, independently of the source's degree.
            dst = (rng.choice(dest_hubs) if rng.random() < REL_DEST_HUB_BIAS
                   else rng.randrange(entities))
            if dst == i:
                continue
            rtype = RELATION_TYPES[(i + k) % len(RELATION_TYPES)]
            re_uri = f"<{NS}:edge:rel:{i}:{k}>"
            emit(_t(re_uri, VITALTYPE, E_RELATION))
            emit(_t(re_uri, URIPROP, _lit(f"{NS}:edge:rel:{i}:{k}")))
            emit(_t(re_uri, EDGE_SOURCE, e))
            emit(_t(re_uri, EDGE_DEST, ent[dst]))
            emit(_t(re_uri, HAS_RELATION_TYPE, f"<{NS}:rel_type:{rtype}>"))
            rel_out[i] = rel_out.get(i, 0) + 1
            rel_in[dst] = rel_in.get(dst, 0) + 1
            rel_by_type[rtype] = rel_by_type.get(rtype, 0) + 1

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest = {
        "n_entities": entities,
        "n_triples": len(lines),
        "seed": seed,
        "frames": {
            "assertion_explicit": n_assertion,
            "assertion_unset": n_assertion_unset,
            "aspect": n_aspect,
            "aspect_under_entity": n_aspect_under_entity,
            "aspect_under_assertion": n_aspect_under_assertion,
        },
        "slots": {"total": n_slots,
                  "text_values": n_text_values,
                  "entity_values": n_entity_values},
        "relations": {
            "total": sum(rel_by_type.values()),
            "by_type": dict(sorted(rel_by_type.items())),
            # Both roles, because a relation fans out in BOTH directions and a
            # direction-choosing rewrite has to be judged against both.
            "out_degree": _degree_stats(rel_out, entities),
            "in_degree": _degree_stats(rel_in, entities),
        },
        # The whole point of the fixture: an edge kind whose backward fan-out is
        # not 1, so "always traverse backward" is refutable here.
        "entity_value_in_degree": _degree_stats(value_in, entities),
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
    print(f"✅ {m['n_triples']:,} triples for {m['n_entities']:,} entities "
          f"-> {a.out}")
    print(f"   frames: {m['frames']['assertion_explicit']:,} assertion "
          f"(+{m['frames']['assertion_unset']:,} unset), "
          f"{m['frames']['aspect']:,} aspect")
    r = m["relations"]
    print(f"   relations: {r['total']:,}  out-degree avg {r['out_degree']['avg']} "
          f"p99 {r['out_degree']['p99']} max {r['out_degree']['max']}")
    print(f"                        in-degree  avg {r['in_degree']['avg']} "
          f"p99 {r['in_degree']['p99']} max {r['in_degree']['max']}")
    v = m["entity_value_in_degree"]
    print(f"   entity-valued slot targets: avg {v['avg']} p99 {v['p99']} "
          f"max {v['max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
