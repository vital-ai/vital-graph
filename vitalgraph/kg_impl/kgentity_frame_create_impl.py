#!/usr/bin/env python3
"""
KGEntity Frame Create Processor Implementation

This module provides the KGEntityFrameCreateProcessor class for creating frames
and linking them to existing KGEntities following the kg_impl processor pattern.

REFACTORING SOURCE: Extracted from KGEntitiesEndpoint._create_or_update_frames()
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# RDFLib imports for proper quad building with type preservation
from rdflib import URIRef, Literal, BNode

# Domain model imports for edge creation and type categorization
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

# Backend adapter import
from vitalgraph.kg_impl.kg_backend_utils import (
    EntityAbsent, GuardUnsatisfiable, KGBackendInterface, StaleWrite,
    entity_present_precheck)
from vitalgraph.kg_impl.edge_uris import edge_uri
from vitalgraph.kg_impl.frame_grouping import UngroupableSlot, assign_frame_groupings
from .refusals import RequestRefused


def _sparql_binding_to_rdflib(binding) -> Any:
    """
    Convert a SPARQL result binding (dict with value/type/datatype/language)
    to the corresponding RDFLib object, preserving datatype and language info.

    Handles:
        - {"type": "uri", "value": "..."} → URIRef
        - {"type": "literal", "value": "...", "datatype": "..."} → Literal with datatype
        - {"type": "literal", "value": "...", "language": "..."} → Literal with lang
        - {"type": "literal", "value": "..."} → plain Literal
        - {"type": "bnode", "value": "..."} → BNode
        - plain string → URIRef if valid URI, else Literal
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
    # Fallback for plain strings
    if isinstance(binding, str):
        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
        if validate_rfc3986(binding, rule='URI'):
            return URIRef(binding)
        return Literal(binding)
    return Literal(str(binding))


@dataclass
class FrameObjectCategories:
    """Categorization of frame objects by type.

    `unhandled` carries what matched NONE of the three types. It exists because
    this classification had no `else` and so lost such objects silently: a
    caller passing the `KGEntity` alongside its frames — the natural way to
    change an entity property and a frame slot in one write — had the entity
    node dropped here and still got `status: "updated"` (`issues/225`).

    Kept as a list rather than a count so the caller can name the types in its
    message. Nothing writes these; the point is to stop them disappearing
    without trace, not to make them work.
    """
    frame_objects: List[GraphObject]
    slot_objects: List[GraphObject]
    edge_objects: List[GraphObject]
    unhandled: List[GraphObject] = field(default_factory=list)


@dataclass
class CreateFrameResult:
    """Result of frame creation operation."""
    success: bool
    created_uris: List[str]
    message: str
    frame_count: int
    # Type names present in the payload that were NOT written. Carried so the
    # caller's message can say so: reporting plain success for a payload that
    # was partly discarded is `issues/225`.
    unhandled_types: List[str] = field(default_factory=list)
    # Subjects an update/upsert DELETED that the request did not re-send: the
    # rest of a replaced frame graph (`issues/256`). The caller clears their
    # vector/geo/fuzzy rows; their FTS rows were cleared in the transaction.
    removed_uris: List[str] = field(default_factory=list)


class KGEntityFrameCreateProcessor:
    """
    Processor for creating frames and linking them to existing KGEntities.
    
    REFACTORING SOURCE: Extract logic from KGEntitiesEndpoint._create_or_update_frames()
    
    Handles:
    - Frame object creation with proper properties
    - Edge_hasEntityKGFrame creation for entity-frame linking  
    - Grouping URI assignment (entity-level + frame-level)
    - Frame graph validation and structure analysis
    - Backend integration for atomic frame creation operations
    - UPDATE/UPSERT operations with existing frame deletion
    """
    
    def __init__(self):
        """Initialize the frame create processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()
    
    async def create_entity_frame(
        self,
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        frame_objects: List[GraphObject],
        operation_mode: str = "CREATE",
        parent_frame_uri: Optional[str] = None,
        if_unmodified_since: Optional[str] = None,
    ) -> CreateFrameResult:
        """
        Create frame graph and link to existing entity.
        
        EXTRACTED FROM: _create_or_update_frames() lines 937-1164
        
        Process:
        1. Validate entity exists (existing: lines 957-959)
        2. Categorize frame objects (existing: lines 980-993)
        3. Set dual grouping URIs (existing: lines 995-1011)
        4. Create Edge_hasEntityKGFrame objects (existing: lines 1019-1040)
        5. Handle UPDATE/UPSERT deletion (existing: lines 1061-1123)
        6. Execute atomic creation via backend (existing: lines 1125-1145)
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: URI of the target entity
            frame_objects: List of frame-related GraphObjects
            operation_mode: CREATE, UPDATE, or UPSERT
            
        Returns:
            CreateFrameResult with created URIs and metadata
        """
        try:
            import time as _time
            _p0 = _time.time()
            if parent_frame_uri:
                self.logger.debug(f"Creating/updating CHILD frames for entity {entity_uri} in space {space_id}, graph {graph_id}, parent_frame_uri={parent_frame_uri}, operation_mode={operation_mode}")
            else:
                self.logger.debug(f"Creating/updating TOP-LEVEL frames for entity {entity_uri} in space {space_id}, graph {graph_id}, operation_mode={operation_mode}")
            
            # Step 1, THE ENTITY EXISTS, is no longer checked here (`issues/256`):
            # a create passes it to the write as a `precheck`, decided under the
            # entity lock. Checked here, a create could pass, wait on the lock
            # while the entity was deleted, and then write frames onto nothing.
            # UPDATE/UPSERT rely on the ownership check upstream, as before.
            _p1 = _time.time()

            # Steps 2-5: categorise, group, link.
            creating = not operation_mode or str(operation_mode).upper() not in ['UPDATE', 'UPSERT']
            categories, all_objects = await self.prepare_entity_frame_objects(
                entity_uri, frame_objects, parent_frame_uri, create_links=creating)
            if not categories.frame_objects:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Request must contain at least one KGFrame object",
                    frame_count=0
                )
            
            _p2 = _time.time()
            self.logger.info(f"⏱️ PROCESSOR categorize+grouping+edges: {_p2-_p1:.3f}s")
            
            # Step 6: Execute atomic UPDATE/UPSERT or CREATE operation
            _removed: List[str] = []
            if operation_mode and str(operation_mode).upper() in ['UPDATE', 'UPSERT']:
                success = await self.execute_atomic_frame_update(backend_adapter, space_id, graph_id, 
                                                               categories.frame_objects, all_objects, operation_mode,
                                                                 entity_uri=entity_uri,
                                                                 if_unmodified_since=if_unmodified_since,
                                                                 removed_uris=_removed)
            else:
                # Step 7: Execute atomic creation via backend (extracted from lines 1125-1145)
                success = await self.execute_frame_creation(backend_adapter, space_id, graph_id, all_objects,
                                                                            entity_uri=entity_uri,
                                                                            if_unmodified_since=if_unmodified_since,
                                                                            precheck=entity_present_precheck(
                                                                                space_id, graph_id, entity_uri))
            
            if success:
                created_uris = [str(obj.URI) for obj in all_objects if hasattr(obj, 'URI')]
                self.logger.debug(f"Successfully created/updated {len(created_uris)} frame objects")
                
                _unhandled = sorted({type(o).__name__ for o in categories.unhandled})
                _msg = f"Successfully created {len(categories.frame_objects)} frames"
                if _unhandled:
                    # Say it in the MESSAGE, not only the log. The caller sees
                    # this string; it is the only place a discarded object can
                    # still be noticed (`issues/225`).
                    _msg += (f"; {len(categories.unhandled)} object(s) NOT written "
                             f"({', '.join(_unhandled)})")

                return CreateFrameResult(
                    success=True,
                    created_uris=created_uris,
                    message=_msg,
                    frame_count=len(categories.frame_objects),
                    unhandled_types=_unhandled,
                    removed_uris=_removed,
                )
            else:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Failed to create/update frames",
                    frame_count=0,
                )
                
        except EntityAbsent as e:
            # The same answer the pre-lock check gave, so the route's status for
            # a missing entity does not change: only WHEN it is decided does.
            return CreateFrameResult(
                success=False, created_uris=[], message=str(e), frame_count=0)
        except (StaleWrite, GuardUnsatisfiable, RequestRefused):
            # A REFUSAL, not a failure, and the difference is the whole point
            # (`issues/253`): the caller must be told its entity moved so it can
            # re-read and merge, where a generic failure tells it to give up or
            # to replay the same losing write. Every broad `except` between the
            # guard and the endpoint has to let this one past, and three of them
            # did not — the refusal arrived over HTTP as `store_failed`.
            raise
        except Exception as e:
            self.logger.error(f"Error creating/updating frames: {e}")
            return CreateFrameResult(
                success=False,
                created_uris=[],
                message=f"Error creating/updating frames: {str(e)}",
                frame_count=0,
            )
    
    async def prepare_entity_frame_objects(self, entity_uri: str, frame_objects: List[GraphObject],
                                           parent_frame_uri: Optional[str] = None,
                                           create_links: bool = True):
        """Categorise, group and (for a create or replace) link a request's objects.

        Returns (categories, all_objects). Nothing is written. Shared by
        `create_entity_frame` and `replace_entity_frames`, so a replace writes
        exactly what a create would.
        """
        categories = await self.categorize_frame_objects(frame_objects)
        if not categories.frame_objects:
            return categories, []
        # ALL objects, not just frames, so hierarchical child frames get
        # kGGraphURI set.
        all_input_objects = categories.frame_objects + categories.slot_objects + categories.edge_objects
        all_objects = await self.assign_grouping_uris(all_input_objects, entity_uri)
        # Linking edges only on create/replace: on UPDATE/UPSERT they exist.
        if create_links:
            if parent_frame_uri:
                all_objects.extend(self._create_parent_child_edges(
                    parent_frame_uri, entity_uri, categories.frame_objects))
            else:
                all_objects.extend(await self.create_entity_frame_edges(
                    entity_uri, categories.frame_objects))
        return categories, all_objects

    async def replace_entity_frames(self, backend_adapter: KGBackendInterface, space_id: str,
                                    graph_id: str, entity_uri: str,
                                    frame_objects: List[GraphObject],
                                    parent_frame_uri: Optional[str] = None,
                                    if_unmodified_since: Optional[str] = None) -> CreateFrameResult:
        """Replace the named frames and their descendants, in ONE locked transaction.

        `issues/256` item 4. Scope is what the request NAMES: each frame in it,
        plus its descendants in the store. The entity's other frames, and a
        parent's other children, are untouched — this used to delete every
        top-level frame of the entity, or every child of the parent, whatever
        the request named. Deep: a descendant the request does not re-send is
        gone. A frame not there yet is created.

        Ownership, the entity's existence, the guard (on the entity), the delete,
        the insert and the entity stamp are one transaction under the entity lock
        (`delete_frame_subtrees`), so a refused or failed replace leaves the old
        frames as they were. The links are re-created by the request, so the old
        ones into the subtree go.
        """
        categories, all_objects = await self.prepare_entity_frame_objects(
            entity_uri, frame_objects, parent_frame_uri, create_links=True)
        if not categories.frame_objects:
            return CreateFrameResult(
                success=False, created_uris=[], frame_count=0,
                message="Request must contain at least one KGFrame object")
        insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
        written = list(dict.fromkeys(str(o.URI) for o in all_objects
                                     if getattr(o, 'URI', None)))
        result = await backend_adapter.delete_frame_subtrees(
            space_id, graph_id, [str(f.URI) for f in categories.frame_objects],
            recursive=True, owner_entity_uri=entity_uri,
            if_unmodified_since=if_unmodified_since,
            insert_quads=insert_quads, insert_subjects=written,
            keep_outside_links=False,
            precheck=entity_present_precheck(space_id, graph_id, entity_uri))
        _written = set(written)
        return CreateFrameResult(
            success=True, created_uris=written,
            message=(f"Replaced {len(result.deleted_frames)} frame(s) with "
                     f"{len(categories.frame_objects)}"),
            frame_count=len(categories.frame_objects),
            unhandled_types=sorted({type(o).__name__ for o in categories.unhandled}),
            removed_uris=[u for u in result.member_uris if u not in _written])

    # `validate_entity_exists` was DELETED 2026-10-04 (`issues/256`): the check
    # runs inside the write transaction now (`entity_present_precheck`).

    async def categorize_frame_objects(self, graph_objects: List[GraphObject]) -> FrameObjectCategories:
        """
        Categorize objects by type: frames, slots, edges.
        EXTRACTED FROM: lines 980-993 in _create_or_update_frames()
        
        Args:
            graph_objects: List of GraphObjects to categorize
            
        Returns:
            FrameObjectCategories with categorized objects
        """
        frame_objects = []
        slot_objects = []
        edge_objects = []
        
        unhandled = []

        # First pass: categorize objects by type (extracted from lines 980-993)
        for obj in graph_objects:
            if isinstance(obj, VITAL_Edge):
                edge_objects.append(obj)
            elif isinstance(obj, KGFrame):
                frame_objects.append(obj)
            elif isinstance(obj, KGSlot):
                slot_objects.append(obj)
            else:
                # ANYTHING ELSE IS NOT WRITTEN, AND MUST NOT VANISH QUIETLY.
                #
                # This branch did not exist, so an object of any other type
                # joined no list and ceased to exist here. The caller still got
                # success and `status: "updated"`, because the frames it DID
                # recognise were written -- `issues/225`.
                #
                # The live case is a `KGEntity`: passing it alongside its frames
                # is the natural way to change an entity property and a frame
                # slot in one write, and it is validated, has its grouping URI
                # assigned, and is then dropped right here.
                #
                # Collected rather than raised. Rejecting outright would break
                # any caller that has been passing extra objects harmlessly, and
                # the defect is the SILENCE, not the discarding. The caller
                # decides what to say about it.
                unhandled.append(obj)

        if unhandled:
            self.logger.warning(
                "⚠️ %d object(s) in the payload are not frames, slots or edges "
                "and will NOT be written: %s. See issues/225.",
                len(unhandled),
                ", ".join(sorted({type(o).__name__ for o in unhandled})))

        self.logger.debug(f"📦 Categorized objects: {len(frame_objects)} frames, {len(slot_objects)} slots, {len(edge_objects)} edges, {len(unhandled)} unhandled")

        return FrameObjectCategories(
            frame_objects=frame_objects,
            slot_objects=slot_objects,
            edge_objects=edge_objects,
            unhandled=unhandled
        )
    
    async def assign_grouping_uris(self, frame_objects: List[GraphObject], 
                                 entity_uri: str) -> List[GraphObject]:
        """
        Assign dual grouping URIs to frame objects.
        
        Entity-level: kGGraphURI = entity_uri (for complete entity retrieval)
        Frame-level:  frameGraphURI = immediate owning frame URI
        
        Slot/edge ownership is determined by Edge_hasKGSlot source edges.
        Each frame's frameGraphURI points to itself.
        Each slot's frameGraphURI points to the frame that owns it.
        Each slot-edge's frameGraphURI points to the frame it sources from.
        
        Args:
            frame_objects: List of frame-related GraphObjects
            entity_uri: URI of the target entity
            
        Returns:
            List[GraphObject]: Objects with assigned grouping URIs
        """
        # Frame-level grouping is decided in ONE place (`issues/257`): every
        # frame with itself, every slot with the frame its Edge_hasKGSlot
        # names, and nothing the client sent survives. This kept a client's
        # value for a slot whose edge was not in a multi-frame payload, and for
        # an edge whose source frame was not in the payload. Raises
        # `UngroupableSlot` for a slot it cannot place.
        assign_frame_groupings(frame_objects)

        for obj in frame_objects:
            # Entity-level grouping on ALL objects
            obj.kGGraphURI = entity_uri
            # Entity-enclosed frames are Aspects
            if isinstance(obj, KGFrame) and not getattr(obj, 'kGFormType', None):
                obj.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect"
        
        return frame_objects
    
    async def create_entity_frame_edges(self, entity_uri: str, 
                                      frame_objects: List[GraphObject]) -> List[GraphObject]:
        """
        Create Edge_hasEntityKGFrame linking objects for entity-to-frame connections.
        EXTRACTED FROM: lines 1019-1040 in _create_or_update_frames()
        
        Args:
            entity_uri: URI of the target entity
            frame_objects: List of KGFrame objects
            
        Returns:
            List[GraphObject]: Created Edge_hasEntityKGFrame objects
        """
        entity_frame_edges = []

        # Create Edge_hasEntityKGFrame edges server-side for each frame (extracted from lines 1019-1040)
        for frame_obj in frame_objects:
            # DETERMINISTIC, from the two endpoints (`issues/253`). A `uuid4()`
            # here meant re-creating a frame added a SECOND edge to it rather
            # than rewriting the first — the subject-level delete cannot remove
            # an edge whose URI it has just invented — which is also why a
            # timed-out POST could not be retried.
            entity_frame_edge = Edge_hasEntityKGFrame()
            entity_frame_edge.URI = edge_uri(
                "Edge_hasEntityKGFrame", entity_uri, frame_obj.URI)
            entity_frame_edge.edgeSource = entity_uri
            entity_frame_edge.edgeDestination = frame_obj.URI
            
            # Debug: Verify edge properties are set correctly
            self.logger.debug(f"🔍 Edge properties: URI={entity_frame_edge.URI}, edgeSource={getattr(entity_frame_edge, 'edgeSource', 'NOT_SET')}, edgeDestination={getattr(entity_frame_edge, 'edgeDestination', 'NOT_SET')}")
            
            # Debug: Test individual edge triple generation
            edge_triples = await asyncio.to_thread(GraphObject.to_triples_list, [entity_frame_edge])
            self.logger.debug(f"🔍 Edge {entity_frame_edge.URI} generates {len(edge_triples)} triples:")
            for i, (s, p, o) in enumerate(edge_triples):
                self.logger.debug(f"  Edge triple {i+1}: s={repr(str(s))}, p={repr(str(p))}, o={repr(str(o))}")
            
            # Set grouping URIs for the edge
            if hasattr(entity_frame_edge, 'kGGraphURI'):
                entity_frame_edge.kGGraphURI = entity_uri
            
            entity_frame_edges.append(entity_frame_edge)
            
            self.logger.debug(f"🔗 Created entity-to-frame edge: {entity_uri} -> {frame_obj.URI}")
        
        return entity_frame_edges
    
    def _create_parent_child_edges(self, parent_frame_uri: str, entity_uri: str,
                                   frame_objects: List[GraphObject]) -> List[GraphObject]:
        """
        Create Edge_hasKGFrame linking objects for parent-to-child frame connections.
        
        Args:
            parent_frame_uri: URI of the parent frame
            entity_uri: URI of the entity (for kGGraphURI)
            frame_objects: List of child KGFrame objects
            
        Returns:
            List[GraphObject]: Created Edge_hasKGFrame objects
        """
        edges = []
        for frame_obj in frame_objects:
            if not isinstance(frame_obj, KGFrame):
                continue
            child_uri = str(frame_obj.URI)

            edge = Edge_hasKGFrame()
            # Already deterministic; `edge_uri` produces the identical string and
            # is where the convention now lives (`issues/253`).
            edge.URI = edge_uri("Edge_hasKGFrame", parent_frame_uri, child_uri)
            edge.edgeSource = parent_frame_uri
            edge.edgeDestination = child_uri
            if hasattr(edge, 'kGGraphURI'):
                edge.kGGraphURI = entity_uri
            
            edges.append(edge)
            self.logger.debug(f"🔗 Created parent-child frame edge: {parent_frame_uri} -> {child_uri}")
        
        return edges
    
    async def execute_atomic_frame_update(self, backend_adapter: KGBackendInterface, space_id: str,
                                        graph_id: str, frame_objects: List[GraphObject], all_objects: List[GraphObject],
                                        operation_mode: str,
                                        entity_uri: Optional[str] = None,
                                        if_unmodified_since: Optional[str] = None,
                                        removed_uris: Optional[List[str]] = None) -> tuple:
        """
        Execute atomic frame UPDATE/UPSERT: each frame's WHOLE graph is replaced.

        `issues/256`: the frames in the request are passed as
        `replace_frame_graphs`, so everything grouped under them that the
        request does not re-send is deleted. This deleted only the subjects in
        the request, which made update and upsert a merge: a slot left out
        survived, still attached.
        
        Collects subject URIs from all objects being written, deletes their
        existing quads via direct SQL, then inserts new quads — all in one
        transaction.  Falls back to SPARQL-based quad diff for backends
        without update_subjects_graph.
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier  
            frame_objects: List of frame objects being updated
            all_objects: All GraphObjects to create (frames, slots, edges)
            operation_mode: 'UPDATE' or 'UPSERT'
            
        Returns:
            True if the operation committed.
        """
        try:
            import time
            t0 = time.time()
            self.logger.debug(f"🔄 Executing atomic frame {operation_mode} for {len(frame_objects)} frames")
            
            # Step 1: Build insert quads for new frame data
            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            t1 = time.time()
            self.logger.info(f"⏱️ FRAME_UPDATE step1 build_insert_quads: {t1-t0:.3f}s ({len(insert_quads)} quads)")
            
            # Step 2: Subject-level delete + insert (safe path)
            if hasattr(backend_adapter, 'update_subjects_graph'):
                # Collect all subject URIs from both frame objects and child objects
                subject_uris = list({str(obj.URI) for obj in all_objects
                                     if hasattr(obj, 'URI') and obj.URI})
                # Serialise on the grouping (`issues/174`): entity upsert and
                # entity-graph delete hold the entity key, so a frame write must
                # take the same one to be excluded from them.
                success = await backend_adapter.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads,
                    lock_uris=[entity_uri] if entity_uri else None,
                    # The guard and the stamp both key on the OWNING ENTITY, the
                    # same thing the lock keys on (`issues/253`). Stamping here
                    # rather than after the write is what makes the comparison
                    # race-free for the next writer.
                    if_unmodified_since=if_unmodified_since,
                    guard_subject=entity_uri,
                    replace_frame_graphs=[str(f.URI) for f in frame_objects
                                          if getattr(f, 'URI', None)],
                    removed_uris=removed_uris)
                t2 = time.time()
                self.logger.info(f"⏱️ FRAME_UPDATE step2 update_subjects_graph: {t2-t1:.3f}s "
                               f"({len(subject_uris)} subjects, {len(insert_quads)} quads)")
                self.logger.info(f"⏱️ FRAME_UPDATE total: {t2-t0:.3f}s")
            else:
                # Fallback: SPARQL-based quad diff + update_quads
                delete_quads = await self.build_delete_quads_for_frames(
                    backend_adapter, space_id, graph_id, frame_objects)
                t2 = time.time()
                self.logger.info(f"⏱️ FRAME_UPDATE step2 build_delete_quads: {t2-t1:.3f}s ({len(delete_quads)} quads)")
                
                def _quad_str_key(q):
                    return (str(q[0]), str(q[1]), str(q[2]), str(q[3]))
                
                old_key_map = {_quad_str_key(q): q for q in delete_quads}
                new_key_map = {_quad_str_key(q): q for q in insert_quads}
                unchanged_keys = set(old_key_map.keys()) & set(new_key_map.keys())
                actual_deletes = [old_key_map[k] for k in set(old_key_map.keys()) - unchanged_keys]
                actual_inserts = [new_key_map[k] for k in set(new_key_map.keys()) - unchanged_keys]
                self.logger.info(f"⏱️ FRAME_UPDATE diff: {len(unchanged_keys)} unchanged, "
                               f"{len(actual_deletes)} to delete, {len(actual_inserts)} to insert")
                
                success = await backend_adapter.update_quads(space_id, graph_id, actual_deletes, actual_inserts)
                t3 = time.time()
                self.logger.info(f"⏱️ FRAME_UPDATE step3 update_quads: {t3-t2:.3f}s")
                self.logger.info(f"⏱️ FRAME_UPDATE total: {t3-t0:.3f}s")
            
            if success:
                self.logger.debug(f"✅ Atomic frame {operation_mode} completed successfully")
                return True
            else:
                self.logger.error(f"❌ Atomic frame {operation_mode} failed")
                return False
                
        except (StaleWrite, GuardUnsatisfiable, RequestRefused):
            raise                     # a refusal must reach the caller as one
        except Exception as e:
            self.logger.error(f"Error in atomic frame {operation_mode}: {e}")
            return False
    
    async def build_delete_quads_for_frames(self, backend_adapter: KGBackendInterface, space_id: str,
                                          graph_id: str, frame_objects: List[GraphObject]) -> List[tuple]:
        """
        Build delete quads for existing frame data that needs to be replaced.
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            frame_objects: List of frame objects being updated
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to delete
        """
        try:
            delete_quads = []
            
            # Get frame URIs that are being updated
            frame_uris = [str(obj.URI) for obj in frame_objects if hasattr(obj, 'URI')]
            
            if not frame_uris:
                self.logger.debug("🔍 No frame URIs found for delete quad building")
                return delete_quads
            
            self.logger.debug(f"🔍 Building delete quads for {len(frame_uris)} frames")
            
            # For each frame, find all subjects that belong to it via frameGraphURI
            for frame_uri in frame_uris:
                # Query to find all subjects that have hasFrameGraphURI pointing to this frame
                find_subjects_query = f"""
                SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject <http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI> <{frame_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                """
                
                self.logger.debug(f"🔍 Finding triples for frame: {frame_uri}")
                self.logger.debug(f"🔍 Delete query: {find_subjects_query}")
                results = await backend_adapter.execute_sparql_query(space_id, find_subjects_query)
                self.logger.debug(f"🔍 Delete query results: {results}")
                
                # Convert SPARQL results to delete quads - handle nested structure
                bindings = []
                if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                    bindings = results['results'].get('bindings', [])
                elif isinstance(results, list):
                    bindings = results
                
                for result in bindings:
                    if isinstance(result, dict) and all(key in result for key in ['subject', 'predicate', 'object']):
                        subject = str(result['subject'].get('value', '')) if isinstance(result['subject'], dict) else str(result['subject'])
                        predicate = str(result['predicate'].get('value', '')) if isinstance(result['predicate'], dict) else str(result['predicate'])
                        
                        # Reconstruct RDFLib object from full binding to preserve datatype/language
                        o = _sparql_binding_to_rdflib(result.get('object', ''))
                        
                        if subject and predicate and o is not None:
                            delete_quads.append((subject, predicate, o, graph_id))
                
                # Also include the frame itself - find all its triples
                frame_triples_query = f"""
                SELECT DISTINCT ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?predicate ?object .
                    }}
                }}
                """
                
                frame_results = await backend_adapter.execute_sparql_query(space_id, frame_triples_query)
                
                # Handle nested structure for frame results
                frame_bindings = []
                if isinstance(frame_results, dict) and 'results' in frame_results and isinstance(frame_results['results'], dict):
                    frame_bindings = frame_results['results'].get('bindings', [])
                elif isinstance(frame_results, list):
                    frame_bindings = frame_results
                
                for result in frame_bindings:
                    if isinstance(result, dict) and all(key in result for key in ['predicate', 'object']):
                        predicate = str(result['predicate'].get('value', '')) if isinstance(result['predicate'], dict) else str(result['predicate'])
                        # Reconstruct RDFLib object from full binding to preserve datatype/language
                        o = _sparql_binding_to_rdflib(result.get('object', ''))
                        
                        if predicate and o is not None:
                            delete_quads.append((frame_uri, predicate, o, graph_id))
            
            self.logger.debug(f"🔍 Built {len(delete_quads)} delete quads")
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads: {e}")
            return []
    
    async def build_insert_quads_for_objects(self, all_objects: List[GraphObject], graph_id: str) -> List[tuple]:
        """
        Build insert quads for new frame data.
        
        Args:
            all_objects: All GraphObjects to create (frames, slots, edges)
            graph_id: Graph identifier
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to insert
        """
        try:
            self.logger.debug(f"🔍 Building insert quads for {len(all_objects)} objects")
            
            # Log each object type, URI, and check for kGGraphURI property
            for i, obj in enumerate(all_objects):
                obj_type = type(obj).__name__
                obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                has_kg_graph_uri = hasattr(obj, 'kGGraphURI')
                kg_graph_uri_value = str(obj.kGGraphURI) if has_kg_graph_uri and obj.kGGraphURI else 'NOT_SET'
                self.logger.debug(f"🔍   Object {i+1}: {obj_type} - {obj_uri}")
                self.logger.debug(f"🔍   Has kGGraphURI: {has_kg_graph_uri}, Value: {kg_graph_uri_value}")
            
            # Convert VitalSigns objects to triples (offload to thread to avoid blocking event loop)
            triples = await asyncio.to_thread(GraphObject.to_triples_list, all_objects)
            
            self.logger.debug(f"🔍 to_triples_list returned {len(triples)} RDFLib triple objects")
            
            # Check if hasKGGraphURI triples are present
            kg_graph_uri_triples = [t for t in triples if 'hasKGGraphURI' in str(t[1])]
            frame_graph_uri_triples = [t for t in triples if 'hasFrameGraphURI' in str(t[1])]
            self.logger.debug(f"🔍 Found {len(kg_graph_uri_triples)} hasKGGraphURI triples")
            self.logger.debug(f"🔍 Found {len(frame_graph_uri_triples)} hasFrameGraphURI triples")
            
            for triple in kg_graph_uri_triples:
                s, p, o = triple
                self.logger.debug(f"🔍   hasKGGraphURI triple: {s} -> {o}")
            
            for i, triple in enumerate(triples[:10]):  # Log first 10 triples
                s, p, o = triple
                self.logger.debug(f"🔍   Triple {i+1}: {s} | {p} | {o}")
            if len(triples) > 10:
                self.logger.debug(f"🔍   ... and {len(triples) - 10} more triples")
            
            # Convert triples to quads by adding graph_id
            # Keep RDFLib objects (especially Literal with datatype/language)
            # so downstream formatters (_format_term, _format_sparql_term,
            # _extract_term_info) can preserve type information.
            insert_quads = []
            for triple in triples:
                s, p, o = triple
                insert_quads.append((str(s), str(p), o, graph_id))
            
            self.logger.debug(f"🔍 Built {len(insert_quads)} insert quads")
            return insert_quads
            
        except Exception as e:
            self.logger.error(f"Error building insert quads: {e}")
            return []

    # `handle_frame_update_deletion` was DELETED here 2026-10-02 (`issues/256`).
    # Nothing called it, and it could not have done its job: it matched
    # `haley-ai-kg#frameGraphURI`, but the property is `hasFrameGraphURI`, so it
    # found no slots and would have deleted only the frame. The frame-graph
    # replace it was meant to provide is specified in `issues/256`.
    
    async def _build_delete_quads_for_subjects(self, backend_adapter: KGBackendInterface,
                                               space_id: str, graph_id: str,
                                               all_objects: List[GraphObject]) -> List[tuple]:
        """
        Query existing triples for all subject URIs that are about to be inserted.
        Returns delete quads so that existing data is cleaned before insert,
        preventing triple accumulation when a subject is written more than once.
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            all_objects: Objects whose subject URIs will be checked
            
        Returns:
            List of (subject, predicate, object, graph) tuples to delete
        """
        try:
            subject_uris = set()
            for obj in all_objects:
                if hasattr(obj, 'URI') and obj.URI:
                    subject_uris.add(str(obj.URI))
            
            if not subject_uris:
                return []
            
            # Batch query: find all existing triples for these subjects
            subject_values = " ".join(f"<{uri}>" for uri in subject_uris)
            query = f"""SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    VALUES ?subject {{ {subject_values} }}
                    ?subject ?predicate ?object .
                }}
            }}"""
            
            results = await backend_adapter.execute_sparql_query(space_id, query)
            
            # Parse SPARQL results into quad tuples
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
                    # Reconstruct RDFLib object from full binding dict to preserve datatype/language
                    o_binding = row.get('object', '')
                    o = _sparql_binding_to_rdflib(o_binding)
                    if s and p and o is not None:
                        delete_quads.append((s, p, o, graph_id))
            
            if delete_quads:
                self.logger.info(f"🧹 Pre-cleanup: found {len(delete_quads)} existing triples for {len(subject_uris)} subjects")
            
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads for subjects: {e}")
            return []

    async def execute_frame_creation(self, backend_adapter: KGBackendInterface, space_id: str, 
                                   graph_id: str, all_objects: List[GraphObject],
                                   entity_uri: Optional[str] = None,
                                   if_unmodified_since: Optional[str] = None,
                                   precheck=None) -> bool:
        """
        Execute atomic frame creation via subject-level delete + insert.
        
        Collects all subject URIs from the objects, deletes their existing
        quads via direct SQL, then inserts the new quads — all in a single
        transaction.  This avoids the fragile SPARQL round-trip that can
        lose datatype metadata and cause silent delete failures.
        
        Falls back to the old update_quads path for backends without
        update_subjects_graph (e.g. a legacy dual-write backend).
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            all_objects: All GraphObjects to create (frames, slots, edges)
            
        Returns:
            True if the operation committed.
        """
        try:
            import time as _time
            _t0 = _time.time()
            
            self.logger.debug(f"🔍 Storing {len(all_objects)} objects to backend:")
            for obj in all_objects:
                self.logger.debug(f"  - {obj.__class__.__name__}: {getattr(obj, 'URI', 'NO_URI')}")
            
            # Step 1: Build insert quads from VitalSigns objects
            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            _t1 = _time.time()
            self.logger.info(f"⏱️ FRAME_CREATE step1 build_insert_quads: {_t1-_t0:.3f}s ({len(insert_quads)} quads)")
            
            # Step 2: Subject-level delete + insert (safe path)
            if hasattr(backend_adapter, 'update_subjects_graph'):
                subject_uris = list({str(obj.URI) for obj in all_objects
                                     if hasattr(obj, 'URI') and obj.URI})
                # Serialise on the grouping (`issues/174`): entity upsert and
                # entity-graph delete hold the entity key, so a frame write must
                # take the same one to be excluded from them.
                success = await backend_adapter.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads,
                    lock_uris=[entity_uri] if entity_uri else None,
                    # The guard and the stamp both key on the OWNING ENTITY, the
                    # same thing the lock keys on (`issues/253`). Stamping here
                    # rather than after the write is what makes the comparison
                    # race-free for the next writer.
                    if_unmodified_since=if_unmodified_since,
                    guard_subject=entity_uri,
                    precheck=precheck)
                _t2 = _time.time()
                self.logger.info(f"⏱️ FRAME_CREATE step2 update_subjects_graph: {_t2-_t1:.3f}s "
                               f"({len(subject_uris)} subjects, {len(insert_quads)} quads)")
                self.logger.info(f"⏱️ FRAME_CREATE total: {_t2-_t0:.3f}s")
            else:
                # Fallback for backends without subject-level delete
                delete_quads = await self._build_delete_quads_for_subjects(
                    backend_adapter, space_id, graph_id, all_objects)
                success = await backend_adapter.update_quads(
                    space_id, graph_id, delete_quads, insert_quads)
                _t2 = _time.time()
                self.logger.info(f"⏱️ FRAME_CREATE fallback update_quads: {_t2-_t1:.3f}s")
                self.logger.info(f"⏱️ FRAME_CREATE total: {_t2-_t0:.3f}s")
            
            if success:
                self.logger.debug(f"✅ Atomic frame creation completed successfully")
                return True
            else:
                self.logger.error(f"❌ Atomic frame creation failed")
                return False
            
        except (StaleWrite, GuardUnsatisfiable, RequestRefused):
            raise                     # a refusal must reach the caller as one
        except Exception as e:
            self.logger.error(f"Error executing frame creation: {e}")
            return False
