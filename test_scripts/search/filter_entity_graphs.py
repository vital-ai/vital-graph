#!/usr/bin/env python3
"""Filter an N-Quads export down to the entity graphs of one KG entity type.

Why this exists rather than `vitalgraphexport --entity-type-uri`: that flag is
`vital` block format only, and its query must `ORDER BY` the grouping URI
before it can emit its first block. Measured against production, that sort
spilled **15 GB of temp and was still growing at ~1.3 GB/min after 8 minutes,
having produced zero rows** — while an unfiltered N-Quads export of the same
space streams with no sort and no temp at ~57k rows/s. So the cheap thing is
to export everything and do the selection here, where the cost lands on a
workstation instead of a production database.

THE MEMBERSHIP RULE

A KG entity graph is not a URI prefix — it is declared. Every member subject
carries

    <member> haley:hasKGGraphURI <entity-uri>

and the entity itself carries `hasKGEntityType`. Members are therefore found
by that predicate, not by string prefix. (In this dataset member URIs *do*
happen to extend the entity URI, so prefix matching would appear to work and
would silently drop any member that did not follow the convention.)

Three streaming passes, because a member can appear in the file before the
entity that claims it:

    1. entity URIs whose hasKGEntityType matches
    2. subjects whose hasKGGraphURI is one of those
    3. emit every quad whose subject is in either set

Subjects are held as 8-byte digests, not strings, so memory stays flat in the
URI length: ~3-4M members costs a few hundred MB rather than several GB.

    python3 test_scripts/search/filter_entity_graphs.py \\
        --in  prod_kg_full.nq.gz \\
        --out prod_nurture.nq.gz \\
        --entity-type 'urn:<ns>:kg:entity:NurtureAction'
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import sys
import time

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
P_ENTITY_TYPE = f"<{HALEY}hasKGEntityType>"
P_GRAPH_URI = f"<{HALEY}hasKGGraphURI>"


def _h(s: str) -> int:
    """8-byte digest of a URI, as an int. Collision risk is negligible here
    (~3M items in a 2^64 space) and the memory saving is the point."""
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def _open(path: str, mode: str = "rt"):
    if path.endswith(".gz"):
        return gzip.open(path, mode, encoding="utf-8" if "t" in mode else None)
    return open(path, mode, encoding="utf-8" if "t" in mode else None)


def _subject(line: str) -> str | None:
    """Subject URI of an N-Quads line, without allocating the whole parse."""
    if not line.startswith("<"):
        return None                      # blank node or malformed; not ours
    end = line.find("> ", 1)
    return line[1:end] if end > 0 else None


def _parts(line: str):
    """(subject, predicate_token, object_token) — enough for the two probes."""
    if not line.startswith("<"):
        return None, None, None
    s_end = line.find("> ", 1)
    if s_end < 0:
        return None, None, None
    p_start = s_end + 2
    p_end = line.find(" ", p_start)
    if p_end < 0:
        return None, None, None
    o_start = p_end + 1
    o_end = line.find(" ", o_start)
    if o_end < 0:
        o_end = len(line)
    return line[1:s_end], line[p_start:p_end], line[o_start:o_end]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--entity-type", required=True,
                    help="KG entity type URI, e.g. urn:<ns>:kg:entity:NurtureAction")
    ap.add_argument("--progress", type=int, default=5_000_000)
    a = ap.parse_args()

    want_obj = f"<{a.entity_type}>"
    t0 = time.monotonic()

    # ---- pass 1: the entities ------------------------------------------
    entities: set[int] = set()
    n = 0
    with _open(a.src) as f:
        for line in f:
            n += 1
            if a.progress and n % a.progress == 0:
                print(f"  pass1 {n:,} lines, {len(entities):,} entities "
                      f"({time.monotonic() - t0:.0f}s)", file=sys.stderr)
            s, p, o = _parts(line)
            if p == P_ENTITY_TYPE and o == want_obj and s:
                entities.add(_h(s))
    print(f"pass 1: {n:,} lines, {len(entities):,} entities "
          f"({time.monotonic() - t0:.0f}s)", file=sys.stderr)
    if not entities:
        print(f"No subject has {P_ENTITY_TYPE} {want_obj} — wrong type URI?",
              file=sys.stderr)
        return 1

    # ---- pass 2: their members -----------------------------------------
    members: set[int] = set()
    n = 0
    with _open(a.src) as f:
        for line in f:
            n += 1
            if a.progress and n % a.progress == 0:
                print(f"  pass2 {n:,} lines, {len(members):,} members "
                      f"({time.monotonic() - t0:.0f}s)", file=sys.stderr)
            s, p, o = _parts(line)
            if p == P_GRAPH_URI and s and o and o.startswith("<"):
                if _h(o[1:-1]) in entities:
                    members.add(_h(s))
    print(f"pass 2: {len(members):,} member subjects "
          f"({time.monotonic() - t0:.0f}s)", file=sys.stderr)

    keep = entities | members
    print(f"keeping {len(keep):,} distinct subjects", file=sys.stderr)

    # ---- pass 3: emit ---------------------------------------------------
    out = _open(a.dst, "wt")
    try:
        n, written = _emit(a.src, keep, out, a.progress, t0)
    finally:
        out.close()

    size = os.path.getsize(a.dst)
    print(f"pass 3: {written:,} of {n:,} quads written to {a.dst} "
          f"({size / 1e6:.1f} MB gz, {time.monotonic() - t0:.0f}s)",
          file=sys.stderr)

    if written == 0:
        print("Wrote nothing — check the entity type URI.", file=sys.stderr)
        return 1
    return 0


def _emit(src: str, keep: set[int], out, progress: int, t0: float):
    """Stream the source, writing kept quads. Returns (lines_read, written)."""
    n = written = 0
    with _open(src) as f:
        for line in f:
            n += 1
            s = _subject(line)
            if s is not None and _h(s) in keep:
                out.write(line)
                written += 1
            if progress and n % progress == 0:
                print(f"  pass3 {n:,} lines, {written:,} kept "
                      f"({time.monotonic() - t0:.0f}s)", file=sys.stderr)
    return n, written


if __name__ == "__main__":
    sys.exit(main())
