"""Delete orphaned KG entity graph objects.

Discovers all objects belonging to an entity graph (via ``hasKGGraphURI``)
and deletes them in batches through the VitalGraph client API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

from .orphan_scanner import (
    InspectResult,
    _extract_bindings,
    _val,
    inspect_entity_graph,
    shorten,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_ALL_GRAPH_SUBJECTS = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT DISTINCT ?subject
WHERE {{
  ?subject haley:hasKGGraphURI <{entity_uri}> .
}}
"""

_EDGE_SUBJECTS = """\
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?edge
WHERE {{
  {{
    ?edge vital:hasEdgeSource <{entity_uri}> .
  }} UNION {{
    ?edge vital:hasEdgeDestination <{entity_uri}> .
  }}
}}
"""

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DeleteResult:
    """Result of an orphan graph deletion."""
    entity_uri: str
    total_discovered: int = 0
    total_deleted: int = 0
    total_errors: int = 0
    remaining: int = 0
    dry_run: bool = True

    @property
    def success(self) -> bool:
        return self.remaining == 0 and self.total_errors == 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def delete_orphan_graph(
    client: VitalGraphClient,
    space_id: str,
    entity_uri: str,
    graph_id: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = True,
) -> DeleteResult:
    """Delete all objects belonging to an orphaned entity graph.

    Parameters
    ----------
    client:
        Connected VitalGraphClient instance.
    space_id:
        Space containing the entity graph.
    entity_uri:
        URI of the (missing) top-level KGEntity.
    graph_id:
        Named graph URI to delete from. If ``None``, auto-detects from
        the first graph in the space.
    batch_size:
        Number of URIs per batch delete call.
    dry_run:
        If ``True`` (default), report what would be deleted without
        actually deleting.
    """
    result = DeleteResult(entity_uri=entity_uri, dry_run=dry_run)

    # Resolve graph_id if not provided
    if graph_id is None:
        graphs_resp = await client.graphs.list_graphs(space_id)
        if not graphs_resp.graphs:
            logger.error("No graphs found in space %s", space_id)
            return result
        graph_id = str(graphs_resp.graphs[0].graph_uri)
        logger.info("Auto-detected graph: %s", graph_id)

    # Collect all URIs to delete
    uris_to_delete: List[str] = []

    # 1. Objects with hasKGGraphURI = entity_uri
    q1 = _ALL_GRAPH_SUBJECTS.format(entity_uri=entity_uri)
    resp1 = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q1)
    )
    for b in _extract_bindings(resp1):
        uri = _val(b, "subject")
        if uri:
            uris_to_delete.append(uri)

    # 2. Edges referencing entity as source or destination
    q2 = _EDGE_SUBJECTS.format(entity_uri=entity_uri)
    resp2 = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q2)
    )
    for b in _extract_bindings(resp2):
        uri = _val(b, "edge")
        if uri and uri not in uris_to_delete:
            uris_to_delete.append(uri)

    # 3. The entity URI itself (in case partial triples remain)
    if entity_uri not in uris_to_delete:
        uris_to_delete.append(entity_uri)

    result.total_discovered = len(uris_to_delete)

    if dry_run:
        print(f"\n[DRY RUN] Would delete {result.total_discovered} objects:")
        for uri in uris_to_delete:
            print(f"  {shorten(uri)}")
        print(f"\nRe-run with --no-dry-run to execute.")
        return result

    # Execute batch deletion
    logger.info(
        "Deleting %d objects in batches of %d...",
        len(uris_to_delete), batch_size,
    )
    for i in range(0, len(uris_to_delete), batch_size):
        batch = uris_to_delete[i : i + batch_size]
        uri_list = ",".join(batch)
        batch_num = i // batch_size + 1

        try:
            del_resp = await client.objects.delete_objects_batch(
                space_id, graph_id, uri_list
            )
            if del_resp.is_success:
                result.total_deleted += len(batch)
                logger.info("  Batch %d: deleted %d objects", batch_num, len(batch))
            else:
                result.total_errors += len(batch)
                logger.error(
                    "  Batch %d: FAILED - %s", batch_num, del_resp.message
                )
        except Exception as exc:
            result.total_errors += len(batch)
            logger.error("  Batch %d: EXCEPTION - %s", batch_num, exc)

    # Verify
    resp_verify = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q1)
    )
    result.remaining = len(_extract_bindings(resp_verify))

    return result


def print_delete_result(result: DeleteResult) -> None:
    """Pretty-print a DeleteResult to stdout."""
    print(f"\nEntity URI: {result.entity_uri}")
    if result.dry_run:
        print(f"[DRY RUN] {result.total_discovered} objects would be deleted")
    else:
        print(f"Discovered: {result.total_discovered}")
        print(f"Deleted:    {result.total_deleted}")
        print(f"Errors:     {result.total_errors}")
        print(f"Remaining:  {result.remaining}")
        if result.success:
            print("Status: SUCCESS — all objects deleted")
        else:
            print("Status: INCOMPLETE — some objects remain or had errors")
