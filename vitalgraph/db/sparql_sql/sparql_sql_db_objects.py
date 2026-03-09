"""
SPARQL-SQL Database Objects Layer

Implements the database objects layer for the sparql_sql backend.
Mirrors FusekiPostgreSQLDbObjects but uses execute_sparql_query()
via the V2 SPARQL-to-SQL pipeline instead of Fuseki directly.

Two-phase query pattern:
1. Phase 1: Find subject URIs matching criteria (SPARQL SELECT)
2. Phase 2: Retrieve complete triples for those URIs (SPARQL SELECT)
3. Phase 3: Convert triples to VitalSigns GraphObjects

Used by KGTypeImpl, ObjectsImpl, kgframe_graph_impl, and other
endpoint implementations via backend_adapter.backend.db_objects.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple

from rdflib import URIRef, Literal

logger = logging.getLogger(__name__)

# Materialized predicates to filter out (same as kg_graph_retrieval_utils)
_MATERIALIZED_PREDICATES = frozenset([
    'http://vital.ai/vitalgraph/direct#hasEntityFrame',
    'http://vital.ai/vitalgraph/direct#hasFrame',
    'http://vital.ai/vitalgraph/direct#hasSlot',
])


def _materialized_filter(pred_var: str = "?p") -> str:
    """SPARQL FILTER clause to exclude materialized predicates."""
    clauses = [f"{pred_var} != <{p}>" for p in _MATERIALIZED_PREDICATES]
    return f"FILTER({' && '.join(clauses)})"


class SparqlSQLDbObjects:
    """Database objects layer for the sparql_sql backend.

    Provides the same API as ``FusekiPostgreSQLDbObjects`` so that
    kg_impl code can call ``backend_adapter.backend.db_objects.*``
    regardless of which backend is active.
    """

    def __init__(self, space_impl):
        """
        Args:
            space_impl: SparqlSQLSpaceImpl instance (provides execute_sparql_query)
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.SparqlSQLDbObjects")
        self.logger.info("Initialized SparqlSQLDbObjects")

    # ------------------------------------------------------------------
    # list_objects
    # ------------------------------------------------------------------

    async def list_objects(
        self,
        space_id: str,
        graph_id: Optional[str] = None,
        page_size: int = 100,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Any], int]:
        """List objects using two-phase query: find URIs then get complete objects.

        Returns:
            (graph_objects, total_count)
        """
        try:
            if graph_id is None:
                graph_id = "main"

            # Phase 1 — find subject URIs
            subject_uris, total_count = await self._find_subject_uris(
                space_id, graph_id, filters, page_size, offset
            )
            if not subject_uris:
                return [], total_count

            # Phase 2 — get triples
            triples = await self._get_triples_for_uris(
                space_id, graph_id, subject_uris
            )
            if not triples:
                return [], total_count

            # Phase 3 — VitalSigns conversion
            objects = self._triples_to_vitalsigns(triples)
            return objects, total_count

        except Exception as e:
            self.logger.error("list_objects failed: %s", e)
            return [], 0

    # ------------------------------------------------------------------
    # get_objects_by_uris
    # ------------------------------------------------------------------

    async def get_objects_by_uris(
        self,
        space_id: str,
        uris: List[str],
        graph_id: Optional[str] = None,
    ) -> List[Any]:
        """Get multiple objects by URI list → VitalSigns GraphObjects."""
        try:
            if graph_id is None:
                graph_id = "main"
            if not uris:
                return []

            triples = await self._get_triples_for_uris(space_id, graph_id, uris)
            if not triples:
                return []

            return self._triples_to_vitalsigns(triples)

        except Exception as e:
            self.logger.error("get_objects_by_uris failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # get_objects_by_uris_batch (raw quads variant)
    # ------------------------------------------------------------------

    async def get_objects_by_uris_batch(
        self,
        space_id: str,
        subject_uris: List[str],
        graph_id: Optional[str] = None,
    ) -> List[Tuple[str, str, str, str]]:
        """Get objects as raw (s, p, o, g) quads."""
        try:
            if graph_id is None:
                graph_id = "main"
            if not subject_uris:
                return []

            triples = await self._get_triples_for_uris(
                space_id, graph_id, subject_uris
            )
            return [(s, p, o, graph_id) for s, p, o in triples]

        except Exception as e:
            self.logger.error("get_objects_by_uris_batch failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # get_existing_object_uris
    # ------------------------------------------------------------------

    async def get_existing_object_uris(
        self, space_id: str, uris: List[str]
    ) -> List[str]:
        """Return which of the given URIs actually exist in the space."""
        try:
            if not uris:
                return []

            uri_values = " ".join(f"<{u}>" for u in uris)
            query = f"""
            SELECT DISTINCT ?s WHERE {{
                VALUES ?s {{ {uri_values} }}
                ?s ?p ?o .
            }}
            """
            result = await self.space_impl.execute_sparql_query(space_id, query)
            bindings = self._extract_bindings(result)
            return [b['s']['value'] for b in bindings if 's' in b]

        except Exception as e:
            self.logger.error("get_existing_object_uris failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # get_object_by_uri
    # ------------------------------------------------------------------

    async def get_object_by_uri(
        self,
        space_id: str,
        uri: str,
        graph_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Get a single object by URI → VitalSigns GraphObject or None."""
        objects = await self.get_objects_by_uris(space_id, [uri], graph_id)
        return objects[0] if objects else None

    # ------------------------------------------------------------------
    # count_objects
    # ------------------------------------------------------------------

    async def count_objects(
        self,
        space_id: str,
        graph_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count objects matching criteria without retrieving them."""
        try:
            if graph_id is None:
                graph_id = "main"

            filter_clause = self._build_filter_clause(filters)
            query = f"""
            SELECT (COUNT(DISTINCT ?subject) AS ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    {filter_clause}
                }}
            }}
            """
            result = await self.space_impl.execute_sparql_query(space_id, query)
            bindings = self._extract_bindings(result)
            if bindings and 'count' in bindings[0]:
                return int(bindings[0]['count']['value'])
            return 0

        except Exception as e:
            self.logger.error("count_objects failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # search_objects
    # ------------------------------------------------------------------

    async def search_objects(
        self,
        space_id: str,
        search_text: str,
        graph_id: Optional[str] = None,
        vitaltype_filter: Optional[str] = None,
        page_size: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Any], int]:
        """Search objects by text across all properties."""
        filters: Dict[str, Any] = {'search_text': search_text}
        if vitaltype_filter:
            filters['vitaltype_filter'] = vitaltype_filter
        return await self.list_objects(
            space_id, graph_id, page_size, offset, filters
        )

    # ==================================================================
    # Internal helpers
    # ==================================================================

    async def _find_subject_uris(
        self,
        space_id: str,
        graph_id: str,
        filters: Optional[Dict[str, Any]],
        page_size: int,
        offset: int,
    ) -> Tuple[List[str], int]:
        """Phase 1: find distinct subject URIs matching criteria."""

        filter_clause = self._build_filter_clause(filters)

        query = f"""
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{graph_id}> {{
                {filter_clause}
            }}
        }}
        ORDER BY ?subject
        LIMIT {page_size} OFFSET {offset}
        """

        result = await self.space_impl.execute_sparql_query(space_id, query)
        bindings = self._extract_bindings(result)
        uris = [b['subject']['value'] for b in bindings if 'subject' in b]

        # Approximate total count from returned page
        total_count = len(uris)
        return uris, total_count

    async def _get_triples_for_uris(
        self,
        space_id: str,
        graph_id: str,
        subject_uris: List[str],
        batch_size: int = 100,
    ) -> List[Tuple[str, str, str]]:
        """Phase 2: batch-retrieve triples for a list of subject URIs.

        Returns list of (subject, predicate, object) string tuples
        converted to rdflib terms for VitalSigns compatibility.
        """
        all_triples: List[Tuple] = []

        for i in range(0, len(subject_uris), batch_size):
            batch = subject_uris[i : i + batch_size]
            uri_values = " ".join(f"<{u}>" for u in batch)

            query = f"""
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    VALUES ?s {{ {uri_values} }}
                    ?s ?p ?o .
                    {_materialized_filter()}
                }}
            }}
            """

            result = await self.space_impl.execute_sparql_query(space_id, query)
            bindings = self._extract_bindings(result)

            for b in bindings:
                s = b.get('s', {}).get('value')
                p = b.get('p', {}).get('value')
                o_data = b.get('o', {})
                if not (s and p and o_data.get('value') is not None):
                    continue

                s_term = URIRef(s)
                p_term = URIRef(p)

                o_type = o_data.get('type', 'literal')
                o_val = o_data['value']
                if o_type == 'uri':
                    o_term = URIRef(o_val)
                else:
                    lang = o_data.get('xml:lang')
                    datatype = o_data.get('datatype')
                    o_term = Literal(
                        o_val,
                        lang=lang,
                        datatype=URIRef(datatype) if datatype else None,
                    )

                all_triples.append((s_term, p_term, o_term))

        return all_triples

    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter_clause(filters: Optional[Dict[str, Any]]) -> str:
        """Build SPARQL filter body from a filters dict."""
        parts: List[str] = []
        if filters:
            vt = filters.get('vitaltype_filter')
            if vt:
                parts.append(f'?subject a <{vt}> .')

            search = filters.get('search_text')
            if search:
                escaped = search.replace('"', '\\"')
                parts.append(
                    '?subject ?searchProp ?searchValue .\n'
                    f'FILTER(CONTAINS(LCASE(STR(?searchValue)), LCASE("{escaped}")))'
                )

            subj = filters.get('subject_uri')
            if subj:
                parts.append(f'?subject = <{subj}> .')

        if not parts:
            parts.append('?subject a ?type .')

        return "\n                ".join(parts)

    @staticmethod
    def _extract_bindings(result: Any) -> List[Dict[str, Any]]:
        """Unwrap SPARQL JSON results to a list of binding dicts."""
        if isinstance(result, dict):
            if 'results' in result and 'bindings' in result['results']:
                return result['results']['bindings']
            if 'bindings' in result:
                return result['bindings']
        if isinstance(result, list):
            return result
        return []

    @staticmethod
    def _triples_to_vitalsigns(triples: List[Tuple]) -> List[Any]:
        """Convert rdflib triples to VitalSigns GraphObjects."""
        if not triples:
            return []
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vs = VitalSigns()
        return vs.from_triples_list(triples)
