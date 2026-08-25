"""The one name for the default graph's storage context.

Quads written without an explicit graph land in a context whose URI is this
string. That is a STORAGE detail: SPARQL's dataset model says the default
graph is not one of the named graphs, so this context must not behave like
one (`named_graph_semantics` §4.2).

Concretely, it is excluded from three places, and the list is here because
each site is easy to add and easy to forget:

  1. `GRAPH ?g` enumeration     -- collect.py / emit_path.py
  2. `FROM NAMED` eligibility   -- collect.py
  3. the `graph` catalog        -- graph_registry.py

It lived as a private `_FALLBACK_DEFAULT_GRAPH` in `emit_update` and as bare
"urn:default" literals elsewhere, which is how a value that has to be
recognised in three unrelated modules ends up recognised in one.
"""

from __future__ import annotations

DEFAULT_GRAPH_URI = "urn:default"


def is_default_graph(uri: str | None) -> bool:
    """True for the context that backs the default graph."""
    return uri == DEFAULT_GRAPH_URI
