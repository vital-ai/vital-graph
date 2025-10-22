"""
PostgreSQL Space Database Objects Operations

This module provides optimized database operations for object retrieval and management
that complement the existing db_ops layer. It focuses on read operations and bulk
object queries using optimized SQL.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any
import psycopg
from psycopg.rows import dict_row
from rdflib.term import Identifier

# Import PostgreSQL utilities
from ..postgresql_log_utils import PostgreSQLLogUtils
from .postgresql_space_utils import PostgreSQLSpaceUtils


class PostgreSQLSpaceDBObjects:
    """
    PostgreSQL database operations for object retrieval and management.
    
    This class handles optimized database operations for object queries:
    - Bulk object retrieval by URIs
    - Object existence checks for conflict detection
    - Object metadata operations (vitaltypes, counts)
    - Optimized SQL queries with proper indexing
    """
    
    def __init__(self, space_impl):
        """
        Initialize database objects operations with reference to space implementation.
        
            space_impl: PostgreSQLSpaceImpl instance for accessing connections and utilities
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def _strip_angle_brackets(self, uri_text: str) -> str:
        """
        Strip angle brackets from URI text if present.
        
        Args:
            uri_text: URI text that may have angle brackets
            
        Returns:
            Clean URI text without angle brackets
        """
        if uri_text.startswith('<') and uri_text.endswith('>'):
            return uri_text[1:-1]
        return uri_text
    
    def _convert_term_to_rdflib(self, term_text: str, term_type: str, lang: Optional[str] = None, 
                               datatype_id: Optional[int] = None):
        """
        Convert database term to appropriate RDFLib Identifier.
        
        Args:
            term_text: Text content of the term (can be None)
            term_type: Type of term ('U' for URI, 'L' for Literal, 'B' for BNode, 'G' for Graph)
            lang: Language tag for literals
            datatype_id: Datatype ID for literals
            
        Returns:
            RDFLib Identifier (URIRef, Literal, or BNode) or None if term_text is None
        """
        from rdflib import URIRef, Literal, BNode
        
        # Handle None values
        if term_text is None:
            return None
            
        if term_type == 'U' or term_type == 'G':
            # URI Reference or Graph (both treated as URIRef)
            # Strip angle brackets if present
            clean_uri = self._strip_angle_brackets(term_text)
            return URIRef(clean_uri)
        elif term_type == 'L':
            # Literal - handle language and datatype
            if lang:
                return Literal(term_text, lang=lang)
            elif datatype_id:
                # For now, create plain literal - datatype resolution can be added later if needed
                # TODO: Implement datatype_id to URI resolution if required
                return Literal(term_text)
            else:
                # Plain literal without language or datatype
                return Literal(term_text)
        elif term_type == 'B':
            # Blank Node
            return BNode(term_text)
        else:
            # Fallback to URIRef
            # Strip angle brackets if present
            clean_uri = self._strip_angle_brackets(term_text)
            return URIRef(clean_uri)
    
    async def get_objects_by_uris_batch(self, space_id: str, subject_uris: List[str], 
                                       graph_id: Optional[str] = None) -> List[Tuple]:
        """
        Get all quads for multiple objects by their URIs using optimized SQL.
{{ ... }}
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs to retrieve
            graph_id: Optional graph identifier to filter by
            
        Returns:
            List of tuples (subject, predicate, object, graph) as RDFLib Identifiers
        """
        if not subject_uris:
            return []
        
        try:
            # Get table names
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            # Build optimized query with JOINs - include term_type for proper RDFLib conversion
            query_parts = [
                "SELECT s.term_text as subject, p.term_text as predicate,",
                "       o.term_text as object, o.term_type as object_type,",
                "       o.lang as object_lang, o.datatype_id as object_datatype_id,",
                "       g.term_text as graph",
                f"FROM {quad_table} q",
                f"JOIN {term_table} s ON q.subject_uuid = s.term_uuid",
                f"JOIN {term_table} p ON q.predicate_uuid = p.term_uuid", 
                f"JOIN {term_table} o ON q.object_uuid = o.term_uuid",
                f"JOIN {term_table} g ON q.context_uuid = g.term_uuid",
                "WHERE s.term_text = ANY(%s)"
            ]
            
            # Create versions with and without angle brackets for each URI
            all_uri_variants = []
            for uri in subject_uris:
                all_uri_variants.append(uri)  # Without brackets
                all_uri_variants.append(f"<{uri}>")  # With brackets
            params = [all_uri_variants]
            
            # Add graph filter if specified
            if graph_id:
                query_parts.append("AND g.term_text = %s")
                params.append(graph_id)
            
            query = " ".join(query_parts)
            
            # Debug logging
            self.logger.info(f"Executing query for URIs: {subject_uris}")
            self.logger.info(f"Graph filter: {graph_id}")
            self.logger.debug(f"SQL Query: {query}")
            self.logger.debug(f"Parameters: {params}")
            
            # Execute query
            async with self.space_impl.core.get_dict_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
            
            # Convert to RDFLib Identifiers
            quads = []
            for row in rows:
                from rdflib import URIRef
                
                # Convert terms to appropriate RDFLib types using helper method
                # Strip angle brackets from URIs before creating URIRef objects
                subject = URIRef(self._strip_angle_brackets(row['subject']))  # Subjects are always URIs
                predicate = URIRef(self._strip_angle_brackets(row['predicate']))  # Predicates are always URIs
                
                # Convert object using proper term type information
                obj = self._convert_term_to_rdflib(
                    row['object'], 
                    row['object_type'], 
                    row['object_lang'], 
                    row['object_datatype_id']
                )
                
                # Skip quads with None objects (invalid RDF)
                if obj is None:
                    self.logger.warning(f"Skipping quad with None object - Subject: {subject}, Predicate: {predicate}, Object: None, Graph: {row['graph']}")
                    continue
                
                graph = URIRef(self._strip_angle_brackets(row['graph']))  # Graphs are always URIs
                
                self.logger.info(f"Subject: {subject}, Predicate: {predicate}, Object: {obj}, Graph: {graph}")
                
                quads.append((subject, predicate, obj, graph))
            
            self.logger.debug(f"Retrieved {len(quads)} quads for {len(subject_uris)} objects")
            return quads
            
        except Exception as e:
            self.logger.error(f"Error retrieving objects by URIs: {e}")
            raise
    
    async def get_object_quads_by_uri(self, space_id: str, subject_uri: str, 
                                     graph_id: Optional[str] = None) -> List[Tuple]:
        """
        Get all quads for a single object by URI.
        
        Args:
            space_id: Space identifier
            subject_uri: Subject URI to retrieve
            graph_id: Optional graph identifier to filter by
            
        Returns:
            List of tuples (subject, predicate, object, graph) as RDFLib Identifiers
        """
        return await self.get_objects_by_uris_batch(space_id, [subject_uri], graph_id)
    
    async def get_object_by_uri(self, space_id: str, uri: str, 
                               graph_id: Optional[str] = None) -> Optional[Any]:
        """
        Get a single object by URI and return as VitalSigns object.
        
        Args:
            space_id: Space identifier
            uri: Subject URI to retrieve
            graph_id: Optional graph identifier to filter by
            
        Returns:
            VitalSigns object or None if not found
        """
        try:
            # Get quads for this object
            quads = await self.get_object_quads_by_uri(space_id, uri, graph_id)
            
            if not quads:
                return None
            
            # Convert quads to JSON-LD, then to VitalSigns object
            from rdflib import Graph
            g = Graph()
            for s, p, o, graph_ctx in quads:
                g.add((s, p, o))
            
            # Convert to JSON-LD
            jsonld_str = g.serialize(format='json-ld')
            import json
            jsonld_doc = json.loads(jsonld_str)
            
            # Ensure proper JSON-LD structure for jsonld_to_graphobjects
            if isinstance(jsonld_doc, list):
                # Convert list to proper JSON-LD document structure
                jsonld_document = {
                    "@context": {
                        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                        "vital": "http://vital.ai/ontology/vital-core#",
                        "haley": "http://vital.ai/ontology/haley-ai-kg#"
                    },
                    "@graph": jsonld_doc
                }
            else:
                jsonld_document = jsonld_doc
            
            # Convert to VitalSigns objects
            from vitalgraph.utils.data_format_utils import jsonld_to_graphobjects
            objects = await jsonld_to_graphobjects(jsonld_document)
            
            # Return the first object (should be the only one for a single URI)
            if objects:
                return objects[0]
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting object by URI {uri}: {e}")
            return None
    
    async def check_objects_exist(self, space_id: str, subject_uris: List[str]) -> Dict[str, bool]:
        """
        Check which objects exist in the database using optimized direct term lookup.
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs to check
            
        Returns:
            Dictionary mapping URI to existence boolean
        """
        if not subject_uris:
            return {}
        
        try:
            # Get table names
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            # Create versions with and without angle brackets for each URI
            all_uri_variants = []
            for uri in subject_uris:
                all_uri_variants.append(uri)  # Without brackets
                all_uri_variants.append(f"<{uri}>")  # With brackets
            
            # Optimized query: direct term table lookup with existence check
            # This uses the new term_text index and is much faster than JOINing
            query = f"""
            SELECT DISTINCT term_text as subject_uri
            FROM {term_table}
            WHERE term_text = ANY(%s) 
              AND term_type = 'U'
              AND EXISTS (SELECT 1 FROM {quad_table} WHERE subject_uuid = term_uuid)
            """
            
            # Execute query
            async with self.space_impl.core.get_dict_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, [all_uri_variants])
                    rows = cursor.fetchall()
            
            # Build result dictionary - map back to original URIs (without angle brackets)
            existing_uris = set()
            for row in rows:
                uri_text = row['subject_uri']
                # Strip angle brackets if present to match original input
                clean_uri = self._strip_angle_brackets(uri_text)
                existing_uris.add(clean_uri)
            
            result = {uri: uri in existing_uris for uri in subject_uris}
            
            self.logger.debug(f"Checked existence for {len(subject_uris)} URIs, {len(existing_uris)} exist (optimized)")
            return result
            
        except Exception as e:
            self.logger.error(f"Error checking object existence: {e}")
            raise
    
    async def get_existing_object_uris(self, space_id: str, subject_uris: List[str]) -> List[str]:
        """
        Return list of URIs that already exist in the database.
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs to check
            
        Returns:
            List of URIs that exist in the database
        """
        existence_map = await self.check_objects_exist(space_id, subject_uris)
        return [uri for uri, exists in existence_map.items() if exists]
    
    async def get_object_vitaltypes(self, space_id: str, subject_uris: List[str]) -> Dict[str, str]:
        """
        Get vitaltype for each object URI.
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs
            
        Returns:
            Dictionary mapping subject URI to vitaltype URI
        """
        if not subject_uris:
            return {}
        
        try:
            # Get table names
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            # Query for vitaltype property
            from vital_ai_vitalsigns.model.vital_constants import VitalConstants
            vitaltype_uri = VitalConstants.vitaltype_uri
            
            query = f"""
            SELECT s.term_text as subject_uri, o.term_text as vitaltype_uri
            FROM {quad_table} q
            JOIN {term_table} s ON q.subject_uuid = s.term_uuid
            JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
            JOIN {term_table} o ON q.object_uuid = o.term_uuid
            WHERE s.term_text = ANY(%s) AND p.term_text = %s
            """
            
            # Execute query
            async with self.space_impl.core.get_dict_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, [subject_uris, vitaltype_uri])
                    rows = cursor.fetchall()
            
            # Build result dictionary
            result = {row['subject_uri']: row['vitaltype_uri'] for row in rows}
            
            self.logger.debug(f"Retrieved vitaltypes for {len(result)} objects")
            return result
            
        except Exception as e:
            self.logger.error(f"Error retrieving object vitaltypes: {e}")
            raise
    
    async def count_objects_by_vitaltype(self, space_id: str, vitaltype_uri: str, 
                                        graph_id: Optional[str] = None) -> int:
        """
        Count objects of a specific vitaltype using optimized queries.
        
        Args:
            space_id: Space identifier
            vitaltype_uri: Vitaltype URI to count
            graph_id: Optional graph identifier to filter by
            
        Returns:
            Number of objects with the specified vitaltype
        """
        try:
            # Get table names
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            # Query for vitaltype count
            from vital_ai_vitalsigns.model.vital_constants import VitalConstants
            vitaltype_predicate = VitalConstants.vitaltype_uri
            
            # Optimized query: avoid COUNT(DISTINCT) and unnecessary JOINs
            # Use subqueries to leverage term_text indexes
            if graph_id:
                # Complex case: with graph filter
                query = f"""
                SELECT COUNT(*) as count
                FROM {quad_table} q
                WHERE q.predicate_uuid = (SELECT term_uuid FROM {term_table} WHERE term_text = %s)
                  AND q.object_uuid = (SELECT term_uuid FROM {term_table} WHERE term_text = %s)
                  AND q.context_uuid = (SELECT term_uuid FROM {term_table} WHERE term_text = %s)
                """
                params = [vitaltype_predicate, vitaltype_uri, graph_id]
            else:
                # Simple case: no graph filter - much faster
                query = f"""
                SELECT COUNT(*) as count
                FROM {quad_table} q
                WHERE q.predicate_uuid = (SELECT term_uuid FROM {term_table} WHERE term_text = %s)
                  AND q.object_uuid = (SELECT term_uuid FROM {term_table} WHERE term_text = %s)
                """
                params = [vitaltype_predicate, vitaltype_uri]
            
            # Execute query
            async with self.space_impl.core.get_dict_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    result = cursor.fetchone()
            
            count = result['count'] if result else 0
            self.logger.debug(f"Found {count} objects with vitaltype {vitaltype_uri} (optimized query)")
            return count
            
        except Exception as e:
            self.logger.error(f"Error counting objects by vitaltype: {e}")
            raise
    
    def _is_simple_count_query(self, filters: Dict[str, Any]) -> bool:
        """
        Determine if we can use a simple optimized count query.
        
        Args:
            filters: Dictionary of filter parameters
            
        Returns:
            True if simple count query can be used, False for complex query
        """
        # Simple queries: no filters or only graph_id filter
        complex_filters = ['vitaltype_filter', 'search_text', 'subject_uri']
        return not any(filters.get(f) for f in complex_filters)
    
    async def _get_simple_count(self, space_id: str, graph_id: Optional[str] = None) -> int:
        """
        Get count using optimized simple query for cases with no complex filters.
        
        Args:
            space_id: Space identifier
            graph_id: Optional graph identifier to filter by
            
        Returns:
            Total count of distinct subjects
        """
        try:
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            if graph_id:
                # Simple case with graph filter - use index on context_uuid
                query = f"""
                SELECT COUNT(DISTINCT subject_uuid) as count
                FROM {quad_table} 
                WHERE context_uuid = (SELECT term_uuid FROM {term_table} WHERE term_text = %s)
                """
                params = [graph_id]
            else:
                # Simplest case: count all distinct subjects
                query = f"SELECT COUNT(DISTINCT subject_uuid) as count FROM {quad_table}"
                params = []
            
            async with self.space_impl.core.get_dict_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    result = cursor.fetchone()
            
            count = result['count'] if result else 0
            self.logger.debug(f"Simple count query returned {count} objects")
            return count
            
        except Exception as e:
            self.logger.error(f"Error in simple count query: {e}")
            raise
    
    async def _get_complex_count(self, space_id: str, filters: Dict[str, Any]) -> int:
        """
        Get count using complex query for cases with multiple filters.
        
        Args:
            space_id: Space identifier
            filters: Dictionary of filter parameters
            
        Returns:
            Total count matching the complex filters
        """
        try:
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            # Build complex query with JOINs instead of subqueries for better performance
            joins = [f"JOIN {term_table} ts ON q.subject_uuid = ts.term_uuid"]
            where_conditions = ["1=1"]
            params = []
            
            # Add graph filter
            if filters.get('graph_id'):
                joins.append(f"JOIN {term_table} tg ON q.context_uuid = tg.term_uuid")
                where_conditions.append("tg.term_text = %s")
                params.append(filters['graph_id'])
            
            # Add vitaltype filter
            if filters.get('vitaltype_filter'):
                joins.extend([
                    f"JOIN {quad_table} q2 ON q.subject_uuid = q2.subject_uuid",
                    f"JOIN {term_table} tp ON q2.predicate_uuid = tp.term_uuid",
                    f"JOIN {term_table} to_vt ON q2.object_uuid = to_vt.term_uuid"
                ])
                where_conditions.extend([
                    "tp.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'",
                    "to_vt.term_text = %s"
                ])
                params.append(filters['vitaltype_filter'])
            
            # Add subject URI filter
            if filters.get('subject_uri'):
                where_conditions.append("ts.term_text = %s")
                params.append(filters['subject_uri'])
            
            # Add search text filter
            if filters.get('search_text'):
                joins.append(f"LEFT JOIN {term_table} tobj ON q.object_uuid = tobj.term_uuid")
                where_conditions.append("(ts.term_text ILIKE %s OR tobj.term_text ILIKE %s)")
                search_param = f"%{filters['search_text']}%"
                params.extend([search_param, search_param])
            
            # Build final query
            join_clause = " ".join(joins)
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
            SELECT COUNT(DISTINCT q.subject_uuid) as count
            FROM {quad_table} q
            {join_clause}
            WHERE {where_clause}
            """
            
            async with self.space_impl.core.get_dict_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    result = cursor.fetchone()
            
            count = result['count'] if result else 0
            self.logger.debug(f"Complex count query returned {count} objects")
            return count
            
        except Exception as e:
            self.logger.error(f"Error in complex count query: {e}")
            raise
    
    async def list_objects(self, space_id: str, graph_id: Optional[str] = None, 
                          page_size: int = 100, offset: int = 0, 
                          vitaltype_filter: Optional[str] = None, 
                          search_text: Optional[str] = None,
                          subject_uri: Optional[str] = None,
                          filters: Optional[Dict[str, Any]] = None) -> Tuple[List[Any], int]:
        """
        List objects with pagination and filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Optional graph identifier for filtering
            page_size: Number of objects per page
            offset: Offset for pagination
            vitaltype_filter: Optional vitaltype URI for filtering
            search_text: Optional text search
            subject_uri: Optional specific subject URI
            filters: Optional dictionary of filters (overrides individual filter params)
            
        Returns:
            Tuple of (objects_list, total_count)
        """
        try:
            # If filters dict is provided, extract values from it
            if filters:
                # Handle both 'vitaltype_filter' and 'vitaltype_uri' for backward compatibility
                vitaltype_filter = filters.get('vitaltype_filter', filters.get('vitaltype_uri', vitaltype_filter))
                search_text = filters.get('search_text', search_text)
                subject_uri = filters.get('subject_uri', subject_uri)
                # graph_id can also come from filters if needed
                graph_id = filters.get('graph_id', graph_id)
            
            # Create filters dictionary for helper methods
            filter_dict = {
                'graph_id': graph_id,
                'vitaltype_filter': vitaltype_filter,
                'search_text': search_text,
                'subject_uri': subject_uri
            }
            
            # Use optimized count query based on complexity
            if self._is_simple_count_query(filter_dict):
                total_count = await self._get_simple_count(space_id, graph_id)
            else:
                total_count = await self._get_complex_count(space_id, filter_dict)
            
            # Get table names for main query
            quad_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "rdf_quad"
            )
            term_table = self.space_impl.utils.get_table_name(
                self.space_impl.global_prefix, space_id, "term"
            )
            
            # Build main query using same logic as complex count but with pagination
            joins = [f"JOIN {term_table} ts ON q.subject_uuid = ts.term_uuid"]
            where_conditions = ["1=1"]
            params = []
            
            # Add filters (same logic as _get_complex_count)
            if graph_id:
                joins.append(f"JOIN {term_table} tg ON q.context_uuid = tg.term_uuid")
                where_conditions.append("tg.term_text = %s")
                params.append(graph_id)
            
            if vitaltype_filter:
                joins.extend([
                    f"JOIN {quad_table} q2 ON q.subject_uuid = q2.subject_uuid",
                    f"JOIN {term_table} tp ON q2.predicate_uuid = tp.term_uuid",
                    f"JOIN {term_table} to_vt ON q2.object_uuid = to_vt.term_uuid"
                ])
                where_conditions.extend([
                    "tp.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'",
                    "to_vt.term_text = %s"
                ])
                params.append(vitaltype_filter)
            
            if subject_uri:
                where_conditions.append("ts.term_text = %s")
                params.append(subject_uri)
            
            if search_text:
                joins.append(f"LEFT JOIN {term_table} tobj ON q.object_uuid = tobj.term_uuid")
                where_conditions.append("(ts.term_text ILIKE %s OR tobj.term_text ILIKE %s)")
                search_param = f"%{search_text}%"
                params.extend([search_param, search_param])
            
            # Build final main query
            join_clause = " ".join(joins)
            where_clause = " AND ".join(where_conditions)
            
            main_query = f"""
                SELECT DISTINCT 
                    ts.term_text as subject_uri,
                    ts.term_type as subject_type
                FROM {quad_table} q
                {join_clause}
                WHERE {where_clause}
                ORDER BY ts.term_text
                LIMIT %s OFFSET %s
            """
            
            # Add pagination parameters
            main_params = params + [page_size, offset]
            
            async with self.space_impl.core.get_dict_connection() as conn:
                
                # Get objects (use main_params which includes pagination)
                with conn.cursor() as cursor:
                    cursor.execute(main_query, main_params)
                    rows = cursor.fetchall()
                
                # Extract subject URIs and get full objects
                subject_uris = [row['subject_uri'] for row in rows]
                
                if subject_uris:
                    try:
                        # Get full quads for these objects
                        quads = await self.get_objects_by_uris_batch(space_id, subject_uris, graph_id)
                        self.logger.debug(f"Retrieved {len(quads)} quads for objects")
                        
                        # Convert quads to JSON-LD, then to VitalSigns objects
                        from rdflib import Graph
                        g = Graph()
                        for s, p, o, graph_ctx in quads:
                            g.add((s, p, o))
                        
                        # Convert to JSON-LD
                        jsonld_str = g.serialize(format='json-ld')
                        import json
                        jsonld_doc = json.loads(jsonld_str)
                        
                        # Ensure proper JSON-LD structure for jsonld_to_graphobjects
                        if isinstance(jsonld_doc, list):
                            # Convert list to proper JSON-LD document structure
                            jsonld_document = {
                                "@context": {
                                    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                                    "vital": "http://vital.ai/ontology/vital-core#",
                                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                                },
                                "@graph": jsonld_doc
                            }
                        else:
                            jsonld_document = jsonld_doc
                        
                        # Convert to VitalSigns objects
                        from vitalgraph.utils.data_format_utils import jsonld_to_graphobjects
                        objects = await jsonld_to_graphobjects(jsonld_document)
                    except Exception as conversion_error:
                        self.logger.error(f"Error converting objects: {conversion_error}")
                        # Fallback to basic object info
                        objects = []
                        for uri in subject_uris:
                            objects.append({'subject_uri': uri, 'vitaltype_uri': None})
                else:
                    objects = []
                
                self.logger.debug(f"Listed {len(objects)} objects (total: {total_count}) in space {space_id}")
                return objects, total_count
                
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            import traceback
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            raise