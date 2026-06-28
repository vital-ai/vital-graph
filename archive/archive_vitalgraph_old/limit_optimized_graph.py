#!/usr/bin/env python3

"""
SPARQL LIMIT/OFFSET Optimization for VitalGraph

This module provides a Graph wrapper that intercepts SPARQL queries with LIMIT/OFFSET
clauses and ensures they are pushed down to the SQL level for optimal performance.
"""

import re
import logging
from rdflib import Graph

_logger = logging.getLogger(__name__)

class LimitOptimizedGraph(Graph):
    """
    A Graph wrapper that optimizes SPARQL queries with LIMIT/OFFSET clauses
    by pushing them down to the SQL level.
    """
    
    def __init__(self, store=None, identifier=None, namespace_manager=None, base=None):
        """Initialize the optimized graph"""
        super().__init__(store=store, identifier=identifier, 
                        namespace_manager=namespace_manager, base=base)
        _logger.info("LimitOptimizedGraph initialized")
    
    def query(self, query_object, processor='sparql', result='sparql', 
              initNs=None, initBindings=None, use_store_provided=True, **kwargs):
        """
        Override query method to extract LIMIT/OFFSET and set store context
        """
        _logger.info("🚀 LimitOptimizedGraph.query: FUNCTION STARTED")
        
        # Convert query to string if it's a prepared query
        if hasattr(query_object, 'algebra'):
            # This is a prepared query - we need to extract the original query string
            query_string = str(query_object)
        else:
            query_string = str(query_object)
        
        _logger.info(f"Query string: {query_string[:200]}...")
        
        # Extract LIMIT and OFFSET from SPARQL query
        limit_match = re.search(r'LIMIT\s+(\d+)', query_string, re.IGNORECASE)
        offset_match = re.search(r'OFFSET\s+(\d+)', query_string, re.IGNORECASE)
        
        limit = int(limit_match.group(1)) if limit_match else None
        offset = int(offset_match.group(1)) if offset_match else None
        
        _logger.info(f"Extracted LIMIT={limit}, OFFSET={offset}")
        
        # Set query context in the store if it's a VitalGraphSQLStore
        if hasattr(self.store, '_query_context'):
            self.store._query_context['limit'] = limit
            self.store._query_context['offset'] = offset
            _logger.info(f"Set store query context: limit={limit}, offset={offset}")
        
        # Execute the original query
        # NOTE: Do NOT clear context in finally block - RDFLib may call triples() after query() returns
        result = super().query(query_object, processor=processor, result=result,
                             initNs=initNs, initBindings=initBindings,
                             use_store_provided=use_store_provided, **kwargs)
        
        # Context will be cleared by the store after triples() completes
        # or by the next query that sets new context
        _logger.info("Query completed - context preserved for triples() method")
        return result
