# Graph-Filtered Analytics Filtered On A Column That Does Not Exist

## Status: FIXED alongside `issues/163`. Found while making `rdf_stats`
## graph-aware, not by anything that was watching for it.

## What it did

`AnalyticsJob._graph_filter` built its clause as:

    AND q.graph_id = <n>

against `{space}_rdf_quad`, whose columns are:

    subject_uuid  predicate_uuid  object_uuid  context_uuid  quad_uuid  dataset

There is no `graph_id`. Graphs are identified in the quad table by
`context_uuid`, a term uuid; `graph_id` is a serial on the separate `graph`
registry table. So every analytics request that named a graph failed:

    ERROR:  column q.graph_id does not exist

Confirmed directly against `e2e_test_space_rdf_quad` rather than inferred.

The clause was interpolated into four separate computations — entity, frame,
relation and property analytics — so the failure was total for a graph-scoped
request, not partial.

## Why it survived

`_graph_filter` returns `""` when no graph is given, so the broken text is only
ever emitted on the graph-filtered path. Every exercised caller passes no graph:
the periodic job computes whole-space analytics, and the result is only
persisted `if not graph_uri`. The one code path that builds the clause is the
one nothing runs.

It is the same shape as the dead-code incidents logged elsewhere this week — an
optimisation or a filter that is never actually reached is indistinguishable
from a working one unless something asserts on the SQL it produces.

## The fix

Resolve the graph to its CONTEXT UUID and filter on the column the table has:

    AND q.context_uuid = '<uuid>'::uuid

`graph` still gates existence, so "Graph not found" keeps its meaning for an
unregistered URI. A registered graph whose URI is not a term in this space holds
no quads and is reported the same way, rather than silently widening the request
to the whole space — which is the failure mode to avoid here, since a wrong
number that looks plausible is worse than an error.

## Not covered by a test yet

The fix is exercised by construction — the same helper now feeds the `rdf_stats`
fast path, which `issues/163` covers — but there is still no test that calls
`AnalyticsJob` with a `graph_uri` and asserts the counts are that graph's. That
is the test that would have caught this, and it should exist.
