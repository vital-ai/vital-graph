"""Every `SET LOCAL` the server executes runs inside a transaction — issues/275.

`SET LOCAL` holds only inside a transaction block. On an autocommit connection
PostgreSQL emits a WARNING and keeps the current value, so the setting silently
does nothing: the analytics job's `SET LOCAL statement_timeout = '120s'` ran at
the instance's 60 s for as long as it existed, and the main KG space's analytics
failed at ~59 s after every restart.

This reads every module under `vitalgraph/` and, for each executed statement
starting `SET LOCAL`, requires that it sits lexically inside `async with
….transaction()`, or in a function that checks `is_in_transaction()`, or in a
helper named below whose contract is "the caller holds the transaction" — and
then checks that helper's own callers open one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import vitalgraph

ROOT = Path(vitalgraph.__file__).parent

# Helpers whose docstring makes the caller own the transaction. Each one's call
# sites are checked in turn.
CALLER_HOLDS_THE_TRANSACTION = {"_apply_read_fence"}


def _set_local_calls(tree):
    """(node, parents) for each `<x>.execute("SET LOCAL …")` / f-string form."""
    out = []

    def visit(node, parents):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("execute", "fetch", "fetchval") and node.args):
            a0 = node.args[0]
            text = None
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                text = a0.value
            elif isinstance(a0, ast.JoinedStr) and a0.values and isinstance(a0.values[0], ast.Constant):
                text = a0.values[0].value
            if text and text.lstrip().upper().startswith("SET LOCAL"):
                out.append((node, list(parents)))
        for child in ast.iter_child_nodes(node):
            visit(child, parents + [node])

    visit(tree, [])
    return out


def _in_transaction_block(parents) -> bool:
    for p in parents:
        if isinstance(p, (ast.AsyncWith, ast.With)):
            for item in p.items:
                src = ast.unparse(item.context_expr)
                if src.endswith(".transaction()") or ".transaction(" in src:
                    return True
    return False


def _enclosing_function(parents):
    for p in reversed(parents):
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return p
    return None


def _modules():
    for path in sorted(ROOT.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def test_every_set_local_is_inside_a_transaction():
    offenders = []
    for path, tree in _modules():
        for node, parents in _set_local_calls(tree):
            fn = _enclosing_function(parents)
            if _in_transaction_block(parents):
                continue
            if fn is not None and "is_in_transaction" in ast.unparse(fn):
                continue
            if fn is not None and fn.name in CALLER_HOLDS_THE_TRANSACTION:
                continue
            offenders.append(f"{path.relative_to(ROOT.parent)}:{node.lineno} "
                             f"in {fn.name if fn else '<module>'}")
    assert not offenders, (
        "SET LOCAL outside a transaction is a silent no-op (issues/275): "
        + "; ".join(offenders))


def test_the_caller_holds_helpers_are_called_inside_a_transaction():
    offenders = []
    for path, tree in _modules():
        def visit(node, parents):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in CALLER_HOLDS_THE_TRANSACTION):
                if not _in_transaction_block(parents):
                    fn = _enclosing_function(parents)
                    offenders.append(f"{path.relative_to(ROOT.parent)}:{node.lineno} "
                                     f"{node.func.id} in {fn.name if fn else '<module>'}")
            for child in ast.iter_child_nodes(node):
                visit(child, parents + [node])
        visit(tree, [])
    assert not offenders, "; ".join(offenders)


def test_the_guard_catches_the_analytics_shape():
    """The shape issues/275 shipped — acquire, then SET LOCAL, no transaction."""
    tree = ast.parse(
        "async def f(pool):\n"
        "    async with pool.acquire() as conn:\n"
        "        await conn.execute(\"SET LOCAL statement_timeout = '120s'\")\n")
    (node, parents), = _set_local_calls(tree)
    assert not _in_transaction_block(parents)
