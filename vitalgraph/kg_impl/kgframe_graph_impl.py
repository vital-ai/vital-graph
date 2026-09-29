#!/usr/bin/env python3
"""
KGFrame Graph Processor Implementation

This module provides the KGFrameGraphProcessor class for handling
complete frame graph operations (retrieval and deletion).

Handles:
- Complete frame graph retrieval (frame + slots + edges)
- Frame graph deletion with cascade
- Child frame inclusion in graph operations
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot

# Common utilities
from vitalgraph.kg_impl.kg_backend_utils import (
    KGBackendInterface,
    BackendOperationResult
)


@dataclass
class FrameGraphResult:
    """Result of frame graph operation."""
    success: bool
    graph_objects: List[GraphObject]
    message: str
    error: Optional[str] = None


class KGFrameGraphProcessor:
    """
    Processor for frame graph operations.
    
    Handles:
    - Complete frame graph retrieval (frame + slots + edges)
    - Frame graph deletion with cascade
    - Child frame inclusion
    """
    
    def __init__(self):
        """Initialize the frame graph processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()
    
    async def get_frame_graph(
        self,
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        frame_uri: str
    ) -> FrameGraphResult:
        """
        Get complete graph for a frame including all connected objects.
        
        Returns:
        - Frame object
        - All immediate connected slots
        - All Edge_hasKGSlot relationships
        
        Note: Does NOT include child frames (which can have arbitrary depth).
        
        Args:
            backend_adapter: Backend adapter
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to get graph for
            
        Returns:
            FrameGraphResult with graph objects
        """
        try:
            self.logger.info(f"Getting frame graph for {frame_uri}")
            
            # Phase 1: Build SPARQL SELECT query to find all subject URIs in frame graph
            query = self._build_frame_graph_query(frame_uri, graph_id)
            
            # Execute query to get subject URIs
            results = await backend_adapter.execute_sparql_query(space_id, query)
            
            if not results:
                return FrameGraphResult(
                    success=False,
                    graph_objects=[],
                    message=f"Frame {frame_uri} not found",
                    error="Frame not found"
                )
            
            # Phase 2: Extract subject URIs from SELECT results
            subject_uris = []
            
            # Handle nested results structure: {'success': True, 'results': {'bindings': [...]}}
            bindings = []
            if isinstance(results, dict):
                if 'results' in results and 'bindings' in results['results']:
                    bindings = results['results']['bindings']
                elif 'bindings' in results:
                    bindings = results['bindings']
            elif isinstance(results, list):
                bindings = results
            
            for binding in bindings:
                if 'subject' in binding:
                    subject_uri = binding['subject'].get('value')
                    if subject_uri:
                        subject_uris.append(subject_uri)
            
            if not subject_uris:
                self.logger.warning("No subject URIs found in frame graph")
                return FrameGraphResult(
                    success=False,
                    graph_objects=[],
                    message=f"No objects found in frame graph for {frame_uri}",
                    error="No objects found"
                )
            
            self.logger.info(f"Found {len(subject_uris)} subjects in frame graph")
            
            # Phase 3: Fetch all objects by their URIs as VitalSigns objects
            
            # Use adapter's get_objects_by_uris (routed through KGBackendInterface)
            graph_objects = await backend_adapter.get_objects_by_uris(space_id, subject_uris, graph_id)
            
            if not graph_objects:
                self.logger.warning(f"No objects returned for frame graph")
                return FrameGraphResult(
                    success=False,
                    graph_objects=[],
                    message=f"No objects found for frame {frame_uri}",
                    error="No objects returned from backend"
                )
            
            self.logger.info(f"Retrieved frame graph with {len(graph_objects)} objects")
            
            return FrameGraphResult(
                success=True,
                graph_objects=graph_objects,
                message=f"Successfully retrieved frame graph with {len(graph_objects)} objects"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to get frame graph: {e}", exc_info=True)
            return FrameGraphResult(
                success=False,
                graph_objects=[],
                message=f"Failed to get frame graph: {str(e)}",
                error=str(e)
            )
    
    async def delete_frame_graph(
        self,
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        frame_uri: str
    ) -> bool:
        """
        Delete frame and all connected objects.
        
        Deletes:
        - Frame object
        - All connected slots
        - All Edge_hasKGSlot relationships
        - All Edge_hasKGFrame relationships (parent/child)
        
        Args:
            backend_adapter: Backend adapter
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to delete
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            self.logger.info(f"Deleting frame graph for {frame_uri}")
            
            # Build SPARQL DELETE query for frame graph
            query = self._build_frame_graph_delete_query(frame_uri, graph_id)
            
            # Execute deletion
            await backend_adapter.execute_sparql_update(space_id, query)
            
            self.logger.info(f"Successfully deleted frame graph for {frame_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete frame graph: {e}", exc_info=True)
            return False
    
    def _build_frame_graph_query(self, frame_uri: str, graph_id: str) -> str:
        """Build SPARQL finding every subject in this frame's graph.

        A frame reaches its slots by one of two linkages, and a space may use
        both, so this cannot pick a side:

          attribute   the slot carries `hasFrameGraphURI` naming its frame;
          connection  an `Edge_hasKGSlot` edge runs FROM the frame (source) TO
                      the slot (destination).

        Only the attribute form was implemented, though the method contract
        above it has always promised "All immediate connected slots, All
        Edge_hasKGSlot relationships". On a connection frame the query returned
        the frame alone, `get_frame_graph` saw a single object and returned
        None as "frame only", and the UI's Slot Summary reported "No slots found
        for this frame" for a frame with two of them. Silent, because a pattern
        anchored on an absent predicate matches nothing rather than failing.

        The EDGES are returned as well as the slots, deliberately. The client
        identifies a slot by the edge that links it — it pairs
        `isEdgeHasKGSlot(o) && o.edgeSource === frameId` with the slot at
        `edgeDestination` — so slots without their edges would still render
        nothing.

        BOTH CONNECTION ARMS ARE TYPED TO `Edge_hasKGSlot` (`issues/250`). They
        were untyped, matching ANY edge out of the frame — and a frame's other
        outbound edge is `Edge_hasKGFrame`, pointing at a CHILD frame. So the
        child frame arrived in the parent's graph as a bare destination with
        none of its own slots behind it, because a child carries its OWN
        `hasFrameGraphURI` and the attribute arm above never reaches it. A child
        frame with zero slots is indistinguishable from a frame whose slots were
        not fetched, which is the same ambiguity this docstring already warns
        about. Typing the arms makes the contract above — "Does NOT include
        child frames" — true, rather than half-applied.

        Nothing legitimate is lost: the whole corpus has three edge types, and
        only `Edge_hasKGSlot` and `Edge_hasKGFrame` can leave a frame at all
        (`Edge_hasEntityKGFrame` runs entity->frame).

        THE FILTER IS ON `vital:vitaltype`, NOT `rdf:type`, and that is not
        interchangeable here. `vitaltype` is the single-valued type URI this
        codebase counts on and the predicate `kg_query_builder` already uses to
        type a slot edge. Anchoring on the wrong one would match nothing and
        return every connection frame as slotless — silently, for the same
        reason a missing arm is silent.

        Args:
            frame_uri: Frame URI
            graph_id: Graph identifier

        Returns:
            SPARQL SELECT query to find all subjects in frame graph
        """
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>

        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{graph_id}> {{
                # The frame itself
                {{ <{frame_uri}> ?p ?o . BIND(<{frame_uri}> AS ?subject) }}
                UNION
                # Attribute linkage: objects naming this frame
                {{ ?subject haley:hasFrameGraphURI <{frame_uri}> . }}
                UNION
                # Connection linkage: the SLOT edges out of this frame
                {{ ?subject vital:hasEdgeSource <{frame_uri}> .
                   ?subject vital:vitaltype haley:Edge_hasKGSlot . }}
                UNION
                # Connection linkage: the slots those edges point at
                {{ ?_slotEdge vital:hasEdgeSource <{frame_uri}> .
                   ?_slotEdge vital:vitaltype haley:Edge_hasKGSlot .
                   ?_slotEdge vital:hasEdgeDestination ?subject . }}
            }}
        }}
        """
        return query

    def _build_frame_graphs_query(self, frame_uris: list, graph_id: str) -> str:
        """The four-arm frame-graph query, batched over N frames with VALUES.

        `issues/240`. The per-frame form makes one SELECT per URI, so a 25-frame
        page costs 25 round trips where the entity side does one
        (`_fetch_entity_graphs`). This is the same query with `?frame` bound by a
        VALUES clause instead of a literal, projecting `?frame` alongside
        `?subject` so the results can be grouped back per frame.

        ALL FOUR ARMS ARE PRESERVED, and that is the whole risk of this change.
        The singular version's docstring records why: only the attribute linkage
        was implemented once, so a CONNECTION frame returned the frame alone,
        `get_frame_graph` read one object as "frame only" and returned None, and
        the UI reported "No slots found for this frame" for a frame with two.
        A pattern anchored on an absent predicate matches nothing rather than
        failing, so a dropped arm here is silent. The equivalence test against
        the singular implementation exists for exactly that.

        The two connection arms are typed to `Edge_hasKGSlot` — see the singular
        builder for why (`issues/250`: untyped, they dragged in the child frame
        that `Edge_hasKGFrame` points at, without its slots). Both builders must
        change together or the equivalence test fails, which is the point of it.
        """
        values = " ".join(f"<{u}>" for u in frame_uris)
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT DISTINCT ?frame ?subject WHERE {{
            VALUES ?frame {{ {values} }}
            GRAPH <{graph_id}> {{
                # The frame itself
                {{ ?frame ?p ?o . BIND(?frame AS ?subject) }}
                UNION
                # Attribute linkage: objects naming this frame
                {{ ?subject haley:hasFrameGraphURI ?frame . }}
                UNION
                # Connection linkage: the SLOT edges out of this frame
                {{ ?subject vital:hasEdgeSource ?frame .
                   ?subject vital:vitaltype haley:Edge_hasKGSlot . }}
                UNION
                # Connection linkage: the slots those edges point at
                {{ ?_slotEdge vital:hasEdgeSource ?frame .
                   ?_slotEdge vital:vitaltype haley:Edge_hasKGSlot .
                   ?_slotEdge vital:hasEdgeDestination ?subject . }}
            }}
        }}
        """
        return query

    async def get_frame_graphs(
        self,
        backend_adapter,
        space_id: str,
        graph_id: str,
        frame_uris: list,
    ) -> dict:
        """Frame graphs for MANY frames: one SELECT, one object fetch.

        Returns `{frame_uri: [graph objects]}`, omitting frames with nothing.

        Added alongside `get_frame_graph` rather than replacing it — the
        single-URI path is in production and its behaviour is pinned by tests, so
        it keeps working unchanged while this is proven equivalent.

        One object can belong to SEVERAL frames (a shared subject), so objects
        are fetched ONCE over the union of subjects and then distributed by URI.
        Fetching per frame would refetch them and is the cost this removes.
        """
        if not frame_uris:
            return {}
        try:
            query = self._build_frame_graphs_query(list(frame_uris), graph_id)
            results = await backend_adapter.execute_sparql_query(space_id, query)

            bindings = []
            if isinstance(results, dict):
                if 'results' in results and 'bindings' in results['results']:
                    bindings = results['results']['bindings']
                elif 'bindings' in results:
                    bindings = results['bindings']
            elif isinstance(results, list):
                bindings = results

            per_frame = {}
            all_subjects = []
            for b in bindings:
                f = (b.get('frame') or {}).get('value')
                s_uri = (b.get('subject') or {}).get('value')
                if not f or not s_uri:
                    continue
                per_frame.setdefault(f, []).append(s_uri)
                all_subjects.append(s_uri)

            if not all_subjects:
                return {}

            # Deduped: the same subject reached from two frames is one fetch.
            unique = list(dict.fromkeys(all_subjects))
            objects = await backend_adapter.get_objects_by_uris(
                space_id, unique, graph_id) or []
            by_uri = {str(getattr(o, 'URI', '')): o for o in objects}

            out = {}
            for f, subs in per_frame.items():
                objs = [by_uri[u] for u in dict.fromkeys(subs) if u in by_uri]
                if objs:
                    out[f] = objs
            self.logger.info(
                "Frame graphs: %d frame(s), %d distinct subject(s), one query",
                len(out), len(unique))
            return out
        except Exception as e:
            self.logger.error(f"Failed to get frame graphs: {e}", exc_info=True)
            return {}

    def _build_frame_graph_delete_query(self, frame_uri: str, graph_id: str) -> str:
        """
        Build SPARQL DELETE query for complete frame graph.
        
        Args:
            frame_uri: Frame URI
            graph_id: Graph identifier
            
        Returns:
            SPARQL DELETE query
        """
        query = f"""
        DELETE {{
            GRAPH <{graph_id}> {{
                # Delete frame itself
                <{frame_uri}> ?framePred ?frameObj .
                
                # Delete slots
                ?slot ?slotPred ?slotObj .
                
                # Delete edges to slots
                ?edge ?edgePred ?edgeObj .
                
                # Delete child frames
                ?childFrame ?childFramePred ?childFrameObj .
                
                # Delete edges to child frames
                ?childEdge ?childEdgePred ?childEdgeObj .
            }}
        }}
        WHERE {{
            GRAPH <{graph_id}> {{
                # Frame properties
                <{frame_uri}> ?framePred ?frameObj .
                
                # Slots and edges
                OPTIONAL {{
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> .
                    ?edge <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slot .
                    
                    ?slot ?slotPred ?slotObj .
                    ?edge ?edgePred ?edgeObj .
                }}
                
                # Child frames and edges
                OPTIONAL {{
                    ?childEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> <{frame_uri}> .
                    ?childEdge <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame> .
                    ?childEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?childFrame .
                    
                    ?childFrame ?childFramePred ?childFrameObj .
                    ?childEdge ?childEdgePred ?childEdgeObj .
                }}
            }}
        }}
        """
        return query
    
    async def _convert_results_to_vitalsigns(self, results: List[Dict[str, Any]]) -> List[GraphObject]:
        """
        Convert SPARQL SELECT results to VitalSigns objects.
        
        The SELECT query returns subject URIs. We then fetch all triples for those subjects
        and convert them to VitalSigns objects.
        
        Args:
            results: SPARQL SELECT query results (list of bindings with 'subject' key)
            
        Returns:
            List of VitalSigns GraphObjects
        """
        try:
            if not results:
                return []
            
            # Extract subject URIs from SELECT results
            subject_uris = []
            for binding in results:
                if 'subject' in binding:
                    subject_uri = binding['subject'].get('value')
                    if subject_uri:
                        subject_uris.append(subject_uri)
            
            if not subject_uris:
                self.logger.warning("No subject URIs found in SELECT results")
                return []
            
            self.logger.info(f"Found {len(subject_uris)} subjects in frame graph")
            
            # For now, return empty list - the backend adapter should handle fetching triples
            # This will be implemented properly when we have the backend adapter method
            return []
            
        except Exception as e:
            self.logger.error(f"Failed to convert results to VitalSigns: {e}", exc_info=True)
            return []
