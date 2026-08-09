"""Generate a lead fixture containing DEPTH-1 frame chains (issues/050).

Why this exists
---------------
Slot URIs encode frame containment, so nesting depth is directly countable.
Measured on a restored production space against the 10k fixture:

    frame depth                        production        10k fixture
    1  entity -> frame -> slot       1,364,214 (98.0%)            0
    2  entity -> frame -> frame -> slot  26,134 (1.9%)      387,700 (all)
    3                                     1,141 (0.08%)            0

The fixture is uniformly depth 2 and contains no depth-1 chain at all, so it
cannot exercise the shape that is 98% of production. This is not a scale
problem: `generate_lead_dataset.py` clones template graphs that happen to be
uniformly depth 2, so generating more entities produces more depth-2 chains.

Depth is not cosmetic. It sets the join count, and join reduction is the
mechanism the edge table, frame_entity and the covering indexes all rely on:

    depth   quad joins, edge rewrite ON   OFF
    1                                 6    10
    2                                 8    14

So the shape carrying almost all production traffic is where the edge table's
benefit is realised, and it is the one no benchmark runs.

What this does
--------------
Promotes a child frame to attach directly to the entity, for a chosen fraction
of entities:

    entity --Edge_hasEntityKGFrame--> CompanyFrame
           --Edge_hasKGFrame-------->   CompanyAddressFrame --> slot   (depth 2)

becomes

    entity --Edge_hasEntityKGFrame--> CompanyAddressFrame --> slot     (depth 1)

The child frame keeps its type, its slots and their values, so criteria that
addressed it as a nested frame still address it — at one level less. That
matters: the point is to vary depth while holding the data constant, so a
depth-1 and a depth-2 measurement differ in shape and nothing else.

The parent frame stays. It has three other children
(companyfinancial/identity/operations), and an earlier revision that dropped
everything under its prefix deleted those as well — 46,300 triples per 500
entities, silently. Re-parenting one child must leave its siblings untouched,
or the fixture measures different data rather than the same data at a
different depth. Slot count is identical before and after; only depth moves.

Usage
-----
    python scripts/generate_depth_mix_dataset.py --out internal_data/lead_depth1 \\
        --entities 2000 --flatten-every 1

    python scripts/convert_nt_to_csv.py internal_data/lead_depth1/lead_syn_*.nt \\
        --out test_data/lead_depth1.csv --graph urn:lead_depth1 --dataset lead_depth1
    # then create the space and load, as in load_duplicate_quad_dataset.sh

`--flatten-every 1` produces an all-depth-1 fixture, which is the useful
counterpart to the existing all-depth-2 one. A mixed fixture (say every other
entity) is available via larger values, but two clean fixtures compare more
sharply than one blended one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_lead_dataset import generate  # noqa: E402

HAS_ENTITY_FRAME = "<http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame>"
HAS_KG_FRAME = "<http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame>"
EDGE_SOURCE = "<http://vital.ai/ontology/vital-core#hasEdgeSource>"

# Every parent -> child chain is flattened, not one named pair. A fixture that
# is depth 1 for the Company chain and depth 2 everywhere else is not a depth-1
# fixture — it is a mixture that makes every non-Company cell vacuous, which is
# exactly what the first version produced.
_NESTED_RE = re.compile(r":frame:(\w+):0:frame:(\w+):0")
_PARENT_EDGE_RE = re.compile(r"^(urn:acme:lead:[A-Za-z0-9]+):frame:(\w+):0:edge:to_(\w+)$")
_SUBJ_RE = re.compile(r"^<([^>]+)>")


def flatten(out_dir: Path, every: int) -> dict:
    """Promote every child frame to attach directly to its entity."""
    entity_index: dict[str, int] = {}
    flattened: set[str] = set()
    rewired = 0

    for shard in sorted(out_dir.glob("lead_syn_*.nt")):
        keep: list[str] = []
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            m = _SUBJ_RE.match(line)
            subj = m.group(1) if m else ""
            ent = subj.split(":frame:")[0].split(":edge:")[0]
            if not ent.startswith("urn:acme:lead:"):
                keep.append(line)
                continue
            if ent not in entity_index:
                entity_index[ent] = len(entity_index)
            if entity_index[ent] % every:
                keep.append(line)
                continue

            # Collapse every nested pair, repeatedly, so a depth-3 chain lands
            # at depth 1 rather than 2.
            new = line
            while True:
                collapsed = _NESTED_RE.sub(r":frame:\2:0", new)
                if collapsed == new:
                    break
                new = collapsed
            if new != line:
                flattened.add(ent)

            # A parent -> child edge now points entity -> child, so it has to
            # become an entity-frame edge and be sourced from the entity. Its
            # own URI keeps the parent segment; that is just its identity.
            pm = _PARENT_EDGE_RE.match(subj)
            if pm:
                if new.rstrip().endswith(f"{HAS_KG_FRAME} ."):
                    new = new.replace(HAS_KG_FRAME, HAS_ENTITY_FRAME)
                    rewired += 1
                elif EDGE_SOURCE in new:
                    new = re.sub(r"<%s:frame:\w+:0>" % re.escape(ent),
                                 f"<{ent}>", new)
            keep.append(new)

        shard.write_text("\n".join(keep) + "\n", encoding="utf-8")

    return {
        "flattened_entities": len(flattened),
        "edges_rewired_to_entity": rewired,
        "flatten_every": every,
        "chain": "all parent -> child chains",
    }


def verify(out_dir: Path) -> dict:
    """Count slot URIs by frame depth — the property this fixture exists for."""
    depths: dict[int, int] = {}
    for shard in sorted(out_dir.glob("lead_syn_*.nt")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            m = _SUBJ_RE.match(line)
            if not m or ":slot:" not in m.group(1):
                continue
            d = m.group(1).count(":frame:")
            depths[d] = depths.get(d, 0) + 1
    return {str(k): v for k, v in sorted(depths.items())}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template-dir", default="internal_data/lead_test_data")
    ap.add_argument("--out", default="internal_data/lead_depth1")
    ap.add_argument("--entities", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260808)
    ap.add_argument("--flatten-every", type=int, default=1,
                    help="1 = flatten every entity (all depth 1)")
    ap.add_argument("--mql-true-rate", type=float, default=0.5)
    ap.add_argument("--templates", type=int, default=None)
    a = ap.parse_args()

    out_dir = Path(a.out)
    rc = generate(Path(a.template_dir), out_dir, a.entities, a.seed,
                  trim=True, shard_entities=max(a.entities, 1),
                  mql_true_rate=a.mql_true_rate, templates_limit=a.templates)
    if rc:
        return rc

    before = verify(out_dir)
    print(f"\n📐 slot depth before flattening: {before}")
    info = flatten(out_dir, a.flatten_every)
    after = verify(out_dir)
    print(f"📐 slot depth after  flattening: {after}")
    print(f"   {info['flattened_entities']:,} entities flattened, "
          f"{info['edges_rewired_to_entity']:,} edges rewired")

    mp = out_dir / "manifest.json"
    manifest = json.loads(mp.read_text())
    manifest["depth_mix"] = {**info, "slot_depth_before": before,
                             "slot_depth_after": after}
    mp.write_text(json.dumps(manifest, indent=2))

    if not after.get("1"):
        print("❌ no depth-1 slots produced — the fixture would not close the "
              "gap it exists for", file=sys.stderr)
        return 1
    print(f"📄 manifest: {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
