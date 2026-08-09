#!/usr/bin/env python
"""Convert N-Triples to the slim uuid-only CSVs that `load_wordnet_csv.py` COPYs.

The missing CLI for `test_scripts/import/test_csv_import_process.py`. That
module's `convert_ntriples_to_csv()` has always supported `uuid_only_quads`, but
its own `main()` hardcodes the input path, output path and graph URI, and passes
six positional arguments — stopping one short of the flag. So running it as
written always produced the 14-column form, which needs a staging table and an
`INSERT..SELECT` on load. On wordnet that cost 196s per load instead of 115s and
3.56 GB on disk instead of 1.35 GB.

This exposes the flag, defaults it on, and takes arguments, so every dataset
loads by the same bulk path:

    .nt  ──(this)──▶  slim CSV + terms CSV  ──(load_wordnet_csv.py)──▶  space

Multiple inputs are concatenated first, since the underlying converter reads a
single file and a generated dataset arrives as shards.

    # wordnet
    python scripts/convert_nt_to_csv.py test_data/kgframe-wordnet-0.0.1-vt.nt \\
        --out test_data/wordnet_frames.csv --graph urn:wordnet_frames \\
        --dataset wordnet_frames

    # generated lead fixture (sharded)
    python scripts/convert_nt_to_csv.py internal_data/lead_synth/lead_syn_*.nt \\
        --out test_data/lead_synth.csv --graph urn:sp_lead_synth_10k \\
        --dataset lead_synth

The terms CSV is written alongside as `<out-stem>_terms.csv`, which is the
naming `load_wordnet_csv.py` expects to be handed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test_scripts", "import"))


def concat(inputs: list[Path], dest: Path) -> int:
    """Concatenate shards into one .nt. Returns total bytes."""
    total = 0
    with open(dest, "wb") as out:
        for p in inputs:
            with open(p, "rb") as fh:
                shutil.copyfileobj(fh, out, 1024 * 1024)
            total += p.stat().st_size
    return total


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".nt file(s); concatenated in order")
    ap.add_argument("--out", required=True, help="quads CSV path")
    ap.add_argument("--graph", required=True, help="graph URI (context)")
    ap.add_argument("--dataset", required=True,
                    help="dataset identifier written into the CSVs")
    ap.add_argument("--full-14-column", action="store_true",
                    help="emit the legacy 14-column quads CSV with text values. "
                         "Human-readable, but needs a staging table on load. "
                         "Only for debugging an export.")
    a = ap.parse_args()

    inputs = [Path(p) for p in a.inputs]
    missing = [p for p in inputs if not p.is_file()]
    if missing:
        print(f"❌ missing input(s): {', '.join(map(str, missing))}",
              file=sys.stderr)
        return 2

    from test_csv_import_process import NTriplesCSVConverter

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = None
    try:
        if len(inputs) > 1:
            fd, tmp_path = tempfile.mkstemp(suffix=".nt", dir=str(out.parent))
            os.close(fd)
            tmp = Path(tmp_path)
            n_bytes = concat(inputs, tmp)
            print(f"🧩 concatenated {len(inputs)} shard(s) → "
                  f"{n_bytes / 1e9:.2f} GB")
            source = tmp
        else:
            source = inputs[0]

        print(f"🚀 {source.name} → {out.name} "
              f"({'14-column' if a.full_14_column else 'uuid-only'})")
        t0 = time.time()
        converter = NTriplesCSVConverter()
        converter.convert_ntriples_to_csv(
            str(source), str(out), a.graph, a.dataset,
            uuid_only_quads=not a.full_14_column,
        )
        dt = time.time() - t0
    finally:
        if tmp and tmp.exists():
            tmp.unlink()

    terms = out.parent / f"{out.stem}_terms.csv"
    print(f"\n🏁 {dt:.1f}s")
    print(f"   quads: {out}  ({out.stat().st_size / 1e9:.2f} GB)")
    if terms.exists():
        print(f"   terms: {terms}  ({terms.stat().st_size / 1e9:.2f} GB)")
    print(f"\nLoad with:\n"
          f"  python scripts/load_wordnet_csv.py --space <space_id> \\\n"
          f"      --quads-csv {out} --terms-csv {terms}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
