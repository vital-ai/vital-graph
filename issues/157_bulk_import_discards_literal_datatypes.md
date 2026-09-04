# `vitalgraphimport --mode bulk` Discards Literal Datatypes

## Status: FIXED 2026-09-04 for non-string datatypes; see issues/158 for the
## xsd:string half, which the fix uncovered and cannot settle on its own.
##
## Originally filed as: OPEN. Found 2026-09-04 when a hierarchical criterion returned 0 rows
## against a freshly imported fixture and 698 against an equivalent space loaded
## by the CSV path.

## What happens

Every typed literal loses its datatype on the way in.

    space              loader                          terms with a datatype
    sp_lead_types      scripts/load_wordnet_csv.py                     6,636
    nurture_shape_test vitalgraphimport --mode bulk                       26

The source file carries the datatype correctly:

    "58.0"^^<http://www.w3.org/2001/XMLSchema#float>

and the database ends up with `datatype_id IS NULL` for that term. Both spaces
have the same 40-row `_datatype` table — it is the TERMS that are never linked.

## Why

`_classify_node` (`data_import_impl.py`) returns a THREE-tuple and its signature
says so:

    def _classify_node(node, bnode_scope=None) -> Tuple[str, str, Optional[str]]:
        """Classify a pyoxigraph triple node into (value, term_type, lang)."""
        if cls_name == "Literal":
            lang = str(node.language) if node.language else None
            return node.value, "L", lang        # node.datatype is dropped here

`pyoxigraph`'s Literal carries `.datatype`; it is simply not read. The caller
then keys and hashes without it:

    def ensure(text, ttype, lang=None):
        key = (text, ttype, lang)
        terms[key] = _term_uuid(text, ttype, lang=lang)

even though `_term_uuid` accepts `datatype_id` and every other writer passes it.

## Two distinct consequences, the second worse than the first

1. **TYPED COMPARATORS SILENTLY MATCH NOTHING.** `gte`/`lt` on a numeric or
   date slot resolves through the slot class to a value predicate and a typed
   comparison. With the datatype gone the comparison never matches, the query
   returns 0 rows, and nothing errors. Reproduced exactly:

       hierarchical MQLRating >= 65
         sp_lead_types        698     (CSV loader)
         nurture_shape_test     0     (bulk import, same generator, same shape)

2. **TERM IDENTITY SPLITS.** `_generate_term_uuid(text, type, lang, datatype_id)`
   INCLUDES the datatype. A bulk-imported `"58.0"` therefore gets a different
   uuid from the same literal written through `add_rdf_quads_batch` or a SPARQL
   UPDATE. The same value becomes two terms, and a query written against one
   cannot see quads written through the other. This is latent until a space is
   both bulk-imported and incrementally written, which is the normal lifecycle.

## Scope

`--mode bulk` is the default of the CLI and the documented path for loading a
dataset. Anything loaded that way has untyped literals. `sp_lead_types` escaped
only because it was loaded by `load_wordnet_csv.py`, which goes through the
slim-CSV path and preserves them.

Worth checking whether `--mode incremental` shares `_classify_node`; the
docstring says "shared by both N-Triples importers", which suggests it does.

## Fix

Read the datatype and thread it through: `_classify_node` returns a four-tuple,
`ensure` keys on it, `_term_uuid` receives it, and the term row carries the
resolved `datatype_id`. The datatype table is already populated, so this is
resolution against existing rows rather than new schema.

## Testing

Nothing covers it. A test that imports one typed literal and asserts
`datatype_id IS NOT NULL` would have caught it, and so would any assertion that
a range comparator returns a non-zero count after a bulk import — the existing
comparator coverage runs against a CSV-loaded fixture, which is why it passes.

## Related

  * `issues/156` — an interrupted bulk import leaves a space unindexed. Same
    shape of failure: correct answers, or plausible ones, with no signal.
  * `planning/planning_performance/lead_fixture_production_shape_plan.md` — the
    fixture work that surfaced this.
