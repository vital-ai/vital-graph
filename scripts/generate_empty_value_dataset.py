"""Generate a lead fixture where some slots EXIST but have NO VALUE (issues/052).

Why this exists
---------------
`is_empty` asks for slots that are present but unvalued. In every generated
fixture that set is empty: **0 of 387,700 slots lack a value**, because the
generator emits a value for every slot it emits. So `is_empty` returns nothing,
`not_exists` returns nothing, and any test over them passes while comparing
empty sets to empty sets.

That is not hypothetical. While fixing issues/052 three separate comparisons
"matched" with both sides returning zero rows, and a change to SPARQL join
semantics nearly shipped on that evidence.

Variance is the point, not merely presence. A slot that is empty for *every*
entity answers `is_empty` with everything, which is just as degenerate as
answering with nothing — a query returning all rows exercises no selectivity and
a wrong join can still look right. This leaves the chosen slot valued for most
entities and unvalued for a controlled fraction, so the correct answer is a
specific number that a wrong implementation will miss.

A boolean slot is used by default. Booleans have the smallest value domain, so a
mistake that confuses "no value" with "value false" shows up here and would hide
in a text slot.

Usage
-----
    python scripts/generate_empty_value_dataset.py --out internal_data/lead_empty \\
        --entities 1000 --slot MQLv2 --empty-every 3

    python scripts/convert_nt_to_csv.py internal_data/lead_empty/lead_syn_*.nt \\
        --out test_data/lead_empty.csv --graph urn:lead_empty --dataset lead_empty
    # then create the space and load, as in load_duplicate_quad_dataset.sh

The manifest records how many slots were emptied, so a bench can assert the
exact expected count rather than "more than zero".
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

_SUBJ_RE = re.compile(r"^<([^>]+)>")
# Any of the typed value predicates; which one applies depends on the slot class.
_VALUE_PRED_RE = re.compile(r"#has\w*SlotValue>")


def empty_slots(out_dir: Path, slot: str, every: int) -> dict:
    """Drop the value triple from every Nth occurrence of `slot`.

    The slot node itself, its type triple and its edge from the frame all stay:
    `is_empty` means "the slot is there and holds nothing", so removing the slot
    entirely would test `not_exists` instead and leave `is_empty` still empty.
    """
    needle = f":slot:{slot.lower()}"
    seen: dict[str, int] = {}
    emptied = 0
    kept_values = 0

    for shard in sorted(out_dir.glob("lead_syn_*.nt")):
        out = []
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            m = _SUBJ_RE.match(line)
            subj = m.group(1) if m else ""
            if needle not in subj.lower() or not _VALUE_PRED_RE.search(line):
                out.append(line)
                continue
            idx = seen.setdefault(subj, len(seen))
            if idx % every == 0:
                emptied += 1          # drop this value triple
                continue
            kept_values += 1
            out.append(line)
        shard.write_text("\n".join(out) + "\n", encoding="utf-8")

    return {
        "slot": slot,
        "empty_every": every,
        "slots_emptied": emptied,
        "slots_still_valued": kept_values,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template-dir", default="internal_data/lead_test_data")
    ap.add_argument("--out", default="internal_data/lead_empty")
    ap.add_argument("--entities", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260809)
    ap.add_argument("--slot", default="MQLv2",
                    help="slot local name to empty; a boolean by default")
    ap.add_argument("--empty-every", type=int, default=3,
                    help="empty every Nth occurrence, leaving the rest valued")
    ap.add_argument("--mql-true-rate", type=float, default=0.5)
    ap.add_argument("--templates", type=int, default=None)
    a = ap.parse_args()

    out_dir = Path(a.out)
    rc = generate(Path(a.template_dir), out_dir, a.entities, a.seed,
                  trim=True, shard_entities=max(a.entities, 1),
                  mql_true_rate=a.mql_true_rate, templates_limit=a.templates)
    if rc:
        return rc

    info = empty_slots(out_dir, a.slot, a.empty_every)
    print(f"\n🕳  {a.slot}: {info['slots_emptied']:,} slots emptied, "
          f"{info['slots_still_valued']:,} still valued")

    if not info["slots_emptied"] or not info["slots_still_valued"]:
        print("❌ need BOTH empty and valued slots — an all-or-nothing split "
              "answers is_empty degenerately and tests nothing", file=sys.stderr)
        return 1

    mp = out_dir / "manifest.json"
    manifest = json.loads(mp.read_text())
    manifest["empty_values"] = info
    mp.write_text(json.dumps(manifest, indent=2))
    print(f"📄 manifest: {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
