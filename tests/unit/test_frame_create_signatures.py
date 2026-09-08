"""A frame-write call site must not pass a keyword its callee refuses.

`4d009230` threaded `entity_uri` through the frame write paths to serialise
them on the grouping. It added the parameter to `execute_atomic_frame_update`,
added `entity_uri=entity_uri` to BOTH call sites, and used `entity_uri` inside
`execute_frame_creation`'s body — but never added it to that signature.

So every frame creation through that path raised

    execute_frame_creation() got an unexpected keyword argument 'entity_uri'

at runtime. Imports still succeeded, the unit suite still passed, and it was
E2E that went red. It stayed red for ten pushes because the failure looked like
part of a pre-existing E2E problem.

Checked by INSPECTION rather than by calling: these methods need a backend, a
space and a live transaction, so a test that exercised them would be an
integration test guarding an error that a signature check catches for free.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

MODULES = [
    "vitalgraph.kg_impl.kgentity_frame_create_impl",
    "vitalgraph.kg_impl.kgframe_create_impl",
]


def _calls_and_defs(src: str):
    """`{name: {kwargs}}` for self.<name>(...) calls, and `{name: {params}}`."""
    tree = ast.parse(src)
    calls, defs = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            defs[node.name] = ({a.arg for a in node.args.args}
                               | {a.arg for a in node.args.kwonlyargs})
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"):
            kw = {k.arg for k in node.keywords if k.arg}
            calls.setdefault(node.func.attr, set()).update(kw)
    return calls, defs


@pytest.mark.parametrize("modname", MODULES)
def test_no_self_call_passes_an_unaccepted_keyword(modname):
    mod = __import__(modname, fromlist=["x"])
    src = pathlib.Path(inspect.getfile(mod)).read_text()
    calls, defs = _calls_and_defs(src)

    bad = []
    for name, kwargs in calls.items():
        if name not in defs:
            continue                     # defined elsewhere; not ours to check
        unknown = kwargs - defs[name]
        if unknown:
            bad.append(f"self.{name}(...) passes {sorted(unknown)}, "
                       f"which {name}() does not accept")
    assert not bad, (
        f"{modname} calls a method of its own class with a keyword that method "
        f"refuses — a guaranteed TypeError at runtime that imports and unit "
        f"tests do not catch:\n  " + "\n  ".join(bad))


def test_entity_uri_is_threaded_consistently():
    """The specific regression: used in a body, so it must be a parameter."""
    from vitalgraph.kg_impl import kgentity_frame_create_impl as m

    src = pathlib.Path(inspect.getfile(m)).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.AsyncFunctionDef)
                and node.name in ("execute_frame_creation",
                                  "execute_atomic_frame_update")):
            params = {a.arg for a in node.args.args}
            body = ast.get_source_segment(src, node) or ""
            uses = "entity_uri" in body.split("\n", 1)[-1]
            assert not uses or "entity_uri" in params, (
                f"{node.name} uses entity_uri in its body but does not accept "
                f"it as a parameter")
