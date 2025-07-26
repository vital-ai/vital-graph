

"""
PostgreSQL SPARQL Implementation New - Orchestrator Class for VitalGraph

This is the new modular orchestrator class that coordinates all SPARQL operations
using the refactored supporting classes. It maintains the same public API as the
original PostgreSQLSparqlImpl but delegates functionality to specialized modules.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from rdflib import Variable, URIRef, Literal, BNode
from rdflib.plugins.sparql import prepareQuery

# Import PostgreSQL space implementation and utilities
from .postgresql_space_impl import PostgreSQLSpaceImpl
from .postgresql_utils import PostgreSQLUtils
from .postgresql_term_cache import PostgreSQLTermCache

# Import all the refactored supporting classes
from .postgresql_sparql_utils import TableConfig, AliasGenerator, GraphConstants, SparqlUtils
from .postgresql_sparql_translator import PostgreSQLSparqlTranslator
from .postgresql_sparql_patterns import PostgreSQLSparqlPatterns
from .postgresql_sparql_filters import PostgreSQLSparqlFilters
from .postgresql_sparql_aggregates import PostgreSQLSparqlAggregates
from .postgresql_sparql_property_paths import PostgreSQLSparqlPropertyPaths
from .postgresql_sparql_updates import PostgreSQLSparqlUpdates


class PostgreSQLSparqlImplNew:
    """
    New modular PostgreSQL SPARQL implementation orchestrator.
    
    This class coordinates all SPARQL operations by delegating to specialized
    supporting classes while maintaining the same public API as the original
    PostgreSQLSparqlImpl for seamless replacement.
    """
    
    def __init__(self, space_impl: PostgreSQLSpaceImpl):
        """
        Initialize the new SPARQL implementation orchestrator.
        
        Args:
            space_impl: PostgreSQLSpaceImpl instance for database operations
        """
        self.space_impl = space_impl
        self.logger = logging.getLogger(__name__)
        
        # Initialize term cache for efficient term UUID lookups
        self.term_cache = PostgreSQLTermCache()
        
        # Initialize all supporting classes
        self.translator = PostgreSQLSparqlTranslator(space_impl, self.logger)
        self.patterns = PostgreSQLSparqlPatterns(space_impl, self.logger)
        self.filters = PostgreSQLSparqlFilters(space_impl, self.logger)
        self.aggregates = PostgreSQLSparqlAggregates(space_impl, self.logger)
        self.property_paths = PostgreSQLSparqlPropertyPaths(space_impl, self.logger)
        self.updates = PostgreSQLSparqlUpdates(space_impl, self.logger)
        
        # Initialize counters for query processing
        self.variable_counter = 0
        self.join_counter = 0
        
        # Graph cache for efficient graph URI lookups
        self.graph_cache = {}
        
        self.logger.info("PostgreSQL SPARQL Implementation New initialized successfully")
    
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the specified space.
        
        This is the main public API method that maintains compatibility with
        the original implementation while using the new modular architecture.
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL query string
            
        Returns:
            List of result dictionaries with variable bindings (SELECT)
            or List of RDF triple dictionaries (CONSTRUCT/DESCRIBE)
        """
        try:
            # Validate space exists
            PostgreSQLUtils.validate_space_id(space_id)
            
            self.logger.info(f"Executing SPARQL query in space '{space_id}'")
            self.logger.debug(f"Query: {sparql_query}")
            
            # Initialize graph cache if needed
            await self.initialize_graph_cache_if_needed(space_id)
            
            # Validate and analyze the query
            if not self.translator.validate_sparql_query(sparql_query):
                raise ValueError("Invalid SPARQL query syntax")
            
            query_type = self.translator.extract_query_type(sparql_query)
            if not self.translator.is_supported_query_type(query_type):
                raise NotImplementedError(f"Query type {query_type} not supported")
            
            # Generate query statistics for monitoring
            stats = self.translator.generate_query_statistics(sparql_query)
            self.logger.debug(f"Query statistics: {stats}")
            
            # Translate SPARQL to SQL using the translator
            sql_query = await self.translator.translate_sparql_to_sql(space_id, sparql_query)
            
            # Execute the SQL query
            sql_results = await self.execute_sql_query(sql_query)
            
            # Process results based on query type
            if query_type == "ConstructQuery":
                # Convert SQL results to RDF triples for CONSTRUCT queries
                construct_triples = await self.process_construct_results(sql_results, sparql_query)
                self.logger.info(f"CONSTRUCT query executed successfully, returned {len(construct_triples)} triples")
                return construct_triples
            elif query_type == "DescribeQuery":
                # Convert SQL results to RDF triples for DESCRIBE queries
                describe_triples = await self.process_describe_results(sql_results)
                self.logger.info(f"DESCRIBE query executed successfully, returned {len(describe_triples)} triples")
                return describe_triples
            else:
                # For SELECT and ASK queries, return SQL results as-is
                self.logger.info(f"{query_type} executed successfully, returned {len(sql_results)} results")
                return sql_results
                
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            raise
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute a SPARQL 1.1 UPDATE operation.
        
        Args:
            space_id: The space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            bool: True if update was successful
            
        Raises:
            Exception: If update operation fails
        """
        try:
            # Validate space exists
            PostgreSQLUtils.validate_space_id(space_id)
            
            self.logger.info(f"Executing SPARQL UPDATE in space '{space_id}'")
            self.logger.debug(f"Update: {sparql_update}")
            
            # Initialize graph cache if needed
            await self.initialize_graph_cache_if_needed(space_id)
            
            # Validate and analyze the update
            if not self.updates.validate_sparql_update(sparql_update):
                raise ValueError("Invalid SPARQL UPDATE syntax")
            
            update_type = self.updates.extract_update_type(sparql_update)
            if not self.updates.is_supported_update_type(update_type):
                raise NotImplementedError(f"Update type {update_type} not supported")
            
            # Generate update statistics for monitoring
            stats = self.updates.generate_update_statistics(sparql_update)
            self.logger.debug(f"Update statistics: {stats}")
            
            # Execute the appropriate update operation
            if update_type == 'INSERT_DATA':
                result = await self.updates.execute_insert_data(space_id, sparql_update)
            elif update_type == 'DELETE_DATA':
                result = await self.updates.execute_delete_data(space_id, sparql_update)
            elif update_type in ('INSERT_DELETE_PATTERN', 'MODIFY'):
                result = await self.updates.execute_insert_delete_pattern(space_id, sparql_update)
            else:
                raise NotImplementedError(f"Update operation {update_type} not yet implemented")
            
            self.logger.info(f"SPARQL UPDATE executed successfully: {update_type}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL UPDATE: {e}")
            raise
    
    async def initialize_graph_cache_if_needed(self, space_id: str) -> None:
        """
        Initialize the graph cache if it's empty (lazy loading).
        
        Args:
            space_id: The space identifier
        """
        if space_id not in self.graph_cache:
            try:
                # Load graph information from the database
                # This would need to be implemented based on the space implementation
                self.graph_cache[space_id] = {}
                self.logger.debug(f"Initialized graph cache for space '{space_id}'")
            except Exception as e:
                self.logger.warning(f"Failed to initialize graph cache for space '{space_id}': {e}")
                self.graph_cache[space_id] = {}
    
    async def execute_sql_query(self, sql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SQL query against the database.
        
        Args:
            sql_query: SQL query string
            
        Returns:
            List of result dictionaries
        """
        try:
            # Clean up the SQL query before execution
            cleaned_sql = self.translator.cleanup_sql_before_execution(sql_query)
            
            # Execute using the space implementation's SQL execution method
            # This would need to be adapted based on the actual space implementation API
            results = await self.space_impl.execute_sql_query(cleaned_sql)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error executing SQL query: {e}")
            self.logger.error(f"SQL: {sql_query}")
            raise
    
    async def process_construct_results(self, sql_results: List[Dict[str, Any]], 
                                      sparql_query: str) -> List[Dict[str, str]]:
        """
        Process SQL results for CONSTRUCT queries to return RDF triples.
        
        Args:
            sql_results: Raw SQL query results
            sparql_query: Original SPARQL CONSTRUCT query
            
        Returns:
            List of RDF triple dictionaries
        """
        try:
            # Extract CONSTRUCT template from the query
            prepared_query = prepareQuery(sparql_query)
            construct_template = getattr(prepared_query.algebra, 'template', [])
            
            # Convert SQL results to RDF triples based on the template
            triples = []
            for result in sql_results:
                # Apply the CONSTRUCT template to each result binding
                for subject_template, predicate_template, object_template in construct_template:
                    # Substitute variables with actual values from the result
                    subject = self.substitute_template_term(subject_template, result)
                    predicate = self.substitute_template_term(predicate_template, result)
                    obj = self.substitute_template_term(object_template, result)
                    
                    if subject and predicate and obj:
                        triples.append({
                            'subject': str(subject),
                            'predicate': str(predicate),
                            'object': str(obj)
                        })
            
            return triples
            
        except Exception as e:
            self.logger.error(f"Error processing CONSTRUCT results: {e}")
            return []
    
    async def process_describe_results(self, sql_results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Process SQL results for DESCRIBE queries to return RDF triples.
        
        Args:
            sql_results: Raw SQL query results
            
        Returns:
            List of RDF triple dictionaries
        """
        try:
            # DESCRIBE queries should return subject, predicate, object columns
            triples = []
            for result in sql_results:
                if 'subject' in result and 'predicate' in result and 'object' in result:
                    triples.append({
                        'subject': str(result['subject']),
                        'predicate': str(result['predicate']),
                        'object': str(result['object'])
                    })
            
            return triples
            
        except Exception as e:
            self.logger.error(f"Error processing DESCRIBE results: {e}")
            return []
    
    def substitute_template_term(self, template_term, result_binding: Dict[str, Any]):
        """
        Substitute a template term with actual values from result bindings.
        
        Args:
            template_term: Template term (Variable, URIRef, Literal, etc.)
            result_binding: Dictionary of variable bindings from SQL results
            
        Returns:
            Substituted term or None if substitution fails
        """
        try:
            if isinstance(template_term, Variable):
                # Look up variable value in result bindings
                var_name = template_term.toPython().lower()
                return result_binding.get(var_name)
            else:
                # Return literal terms as-is
                return template_term
                
        except Exception as e:
            self.logger.warning(f"Error substituting template term {template_term}: {e}")
            return None
    
    async def get_term_uuids_batch(self, terms: List[Tuple[str, str]], 
                                  table_config: TableConfig) -> Dict[Tuple[str, str], str]:
        """
        Get term UUIDs for multiple terms using cache and batch database lookup.
        
        Args:
            terms: List of (term_text, term_type) tuples
            table_config: Table configuration for database queries
            
        Returns:
            Dictionary mapping (term_text, term_type) to term_uuid
        """
        try:
            # Use the term cache for efficient lookups
            return await self.term_cache.get_term_uuids_batch(terms, table_config, self.space_impl)
            
        except Exception as e:
            self.logger.error(f"Error getting term UUIDs: {e}")
            return {}
    
    def get_query_complexity_estimate(self, sparql_query: str) -> int:
        """
        Get an estimate of query computational complexity.
        
        Args:
            sparql_query: SPARQL query string
            
        Returns:
            Complexity score (higher = more complex)
        """
        return self.translator.estimate_query_complexity(
            prepareQuery(sparql_query).algebra
        )
    
    def get_update_complexity_estimate(self, sparql_update: str) -> int:
        """
        Get an estimate of update operation computational complexity.
        
        Args:
            sparql_update: SPARQL UPDATE string
            
        Returns:
            Complexity score (higher = more complex)
        """
        return self.updates.estimate_update_complexity(sparql_update)
    
    # Graph Management Operations
    
    async def execute_create_graph(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute CREATE GRAPH operation.
        
        Args:
            space_id: The space identifier
            sparql_update: CREATE GRAPH SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing CREATE GRAPH operation")
        
        try:
            # Initialize graph cache if needed
            await self.initialize_graph_cache_if_needed(space_id)
            
            # Extract graph URI from the query
            graph_uri = self.extract_graph_uri(sparql_update, "CREATE")
            if not graph_uri:
                raise ValueError("No graph URI found in CREATE GRAPH query")
            
            self.logger.info(f"Creating graph: {graph_uri}")
            
            # Ensure graph is registered in cache and database
            await self.ensure_graph_registered(space_id, graph_uri)
            
            self.logger.info(f"Graph {graph_uri} created successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in CREATE GRAPH operation: {e}")
            raise
    
    async def execute_drop_graph(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute DROP GRAPH operation.
        
        Args:
            space_id: The space identifier
            sparql_update: DROP GRAPH SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing DROP GRAPH operation")
        
        try:
            # Extract graph URI from the query
            graph_uri = self.extract_graph_uri(sparql_update, "DROP")
            if not graph_uri:
                raise ValueError("No graph URI found in DROP GRAPH query")
            
            self.logger.info(f"Dropping graph: {graph_uri}")
            
            # Remove all quads from the specified graph
            await self.remove_all_quads_from_graph(space_id, graph_uri)
            
            # Remove graph from database and cache
            await self.remove_graph_from_db(space_id, graph_uri)
            if space_id in self.graph_cache and graph_uri in self.graph_cache[space_id]:
                del self.graph_cache[space_id][graph_uri]
            
            self.logger.info(f"Graph {graph_uri} dropped successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in DROP GRAPH operation: {e}")
            raise
    
    async def execute_clear_graph(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute CLEAR GRAPH operation.
        
        Args:
            space_id: The space identifier
            sparql_update: CLEAR GRAPH SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing CLEAR GRAPH operation")
        
        try:
            # Extract graph URI from the query
            graph_uri = self.extract_graph_uri(sparql_update, "CLEAR")
            if not graph_uri:
                raise ValueError("No graph URI found in CLEAR GRAPH query")
            
            self.logger.info(f"Clearing graph: {graph_uri}")
            
            # Remove all quads from the specified graph (same as DROP but graph still exists)
            await self.remove_all_quads_from_graph(space_id, graph_uri)
            
            self.logger.info(f"Graph {graph_uri} cleared successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in CLEAR GRAPH operation: {e}")
            raise
    
    async def execute_copy_graph(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute COPY GRAPH operation.
        
        Args:
            space_id: The space identifier
            sparql_update: COPY GRAPH SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing COPY GRAPH operation")
        
        try:
            # Extract source and target graph URIs
            source_graph, target_graph = self.extract_graph_pair(sparql_update, "COPY")
            
            self.logger.info(f"Copying from {source_graph} to {target_graph}")
            
            # First clear the target graph
            await self.remove_all_quads_from_graph(space_id, target_graph)
            
            # Then copy all quads from source to target
            await self.copy_all_quads_between_graphs(space_id, source_graph, target_graph)
            
            self.logger.info(f"Graph copied successfully from {source_graph} to {target_graph}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in COPY GRAPH operation: {e}")
            raise
    
    async def execute_move_graph(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute MOVE GRAPH operation.
        
        Args:
            space_id: The space identifier
            sparql_update: MOVE GRAPH SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing MOVE GRAPH operation")
        
        try:
            # Extract source and target graph URIs
            source_graph, target_graph = self.extract_graph_pair(sparql_update, "MOVE")
            
            self.logger.info(f"Moving from {source_graph} to {target_graph}")
            
            # First clear the target graph
            await self.remove_all_quads_from_graph(space_id, target_graph)
            
            # Copy all quads from source to target
            await self.copy_all_quads_between_graphs(space_id, source_graph, target_graph)
            
            # Then clear the source graph
            await self.remove_all_quads_from_graph(space_id, source_graph)
            
            self.logger.info(f"Graph moved successfully from {source_graph} to {target_graph}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in MOVE GRAPH operation: {e}")
            raise
    
    async def execute_add_graph(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute ADD GRAPH operation.
        
        Args:
            space_id: The space identifier
            sparql_update: ADD GRAPH SPARQL query
            
        Returns:
            bool: True if successful
        """
        self.logger.debug("Executing ADD GRAPH operation")
        
        try:
            # Extract source and target graph URIs
            source_graph, target_graph = self.extract_graph_pair(sparql_update, "ADD")
            
            self.logger.info(f"Adding from {source_graph} to {target_graph}")
            
            # Copy all quads from source to target (merge, don't clear target first)
            await self.copy_all_quads_between_graphs(space_id, source_graph, target_graph)
            
            self.logger.info(f"Graph added successfully from {source_graph} to {target_graph}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in ADD GRAPH operation: {e}")
            raise
    
    async def execute_load_operation(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute SPARQL LOAD operation using the transfer utilities module.
        
        Supports:
        - LOAD <source-uri>
        - LOAD <source-uri> INTO GRAPH <target-graph>
        
        Args:
            space_id: Space identifier
            sparql_update: SPARQL LOAD query
            
        Returns:
            bool: True if successful
        """
        try:
            # Import the transfer utilities
            from vitalgraph.transfer.transfer_utils import DataTransferManager, TransferConfig
            
            # Create transfer manager with configuration
            config = TransferConfig(
                max_file_size=100 * 1024 * 1024,  # 100MB
                timeout_seconds=30,
                allowed_schemes=['http', 'https'],
                # TODO: Add domain allowlist from configuration if needed
                # allowed_domains=['trusted-domain.com']
            )
            
            transfer_manager = DataTransferManager(config)
            
            # Execute the load operation
            load_result = await transfer_manager.execute_load_operation(sparql_update)
            
            if not load_result.success:
                raise ValueError(f"LOAD operation failed: {load_result.error_message}")
            
            # Get the parsed data
            source_uri = load_result.source_uri
            target_graph = load_result.target_graph
            
            # Re-parse to get quads (the transfer manager returns metadata, we need the actual quads)
            # Parse the LOAD query to get URIs
            parsed_source_uri, parsed_target_graph = transfer_manager.query_parser.parse_load_query(sparql_update)
            
            # Fetch and parse content again to get quads
            content, content_type, content_size = await transfer_manager.http_fetcher.fetch_content(parsed_source_uri)
            rdf_format = transfer_manager.format_detector.detect_format(content_type, parsed_source_uri)
            triples = transfer_manager.rdf_parser.parse_content(content, rdf_format, parsed_source_uri)
            quads = transfer_manager.rdf_parser.convert_triples_to_quads(triples, parsed_target_graph)
            
            # Register the target graph if it doesn't exist
            if target_graph:
                await self.ensure_graphs_registered_batch(space_id, {target_graph})
            
            # Insert quads using existing batch insertion logic
            if quads:
                await self.space_impl.add_rdf_quads_batch(space_id, quads)
                self.logger.info(f"Successfully loaded {len(quads)} quads from {source_uri} (format: {load_result.format_detected}, size: {load_result.content_size} bytes, elapsed: {load_result.elapsed_seconds:.3f}s)")
            else:
                self.logger.warning(f"No valid RDF data found in {source_uri}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in LOAD operation: {e}")
            raise
    
    # Helper methods for graph operations
    
    def extract_graph_uri(self, sparql_update: str, operation: str) -> str:
        """
        Extract graph URI from CREATE/DROP/CLEAR GRAPH operations.
        
        Args:
            sparql_update: SPARQL UPDATE query
            operation: Operation type (CREATE, DROP, CLEAR)
            
        Returns:
            str: Graph URI
        """
        import re
        
        # Pattern to match graph URI in angle brackets
        pattern = rf'{operation}\s+(?:SILENT\s+)?GRAPH\s+<([^>]+)>'
        match = re.search(pattern, sparql_update, re.IGNORECASE)
        
        if match:
            return match.group(1)
        
        # Fallback: try without GRAPH keyword
        pattern = rf'{operation}\s+(?:SILENT\s+)?<([^>]+)>'
        match = re.search(pattern, sparql_update, re.IGNORECASE)
        
        if match:
            return match.group(1)
        
        raise ValueError(f"Could not extract graph URI from {operation} operation: {sparql_update}")
    
    def extract_graph_pair(self, sparql_update: str, operation: str) -> Tuple[str, str]:
        """
        Extract source and target graph URIs from COPY/MOVE/ADD operations.
        
        Args:
            sparql_update: SPARQL UPDATE query
            operation: Operation type (COPY, MOVE, ADD)
            
        Returns:
            tuple: (source_graph, target_graph)
        """
        import re
        
        # Pattern to match "OPERATION <source> TO <target>"
        pattern = rf'{operation}\s+<([^>]+)>\s+TO\s+<([^>]+)>'
        match = re.search(pattern, sparql_update, re.IGNORECASE)
        
        if match:
            return match.group(1), match.group(2)
        
        raise ValueError(f"Could not extract graph pair from {operation} operation: {sparql_update}")
    
    async def ensure_graph_registered(self, space_id: str, graph_uri: str) -> None:
        """
        Ensure a graph is registered in both the cache and the graph table.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to register
        """
        try:
            # Initialize graph cache if needed
            await self.initialize_graph_cache_if_needed(space_id)
            
            # Check if graph is already in cache
            if space_id in self.graph_cache and graph_uri in self.graph_cache[space_id]:
                return
            
            # Check if graph exists in database
            if not await self.graph_exists_in_db(space_id, graph_uri):
                # Insert graph into database
                await self.insert_graph_to_db(space_id, graph_uri)
            
            # Add to cache
            if space_id not in self.graph_cache:
                self.graph_cache[space_id] = {}
            self.graph_cache[space_id][graph_uri] = True
            
        except Exception as e:
            self.logger.error(f"Error ensuring graph {graph_uri} is registered: {e}")
            raise
    
    async def ensure_graphs_registered_batch(self, space_id: str, graph_uris: set) -> None:
        """
        Efficiently ensure multiple graphs are registered in both cache and database.
        
        Args:
            space_id: The space identifier
            graph_uris: Set of graph URIs to register
        """
        try:
            # Initialize graph cache if needed
            await self.initialize_graph_cache_if_needed(space_id)
            
            # Filter out graphs that are already in cache
            uncached_graphs = set()
            for graph_uri in graph_uris:
                if space_id not in self.graph_cache or graph_uri not in self.graph_cache[space_id]:
                    uncached_graphs.add(graph_uri)
            
            if not uncached_graphs:
                return  # All graphs already cached
            
            # Check which graphs exist in database
            existing_graphs = await self.check_graphs_exist_in_db_batch(space_id, uncached_graphs)
            
            # Insert missing graphs
            missing_graphs = uncached_graphs - existing_graphs
            if missing_graphs:
                await self.insert_graphs_to_db_batch(space_id, missing_graphs)
            
            # Add all to cache
            if space_id not in self.graph_cache:
                self.graph_cache[space_id] = {}
            for graph_uri in uncached_graphs:
                self.graph_cache[space_id][graph_uri] = True
                
        except Exception as e:
            self.logger.error(f"Error ensuring graphs are registered: {e}")
            raise
    
    async def graph_exists_in_db(self, space_id: str, graph_uri: str) -> bool:
        """
        Check if a graph exists in the database.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to check
            
        Returns:
            bool: True if graph exists in database
        """
        try:
            # This would need to be implemented based on the actual space implementation
            # For now, assume the space implementation has a method to check graph existence
            if hasattr(self.space_impl, 'graph_exists'):
                return await self.space_impl.graph_exists(space_id, graph_uri)
            else:
                # Fallback: assume graph exists if we can't check
                self.logger.warning(f"Cannot check graph existence for {graph_uri}, assuming it exists")
                return True
                
        except Exception as e:
            self.logger.error(f"Error checking if graph {graph_uri} exists: {e}")
            return False
    
    async def check_graphs_exist_in_db_batch(self, space_id: str, graph_uris: set) -> set:
        """
        Check which graphs exist in the database (batch operation).
        
        Args:
            space_id: The space identifier
            graph_uris: Set of graph URIs to check
            
        Returns:
            set: Set of graph URIs that exist in the database
        """
        try:
            existing_graphs = set()
            for graph_uri in graph_uris:
                if await self.graph_exists_in_db(space_id, graph_uri):
                    existing_graphs.add(graph_uri)
            return existing_graphs
            
        except Exception as e:
            self.logger.error(f"Error checking graphs existence: {e}")
            return set()
    
    async def insert_graph_to_db(self, space_id: str, graph_uri: str) -> None:
        """
        Insert a new graph into the database.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to insert
        """
        try:
            # This would need to be implemented based on the actual space implementation
            if hasattr(self.space_impl, 'insert_graph'):
                await self.space_impl.insert_graph(space_id, graph_uri)
            else:
                self.logger.warning(f"Cannot insert graph {graph_uri}, space implementation missing method")
                
        except Exception as e:
            self.logger.error(f"Error inserting graph {graph_uri}: {e}")
            raise
    
    async def insert_graphs_to_db_batch(self, space_id: str, graph_uris: set) -> None:
        """
        Insert multiple new graphs into the database (batch operation).
        
        Args:
            space_id: The space identifier
            graph_uris: Set of graph URIs to insert
        """
        try:
            for graph_uri in graph_uris:
                await self.insert_graph_to_db(space_id, graph_uri)
                
        except Exception as e:
            self.logger.error(f"Error inserting graphs: {e}")
            raise
    
    async def remove_graph_from_db(self, space_id: str, graph_uri: str) -> None:
        """
        Remove a graph from the database.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to remove
        """
        try:
            # This would need to be implemented based on the actual space implementation
            if hasattr(self.space_impl, 'remove_graph'):
                await self.space_impl.remove_graph(space_id, graph_uri)
            else:
                self.logger.warning(f"Cannot remove graph {graph_uri}, space implementation missing method")
                
        except Exception as e:
            self.logger.error(f"Error removing graph {graph_uri}: {e}")
            raise
    
    async def remove_all_quads_from_graph(self, space_id: str, graph_uri: str) -> None:
        """
        Remove all quads from a specific graph.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to clear
        """
        try:
            # This would need to be implemented based on the actual space implementation
            if hasattr(self.space_impl, 'remove_all_quads_from_graph'):
                await self.space_impl.remove_all_quads_from_graph(space_id, graph_uri)
            else:
                self.logger.warning(f"Cannot remove quads from graph {graph_uri}, space implementation missing method")
                
        except Exception as e:
            self.logger.error(f"Error removing quads from graph {graph_uri}: {e}")
            raise
    
    async def copy_all_quads_between_graphs(self, space_id: str, source_graph: str, target_graph: str) -> None:
        """
        Copy all quads from source graph to target graph.
        
        Args:
            space_id: The space identifier
            source_graph: URI of the source graph
            target_graph: URI of the target graph
        """
        try:
            # This would need to be implemented based on the actual space implementation
            if hasattr(self.space_impl, 'copy_all_quads_between_graphs'):
                await self.space_impl.copy_all_quads_between_graphs(space_id, source_graph, target_graph)
            else:
                # Fallback: get all quads from source and insert into target
                quads = await self.get_all_quads_in_graph(space_id, source_graph)
                if quads:
                    # Convert to target graph and insert
                    target_quads = [(s, p, o, URIRef(target_graph)) for s, p, o, g in quads]
                    await self.space_impl.add_rdf_quads_batch(space_id, target_quads)
                
        except Exception as e:
            self.logger.error(f"Error copying quads from {source_graph} to {target_graph}: {e}")
            raise
    
    async def get_all_quads_in_graph(self, space_id: str, graph_uri: str) -> List[Tuple[Any, Any, Any, Any]]:
        """
        Get all quads in a specific graph.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph
            
        Returns:
            list: List of (subject, predicate, object, graph) tuples
        """
        try:
            # This would need to be implemented based on the actual space implementation
            if hasattr(self.space_impl, 'get_all_quads_in_graph'):
                return await self.space_impl.get_all_quads_in_graph(space_id, graph_uri)
            else:
                self.logger.warning(f"Cannot get quads from graph {graph_uri}, space implementation missing method")
                return []
                
        except Exception as e:
            self.logger.error(f"Error getting quads from graph {graph_uri}: {e}")
            return []
    
    # Database Integration Methods
    
    async def graph_exists(self, space_id: str, graph_uri: str) -> bool:
        """
        Check if a graph exists in the database.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to check
            
        Returns:
            bool: True if graph exists, False otherwise
        """
        try:
            # Check graph cache first
            if hasattr(self, 'graph_cache') and self.graph_cache:
                if graph_uri in self.graph_cache:
                    return True
            
            # Get dynamic table names from space implementation
            table_names = self.space_impl._get_table_names(space_id)
            sql = f"""
                SELECT 1 FROM {table_names['graph']} 
                WHERE graph_uri = %s 
                LIMIT 1
            """
            
            result = await self._execute_sql_query_with_params(sql, (graph_uri,))
            return len(result) > 0
            
        except Exception as e:
            self.logger.error(f"Error checking if graph {graph_uri} exists: {e}")
            return False
    
    async def insert_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Insert a new graph into the database.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to insert
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if graph already exists
            if await self.graph_exists(space_id, graph_uri):
                self.logger.info(f"Graph {graph_uri} already exists")
                return True
            
            # Get dynamic table names from space implementation
            table_names = self.space_impl._get_table_names(space_id)
            sql = f"""
                INSERT INTO {table_names['graph']} (graph_uri, graph_name, triple_count) 
                VALUES (%s, %s, %s)
                ON CONFLICT (graph_uri) DO NOTHING
            """
            
            await self._execute_sql_query_with_params(sql, (graph_uri, graph_uri, 0))
            
            # Update graph cache
            if hasattr(self, 'graph_cache') and self.graph_cache is not None:
                self.graph_cache.add(graph_uri)
            
            self.logger.info(f"Successfully inserted graph {graph_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error inserting graph {graph_uri}: {e}")
            return False
    
    async def remove_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Remove a graph from the database.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to remove
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get dynamic table names from space implementation
            table_names = self.space_impl._get_table_names(space_id)
            sql = f"""
                DELETE FROM {table_names['graph']} 
                WHERE graph_uri = %s
            """
            
            await self._execute_sql_query_with_params(sql, (graph_uri,))
            
            # Update graph cache
            if hasattr(self, 'graph_cache') and self.graph_cache is not None:
                self.graph_cache.discard(graph_uri)
            
            self.logger.info(f"Successfully removed graph {graph_uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error removing graph {graph_uri}: {e}")
            return False
    
    async def remove_all_quads_from_graph(self, space_id: str, graph_uri: str) -> bool:
        """
        Remove all quads (triples) from a specific graph.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph to clear
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get table configuration
            table_config = TableConfig.from_space_impl(self.space_impl, space_id)
            
            # Get graph UUID from term table
            graph_uuid_query = f"""
                SELECT term_uuid FROM {table_config.term_table} 
                WHERE term_value = %s AND term_type = 'uri'
            """
            
            graph_uuid_result = await self._execute_sql_query_with_params(graph_uuid_query, (graph_uri,))
            if not graph_uuid_result:
                self.logger.info(f"Graph {graph_uri} not found in term table, nothing to remove")
                return True
            
            graph_uuid = graph_uuid_result[0]['term_uuid'] if isinstance(graph_uuid_result[0], dict) else graph_uuid_result[0][0]
            
            # Remove all quads from the specified graph
            sql = f"""
                DELETE FROM {table_config.quad_table} 
                WHERE graph_uuid = %s
            """
            
            result = await self._execute_sql_query_with_params(sql, (graph_uuid,))
            
            # Log the number of quads removed
            if hasattr(result, 'rowcount'):
                self.logger.info(f"Removed {result.rowcount} quads from graph {graph_uri}")
            else:
                self.logger.info(f"Successfully cleared all quads from graph {graph_uri}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error removing quads from graph {graph_uri}: {e}")
            return False
    
    async def copy_all_quads_between_graphs(self, space_id: str, source_graph_uri: str, target_graph_uri: str) -> bool:
        """
        Copy all quads from source graph to target graph.
        
        Args:
            space_id: The space identifier
            source_graph_uri: URI of the source graph
            target_graph_uri: URI of the target graph
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure target graph exists
            await self.ensure_graph_registered(space_id, target_graph_uri)
            
            # Get table configuration
            table_config = TableConfig.from_space_impl(self.space_impl, space_id)
            
            # Get source and target graph UUIDs from term table
            graph_uuid_query = f"""
                SELECT term_uuid, term_value FROM {table_config.term_table} 
                WHERE term_value IN (%s, %s) AND term_type = 'uri'
            """
            
            graph_uuid_result = await self._execute_sql_query_with_params(graph_uuid_query, (source_graph_uri, target_graph_uri))
            
            source_graph_uuid = None
            target_graph_uuid = None
            
            for row in graph_uuid_result:
                if isinstance(row, dict):
                    if row['term_value'] == source_graph_uri:
                        source_graph_uuid = row['term_uuid']
                    elif row['term_value'] == target_graph_uri:
                        target_graph_uuid = row['term_uuid']
                else:
                    # Handle tuple format
                    if row[1] == source_graph_uri:
                        source_graph_uuid = row[0]
                    elif row[1] == target_graph_uri:
                        target_graph_uuid = row[0]
            
            if not source_graph_uuid:
                self.logger.info(f"Source graph {source_graph_uri} not found, nothing to copy")
                return True
            
            if not target_graph_uuid:
                self.logger.error(f"Target graph {target_graph_uri} not found after registration")
                return False
            
            # Copy all quads from source to target graph
            sql = f"""
                INSERT INTO {table_config.quad_table} (subject_uuid, predicate_uuid, object_uuid, graph_uuid)
                SELECT subject_uuid, predicate_uuid, object_uuid, %s
                FROM {table_config.quad_table} 
                WHERE graph_uuid = %s
                ON CONFLICT (subject_uuid, predicate_uuid, object_uuid, graph_uuid) DO NOTHING
            """
            
            result = await self._execute_sql_query_with_params(sql, (target_graph_uuid, source_graph_uuid))
            
            # Log the number of quads copied
            if hasattr(result, 'rowcount'):
                self.logger.info(f"Copied {result.rowcount} quads from {source_graph_uri} to {target_graph_uri}")
            else:
                self.logger.info(f"Successfully copied quads from {source_graph_uri} to {target_graph_uri}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error copying quads from {source_graph_uri} to {target_graph_uri}: {e}")
            return False
    
    async def get_all_quads_in_graph(self, space_id: str, graph_uri: str, page_size: int = 1000, offset: int = 0) -> dict:
        """
        Get all quads in a specific graph with paging support.
        
        Args:
            space_id: The space identifier
            graph_uri: URI of the graph
            page_size: Number of quads to return per page (default: 1000)
            offset: Number of quads to skip (default: 0)
            
        Returns:
            dict: Dictionary containing 'quads' list, 'total_count', 'has_more', 'next_offset'
        """
        try:
            # Get table configuration
            table_config = TableConfig.from_space_impl(self.space_impl, space_id)
            
            # Get graph UUID from term table
            graph_uuid_query = f"""
                SELECT term_uuid FROM {table_config.term_table} 
                WHERE term_value = %s AND term_type = 'uri'
            """
            
            graph_uuid_result = await self._execute_sql_query_with_params(graph_uuid_query, (graph_uri,))
            if not graph_uuid_result:
                return {
                    'quads': [],
                    'total_count': 0,
                    'page_size': page_size,
                    'offset': offset,
                    'has_more': False,
                    'next_offset': None,
                    'returned_count': 0
                }
            
            graph_uuid = graph_uuid_result[0]['term_uuid'] if isinstance(graph_uuid_result[0], dict) else graph_uuid_result[0][0]
            
            # Get total count first
            count_sql = f"""
                SELECT COUNT(*) as total_count
                FROM {table_config.quad_table} 
                WHERE graph_uuid = %s
            """
            
            count_result = await self._execute_sql_query_with_params(count_sql, (graph_uuid,))
            total_count = count_result[0]['total_count'] if count_result and isinstance(count_result[0], dict) else (count_result[0][0] if count_result else 0)
            
            # Get paged quads with term joins
            quads_sql = f"""
                SELECT 
                    s.term_value as subject_uri,
                    p.term_value as predicate_uri, 
                    o.term_value as object_value,
                    o.term_type as object_type,
                    g.term_value as graph_uri
                FROM {table_config.quad_table} q
                JOIN {table_config.term_table} s ON q.subject_uuid = s.term_uuid
                JOIN {table_config.term_table} p ON q.predicate_uuid = p.term_uuid  
                JOIN {table_config.term_table} o ON q.object_uuid = o.term_uuid
                JOIN {table_config.term_table} g ON q.graph_uuid = g.term_uuid
                WHERE q.graph_uuid = %s
                ORDER BY s.term_value, p.term_value, o.term_value
                LIMIT %s OFFSET %s
            """
            
            quads_result = await self._execute_sql_query_with_params(quads_sql, (graph_uuid, page_size, offset))
            
            # Convert to quad tuples
            quads = []
            for row in quads_result:
                if isinstance(row, dict):
                    # Convert object based on type
                    if row['object_type'] == 'uri':
                        obj = row['object_value']
                    elif row['object_type'] == 'literal':
                        obj = row['object_value']
                    else:
                        obj = row['object_value']
                    
                    quad = (row['subject_uri'], row['predicate_uri'], obj, row['graph_uri'])
                else:
                    # Handle tuple format
                    quad = (row[0], row[1], row[2], row[4])  # subject, predicate, object, graph
                
                quads.append(quad)
            
            # Calculate pagination info
            has_more = (offset + len(quads)) < total_count
            next_offset = offset + len(quads) if has_more else None
            
            result = {
                'quads': quads,
                'total_count': total_count,
                'page_size': page_size,
                'offset': offset,
                'has_more': has_more,
                'next_offset': next_offset,
                'returned_count': len(quads)
            }
            
            self.logger.info(f"Retrieved {len(quads)} quads from graph {graph_uri} (offset: {offset}, total: {total_count})")
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting quads from graph {graph_uri}: {e}")
            return {
                'quads': [],
                'total_count': 0,
                'page_size': page_size,
                'offset': offset,
                'has_more': False,
                'next_offset': None,
                'returned_count': 0
            }
 