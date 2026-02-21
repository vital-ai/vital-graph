"""
Fuseki-PostgreSQL Database Operations Layer

This module implements the database operations layer for the Fuseki-PostgreSQL hybrid backend.
It provides transaction-aware quad operations using the dual-write coordinator to ensure
consistency between Fuseki and PostgreSQL.

Used by KGTypeImpl, ObjectsImpl, and other endpoint implementations for CRUD operations.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple


class FusekiPostgreSQLDbOps:
    """Database operations layer providing transaction-aware quad operations for Fuseki-PostgreSQL backend."""
    
    def __init__(self, space_impl):
        """
        Initialize the database operations layer.
        
        Args:
            space_impl: FusekiPostgreSQLSpaceImpl instance
        """
        self.space_impl = space_impl
        self.dual_write_coordinator = space_impl.dual_write_coordinator
        self.fuseki_manager = space_impl.fuseki_manager
        self.postgresql_impl = space_impl.postgresql_impl
        self.logger = logging.getLogger(f"{__name__}.FusekiPostgreSQLDbOps")
        
        self.logger.info("Initialized FusekiPostgreSQLDbOps with dual-write coordinator")
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[tuple], 
                                 transaction=None, auto_commit: bool = True) -> int:
        """
        Add RDF quads in batch using dual-write coordinator for consistency.
        
        Args:
            space_id: Space identifier
            quads: List of quad tuples (subject, predicate, object, graph)
            transaction: Optional transaction context (for compatibility)
            auto_commit: Whether to auto-commit (ignored, handled by dual-write coordinator)
            
        Returns:
            Number of quads successfully added
        """
        try:
            if not quads:
                self.logger.debug("No quads provided for addition")
                return 0
            
            self.logger.debug(f"Adding {len(quads)} RDF quads to space {space_id} via dual-write")
            try:
                # Bypass SPARQL parser entirely for simple INSERT operations
                # Call dual-write coordinator directly with RDFLib quads
                success = await self.dual_write_coordinator.add_quads(space_id, quads)
                
                if success:
                    self.logger.debug(f"Successfully added {len(quads)} quads via dual-write")
                    return len(quads)
                else:
                    self.logger.error(f"Failed to add quads via dual-write coordinator")
                    return 0
            except Exception as e:
                self.logger.error(f"Error adding RDF quads batch: {e}")
                self.logger.error(f"Failed to add quads via dual-write coordinator")
                return 0
                
        except Exception as e:
            self.logger.error(f"Error adding RDF quads batch: {e}")
            return 0
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple], 
                                   transaction=None, auto_commit: bool = True) -> int:
        """
        Remove RDF quads in batch using dual-write coordinator for consistency.
        
        Args:
            space_id: Space identifier
            quads: List of quad tuples (subject, predicate, object, graph)
            transaction: Optional transaction context (for compatibility)
            auto_commit: Whether to auto-commit (ignored, handled by dual-write coordinator)
            
        Returns:
            Number of quads successfully removed
        """
        try:
            if not quads:
                self.logger.debug("No quads provided for removal")
                return 0
            
            import time
            start_time = time.time()
            self.logger.info(f"🔥 REMOVE_QUADS_BATCH: Removing {len(quads)} RDF quads from space {space_id} via dual-write")
            
            # Bypass SPARQL parser entirely for simple DELETE operations
            # Call dual-write coordinator directly with quads (SAME AS add_rdf_quads_batch!)
            success = await self.dual_write_coordinator.remove_quads(space_id, quads)
            
            elapsed_time = time.time() - start_time
            
            if success:
                self.logger.info(f"🔥 REMOVE_QUADS_BATCH: Successfully removed {len(quads)} quads via dual-write in {elapsed_time:.3f}s")
                return len(quads)
            else:
                self.logger.error(f"🔥 REMOVE_QUADS_BATCH: Failed to remove quads via dual-write coordinator after {elapsed_time:.3f}s")
                return 0
                
        except Exception as e:
            self.logger.error(f"🔥 REMOVE_QUADS_BATCH: Error removing RDF quads batch: {e}")
            return 0
    
    async def remove_quads_by_subject_uris(self, space_id: str, subject_uris: List[str], 
                                         graph_id: Optional[str] = None, 
                                         transaction=None) -> int:
        """
        Remove all quads for specific subject URIs using dual-write coordinator.
        
        Args:
            space_id: Space identifier
            subject_uris: List of subject URIs to remove all quads for
            graph_id: Graph identifier (defaults to "main")
            transaction: Optional transaction context (for compatibility)
            
        Returns:
            Number of subjects successfully removed
        """
        try:
            if not subject_uris:
                self.logger.debug("No subject URIs provided for removal")
                return 0
            
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            self.logger.debug(f"Removing all quads for {len(subject_uris)} subjects in space {space_id}, graph {graph_id}")
            
            # Build graph URI
            from .fuseki_query_utils import FusekiQueryUtils
            graph_uri = FusekiQueryUtils.build_graph_uri(space_id, graph_id)
            
            # Build SPARQL DELETE query for each subject
            delete_operations = []
            for subject_uri in subject_uris:
                delete_operation = f"""
                DELETE {{
                    GRAPH <{graph_uri}> {{
                        <{subject_uri}> ?p ?o .
                    }}
                }}
                WHERE {{
                    GRAPH <{graph_uri}> {{
                        <{subject_uri}> ?p ?o .
                    }}
                }}
                """
                delete_operations.append(delete_operation)
            
            # Execute each delete operation via dual-write coordinator
            successful_removals = 0
            for i, delete_sparql in enumerate(delete_operations):
                try:
                    success = await self.dual_write_coordinator.execute_sparql_update(space_id, delete_sparql)
                    if success:
                        successful_removals += 1
                    else:
                        self.logger.warning(f"Failed to remove subject {subject_uris[i]}")
                except Exception as e:
                    self.logger.error(f"Error removing subject {subject_uris[i]}: {e}")
            
            self.logger.debug(f"Successfully removed {successful_removals}/{len(subject_uris)} subjects")
            return successful_removals
            
        except Exception as e:
            self.logger.error(f"Error removing quads by subject URIs: {e}")
            return 0
    
    async def update_rdf_quads_batch(self, space_id: str, old_quads: List[tuple], 
                                   new_quads: List[tuple], 
                                   transaction=None) -> Tuple[int, int]:
        """
        Update RDF quads by removing old and adding new in a coordinated operation.
        
        Args:
            space_id: Space identifier
            old_quads: List of quad dictionaries to remove
            new_quads: List of quad dictionaries to add
            transaction: Optional transaction context (for compatibility)
            
        Returns:
            Tuple of (removed_count, added_count)
        """
        try:
            self.logger.debug(f"Updating RDF quads: removing {len(old_quads)}, adding {len(new_quads)}")
            
            # Remove old quads first
            removed_count = 0
            if old_quads:
                removed_count = await self.remove_rdf_quads_batch(space_id, old_quads, transaction)
            
            # Add new quads
            added_count = 0
            if new_quads:
                added_count = await self.add_rdf_quads_batch(space_id, new_quads, transaction)
            
            self.logger.debug(f"Update complete: removed {removed_count}, added {added_count}")
            return removed_count, added_count
            
        except Exception as e:
            self.logger.error(f"Error updating RDF quads batch: {e}")
            return 0, 0
    
    def _format_sparql_term(self, term: str) -> str:
        """
        Format an RDF term for SPARQL based on its type.
        
        Args:
            term: RDF term string
            
        Returns:
            Formatted term for SPARQL query
        """
        if term is None:
            return '""'
        
        # Check if it's a URI (starts with http:// or https:// or urn:)
        if str(term).startswith(('http://', 'https://', 'urn:')):
            return f'<{term}>'
        
        # Check if it's already a properly formatted URI in angle brackets
        if str(term).startswith('<') and str(term).endswith('>'):
            return term
        
        # Check if it's a blank node
        if str(term).startswith('_:'):
            return term
        
        # Check if it's a number (integer or decimal)
        try:
            if '.' in term:
                float(term)
                return term  # Decimal literal
            else:
                int(term)
                return term  # Integer literal
        except ValueError:
            pass
        
        # Check if it's already a quoted string literal
        if (term.startswith('"') and term.endswith('"')) or (term.startswith("'") and term.endswith("'")):
            return term
        
        # Default: treat as string literal and escape quotes
        escaped_term = term.replace('"', '\\"')
        return f'"{escaped_term}"'
    
    async def get_quad_count(self, space_id: str, graph_id: Optional[str] = None) -> int:
        """
        Get count of quads in a space/graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (defaults to "main")
            
        Returns:
            Number of quads in the space/graph
        """
        try:
            # Default to main graph if not specified
            if graph_id is None:
                graph_id = "main"
            
            # Use existing space implementation method
            from .fuseki_query_utils import FusekiQueryUtils
            graph_uri = FusekiQueryUtils.build_graph_uri(space_id, graph_id)
            
            # Delegate to space implementation
            count = await self.space_impl.get_quad_count(space_id, graph_uri)
            
            self.logger.debug(f"Quad count for space {space_id}, graph {graph_id}: {count}")
            return count
            
        except Exception as e:
            self.logger.error(f"Error getting quad count: {e}")
            return 0
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """
        Execute a SPARQL UPDATE query via dual-write coordinator.
        
        Args:
            space_id: Space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.debug(f"Executing SPARQL UPDATE in space {space_id}")
            self.logger.debug(f"SPARQL UPDATE: {sparql_update}")
            
            success = await self.dual_write_coordinator.execute_sparql_update(space_id, sparql_update)
            
            if success:
                self.logger.debug("SPARQL UPDATE executed successfully via dual-write")
            else:
                self.logger.error("SPARQL UPDATE failed via dual-write coordinator")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL UPDATE: {e}")
            return False
    
    async def execute_sparql_query(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL SELECT query (reads from Fuseki).
        
        Args:
            space_id: Space identifier
            sparql_query: SPARQL SELECT query string
            
        Returns:
            List of binding dictionaries
        """
        try:
            self.logger.debug(f"Executing SPARQL SELECT in space {space_id}")
            self.logger.debug(f"SPARQL SELECT: {sparql_query}")
            
            bindings = await self.fuseki_manager.query_dataset(space_id, sparql_query)
            
            self.logger.debug(f"SPARQL SELECT returned {len(bindings)} results")
            return bindings
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL SELECT: {e}")
            return []
