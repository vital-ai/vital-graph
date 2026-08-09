#!/usr/bin/env python
"""Generate a lead fixture that contains DUPLICATE ANCHOR QUADS (issues/046).

Why this exists as a separate dataset
-------------------------------------
`generate_lead_dataset.py` emits every triple exactly once, so in every fixture
built from it each entity has exactly one `vitaltype KGEntity` row and one
`hasKGEntityType` row. That makes the semi-join's DISTINCT elision *sound on
that data* — which is precisely why the elision shipped and why the benches
passed while returning 34,659 rows for 34,423 entities on production data.

`rdf_quad`'s primary key is `(subject, predicate, object, context, quad_uuid)`
and `quad_uuid` defaults to `gen_random_uuid()`, so the same triple written
twice becomes two rows. Production has them: 82 subjects carried the anchor quad
more than once, contributing 236 extra rows. No generated fixture could express
that, so no assertion over the generated fixtures can regress the bug.

This produces a small dataset that does, keeping the entity → frame → slot shape
of the lead fixtures so the existing bench criteria work against it unchanged.

What is duplicated
------------------
Only the two ANCHOR triples of an entity:

    <entity> <vital-core#vitaltype>      <haley-ai-kg#KGEntity> .
    <entity> <haley-ai-kg#hasKGEntityType> <urn:acme:kg:entity:Lead> .

Those are what the semi-join's outer side scans — the generic anchor and the
specific one respectively — so duplicating them is what exercises the defect on
both paths (issues/045 covers the specific-type path). Frame and slot triples
are left alone: duplicating those would test the probe side, which EXISTS makes
insensitive to multiplicity by construction, and would muddy the manifest's
match counts.

Multiplicity varies (2x, 3x, 4x) rather than being uniform, so an off-by-one in
deduplication shows up as a wrong count rather than a coincidentally right one.

Usage
-----
    python scripts/generate_duplicate_quad_dataset.py \\
        --out internal_data/lead_dup --entities 500

    python scripts/convert_nt_to_csv.py internal_data/lead_dup/lead_syn_*.nt \\
        --out test_data/lead_dup.csv --graph urn:lead_dup --dataset lead_dup

    python scripts/load_wordnet_csv.py --csv test_data/lead_dup.csv \\
        --space sp_lead_dup --graph urn:lead_dup

The manifest records how many entities were duplicated and how many extra rows
that produced, so a test can assert the fixture is actually non-degenerate
before trusting a "no duplicates in the result" pass. A duplicate-detection test
against a fixture with no duplicates is exactly the vacuous check that let
issues/046 through.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_lead_dataset import generate  # noqa: E402

VITALTYPE = "<http://vital.ai/ontology/vital-core#vitaltype>"
KGENTITY = "<http://vital.ai/ontology/haley-ai-kg#KGEntity>"
HAS_ENTITY_TYPE = "<http://vital.ai/ontology/haley-ai-kg#hasKGEntityType>"

# 2, 3, 4 copies in rotation. Production's duplicated subjects averaged ~2.9
# extra rows each, so this lands in the same neighbourhood without pretending to
# a precision the shape does not have.
COPIES = (2, 3, 4)


def _is_anchor(line: str) -> bool:
    """Is this one of the entity's own two anchor triples?

    Matched on predicate+object rather than on the subject, because the subject
    is an entity URI whose form the template controls. Frame and slot subjects
    carry `vitaltype` too — with a different object — so the object test is what
    keeps this to the anchors.
    """
    if VITALTYPE in line and KGENTITY in line:
        return True
    return HAS_ENTITY_TYPE in line


def duplicate_anchors(out_dir: Path, every: int) -> dict:
    """Rewrite the shards in place, duplicating anchors of every Nth entity.

    Returns the tally for the manifest. Entities are identified by the subject
    of their anchor triples, so selection does not depend on shard boundaries or
    on the order the generator happened to emit.
    """
    entity_index: dict[str, int] = {}
    multiplicity: dict[str, int] = {}
    extra_rows = 0

    for shard in sorted(out_dir.glob("lead_syn_*.nt")):
        rewritten = []
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rewritten.append(line)
            if not _is_anchor(line):
                continue
            subject = line.split(" ", 1)[0]
            if subject not in entity_index:
                entity_index[subject] = len(entity_index)
            idx = entity_index[subject]
            if idx % every:
                continue
            copies = COPIES[(idx // every) % len(COPIES)]
            multiplicity[subject] = copies
            # copies TOTAL rows, so copies-1 extra beyond the one just written
            rewritten.extend([line] * (copies - 1))
            extra_rows += copies - 1
        shard.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    by_copies: dict[int, int] = {}
    for c in multiplicity.values():
        by_copies[c] = by_copies.get(c, 0) + 1

    return {
        "duplicated_entities": len(multiplicity),
        "extra_anchor_rows": extra_rows,
        "entities_by_copy_count": {str(k): v for k, v in sorted(by_copies.items())},
        "duplicate_every": every,
        "anchor_predicates": ["vital-core#vitaltype -> haley-ai-kg#KGEntity",
                              "haley-ai-kg#hasKGEntityType"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template-dir", default="internal_data/lead_test_data")
    ap.add_argument("--out", default="internal_data/lead_dup")
    ap.add_argument("--entities", type=int, default=500,
                    help="small on purpose — this fixture tests a correctness "
                         "property, not a cost curve")
    ap.add_argument("--seed", type=int, default=20260808)
    ap.add_argument("--duplicate-every", type=int, default=5,
                    help="duplicate the anchors of every Nth entity")
    ap.add_argument("--mql-true-rate", type=float, default=0.5)
    ap.add_argument("--templates", type=int, default=None)
    args = ap.parse_args()

    out_dir = Path(args.out)
    rc = generate(Path(args.template_dir), out_dir, args.entities, args.seed,
                  trim=True, shard_entities=max(args.entities, 1),
                  mql_true_rate=args.mql_true_rate,
                  templates_limit=args.templates)
    if rc:
        return rc

    print(f"\n🔁 duplicating anchor quads for every {args.duplicate_every}th entity")
    dup = duplicate_anchors(out_dir, args.duplicate_every)

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["duplicate_quads"] = dup
    manifest["n_triples"] += dup["extra_anchor_rows"]
    manifest_path.write_text(json.dumps(manifest, indent=2))

    if not dup["duplicated_entities"]:
        print("❌ no anchors were duplicated — the fixture would be degenerate "
              "and any test over it vacuous", file=sys.stderr)
        return 1

    print(f"   {dup['duplicated_entities']:,} entities duplicated, "
          f"{dup['extra_anchor_rows']:,} extra anchor rows "
          f"({dup['entities_by_copy_count']})")
    print(f"📄 manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
