"""Compare two comparator-sweep logs and report regressions. Fails loudly.

Written after a hand-rolled comparison declared "no cell regressed" while SEVEN
cells were timing out. Its regex matched only rows in the `NNms` form, so a
timed-out cell did not parse and silently dropped out of the comparison — it
compared 11 of 39 cells and called that success. The regression reached
origin/main.

So the rules here are about not being able to lie:

  * A cell present in the baseline and ABSENT from the comparison is an ERROR,
    not a skip. Disappearing is exactly what a timeout looks like.
  * A timeout is parsed as a value (the budget), never dropped.
  * The cell COUNT of both files is printed, so "compared 11 of 39" is visible
    rather than implied.
  * Exit code is non-zero on any regression or any unparsed cell, so it can gate
    a commit instead of being read optimistically.

    python scripts/perf_sweep_diff.py BASELINE.log CURRENT.log
"""
from __future__ import annotations

import re
import sys

# "  cell   cold   warm   buffers  rows" — warm may be a number or a timeout.
_ROW = re.compile(r"^\s+(\S+/\S+)\s+(\S+)\s+([\d,]+)ms\s+([\d,]+|timeout)\s")
_TIMEOUT_ROW = re.compile(r"^\s+(\S+/\S+)\s+.*TIMED OUT", re.I)


def parse(path: str) -> tuple[dict, list]:
    warm, unparsed = {}, []
    for line in open(path):
        if not line.startswith("  ") or "/" not in line.split()[0:1][0:1] and not line[2:3].isalpha():
            pass
        m = _ROW.match(line)
        if m:
            warm[m.group(1)] = int(m.group(3).replace(",", ""))
            continue
        t = _TIMEOUT_ROW.match(line)
        if t:
            warm[t.group(1)] = float("inf")
            continue
        # A line that looks like a cell row but matched neither pattern is the
        # dangerous case: silently skipping it is how the last comparison lied.
        if re.match(r"^\s{2}\w+/\w+\s", line):
            unparsed.append(line.rstrip())
    return warm, unparsed


def main(base_path: str, cur_path: str) -> int:
    base, base_bad = parse(base_path)
    cur, cur_bad = parse(cur_path)
    print(f"  baseline {base_path}: {len(base)} cells")
    print(f"  current  {cur_path}: {len(cur)} cells")

    problems = 0
    for line in base_bad + cur_bad:
        print(f"  UNPARSED ROW (treated as failure): {line}")
        problems += 1

    missing = sorted(set(base) - set(cur))
    for cell in missing:
        print(f"  MISSING from current: {cell} — a cell that vanished is a timeout")
        problems += 1

    regressed = []
    for cell, was in sorted(base.items()):
        if cell not in cur:
            continue
        now = cur[cell]
        if now == float("inf") and was != float("inf"):
            regressed.append((cell, was, now))
        elif now > max(was * 2, was + 300):
            regressed.append((cell, was, now))

    for cell, was, now in sorted(regressed, key=lambda r: -(r[2] - r[1])):
        w = "TIMEOUT" if now == float("inf") else f"{now:,.0f}ms"
        print(f"  REGRESSED {cell:28s} {was:>8,.0f}ms -> {w}")
    problems += len(regressed)

    if problems:
        print(f"\n  {problems} problem(s) — NOT safe to commit")
    else:
        print(f"\n  no regressions across {len(base)} cells")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
