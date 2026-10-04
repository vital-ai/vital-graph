"""Every refusal a write path can raise must reach the caller as one.

THIS TEST EXISTS BECAUSE THE CHECK WAS RUN BY HAND THREE TIMES AND FOUND A REAL
DEFECT ONCE. In `v0.0.78` review, `UnguardableWrite` and `AmbiguousStamp` were
raised deliberately and documented as loud, and both were swallowed by the
`except Exception: return False` at the bottom of the same function — so a
refusal arrived as a generic `STORE_FAILED` with the cause in the log only. The
fix added `except GuardUnsatisfiable: raise`. Nothing stopped it regressing, and
the next release added a THIRD such exception (`UngroupableSlot`), which had to
be threaded through the same handlers by hand again.

The shape of the bug is always the same: a specific exception raised somewhere
below, and a broad `except Exception` between it and the response that turns it
into something else. It is invisible in review because the raise and the handler
are hundreds of lines apart, and invisible to the existing tests because they
assert on SOURCE SHAPE (`assert "except GuardUnsatisfiable" in src`) rather than
on what escapes.

`StaleWrite` is the anchor. It is the oldest of the family and every path that
can refuse handles it, so any `try` that catches `StaleWrite` is by construction
on a refusal path — and must therefore let its siblings past too.

WHY AST AND NOT A LIVE CALL. Reaching every one of these handlers through the
API needs a database, a space, and a request shaped to trigger each refusal on
each route — which is what `tests/integration/test_a_stale_write_is_refused.py`
does for the two it can reach. This covers the rest, cheaply, and it covers the
NEXT one automatically: add a sibling to `REFUSALS` and every path is checked.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# The anchor, and the siblings that must travel with it. A refusal is a DOMAIN
# outcome answered in a 200 body (`model/result_status.py`); swallowed into the
# generic failure path it becomes indistinguishable from a write that broke.
ANCHOR = "StaleWrite"
# `RequestRefused` is the base of `UngroupableSlot`, `DeleteRefused` and the
# `issues/256` write refusals; catching the base is what lets the family past.
SIBLINGS = ("GuardUnsatisfiable", "RequestRefused")

ROOT = pathlib.Path(__file__).resolve().parents[2]
SEARCH = ("vitalgraph/endpoint", "vitalgraph/kg_impl")


def _caught(handler: ast.ExceptHandler) -> set:
    if handler.type is None:
        return {"BARE"}
    if isinstance(handler.type, ast.Tuple):
        return {ast.unparse(e) for e in handler.type.elts}
    return {ast.unparse(handler.type)}


def _modules():
    for d in SEARCH:
        yield from sorted((ROOT / d).glob("*.py"))


def _refusal_handlers():
    """Every `try` that handles the anchor, with what else it catches."""
    for path in _modules():
        src = path.read_text()
        if ANCHOR not in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not node.handlers:
                continue
            caught = set().union(*(_caught(h) for h in node.handlers))
            if ANCHOR in caught:
                yield path.relative_to(ROOT), node.lineno, caught


class TestARefusalIsNotSwallowed:

    def test_the_anchor_is_actually_handled_somewhere(self):
        """Guard the guard: a rename would make every assertion below vacuous."""
        found = list(_refusal_handlers())
        assert found, (
            f"no `try` anywhere under {SEARCH} handles {ANCHOR}. Either the "
            f"refusal family was renamed — in which case update ANCHOR and "
            f"SIBLINGS — or every refusal path has lost its handler.")

    @pytest.mark.parametrize("sibling", SIBLINGS)
    def test_every_refusal_path_lets_the_sibling_past(self, sibling):
        gaps = [
            f"{path}:{line} catches {ANCHOR} but not {sibling} "
            f"(catches: {', '.join(sorted(caught))})"
            for path, line, caught in _refusal_handlers()
            if sibling not in caught
        ]
        assert not gaps, (
            f"{sibling} is a refusal, like {ANCHOR}: a domain outcome the caller "
            f"must be told about. On the paths below it falls through to the "
            f"broad `except Exception`, which answers a generic failure and "
            f"leaves the reason in the log.\n\n  " + "\n  ".join(gaps) +
            "\n\nAdd it to the same handler tuple as " + ANCHOR + ".")

    def test_no_refusal_path_ends_in_a_bare_except(self):
        """`except:` catches BaseException — including the cancellation that
        `issues/253`'s write deadline relies on propagating."""
        bare = [f"{path}:{line}" for path, line, caught in _refusal_handlers()
                if "BARE" in caught]
        assert not bare, "bare `except:` on a refusal path: " + ", ".join(bare)
