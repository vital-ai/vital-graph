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

# The chain to flatten. Chosen because the growth-curve benches already filter
# on CompanyStateCode, so the depth-1 fixture answers the same criteria.
PARENT = "companyframe"
CHILD = "companyaddressframe"

_SUBJ_RE = re.compile(r"^<([^>]+)>")


def flatten(out_dir: Path, every: int) -> dict:
    """Promote CHILD out from under PARENT for every Nth entity, in place."""
    nested = f":frame:{PARENT}:0:frame:{CHILD}:0"
    promoted = f":frame:{CHILD}:0"
    parent_prefix = f":frame:{PARENT}:0"

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
            if ent.startswith("urn:acme:lead:"):
                if ent not in entity_index:
                    entity_index[ent] = len(entity_index)
                selected = entity_index[ent] % every == 0
            else:
                selected = False

            if not selected or nested not in line and parent_prefix not in line:
                keep.append(line)
                continue

            flattened.add(ent)

            # The child and everything under it moves up a level.
            if nested in line:
                keep.append(line.replace(nested, promoted))
                continue

            # What remains touches the parent frame. Only the edge that carried
            # parent -> child changes, becoming entity -> child. The parent
            # itself STAYS: it has three other children
            # (companyfinancial/identity/operations), and dropping everything
            # under its prefix deleted those too — 46,300 triples per 500
            # entities, silently. Re-parenting one child must not disturb its
            # siblings, or the fixture measures different data rather than the
            # same data at a different depth.
            if f"{parent_prefix}:edge:to_{CHILD}" in subj:
                line = line.replace(nested, promoted)
                if line.endswith(f"{HAS_KG_FRAME} ."):
                    line = line.replace(HAS_KG_FRAME, HAS_ENTITY_FRAME)
                    rewired += 1
                elif EDGE_SOURCE in line:
                    line = re.sub(r"<[^>]*:frame:%s:0>" % PARENT, f"<{ent}>", line)
                keep.append(line)
                continue

            keep.append(line)                 # parent frame and its siblings

        shard.write_text("\n".join(keep) + "\n", encoding="utf-8")

    return {
        "flattened_entities": len(flattened),
        "edges_rewired_to_entity": rewired,
        "flatten_every": every,
        "chain": f"{PARENT} -> {CHILD}",
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
