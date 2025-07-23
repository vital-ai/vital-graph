import logging
from typing import Optional
from rdflib import (
    BNode,
    Literal,
    URIRef
)
from rdflib.term import Variable
from rdflib.graph import Graph, QuotedGraph
from rdflib.namespace import RDF
from rdflib.plugins.stores.regexmatching import PYTHON_REGEX, REGEXTerm
from rdflib.store import CORRUPTED_STORE, VALID_STORE, NodePickler, Store
from .sparql import VitalSparql
from ..space.space_impl import SpaceImpl

class VitalGraphSQLStore(Store):
    """VitalGraph SQL Store implementation.
    
    A Store implementation that provides RDF storage capabilities
    using SQL databases with optimizations for text search and bulk operations.
    """
    
    # Store properties
    context_aware = True
    formula_aware = False
    transaction_aware = True
    graph_aware = True
    
    def __init__(self, configuration=None, identifier=None, space_impl: Optional[SpaceImpl] = None):
        """Initialize the VitalGraphSQLStore.
        
        Args:
            configuration: String containing information open can use to connect to datastore
            identifier: URIRef of the Store. Defaults to CWD
            space_impl: Optional SpaceImpl instance for database operations
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.info(f"Initializing VitalGraphSQLStore with configuration={configuration}, identifier={identifier}")
        
        super().__init__(configuration, identifier)
        
        # Initialize VitalSparql for query analysis and logging
        store_id = str(identifier) if identifier else "unknown"
        self.sparql_analyzer = VitalSparql(store_identifier=store_id)
        self.logger.debug(f"VitalSparql analyzer initialized for store: {store_id}")
        
        # Store the SpaceImpl instance
        self.space_impl = space_impl
        if space_impl:
            self.logger.info(f"SpaceImpl provided: {type(space_impl).__name__} for space_id='{space_impl.space_id}'")
        else:
            self.logger.debug("No SpaceImpl provided - will be created during open() if needed")
        
        # Parse configuration if provided
        self._parsed_config = self._parse_configuration(configuration)
        
        self.logger.debug("VitalGraphSQLStore initialization completed")
    
    # Database management methods
    def _parse_configuration(self, configuration: Optional[str]) -> dict:
        """Parse the configuration string to extract parameters.
        
        Args:
            configuration: Configuration string in format "id=space_123" or None
            
        Returns:
            Dictionary with parsed configuration parameters
        """
        if not configuration:
            return {}
        
        config = {}
        try:
            # Parse simple key=value format
            if '=' in configuration:
                key, value = configuration.split('=', 1)
                config[key.strip()] = value.strip()
                self.logger.debug(f"Parsed configuration: {config}")
            else:
                self.logger.warning(f"Configuration format not recognized: {configuration}")
        except Exception as e:
            self.logger.error(f"Error parsing configuration '{configuration}': {e}")
        
        return config
    
    def _create_store(self, configuration: str) -> bool:
        """Create a new store instance (private method).
        
        Args:
            configuration: Store configuration string
            
        Returns:
            True if creation successful, False otherwise
        """
        self.logger.info(f"_create_store() called with configuration={configuration}")
        
        try:
            # Ensure SpaceImpl is provided
            if not self.space_impl:
                self.logger.error("SpaceImpl must be provided during store initialization")
                return False
            
            # Parse configuration to get space_id
            config = self._parse_configuration(configuration)
            space_id = config.get('id', 'unknown')
            
            # Verify space_id matches SpaceImpl
            if self.space_impl.space_id != space_id:
                self.logger.warning(f"Configuration space_id '{space_id}' does not match SpaceImpl space_id '{self.space_impl.space_id}'")
            
            # Delegate actual creation to SpaceImpl
            self.logger.info("Delegating store creation to SpaceImpl...")
            creation_success = self.space_impl.create()
            
            if creation_success:
                self.logger.debug(f"_create_store() completed successfully")
                return True
            else:
                self.logger.error(f"SpaceImpl creation failed")
                return False
            
        except Exception as e:
            self.logger.error(f"_create_store() failed: {e}")
            return False
    
    def open(self, configuration, create=False):
        """Open the store specified by the configuration string.
        
        Args:
            configuration: Store configuration string
            create: If True, a store will be created if it doesn't exist
            
        Returns:
            One of: VALID_STORE, CORRUPTED_STORE, or NO_STORE
        """
        self.logger.info(f"open() called with configuration={configuration}, create={create}")
        
        try:
            # If create is True, create the store first
            if create:
                self.logger.info("Create flag is True, creating store...")
                creation_success = self._create_store(configuration)
                if not creation_success:
                    self.logger.error("Store creation failed")
                    return CORRUPTED_STORE
            
            # Ensure SpaceImpl is provided
            if not self.space_impl:
                self.logger.error("SpaceImpl must be provided during store initialization")
                return CORRUPTED_STORE
            
            # Parse configuration to get space_id
            config = self._parse_configuration(configuration)
            space_id = config.get('id', 'unknown')
            
            # Verify space_id matches SpaceImpl
            if self.space_impl.space_id != space_id:
                self.logger.warning(f"Configuration space_id '{space_id}' does not match SpaceImpl space_id '{self.space_impl.space_id}'")
            
            # Delegate actual opening to SpaceImpl (if not creating)
            if not create:
                self.logger.info("Delegating store opening to SpaceImpl...")
                opening_success = self.space_impl.open()
                
                if not opening_success:
                    self.logger.error("SpaceImpl opening failed")
                    return CORRUPTED_STORE
            
            result = VALID_STORE
            self.logger.info(f"open() completed successfully, returning {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"open() failed: {e}")
            return CORRUPTED_STORE
    
    def close(self, commit_pending_transaction=False):
        """Close the database connection.
        
        Args:
            commit_pending_transaction: Whether to commit all pending transactions before closing
        """
        self.logger.info(f"close() called with commit_pending_transaction={commit_pending_transaction}")
        
        try:
            # Handle transaction commit if requested
            if commit_pending_transaction:
                self.logger.info("Committing pending transactions before closing...")
                # TODO: Implement transaction commit logic if needed
            
            # Delegate actual closing to SpaceImpl
            if self.space_impl:
                self.logger.info("Delegating store closing to SpaceImpl...")
                self.space_impl.close()
                self.logger.debug("SpaceImpl closed successfully")
            else:
                self.logger.warning("No SpaceImpl available to close")
            
            self.logger.debug("close() completed successfully")
            
        except Exception as e:
            self.logger.error(f"close() failed: {e}")
    
    def destroy(self, configuration):
        """Destroy the instance of the store.
        
        Args:
            configuration: The configuration string identifying the store instance
        """
        self.logger.info(f"destroy() called with configuration={configuration}")
        
        try:
            # Parse configuration to get space_id
            config = self._parse_configuration(configuration)
            space_id = config.get('id', 'unknown')
            
            # Verify space_id matches SpaceImpl if available
            if self.space_impl and self.space_impl.space_id != space_id:
                self.logger.warning(f"Configuration space_id '{space_id}' does not match SpaceImpl space_id '{self.space_impl.space_id}'")
            
            # Delegate actual destruction to SpaceImpl
            if self.space_impl:
                self.logger.info("Delegating store destruction to SpaceImpl...")
                destruction_success = self.space_impl.destroy()
                
                if destruction_success:
                    self.logger.info("SpaceImpl destroyed successfully")
                else:
                    self.logger.error("SpaceImpl destruction failed")
                    
                # Clear the SpaceImpl reference after destruction
                self.space_impl = None
                self.logger.debug("SpaceImpl reference cleared")
            else:
                self.logger.warning("No SpaceImpl available to destroy")
            
            self.logger.debug("destroy() completed successfully")
            
        except Exception as e:
            self.logger.error(f"destroy() failed: {e}")
    
    # RDF API methods
    def add(self, triple, context, quoted=False):
        """Add the given statement to a specific context or to the model.
        
        Args:
            triple: The triple to add
            context: The context to add the triple to
            quoted: If True, indicates this statement is quoted/hypothetical
        """
        self.logger.info(f"add() called with triple={triple}, context={context}, quoted={quoted}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for add operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.add_triple(triple, context, quoted)
            
            if success:
                self.logger.debug("add() completed successfully via SpaceImpl")
            else:
                self.logger.warning("add() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"add() failed: {e}")
    
    def addN(self, quads):
        """Add each item in the list of statements to a specific context.
        
        Args:
            quads: An iterable of quads to add
        """
        # Convert to list to get count for logging
        quad_list = list(quads) if hasattr(quads, '__iter__') else [quads]
        self.logger.info(f"addN() called with {len(quad_list)} quads")
        self.logger.debug(f"addN() quad details: {quad_list[:3]}{'...' if len(quad_list) > 3 else ''}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for addN operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.add_triples(quad_list)
            
            if success:
                self.logger.debug(f"addN() completed successfully via SpaceImpl - added {len(quad_list)} quads")
            else:
                self.logger.warning("addN() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"addN() failed: {e}")
    
    def remove(self, triple, context=None):
        """Remove the set of triples matching the pattern from the store.
        
        Args:
            triple: Triple pattern to match for removal
            context: Context to remove from, or None for all contexts
        """
        self.logger.info(f"remove() called with triple={triple}, context={context}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for remove operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.remove_triple(triple, context)
            
            if success:
                self.logger.debug("remove() completed successfully via SpaceImpl")
            else:
                self.logger.warning("remove() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"remove() failed: {e}")
    
    def triples_choices(self, triple, context=None):
        """A variant of triples that can take a list of terms instead of a single term in any slot.
        
        Args:
            triple: Triple pattern with possible lists in any position
            context: Context to query
            
        Yields:
            Tuples of (triple, context_iterator)
        """
        self.logger.info(f"triples_choices() called with context={context}")
        
        # Detailed logging of triple choices pattern components
        if triple and len(triple) >= 3:
            subject, predicate, obj = triple[0], triple[1], triple[2]
            self.logger.info(f"Triple choices pattern breakdown:")
            
            # Log subject with list detection
            if isinstance(subject, (list, tuple)):
                self.logger.info(f"  Subject: {type(subject).__name__} with {len(subject)} choices = {subject}")
            else:
                self.logger.info(f"  Subject: {type(subject).__name__} = {subject}")
            
            # Log predicate with list detection
            if isinstance(predicate, (list, tuple)):
                self.logger.info(f"  Predicate: {type(predicate).__name__} with {len(predicate)} choices = {predicate}")
            else:
                self.logger.info(f"  Predicate: {type(predicate).__name__} = {predicate}")
            
            # Log object with list detection
            if isinstance(obj, (list, tuple)):
                self.logger.info(f"  Object: {type(obj).__name__} with {len(obj)} choices = {obj}")
            else:
                self.logger.info(f"  Object: {type(obj).__name__} = {obj}")
            
            # Count choice positions
            choice_positions = sum(1 for x in [subject, predicate, obj] if isinstance(x, (list, tuple)))
            self.logger.info(f"Choice pattern: {choice_positions}/3 positions have multiple choices")
        else:
            self.logger.warning(f"Invalid triple choices pattern: {triple}")
        
        # Log context details
        if context:
            self.logger.info(f"Context details: {type(context).__name__} = {context}")
        else:
            self.logger.info("Context: None (conjunctive query across all graphs)")
        
        # TODO: Implement optimized triples_choices
        # For now, fall back to default implementation
        self.logger.debug("triples_choices() falling back to default implementation")
        yield from super().triples_choices(triple, context)
    
    def triples(self, triple_pattern, context=None):
        """Generator over all the triples matching the pattern.
        
        Args:
            triple_pattern: Pattern to match (subject, predicate, object)
            context: A specific context to query or None for conjunctive query
            
        Yields:
            Tuples of (triple, context_iterator)
        """
        self.logger.info(f"triples() called with context={context}")
        
        # Detailed logging of triple pattern components
        if triple_pattern and len(triple_pattern) >= 3:
            subject, predicate, obj = triple_pattern[0], triple_pattern[1], triple_pattern[2]
            self.logger.info(f"Triple pattern breakdown:")
            self.logger.info(f"  Subject: {type(subject).__name__} = {subject}")
            self.logger.info(f"  Predicate: {type(predicate).__name__} = {predicate}")
            self.logger.info(f"  Object: {type(obj).__name__} = {obj}")
            
            # Log pattern specificity
            none_count = sum(1 for x in [subject, predicate, obj] if x is None)
            self.logger.info(f"Pattern specificity: {3-none_count}/3 terms specified ({none_count} wildcards)")
        else:
            self.logger.warning(f"Invalid triple pattern: {triple_pattern}")
        
        # Log context details
        if context:
            self.logger.info(f"Context details: {type(context).__name__} = {context}")
        else:
            self.logger.info("Context: None (conjunctive query across all graphs)")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for triples operation")
                return
            
            # Delegate to SpaceImpl
            for result in self.space_impl.get_triples(triple_pattern, context):
                yield result
                
            self.logger.debug("triples() completed successfully via SpaceImpl")
            
        except Exception as e:
            self.logger.error(f"triples() failed: {e}")
            # Return empty generator on error
            return
    
    def __len__(self, context=None):
        """Number of statements in the store.
        
        Args:
            context: A graph instance to query or None
            
        Returns:
            Number of statements
        """
        self.logger.debug(f"__len__() called with context={context}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for __len__ operation")
                return 0
            
            # Delegate to SpaceImpl
            result = self.space_impl.get_length(context)
            
            self.logger.debug(f"__len__() returning {result} via SpaceImpl")
            return result
            
        except Exception as e:
            self.logger.error(f"__len__() failed: {e}")
            return 0
    
    def contexts(self, triple=None):
        """Generator over all contexts in the graph.
        
        Args:
            triple: If specified, generator over all contexts the triple is in
            
        Yields:
            Context nodes
        """
        self.logger.info(f"contexts() called with triple={triple}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for contexts operation")
                return
            
            # Delegate to SpaceImpl
            for context in self.space_impl.get_contexts(triple):
                yield context
                
            self.logger.debug("contexts() completed successfully via SpaceImpl")
            
        except Exception as e:
            self.logger.error(f"contexts() failed: {e}")
            # Return empty generator on error
            return
    
    # Query methods
    def query(self, query, initNs, initBindings, queryGraph, **kwargs):
        """Execute a SPARQL query.
        
        Args:
            query: Query object or string
            initNs: Initial namespace bindings
            initBindings: Initial variable bindings
            queryGraph: Graph to query (None, URIRef, or '__UNION__')
            **kwargs: Additional query parameters
            
        Returns:
            Query result
        """
        self.logger.info(f"query() called with query type={type(query)}, queryGraph={queryGraph}")
        
        # Use VitalSparql to analyze and log the query parse tree
        self.sparql_analyzer.log_parse_tree(query, "query")
        
        # Log the execution context
        self.sparql_analyzer.log_query_execution_context(
            initNs=initNs, 
            initBindings=initBindings, 
            queryGraph=queryGraph, 
            **kwargs
        )
        
        # TODO: Implement SPARQL query execution
        self.logger.warning("query() not yet implemented - raising NotImplementedError")
        raise NotImplementedError("SPARQL query not yet implemented")
    
    def update(self, update, initNs, initBindings, queryGraph, **kwargs):
        """Execute a SPARQL update.
        
        Args:
            update: Update object or string
            initNs: Initial namespace bindings
            initBindings: Initial variable bindings
            queryGraph: Graph to update (None, URIRef, or '__UNION__')
            **kwargs: Additional update parameters
        """
        self.logger.info(f"update() called with update type={type(update)}, queryGraph={queryGraph}")
        
        # Use VitalSparql to analyze and log the update parse tree
        self.sparql_analyzer.log_parse_tree(update, "update")
        
        # Log the execution context
        self.sparql_analyzer.log_query_execution_context(
            initNs=initNs, 
            initBindings=initBindings, 
            queryGraph=queryGraph, 
            **kwargs
        )
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for update operation")
                raise NotImplementedError("No SpaceImpl available for SPARQL update")
            
            # Delegate to SpaceImpl
            result = self.space_impl.execute_sparql_update(
                update=str(update),
                initNs=initNs,
                initBindings=initBindings,
                queryGraph=queryGraph,
                **kwargs
            )
            
            self.logger.debug("update() completed successfully via SpaceImpl")
            return result
            
        except Exception as e:
            self.logger.error(f"update() failed: {e}")
            raise
    
    # Namespace methods
    def bind(self, prefix, namespace, override=True):
        """Bind a namespace to a prefix.
        
        Args:
            prefix: The prefix to bind the namespace to
            namespace: The URIRef of the namespace to bind
            override: If True, rebind even if namespace is already bound to another prefix
        """
        self.logger.info(f"bind() called with prefix={prefix}, namespace={namespace}, override={override}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for bind operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.bind_namespace(prefix, namespace, override)
            
            if success:
                self.logger.debug("bind() completed successfully via SpaceImpl")
            else:
                self.logger.warning("bind() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"bind() failed: {e}")
    

    def namespaces(self):
        """Generator over all namespace bindings.
        
        Yields:
            Tuples of (prefix, namespace)
        """
        self.logger.debug("namespaces() called")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for namespaces operation")
                return
            
            # Delegate to SpaceImpl
            for binding in self.space_impl.get_namespaces():
                yield binding
                
            self.logger.debug("namespaces() completed successfully via SpaceImpl")
            
        except Exception as e:
            self.logger.error(f"namespaces() failed: {e}")
            # Return empty generator on error
            return
    
    # Transaction methods
    def commit(self):
        """Commit the current transaction."""
        self.logger.info("commit() called")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for commit operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.commit_transaction()
            
            if success:
                self.logger.debug("commit() completed successfully via SpaceImpl")
            else:
                self.logger.warning("commit() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"commit() failed: {e}")
    
    def rollback(self):
        """Rollback the current transaction."""
        self.logger.info("rollback() called")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for rollback operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.rollback_transaction()
            
            if success:
                self.logger.debug("rollback() completed successfully via SpaceImpl")
            else:
                self.logger.warning("rollback() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"rollback() failed: {e}")
    
    # Graph methods
    def add_graph(self, graph):
        """Add a graph to the store.
        
        Args:
            graph: A Graph instance
        """
        self.logger.info(f"add_graph() called with graph={graph}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for add_graph operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.add_graph(graph)
            
            if success:
                self.logger.debug("add_graph() completed successfully via SpaceImpl")
            else:
                self.logger.warning("add_graph() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"add_graph() failed: {e}")
    
    def remove_graph(self, graph):
        """Remove a graph from the store.
        
        Args:
            graph: A Graph instance
        """
        self.logger.info(f"remove_graph() called with graph={graph}")
        
        try:
            if not self.space_impl:
                self.logger.error("No SpaceImpl available for remove_graph operation")
                return
            
            # Delegate to SpaceImpl
            success = self.space_impl.remove_graph(graph)
            
            if success:
                self.logger.debug("remove_graph() completed successfully via SpaceImpl")
            else:
                self.logger.warning("remove_graph() failed in SpaceImpl")
                
        except Exception as e:
            self.logger.error(f"remove_graph() failed: {e}")

