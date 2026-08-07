#!/usr/bin/env python
"""Convert a VitalSigns Block file (.vital / .vital.bz2) to N-Triples.

Why this exists: the `.nt` exports in test_data/ are lossy — they carry
`rdf:type` but not `vital-core#vitaltype`, which is exactly what the KG fast
paths filter on. The `.vital` block file carries `vitaltype` on every object
(1,536,485 of them for kgframe-wordnet-0.0.1), matching the reference space.
Converting from the block file therefore produces a faithful dataset; loading
the `.nt` does not.

Uses the VitalSigns block API, on the fast triples path:

    GraphObject.from_json_triples(line)  ->  [(s, p, o), ...]

which emits triples straight from each object's JSON without instantiating
GraphObjects.

    python scripts/convert_vital_to_ntriples.py \\
        test_data/kgframe-wordnet-0.0.1.vital test_data/kgframe-wordnet-0.0.1.vt.nt

Note: `VitalBlockReader(..., triples_only=True)` does not work in VitalSigns
0.1.53 — `__iter__` builds `VitalBlock(current_block)` without forwarding the
flag, so `triple_list` is never set and `get_triples()` raises AttributeError.
We read the block lines and call `from_json_triples` per object instead, which
is the same code path the flag was meant to select.
"""

from __future__ import annotations

import argparse
import bz2
import sys
import time

from rdflib.term import Literal, URIRef, BNode


def _open(path: str):
    return bz2.open(path, "rt", encoding="utf-8") if path.endswith(".bz2") \
        else open(path, "rt", encoding="utf-8")


def _nt_term(t) -> str:
    """Serialize one rdflib term in N-Triples form."""
    if isinstance(t, URIRef):
        return f"<{t}>"
    if isinstance(t, BNode):
        return f"_:{t}"
    if isinstance(t, Literal):
        # Escape per N-Triples: backslash, quote, newline, carriage return, tab.
        s = (str(t).replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
        if t.language:
            return f'"{s}"@{t.language}'
        if t.datatype:
            return f'"{s}"^^<{t.datatype}>'
        return f'"{s}"'
    return f'"{t}"'


def convert(src: str, dst: str, limit: int | None = None,
            progress_every: int = 200_000) -> tuple[int, int]:
    from vital_ai_vitalsigns.model.GraphObject import GraphObject

    objects = 0
    triples = 0
    t0 = time.time()

    with _open(src) as fin, open(dst, "w", encoding="utf-8") as fout:
        after_header = False
        for line in fin:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if not after_header:
                # Header is `jsonl 1.0.0` then a `|` block separator.
                if s == "|":
                    after_header = True
                continue
            if s == "|":            # block separator
                continue

            for (subj, pred, obj) in GraphObject.from_json_triples(s):
                fout.write(f"{_nt_term(subj)} {_nt_term(pred)} {_nt_term(obj)} .\n")
                triples += 1
            objects += 1

            if progress_every and objects % progress_every == 0:
                el = time.time() - t0
                print(f"  {objects:,} objects, {triples:,} triples "
                      f"({objects / el:,.0f} obj/s)", file=sys.stderr)
            if limit and objects >= limit:
                break

    el = time.time() - t0
    print(f"✅ {objects:,} objects → {triples:,} triples in {el:.1f}s "
          f"({triples / max(el, 0.001):,.0f} triples/s) → {dst}", file=sys.stderr)
    return objects, triples


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="input .vital / .vital.bz2")
    ap.add_argument("dst", help="output .nt")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N objects (for timing runs)")
    args = ap.parse_args()
    convert(args.src, args.dst, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
