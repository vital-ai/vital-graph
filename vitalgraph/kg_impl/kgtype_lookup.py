"""KGType existence lookup that cannot mistake a failed query for an absent type.

`issues/261`. `execute_sparql_query` does not raise when the query engine fails;
it returns `{'success': False, 'error': ..., 'results': {'bindings': []}}`. The
create, delete and update processors each carried a copy of `kgtype_exists` that
read only the bindings, so a failed lookup was the same `False` as a missing
type. Seen on dev with the compiler sidecar down: a batch delete answered
"No KGTypes found for deletion" — a success — and deleted nothing. On create the
same misreading lets a create proceed over a type it could not check.

This is the `issues/215` / `issues/100` / `issues/082` shape, and
`kgquery_endpoint._checked_query` is the same answer: a reported failure raises.
"""

import logging

logger = logging.getLogger(__name__)


class KGTypeLookupFailed(RuntimeError):
    """The existence query did not run, so existence is unknown.

    The message deliberately avoids the phrase "not found": the KGType
    endpoints map an exception containing it to NOT_FOUND, and this is a store
    failure, not an absence.
    """


async def kgtype_exists(backend, space_id: str, graph_id: str, kgtype_uri: str) -> bool:
    """True if the KGType has any quad in the graph; raises if the query failed."""
    check_query = f"""
    SELECT ?s WHERE {{
        GRAPH <{graph_id}> {{
            <{kgtype_uri}> ?p ?o .
            BIND(<{kgtype_uri}> AS ?s)
        }}
    }} LIMIT 1
    """
    result = await backend.execute_sparql_query(space_id, check_query)
    if isinstance(result, dict):
        if result.get("success") is False:
            raise KGTypeLookupFailed(
                f"existence check for KGType {kgtype_uri} in {space_id} could not "
                f"run: {result.get('error') or 'backend reported failure'}")
        result = result.get("results", {}).get("bindings", [])
    return bool(result)
