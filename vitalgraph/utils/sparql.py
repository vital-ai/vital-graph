"""VitalSparql - SPARQL query analysis and logging for VitalGraph.

This module provides SPARQL query parsing, analysis, and logging capabilities
to help with implementing and debugging SPARQL query execution.
"""

import logging
from typing import Any, Optional, Union
import traceback

try:
    from rdflib.plugins.sparql.sparql import Query, Update
    from rdflib.plugins.sparql.parser import parseQuery, parseUpdate
    from rdflib.plugins.sparql.algebra import translateQuery, translateUpdate, traverse
except ImportError:
    # Fallback if specific SPARQL modules are not available
    Query = Any
    Update = Any
    parseQuery = None
    parseUpdate = None
    translateQuery = None
    translateUpdate = None
    traverse = None


class VitalSparql:
    """SPARQL query analysis and logging for VitalGraph.
    
    This class provides functionality to parse, analyze, and log SPARQL queries
    and updates to help with debugging and implementation of query execution.
    """
    
    def __init__(self, store_identifier: str = None):
        """Initialize VitalSparql with logging.
        
        Args:
            store_identifier: Identifier for the associated store (for logging context)
        """
        self.store_identifier = store_identifier or "unknown"
        self.logger = logging.getLogger(f"{__name__}.VitalSparql")
        self.logger.info(f"VitalSparql initialized for store: {self.store_identifier}")
    
    def log_parse_tree(self, query_or_update: Union[str, Query, Update], query_type: str = "query") -> Optional[Any]:
        """Log the parse tree of a SPARQL query or update.
        
        Args:
            query_or_update: SPARQL query string or parsed Query/Update object
            query_type: Type of operation ("query" or "update")
            
        Returns:
            Parsed query object or None if parsing failed
        """
        self.logger.info(f"=== SPARQL {query_type.upper()} PARSE TREE ANALYSIS ===")
        
        try:
            # Handle string vs already parsed objects
            if isinstance(query_or_update, str):
                query_string = query_or_update
                self.logger.info(f"Raw {query_type} string:")
                self._log_query_string(query_string)
                
                # Parse the query
                parsed_query = self._parse_query_string(query_string, query_type)
            else:
                # Already parsed object
                parsed_query = query_or_update
                query_string = str(query_or_update) if hasattr(query_or_update, '__str__') else "<unprintable>"
                self.logger.info(f"Pre-parsed {query_type} object: {type(query_or_update)}")
            
            if parsed_query:
                self._log_parsed_structure(parsed_query, query_type)
                self._log_algebra_tree(parsed_query, query_type)
            
            return parsed_query
            
        except Exception as e:
            self.logger.error(f"Failed to parse {query_type}: {e}")
            self.logger.debug(f"Parse error details:", exc_info=True)
            return None
    
    def _log_query_string(self, query_string: str) -> None:
        """Log the raw query string with line numbers."""
        lines = query_string.strip().split('\n')
        for i, line in enumerate(lines, 1):
            self.logger.info(f"  {i:2d}: {line}")
    
    def _parse_query_string(self, query_string: str, query_type: str) -> Optional[Any]:
        """Parse a SPARQL query string.
        
        Args:
            query_string: Raw SPARQL string
            query_type: "query" or "update"
            
        Returns:
            Parsed query object or None
        """
        try:
            if query_type.lower() == "query":
                if parseQuery:
                    parsed = parseQuery(query_string)
                    self.logger.info("✓ Query parsing successful")
                    return parsed
                else:
                    self.logger.warning("parseQuery not available - using fallback")
                    return query_string
            elif query_type.lower() == "update":
                if parseUpdate:
                    parsed = parseUpdate(query_string)
                    self.logger.info("✓ Update parsing successful")
                    return parsed
                else:
                    self.logger.warning("parseUpdate not available - using fallback")
                    return query_string
            else:
                self.logger.error(f"Unknown query type: {query_type}")
                return None
                
        except Exception as e:
            self.logger.error(f"Parse error: {e}")
            return None
    
    def _log_parsed_structure(self, parsed_query: Any, query_type: str) -> None:
        """Log the structure of the parsed query."""
        self.logger.info(f"Parsed {query_type} structure:")
        
        try:
            # Log basic structure information
            if hasattr(parsed_query, '__dict__'):
                for key, value in parsed_query.__dict__.items():
                    if key.startswith('_'):
                        continue
                    self.logger.info(f"  {key}: {type(value).__name__} = {self._format_value(value)}")
            else:
                self.logger.info(f"  Type: {type(parsed_query).__name__}")
                self.logger.info(f"  Value: {self._format_value(parsed_query)}")
                
        except Exception as e:
            self.logger.warning(f"Could not log parsed structure: {e}")
    
    def _log_algebra_tree(self, parsed_query: Any, query_type: str) -> None:
        """Log the SPARQL algebra tree representation.
        
        Args:
            parsed_query: Parsed SPARQL query/update object
            query_type: "query" or "update"
        """
        try:
            if query_type.lower() == "query" and translateQuery:
                query_obj = translateQuery(parsed_query)
                self.logger.info("=== SPARQL ALGEBRA TREE ===")
                self.logger.info(f"Query object type: {type(query_obj).__name__}")
                
                # Log query-level attributes first
                if hasattr(query_obj, '__dict__'):
                    query_attrs = {k: v for k, v in query_obj.__dict__.items() 
                                 if not k.startswith('_') and k != 'algebra'}
                    if query_attrs:
                        self.logger.info("Query attributes:")
                        for key, value in query_attrs.items():
                            self.logger.info(f"  {key}: {self._format_value(value)}")
                
                # Access and log the actual algebra tree
                if hasattr(query_obj, 'algebra'):
                    self._walk_algebra_tree(query_obj.algebra)
                    
                    # Also log algebra tree statistics
                    self._log_algebra_statistics(query_obj.algebra)
                else:
                    # Fallback: try to extract algebra from the query object
                    self.logger.info(f"No direct 'algebra' attribute found in {type(query_obj).__name__}")
                    self.logger.info("Available attributes:")
                    if hasattr(query_obj, '__dict__'):
                        for key, value in query_obj.__dict__.items():
                            if not key.startswith('_'):
                                self.logger.info(f"  {key}: {type(value).__name__}")
                                if key == 'algebra' or 'algebra' in key.lower():
                                    self.logger.info(f"  Found potential algebra in '{key}':")
                                    self._walk_algebra_tree(value)
                                    
            elif query_type.lower() == "update" and translateUpdate:
                update_obj = translateUpdate(parsed_query)
                self.logger.info("=== SPARQL UPDATE ALGEBRA ===")
                self.logger.info(f"Update object type: {type(update_obj).__name__}")
                
                # Log update-level attributes first
                if hasattr(update_obj, '__dict__'):
                    update_attrs = {k: v for k, v in update_obj.__dict__.items() 
                                  if not k.startswith('_') and k not in ['algebra', 'request']}
                    if update_attrs:
                        self.logger.info("Update attributes:")
                        for key, value in update_attrs.items():
                            self.logger.info(f"  {key}: {self._format_value(value)}")
                
                # Access the actual algebra from the Update object
                if hasattr(update_obj, 'algebra'):
                    self._walk_algebra_tree(update_obj.algebra)
                elif hasattr(update_obj, 'request'):
                    # Updates might have a 'request' attribute containing the operations
                    self._walk_algebra_tree(update_obj.request)
                else:
                    # Fallback: try to extract algebra from the update object
                    self.logger.info(f"No direct 'algebra' or 'request' attribute found in {type(update_obj).__name__}")
                    self.logger.info("Available attributes:")
                    if hasattr(update_obj, '__dict__'):
                        for key, value in update_obj.__dict__.items():
                            if not key.startswith('_'):
                                self.logger.info(f"  {key}: {type(value).__name__}")
                                if 'request' in key.lower() or 'operation' in key.lower() or 'algebra' in key.lower():
                                    self.logger.info(f"  Found potential operations in '{key}':")
                                    self._walk_algebra_tree(value)
            else:
                self.logger.info(f"Algebra translation not available for {query_type}")
                if query_type.lower() == "query" and not translateQuery:
                    self.logger.info("  translateQuery function not imported")
                elif query_type.lower() == "update" and not translateUpdate:
                    self.logger.info("  translateUpdate function not imported")
                
        except Exception as e:
            self.logger.warning(f"Could not generate algebra tree: {e}")
            self.logger.debug(f"Algebra tree error details: {traceback.format_exc()}")
    
    def _walk_algebra_tree(self, node: Any) -> None:
        """
        Walk the SPARQL algebra tree using RDFLib's traverse function and log it as a single formatted string.
        """
        try:
            lines = []
            
            def visit_node(n):
                """Visitor function for RDFLib's traverse - collects node information"""
                self._collect_node_info(n, lines, 0)
                return None  # Don't modify the tree
            
            # Use RDFLib's built-in traverse function
            traverse(node, visitPre=visit_node)
            
            # Join all lines into a single string and log it
            if lines:
                tree_output = "\n".join(lines)
                self.logger.info(tree_output)
            else:
                self.logger.info("<empty algebra tree>")
                
        except Exception as e:
            self.logger.warning(f"Error walking algebra tree: {e}")
            self.logger.debug(f"Tree walking error details: {traceback.format_exc()}")
    
    def _log_algebra_statistics(self, algebra_node: Any) -> None:
        """Log statistics about the algebra tree structure.
        
        Args:
            algebra_node: Root node of the algebra tree
        """
        try:
            stats = self._collect_algebra_statistics(algebra_node)
            
            # Build statistics as a single formatted string
            stats_lines = []
            stats_lines.append(f"Total nodes: {stats['total_nodes']}")
            stats_lines.append(f"Max depth: {stats['max_depth']}")
            
            if stats['node_types']:
                stats_lines.append("Node type distribution:")
                for node_type, count in sorted(stats['node_types'].items()):
                    stats_lines.append(f"  {node_type}: {count}")
            
            if stats['operations']:
                stats_lines.append("SPARQL operations found:")
                for op in sorted(stats['operations']):
                    stats_lines.append(f"  - {op}")
            
            # Log as single entry with newlines
            stats_string = "\n" + "\n".join(stats_lines) + "\n"
            self.logger.info(f"Algebra tree statistics:{stats_string}")
                    
        except Exception as e:
            self.logger.debug(f"Could not collect algebra statistics: {e}")
    
    def _collect_algebra_statistics(self, node: Any, depth: int = 0) -> dict:
        """Recursively collect statistics about the algebra tree.
        
        Args:
            node: Current node to analyze
            depth: Current depth in the tree
            
        Returns:
            Dictionary with statistics
        """
        stats = {
            'total_nodes': 0,
            'max_depth': depth,
            'node_types': {},
            'operations': set()
        }
        
        try:
            stats['total_nodes'] = 1
            node_type = type(node).__name__
            stats['node_types'][node_type] = 1
            
            # Check for SPARQL operation names
            if hasattr(node, 'name'):
                operation_name = getattr(node, 'name', '')
                if operation_name:
                    stats['operations'].add(operation_name)
            
            # Recursively process child nodes
            if hasattr(node, '__dict__'):
                for key, value in node.__dict__.items():
                    if not key.startswith('_'):
                        if self._is_algebra_node(value):
                            child_stats = self._collect_algebra_statistics(value, depth + 1)
                            self._merge_statistics(stats, child_stats)
                        elif isinstance(value, (list, tuple)):
                            for item in value:
                                if self._is_algebra_node(item):
                                    child_stats = self._collect_algebra_statistics(item, depth + 1)
                                    self._merge_statistics(stats, child_stats)
                                    
        except Exception as e:
            # Don't let statistics collection break the main logging
            pass
            
        return stats
    
    def _merge_statistics(self, main_stats: dict, child_stats: dict) -> None:
        """Merge child statistics into main statistics.
        
        Args:
            main_stats: Main statistics dictionary to update
            child_stats: Child statistics to merge in
        """
        main_stats['total_nodes'] += child_stats['total_nodes']
        main_stats['max_depth'] = max(main_stats['max_depth'], child_stats['max_depth'])
        
        # Merge node type counts
        for node_type, count in child_stats['node_types'].items():
            main_stats['node_types'][node_type] = main_stats['node_types'].get(node_type, 0) + count
        
        # Merge operations
        main_stats['operations'].update(child_stats['operations'])
    

    
    def _collect_node_info(self, node: Any, lines: list, depth: int) -> None:
        """
        Collect information about a node visited by RDFLib's traverse function.
        This is called for each node in the algebra tree.
        """
        try:
            # Track depth for indentation (traverse visits nodes in order)
            prefix = "  " * depth
            
            # Handle CompValue objects (RDFLib algebra nodes)
            if hasattr(node, 'name') and hasattr(node, '__dict__'):
                node_name = getattr(node, 'name', type(node).__name__)
                lines.append(f"{prefix}├─ {node_name}")
                
                # Get important attributes
                attrs = {k: v for k, v in node.__dict__.items() 
                        if not k.startswith('_') and v is not None and k != 'name'}
                
                # Prioritize key SPARQL algebra attributes
                priority_attrs = ['p', 'expr', 'triples', 'p1', 'p2', 'PV', 'other']
                ordered_attrs = []
                
                # Add priority attributes first
                for attr in priority_attrs:
                    if attr in attrs:
                        ordered_attrs.append((attr, attrs[attr]))
                        
                # Add remaining attributes
                for attr, value in attrs.items():
                    if attr not in priority_attrs:
                        ordered_attrs.append((attr, value))
                
                # Log key attributes (but don't recurse - traverse handles that)
                for i, (key, value) in enumerate(ordered_attrs[:5]):  # Limit to first 5 attributes
                    is_last = (i == len(ordered_attrs) - 1) or (i == 4)
                    connector = "└─" if is_last else "├─"
                    
                    if isinstance(value, (list, tuple)):
                        if key == 'triples' and len(value) <= 3:
                            lines.append(f"{prefix}│  {connector} {key}: [{len(value)} triples]")
                            for j, triple in enumerate(value):
                                if isinstance(triple, (list, tuple)) and len(triple) == 3:
                                    s, p, o = triple
                                    triple_str = f"({self._format_value(s)}, {self._format_value(p)}, {self._format_value(o)})"
                                    lines.append(f"{prefix}│  │  └─ {triple_str}")
                        else:
                            lines.append(f"{prefix}│  {connector} {key}: [{len(value)} items]")
                    elif isinstance(value, set):
                        if len(value) <= 3:
                            var_list = ", ".join(str(v) for v in sorted(value, key=str))
                            lines.append(f"{prefix}│  {connector} {key}: {{{var_list}}}")
                        else:
                            lines.append(f"{prefix}│  {connector} {key}: {{{len(value)} variables}}")
                    elif not self._is_complex_node(value):
                        # Only show simple values here - complex nodes will be visited by traverse
                        formatted_value = self._format_sparql_value(key, value)
                        lines.append(f"{prefix}│  {connector} {key}: {formatted_value}")
                    else:
                        lines.append(f"{prefix}│  {connector} {key}: {type(value).__name__}")
                        
                if len(ordered_attrs) > 5:
                    lines.append(f"{prefix}│  └─ ... ({len(ordered_attrs) - 5} more attributes)")
                    
            elif isinstance(node, (list, tuple)) and node:
                lines.append(f"{prefix}├─ {type(node).__name__}[{len(node)}]")
                # Don't show list contents here - traverse will visit each item
                
            elif isinstance(node, dict) and node:
                lines.append(f"{prefix}├─ Dict[{len(node)}]")
                # Don't show dict contents here - traverse will visit each value
                
            elif not self._is_complex_node(node):
                # Leaf nodes (simple values)
                lines.append(f"{prefix}├─ {type(node).__name__}: {self._format_value(node)}")
                
        except Exception as e:
            lines.append(f"{prefix}├─ <error collecting node info: {e}>")
            self.logger.debug(f"Node collection error: {traceback.format_exc()}")
    
    def _is_complex_node(self, node: Any) -> bool:
        """
        Check if a node is complex (has sub-structure that traverse should handle).
        """
        return (hasattr(node, '__dict__') and 
                any(not k.startswith('_') for k in node.__dict__.keys()) or
                isinstance(node, (list, tuple, dict)) and node)
    
    def _format_value(self, value: Any, max_length: int = 100) -> str:
        """Format a value for logging, truncating if too long."""
        try:
            str_value = str(value)
            if len(str_value) > max_length:
                return str_value[:max_length] + "..."
            return str_value
        except Exception:
            return f"<{type(value).__name__} object>"
    
    def _format_sparql_value(self, key: str, value: Any) -> str:
        """Format SPARQL-specific values with enhanced context.
        
        Args:
            key: The attribute name for context
            value: The value to format
            
        Returns:
            Formatted string representation
        """
        try:
            # Handle common SPARQL algebra attributes with special formatting
            if key.lower() in ['vars', 'variables']:
                if isinstance(value, (list, tuple, set)):
                    var_names = [str(v) for v in value]
                    return f"[{', '.join(var_names)}] ({len(var_names)} variables)"
            
            elif key.lower() in ['triples', 'patterns']:
                if isinstance(value, (list, tuple)):
                    return f"[{len(value)} triple patterns]"
            
            elif key.lower() in ['expr', 'expression']:
                # SPARQL expressions - show type and brief content
                return f"{type(value).__name__}: {self._format_value(value, 50)}"
            
            elif key.lower() in ['graph', 'graphiri']:
                # Graph IRIs
                return f"Graph: {self._format_value(value, 80)}"
            
            elif 'filter' in key.lower():
                # Filter expressions
                return f"Filter: {self._format_value(value, 60)}"
            
            # Default formatting for other values
            return self._format_value(value)
            
        except Exception:
            return f"<{type(value).__name__} object>"
    
    def log_query_execution_context(self, initNs: dict = None, initBindings: dict = None, 
                                   queryGraph: str = None, **kwargs) -> None:
        """Log the execution context for a SPARQL query.
        
        Args:
            initNs: Initial namespace bindings
            initBindings: Initial variable bindings
            queryGraph: Graph to query
            **kwargs: Additional query parameters
        """
        self.logger.info("=== SPARQL QUERY EXECUTION CONTEXT ===")
        
        if initNs:
            self.logger.info("Initial Namespaces:")
            for prefix, uri in initNs.items():
                self.logger.info(f"  {prefix}: {uri}")
        else:
            self.logger.info("Initial Namespaces: None")
        
        if initBindings:
            self.logger.info("Initial Bindings:")
            for var, value in initBindings.items():
                self.logger.info(f"  ?{var}: {value}")
        else:
            self.logger.info("Initial Bindings: None")
        
        self.logger.info(f"Query Graph: {queryGraph}")
        
        if kwargs:
            self.logger.info("Additional Parameters:")
            for key, value in kwargs.items():
                self.logger.info(f"  {key}: {self._format_value(value)}")