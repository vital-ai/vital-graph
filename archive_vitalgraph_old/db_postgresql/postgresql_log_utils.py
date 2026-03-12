import logging
import time
from contextlib import contextmanager
from typing import Union, Tuple, Optional, Dict
from datetime import datetime
import uuid
import hashlib

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode
from rdflib.term import Identifier
from rdflib.namespace import XSD

class PostgreSQLLogUtils:
    """
    Utility class for PostgreSQL RDF operations.
    
    Contains reusable utility methods for:
    - Performance timing and logging
    - SPARQL algebra debugging
    - SQL query logging and analysis
    - RDFLib integration utilities
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize PostgreSQL utilities.
        
        Args:
            logger: Optional logger instance. If None, creates a new logger.
        """
        self.logger = logger or logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @contextmanager
    def time_operation(self, operation_name: str, details: str = ""):
        """
        Context manager for timing operations and logging performance metrics.
        
        Args:
            operation_name: Name of the operation being timed
            details: Additional details to include in the log message
        """
        start_time = time.time()
        detail_str = f" ({details})" if details else ""
        self.logger.debug(f"Starting {operation_name}{detail_str}")
        
        try:
            yield
        finally:
            end_time = time.time()
            duration = end_time - start_time
            duration_ms = duration * 1000
            
            if duration < 0.001:  # Less than 1ms
                duration_str = f"{duration_ms:.3f}ms"
            elif duration < 1.0:  # Less than 1 second
                duration_str = f"{duration_ms:.1f}ms"
            else:  # 1 second or more
                duration_str = f"{duration:.2f}s"
            
            self.logger.info(f"Completed {operation_name}{detail_str} in {duration_str}")
    
    def log_algebra_structure(self, algebra, query_text: str = "", max_depth: int = 3):
        """
        Safely log SPARQL algebra structure with robust error handling.
        
        Args:
            algebra: RDFLib algebra object (may be string in some cases)
            query_text: Optional SPARQL query text for context
            max_depth: Maximum recursion depth for nested structures
        """
        try:
            if query_text:
                truncated_query = query_text[:200] + "..." if len(query_text) > 200 else query_text
                self.logger.debug(f"Query text: {truncated_query}")
            
            # Safe algebra type detection
            algebra_name = self._get_safe_algebra_name(algebra)
            self.logger.debug(f"Algebra type: {algebra_name}")
            
            # Log structure with depth limit
            self._log_algebra_node(algebra, indent=0, max_depth=max_depth)
            
        except Exception as e:
            self.logger.warning(f"Algebra logging failed: {e}")
    
    def _get_safe_algebra_name(self, node) -> str:
        """
        Safely get the name of an algebra node, handling string cases.
        
        Args:
            node: Algebra node (may be string)
            
        Returns:
            str: Safe name representation
        """
        if isinstance(node, str):
            return "String"
        return getattr(node, 'name', str(type(node).__name__))
    
    def _log_algebra_node(self, node, indent: int = 0, max_depth: int = 3):
        """
        Recursively log algebra node structure with safe string handling.
        
        Args:
            node: Algebra node to log
            indent: Current indentation level
            max_depth: Maximum recursion depth
        """
        if indent > max_depth:
            self.logger.debug("  " * indent + "... (max depth reached)")
            return
            
        spaces = "  " * indent
        
        try:
            if isinstance(node, str):
                truncated = node[:50] + "..." if len(node) > 50 else node
                self.logger.debug(f"{spaces}📌 String: {truncated}")
                return
            
            if hasattr(node, 'name'):
                node_name = getattr(node, 'name', 'Unknown')
                self.logger.debug(f"{spaces}📌 {node_name}")
                
                # Log key attributes based on node type
                if node_name == 'Union':
                    if hasattr(node, 'p1') and node.p1:
                        self.logger.debug(f"{spaces}  ├─ LEFT:")
                        self._log_algebra_node(node.p1, indent + 2, max_depth)
                    if hasattr(node, 'p2') and node.p2:
                        self.logger.debug(f"{spaces}  └─ RIGHT:")
                        self._log_algebra_node(node.p2, indent + 2, max_depth)
                elif hasattr(node, 'p') and node.p:
                    self.logger.debug(f"{spaces}  └─ pattern:")
                    self._log_algebra_node(node.p, indent + 2, max_depth)
                elif hasattr(node, 'triples') and node.triples:
                    self.logger.debug(f"{spaces}  └─ triples: {len(node.triples)} patterns")
                    
            elif isinstance(node, (list, tuple)):
                self.logger.debug(f"{spaces}📌 {type(node).__name__} ({len(node)} items)")
                for i, item in enumerate(node[:2]):  # Show first 2 items
                    self.logger.debug(f"{spaces}  [{i+1}]:")
                    self._log_algebra_node(item, indent + 2, max_depth)
                if len(node) > 2:
                    self.logger.debug(f"{spaces}  ... and {len(node) - 2} more")
            else:
                self.logger.debug(f"{spaces}📌 {type(node).__name__}")
                
        except Exception as e:
            self.logger.debug(f"{spaces}⚠️  Node logging error: {e}")
    
    def log_sql_query(self, sql: str, params: Optional[Tuple] = None, 
                     execution_time: Optional[float] = None, result_count: Optional[int] = None):
        """
        Log SQL query with parameters and performance metrics.
        
        Args:
            sql: SQL query string
            params: Optional query parameters
            execution_time: Optional execution time in seconds
            result_count: Optional number of results returned
        """
        try:
            # Log query with truncation for very long queries
            if len(sql) > 1000:
                truncated_sql = sql[:500] + "\n... (truncated) ...\n" + sql[-500:]
                self.logger.debug(f"SQL Query (truncated):\n{truncated_sql}")
            else:
                self.logger.debug(f"SQL Query:\n{sql}")
            
            # Log parameters if provided
            if params:
                self.logger.debug(f"Parameters: {params}")
            
            # Log performance metrics
            if execution_time is not None:
                time_str = f"{execution_time*1000:.1f}ms" if execution_time < 1 else f"{execution_time:.2f}s"
                self.logger.info(f"SQL executed in {time_str}")
            
            if result_count is not None:
                self.logger.info(f"SQL returned {result_count} results")
                
        except Exception as e:
            self.logger.warning(f"SQL logging failed: {e}")
    
    def log_rdflib_terms(self, terms: Dict[str, Identifier], max_terms: int = 10):
        """
        Log RDFLib terms for debugging.
        
        Args:
            terms: Dictionary of term names to RDFLib Identifier objects
            max_terms: Maximum number of terms to log
        """
        try:
            self.logger.debug(f"RDFLib Terms ({len(terms)} total):")
            
            for i, (name, term) in enumerate(terms.items()):
                if i >= max_terms:
                    self.logger.debug(f"  ... and {len(terms) - max_terms} more terms")
                    break
                    
                term_type = "URI" if isinstance(term, URIRef) else \
                           "Literal" if isinstance(term, Literal) else \
                           "BNode" if isinstance(term, BNode) else "Unknown"
                           
                term_str = str(term)[:100] + "..." if len(str(term)) > 100 else str(term)
                self.logger.debug(f"  {name}: {term_type} = {term_str}")
                
        except Exception as e:
            self.logger.warning(f"RDFLib terms logging failed: {e}")
