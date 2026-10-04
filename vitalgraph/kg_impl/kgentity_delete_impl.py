"""
KGEntity Delete Implementation for VitalGraph.

This module provides the implementation for deleting KG entities from the backend storage,
supporting both single entity deletion and entity graph deletion with related objects.
"""

import logging
from typing import List, Optional, Dict, Any, Union

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity

# RDFLib helper for datatype preservation in SPARQL result parsing
from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib


class KGEntityDeleteProcessor:
    """
    Processor for KGEntity deletion operations with backend integration.
    
    Handles both single entity deletion and entity graph deletion with proper
    a single PostgreSQL transaction.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    # `delete_entity` (a SPARQL read then a quad-level delete, no lock) and
    # `delete_entities_batch` were DELETED 2026-10-04 (`issues/256`): the
    # entity-only form is `delete_entity_graph(..., entity_only=True)` now, one
    # locked transaction, refused while the entity has members.

    async def delete_entity_graph(self, backend, space_id: str, graph_id: str, entity_uri: str,
                                  collected_uris: Optional[List[str]] = None,
                                  if_unmodified_since: Optional[str] = None,
                                  entity_only: bool = False) -> int:
        """
        Delete an entity graph (entity plus all related objects) from the backend.
        
        Uses direct SQL bulk delete when available (SparqlSQLBackendAdapter),
        falling back to the SPARQL-based approach for other backends.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the primary entity whose graph should be deleted
            
            collected_uris: Optional list; if given, every member subject URI
                this deletes is appended to it. The caller needs them for
                derived-data cleanup — an FTS/vector row is keyed on the
                SUBJECT, so deleting an entity graph without telling those
                stores which subjects went leaves rows that still match a
                search and resolve to a deleted entity (issues/217).
                This method already computes the list; it used to discard it
                and return only a count.
            if_unmodified_since: Refuse (`StaleWrite`) if the entity's
                modification time has moved since the caller read it.
            entity_only: Delete the entity subject alone, and refuse
                (`DeleteRefused`) if it has members (`issues/256`).

        Returns:
            int: non-zero if anything was deleted, 0 if the entity graph was
            ABSENT. A failure RAISES (`issues/256`): this returned 0 for both,
            so the endpoint could not tell "already gone" (NO_OP) from "the
            delete failed" (STORE_FAILED) and reported both as a failure.
        """
        try:
            import time
            start_time = time.time()
            self.logger.info(f"🔥 DELETE ENTITY GRAPH START: {entity_uri} from graph: {graph_id}")
            
            # Fast path: direct SQL bulk delete (SparqlSQLBackendAdapter).
            # `collected_uris` goes THROUGH: this path used to return without
            # filling it, so the caller's auto-sync was handed the entity URI
            # alone and every member's vector, geo and fuzzy rows outlived the
            # entity (`issues/256`; FTS was already cleaned in the bulk
            # delete's own transaction).
            if hasattr(backend, 'delete_entity_graph_direct'):
                deleted_quads = await backend.delete_entity_graph_direct(
                    space_id, graph_id, entity_uri, collected_uris=collected_uris,
                    if_unmodified_since=if_unmodified_since, entity_only=entity_only)
                elapsed = time.time() - start_time
                self.logger.info(f"🔥 DELETE ENTITY GRAPH DONE (bulk SQL): {deleted_quads} quads in {elapsed:.3f}s")
                # Return non-zero to indicate success (caller checks > 0)
                return 1 if deleted_quads > 0 else 0

            # Slow path: SPARQL-based delete (other backends). It has no lock and
            # no transaction, so it cannot honour a guard or a member check;
            # refusing is better than silently ignoring them.
            if entity_only or if_unmodified_since is not None:
                raise RuntimeError(
                    "entity_only and if_unmodified_since need a backend with "
                    "delete_entity_graph_direct")
            full_graph_uri = graph_id
            kg_graph_uri = entity_uri
            
            find_subjects_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT DISTINCT ?s WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?s haley:hasKGGraphURI <{kg_graph_uri}> .
                }}
            }}
            """
            
            subjects_result = await backend.execute_sparql_query(space_id, find_subjects_query)
            
            subject_uris = []
            if isinstance(subjects_result, dict) and 'results' in subjects_result:
                bindings = subjects_result['results'].get('bindings', [])
                for binding in bindings:
                    if 's' in binding:
                        s_value = binding['s'].get('value', '') if isinstance(binding['s'], dict) else str(binding['s'])
                        if s_value:
                            subject_uris.append(s_value)
            
            if collected_uris is not None:
                collected_uris.extend(str(u) for u in subject_uris)

            if not subject_uris:
                self.logger.warning(f"No objects found with kGGraphURI: {kg_graph_uri}")
                return 0
            
            subject_filter = ', '.join([f'<{str(uri).strip()}>' for uri in subject_uris])
            triples_query = f"""
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?s ?p ?o .
                    FILTER(?s IN ({subject_filter}))
                }}
            }}
            """
            
            triples_result = await backend.execute_sparql_query(space_id, triples_query)
            
            quads = []
            if isinstance(triples_result, dict) and 'results' in triples_result:
                bindings = triples_result['results'].get('bindings', [])
                for binding in bindings:
                    if 's' in binding and 'p' in binding and 'o' in binding:
                        s_value = binding['s'].get('value', '') if isinstance(binding['s'], dict) else str(binding['s'])
                        p_value = binding['p'].get('value', '') if isinstance(binding['p'], dict) else str(binding['p'])
                        o_rdflib = _sparql_binding_to_rdflib(binding.get('o', ''))
                        if s_value and p_value and o_rdflib is not None:
                            quads.append((s_value, p_value, o_rdflib, full_graph_uri))
            
            if not quads:
                self.logger.warning(f"No triples found for entity graph objects")
                return 0
            
            deleted_count = await backend.remove_rdf_quads_batch(space_id, quads)
            elapsed = time.time() - start_time
            self.logger.info(f"🔥 DELETE ENTITY GRAPH DONE (SPARQL): {deleted_count} quads in {elapsed:.3f}s")
            
            return len(subject_uris) if deleted_count > 0 else 0
            
        except Exception as e:
            self.logger.error(f"Error deleting entity graph for {entity_uri}: {e}")
            raise
    
    async def entity_exists(self, backend, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Check if an entity exists in the backend.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            entity_uri: URI of the entity to check
            
        Returns:
            bool: True if entity exists, False otherwise
        """
        try:
            # Use backend's object_exists method to check if entity exists
            if hasattr(backend, 'object_exists'):
                try:
                    return await backend.object_exists(space_id, graph_id, entity_uri)
                except Exception:
                    return False
            
            # Fallback: assume entity exists (let deletion handle the error)
            self.logger.warning(f"Cannot check entity existence for {entity_uri} - backend method not available")
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking if entity exists {entity_uri}: {e}")
            return False
