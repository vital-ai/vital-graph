#!/usr/bin/env python3
"""
KG SPARQL Utilities

Utility functions for SPARQL query processing and result handling.
Used across KG processors to provide consistent SPARQL operations.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Concrete KG entity classes. A UNION over these is preferable to matching the
# type's text: prune_union removes branches for classes absent from the space,
# so unused subtypes cost nothing in the emitted SQL.
KG_ENTITY_CLASS_URIS = (
    "http://vital.ai/ontology/haley-ai-kg#KGEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGNewsEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGProductEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGWebEntity",
)


class KGSparqlUtils:
    """Utility class for common SPARQL operations and result processing."""
    
    @staticmethod
    def extract_count_from_results(results: Any) -> int:
        """
        Extract count value from SPARQL COUNT query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            int: Extracted count value, 0 if not found
        """
        try:
            if isinstance(results, dict) and results.get("results", {}).get("bindings"):
                bindings = results["results"]["bindings"]
                if bindings and len(bindings) > 0:
                    count_binding = bindings[0]
                    if "count" in count_binding:
                        count_value = count_binding["count"].get("value", "0")
                        return int(count_value)
            return 0
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Error extracting count from SPARQL results: {e}")
            return 0
    
    @staticmethod
    def extract_uris_from_results(results: Any, variable_name: str = "uri") -> List[str]:
        """
        Extract URI values from SPARQL query results.
        
        Args:
            results: SPARQL query results
            variable_name: Name of the variable containing URIs
            
        Returns:
            List[str]: List of extracted URIs
        """
        uris = []
        try:
            if isinstance(results, dict) and results.get("results", {}).get("bindings"):
                for binding in results["results"]["bindings"]:
                    if variable_name in binding:
                        uri_value = binding[variable_name].get("value")
                        if uri_value:
                            uris.append(uri_value)
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting URIs from SPARQL results: {e}")
        
        return uris
    
    @staticmethod
    def extract_subject_uris_from_results(results: Any) -> List[str]:
        """
        Extract subject URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List[str]: List of extracted subject URIs
        """
        return KGSparqlUtils.extract_uris_from_results(results, "subject")
    
    @staticmethod
    def build_search_filter(search: Optional[str], search_properties: List[str] = None) -> str:
        """
        Build SPARQL search filter for text search across properties.
        
        Args:
            search: Search term
            search_properties: List of properties to search (defaults to common text properties)
            
        Returns:
            str: SPARQL filter clause
        """
        if not search:
            return ""
        
        if search_properties is None:
            search_properties = [
                "haley:hasName", 
                "vital:hasName", 
                "haley:hasKGSlotStringValue",
                "vital:hasDescription"
            ]
        
        # Escape search term for SPARQL
        escaped_search = search.replace('"', '\\"')
        
        # Build filter conditions for each property
        filter_conditions = []
        for prop in search_properties:
            filter_conditions.append(f'CONTAINS(LCASE(STR(?{prop.split(":")[-1]})), LCASE("{escaped_search}"))')
        
        if filter_conditions:
            return f"""
            OPTIONAL {{ ?subject {search_properties[0]} ?{search_properties[0].split(":")[-1]} }}
            """ + "".join([f"""
            OPTIONAL {{ ?subject {prop} ?{prop.split(":")[-1]} }}""" for prop in search_properties[1:]]) + f"""
            FILTER ({" || ".join(filter_conditions)})
            """
        
        return ""
    
    @staticmethod
    def build_pagination_clause(page_size: int, offset: int) -> str:
        """
        Build SPARQL LIMIT and OFFSET clause for pagination.
        
        Args:
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            str: SPARQL pagination clause
        """
        return f"LIMIT {page_size} OFFSET {offset}"

    # Sequence properties are integers and need the numeric ordering construct
    # below; every other sortable property uses a plain lexical sort.
    SEQUENCE_PROPERTIES = frozenset({
        "http://vital.ai/ontology/haley-ai-kg#hasFrameSequence",
        "http://vital.ai/ontology/haley-ai-kg#hasSlotSequence",
        # KG relations have no dedicated sequence property; hasListIndex is
        # inherited from VITAL_Edge and is the ordering key for them. Integer
        # and sparsely populated, so it is exactly the sequence case.
        "http://vital.ai/ontology/vital-core#hasListIndex",
    })

    @staticmethod
    def reorder_to_match(objects: list, ordered_uris: list) -> list:
        """Return ``objects`` in the order given by ``ordered_uris``.

        Paging/sorting queries decide the order, but objects are typically
        rebuilt from a second triple fetch that groups by its own order.
        Without this, ORDER BY governs WHICH objects appear on a page but not
        the order they appear IN — so sorting looks broken end to end while
        every builder-level test passes.

        Objects whose URI is absent from the list are appended, not dropped.
        """
        if not objects or not ordered_uris:
            return objects
        rank = {uri: i for i, uri in enumerate(ordered_uris)}
        tail = len(rank)
        return sorted(objects,
                      key=lambda o: rank.get(str(getattr(o, "URI", "")), tail))

    @staticmethod
    def build_sort_clauses(anchor_var: str, sort_by: Optional[str],
                           sort_order: str = "asc",
                           var_prefix: str = "sort") -> tuple:
        """Build the WHERE patterns, projection and ORDER BY for a sorted page.

        Returns ``(patterns, projection, order_clause)``.

        The caller MUST emit the subquery shape below — an ORDER BY that sits
        in the same SELECT as a DISTINCT is silently DROPPED by the backend,
        which then returns subject/URI order while looking like it sorted:

            SELECT ?anchor WHERE {
                { SELECT DISTINCT ?anchor <projection> WHERE {
                      GRAPH <...> {
                          ... <patterns> ...
                      }
                } }
            }
            <order_clause>
            LIMIT n OFFSET m

        ``patterns`` must go INSIDE the GRAPH block (they match against the
        anchor's graph); ``projection`` must be added to the inner DISTINCT
        SELECT so the sort keys survive to the outer ORDER BY.

        Ordering contract (see
        planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md):

          - subjects WITH the sort property sort by it;
          - subjects WITHOUT it sort last — in BOTH directions;
          - the anchor variable tiebreaks, giving a total order so that
            offset paging is stable.

        For sequence properties the value is an xsd:integer, and two extra
        keys are needed because of how the backend compiles ORDER BY:

          - ``xsd:integer(...)`` via BIND puts the sort key in the numeric
            lane.  A bare ``ORDER BY ?seq`` resolves to the lexical column and
            orders 1,10,11,12,2,... instead of 1..12.
          - ``IF(BOUND(?v), 0, 1)`` as the LEADING key keeps unsequenced
            subjects last in both directions.  PostgreSQL defaults to NULLS
            LAST on ASC but NULLS FIRST on DESC, and SPARQL has no NULLS LAST
            syntax to override it.  BOUND() (not a truthiness test) is
            required because sequence 0 is a legitimate value, commonly used
            for singletons.

        Callers must declare the xsd prefix when sorting on a sequence
        property.
        """
        anchor = anchor_var.lstrip("?")
        if not sort_by:
            # No sort was asked for, so DO NOT invent one. `ORDER BY ?anchor`
            # orders by the anchor's URI TEXT, and text lives in the term table
            # — so the backend must resolve every candidate's URI and sort the
            # lot before LIMIT can discard all but a page of it. On the frames
            # list of a 1.1M-frame graph that ordering WAS the page load:
            #
            #     ORDER BY ?frame     5,571 ms
            #     no ORDER BY           611 ms
            #
            # Omitting it does not make paging unstable. The SQL pipeline
            # synthesizes its own order for an unordered SLICE and marks it
            # `stable_paging`, which emits `ORDER BY <anchor>__uuid` — a total
            # order over a column already in hand, needing no term JOIN.
            # Verified on that graph: ten consecutive pages partition the
            # result set with no overlap, and a given page is repeatable.
            #
            # A caller that genuinely needs URI-ordered output must ask for it;
            # it is not free and was never free.
            return "", "", ""

        direction = "DESC" if str(sort_order).lower() == "desc" else "ASC"
        val_var = f"{var_prefix}_val"

        if sort_by in KGSparqlUtils.SEQUENCE_PROPERTIES:
            missing_var = f"{var_prefix}_missing"
            num_var = f"{var_prefix}_num"
            patterns = (
                f"OPTIONAL {{ ?{anchor} <{sort_by}> ?{val_var} . }}\n"
                f"                BIND(IF(BOUND(?{val_var}), 0, 1) AS ?{missing_var})\n"
                f"                BIND(xsd:integer(?{val_var}) AS ?{num_var})"
            )
            order_term = (f"?{num_var}" if direction == "ASC"
                          else f"DESC(?{num_var})")
            return (patterns, f"?{missing_var} ?{num_var}",
                    f"ORDER BY ?{missing_var} {order_term} ?{anchor}")

        patterns = f"OPTIONAL {{ ?{anchor} <{sort_by}> ?{val_var} . }}"
        order_term = f"?{val_var}" if direction == "ASC" else f"DESC(?{val_var})"
        return patterns, f"?{val_var}", f"ORDER BY {order_term} ?{anchor}"

    @staticmethod
    def build_graph_clause(graph_id: str) -> str:
        """
        Build SPARQL GRAPH clause.
        
        Args:
            graph_id: Graph identifier
            
        Returns:
            str: SPARQL GRAPH clause
        """
        return f"GRAPH <{graph_id}>"
    
    @staticmethod
    def escape_sparql_string(value: str) -> str:
        """
        Escape string value for use in SPARQL queries.
        
        Args:
            value: String value to escape
            
        Returns:
            str: Escaped string value
        """
        if not isinstance(value, str):
            return str(value)
        
        # Escape quotes and backslashes
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return escaped
    
    @staticmethod
    def build_uri_reference(uri: str) -> str:
        """
        Build proper URI reference for SPARQL queries.
        
        Args:
            uri: URI string
            
        Returns:
            str: Properly formatted URI reference
        """
        if not uri:
            return ""
        
        # If already wrapped in angle brackets, return as-is
        if uri.startswith('<') and uri.endswith('>'):
            return uri
        
        # Wrap in angle brackets
        return f"<{uri}>"
    
    @staticmethod
    def build_prefixes() -> str:
        """
        Build standard SPARQL prefixes for KG operations.
        
        Returns:
            str: SPARQL prefix declarations
        """
        return """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        """
    
    @staticmethod
    def validate_sparql_results(results: Any) -> bool:
        """
        Validate SPARQL query results structure.
        
        Args:
            results: SPARQL query results
            
        Returns:
            bool: True if results are valid, False otherwise
        """
        try:
            if not isinstance(results, dict):
                return False
            
            if "results" not in results:
                return False
            
            if "bindings" not in results["results"]:
                return False
            
            return True
        except Exception:
            return False
    
    @staticmethod
    def build_type_filter(entity_type: Optional[str]) -> str:
        """
        Build SPARQL type filter clause.
        
        Args:
            entity_type: Entity type URI
            
        Returns:
            str: SPARQL type filter clause
        """
        if not entity_type:
            return ""
        
        return f"""
        ?subject a {KGSparqlUtils.build_uri_reference(entity_type)} .
        """
    
    @staticmethod
    def build_grouping_uri_filter(grouping_uri: str, property_name: str = "haley:kGGraphURI") -> str:
        """
        Build SPARQL filter for grouping URI properties.
        
        Args:
            grouping_uri: Grouping URI value
            property_name: Property name for grouping URI
            
        Returns:
            str: SPARQL grouping URI filter clause
        """
        if not grouping_uri:
            return ""
        
        return f"""
        ?subject {property_name} {KGSparqlUtils.build_uri_reference(grouping_uri)} .
        """
    
    @staticmethod
    def extract_typed_triples_from_sparql_results(results: Any) -> List[tuple]:
        """
        Extract triples from SPARQL SELECT results, preserving object type info.
        
        Returns:
            List of (subject_str, predicate_str, object_str, object_type, datatype) tuples
            where object_type is 'uri' or 'literal', and datatype is the XSD datatype URI or None.
        """
        triples = []
        try:
            if isinstance(results, dict) and "results" in results and isinstance(results["results"], dict):
                bindings = results["results"].get("bindings", [])
                for binding in bindings:
                    subject = binding.get("subject", {}).get("value")
                    predicate = binding.get("predicate", {}).get("value")
                    obj_binding = binding.get("object", {})
                    obj = obj_binding.get("value")
                    obj_type = obj_binding.get("type", "literal")
                    obj_datatype = obj_binding.get("datatype")
                    if subject is not None and predicate is not None and obj is not None:
                        triples.append((subject, predicate, obj, obj_type, obj_datatype))
            elif isinstance(results, dict) and results.get("bindings"):
                for binding in results["bindings"]:
                    subject = binding.get("subject", {}).get("value")
                    predicate = binding.get("predicate", {}).get("value")
                    obj_binding = binding.get("object", {})
                    obj = obj_binding.get("value")
                    obj_type = obj_binding.get("type", "literal")
                    obj_datatype = obj_binding.get("datatype")
                    if subject is not None and predicate is not None and obj is not None:
                        triples.append((subject, predicate, obj, obj_type, obj_datatype))
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting typed triples from SPARQL results: {e}")
        return triples

    @staticmethod
    def extract_triples_from_sparql_results(results: Any) -> List[tuple]:
        """
        Extract triples from SPARQL SELECT results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List[tuple]: List of (subject, predicate, object) triples
        """
        triples = []
        try:
            # Handle nested structure: results.results.bindings
            if isinstance(results, dict) and "results" in results and isinstance(results["results"], dict):
                bindings = results["results"].get("bindings", [])
                for binding in bindings:
                    subject = binding.get("subject", {}).get("value")
                    predicate = binding.get("predicate", {}).get("value")
                    obj = binding.get("object", {}).get("value")
                    if subject is not None and predicate is not None and obj is not None:
                        triples.append((subject, predicate, obj))
            # Handle flat structure: results.bindings
            elif isinstance(results, dict) and results.get("bindings"):
                for binding in results["bindings"]:
                    subject = binding.get("subject", {}).get("value")
                    predicate = binding.get("predicate", {}).get("value")
                    obj = binding.get("object", {}).get("value")
                    if subject is not None and predicate is not None and obj is not None:
                        triples.append((subject, predicate, obj))
            elif isinstance(results, list):
                for item in results:
                    if isinstance(item, dict):
                        subject = item.get("subject")
                        predicate = item.get("predicate")
                        obj = item.get("object")
                        
                        # Handle both string and dict formats
                        if isinstance(subject, dict):
                            subject = subject.get("value")
                        if isinstance(predicate, dict):
                            predicate = predicate.get("value")
                        if isinstance(obj, dict):
                            obj = obj.get("value")
                        
                        if subject is not None and predicate is not None and obj is not None:
                            triples.append((subject, predicate, obj))
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting triples from SPARQL results: {e}")
        
        return triples
    
    @staticmethod
    def extract_frame_uris_from_results(results: Any) -> List[str]:
        """
        Extract frame URIs from SPARQL query results.
        
        Args:
            results: SPARQL query results
            
        Returns:
            List[str]: List of extracted frame URIs
        """
        frame_uris = []
        try:
            # Unwrap nested dict format: {'success': ..., 'results': {'bindings': [...]}}
            bindings = None
            if isinstance(results, dict):
                if 'results' in results and isinstance(results['results'], dict):
                    bindings = results['results'].get('bindings', [])
                elif 'bindings' in results:
                    bindings = results['bindings']
            
            if bindings is not None:
                for binding in bindings:
                    if isinstance(binding, dict):
                        frame_uri = binding.get("frame_uri", {}).get("value")
                        if frame_uri:
                            frame_uris.append(frame_uri)
            elif isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and "frame_uri" in item:
                        frame_value = item["frame_uri"]
                        if isinstance(frame_value, str):
                            frame_uris.append(frame_value)
                        elif isinstance(frame_value, dict):
                            frame_uri = frame_value.get("value")
                            if frame_uri:
                                frame_uris.append(frame_uri)
        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting frame URIs from SPARQL results: {e}")
        
        return frame_uris
    
    @staticmethod
    async def convert_triples_to_vitalsigns_frames(triples: List[Dict[str, str]]) -> List:
        """
        Convert triples to VitalSigns frame objects using GraphObject.from_triples_list().
        
        Args:
            triples: List of triple dictionaries with 'subject', 'predicate', 'object' keys
            
        Returns:
            List: List of VitalSigns KGFrame objects
        """
        try:
            if not triples:
                return []
            
            # Convert triples to the format expected by GraphObject.from_triples_list()
            # The method expects a Generator[Tuple, None, None] of RDFLib (URIRef, URIRef, URIRef/Literal) tuples
            def triples_generator():
                from rdflib import URIRef, Literal
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                for triple in triples:
                    subject = URIRef(triple["subject"])
                    predicate = URIRef(triple["predicate"])
                    
                    # Object might be a URI or literal value
                    obj_str = triple["object"]
                    if validate_rfc3986(obj_str, rule='URI'):
                        obj = URIRef(obj_str)
                    else:
                        obj = Literal(obj_str)
                    
                    yield (subject, predicate, obj)
            
            # Use GraphObject.from_triples_list() to convert all triples to VitalSigns objects
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            all_objects = await asyncio.to_thread(GraphObject.from_triples_list, list(triples_generator()))
            
            # Filter for KGFrame objects
            frames = []
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            
            for obj in all_objects:
                if isinstance(obj, KGFrame):
                    frames.append(obj)
            
            logger.debug(f"Converted {len(triples)} triples to {len(all_objects)} objects, {len(frames)} frames")
            
            return frames
            
        except Exception as e:
            logger.error(f"Error converting triples to VitalSigns frames: {e}")
            return []


class KGSparqlQueryBuilder:
    """Builder class for constructing common SPARQL queries."""
    
    def __init__(self):
        self.utils = KGSparqlUtils()
    
    def build_frame_discovery_query(self, graph_id: str, entity_uri: str, 
                                  page_size: int = 100, offset: int = 0, 
                                  search: Optional[str] = None) -> str:
        """
        Build SPARQL query to discover frames associated with an entity.
        
        Args:
            graph_id: Graph identifier
            entity_uri: Entity URI
            page_size: Number of results per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            str: SPARQL query string
        """
        search_filter = self.utils.build_search_filter(search) if search else ""
        pagination = self.utils.build_pagination_clause(page_size, offset)
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT DISTINCT ?frame WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                ?frame a haley:KGFrame ;
                       haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} .
                {search_filter}
            }}
        }}
        ORDER BY ?frame
        {pagination}
        """
    
    def build_frame_count_query(self, graph_id: str, entity_uri: str, 
                               search: Optional[str] = None) -> str:
        """
        Build SPARQL query to count frames associated with an entity.
        
        Args:
            graph_id: Graph identifier
            entity_uri: Entity URI
            search: Optional search term
            
        Returns:
            str: SPARQL count query string
        """
        search_filter = self.utils.build_search_filter(search) if search else ""
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT (COUNT(DISTINCT ?frame) as ?count) WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                ?frame a haley:KGFrame ;
                       haley:hasKGGraphURI {self.utils.build_uri_reference(entity_uri)} .
                {search_filter}
            }}
        }}
        """
    
    def build_frame_graph_query(self, graph_id: str, frame_uri: str, 
                               include_frame_graph: bool = True) -> str:
        """
        Build SPARQL query to get frame and optionally its complete graph.
        
        Args:
            graph_id: Graph identifier
            frame_uri: Frame URI
            include_frame_graph: Whether to include complete frame graph
            
        Returns:
            str: SPARQL query string
        """
        import logging
        logger = logging.getLogger(f"{__name__}.KGSparqlQueryBuilder")
        
        if include_frame_graph:
            # Get frame and all objects in its frame graph, including connecting edges
            query = f"""
            {self.utils.build_prefixes()}
            
            SELECT DISTINCT ?subject WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    {{
                        # Get the frame itself
                        BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                        {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame .
                    }} UNION {{
                        # Get all objects that belong to this frame's graph
                        ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                    }} UNION {{
                        # Get edges connecting objects within the frame
                        # Only include edges that have frameGraphURI (excludes Edge_hasEntityKGFrame)
                        ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                        ?subject vital:hasEdgeSource ?frameObject .
                    }}
                }}
            }}
            """
            logger.debug(f"🔍 Built frame graph query for {frame_uri}")
            logger.debug(f"🔍 Query will look for:")
            logger.debug(f"🔍   1. Frame itself: {frame_uri}")
            logger.debug(f"🔍   2. Objects with hasFrameGraphURI = {frame_uri}")
            logger.debug(f"🔍   3. Edges with hasFrameGraphURI = {frame_uri}")
            return query
        else:
            # Get only the frame itself
            return f"""
            {self.utils.build_prefixes()}
            
            SELECT DISTINCT ?subject WHERE {{
                {self.utils.build_graph_clause(graph_id)} {{
                    BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                    {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame .
                }}
            }}
            """
    
    def build_frame_deletion_count_query(self, graph_id: str, frame_uri: str) -> str:
        """
        Build SPARQL query to count objects that will be deleted with a frame.
        
        Args:
            graph_id: Graph identifier
            frame_uri: Frame URI
            
        Returns:
            str: SPARQL count query string
        """
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT (COUNT(?subject) as ?count) WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                {{
                    # Count the frame itself
                    BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                    {self.utils.build_uri_reference(frame_uri)} a haley:KGFrame .
                }} UNION {{
                    # Count all objects that belong to this frame's graph
                    ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} .
                }}
            }}
        }}
        """
    
    def build_frame_deletion_query(self, graph_id: str, frame_uri: str) -> str:
        """
        Build SPARQL DELETE query to remove frame and its complete graph.
        
        Args:
            graph_id: Graph identifier
            frame_uri: Frame URI
            
        Returns:
            str: SPARQL DELETE query string
        """
        return f"""
        {self.utils.build_prefixes()}
        
        DELETE {{
            {self.utils.build_graph_clause(graph_id)} {{
                ?subject ?predicate ?object .
            }}
        }}
        WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                {{
                    # Delete the frame itself
                    BIND({self.utils.build_uri_reference(frame_uri)} as ?subject)
                    {self.utils.build_uri_reference(frame_uri)} ?predicate ?object .
                }} UNION {{
                    # Delete all objects that belong to this frame's graph
                    ?subject haley:hasFrameGraphURI {self.utils.build_uri_reference(frame_uri)} ;
                             ?predicate ?object .
                }}
            }}
        }}
        """
    
    def build_entity_graphs_query(self, graph_id: str, entity_type_uri: Optional[str] = None, 
                                 search: Optional[str] = None, page_size: int = 100, 
                                 offset: int = 0) -> str:
        """
        Build SPARQL query for listing complete entity graphs (all objects with kGGraphURI).
        
        Args:
            graph_id: Graph identifier
            entity_type_uri: Optional entity type filter
            search: Optional search term
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            str: SPARQL query string
        """
        # Build entity type filter
        if entity_type_uri:
            entity_filter = f"?entity a {self.utils.build_uri_reference(entity_type_uri)} ."
        else:
            # UNION over the concrete KG entity classes rather than
            # `?entity a ?entityType` + STRSTARTS/STRENDS. The string form
            # joined every entity to its type and then filtered on the type's
            # text; this matches the classes directly, and prune_union drops
            # the branches whose class does not exist in the space before SQL
            # emission — this is the exact case its docstring cites.
            entity_filter = " UNION ".join(
                f"{{ ?entity a <{uri}> . }}" for uri in KG_ENTITY_CLASS_URIS)
        
        # Build search filter
        search_filter = ""
        if search:
            escaped_search = self.utils.escape_sparql_string(search)
            search_filter = f"""
            ?entity vital:hasName ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{escaped_search}")))
            """
        
        # Build pagination
        pagination = self.utils.build_pagination_clause(page_size, offset)
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT DISTINCT ?subject WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                # Find entities first
                {entity_filter}
                {search_filter}
                
                # Then find all objects with matching hasKGGraphURI
                ?subject haley:hasKGGraphURI ?entity .
            }}
        }}
        ORDER BY ?subject
        {pagination}
        """
    
    def build_list_entities_query(self, graph_id: str, entity_type_uri: Optional[str] = None, 
                                 search: Optional[str] = None, page_size: int = 100, 
                                 offset: int = 0) -> str:
        """
        Build SPARQL query for listing entity subjects (subject-first pattern).
        
        Args:
            graph_id: Graph identifier
            entity_type_uri: Optional entity type filter
            search: Optional search term
            page_size: Number of results per page
            offset: Offset for pagination
            
        Returns:
            str: SPARQL query string
        """
        # Build entity type filter
        # KGEntity uses hasKGEntityType property, not rdf:type
        if entity_type_uri:
            type_filter = f"""
            ?entity vital-core:vitaltype haley:KGEntity .
            ?entity haley:hasKGEntityType {self.utils.build_uri_reference(entity_type_uri)} .
            """
        else:
            type_filter = """
            ?entity vital-core:vitaltype haley:KGEntity .
            """
        
        # Build search filter
        search_filter = ""
        if search:
            escaped_search = self.utils.escape_sparql_string(search)
            search_filter = f"""
            ?entity vital:hasName ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{escaped_search}")))
            """
        
        # Build pagination
        pagination = self.utils.build_pagination_clause(page_size, offset)
        
        return f"""
        {self.utils.build_prefixes()}
        
        SELECT DISTINCT ?entity WHERE {{
            {self.utils.build_graph_clause(graph_id)} {{
                {type_filter}
                {search_filter}
            }}
        }}
        ORDER BY ?entity
        {pagination}
        """