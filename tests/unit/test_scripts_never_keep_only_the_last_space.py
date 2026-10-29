"""No script silently keeps only the last of several `--space` flags.

A plain `add_argument("--space")` is single-valued, and argparse keeps the LAST
value when it is given twice, without a word. `migrate_pred_stats_object_count.py
--space a --space b --space c --space d` therefore migrated only `d`, and a
command written for four spaces looked like it had run on four (2026-10-29,
found during the v0.0.97 deploy). 37 scripts had the same flag.

Every `--space` is now `action="append"`: a script that loops over spaces takes
the list, and a script that works on one space refuses a repeat with an error.
This pins both, so a new script cannot reintroduce the trap.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
DECL = re.compile(r'add_argument\(\s*"--space"([^)]*)\)')


def _declaring():
    for p in sorted(SCRIPTS.glob("*.py")):
        text = p.read_text()
        for m in DECL.finditer(text):
            yield p, text, m.group(1)


def test_every_space_flag_is_repeatable():
    single = [p.name for p, _t, args in _declaring() if 'action="append"' not in args]
    assert not single, (
        f"--space declared single-valued (a repeat silently keeps the last): {single}")


def test_a_one_space_script_refuses_a_repeat():
    """A script that unwraps the list to one value must refuse a second one,
    not take the first or the last."""
    unguarded = []
    for p, text, _args in _declaring():
        unwraps = re.search(r"\.space = \w+\.space\[0\]", text)
        if unwraps and "given more than once" not in text:
            unguarded.append(p.name)
    assert not unguarded, f"unwraps --space to one value without refusing a repeat: {unguarded}"


def test_the_check_sees_the_scripts():
    assert sum(1 for _ in _declaring()) >= 30
