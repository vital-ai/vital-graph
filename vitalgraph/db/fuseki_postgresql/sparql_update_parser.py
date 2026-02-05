"""
SPARQL UPDATE parser for FUSEKI_POSTGRESQL hybrid backend.
Parses SPARQL UPDATE operations to determine affected triples for dual-write operations.
"""

import logging
from typing import Dict, List, Any, Optional
from rdflib.plugins.sparql import prepareQuery

logger = logging.getLogger(__name__)


class SPARQLUpdateParser:
    """
    Parses SPARQL UPDATE operations to determine affected triples.
    
    Uses rdflib to parse UPDATE queries and extract:
    - INSERT operations: New triples being added
    - DELETE operations: Query patterns to find triples being removed
    - DELETE/INSERT operations: Combined operations
    
    For DELETE operations, executes queries against Fuseki to determine
    the exact triples that will be affected before applying the update.
    """
    
    def __init__(self, fuseki_manager):
        """
        Initialize SPARQL UPDATE parser.
        
        Args:
            fuseki_manager: FusekiDatasetManager instance for query execution
        """
        self.fuseki_manager = fuseki_manager
        self.logger = logging.getLogger(__name__)
    
    async def parse_update_operation(self, space_id: str, sparql_update: str) -> Dict[str, Any]:
        """
        Parse SPARQL UPDATE and determine affected triples.
        
        Args:
            space_id: Target space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            Dictionary containing:
            - operation_type: 'insert', 'delete', 'delete_insert', 'insert_data', 'delete_data'
            - insert_triples: List of triples to be inserted
            - delete_triples: List of triples to be deleted (resolved from patterns)
            - raw_update: Original SPARQL UPDATE string
        """
        
        # Strip leading/trailing whitespace at entry point - RDFLib is sensitive to this
        import time
        parse_start = time.time()
        sparql_update = sparql_update.strip()
        strip_time = time.time() - parse_start
        logger.info(f"🔥 PARSER: parse_update_operation() started, stripped whitespace in {strip_time:.3f}s")
        
        try:
            identify_start = time.time()
            logger.info(f"🔥 PARSER: Calling _identify_operation_type()...")
            operation_type = self._identify_operation_type(sparql_update)
            identify_time = time.time() - identify_start
            logger.info(f"� PARSER: _identify_operation_type() completed in {identify_time:.3f}s, type={operation_type}")
            
            result = {
                'operation_type': operation_type,
                'insert_triples': [],
                'delete_triples': [],
                'raw_update': sparql_update
            }
            
            # Extract patterns from the query
            patterns_start = time.time()
            logger.info(f"🔥 PARSER: Calling _extract_patterns_from_query()...")
            patterns = self._extract_patterns_from_query(sparql_update)
            patterns_time = time.time() - patterns_start
            logger.info(f"🔥 PARSER: _extract_patterns_from_query() completed in {patterns_time:.3f}s")
            
            # Handle INSERT operations  
            if operation_type in ['insert', 'delete_insert', 'insert_data', 'insert_delete_pattern']:
                if operation_type == 'insert_data':
                    # For INSERT DATA, extract concrete triples directly
                    result['insert_triples'] = self._extract_insert_data_triples(sparql_update)
                elif operation_type == 'insert_delete_pattern':
                    # For INSERT/DELETE with WHERE patterns, resolve INSERT triples from Fuseki
                    insert_triples = await self._resolve_insert_patterns_from_fuseki(
                        space_id, sparql_update
                    )
                    result['insert_triples'] = insert_triples
                    logger.debug(f"🔍 INSERT triples resolved for operation: {len(insert_triples)} triples")
                    for triple in insert_triples:
                        logger.debug(f"🔍 INSERT triple in result: {triple}")
                else:
                    # For INSERT with WHERE, we need the concrete triples after variable binding
                    # This is complex - for now, we'll handle this in the dual-write coordinator
                    result['insert_patterns'] = patterns.get('insert_patterns', [])
            
            # Handle DELETE operations
            if operation_type in ['delete', 'delete_insert', 'delete_data', 'insert_delete_pattern']:
                if operation_type == 'delete_data':
                    # For DELETE DATA, extract concrete triples directly
                    import time
                    extract_start = time.time()
                    logger.info(f"🔥 PARSER: Calling _extract_delete_data_triples() for DELETE DATA...")
                    result['delete_triples'] = self._extract_delete_data_triples(sparql_update)
                    extract_time = time.time() - extract_start
                    logger.info(f"🔥 PARSER: _extract_delete_data_triples() completed in {extract_time:.3f}s, found {len(result['delete_triples'])} triples")
                else:
                    # For DELETE with WHERE patterns, resolve to concrete triples
                    result['delete_triples'] = await self._resolve_delete_patterns_from_fuseki(
                        space_id, sparql_update
                    )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing SPARQL UPDATE: {e}")
            return {
                'operation_type': 'unknown',
                'insert_triples': [],
                'delete_triples': [],
                'raw_update': sparql_update,
                'error': str(e)
            }
    
    async def _resolve_delete_patterns(self, space_id: str, delete_patterns: List[str], where_clause: Optional[str]) -> List[tuple]:
        """
        Execute SELECT query to find triples matching DELETE patterns.
        
        For DELETE operations like:
        DELETE { ?s ?p ?o } WHERE { ?s a :Person . ?s :name ?name }
        
        Convert to SELECT query:
        SELECT ?s ?p ?o WHERE { ?s a :Person . ?s :name ?name . ?s ?p ?o }
        
        Then execute against Fuseki to get actual triples that will be deleted.
        """
        
        if not delete_patterns:
            return []
        
        try:
            # Build SELECT query from DELETE patterns and WHERE clause
            select_query = self._build_resolution_query(delete_patterns, where_clause)
            
            # Execute against Fuseki dataset
            results = await self.fuseki_manager.query_dataset(space_id, select_query)
            
            # Convert SPARQL results to triple format
            return self._sparql_results_to_triples(results)
            
        except Exception as e:
            self.logger.error(f"Error resolving DELETE patterns: {e}")
            return []
    
    async def _resolve_delete_patterns_from_fuseki(self, space_id: str, sparql_update: str) -> List[tuple]:
        """
        Resolve DELETE patterns by querying Fuseki to find concrete triples.
        
        For DELETE operations with WHERE clauses, we need to:
        1. Convert the DELETE pattern to a SELECT query
        2. Execute the SELECT query against Fuseki to find matching triples
        3. Return the concrete triples for deletion from PostgreSQL
        """
        try:
            logger.debug("🔍 Resolving DELETE patterns from Fuseki...")
            
            # Convert DELETE to SELECT query
            select_query = self._convert_delete_to_select_query(sparql_update)
            
            if not select_query:
                logger.error("❌ Could not convert DELETE to SELECT query")
                return []
            
            logger.debug(f"✅ Converted to SELECT query:")
            logger.debug(f"   {select_query}")
            logger.debug(f"🔍 SELECT query length: {len(select_query)} characters")
            
            # For UPDATE operations, we need to query for the specific predicate/object pattern
            # not just variables, so let's create a more specific query
            if "foaf:age ?oldAge" in sparql_update:
                # This is an UPDATE operation targeting foaf:age, query for existing age values
                subject_uri = self._extract_subject_from_delete_query(sparql_update)
                graph_uri = self._extract_graph_from_delete_query(sparql_update)
                if subject_uri and graph_uri:
                    specific_query = f"""
                    SELECT ?p ?o WHERE {{
                        GRAPH <{graph_uri}> {{
                            <{subject_uri}> ?p ?o .
                            FILTER(?p = <http://xmlns.com/foaf/0.1/age>)
                        }}
                    }}
                    """
                    select_query = specific_query
                    logger.debug(f"🔄 Using specific UPDATE query: {select_query}")
            
            # Execute SELECT query against Fuseki to find concrete triples
            if self.fuseki_manager:
                # CRITICAL FIX: Extract ALL subjects from DELETE pattern, not just the first one
                all_subjects = self._extract_all_subjects_from_delete_query(sparql_update)
                graph_uri = self._extract_graph_from_delete_query(sparql_update)
                
                logger.debug(f"🔍 Extracted {len(all_subjects)} subjects from DELETE query")
                logger.debug(f"🔍 Extracted graph URI from DELETE query: {graph_uri}")
                
                # Graph URI is required for DELETE operations
                if graph_uri is None:
                    logger.error(f"❌ DELETE query must specify a GRAPH clause - no graph URI found in query")
                    return []
                
                # Convert Fuseki results to triple format
                triples = []
                
                # Query Fuseki for each subject to find all its triples
                for subject_uri in all_subjects:
                    subject_query = f"""
                    SELECT ?p ?o WHERE {{
                        GRAPH <{graph_uri}> {{
                            <{subject_uri}> ?p ?o .
                        }}
                    }}
                    """
                    
                    logger.debug(f"🔍 Querying Fuseki for subject: {subject_uri}")
                    results = await self.fuseki_manager.query_dataset(space_id, subject_query)
                    logger.debug(f"📊 Found {len(results)} triples for subject {subject_uri}")
                    
                    for result in results:
                        # Handle SPARQL JSON result format: {'p': {...}, 'o': {...}}
                        if isinstance(result, dict) and 'p' in result and 'o' in result:
                            predicate = result['p']['value']
                            object_val = self._format_sparql_term(result['o'])
                        # Handle tuple format: (predicate, object)
                        elif isinstance(result, (list, tuple)) and len(result) >= 2:
                            predicate = str(result[0])
                            object_val = str(result[1])
                        else:
                            logger.warning(f"Skipping malformed result: {result}")
                            continue
                        
                        # Skip empty results
                        if not predicate or not object_val:
                            logger.warning(f"Skipping empty result: {result}")
                            continue
                        
                        # Create tuple format: (subject, predicate, object, graph)
                        triple_tuple = (subject_uri, predicate, object_val, graph_uri)
                        triples.append(triple_tuple)
                        logger.debug(f"🔍 Resolved triple: {triple_tuple}")
                
                logger.debug(f"✅ Resolved {len(triples)} concrete triples from DELETE pattern with {len(all_subjects)} subjects")
                return triples
            else:
                logger.error("❌ No Fuseki manager available for pattern resolution")
                return []
            
        except Exception as e:
            logger.error(f"❌ Error resolving DELETE patterns from Fuseki: {e}")
            return []
    
    def _convert_delete_to_select_query(self, sparql_update: str) -> str:
        """
        Convert DELETE query to SELECT query using pure RDFLib SPARQL parsing.
        
        For DELETE operations, extract variables from DELETE clause and WHERE clause
        using RDFLib algebra traversal only.
        """
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            from rdflib import Variable
            
            logger.debug(f"🔍 Converting DELETE to SELECT for SPARQL:\n{sparql_update}")
            
            # Parse the DELETE query using RDFLib
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            logger.debug(f"🔍 Parsed algebra structure: {algebra}")
            
            # RDFLib returns an UpdateRequest object containing update operations
            if hasattr(algebra, 'request'):
                operations = algebra.request if hasattr(algebra.request, '__iter__') else [algebra.request]
            else:
                operations = [algebra]
            
            # Process each update operation to find DELETE operations
            for op in operations:
                logger.debug(f"🔍 Processing operation: {type(op)}")
                
                # Handle nested algebra structure - look for actual operations in algebra attribute
                actual_ops = []
                if hasattr(op, 'algebra'):
                    if isinstance(op.algebra, list):
                        actual_ops = op.algebra
                    else:
                        actual_ops = [op.algebra]
                else:
                    actual_ops = [op]
                
                # Process each actual operation
                for actual_op in actual_ops:
                    logger.debug(f"🔍 Processing actual operation: {type(actual_op)}")
                    
                    # Check if this is a Modify operation with DELETE clause
                    if hasattr(actual_op, 'delete') and actual_op.delete is not None:
                        # Extract variables from DELETE and WHERE clauses
                        variables = set()
                        
                        # Get variables from DELETE clause
                        delete_vars = self._extract_variables_from_clause(actual_op.delete)
                        variables.update(delete_vars)
                        logger.debug(f"🔍 Variables from DELETE clause: {delete_vars}")
                        
                        # Get variables from WHERE clause if present
                        where_vars = set()
                        where_pattern = ""
                        if hasattr(actual_op, 'where') and actual_op.where is not None:
                            where_vars = self._extract_variables_from_clause(actual_op.where)
                            variables.update(where_vars)
                            where_pattern = self._algebra_to_sparql_pattern(actual_op.where)
                            logger.debug(f"🔍 Variables from WHERE clause: {where_vars}")
                            logger.debug(f"🔍 WHERE pattern: {where_pattern}")
                        
                        # Build SELECT query with extracted variables
                        if variables:
                            var_list = sorted([f'?{var}' for var in variables])
                            select_vars = ' '.join(var_list)
                        else:
                            logger.error("❌ No variables extracted from DELETE/WHERE clauses")
                            raise ValueError("Could not extract variables from DELETE query")
                        
                        if not where_pattern:
                            logger.error("❌ No WHERE pattern extracted from DELETE query")
                            raise ValueError("Could not extract WHERE pattern from DELETE query")
                        
                        select_query = f"SELECT {select_vars} WHERE {{ {where_pattern} }}"
                        logger.debug(f"🔍 Generated SELECT query: {select_query}")
                        return select_query
            
            logger.error("❌ Could not extract DELETE patterns from RDFLib algebra")
            raise ValueError("Could not find DELETE operation in parsed algebra")
            
        except Exception as e:
            logger.error(f"Error converting DELETE to SELECT using RDFLib: {e}")
            logger.debug(f"🔍 Failed SPARQL was:\n{sparql_update}")
            raise
    
    def _extract_variables_from_clause(self, clause) -> set:
        """Extract variables from a DELETE/INSERT/WHERE clause."""
        variables = set()
        try:
            from rdflib import Variable
            
            logger.debug(f"Extracting variables from clause type: {type(clause)}")
            
            # Handle None clause
            if clause is None:
                logger.warning("Clause is None, cannot extract variables")
                return variables
            
            # Handle CompValue nodes (Join, Graph, BGP, etc.)
            if hasattr(clause, 'name'):
                logger.debug(f"Clause is CompValue with name: {clause.name}")
                # Recursively traverse the CompValue structure
                variables.update(self._extract_variables_from_algebra_node(clause))
                return variables
            
            # Handle different clause structures
            if hasattr(clause, 'triples') and clause.triples is not None:
                # Direct triples access
                for triple in clause.triples:
                    variables.update(self._extract_variables_from_triple(triple))
            elif hasattr(clause, 'quads') and clause.quads is not None:
                # Quad-based structure (graph-aware)
                for graph_uri, triples in clause.quads.items():
                    for triple in triples:
                        variables.update(self._extract_variables_from_triple(triple))
            elif hasattr(clause, '__iter__'):
                # Iterable of triples
                try:
                    for triple in clause:
                        variables.update(self._extract_variables_from_triple(triple))
                except TypeError:
                    # Not actually iterable
                    pass
            else:
                # Try to traverse the algebra tree
                variables.update(self._extract_variables_from_algebra_node(clause))
                
        except Exception as e:
            logger.error(f"Error extracting variables from clause: {e}")
            
        return variables
    
    def _extract_variables_from_triple(self, triple) -> set:
        """Extract variables from a single triple."""
        variables = set()
        try:
            from rdflib import Variable
            
            # Validate triple has exactly 3 components
            if not hasattr(triple, '__len__') or len(triple) != 3:
                logger.warning(f"Invalid triple format - expected 3 components, got {len(triple) if hasattr(triple, '__len__') else 'unknown'}: {triple}")
                return variables
            
            s, p, o = triple
            
            # Check each component for variables
            for term in [s, p, o]:
                if isinstance(term, Variable):
                    variables.add(str(term))
                    
        except Exception as e:
            logger.error(f"Error extracting variables from triple: {e}")
            
        return variables

    def _extract_variables_from_algebra_node(self, node) -> set:
        """Extract variables from an RDFLib algebra node."""
        from rdflib import Variable
        from collections import defaultdict
        
        variables = set()
        
        def traverse(n):
            # Handle Variable objects directly
            if isinstance(n, Variable):
                variables.add(str(n).replace('?', ''))
                return
            
            # Handle RDFLib CompValue objects (they act like dictionaries)
            if hasattr(n, 'items') and callable(getattr(n, 'items')):
                try:
                    for key, value in n.items():
                        traverse(key)
                        traverse(value)
                    return
                except (TypeError, AttributeError):
                    pass
            
            # Handle dictionaries (like quads defaultdict)
            if isinstance(n, dict):
                for key, value in n.items():
                    traverse(key)
                    traverse(value)
                return
            
            # Handle defaultdict specifically
            if isinstance(n, defaultdict):
                for key, value in n.items():
                    traverse(key)
                    traverse(value)
                return
            
            # Handle lists and tuples
            if hasattr(n, '__iter__') and not isinstance(n, (str, bytes)):
                try:
                    for child in n:
                        traverse(child)
                except (TypeError, AttributeError):
                    pass
                return
            
            # Handle regular objects with __dict__
            if hasattr(n, '__dict__'):
                for attr_name, attr_value in n.__dict__.items():
                    if attr_value is not None:
                        traverse(attr_value)
        
        traverse(node)
        return variables
    
    def _algebra_node_to_sparql(self, node) -> str:
        """Convert RDFLib algebra node back to SPARQL pattern using simplified approach."""
        try:
            from rdflib import URIRef, Variable, Literal
            
            # For WHERE clause reconstruction, use a simpler approach
            # Extract the key components we need for a valid SELECT query
            
            # Get variables from the node
            variables = self._extract_variables_from_algebra_node(node)
            
            # Try to find graph URI and basic triple pattern from the algebra structure
            graph_uri = None
            subject_uri = None
            
            def find_graph_and_subject(n):
                nonlocal graph_uri, subject_uri
                
                # Look for Graph nodes with URIRef terms
                if hasattr(n, 'term') and isinstance(n.term, URIRef):
                    graph_uri = str(n.term)
                
                # Look for BGP triples with URIRef subjects
                if hasattr(n, 'triples') and n.triples:
                    for triple in n.triples:
                        s, p, o = triple
                        if isinstance(s, URIRef):
                            subject_uri = str(s)
                            break
                
                # Recursively search CompValue objects
                if hasattr(n, 'items') and callable(getattr(n, 'items')):
                    try:
                        for key, value in n.items():
                            find_graph_and_subject(value)
                    except (TypeError, AttributeError):
                        pass
                
                # Search lists and iterables
                if hasattr(n, '__iter__') and not isinstance(n, (str, bytes)):
                    try:
                        for child in n:
                            find_graph_and_subject(child)
                    except (TypeError, AttributeError):
                        pass
            
            # Extract graph and subject information
            find_graph_and_subject(node)
            
            # Build a proper SPARQL pattern
            if graph_uri and subject_uri and variables:
                vars_str = ' '.join([f'?{var}' for var in sorted(variables)])
                pattern = f"<{subject_uri}> ?p ?o ."
                return f"GRAPH <{graph_uri}> {{ {pattern} }}"
            elif graph_uri and variables:
                vars_str = ' '.join([f'?{var}' for var in sorted(variables)])
                if len(variables) >= 2:
                    vars_list = sorted(variables)
                    pattern = f"?s ?{vars_list[0]} ?{vars_list[1]} ."
                else:
                    pattern = f"?s ?p ?{list(variables)[0]} ."
                return f"GRAPH <{graph_uri}> {{ {pattern} }}"
            elif variables:
                # Fallback to basic pattern with variables
                vars_list = sorted(variables)
                if len(vars_list) >= 2:
                    return f"?s ?{vars_list[0]} ?{vars_list[1]} ."
                else:
                    return f"?s ?p ?{vars_list[0]} ."
            else:
                return "?s ?p ?o ."
                    
        except Exception as e:
            logger.error(f"Error converting algebra node to SPARQL: {e}")
            # Fallback to basic pattern
            variables = self._extract_variables_from_algebra_node(node)
            if variables:
                vars_list = sorted(variables)
                if len(vars_list) >= 2:
                    return f"?s ?{vars_list[0]} ?{vars_list[1]} ."
                else:
                    return f"?s ?p ?{vars_list[0]} ."
            else:
                return "?s ?p ?o ."
    
    def _extract_subject_from_delete_query(self, sparql_update: str) -> str:
        """Extract the subject URI from a DELETE query using RDFLib parsing.
        
        Note: For DELETE patterns with multiple subjects, this returns the first one.
        Use _extract_all_subjects_from_delete_query() for multi-subject patterns.
        """
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            from rdflib import URIRef
            
            # Parse the DELETE query using RDFLib
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            # Handle Update algebra structure
            update_ops = []
            if hasattr(algebra, 'request'):
                if hasattr(algebra.request, '__iter__'):
                    update_ops = list(algebra.request)
                else:
                    update_ops = [algebra.request]
            else:
                update_ops = [algebra]
            
            # Find the Modify operation and extract subject from DELETE clause
            for update_op in update_ops:
                if hasattr(update_op, 'algebra'):
                    algebra_ops = update_op.algebra if isinstance(update_op.algebra, list) else [update_op.algebra]
                    
                    for actual_op in algebra_ops:
                        if hasattr(actual_op, 'name') and actual_op.name == 'Modify':
                            # Extract subject from DELETE clause
                            if hasattr(actual_op, 'delete') and hasattr(actual_op.delete, 'quads'):
                                for graph_uri, triples in actual_op.delete.quads.items():
                                    for triple in triples:
                                        s, p, o = triple
                                        if isinstance(s, URIRef):
                                            return str(s)
            
            return ""
            
        except Exception as e:
            logger.error(f"Error extracting subject from DELETE query: {e}")
            return ""
    
    def _extract_all_subjects_from_delete_query(self, sparql_update: str) -> list:
        """Extract ALL subject URIs from a DELETE query using RDFLib parsing."""
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            from rdflib import URIRef
            
            # Parse the DELETE query using RDFLib
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            # Handle Update algebra structure
            update_ops = []
            if hasattr(algebra, 'request'):
                if hasattr(algebra.request, '__iter__'):
                    update_ops = list(algebra.request)
                else:
                    update_ops = [algebra.request]
            else:
                update_ops = [algebra]
            
            subjects = []
            
            # Find the Modify operation and extract ALL subjects from DELETE clause
            for update_op in update_ops:
                if hasattr(update_op, 'algebra'):
                    algebra_ops = update_op.algebra if isinstance(update_op.algebra, list) else [update_op.algebra]
                    
                    for actual_op in algebra_ops:
                        if hasattr(actual_op, 'name') and actual_op.name == 'Modify':
                            # Extract all subjects from DELETE clause
                            if hasattr(actual_op, 'delete') and hasattr(actual_op.delete, 'quads'):
                                for graph_uri, triples in actual_op.delete.quads.items():
                                    for triple in triples:
                                        s, p, o = triple
                                        if isinstance(s, URIRef):
                                            subject_str = str(s)
                                            if subject_str not in subjects:
                                                subjects.append(subject_str)
            
            return subjects
            
        except Exception as e:
            logger.error(f"Error extracting subjects from DELETE query: {e}")
            return []
    
    def _extract_graph_from_delete_query(self, sparql_update: str) -> str:
        """Extract the graph URI from a DELETE query using RDFLib parsing.
        
        Returns:
            Graph URI as string, or None if not found
        """
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            from rdflib import URIRef
            
            # Parse the DELETE query using RDFLib
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            # Handle Update algebra structure
            update_ops = []
            if hasattr(algebra, 'request'):
                if hasattr(algebra.request, '__iter__'):
                    update_ops = list(algebra.request)
                else:
                    update_ops = [algebra.request]
            else:
                update_ops = [algebra]
            
            # Find the Modify operation and extract graph from DELETE clause
            for update_op in update_ops:
                if hasattr(update_op, 'algebra'):
                    algebra_ops = update_op.algebra if isinstance(update_op.algebra, list) else [update_op.algebra]
                    
                    for actual_op in algebra_ops:
                        if hasattr(actual_op, 'name') and actual_op.name == 'Modify':
                            # Extract graph from DELETE clause
                            if hasattr(actual_op, 'delete') and hasattr(actual_op.delete, 'quads'):
                                for graph_uri, triples in actual_op.delete.quads.items():
                                    if isinstance(graph_uri, URIRef):
                                        return str(graph_uri)
            
            # No graph URI found
            logger.warning(f"No graph URI found in DELETE query: {sparql_update[:200]}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting graph from DELETE query: {e}")
            return None
    
    async def _resolve_insert_patterns_from_fuseki(self, space_id: str, sparql_update: str) -> List[tuple]:
        """
        Resolve INSERT patterns by extracting INSERT triples from UPDATE operations.
        
        For UPDATE operations (DELETE/INSERT with WHERE), we need to extract the INSERT part
        and resolve any variables using the WHERE clause.
        """
        try:
            logger.debug("🔍 Resolving INSERT patterns from UPDATE operation...")
            
            # Extract INSERT triples from the SPARQL UPDATE query
            insert_triples = self._extract_insert_triples_from_update(sparql_update)
            
            if not insert_triples:
                logger.warning("No INSERT triples found in UPDATE operation")
                return []
            
            logger.debug(f"✅ Extracted {len(insert_triples)} INSERT triples from UPDATE operation")
            return insert_triples
            
        except Exception as e:
            logger.error(f"❌ Error resolving INSERT patterns from UPDATE: {e}")
            return []
    
    def _extract_insert_triples_from_update(self, sparql_update: str) -> List[tuple]:
        """Extract INSERT triples from UPDATE operations using RDFLib parsing."""
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            from rdflib import URIRef, Literal, Variable
            
            # Parse the UPDATE query using RDFLib
            parsed_update = parseUpdate(sparql_update)
            algebra = translateUpdate(parsed_update)
            
            # Handle Update algebra structure
            update_ops = []
            if hasattr(algebra, 'request'):
                if hasattr(algebra.request, '__iter__'):
                    update_ops = list(algebra.request)
                else:
                    update_ops = [algebra.request]
            else:
                update_ops = [algebra]
            
            # Find the Modify operation and extract INSERT triples
            for update_op in update_ops:
                if hasattr(update_op, 'algebra'):
                    algebra_ops = update_op.algebra if isinstance(update_op.algebra, list) else [update_op.algebra]
                    
                    for actual_op in algebra_ops:
                        if hasattr(actual_op, 'name') and actual_op.name == 'Modify':
                            # Extract triples from INSERT clause
                            if hasattr(actual_op, 'insert') and hasattr(actual_op.insert, 'quads'):
                                triples = []
                                for graph_uri, quad_triples in actual_op.insert.quads.items():
                                    for triple in quad_triples:
                                        s, p, o = triple
                                        # Keep RDFLib objects to preserve type information (Literal vs URIRef)
                                        # The Fuseki manager will handle proper formatting based on object types
                                        triple_tuple = (s, p, o, graph_uri if isinstance(graph_uri, URIRef) else 'default')
                                        triples.append(triple_tuple)
                                        logger.debug(f"🔍 INSERT triple: {triple_tuple}")
                                return triples
            
            return []
            
        except Exception as e:
            logger.error(f"Error extracting INSERT triples from UPDATE: {e}")
            return []
    
    def _extract_variables_from_algebra(self, algebra_node) -> set:
        """Extract variables from algebra node."""
        variables = set()
        
        def traverse(node):
            if hasattr(node, 'name') and isinstance(node.name, Variable):
                variables.add(str(node.name).replace('?', ''))
            elif hasattr(node, '__iter__'):
                for child in node:
                    traverse(child)
            elif hasattr(node, '__dict__'):
                for attr_value in node.__dict__.values():
                    if attr_value is not None:
                        traverse(attr_value)
        
        traverse(algebra_node)
        return variables
    
    def _extract_graph_context(self, algebra_node) -> str:
        """Extract graph context from algebra node."""
        # This would traverse the algebra to find GRAPH contexts
        # For now, return None - full implementation would be more complex
        return None
    
    def _algebra_to_sparql_pattern(self, algebra_node) -> str:
        """Convert algebra node back to SPARQL pattern."""
        try:
            from rdflib import Variable, URIRef, Literal, BNode
            
            logger.debug(f"🔍 _algebra_to_sparql_pattern: Starting with node type: {type(algebra_node)}")
            logger.debug(f"🔍 Node attributes: {[attr for attr in dir(algebra_node) if not attr.startswith('_')]}")
            if hasattr(algebra_node, 'name'):
                logger.debug(f"🔍 Node name: {algebra_node.name}")
            # For CompValue (dictionary-like), log the actual keys and values
            if hasattr(algebra_node, 'keys'):
                logger.debug(f"🔍 CompValue keys: {list(algebra_node.keys())}")
                for key in algebra_node.keys():
                    value = algebra_node.get(key)
                    logger.debug(f"🔍   {key}: {type(value).__name__} = {value if not hasattr(value, 'name') else f'CompValue(name={value.name})'}")
            
            def format_term(term):
                if isinstance(term, Variable):
                    return f"?{term}"
                elif isinstance(term, URIRef):
                    return f"<{term}>"
                elif isinstance(term, Literal):
                    return f'"{term}"'
                elif isinstance(term, BNode):
                    return f"_:{term}"
                else:
                    return str(term)
            
            def traverse_algebra(node, depth=0):
                indent = "  " * depth
                patterns = []
                
                logger.debug(f"{indent}🔍 Traversing node type: {type(node).__name__}")
                if hasattr(node, 'name'):
                    logger.debug(f"{indent}🔍 Node name: {node.name}")
                
                if hasattr(node, 'name'):
                    if node.name == 'BGP':  # Basic Graph Pattern
                        logger.info(f"{indent}✅ Found BGP node")
                        if hasattr(node, 'triples'):
                            logger.info(f"{indent}✅ BGP has {len(node.triples)} triples")
                            for triple in node.triples:
                                s, p, o = triple
                                pattern = f"{format_term(s)} {format_term(p)} {format_term(o)}"
                                logger.info(f"{indent}  Triple: {pattern}")
                                patterns.append(pattern)
                    elif node.name == 'Graph':
                        logger.info(f"{indent}✅ Found Graph node")
                        if hasattr(node, 'term') and hasattr(node, 'p'):
                            graph_term = format_term(node.term)
                            logger.info(f"{indent}  Graph URI: {graph_term}")
                            inner_patterns = traverse_algebra(node.p, depth + 1)
                            logger.info(f"{indent}  Inner patterns: {inner_patterns}")
                            for pattern in inner_patterns:
                                patterns.append(f"GRAPH {graph_term} {{ {pattern} }}")
                    elif node.name == 'Join':
                        logger.info(f"{indent}✅ Found Join node")
                        # Join nodes have p1 and p2 children
                        if hasattr(node, 'get'):
                            p1 = node.get('p1')
                            p2 = node.get('p2')
                            if p1:
                                logger.info(f"{indent}  Processing p1")
                                patterns.extend(traverse_algebra(p1, depth + 1))
                            if p2:
                                logger.info(f"{indent}  Processing p2")
                                patterns.extend(traverse_algebra(p2, depth + 1))
                
                # Handle other algebra structures
                if hasattr(node, '__iter__') and not isinstance(node, (str, Variable, URIRef, Literal)):
                    try:
                        for child in node:
                            patterns.extend(traverse_algebra(child, depth + 1))
                    except TypeError:
                        pass
                
                if hasattr(node, '__dict__'):
                    for attr_name, attr_value in node.__dict__.items():
                        if attr_value is not None and attr_name not in ['name']:
                            patterns.extend(traverse_algebra(attr_value, depth + 1))
                
                return patterns
            
            patterns = traverse_algebra(algebra_node)
            if not patterns:
                logger.error("❌ Failed to extract any patterns from algebra node")
                raise ValueError("Could not extract SPARQL pattern from algebra structure")
            
            result = ' . '.join(patterns)
            logger.info(f"🔍 Final pattern result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error converting algebra to SPARQL pattern: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def _identify_operation_type(self, query: str) -> str:
        """Identify the type of SPARQL UPDATE operation using proper RDFLib parsing."""
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            
            # Log the original query
            logger.debug(f"🔍 SPARQL Parser: Original query length: {len(query)}")
            logger.debug(f"🔍 SPARQL Parser: Original query first 200 chars: {repr(query[:200])}")
            
            # Strip leading/trailing whitespace - RDFLib parser is sensitive to this
            query = query.strip()
            
            # Log the stripped query
            logger.debug(f"🔍 SPARQL Parser: Stripped query length: {len(query)}")
            logger.debug(f"🔍 SPARQL Parser: Stripped query first 200 chars: {repr(query[:200])}")
            
            # Parse the UPDATE query using RDFLib
            parsed_update = parseUpdate(query)
            algebra = translateUpdate(parsed_update)
            
            logger.debug(f"🔍 SPARQL Parser: Parsed algebra type: {type(algebra)}")
            logger.debug(f"🔍 SPARQL Parser: Algebra attributes: {[attr for attr in dir(algebra) if not attr.startswith('_')]}")
            
            # RDFLib returns an Update object with algebra attribute containing the actual operations
            if hasattr(algebra, 'algebra'):
                # The algebra attribute contains the actual update operations
                operations = algebra.algebra if hasattr(algebra.algebra, '__iter__') else [algebra.algebra]
                logger.debug(f"🔍 SPARQL Parser: Found {len(operations) if hasattr(operations, '__len__') else 'unknown'} operations in algebra")
            elif hasattr(algebra, 'request'):
                # Fallback to request attribute if available
                operations = algebra.request if hasattr(algebra.request, '__iter__') else [algebra.request]
                logger.debug(f"🔍 SPARQL Parser: Found {len(operations) if hasattr(operations, '__len__') else 'unknown'} operations in request")
            else:
                operations = [algebra]
                logger.debug(f"🔍 SPARQL Parser: Using algebra directly as single operation")
            
            # Process each update operation
            for op in operations:
                logger.debug(f"🔍 SPARQL Parser: Processing operation: {type(op)}")
                logger.debug(f"🔍 SPARQL Parser: Operation attributes: {[attr for attr in dir(op) if not attr.startswith('_')]}")
                
                # Check the operation type directly
                op_type = type(op).__name__
                logger.debug(f"🔍 SPARQL Parser: Operation class name: {op_type}")
                
                # Map RDFLib operation types to our internal types
                if op_type == 'InsertData':
                    return 'insert_data'
                elif op_type == 'DeleteData':
                    return 'delete_data'
                elif op_type == 'Update':
                    # For Update objects, check the internal structure
                    logger.debug(f"🔍 SPARQL Parser: Update object attributes: {[attr for attr in dir(op) if not attr.startswith('_')]}")
                    
                    # Check if it has specific operation attributes
                    if hasattr(op, 'triples') and op.triples:
                        # This is likely an INSERT DATA or DELETE DATA operation
                        # Check the query string to determine which one
                        if 'INSERT DATA' in query.upper():
                            return 'insert_data'
                        elif 'DELETE DATA' in query.upper():
                            return 'delete_data'
                    
                    # Check for other Update patterns
                    if hasattr(op, 'delete') and hasattr(op, 'insert'):
                        return 'insert_delete_pattern'
                    elif hasattr(op, 'delete'):
                        return 'delete'
                    elif hasattr(op, 'insert'):
                        return 'insert'
                        
                elif op_type == 'CompValue':
                    # RDFLib uses CompValue objects for SPARQL operations
                    logger.debug(f"🔍 SPARQL Parser: CompValue object attributes: {[attr for attr in dir(op) if not attr.startswith('_')]}")
                    
                    # Check the 'name' attribute to determine operation type
                    if hasattr(op, 'name'):
                        op_name = str(op.name)
                        logger.debug(f"🔍 SPARQL Parser: CompValue name: {op_name}")
                        
                        if op_name == 'InsertData':
                            return 'insert_data'
                        elif op_name == 'DeleteData':
                            return 'delete_data'
                        elif op_name == 'DeleteWhere':
                            return 'delete_where'
                        elif op_name == 'Modify':
                            # Properly analyze Modify operations by walking the parse tree
                            delete_clause = getattr(op, 'delete', None)
                            insert_clause = getattr(op, 'insert', None)
                            
                            # Walk the parse tree to determine if clauses are actually present and non-empty
                            has_actual_delete = self._has_non_empty_clause(delete_clause)
                            has_actual_insert = self._has_non_empty_clause(insert_clause)
                            
                            logger.debug(f"🔍 SPARQL Parser: Modify analysis - delete_present: {has_actual_delete}, insert_present: {has_actual_insert}")
                            
                            if has_actual_delete and has_actual_insert:
                                return 'insert_delete_pattern'
                            elif has_actual_delete and not has_actual_insert:
                                return 'delete'
                            elif not has_actual_delete and has_actual_insert:
                                return 'insert'
                            else:
                                # Fallback - shouldn't happen with proper parsing
                                return 'insert_delete_pattern'
                        elif op_name == 'Delete':
                            return 'delete'
                        elif op_name == 'Insert':
                            return 'insert'
                        elif op_name == 'Drop':
                            return 'drop_graph'
                        elif op_name == 'Clear':
                            return 'clear_graph'
                        elif op_name == 'Create':
                            return 'create_graph'
                    
                elif op_type == 'Clear':
                    return 'clear_graph'
                elif op_type == 'Drop':
                    return 'drop_graph'
                elif op_type == 'Create':
                    return 'create_graph'
            
            logger.debug(f"🔍 SPARQL Parser: Unknown operation type detected - unable to classify SPARQL operation")
            return 'unknown'
            
        except Exception as e:
            logger.error(f"Error identifying operation type with RDFLib: {e}")
            logger.error(f"Problematic query: {repr(query)}")
            return 'unknown'
    
    def _has_non_empty_clause(self, clause) -> bool:
        """
        Walk the parse tree to determine if a DELETE/INSERT clause is actually present and non-empty.
        
        Args:
            clause: The DELETE or INSERT clause from RDFLib parsing
            
        Returns:
            bool: True if clause contains actual triples/patterns, False otherwise
        """
        if clause is None:
            return False
            
        # Handle different RDFLib clause representations
        if hasattr(clause, '__len__'):
            # If it's a list/set/collection, check if it has content
            if len(clause) == 0:
                return False
            # If it has items, check if any are meaningful (not just empty containers)
            for item in clause:
                if self._is_meaningful_pattern(item):
                    return True
            return False
        elif hasattr(clause, '__iter__') and not isinstance(clause, (str, bytes)):
            # Handle iterables that don't have __len__
            try:
                for item in clause:
                    if self._is_meaningful_pattern(item):
                        return True
                return False
            except (TypeError, AttributeError):
                pass
        
        # If it's a single item, check if it's meaningful
        return self._is_meaningful_pattern(clause)
    
    def _is_meaningful_pattern(self, pattern) -> bool:
        """
        Check if a pattern represents actual content (triples, graph patterns, etc.)
        
        Args:
            pattern: A pattern from the RDFLib parse tree
            
        Returns:
            bool: True if pattern represents actual content, False if empty/None
        """
        if pattern is None:
            return False
            
        # Handle RDFLib CompValue objects
        if hasattr(pattern, 'name'):
            # CompValue objects with names like 'BGP' (Basic Graph Pattern) contain actual patterns
            return True
            
        # Handle tuples (triples)
        if isinstance(pattern, tuple) and len(pattern) >= 3:
            return True
            
        # Handle lists/collections with content
        if hasattr(pattern, '__len__') and len(pattern) > 0:
            return True
            
        # Handle other RDFLib objects that indicate content
        if hasattr(pattern, '__iter__') and not isinstance(pattern, (str, bytes)):
            try:
                # If we can iterate and find at least one item, it's meaningful
                for _ in pattern:
                    return True
                return False
            except (TypeError, AttributeError):
                pass
                
        # If we can't determine, assume it's meaningful if not None
        return pattern is not None
    
    def _extract_patterns_from_query(self, query: str) -> Dict[str, Any]:
        """Extract patterns from SPARQL UPDATE query using RDFLib parsing."""
        result = {
            'delete_patterns': [],
            'insert_patterns': [],
            'where_clause': None
        }
        
        try:
            from rdflib.plugins.sparql.parser import parseUpdate
            from rdflib.plugins.sparql.algebra import translateUpdate
            
            # Parse the UPDATE query using RDFLib
            parsed_update = parseUpdate(query)
            algebra = translateUpdate(parsed_update)
            
            logger.debug(f"Extracting patterns from algebra type: {type(algebra)}")
            
            # RDFLib returns an UpdateRequest object containing update operations
            if hasattr(algebra, 'request'):
                operations = algebra.request if hasattr(algebra.request, '__iter__') else [algebra.request]
            else:
                operations = [algebra]
            
            # Process each update operation
            for op in operations:
                logger.debug(f"Processing operation for pattern extraction: {type(op)}")
                
                # Extract patterns based on operation type
                if hasattr(op, 'delete') and op.delete is not None:
                    # Extract DELETE patterns from the delete clause
                    delete_patterns = self._extract_triples_from_clause(op.delete)
                    result['delete_patterns'].extend(delete_patterns)
                    logger.debug(f"Extracted {len(delete_patterns)} DELETE patterns")
                
                if hasattr(op, 'insert') and op.insert is not None:
                    # Extract INSERT patterns from the insert clause
                    insert_patterns = self._extract_triples_from_clause(op.insert)
                    result['insert_patterns'].extend(insert_patterns)
                    logger.debug(f"Extracted {len(insert_patterns)} INSERT patterns")
                
                if hasattr(op, 'where') and op.where is not None:
                    # Extract WHERE clause pattern
                    where_pattern = self._extract_where_pattern(op.where)
                    result['where_clause'] = where_pattern
                    logger.debug(f"Extracted WHERE pattern: {where_pattern}")
            
            logger.debug(f"Extracted patterns: DELETE={len(result['delete_patterns'])}, INSERT={len(result['insert_patterns'])}")
            
        except Exception as e:
            logger.error(f"Error parsing SPARQL UPDATE query with RDFLib: {e}")
            logger.error(f"Problematic query: {repr(query)}")
            # Return basic patterns as fallback
            result['delete_patterns'] = ['?s ?p ?o']
        
        return result
    
    def _extract_triples_from_clause(self, clause) -> List[str]:
        """Extract triple patterns from a DELETE/INSERT clause."""
        patterns = []
        try:
            from rdflib import Variable, URIRef, Literal, BNode
            
            logger.debug(f"Extracting triples from clause type: {type(clause)}")
            
            # Handle different clause structures
            if hasattr(clause, 'triples'):
                # Direct triples access
                for triple in clause.triples:
                    pattern = self._triple_to_pattern_string(triple)
                    patterns.append(pattern)
            elif hasattr(clause, 'quads'):
                # Quad-based structure (graph-aware)
                for graph_uri, triples in clause.quads.items():
                    for triple in triples:
                        pattern = self._triple_to_pattern_string(triple)
                        patterns.append(pattern)
            elif hasattr(clause, '__iter__'):
                # Iterable of triples
                for triple in clause:
                    pattern = self._triple_to_pattern_string(triple)
                    patterns.append(pattern)
            else:
                # Fallback pattern
                patterns.append('?s ?p ?o')
                
        except Exception as e:
            logger.error(f"Error extracting triples from clause: {e}")
            patterns.append('?s ?p ?o')
            
        return patterns
    
    def _extract_where_pattern(self, where_clause) -> str:
        """Extract pattern from WHERE clause."""
        try:
            logger.debug(f"Extracting WHERE pattern from type: {type(where_clause)}")
            
            # Convert WHERE clause algebra to SPARQL pattern
            return self._algebra_to_sparql_pattern(where_clause)
            
        except Exception as e:
            logger.error(f"Error extracting WHERE pattern: {e}")
            return '?s ?p ?o'
    
    def _triple_to_pattern_string(self, triple) -> str:
        """Convert an RDFLib triple to a SPARQL pattern string."""
        try:
            from rdflib import Variable, URIRef, Literal, BNode
            
            s, p, o = triple
            
            # Convert each component to SPARQL syntax
            def term_to_sparql(term):
                if isinstance(term, Variable):
                    return f'?{term}'
                elif isinstance(term, URIRef):
                    return f'<{term}>'
                elif isinstance(term, Literal):
                    return f'"{term}"'
                elif isinstance(term, BNode):
                    return f'_:{term}'
                else:
                    return str(term)
            
            s_str = term_to_sparql(s)
            p_str = term_to_sparql(p)
            o_str = term_to_sparql(o)
            
            return f'{s_str} {p_str} {o_str}'
            
        except Exception as e:
            logger.error(f"Error converting triple to pattern: {e}")
            return '?s ?p ?o'

    def _extract_algebra_patterns(self, algebra_node) -> List[Dict[str, str]]:
        """Extract patterns from algebra node."""
        patterns = []
        
        try:
            if hasattr(algebra_node, 'triples'):
                for triple in algebra_node.triples:
                    s, p, o = triple
                    pattern = {
                        'subject': str(s),
                        'predicate': str(p),
                        'object': str(o)
                    }
                    patterns.append(pattern)
        except Exception as e:
            logger.error(f"Error extracting algebra patterns: {e}")
        
        return patterns
    
    def _extract_insert_data_triples(self, query: str) -> List[tuple]:
        """Extract concrete triples from INSERT DATA operation using RDFLib (following PostgreSQL backend pattern)."""
        try:
            from rdflib import Graph, ConjunctiveGraph, URIRef
            from rdflib.plugins.sparql.processor import SPARQLUpdateProcessor
            
            logger.debug(f"Parsing INSERT DATA query: {query}")
            
            # Create a temporary graph to capture the INSERT DATA triples
            temp_graph = ConjunctiveGraph()
            
            # Use RDFLib's SPARQL UPDATE processor to parse and extract the data
            processor = SPARQLUpdateProcessor(temp_graph)
            
            # Execute the update on the temporary graph to extract triples
            processor.update(query)
            
            logger.debug(f"🔍 SPARQL Parser: Temp graph has {len(temp_graph)} triples after RDFLib update")
            logger.debug(f"🔍 SPARQL Parser: Query length: {len(query)} characters")
            
            # Extract all quads from the temporary graph
            triples = []
            
            for context in temp_graph.contexts():
                graph_uri = context.identifier if context.identifier != temp_graph.default_context.identifier else None
                
                for subject, predicate, obj in context:
                    # Convert to tuple format: (subject, predicate, object, graph)
                    graph_str = str(graph_uri) if graph_uri else 'default'
                    triple_tuple = (str(subject), str(predicate), str(obj), graph_str)
                    
                    triples.append(triple_tuple)
                    logger.debug(f"  Triple: {subject} {predicate} {obj} (graph: {graph_uri})")
            
            logger.debug(f"Successfully parsed {len(triples)} triples from INSERT DATA")
            return triples
            
        except Exception as e:
            logger.error(f"Error parsing INSERT DATA triples with RDFLib: {e}")
            return []
    
    
    def _extract_delete_data_triples(self, query: str) -> List[tuple]:
        """Extract concrete triples from DELETE DATA operation using RDFLib (following PostgreSQL backend pattern)."""
        try:
            import time
            from rdflib import Graph, ConjunctiveGraph, URIRef
            from rdflib.plugins.sparql.processor import SPARQLUpdateProcessor
            
            logger.info(f"🔥 RDFLIB: Starting DELETE DATA parsing (query length: {len(query)} chars)")
            
            # Create a temporary graph to capture the DELETE DATA triples
            graph_start = time.time()
            temp_graph = ConjunctiveGraph()
            graph_time = time.time() - graph_start
            logger.info(f"🔥 RDFLIB: Created ConjunctiveGraph in {graph_time:.3f}s")
            
            # For DELETE DATA, we need to first populate the graph with the data to be deleted
            # Convert DELETE DATA to INSERT DATA for parsing purposes
            convert_start = time.time()
            insert_query = query.replace('DELETE DATA', 'INSERT DATA', 1)
            convert_time = time.time() - convert_start
            logger.info(f"🔥 RDFLIB: Converted DELETE to INSERT in {convert_time:.3f}s")
            
            # Use RDFLib's SPARQL UPDATE processor to parse and extract the data
            processor_start = time.time()
            processor = SPARQLUpdateProcessor(temp_graph)
            processor_time = time.time() - processor_start
            logger.info(f"🔥 RDFLIB: Created SPARQLUpdateProcessor in {processor_time:.3f}s")
            
            # Execute the insert version on the temporary graph to extract triples
            update_start = time.time()
            logger.info(f"🔥 RDFLIB: Calling processor.update() - THIS IS THE BOTTLENECK...")
            processor.update(insert_query)
            update_time = time.time() - update_start
            logger.info(f"🔥 RDFLIB: processor.update() completed in {update_time:.3f}s")
            
            logger.info(f"🔥 RDFLIB: Temp graph has {len(temp_graph)} triples after parsing")
            
            # Extract all quads from the temporary graph
            triples = []
            
            for context in temp_graph.contexts():
                graph_uri = context.identifier if context.identifier != temp_graph.default_context.identifier else None
                
                for subject, predicate, obj in context:
                    # Convert to tuple format: (subject, predicate, object, graph)
                    graph_str = str(graph_uri) if graph_uri else 'default'
                    triple_tuple = (str(subject), str(predicate), str(obj), graph_str)
                    
                    triples.append(triple_tuple)
                    logger.debug(f"  Delete Triple: {subject} {predicate} {obj} (graph: {graph_uri})")
            
            logger.debug(f"Successfully parsed {len(triples)} triples from DELETE DATA")
            return triples
            
        except Exception as e:
            logger.error(f"Error parsing DELETE DATA triples with RDFLib: {e}")
            return []
    
    
    def _build_resolution_query(self, delete_patterns: List[str], where_clause: Optional[str]) -> str:
        """
        Build SELECT query to resolve DELETE patterns.
        
        Example:
        DELETE { ?s ?p ?o } WHERE { ?s a :Person }
        becomes:
        SELECT ?s ?p ?o WHERE { ?s a :Person . ?s ?p ?o }
        """
        
        # Extract variables from DELETE patterns using RDFLib parsing
        variables = set()
        try:
            from rdflib.plugins.sparql import prepareQuery
            
            # For each pattern, try to parse it as a SPARQL fragment to extract variables
            for pattern in delete_patterns:
                try:
                    # Create a simple SELECT query to parse the pattern
                    test_query = f"SELECT * WHERE {{ {pattern} }}"
                    parsed = prepareQuery(test_query)
                    
                    # Extract variables from the parsed query
                    # This is a simplified approach - full implementation would
                    # traverse the parsed algebra to extract variables
                    logger.debug(f"Parsed pattern: {pattern}")
                    
                except Exception as parse_error:
                    logger.debug(f"Could not parse pattern '{pattern}': {parse_error}")
                    
        except Exception as e:
            logger.error(f"Error extracting variables with RDFLib: {e}")
        
        # Format variables for SELECT
        if variables:
            select_vars = ' '.join([f'?{var}' for var in sorted(variables)])
        else:
            select_vars = '*'
        
        # Combine WHERE clause with DELETE patterns
        if where_clause and delete_patterns:
            combined_where = f"{where_clause} . {' . '.join(delete_patterns)}"
        elif where_clause:
            combined_where = where_clause
        elif delete_patterns:
            combined_where = ' . '.join(delete_patterns)
        else:
            combined_where = "?s ?p ?o"
        
        return f"SELECT {select_vars} WHERE {{ {combined_where} }}"
    
    def _sparql_results_to_triples(self, results: List[Dict]) -> List[tuple]:
        """Convert SPARQL SELECT results to triple format."""
        triples = []
        
        for result in results:
            # Handle tuple format: (subject, predicate, object, graph)
            if len(result) >= 3:
                subject = str(result[0])
                predicate = str(result[1])
                obj = str(result[2])
            else:
                continue
            
            if subject and predicate and obj:
                # Convert to tuple format: (subject, predicate, object, graph)
                # For resolved DELETE patterns, use 'default' graph unless specified
                triple_tuple = (subject, predicate, obj, 'default')
                triples.append(triple_tuple)
        
        return triples
    
    def _format_sparql_term(self, term_dict: Dict[str, str]) -> str:
        """
        Format a SPARQL result term with proper RDF encoding.
        
        Args:
            term_dict: SPARQL result term dict with 'type', 'value', and optionally 'datatype' or 'xml:lang'
            
        Returns:
            Properly formatted term string matching how it's stored in PostgreSQL
        """
        if not isinstance(term_dict, dict):
            return str(term_dict)
        
        term_type = term_dict.get('type')
        value = term_dict.get('value', '')
        
        if term_type == 'uri':
            # URIs are stored without angle brackets in PostgreSQL
            return value
        elif term_type == 'literal':
            # Literals need to be formatted with quotes and datatype
            datatype = term_dict.get('datatype')
            lang = term_dict.get('xml:lang')
            
            if lang:
                # Language-tagged literal: "value"@lang
                return f'"{value}"@{lang}'
            elif datatype:
                # Typed literal: "value"^^<datatype>
                return f'"{value}"^^<{datatype}>'
            else:
                # Plain literal: "value"
                return f'"{value}"'
        elif term_type == 'bnode':
            # Blank node
            return f'_:{value}'
        else:
            # Unknown type, return as-is
            return value
