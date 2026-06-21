#!/usr/bin/env python3
"""
KGFrame Create Processor Implementation (Standalone)

This module provides the KGFrameCreateProcessor class for handling
standalone frame CRUD operations on the top-level /kgframes endpoint.

Unlike KGEntityFrameCreateProcessor, this processor:
- Does NOT use entity_uri or kGGraphURI
- Uses only frameGraphURI for grouping individual frame members
- Does NOT create Edge_hasEntityKGFrame edges
- Operates independently of KGEntity

Based on: kgentity_frame_create_impl.py (stripped of entity concepts)
"""

import asyncio
import logging
from typing import List, Optional
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# RDFLib imports for proper quad building with type preservation
from rdflib import URIRef, Literal, BNode

# Domain model imports
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

# Backend adapter import
from vitalgraph.kg_impl.kg_backend_utils import KGBackendInterface


def _sparql_binding_to_rdflib(binding):
    """
    Convert a SPARQL result binding to the corresponding RDFLib object,
    preserving datatype and language info.
    """
    if isinstance(binding, dict):
        value = binding.get('value', '')
        term_type = binding.get('type', 'literal')
        if term_type == 'uri':
            return URIRef(value)
        elif term_type == 'literal':
            datatype = binding.get('datatype')
            language = binding.get('language')
            if datatype:
                return Literal(value, datatype=URIRef(datatype))
            elif language:
                return Literal(value, lang=language)
            else:
                return Literal(value)
        elif term_type == 'bnode':
            return BNode(value)
    if isinstance(binding, str):
        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
        if validate_rfc3986(binding, rule='URI'):
            return URIRef(binding)
        return Literal(binding)
    return Literal(str(binding))


@dataclass
class FrameObjectCategories:
    """Categorization of frame objects by type."""
    frame_objects: List[GraphObject]
    slot_objects: List[GraphObject]
    edge_objects: List[GraphObject]


@dataclass
class CreateFrameResult:
    """Result of frame creation operation."""
    success: bool
    created_uris: List[str]
    message: str
    frame_count: int
    fuseki_success: Optional[bool] = None


class KGFrameCreateProcessor:
    """
    Processor for standalone frame CRUD operations.

    Uses frameGraphURI as the sole grouping mechanism. Each frame's immediate
    members (the frame itself, its slots, its slot edges) share the same
    frameGraphURI pointing to the frame's URI.

    No entity_uri, no kGGraphURI, no Edge_hasEntityKGFrame.
    """

    def __init__(self):
        """Initialize the standalone frame create processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()

    async def create_frame(
        self,
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        frame_objects: List[GraphObject],
        operation_mode: str = "CREATE"
    ) -> CreateFrameResult:
        """
        Create/update standalone frames.

        Process:
        1. Categorize frame objects (frames, slots, edges)
        2. Assign frameGraphURI to all members
        3. Execute atomic creation or update

        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            frame_objects: List of frame-related GraphObjects
            operation_mode: CREATE, UPDATE, or UPSERT

        Returns:
            CreateFrameResult with created URIs and metadata
        """
        try:
            import time as _time
            _t0 = _time.time()
            self.logger.debug(
                f"Standalone frame {operation_mode} in space {space_id}, graph {graph_id}"
            )

            # Step 1: Categorize frame objects
            categories = await self.categorize_frame_objects(frame_objects)

            if not categories.frame_objects:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Request must contain at least one KGFrame object",
                    frame_count=0
                )

            # Step 2: Assign frameGraphURI to all members
            all_objects = categories.frame_objects + categories.slot_objects + categories.edge_objects
            all_objects = self.assign_frame_grouping_uris(all_objects)

            _t1 = _time.time()
            self.logger.info(f"⏱️ FRAME_STANDALONE categorize+grouping: {_t1-_t0:.3f}s")

            # Step 3: Execute atomic operation
            mode_upper = str(operation_mode).upper() if operation_mode else "CREATE"

            if mode_upper in ('UPDATE', 'UPSERT'):
                success, fuseki_success = await self.execute_atomic_frame_update(
                    backend_adapter, space_id, graph_id,
                    categories.frame_objects, all_objects, mode_upper
                )
            else:
                success, fuseki_success = await self.execute_frame_creation(
                    backend_adapter, space_id, graph_id, all_objects
                )

            _t2 = _time.time()
            self.logger.info(f"⏱️ FRAME_STANDALONE total: {_t2-_t0:.3f}s")

            if success:
                created_uris = [str(obj.URI) for obj in all_objects if hasattr(obj, 'URI')]
                return CreateFrameResult(
                    success=True,
                    created_uris=created_uris,
                    message=f"Successfully processed {len(categories.frame_objects)} frames",
                    frame_count=len(categories.frame_objects),
                    fuseki_success=fuseki_success
                )
            else:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Failed to create/update frames",
                    frame_count=0,
                    fuseki_success=fuseki_success
                )

        except Exception as e:
            self.logger.error(f"Error in standalone frame {operation_mode}: {e}")
            return CreateFrameResult(
                success=False,
                created_uris=[],
                message=f"Error: {str(e)}",
                frame_count=0,
                fuseki_success=False
            )

    async def categorize_frame_objects(self, graph_objects: List[GraphObject]) -> FrameObjectCategories:
        """Categorize objects by type: frames, slots, edges."""
        frame_objects = []
        slot_objects = []
        edge_objects = []

        for obj in graph_objects:
            if isinstance(obj, VITAL_Edge):
                edge_objects.append(obj)
            elif isinstance(obj, KGFrame):
                frame_objects.append(obj)
            elif isinstance(obj, KGSlot):
                slot_objects.append(obj)

        self.logger.debug(
            f"Categorized: {len(frame_objects)} frames, {len(slot_objects)} slots, {len(edge_objects)} edges"
        )

        return FrameObjectCategories(
            frame_objects=frame_objects,
            slot_objects=slot_objects,
            edge_objects=edge_objects
        )

    def assign_frame_grouping_uris(self, objects: List[GraphObject]) -> List[GraphObject]:
        """
        Assign frameGraphURI to all frame graph members.

        - KGFrame: frameGraphURI = own URI
        - KGSlot / VITAL_Edge: frameGraphURI = owning frame's URI

        Slot/edge ownership is determined by Edge_hasKGSlot source or by
        being the only frame in the batch (single-frame case).

        No kGGraphURI is set — that is an entity-scoped concept.
        """
        # Build a map of frame URIs for lookup
        frame_uris = {str(obj.URI) for obj in objects if isinstance(obj, KGFrame)}

        # For slots/edges, find their owning frame via edge source
        slot_to_frame = {}
        for obj in objects:
            if isinstance(obj, VITAL_Edge) and hasattr(obj, 'edgeSource') and hasattr(obj, 'edgeDestination'):
                src = str(obj.edgeSource) if obj.edgeSource else None
                dst = str(obj.edgeDestination) if obj.edgeDestination else None
                if src in frame_uris and dst:
                    slot_to_frame[dst] = src

        # Fallback: if single frame, all non-frame objects belong to it
        fallback_frame_uri = None
        if len(frame_uris) == 1:
            fallback_frame_uri = next(iter(frame_uris))

        for obj in objects:
            if isinstance(obj, KGFrame):
                obj.frameGraphURI = str(obj.URI)
                # Standalone frames are Assertions (top-level independent facts)
                if not getattr(obj, 'kGFormType', None):
                    obj.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Assertion"
            elif isinstance(obj, KGSlot):
                owning_frame = slot_to_frame.get(str(obj.URI), fallback_frame_uri)
                if owning_frame:
                    obj.frameGraphURI = owning_frame
            elif isinstance(obj, VITAL_Edge):
                # Edge belongs to the frame it sources from
                src = str(obj.edgeSource) if hasattr(obj, 'edgeSource') and obj.edgeSource else None
                if src in frame_uris:
                    obj.frameGraphURI = src
                elif fallback_frame_uri:
                    obj.frameGraphURI = fallback_frame_uri

        return objects

    async def execute_frame_creation(self, backend_adapter: KGBackendInterface, space_id: str,
                                     graph_id: str, all_objects: List[GraphObject]) -> tuple:
        """
        Execute atomic frame creation via subject-level delete + insert.
        """
        try:
            import time as _time
            _t0 = _time.time()

            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            _t1 = _time.time()
            self.logger.info(f"⏱️ FRAME_CREATE step1 build_insert_quads: {_t1-_t0:.3f}s ({len(insert_quads)} quads)")

            if hasattr(backend_adapter, 'update_subjects_graph'):
                subject_uris = list({str(obj.URI) for obj in all_objects
                                     if hasattr(obj, 'URI') and obj.URI})
                success = await backend_adapter.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads)
                _t2 = _time.time()
                self.logger.info(f"⏱️ FRAME_CREATE step2 update_subjects_graph: {_t2-_t1:.3f}s")
            else:
                delete_quads = await self._build_delete_quads_for_subjects(
                    backend_adapter, space_id, graph_id, all_objects)
                success = await backend_adapter.update_quads(
                    space_id, graph_id, delete_quads, insert_quads)
                _t2 = _time.time()
                self.logger.info(f"⏱️ FRAME_CREATE fallback update_quads: {_t2-_t1:.3f}s")

            return (True, True) if success else (False, False)

        except Exception as e:
            self.logger.error(f"Error executing frame creation: {e}")
            return (False, False)

    async def execute_atomic_frame_update(self, backend_adapter: KGBackendInterface, space_id: str,
                                          graph_id: str, frame_objects: List[GraphObject],
                                          all_objects: List[GraphObject], operation_mode: str) -> tuple:
        """
        Execute atomic frame UPDATE/UPSERT via subject-level delete + insert.
        """
        try:
            import time as _time
            _t0 = _time.time()

            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            _t1 = _time.time()

            if hasattr(backend_adapter, 'update_subjects_graph'):
                subject_uris = list({str(obj.URI) for obj in all_objects
                                     if hasattr(obj, 'URI') and obj.URI})
                success = await backend_adapter.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads)
            else:
                delete_quads = await self.build_delete_quads_for_frames(
                    backend_adapter, space_id, graph_id, frame_objects)
                # Diff to minimize writes
                def _quad_key(q):
                    return (str(q[0]), str(q[1]), str(q[2]), str(q[3]))
                old_keys = {_quad_key(q) for q in delete_quads}
                new_keys = {_quad_key(q) for q in insert_quads}
                unchanged = old_keys & new_keys
                actual_deletes = [q for q in delete_quads if _quad_key(q) not in unchanged]
                actual_inserts = [q for q in insert_quads if _quad_key(q) not in unchanged]
                success = await backend_adapter.update_quads(
                    space_id, graph_id, actual_deletes, actual_inserts)

            _t2 = _time.time()
            self.logger.info(f"⏱️ FRAME_UPDATE total: {_t2-_t0:.3f}s")

            return (True, True) if success else (False, False)

        except Exception as e:
            self.logger.error(f"Error in atomic frame update: {e}")
            return (False, False)

    async def build_insert_quads_for_objects(self, all_objects: List[GraphObject], graph_id: str) -> list:
        """Build insert quads from VitalSigns objects."""
        try:
            triples = await asyncio.to_thread(GraphObject.to_triples_list, all_objects)
            insert_quads = [(str(s), str(p), o, graph_id) for s, p, o in triples]
            return insert_quads
        except Exception as e:
            self.logger.error(f"Error building insert quads: {e}")
            return []

    async def build_delete_quads_for_frames(self, backend_adapter: KGBackendInterface,
                                            space_id: str, graph_id: str,
                                            frame_objects: List[GraphObject]) -> list:
        """Build delete quads for existing frame data using frameGraphURI lookup."""
        try:
            delete_quads = []
            frame_uris = [str(obj.URI) for obj in frame_objects if hasattr(obj, 'URI')]

            for frame_uri in frame_uris:
                # Find all subjects grouped under this frame
                query = f"""
                SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject <http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI> <{frame_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                """
                results = await backend_adapter.execute_sparql_query(space_id, query)

                bindings = []
                if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                    bindings = results['results'].get('bindings', [])
                elif isinstance(results, list):
                    bindings = results

                for row in bindings:
                    if isinstance(row, dict) and all(k in row for k in ('subject', 'predicate', 'object')):
                        s = str(row['subject'].get('value', '')) if isinstance(row['subject'], dict) else str(row['subject'])
                        p = str(row['predicate'].get('value', '')) if isinstance(row['predicate'], dict) else str(row['predicate'])
                        o = _sparql_binding_to_rdflib(row.get('object', ''))
                        if s and p and o is not None:
                            delete_quads.append((s, p, o, graph_id))

                # Also get the frame's own triples
                frame_query = f"""
                SELECT DISTINCT ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?predicate ?object .
                    }}
                }}
                """
                frame_results = await backend_adapter.execute_sparql_query(space_id, frame_query)

                frame_bindings = []
                if isinstance(frame_results, dict) and 'results' in frame_results and isinstance(frame_results['results'], dict):
                    frame_bindings = frame_results['results'].get('bindings', [])
                elif isinstance(frame_results, list):
                    frame_bindings = frame_results

                for row in frame_bindings:
                    if isinstance(row, dict) and all(k in row for k in ('predicate', 'object')):
                        p = str(row['predicate'].get('value', '')) if isinstance(row['predicate'], dict) else str(row['predicate'])
                        o = _sparql_binding_to_rdflib(row.get('object', ''))
                        if p and o is not None:
                            delete_quads.append((frame_uri, p, o, graph_id))

            return delete_quads

        except Exception as e:
            self.logger.error(f"Error building delete quads: {e}")
            return []

    async def _build_delete_quads_for_subjects(self, backend_adapter: KGBackendInterface,
                                               space_id: str, graph_id: str,
                                               all_objects: List[GraphObject]) -> list:
        """Query existing triples for subjects about to be inserted."""
        try:
            subject_uris = {str(obj.URI) for obj in all_objects if hasattr(obj, 'URI') and obj.URI}
            if not subject_uris:
                return []

            subject_values = " ".join(f"<{uri}>" for uri in subject_uris)
            query = f"""SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    VALUES ?subject {{ {subject_values} }}
                    ?subject ?predicate ?object .
                }}
            }}"""

            results = await backend_adapter.execute_sparql_query(space_id, query)

            delete_quads = []
            bindings = []
            if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                bindings = results['results'].get('bindings', [])
            elif isinstance(results, list):
                bindings = results

            for row in bindings:
                if isinstance(row, dict):
                    s = str(row['subject'].get('value', '')) if isinstance(row.get('subject'), dict) else str(row.get('subject', ''))
                    p = str(row['predicate'].get('value', '')) if isinstance(row.get('predicate'), dict) else str(row.get('predicate', ''))
                    o = _sparql_binding_to_rdflib(row.get('object', ''))
                    if s and p and o is not None:
                        delete_quads.append((s, p, o, graph_id))

            return delete_quads

        except Exception as e:
            self.logger.error(f"Error building delete quads for subjects: {e}")
            return []
