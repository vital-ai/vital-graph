# `VALUES` Containing a Blank Node Raises AttributeError, and the Unit Test Hides It

## Status: RESOLVED 2026-08-16

`emit_table` reads `.label`, the field `BNodeNode` actually has.

The unit test was rewritten rather than adjusted: it built a plain `BNodeNode`
instead of patching `.value` onto one first. The old test described the
implementation, so it could not fail when the implementation was wrong —
verified by reverting the fix and watching the new test raise the original
AttributeError.

`emit_table.py` builds the inline-data SELECT by branching on the node type of
each row value. The blank-node branch reads `.value`:

```python
elif isinstance(val, BNodeNode):
    cols.append(f"'{_esc(val.value)}' AS {sn}")
    cols.append(f"'B' AS {sn}__type")
```
`vitalgraph/db/sparql_sql/emit_table.py:68-70`

`BNodeNode` has no `value` field:

```python
@dataclass
class BNodeNode:
    """An RDF blank node."""
    label: str
```
`vitalgraph/db/jena_sparql/jena_types.py:38-41`

`URINode` and `LiteralNode` both carry `.value`, so the branch was written by
analogy with its neighbours and never executed against a real `BNodeNode`. Any
query with a blank node in `VALUES` — e.g.

    SELECT ?x WHERE { VALUES ?x { _:b0 } }

raises `AttributeError: 'BNodeNode' object has no attribute 'value'` during SQL
generation. Not a wrong result: an unhandled exception out of the generator.

## The test asserts the bug is absent by creating the missing attribute

`tests/unit/sparql_sql/test_emit_table.py:81-98`:

```python
bnode = BNodeNode(label="b0")
bnode.value = "b0"  # type: ignore[attr-defined]  # match emit_table's usage
```

The comment is candid about what it is doing — it patches the object to match
the emitter rather than the emitter to match the object. Because `BNodeNode` is
a plain (non-slotted, non-frozen) dataclass, the assignment succeeds and the
test passes, so the crash is invisible to CI.

This is the clearest instance of the pattern described in
`planning/planning_sparql_features/README.md`: a construct our fixtures never
produce, where the *test* was written to the implementation instead of to the
spec.

## Fix

One line:

```python
cols.append(f"'{_esc(val.label)}' AS {sn}")
```

Then remove the `bnode.value = "b0"` workaround from the unit test so it
constructs a plain `BNodeNode(label="b0")` — which makes the test a real
regression guard rather than a mirror of the code.

Note the emitted text should be the **bare label**, consistent with
`issues/065` — `_esc(val.label)`, not `f"_:{val.label}"`.

## Sweep for the same mistake

`.value` on a `BNodeNode` is the general shape. Worth grepping for other
`BNodeNode` branches that assume the `URINode`/`LiteralNode` field name; the
audit in `planning/planning_sparql_features/blank_nodes.md` §3.3 found the rest
of the emitters correctly using `.label`, but the check is cheap and the
failure mode is a hard crash rather than a wrong answer.

## Related

- `planning/planning_sparql_features/blank_nodes.md` §5 (unit tests)
- `issues/065` — prefix convention, same file family
- `issues/069` — no blank-node fixture
