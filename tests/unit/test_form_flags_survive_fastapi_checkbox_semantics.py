"""A boolean form field keeps its default when omitted — issues/281.

From FastAPI 0.147.0 (2026-10-19) an omitted `bool` form field arrives as False,
whatever its declared default — `bool = Form(True)` and
`Optional[bool] = Form(None)` alike. `/kgdocuments/upload` declared
`store_original: bool = Form(True)`, so every upload that did not send it
stopped keeping the original. E2E caught it the same day.

The route takes the field as a string and parses it (`_form_flag`). The guard
below keeps any route from declaring a `bool` form field again, since the
installed FastAPI may not show the problem.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import vitalgraph
from vitalgraph.endpoint.kgdocuments_endpoint import _form_flag


@pytest.mark.parametrize("value,expected", [
    (None, True), ("", True), ("  ", True),
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
    ("maybe", None), ("2", None),
])
def test_form_flag(value, expected):
    assert _form_flag(value, default=True) is expected


def test_the_default_is_the_callers():
    assert _form_flag(None, default=False) is False


def _bool_form_params(tree):
    """(function, parameter) for every parameter annotated bool / Optional[bool]
    whose default is a `Form(...)` call."""
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = fn.args.args + fn.args.kwonlyargs
        defaults = ([None] * (len(fn.args.args) - len(fn.args.defaults))
                    + list(fn.args.defaults) + list(fn.args.kw_defaults))
        for a, d in zip(args, defaults):
            if not (isinstance(d, ast.Call) and getattr(d.func, "id", None) == "Form"):
                continue
            if a.annotation is not None and "bool" in ast.unparse(a.annotation):
                found.append(f"{fn.name}({a.arg})")
    return found


def test_no_route_declares_a_bool_form_field():
    root = Path(vitalgraph.__file__).parent
    offenders = []
    for py in root.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        if "Form(" not in src:
            continue
        for hit in _bool_form_params(ast.parse(src)):
            offenders.append(f"{py.relative_to(root)}: {hit}")
    assert not offenders, (
        "a bool form field reads an OMITTED value as False on FastAPI >= 0.147, "
        "ignoring its default; take a string and parse it with _form_flag "
        "(issues/281): " + "; ".join(offenders))


def test_the_guard_sees_the_old_declaration():
    old = ("async def upload(store_original: bool = Form(True)): pass\n"
           "async def other(x: Optional[bool] = Form(None)): pass\n")
    assert _bool_form_params(ast.parse(old)) == ["upload(store_original)", "other(x)"]
