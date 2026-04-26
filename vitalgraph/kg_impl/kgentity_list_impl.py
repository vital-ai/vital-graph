"""
KGEntity List Implementation for VitalGraph.

This module provides the implementation for listing KG entities with filtering,
pagination, and search capabilities, working exclusively with GraphObjects.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

# VitalSigns imports for proper integration
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Backend utilities - no direct import needed, will use backend_adapter method

# ---------------------------------------------------------------------------
# KGEntity subclass type clause — matches KGEntity and all known subclasses.
# Must be kept in sync with kg_query_builder.py entity_type_clause.
# ---------------------------------------------------------------------------
_KGENTITY_TYPE_CLAUSE = """{
      ?entity vital-core:vitaltype haley:KGEntity .
    } UNION {
      ?entity vital-core:vitaltype haley:KGNewsEntity .
    } UNION {
      ?entity vital-core:vitaltype haley:KGProductEntity .
    } UNION {
      ?entity vital-core:vitaltype haley:KGWebEntity .
    }"""

_KGENTITY_TYPE_CLAUSE_VAR_S = _KGENTITY_TYPE_CLAUSE.replace("?entity", "?s")

_MATERIALIZED_FILTER = (
    "FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&\n"
    "       ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&\n"
    "       ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)"
)


def _extract_bindings(result) -> list:
    """Normalise SPARQL result to a list of binding dicts."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get('results', {}).get('bindings', [])
    return []


@dataclass
class ListEntitiesResult:
    """Result container for list operations."""
    entities: List[GraphObject]
    total_count: int


class KGEntityListProcessor:
    """
    Processor for KGEntity list operations with backend integration.
    
    Handles entity listing with filtering, pagination, and search capabilities
    while working exclusively with GraphObjects.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    # ==================================================================
    # Optimized list_entities — single SPARQL query for graph=False,
    # concurrent count + entity-graph fetch for graph=True.
    # Replaces the original 3-query sequential pattern (~10x faster).
    # ==================================================================

    async def list_entities(self, space_id: str, graph_id: str,
                           backend_adapter,
                           page_size: int = 10, offset: int = 0,
                           entity_type_uri: Optional[str] = None,
                           search: Optional[str] = None,
                           include_entity_graph: bool = False,
                           sort_by: Optional[str] = None,
                           sort_order: str = "asc") -> ListEntitiesResult:
        """
        List KGEntities with filtering and pagination.

        Optimized path (include_entity_graph=False):
          Single SPARQL query — subquery for pagination joined with
          property fetch.  Count query runs concurrently.

        Graph path (include_entity_graph=True):
          Count + URI query run concurrently, then entity graphs
          fetched in parallel via asyncio.gather.

        sort_by: Optional property URI to sort by (e.g. vital-core:hasName).
        sort_order: 'asc' or 'desc'.
        """
        try:
            self.logger.debug(
                "list_entities space=%s graph=%s page=%d off=%d type=%s search=%s graph_mode=%s sort=%s/%s",
                space_id, graph_id, page_size, offset,
                entity_type_uri, search, include_entity_graph,
                sort_by, sort_order,
            )

            if not include_entity_graph:
                return await self._list_entities_fast(
                    space_id, graph_id, page_size, offset,
                    entity_type_uri, search, backend_adapter,
                    sort_by=sort_by, sort_order=sort_order,
                )
            else:
                return await self._list_entities_with_graph(
                    space_id, graph_id, page_size, offset,
                    entity_type_uri, search, backend_adapter,
                    sort_by=sort_by, sort_order=sort_order,
                )

        except Exception as e:
            self.logger.error(f"Error listing entities: {e}")
            raise

    # ------------------------------------------------------------------
    # Fast path: include_entity_graph=False — 1 data query + 1 count
    # ------------------------------------------------------------------

    async def _list_entities_fast(self, space_id, graph_id, page_size,
                                  offset, entity_type_uri, search,
                                  backend_adapter,
                                  sort_by=None, sort_order="asc") -> ListEntitiesResult:
        """Single SPARQL query fetches paginated entity properties directly."""
        from collections import defaultdict

        # Build the optimized single query
        sparql = self._build_optimized_properties_query(
            graph_id, page_size, offset, entity_type_uri, search,
            sort_by=sort_by, sort_order=sort_order,
        )

        # Run data query and count query concurrently
        count_sparql = self._build_count_query(graph_id, entity_type_uri, search, sort_by=sort_by)

        data_task = backend_adapter.execute_sparql_query(space_id, sparql)
        count_task = backend_adapter.execute_sparql_query(space_id, count_sparql)
        data_result, count_result = await asyncio.gather(data_task, count_task)

        # Parse count
        count_bindings = _extract_bindings(count_result)
        total_count = 0
        if count_bindings and 'count' in count_bindings[0]:
            total_count = int(count_bindings[0]['count']['value'])

        # Parse data bindings → GraphObjects via from_property_maps
        bindings = _extract_bindings(data_result)
        if not bindings:
            return ListEntitiesResult(entities=[], total_count=total_count)

        objects = await self._bindings_to_graph_objects(bindings)
        self.logger.debug("list_entities_fast: %d objects, total=%d", len(objects), total_count)
        return ListEntitiesResult(entities=objects, total_count=total_count)

    # ------------------------------------------------------------------
    # Graph path: include_entity_graph=True
    # ------------------------------------------------------------------

    async def _list_entities_with_graph(self, space_id, graph_id, page_size,
                                        offset, entity_type_uri, search,
                                        backend_adapter,
                                        sort_by=None, sort_order="asc") -> ListEntitiesResult:
        """Get entity URIs, then fetch full entity graphs in parallel."""
        from .kgentity_get_impl import KGEntityGetProcessor

        # Build URI query (with subclass UNIONs + pagination)
        uri_sparql = self._build_entity_uris_query(
            graph_id, page_size, offset, entity_type_uri, search,
            sort_by=sort_by, sort_order=sort_order,
        )
        count_sparql = self._build_count_query(graph_id, entity_type_uri, search, sort_by=sort_by)

        # Run URI + count concurrently
        uri_task = backend_adapter.execute_sparql_query(space_id, uri_sparql)
        count_task = backend_adapter.execute_sparql_query(space_id, count_sparql)
        uri_result, count_result = await asyncio.gather(uri_task, count_task)

        # Parse count
        count_bindings = _extract_bindings(count_result)
        total_count = 0
        if count_bindings and 'count' in count_bindings[0]:
            total_count = int(count_bindings[0]['count']['value'])

        # Parse URIs
        uri_bindings = _extract_bindings(uri_result)
        entity_uris = [b['entity']['value'] for b in uri_bindings if 'entity' in b]

        if not entity_uris:
            return ListEntitiesResult(entities=[], total_count=total_count)

        # Fetch entity graphs concurrently
        get_processor = KGEntityGetProcessor(logger=self.logger)

        async def _fetch(uri):
            try:
                return await get_processor.get_entity(
                    space_id=space_id, graph_id=graph_id,
                    entity_uri=uri, include_entity_graph=True,
                    backend_adapter=backend_adapter,
                )
            except Exception as e:
                self.logger.warning("Error retrieving entity graph %s: %s", uri, e)
                return None

        results = await asyncio.gather(*[_fetch(uri) for uri in entity_uris])

        entities: List[GraphObject] = []
        for uri, objs in zip(entity_uris, results):
            if objs:
                entities.extend(objs)

        self.logger.debug("list_entities_with_graph: %d objects, total=%d", len(entities), total_count)
        return ListEntitiesResult(entities=entities, total_count=total_count)

    # ------------------------------------------------------------------
    # Binding → GraphObject conversion (fast path, no rdflib)
    # ------------------------------------------------------------------

    async def _bindings_to_graph_objects(self, bindings: list) -> List[GraphObject]:
        """Convert ?s ?p ?o SPARQL bindings to GraphObjects via from_property_maps."""
        from collections import defaultdict

        _RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
        _VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype'
        _URI_PROP = 'http://vital.ai/ontology/vital-core#URIProp'
        _XSD = 'http://www.w3.org/2001/XMLSchema#'

        subjects: Dict[str, Dict] = defaultdict(
            lambda: {'type_uri': None, 'properties': {}}
        )

        for b in bindings:
            s = b.get('s', {}).get('value')
            p = b.get('p', {}).get('value')
            o_data = b.get('o', {})
            if not (s and p and o_data.get('value') is not None):
                continue

            o_val = o_data['value']
            o_type = o_data.get('type', 'literal')

            if p == _RDF_TYPE or p == _VITALTYPE:
                subjects[s]['type_uri'] = o_val
                continue
            if p == _URI_PROP:
                continue

            if o_type == 'uri':
                value = o_val
            else:
                value = self._convert_literal(o_val, o_data.get('datatype'))

            props = subjects[s]['properties']
            if p in props:
                existing = props[p]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    props[p] = [existing, value]
            else:
                props[p] = value

        entries = []
        for subject_uri, data in subjects.items():
            if data['type_uri']:
                entries.append({
                    'subject_uri': subject_uri,
                    'type_uri': data['type_uri'],
                    'properties': data['properties'],
                })

        if not entries:
            return []

        return await asyncio.to_thread(GraphObject.from_property_maps, entries)

    @staticmethod
    def _convert_literal(value_str: str, datatype: str = None):
        """Convert a SPARQL literal to native Python type."""
        if not datatype:
            return value_str
        _XSD = 'http://www.w3.org/2001/XMLSchema#'
        if not datatype.startswith(_XSD):
            return value_str
        local = datatype[len(_XSD):]
        if local in ('integer', 'int', 'long', 'short', 'byte',
                     'nonNegativeInteger', 'positiveInteger',
                     'nonPositiveInteger', 'negativeInteger',
                     'unsignedLong', 'unsignedInt', 'unsignedShort', 'unsignedByte'):
            return int(value_str)
        if local in ('float', 'double', 'decimal'):
            return float(value_str)
        if local == 'boolean':
            return value_str.lower() in ('true', '1')
        if local == 'dateTime':
            from datetime import datetime
            try:
                return datetime.fromisoformat(value_str.replace('Z', '+00:00'))
            except ValueError:
                return value_str
        return value_str

    # ------------------------------------------------------------------
    # Optimized SPARQL query builders (with subclass UNIONs)
    # ------------------------------------------------------------------

    def _build_optimized_properties_query(self, graph_id: str, page_size: int,
                                          offset: int, entity_type_uri: Optional[str],
                                          search: Optional[str],
                                          sort_by: Optional[str] = None,
                                          sort_order: str = "asc") -> str:
        """Single query: subquery for paginated entity URIs + property fetch."""
        # Inner subquery type clause
        if entity_type_uri:
            type_clause = (
                f"    ?s vital-core:vitaltype haley:KGEntity .\n"
                f"    ?s haley:hasKGEntityType <{entity_type_uri}> ."
            )
        else:
            type_clause = f"    {_KGENTITY_TYPE_CLAUSE_VAR_S}"

        # Optional search filter
        search_clause = ""
        if search:
            search_clause = (
                f"\n          ?s <http://vital.ai/ontology/vital-core#hasName> ?name ."
                f"\n          FILTER(CONTAINS(LCASE(?name), LCASE(\"{search}\")))"
            )

        # Sort triple + ORDER BY
        sort_triple = ""
        order_by = "ORDER BY ?s"
        if sort_by:
            sort_triple = f"\n          ?s <{sort_by}> ?sort_val ."
            direction = "DESC" if sort_order == "desc" else "ASC"
            order_by = f"ORDER BY {direction}(?sort_val) ?s"

        inner_select = "SELECT DISTINCT ?s WHERE {"
        if sort_by:
            inner_select = "SELECT DISTINCT ?s ?sort_val WHERE {"

        return (
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>\n"
            "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>\n"
            "SELECT ?s ?p ?o WHERE {\n"
            f"  GRAPH <{graph_id}> {{\n"
            "    {\n"
            f"      {inner_select}\n"
            f"        GRAPH <{graph_id}> {{\n"
            f"          {type_clause}{search_clause}{sort_triple}\n"
            "        }\n"
            "      }\n"
            f"      {order_by}\n"
            f"      LIMIT {page_size}\n"
            f"      OFFSET {offset}\n"
            "    }\n"
            "    ?s ?p ?o .\n"
            f"    {_MATERIALIZED_FILTER}\n"
            "  }\n"
            "}\n"
            f"ORDER BY {f'{direction}(?sort_val) ?s ?p' if sort_by else '?s ?p'}"
        )

    def _build_entity_uris_query(self, graph_id: str, page_size: int,
                                  offset: int, entity_type_uri: Optional[str],
                                  search: Optional[str],
                                  sort_by: Optional[str] = None,
                                  sort_order: str = "asc") -> str:
        """SELECT DISTINCT entity URIs with subclass UNIONs and pagination."""
        if entity_type_uri:
            type_clause = (
                "    ?entity vital-core:vitaltype haley:KGEntity .\n"
                f"    ?entity haley:hasKGEntityType <{entity_type_uri}> ."
            )
        else:
            type_clause = f"    {_KGENTITY_TYPE_CLAUSE}"

        search_clause = ""
        if search:
            search_clause = (
                "\n    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name ."
                f"\n    FILTER(CONTAINS(LCASE(?name), LCASE(\"{search}\")))"
            )

        sort_triple = ""
        order_by = "ORDER BY ?entity"
        if sort_by:
            sort_triple = f"\n    ?entity <{sort_by}> ?sort_val ."
            direction = "DESC" if sort_order == "desc" else "ASC"
            order_by = f"ORDER BY {direction}(?sort_val) ?entity"

        select_clause = "SELECT DISTINCT ?entity WHERE {"
        if sort_by:
            select_clause = "SELECT DISTINCT ?entity ?sort_val WHERE {"

        return (
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>\n"
            "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>\n"
            f"{select_clause}\n"
            f"  GRAPH <{graph_id}> {{\n"
            f"    {type_clause}{search_clause}{sort_triple}\n"
            "  }\n"
            "}\n"
            f"{order_by}\n"
            f"LIMIT {page_size}\n"
            f"OFFSET {offset}"
        )

    # ==================================================================
    # ORIGINAL implementation (kept for revert if needed)
    # ==================================================================

    async def _list_entities_original(self, space_id: str, graph_id: str, 
                           backend_adapter,
                           page_size: int = 10, offset: int = 0,
                           entity_type_uri: Optional[str] = None,
                           search: Optional[str] = None,
                           include_entity_graph: bool = False) -> ListEntitiesResult:
        """ORIGINAL 3-query implementation. Kept for revert if needed."""
        try:
            self.logger.debug(f"Listing entities in space '{space_id}', graph '{graph_id}'")
            self.logger.debug(f"Parameters: page_size={page_size}, offset={offset}, entity_type_uri={entity_type_uri}, search={search}, include_entity_graph={include_entity_graph}")
            
            # Get total count first
            total_count = await self._get_total_count_original(
                space_id, graph_id, entity_type_uri, search, backend_adapter
            )
            
            if total_count == 0:
                self.logger.debug("No entities found matching criteria")
                return ListEntitiesResult(entities=[], total_count=0)
            
            # Get entities with pagination
            entities = await self._get_entities_page_original(
                space_id, graph_id, page_size, offset, entity_type_uri, 
                search, include_entity_graph, backend_adapter
            )
            
            self.logger.debug(f"Retrieved {len(entities)} entities (total: {total_count})")
            return ListEntitiesResult(entities=entities, total_count=total_count)
            
        except Exception as e:
            self.logger.error(f"Error listing entities: {e}")
            raise
    
    async def _get_total_count_original(self, space_id: str, graph_id: str, 
                              entity_type_uri: Optional[str], search: Optional[str],
                              backend_adapter) -> int:
        """ORIGINAL count implementation. Kept for revert if needed."""
        try:
            # Build count query using the existing method
            count_query = self._build_count_query(graph_id, entity_type_uri, search)
            self.logger.debug(f"Count query: {count_query}")
            
            # Execute count query using execute_sparql_query
            result = await backend_adapter.execute_sparql_query(space_id, count_query)
            
            if not result:
                self.logger.warning("Count query returned no results")
                return 0
            
            # Handle different result formats
            if isinstance(result, list) and len(result) > 0:
                # Direct list format (as seen in debug output)
                binding = result[0]
                if 'count' in binding:
                    count_value = binding['count']['value']
                    count = int(count_value)
                    self.logger.debug(f"Found {count} entities matching criteria")
                    return count
            elif isinstance(result, dict):
                # Standard SPARQL JSON format
                bindings = result.get('results', {}).get('bindings', [])
                if bindings and 'count' in bindings[0]:
                    count_value = bindings[0]['count']['value']
                    count = int(count_value)
                    self.logger.debug(f"Found {count} entities matching criteria")
                    return count
            
            self.logger.warning(f"Count query returned unexpected format: {type(result)}")
            return 0
            
        except Exception as e:
            self.logger.error(f"Error getting entity count: {e}")
            return 0
    
    async def _get_entities_page_original(self, space_id: str, graph_id: str,
                                page_size: int, offset: int,
                                entity_type_uri: Optional[str], search: Optional[str],
                                include_entity_graph: bool, backend_adapter) -> List[GraphObject]:
        """ORIGINAL 3-query page implementation. Kept for revert if needed."""
        try:
            # First, get entity URIs using SELECT query
            select_query_parts = [
                "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
                "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>",
                "SELECT DISTINCT ?entity WHERE {",
                f"  GRAPH <{graph_id}> {{",
                "    ?entity vital-core:vitaltype haley:KGEntity ."
            ]
            
            # Add entity type filtering if specified
            if entity_type_uri:
                select_query_parts.append(f"    ?entity haley:hasKGEntityType <{entity_type_uri}> .")
            
            # Add search filtering if specified
            if search:
                select_query_parts.extend([
                    "    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .",
                    f"    FILTER(CONTAINS(LCASE(?name), LCASE(\"{search}\")))"
                ])
            
            select_query_parts.extend([
                "  }",
                "}",
                f"LIMIT {page_size}",
                f"OFFSET {offset}"
            ])
            
            select_query = "\n".join(select_query_parts)
            self.logger.debug(f"Entity URIs query: {select_query}")
            
            # Execute SELECT query to get entity URIs
            result = await backend_adapter.execute_sparql_query(space_id, select_query)
            
            if not result:
                self.logger.debug("No entity URIs found")
                return []
            
            # Extract entity URIs from results - handle different formats
            entity_uris = []
            if isinstance(result, list):
                # Direct list format (as seen in debug output)
                for binding in result:
                    if 'entity' in binding:
                        entity_uri = binding['entity']['value']
                        entity_uris.append(entity_uri)
            elif isinstance(result, dict):
                # Standard SPARQL JSON format
                bindings = result.get('results', {}).get('bindings', [])
                for binding in bindings:
                    if 'entity' in binding:
                        entity_uri = binding['entity']['value']
                        entity_uris.append(entity_uri)
            
            if not entity_uris:
                self.logger.debug("No entity URIs extracted from query results")
                return []
            
            self.logger.debug(f"Found {len(entity_uris)} entity URIs: {entity_uris}")
            
            # Retrieve all entities concurrently using asyncio.gather()
            if include_entity_graph:
                from .kgentity_get_impl import KGEntityGetProcessor
                get_processor = KGEntityGetProcessor(logger=self.logger)
                
                async def _fetch_entity_graph(uri: str):
                    try:
                        return await get_processor.get_entity(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=uri,
                            include_entity_graph=True,
                            backend_adapter=backend_adapter
                        )
                    except Exception as e:
                        self.logger.warning(f"Error retrieving entity graph {uri}: {e}")
                        return None
                
                results = await asyncio.gather(*[_fetch_entity_graph(uri) for uri in entity_uris])
                
                entities = []
                for uri, entity_objects in zip(entity_uris, results):
                    if entity_objects:
                        entities.extend(entity_objects)
                        self.logger.debug(f"Retrieved complete entity graph for: {uri} ({len(entity_objects)} objects)")
                    else:
                        self.logger.warning(f"Failed to retrieve entity graph for: {uri}")
            else:
                # Batch fetch: single SPARQL VALUES query instead of N individual queries
                try:
                    all_objects = await backend_adapter.get_objects_by_uris(space_id, entity_uris, graph_id)
                except Exception as e:
                    self.logger.error(f"Batch entity fetch failed: {e}")
                    all_objects = []
                
                # Index by URI for ordered lookup
                uri_to_obj = {}
                for obj in all_objects:
                    obj_uri = str(obj.URI) if hasattr(obj, 'URI') else None
                    if obj_uri and obj_uri not in uri_to_obj:
                        uri_to_obj[obj_uri] = obj
                
                entities = []
                for uri in entity_uris:
                    obj = uri_to_obj.get(uri)
                    if obj:
                        entities.append(obj)
                        self.logger.debug(f"Retrieved basic entity: {uri}")
                    else:
                        self.logger.warning(f"Failed to retrieve entity data for: {uri}")
            
            self.logger.debug(f"Successfully retrieved {len(entities)} entities")
            return entities
            
        except Exception as e:
            self.logger.error(f"Error getting entities page: {e}")
            return []
    
    def _build_count_query(self, graph_id: str, entity_type_uri: Optional[str], 
                          search: Optional[str],
                          sort_by: Optional[str] = None) -> str:
        """Build SPARQL count query (with subclass UNIONs).
        
        When sort_by is provided the sort triple is included as a required join
        so that total_count matches the paginated query (entities missing the
        sort property are excluded from both).
        """
        # Type clause with all subclasses
        if entity_type_uri:
            type_clause = (
                "    ?entity vital-core:vitaltype haley:KGEntity .\n"
                f"    ?entity haley:hasKGEntityType <{entity_type_uri}> ."
            )
        else:
            type_clause = f"    {_KGENTITY_TYPE_CLAUSE}"

        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>",
            "SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {",
            f"  GRAPH <{graph_id}> {{",
            f"    {type_clause}"
        ]
        
        # Search constraint
        if search:
            query_parts.extend([
                "    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .",
                f"    FILTER(CONTAINS(LCASE(?name), LCASE(\"{search}\")))"
            ])

        # Sort join — required so count matches paginated results
        if sort_by:
            query_parts.append(f"    ?entity <{sort_by}> ?sort_val .")
        
        query_parts.extend([
            "  }",
            "}"
        ])
        
        return "\n".join(query_parts)
    
    def _build_entities_query(self, graph_id: str, page_size: int, offset: int,
                             entity_type_uri: Optional[str], search: Optional[str],
                             include_entity_graph: bool) -> str:
        """Build SPARQL entities query with pagination."""
        if include_entity_graph:
            return self._build_entity_graph_query(graph_id, page_size, offset, entity_type_uri, search)
        else:
            return self._build_simple_entities_query(graph_id, page_size, offset, entity_type_uri, search)
    
    def _build_simple_entities_query(self, graph_id: str, page_size: int, offset: int,
                                    entity_type_uri: Optional[str], search: Optional[str]) -> str:
        """Build simple entities query (entity properties only)."""
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>",
            "SELECT ?s ?p ?o WHERE {",
            f"  GRAPH <{graph_id}> {{"
        ]
        
        # Subquery to get entity URIs with pagination
        subquery_parts = [
            "    {",
            "      SELECT DISTINCT ?s WHERE {",
            f"        GRAPH <{graph_id}> {{"
        ]
        
        # Entity type constraint
        if entity_type_uri:
            subquery_parts.extend([
                "          ?s vital-core:vitaltype haley:KGEntity .",
                f"          ?s haley:hasKGEntityType <{entity_type_uri}> ."
            ])
        else:
            subquery_parts.append("          ?s vital-core:vitaltype haley:KGEntity .")
        
        # Search constraint
        if search:
            subquery_parts.extend([
                "          ?s ?sp ?so .",
                f"          FILTER(CONTAINS(LCASE(STR(?so)), LCASE(\"{search}\")))"
            ])
        
        subquery_parts.extend([
            "        }",
            "      }",
            "      ORDER BY ?s",
            f"      LIMIT {page_size}",
            f"      OFFSET {offset}",
            "    }"
        ])
        
        query_parts.extend(subquery_parts)
        query_parts.extend([
            "    ?s ?p ?o .",
            "    FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&",
            "           ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&",
            "           ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)",
            "  }",
            "}",
            "ORDER BY ?s ?p"
        ])
        
        return "\n".join(query_parts)
    
    def _build_entity_graph_query(self, graph_id: str, page_size: int, offset: int,
                                 entity_type_uri: Optional[str], search: Optional[str]) -> str:
        """Build entity graph query (includes related frames, slots, edges)."""
        query_parts = [
            "SELECT ?s ?p ?o WHERE {",
            f"  GRAPH <{graph_id}> {{"
        ]
        
        # Subquery to get entity URIs with pagination
        subquery_parts = [
            "    {",
            "      SELECT DISTINCT ?entity WHERE {",
            f"        GRAPH <{graph_id}> {{"
        ]
        
        # Entity type constraint
        if entity_type_uri:
            subquery_parts.extend([
                f"          ?entity a <{entity_type_uri}> .",
                "          ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> ."
            ])
        else:
            subquery_parts.append("          ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .")
        
        # Search constraint
        if search:
            subquery_parts.extend([
                "          ?entity ?sp ?so .",
                f"          FILTER(CONTAINS(LCASE(STR(?so)), LCASE(\"{search}\")))"
            ])
        
        subquery_parts.extend([
            "        }",
            "      }",
            "      ORDER BY ?entity",
            f"      LIMIT {page_size}",
            f"      OFFSET {offset}",
            "    }"
        ])
        
        query_parts.extend(subquery_parts)
        
        # Get complete entity graph using hasKGGraphURI grouping
        query_parts.extend([
            "    {",
            "      ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> ?entity .",
            "      ?s ?p ?o .",
            "      FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)",
            "    }",
            "    UNION",
            "    {",
            "      ?entity ?p ?o .",
            "      BIND(?entity AS ?s)",
            "      FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&",
            "             ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)",
            "    }",
            "  }",
            "}",
            "ORDER BY ?s ?p"
        ])
        
        return "\n".join(query_parts)
