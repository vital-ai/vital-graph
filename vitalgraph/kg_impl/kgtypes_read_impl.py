"""
KGTypes READ Implementation for VitalGraph

This module provides READ operations for KGTypes using SPARQL queries.
Implements GET, LIST, and batch GET operations with proper VitalSigns integration.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType
from .kg_backend_utils import KGBackendInterface
from .kg_graph_retrieval_utils import GraphObjectRetriever


class KGTypesReadProcessor:
    """Processor for KGTypes READ operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGTypesReadProcessor")
        self.retriever = None  # Will be initialized when backend is available
    
    async def get_kgtype_by_uri(self, backend, space_id: str, graph_id: str, kgtype_uri: str) -> Optional[GraphObject]:
        """
        Get a single KGType by URI.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uri: URI of the KGType to retrieve
            
        Returns:
            Optional[GraphObject]: KGType GraphObject or None if not found
        """
        try:
            self.logger.debug(f"🔍 Getting KGType by URI: {kgtype_uri}")
            
            # Initialize retriever if not already done
            if self.retriever is None:
                self.retriever = GraphObjectRetriever(backend)
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, kgtype_uri, include_materialized_edges=False
            )
            
            if not triples:
                self.logger.debug(f"KGType not found: {kgtype_uri}")
                return None
            
            # Convert triples to VitalSigns GraphObject
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Log triples for debugging
            self.logger.debug(f"🔍 Converting {len(triples)} triples to GraphObject for {kgtype_uri}")
            for i, triple in enumerate(triples[:5]):  # Log first 5 triples
                self.logger.debug(f"  Triple {i+1}: {triple}")
            
            try:
                graph_object = GraphObject.from_triples(triples)
                if graph_object:
                    self.logger.debug(f"✅ Successfully created GraphObject for {kgtype_uri}")
                    self.logger.debug(f"  GraphObject type: {type(graph_object).__name__}")
                    self.logger.debug(f"  GraphObject URI: {getattr(graph_object, 'URI', 'No URI attribute')}")
                else:
                    self.logger.warning(f"⚠️  GraphObject.from_triples returned None for {kgtype_uri}")
                    return None
            except Exception as e:
                self.logger.error(f"❌ Failed to convert triples to GraphObject for {kgtype_uri}: {e}")
                return None
            
            self.logger.debug(f"✅ Retrieved KGType: {kgtype_uri} with {len(triples)} triples")
            return graph_object
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KGType {kgtype_uri}: {e}")
            raise
    
    async def get_kgtypes_by_uris(self, backend, space_id: str, graph_id: str, kgtype_uris: List[str]) -> List[GraphObject]:
        """
        Get multiple KGTypes by URIs.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            kgtype_uris: List of KGType URIs to retrieve
            
        Returns:
            List[GraphObject]: List of KGType GraphObjects (may be subclasses of KGType or KGType instances)
        """
        try:
            self.logger.debug(f"🔍 Getting {len(kgtype_uris)} KGTypes by URIs")
            
            # Initialize retriever if not already done
            if self.retriever is None:
                self.retriever = GraphObjectRetriever(backend)
            
            # Use centralized retriever (filters OUT materialized edges by default)
            grouped_triples = await self.retriever.get_objects_by_uris(
                space_id, graph_id, kgtype_uris, include_materialized_edges=False
            )
            
            # Flatten grouped triples into a single list
            triples = []
            for uri, uri_triples in grouped_triples.items():
                triples.extend(uri_triples)
            
            # Handle empty triples list
            if not triples:
                self.logger.debug(f"✅ No KGTypes found for the given URIs")
                return []
            
            # Convert RDFLib triples to VitalSigns GraphObjects
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            graph_objects = await asyncio.to_thread(GraphObject.from_triples_list, triples)
            
            self.logger.debug(f"✅ Retrieved {len(graph_objects)} KGType GraphObjects from {len(triples)} triples")
            return graph_objects
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KGTypes by URIs: {e}")
            raise
    
    # All KGType subclass URIs for unfiltered listing
    ALL_KGTYPE_URIS = [
        "http://vital.ai/ontology/haley-ai-kg#KGType",
        "http://vital.ai/ontology/haley-ai-kg#KGEntityType",
        "http://vital.ai/ontology/haley-ai-kg#KGFrameType",
        "http://vital.ai/ontology/haley-ai-kg#KGRelationType",
        "http://vital.ai/ontology/haley-ai-kg#KGSlotType",
        "http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType",
    ]

    # Known type-level edge types (source → destination)
    TYPE_EDGE_URIS = [
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasPartOfKGFrameType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasSameAsKGType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelationType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType",
        "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlotType",
    ]

    async def get_type_relationships(
        self, backend, space_id: str, graph_id: str, type_uri: str
    ) -> Dict[str, Any]:
        """
        Get all type-level edges connected to a given type URI.

        Returns a dict with:
          - edges: list of edge dicts  {uri, edgeType, sourceURI, destinationURI, direction}
          - connected_types: list of dicts {uri, name, vitaltype}
          - source_type: dict {uri, name, vitaltype}  (the queried type itself)
        """
        try:
            self.logger.debug(f"Getting type relationships for: {type_uri}")

            # Build SPARQL VALUES clause for known edge types
            edge_type_values = " ".join(
                f"<{et}>" for et in self.TYPE_EDGE_URIS
            )

            # Single SPARQL query: find all edges where type_uri is source or destination
            query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>

SELECT ?edge ?edgeType ?relatedURI ?relatedName ?relatedVitaltype ?direction
WHERE {{
  {{
    ?edge vc:vitaltype ?edgeType .
    ?edge vc:hasEdgeSource <{type_uri}> .
    ?edge vc:hasEdgeDestination ?relatedURI .
    ?relatedURI vc:hasName ?relatedName .
    ?relatedURI vc:vitaltype ?relatedVitaltype .
    VALUES ?edgeType {{ {edge_type_values} }}
    BIND("outgoing" AS ?direction)
  }}
  UNION
  {{
    ?edge vc:vitaltype ?edgeType .
    ?edge vc:hasEdgeSource ?relatedURI .
    ?edge vc:hasEdgeDestination <{type_uri}> .
    ?relatedURI vc:hasName ?relatedName .
    ?relatedURI vc:vitaltype ?relatedVitaltype .
    VALUES ?edgeType {{ {edge_type_values} }}
    BIND("incoming" AS ?direction)
  }}
}}
ORDER BY ?direction ?relatedName
"""

            results = await backend.execute_sparql_query(space_id, query)

            # Unwrap SPARQL JSON bindings
            if isinstance(results, dict):
                bindings = results.get('results', {}).get('bindings', [])
            else:
                bindings = results if results else []

            edges = []
            connected_types = {}
            for b in bindings:
                direction = b.get('direction', {}).get('value', '')
                edge_uri = b.get('edge', {}).get('value', '')
                edge_type = b.get('edgeType', {}).get('value', '')
                related_uri = b.get('relatedURI', {}).get('value', '')
                related_name = b.get('relatedName', {}).get('value', '')
                related_vt = b.get('relatedVitaltype', {}).get('value', '')

                src = type_uri if direction == 'outgoing' else related_uri
                dst = related_uri if direction == 'outgoing' else type_uri

                edges.append({
                    'uri': edge_uri,
                    'edgeType': edge_type,
                    'sourceURI': src,
                    'destinationURI': dst,
                    'direction': direction,
                })

                if related_uri not in connected_types:
                    connected_types[related_uri] = {
                        'uri': related_uri,
                        'name': related_name,
                        'vitaltype': related_vt,
                    }

            # Also fetch the queried type's own name and vitaltype
            source_query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?name ?vitaltype WHERE {{
  <{type_uri}> vc:hasName ?name .
  <{type_uri}> vc:vitaltype ?vitaltype .
}}
"""
            src_results = await backend.execute_sparql_query(space_id, source_query)
            if isinstance(src_results, dict):
                src_bindings = src_results.get('results', {}).get('bindings', [])
            else:
                src_bindings = src_results if src_results else []

            source_type = {'uri': type_uri, 'name': '', 'vitaltype': ''}
            if src_bindings:
                source_type['name'] = src_bindings[0].get('name', {}).get('value', '')
                source_type['vitaltype'] = src_bindings[0].get('vitaltype', {}).get('value', '')

            self.logger.debug(
                f"Found {len(edges)} edges and {len(connected_types)} connected types for {type_uri}"
            )

            return {
                'edges': edges,
                'connected_types': list(connected_types.values()),
                'source_type': source_type,
            }

        except Exception as e:
            self.logger.error(f"Failed to get type relationships for {type_uri}: {e}")
            raise

    async def create_type_relationship(
        self, backend, space_id: str, graph_id: str,
        type_uri: str, edge_type: str, target_uri: str,
    ) -> Dict[str, Any]:
        """
        Create a type-level edge between two types.

        Returns dict with edge_uri, edge_type, source_uri, destination_uri.
        """
        import uuid

        # Validate edge_type is a known type-level edge
        if edge_type not in self.TYPE_EDGE_URIS:
            raise ValueError(
                f"Unknown edge type: {edge_type}. "
                f"Valid types: {', '.join(self.TYPE_EDGE_URIS)}"
            )

        edge_uri = f"urn:edge:{uuid.uuid4()}"
        self.logger.debug(
            f"Creating type relationship: {type_uri} --[{edge_type}]--> {target_uri} (edge {edge_uri})"
        )

        insert_quads = [
            (edge_uri, "http://vital.ai/ontology/vital-core#vitaltype", edge_type, graph_id),
            (edge_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", edge_type, graph_id),
            (edge_uri, "http://vital.ai/ontology/vital-core#hasEdgeSource", type_uri, graph_id),
            (edge_uri, "http://vital.ai/ontology/vital-core#hasEdgeDestination", target_uri, graph_id),
            (edge_uri, "http://vital.ai/ontology/vital-core#isActive", "true", graph_id),
        ]

        success = await backend.update_quads(
            space_id=space_id, graph_id=graph_id,
            delete_quads=[], insert_quads=insert_quads,
        )
        if not success:
            raise Exception("Failed to create type relationship edge")

        return {
            'edge_uri': edge_uri,
            'edge_type': edge_type,
            'source_uri': type_uri,
            'destination_uri': target_uri,
        }

    async def delete_type_relationship(
        self, backend, space_id: str, graph_id: str,
        type_uri: str, edge_uri: str,
    ) -> bool:
        """
        Delete a type-level edge by URI.

        Returns True if deleted.
        """
        self.logger.debug(f"Deleting type relationship edge: {edge_uri}")

        # Verify edge exists and is associated with the given type
        verify_query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?edgeType WHERE {{
  {{
    <{edge_uri}> vc:hasEdgeSource <{type_uri}> .
    <{edge_uri}> vc:vitaltype ?edgeType .
  }}
  UNION
  {{
    <{edge_uri}> vc:hasEdgeDestination <{type_uri}> .
    <{edge_uri}> vc:vitaltype ?edgeType .
  }}
}} LIMIT 1
"""
        results = await backend.execute_sparql_query(space_id, verify_query)
        if isinstance(results, dict):
            bindings = results.get('results', {}).get('bindings', [])
        else:
            bindings = results if results else []

        if not bindings:
            return False

        # Delete all triples with edge_uri as subject
        if hasattr(backend, 'update_subjects_graph'):
            success = await backend.update_subjects_graph(
                space_id, graph_id, [edge_uri], [])
        else:
            # Fetch all triples for the edge, then delete
            fetch_query = f"""\
SELECT ?p ?o WHERE {{
  GRAPH <{graph_id}> {{
    <{edge_uri}> ?p ?o .
  }}
}}
"""
            fetch_results = await backend.execute_sparql_query(space_id, fetch_query)
            if isinstance(fetch_results, dict):
                fetch_bindings = fetch_results.get('results', {}).get('bindings', [])
            else:
                fetch_bindings = fetch_results if fetch_results else []

            delete_quads = []
            for b in fetch_bindings:
                p = b.get('p', {}).get('value', '')
                o = b.get('o', {}).get('value', '')
                delete_quads.append((edge_uri, p, o, graph_id))

            success = await backend.update_quads(
                space_id=space_id, graph_id=graph_id,
                delete_quads=delete_quads, insert_quads=[],
            )

        return success

    # ── Documentation ─────────────────────────────────────────────────

    async def get_type_documentation(
        self, backend, space_id: str, graph_id: str, type_uri: str,
    ) -> Dict[str, Any]:
        """
        Get the documentation KGDocument linked to a type via Edge_hasKGEdge.

        Returns dict with type_uri, content, document_uri, has_documentation.
        """
        query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?docURI ?content WHERE {{
  ?edge vc:hasEdgeSource <{type_uri}> .
  ?edge vc:hasEdgeDestination ?docURI .
  ?edge vc:vitaltype haley:Edge_hasKGEdge .
  ?docURI vc:vitaltype haley:KGDocument .
  OPTIONAL {{ ?docURI haley:hasKGDocumentContent ?content . }}
}} LIMIT 1
"""
        results = await backend.execute_sparql_query(space_id, query)
        if isinstance(results, dict):
            bindings = results.get('results', {}).get('bindings', [])
        else:
            bindings = results if results else []

        if not bindings:
            return {
                'type_uri': type_uri,
                'content': None,
                'document_uri': None,
                'has_documentation': False,
            }

        doc_uri = bindings[0].get('docURI', {}).get('value', '')
        content = bindings[0].get('content', {}).get('value', None)
        return {
            'type_uri': type_uri,
            'content': content,
            'document_uri': doc_uri,
            'has_documentation': True,
        }

    async def update_type_documentation(
        self, backend, space_id: str, graph_id: str,
        type_uri: str, content: str,
    ) -> Dict[str, Any]:
        """
        Create or update the documentation KGDocument for a type.

        Returns dict with type_uri, document_uri, created.
        """
        import uuid

        existing = await self.get_type_documentation(
            backend, space_id, graph_id, type_uri
        )

        if existing['has_documentation']:
            # Update existing document content
            doc_uri = existing['document_uri']
            content_pred = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent"

            # Delete old content triple, insert new one
            delete_quads = [(doc_uri, content_pred, existing.get('content', ''), graph_id)]
            insert_quads = [(doc_uri, content_pred, content, graph_id)]

            await backend.update_quads(
                space_id=space_id, graph_id=graph_id,
                delete_quads=delete_quads, insert_quads=insert_quads,
            )
            return {
                'type_uri': type_uri,
                'document_uri': doc_uri,
                'created': False,
            }
        else:
            # Create new KGDocument + Edge_hasKGEdge
            doc_uri = f"urn:kgdoc:{uuid.uuid4()}"
            edge_uri = f"urn:edge:{uuid.uuid4()}"
            kgdoc_type = "http://vital.ai/ontology/haley-ai-kg#KGDocument"
            edge_type = "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGEdge"
            content_pred = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent"

            insert_quads = [
                # KGDocument object
                (doc_uri, "http://vital.ai/ontology/vital-core#vitaltype", kgdoc_type, graph_id),
                (doc_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", kgdoc_type, graph_id),
                (doc_uri, content_pred, content, graph_id),
                (doc_uri, "http://vital.ai/ontology/vital-core#isActive", "true", graph_id),
                # Edge_hasKGEdge linking type → document
                (edge_uri, "http://vital.ai/ontology/vital-core#vitaltype", edge_type, graph_id),
                (edge_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", edge_type, graph_id),
                (edge_uri, "http://vital.ai/ontology/vital-core#hasEdgeSource", type_uri, graph_id),
                (edge_uri, "http://vital.ai/ontology/vital-core#hasEdgeDestination", doc_uri, graph_id),
                (edge_uri, "http://vital.ai/ontology/vital-core#isActive", "true", graph_id),
            ]

            await backend.update_quads(
                space_id=space_id, graph_id=graph_id,
                delete_quads=[], insert_quads=insert_quads,
            )
            return {
                'type_uri': type_uri,
                'document_uri': doc_uri,
                'created': True,
            }

    async def delete_type_documentation(
        self, backend, space_id: str, graph_id: str, type_uri: str,
    ) -> bool:
        """
        Delete the documentation KGDocument and its linking edge for a type.

        Returns True if deleted, False if no documentation existed.
        """
        existing = await self.get_type_documentation(
            backend, space_id, graph_id, type_uri
        )
        if not existing['has_documentation']:
            return False

        doc_uri = existing['document_uri']

        # Find the linking edge URI
        edge_query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?edge WHERE {{
  ?edge vc:hasEdgeSource <{type_uri}> .
  ?edge vc:hasEdgeDestination <{doc_uri}> .
  ?edge vc:vitaltype haley:Edge_hasKGEdge .
}} LIMIT 1
"""
        results = await backend.execute_sparql_query(space_id, edge_query)
        if isinstance(results, dict):
            bindings = results.get('results', {}).get('bindings', [])
        else:
            bindings = results if results else []

        uris_to_delete = [doc_uri]
        if bindings:
            uris_to_delete.append(bindings[0].get('edge', {}).get('value', ''))

        # Delete both the document and the edge
        if hasattr(backend, 'update_subjects_graph'):
            await backend.update_subjects_graph(
                space_id, graph_id, uris_to_delete, [])
        else:
            # Fetch all triples for each URI and delete
            for uri in uris_to_delete:
                fetch_query = f"""\
SELECT ?p ?o WHERE {{
  GRAPH <{graph_id}> {{
    <{uri}> ?p ?o .
  }}
}}
"""
                fetch_results = await backend.execute_sparql_query(space_id, fetch_query)
                if isinstance(fetch_results, dict):
                    fetch_bindings = fetch_results.get('results', {}).get('bindings', [])
                else:
                    fetch_bindings = fetch_results if fetch_results else []

                delete_quads = [
                    (uri, b.get('p', {}).get('value', ''), b.get('o', {}).get('value', ''), graph_id)
                    for b in fetch_bindings
                ]
                if delete_quads:
                    await backend.update_quads(
                        space_id=space_id, graph_id=graph_id,
                        delete_quads=delete_quads, insert_quads=[],
                    )

        return True

    # ── Search ────────────────────────────────────────────────────────

    # Default index name for KG type search (shared by FTS + vector indexes).
    KGTYPE_INDEX_NAME = "kgtype_default"

    async def search_types(
        self, backend, space_id: str, graph_id: str,
        query: str, type_filter: Optional[str] = None,
        search_mode: str = "keyword",
        limit: int = 100,
        offset: int = 0,
        alpha: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Search KG types by keyword, FTS, vector, or hybrid.

        Builds a SPARQL query using the appropriate ``vg:`` function
        (``vg:textSearch``, ``vg:vectorSimilarity``, ``vg:hybridSearch``)
        and executes it through the standard SPARQL pipeline.

        Falls back to SPARQL ``CONTAINS`` for ``keyword`` mode.

        Returns dict with types, count, total_count, search_mode, query.
        """
        self.logger.debug(
            "Searching types: query='%s', mode=%s, type=%s, limit=%d, offset=%d",
            query, search_mode, type_filter, limit, offset,
        )

        if search_mode in ("fts", "vector", "hybrid"):
            return await self._search_types_vg(
                backend, space_id, graph_id, query,
                search_mode=search_mode,
                type_filter=type_filter, limit=limit,
                offset=offset,
                alpha=alpha,
            )

        # Fallback: SPARQL CONTAINS keyword search
        return await self._search_types_keyword(
            backend, space_id, graph_id, query, type_filter=type_filter,
            limit=limit, offset=offset,
        )

    # ── vg: function search (FTS / vector / hybrid) ────────────────

    async def _search_types_vg(
        self, backend, space_id: str, graph_id: str, query: str,
        *, search_mode: str, type_filter: Optional[str] = None,
        limit: int = 100, offset: int = 0, alpha: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build a SPARQL query with vg: functions and execute it."""
        escaped_query = query.replace('\\', '\\\\').replace('"', '\\"')
        index = self.KGTYPE_INDEX_NAME

        if type_filter:
            type_filter_clause = f'?s vc:vitaltype <{type_filter}> .'
        else:
            type_values_list = " ".join(f"<{t}>" for t in self.ALL_KGTYPE_URIS)
            type_filter_clause = f'VALUES ?vitaltype {{ {type_values_list} }}'

        # Build the BIND clause for the chosen search mode
        if search_mode == "fts":
            bind_clause = (
                f'BIND(vg:textSearch(?s, "{escaped_query}", "{index}") '
                f'AS ?score)'
            )
        elif search_mode == "vector":
            bind_clause = (
                f'BIND(vg:vectorSimilarity(?s, "{escaped_query}", "{index}") '
                f'AS ?score)'
            )
        elif search_mode == "hybrid":
            hybrid_alpha = alpha if alpha is not None else 0.5
            bind_clause = (
                f'BIND(vg:hybridSearch(?s, "{escaped_query}", "{index}", {hybrid_alpha}) '
                f'AS ?score)'
            )
        else:
            bind_clause = ""

        where_clause = f"""\
  ?s vc:vitaltype ?vitaltype .
  {type_filter_clause}
  ?s vc:hasName ?name .
  OPTIONAL {{ ?s <http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription> ?description . }}
  {bind_clause}
  FILTER(BOUND(?score))"""

        # For vg: function modes, COUNT(*) doesn't accurately reflect
        # what the function returns (e.g. vector similarity scores all
        # items, and OFFSET may not work with internal top-k limits).
        # Run the full query once, count results, and slice in Python.
        search_query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

SELECT ?s ?name ?vitaltype ?description ?score WHERE {{
{where_clause}
}}
ORDER BY DESC(?score)
"""

        results = await backend.execute_sparql_query(space_id, search_query)
        all_bindings = self._extract_bindings(results)
        total_count = len(all_bindings)

        # Results are already sorted by score DESC from SPARQL
        # Paginate in Python
        page_bindings = all_bindings[offset:offset + limit]

        types = []
        for b in page_bindings:
            types.append({
                'uri': b.get('s', {}).get('value', ''),
                'name': b.get('name', {}).get('value', ''),
                'vitaltype': b.get('vitaltype', {}).get('value', ''),
                'description': b.get('description', {}).get('value', ''),
                'score': float(b.get('score', {}).get('value', 0)),
            })

        return {
            'types': types,
            'count': len(types),
            'total_count': total_count,
            'search_mode': search_mode,
            'query': query,
        }

    # ── SPARQL CONTAINS keyword search ─────────────────────────────

    async def _search_types_keyword(
        self, backend, space_id: str, graph_id: str, query: str,
        *, type_filter: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> Dict[str, Any]:
        """SPARQL CONTAINS keyword fallback (no vector index required)."""
        if type_filter:
            type_filter_clause = f'?s vc:vitaltype <{type_filter}> .'
        else:
            type_values_list = " ".join(f"<{t}>" for t in self.ALL_KGTYPE_URIS)
            type_filter_clause = f'VALUES ?vitaltype {{ {type_values_list} }}'

        escaped_query = query.replace('\\', '\\\\').replace('"', '\\"')

        where_clause = f"""\
  ?s vc:vitaltype ?vitaltype .
  {type_filter_clause}
  ?s vc:hasName ?name .
  OPTIONAL {{ ?s <http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription> ?description . }}
  FILTER(
    CONTAINS(LCASE(?name), LCASE("{escaped_query}"))
    || CONTAINS(LCASE(COALESCE(?description, "")), LCASE("{escaped_query}"))
  )
  BIND(IF(CONTAINS(LCASE(?name), LCASE("{escaped_query}")), 2, 1) AS ?score)"""

        # Count query
        count_query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>

SELECT (COUNT(*) AS ?cnt) WHERE {{
{where_clause}
}}
"""
        count_results = await backend.execute_sparql_query(space_id, count_query)
        count_bindings = self._extract_bindings(count_results)
        total_count = int(count_bindings[0].get('cnt', {}).get('value', 0)) if count_bindings else 0

        # Data query with pagination — name matches first, then alphabetical
        search_query = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>

SELECT ?s ?name ?vitaltype ?description ?score WHERE {{
{where_clause}
}}
ORDER BY DESC(?score) ?name
LIMIT {limit}
OFFSET {offset}
"""

        results = await backend.execute_sparql_query(space_id, search_query)
        bindings = self._extract_bindings(results)

        types = []
        for b in bindings:
            types.append({
                'uri': b.get('s', {}).get('value', ''),
                'name': b.get('name', {}).get('value', ''),
                'vitaltype': b.get('vitaltype', {}).get('value', ''),
                'description': b.get('description', {}).get('value', ''),
                'score': float(b.get('score', {}).get('value', 0)),
            })

        return {
            'types': types,
            'count': len(types),
            'total_count': total_count,
            'search_mode': 'keyword',
            'query': query,
        }

    @staticmethod
    def _extract_bindings(results) -> list:
        """Extract SPARQL result bindings from various response shapes."""
        if isinstance(results, dict):
            return results.get('results', {}).get('bindings', [])
        return results if results else []

    async def list_kgtypes(self, backend, space_id: str, graph_id: str, 
                          page_size: int = 100, offset: int = 0, 
                          search: Optional[str] = None,
                          type_uri: Optional[str] = None) -> Tuple[List[tuple], int]:
        """
        List KGTypes with pagination and optional search.
        
        Args:
            backend: Backend adapter instance
            space_id: Space identifier
            graph_id: Graph identifier (complete URI)
            page_size: Number of types per page
            offset: Number of types to skip
            search: Optional search text to filter types
            type_uri: Optional type URI to filter by a specific KGType subclass
                      (e.g. 'http://vital.ai/ontology/haley-ai-kg#KGFrameType')
            
        Returns:
            Tuple[List[Tuple], int]: (List of RDFLib triples (subject, predicate, object), total count)
        """
        try:
            self.logger.debug(f"🔍 Listing KGTypes (page_size: {page_size}, offset: {offset}, search: {search}, type_uri: {type_uri})")
            
            # Initialize retriever if not already done
            if self.retriever is None:
                self.retriever = GraphObjectRetriever(backend)
            
            # Use specific type URI if provided, otherwise all KGType subclasses
            kgtype_uris = [type_uri] if type_uri else self.ALL_KGTYPE_URIS
            
            # Use centralized retriever (filters OUT materialized edges by default)
            triples, total_count = await self.retriever.list_objects(
                space_id, graph_id, kgtype_uris,
                property_filters=None,
                include_materialized_edges=False,
                page_size=page_size,
                offset=offset,
                search=search,
                include_count=True
            )
            
            self.logger.debug(f"✅ Listed {len(triples)} KGType RDFLib triples (total: {total_count})")
            return triples, total_count
            
        except Exception as e:
            self.logger.error(f"❌ Failed to list KGTypes: {e}")
            raise
