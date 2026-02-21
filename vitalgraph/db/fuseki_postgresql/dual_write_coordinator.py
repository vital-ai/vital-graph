"""
Dual-write coordinator for FUSEKI_POSTGRESQL hybrid backend.
Synchronizes write operations between Fuseki datasets and PostgreSQL primary data tables.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
import uuid
from datetime import datetime

from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986

from .fuseki_dataset_manager import FusekiDatasetManager
from .postgresql_db_impl import FusekiPostgreSQLDbImpl
from .sparql_update_parser import SPARQLUpdateParser
from .edge_materialization import EdgeMaterializationManager

logger = logging.getLogger(__name__)


class DualWriteResult:
    """Result of a dual-write operation. Truthy when success=True, carries fuseki_success status."""
    
    def __init__(self, success: bool, fuseki_success: bool = True, message: str = ""):
        self.success = success
        self.fuseki_success = fuseki_success
        self.message = message
    
    def __bool__(self):
        return self.success
    
    def __repr__(self):
        return f"DualWriteResult(success={self.success}, fuseki_success={self.fuseki_success}, message='{self.message}')"


class DualWriteCoordinator:
    """
    Coordinates dual-write operations between Fuseki and PostgreSQL.
    
    Ensures that all graph data changes are written to both:
    1. Fuseki datasets (index/cache, for fast queries)
    2. PostgreSQL primary data tables (authoritative storage)
    
    Implements rollback mechanisms to maintain consistency.
    """
    
    def __init__(self, fuseki_manager: FusekiDatasetManager, postgresql_impl: FusekiPostgreSQLDbImpl):
        """
        Initialize dual-write coordinator.
        
        Args:
            fuseki_manager: Fuseki dataset manager instance
            postgresql_impl: PostgreSQL database implementation instance
        """
        self.fuseki_manager = fuseki_manager
        self.postgresql_impl = postgresql_impl
        self.sparql_parser = SPARQLUpdateParser(fuseki_manager)
        self.graph_manager = None  # Lazy-loaded graph manager
        self.materialization_manager = EdgeMaterializationManager(fuseki_manager)
        
        logger.info("DualWriteCoordinator initialized with edge materialization support")
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str, original_quads: List[tuple] = None) -> bool:
        """
        Execute SPARQL UPDATE with dual-write coordination.
        Automatically registers graphs in the graph table before data operations.
        
        Parses SPARQL UPDATE, applies changes to PostgreSQL primary storage first,
        then updates Fuseki query index.
        
        Args:
            space_id: Target space identifier
            sparql_update: SPARQL UPDATE query string
            
        Returns:
            True if both operations succeeded, False otherwise
        """
        try:
            import time
            logger.info(f"🔥 DUAL_WRITE: Executing SPARQL UPDATE for space {space_id}: {sparql_update[:100]}...")
            
            # Step 1: Parse SPARQL UPDATE to determine affected triples
            parse_start = time.time()
            logger.info(f"🔥 DUAL_WRITE: Calling sparql_parser.parse_update_operation()...")
            parsed_operation = await self.sparql_parser.parse_update_operation(space_id, sparql_update)
            parse_time = time.time() - parse_start
            logger.info(f"🔥 DUAL_WRITE: SPARQL parsing completed in {parse_time:.3f}s")
            logger.debug(f" Parsed operation: {parsed_operation}")
            
            if 'error' in parsed_operation:
                logger.error(f"SPARQL UPDATE parsing failed: {parsed_operation['error']}")
                return False
            
            # Step 1.5: Auto-register graphs from INSERT operations BEFORE data operations
            insert_triples = parsed_operation.get('insert_triples', [])
            if insert_triples:
                graph_uris = self._extract_graph_uris_from_quads(insert_triples)
                if graph_uris:
                    logger.debug(f"Auto-registering {len(graph_uris)} graph(s) from SPARQL UPDATE: {graph_uris}")
                    for graph_uri in graph_uris:
                        await self._ensure_graph_registered(space_id, graph_uri)
            
            # Step 2: Execute dual-write operation with correct transaction ordering
            result = await self._execute_parsed_update(space_id, parsed_operation, original_quads)
            logger.debug(f" Dual-write result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error executing SPARQL UPDATE for space {space_id}: {e}")
            return False
    
    async def _execute_parsed_update(self, space_id: str, parsed_operation: Dict[str, Any], original_quads: List[tuple] = None) -> bool:
        """
        Execute dual-write operation from parsed SPARQL UPDATE.
        
        Transaction order: PostgreSQL primary storage first, then Fuseki query index.
        PostgreSQL failure causes entire operation to fail.
        
        Args:
            space_id: Target space
            parsed_operation: Result from SPARQLUpdateParser.parse_update_operation()
        """
        
        operation_type = parsed_operation['operation_type']
        
        # Fail explicitly if operation type is unknown (parser failed)
        if operation_type == 'unknown':
            logger.error(f"❌ Cannot execute SPARQL UPDATE: parser failed to identify operation type")
            logger.error(f"❌ This indicates malformed SPARQL - check that literals are properly quoted")
            return False
        
        # Fail if DELETE WHERE syntax is used (not supported)
        if operation_type == 'delete_where':
            logger.error(f"❌ Cannot execute SPARQL DELETE: DELETE WHERE syntax is not supported")
            logger.error(f"❌ Use DELETE {{ ... }} WHERE {{ ... }} instead")
            return False
        
        try:
            # Step 1: Begin PostgreSQL transaction and apply primary storage changes FIRST
            # PostgreSQL is the authoritative permanent store
            pg_transaction = await self.postgresql_impl.begin_transaction()
            
            # Apply PostgreSQL storage changes within transaction (primary store)
            if operation_type in ['delete', 'delete_insert', 'delete_data']:
                # Remove deleted triples from PostgreSQL
                # Filter out materialized triples before PostgreSQL deletion
                delete_triples = parsed_operation['delete_triples']
                filtered_delete_triples, filtered_count = self.materialization_manager.filter_materialized_triples(delete_triples)
                if filtered_count > 0:
                    logger.debug(f"Filtered {filtered_count} materialized triples from DELETE operation (only deleted from Fuseki)")
                
                logger.debug(f"🗑️ Processing {len(filtered_delete_triples)} DELETE triples for PostgreSQL (filtered from {len(delete_triples)} total)")
                
                if filtered_delete_triples:
                    delete_success = await self._store_delete_triples(
                        space_id, filtered_delete_triples, pg_transaction
                    )
                    logger.debug(f"🎯 DELETE operation result: {delete_success}")
                    if not delete_success:
                        await self.postgresql_impl.rollback_transaction(pg_transaction)
                        return False
                else:
                    logger.debug("All DELETE triples were materialized - skipping PostgreSQL deletion")
            
            # Pattern-based operations are now resolved to concrete triples by the SPARQL parser
            # so they will be handled by the regular delete/insert logic above
            
            if operation_type in ['insert', 'delete_insert', 'insert_data', 'insert_delete_pattern']:
                # Add inserted triples using proper dual-write (both PostgreSQL and Fuseki)
                logger.debug(f"📝 Processing {len(parsed_operation['insert_triples'])} INSERT triples for dual-write")
                insert_success = await self._store_quads_to_postgresql(
                    space_id, parsed_operation['insert_triples'], pg_transaction
                )
                logger.debug(f"🎯 INSERT operation result: {insert_success}")
                if not insert_success:
                    await self.postgresql_impl.rollback_transaction(pg_transaction)
                    return False
            
            # Step 2: Commit PostgreSQL transaction BEFORE Fuseki operation
            # PostgreSQL is authoritative - must succeed for operation to proceed
            logger.debug("💾 Committing PostgreSQL transaction...")
            commit_success = await self.postgresql_impl.commit_transaction(pg_transaction)
            logger.debug(f"🎯 PostgreSQL commit result: {commit_success}")
            
            if not commit_success:
                logger.error("❌ PostgreSQL primary storage failed - aborting operation")
                return False
            
            # Step 3: Update Fuseki dataset AFTER PostgreSQL success
            # For INSERT operations, use original RDFLib quads if available, otherwise use parsed quads
            fuseki_success = True
            if operation_type in ['insert', 'delete_insert', 'insert_data', 'insert_delete_pattern']:
                quads_for_fuseki = original_quads if original_quads else parsed_operation['insert_triples']
                if quads_for_fuseki:
                    logger.debug(f"📝 Adding {len(quads_for_fuseki)} triples to Fuseki dataset (using {'original RDFLib' if original_quads else 'parsed'} quads)")
                    fuseki_success = await self.fuseki_manager.add_quads_to_dataset(
                        space_id, quads_for_fuseki, convert_float_to_decimal=True
                    )
            
            # For DELETE operations, execute the SPARQL UPDATE on Fuseki
            if operation_type in ['delete', 'delete_insert', 'delete_data']:
                if parsed_operation['delete_triples']:
                    logger.debug(f"📝 Executing DELETE on Fuseki dataset")
                    fuseki_success = await self._execute_fuseki_update(space_id, parsed_operation['raw_update'])
            
            # For DROP GRAPH operations, execute directly on Fuseki (PostgreSQL graph table handled separately)
            if operation_type in ['drop_graph', 'clear_graph']:
                logger.debug(f"📝 Executing {operation_type.upper()} on Fuseki dataset")
                fuseki_success = await self._execute_fuseki_update(space_id, parsed_operation['raw_update'])
            
            if not fuseki_success:
                logger.error(f"FUSEKI_SYNC_FAILURE: Fuseki {operation_type} failed for space {space_id} - data stored in PostgreSQL but Fuseki may be inconsistent")
                # Don't rollback PostgreSQL - it's the authoritative store
            
            # Step 4: Materialize direct edge properties in Fuseki (after successful update)
            if fuseki_success:
                await self._materialize_edge_properties(
                    space_id,
                    parsed_operation.get('insert_triples', []),
                    parsed_operation.get('delete_triples', [])
                )
            
            logger.debug(f"SPARQL UPDATE dual-write successful for space {space_id}")
            return DualWriteResult(
                success=True,
                fuseki_success=fuseki_success,
                message="" if fuseki_success else f"FUSEKI_SYNC_FAILURE: Fuseki {operation_type} failed for space {space_id}"
            )
            
        except Exception as e:
            logger.error(f"Error in dual-write operation for space {space_id}: {e}")
            
            # Rollback PostgreSQL if transaction exists
            if 'pg_transaction' in locals():
                await self.postgresql_impl.rollback_transaction(pg_transaction)
            
            return False
    
    async def add_quads(self, space_id: str, quads: List[tuple], 
                       transaction: 'FusekiPostgreSQLTransaction' = None) -> bool:
        """
        Add RDF quads to both Fuseki dataset and PostgreSQL primary data tables.
        Automatically registers graphs in the graph table before data operations.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to add
            transaction: Optional transaction object. If provided, caller manages transaction.
                        If None, this method creates and manages its own transaction.
            
        Returns:
            True if both writes succeeded, False otherwise
        """
        if not quads:
            return True
        
        logger.debug(f"🔍 DUAL-WRITE: Adding {len(quads)} quads to space {space_id}")
        logger.debug(f"🔍 First quad sample: {quads[0] if quads else 'None'}")
        
        # Step 0: Auto-register graphs BEFORE data operations
        graph_uris = self._extract_graph_uris_from_quads(quads)
        if graph_uris:
            logger.debug(f"Auto-registering {len(graph_uris)} graph(s): {graph_uris}")
            for graph_uri in graph_uris:
                await self._ensure_graph_registered(space_id, graph_uri)
        
        # Determine transaction ownership
        if transaction:
            # Caller manages transaction
            pg_transaction = transaction
            should_commit = False
            logger.debug(f"🔍 Using caller-provided transaction")
        else:
            # We manage transaction
            pg_transaction = None
            should_commit = True
        
        fuseki_success = False
        
        try:
            # Step 1: Begin PostgreSQL transaction if we're managing it
            if should_commit:
                logger.debug(f"🔍 Starting PostgreSQL transaction...")
                pg_transaction = await self.postgresql_impl.begin_transaction()
                logger.debug(f"🔍 PostgreSQL transaction started: {pg_transaction}")
            
            # Filter out materialized triples before PostgreSQL write
            filtered_quads, filtered_count = self.materialization_manager.filter_materialized_triples(quads)
            if filtered_count > 0:
                logger.debug(f"Filtered {filtered_count} materialized triples from add_quads (will only exist in Fuseki)")
            
            # If all quads were materialized, skip PostgreSQL but continue to Fuseki
            if not filtered_quads:
                logger.debug("All quads were materialized - skipping PostgreSQL write, will write to Fuseki only")
                pg_success = True  # Consider this successful
            else:
                # Write to PostgreSQL primary data tables (authoritative storage, done first)
                logger.debug(f"🔍 Writing {len(filtered_quads)} quads to PostgreSQL primary data tables...")
                pg_success = await self._store_quads_to_postgresql(space_id, filtered_quads, pg_transaction)
            
            if not pg_success:
                logger.error(f"PostgreSQL primary data write failed for space {space_id}")
                if should_commit:
                    await self.postgresql_impl.rollback_transaction(pg_transaction)
                return False
            
            # Step 2: Commit PostgreSQL transaction if we're managing it
            if should_commit:
                commit_success = await self.postgresql_impl.commit_transaction(pg_transaction)
                
                if not commit_success:
                    logger.error(f"PostgreSQL commit failed for space {space_id}")
                    return False
            
            # Step 3: Write to Fuseki dataset AFTER PostgreSQL success (only if we committed)
            # If caller manages transaction, they'll sync Fuseki after their commit
            if should_commit:
                fuseki_success = await self.fuseki_manager.add_quads_to_dataset(space_id, quads, convert_float_to_decimal=True)
            
            if should_commit and not fuseki_success:
                logger.error(f"FUSEKI_SYNC_FAILURE: Fuseki add_quads failed for space {space_id} - data stored in PostgreSQL but Fuseki may be inconsistent")
                # Rollback PostgreSQL by removing the quads we just added
                # await self._rollback_postgresql_quads(space_id, filtered_quads)
                # return False
                # Don't rollback PostgreSQL - it's the authoritative store
            
            # Step 4: Materialize direct edge properties in Fuseki (after successful write)
            if should_commit and fuseki_success:
                await self._materialize_edge_properties(space_id, quads, [])
            
            logger.debug(f"Dual-write completed: {len(quads)} quads added to space {space_id} (fuseki_success={fuseki_success})")
            return DualWriteResult(
                success=True,
                fuseki_success=fuseki_success,
                message="" if fuseki_success else f"FUSEKI_SYNC_FAILURE: Fuseki add_quads failed for space {space_id}"
            )
            
        except Exception as e:
            logger.error(f"Error in dual-write operation for space {space_id}: {e}")
            
            # Rollback PostgreSQL if we're managing the transaction
            if should_commit and pg_transaction:
                await self.postgresql_impl.rollback_transaction(pg_transaction)
            
            return False
    
    async def remove_quads(self, space_id: str, quads: List[tuple],
                          transaction: 'FusekiPostgreSQLTransaction' = None) -> bool:
        """
        Remove RDF quads from both Fuseki dataset and PostgreSQL primary data tables.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to remove
            transaction: Optional transaction object. If provided, caller manages transaction.
                        If None, this method creates and manages its own transaction.
            
        Returns:
            True if both operations succeeded, False otherwise
        """
        if not quads:
            return True
        
        import time
        overall_start = time.time()
        logger.info(f"🔥 REMOVE_QUADS: Starting removal of {len(quads)} quads from space {space_id}")
        
        # Determine transaction ownership
        if transaction:
            # Caller manages transaction
            pg_transaction = transaction
            should_commit = False
            logger.debug(f"🔥 REMOVE_QUADS: Using caller-provided transaction")
        else:
            # We manage transaction
            pg_transaction = None
            should_commit = True
            logger.debug(f"🔥 REMOVE_QUADS: Will manage own transaction")
        
        try:
            # Step 1: Begin PostgreSQL transaction if we're managing it
            if should_commit:
                tx_start = time.time()
                pg_transaction = await self.postgresql_impl.begin_transaction()
                tx_begin_time = time.time() - tx_start
                logger.info(f"🔥 REMOVE_QUADS: PostgreSQL transaction started in {tx_begin_time:.3f}s")
            
            # Step 2: Remove from PostgreSQL primary data tables FIRST (authoritative store)
            # Filter out materialized triples before PostgreSQL deletion
            filter_start = time.time()
            filtered_quads, filtered_count = self.materialization_manager.filter_materialized_triples(quads)
            filter_time = time.time() - filter_start
            if filtered_count > 0:
                logger.info(f"🔥 REMOVE_QUADS: Filtered {filtered_count} materialized triples in {filter_time:.3f}s (only deleted from Fuseki)")
            
            # If all quads were materialized, skip PostgreSQL
            if not filtered_quads:
                logger.info(f"🔥 REMOVE_QUADS: All quads were materialized - skipping PostgreSQL deletion")
                pg_success = True
            else:
                pg_delete_start = time.time()
                logger.info(f"🔥 REMOVE_QUADS: Removing {len(filtered_quads)} quads from PostgreSQL...")
                pg_success = await self._remove_quads_from_postgresql(space_id, filtered_quads, pg_transaction)
                pg_delete_time = time.time() - pg_delete_start
                logger.info(f"🔥 REMOVE_QUADS: PostgreSQL delete completed in {pg_delete_time:.3f}s (success={pg_success})")
            
            if not pg_success:
                logger.error(f"🔥 REMOVE_QUADS: PostgreSQL primary data removal failed for space {space_id}")
                if should_commit:
                    await self.postgresql_impl.rollback_transaction(pg_transaction)
                return False
            
            # Step 3: Commit PostgreSQL transaction BEFORE Fuseki operation
            # PostgreSQL is authoritative - must succeed for operation to proceed
            if should_commit:
                commit_start = time.time()
                logger.info(f"🔥 REMOVE_QUADS: Committing PostgreSQL transaction...")
                commit_success = await self.postgresql_impl.commit_transaction(pg_transaction)
                commit_time = time.time() - commit_start
                logger.info(f"🔥 REMOVE_QUADS: PostgreSQL transaction committed in {commit_time:.3f}s (success={commit_success})")
                
                if not commit_success:
                    logger.error(f"❌ REMOVE_QUADS: PostgreSQL primary storage commit failed - aborting operation")
                    return False
            
            # Step 4: Remove from Fuseki dataset AFTER PostgreSQL success
            fuseki_success = True
            if should_commit:
                fuseki_start = time.time()
                logger.info(f"🔥 REMOVE_QUADS: Calling _remove_quads_from_fuseki()...")
                fuseki_success = await self._remove_quads_from_fuseki(space_id, quads)
                fuseki_time = time.time() - fuseki_start
                logger.info(f"🔥 REMOVE_QUADS: Fuseki delete completed in {fuseki_time:.3f}s (success={fuseki_success})")
            
            if not fuseki_success:
                logger.error(f"FUSEKI_SYNC_FAILURE: Fuseki remove_quads failed for space {space_id} - data removed from PostgreSQL but Fuseki may be inconsistent")
                # Don't rollback PostgreSQL - it's the authoritative store
            
            # Step 5: Remove materialized direct edge properties from Fuseki (after successful removal)
            if should_commit and fuseki_success:
                await self._materialize_edge_properties(space_id, [], quads)
            
            overall_time = time.time() - overall_start
            logger.info(f"🔥 REMOVE_QUADS: Dual-write removal completed: {len(quads)} quads removed in {overall_time:.3f}s total (fuseki_success={fuseki_success})")
            return DualWriteResult(
                success=True,
                fuseki_success=fuseki_success,
                message="" if fuseki_success else f"FUSEKI_SYNC_FAILURE: Fuseki remove_quads failed for space {space_id}"
            )
            
        except Exception as e:
            overall_time = time.time() - overall_start
            logger.error(f"🔥 REMOVE_QUADS: Error in dual-write removal after {overall_time:.3f}s: {e}")
            
            # Rollback PostgreSQL if we're managing the transaction
            if should_commit and pg_transaction:
                await self.postgresql_impl.rollback_transaction(pg_transaction)
            
            return False
    
    async def update_quads(self, space_id: str,
                          delete_quads: List[tuple], insert_quads: List[tuple]) -> bool:
        """
        Atomically delete and insert quads using a single PostgreSQL transaction.
        
        Both operations share one transaction so orphan-cleanup from the delete
        is never visible to concurrent requests until the insert also completes.
        Fuseki operations happen after the PG commit.
        
        Args:
            space_id: Space identifier
            delete_quads: Quads to remove
            insert_quads: Quads to add
            
        Returns:
            True if PostgreSQL operations succeeded, False otherwise
        """
        import time
        overall_start = time.time()
        logger.info(f"🔄 UPDATE_QUADS: delete={len(delete_quads)}, insert={len(insert_quads)} for space {space_id}")
        
        pg_transaction = None
        try:
            # Single PG transaction for both delete and insert
            pg_transaction = await self.postgresql_impl.begin_transaction()
            
            # --- PostgreSQL DELETE (filtered) ---
            if delete_quads:
                del_filtered, del_filtered_count = self.materialization_manager.filter_materialized_triples(delete_quads)
                if del_filtered_count > 0:
                    logger.debug(f"🔄 UPDATE_QUADS: Filtered {del_filtered_count} materialized triples from DELETE")
                if del_filtered:
                    pg_del_ok = await self._remove_quads_from_postgresql(
                        space_id, del_filtered, pg_transaction, skip_orphan_cleanup=True)
                    if not pg_del_ok:
                        raise Exception("PostgreSQL DELETE failed")
            
            # --- PostgreSQL INSERT (filtered) ---
            if insert_quads:
                ins_filtered, ins_filtered_count = self.materialization_manager.filter_materialized_triples(insert_quads)
                if ins_filtered_count > 0:
                    logger.debug(f"🔄 UPDATE_QUADS: Filtered {ins_filtered_count} materialized triples from INSERT")
                
                # Auto-register graphs
                graph_uris = self._extract_graph_uris_from_quads(insert_quads)
                if graph_uris:
                    for graph_uri in graph_uris:
                        await self._ensure_graph_registered(space_id, graph_uri)
                
                if ins_filtered:
                    pg_ins_ok = await self._store_quads_to_postgresql(space_id, ins_filtered, pg_transaction)
                    if not pg_ins_ok:
                        raise Exception("PostgreSQL INSERT failed")
            
            # Commit after both PG operations succeed
            commit_ok = await self.postgresql_impl.commit_transaction(pg_transaction)
            pg_transaction = None
            if not commit_ok:
                raise Exception("PostgreSQL COMMIT failed")
            
            pg_time = time.time() - overall_start
            logger.info(f"🔄 UPDATE_QUADS: PG committed in {pg_time:.3f}s")
            
        except Exception as e:
            logger.error(f"🔄 UPDATE_QUADS: PG failed: {e}")
            if pg_transaction:
                try:
                    await self.postgresql_impl.rollback_transaction(pg_transaction)
                except Exception as rb_err:
                    logger.error(f"🔄 UPDATE_QUADS: Rollback failed: {rb_err}")
            return False
        
        # --- Fuseki operations (after PG commit, outside PG error handling) ---
        # Combine DELETE DATA + INSERT DATA into a single atomic SPARQL UPDATE
        # to prevent concurrent reads from seeing intermediate state (value deleted
        # but not yet re-inserted).
        fuseki_success = True
        try:
            combined_parts = []
            
            if delete_quads:
                delete_body = self._build_delete_data_body(delete_quads)
                if delete_body:
                    combined_parts.append(f"DELETE DATA {{\n{delete_body}\n}}")
            
            if insert_quads:
                insert_body = self.fuseki_manager._quads_to_sparql_insert_data(
                    insert_quads, convert_float_to_decimal=True)
                if insert_body:
                    formatted = insert_body.strip()
                    combined_parts.append(f"INSERT DATA {{\n{formatted}\n}}")
            
            if combined_parts:
                combined_query = " ;\n".join(combined_parts)
                logger.info(f"\U0001f504 UPDATE_QUADS: Sending atomic Fuseki update "
                            f"({len(combined_parts)} part(s), {len(combined_query)} chars)")
                result = await self.fuseki_manager.update_dataset(space_id, combined_query)
                if not result:
                    logger.error(f"FUSEKI_SYNC_FAILURE: Atomic Fuseki update failed for space {space_id}")
                    fuseki_success = False
            
            if fuseki_success:
                await self._materialize_edge_properties(space_id, insert_quads, delete_quads)
        except Exception as e:
            logger.error(f"FUSEKI_SYNC_FAILURE: Fuseki operation raised exception: {e}")
            fuseki_success = False
        
        overall_time = time.time() - overall_start
        logger.info(f"🔄 UPDATE_QUADS: Completed in {overall_time:.3f}s (fuseki_success={fuseki_success})")
        return DualWriteResult(
            success=True,
            fuseki_success=fuseki_success,
            message="" if fuseki_success else "FUSEKI_SYNC_FAILURE"
        )

    async def create_space_storage(self, space_id: str) -> bool:
        """
        Create storage for a new space in both Fuseki and PostgreSQL.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if both storage systems created successfully, False otherwise
        """
        logger.info(f"Creating dual storage for space: {space_id}")
        
        fuseki_success = False
        postgresql_success = False
        
        try:
            # Step 1: Create Fuseki dataset
            fuseki_success = await self.fuseki_manager.create_dataset(space_id)
            
            if not fuseki_success:
                logger.error(f"Failed to create Fuseki dataset for space {space_id}")
                return False
            
            # Step 2: Create PostgreSQL primary data tables
            postgresql_success = await self.postgresql_impl.create_space_data_tables(space_id)
            
            if not postgresql_success:
                logger.error(f"Failed to create PostgreSQL primary data tables for space {space_id}")
                # Rollback: Delete Fuseki dataset
                await self.fuseki_manager.delete_dataset(space_id)
                return False
            
            logger.info(f"Dual storage created successfully for space: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating dual storage for space {space_id}: {e}")
            
            # Cleanup on failure
            if fuseki_success:
                await self.fuseki_manager.delete_dataset(space_id)
            if postgresql_success:
                await self.postgresql_impl.drop_space_data_tables(space_id)
            
            return False
    
    async def delete_space_storage(self, space_id: str) -> bool:
        """
        Delete storage for a space from both Fuseki and PostgreSQL.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if both deletions succeeded, False otherwise
        """
        logger.info(f"Deleting dual storage for space: {space_id}")
        
        fuseki_success = False
        postgresql_success = False
        
        try:
            # Step 1: Delete Fuseki dataset
            fuseki_success = await self.fuseki_manager.delete_dataset(space_id)
            
            # Step 2: Delete PostgreSQL primary data tables
            postgresql_success = await self.postgresql_impl.drop_space_data_tables(space_id)
            
            # Consider successful if at least one succeeded
            if fuseki_success or postgresql_success:
                logger.info(f"Dual storage deleted for space: {space_id} (Fuseki: {fuseki_success}, PostgreSQL: {postgresql_success})")
                return True
            else:
                logger.error(f"Failed to delete dual storage for space {space_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting dual storage for space {space_id}: {e}")
            return False
    
    async def verify_consistency(self, space_id: str) -> Dict[str, Any]:
        """
        Verify consistency between Fuseki and PostgreSQL data for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Dictionary with consistency check results
        """
        logger.debug(f"Verifying consistency for space: {space_id}")
        
        try:
            # Get Fuseki dataset info
            fuseki_info = await self.fuseki_manager.get_dataset_info(space_id)
            fuseki_count = fuseki_info.get('triple_count', 0) if fuseki_info else 0
            
            # Get PostgreSQL primary data table info
            postgresql_count = await self.postgresql_impl.count_quads(space_id)
            
            consistency_result = {
                'space_id': space_id,
                'fuseki_triple_count': fuseki_count,
                'postgresql_quad_count': postgresql_count,
                'consistent': fuseki_count == postgresql_count,
                'difference': abs(fuseki_count - postgresql_count)
            }
            
            if not consistency_result['consistent']:
                logger.warning(f"Consistency check failed for space {space_id}: Fuseki={fuseki_count}, PostgreSQL={postgresql_count}")
            
            return consistency_result
            
        except Exception as e:
            logger.error(f"Error verifying consistency for space {space_id}: {e}")
            return {
                'space_id': space_id,
                'error': str(e),
                'consistent': False
            }
    
    # Internal helper methods
    
    async def _store_quads_to_postgresql(self, space_id: str, quads: List[tuple], transaction: Any) -> bool:
        """
        Store RDF quads to PostgreSQL primary data tables within a transaction.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads
            transaction: PostgreSQL transaction context
            
        Returns:
            True if storage succeeded, False otherwise
        """
        try:
            # This is a simplified implementation
            # Full implementation would:
            # 1. Extract unique terms from quads
            # 2. Insert terms into {space_id}_term table
            # 3. Insert quad relationships into {space_id}_rdf_quad table
            # 4. Handle term deduplication and UUID generation
            
            logger.debug(f"Storing {len(quads)} quads to PostgreSQL for space {space_id}")
            
            # Pass RDFLib objects directly - PostgreSQL will extract metadata
            # This preserves datatype and language information from Literal objects
            success = await self.postgresql_impl.store_quads_to_postgresql(space_id, quads, transaction)
            
            if success:
                logger.debug(f"Successfully stored {len(quads)} quads to PostgreSQL for space {space_id}")
            else:
                logger.error(f"Failed to store {len(quads)} quads to PostgreSQL for space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error storing quads to PostgreSQL for space {space_id}: {e}")
            return False
    
    async def _execute_fuseki_update(self, space_id: str, sparql_update: str) -> bool:
        """Execute SPARQL UPDATE on Fuseki dataset."""
        try:
            # Execute the SPARQL UPDATE on the Fuseki dataset
            success = await self.fuseki_manager.update_dataset(space_id, sparql_update)
            
            if success:
                logger.debug(f"Fuseki SPARQL UPDATE successful for space {space_id}")
            else:
                logger.error(f"Fuseki SPARQL UPDATE failed for space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error executing Fuseki UPDATE: {e}")
            return False
    
    async def _store_insert_triples(self, space_id: str, triples: List[tuple], transaction: Any) -> bool:
        """Insert triples into PostgreSQL primary storage within a transaction."""
        try:
            if not triples:
                return True
            
            logger.debug(f"Backing up {len(triples)} INSERT triples for space {space_id}")
            
            # Triples are already in tuple format from SPARQL parser: (subject, predicate, object, graph)
            # Use them directly as quads for PostgreSQL storage
            quads = triples
            
            # Filter out materialized triples - they should NEVER go to PostgreSQL
            filtered_quads, filtered_count = self.materialization_manager.filter_materialized_triples(quads)
            if filtered_count > 0:
                logger.info(f"Filtered {filtered_count} materialized triples from INSERT (will only exist in Fuseki)")
            
            # If all quads were materialized, skip PostgreSQL write (success)
            if not filtered_quads:
                logger.debug("All INSERT triples were materialized - skipping PostgreSQL write")
                return True
            
            # Use PostgreSQL implementation to store quads within the transaction (primary store)
            # Using unified method with batch optimization
            success = await self.postgresql_impl.store_quads_to_postgresql(
                space_id, filtered_quads, transaction
            )
            
            if success:
                logger.debug(f"Successfully stored {len(filtered_quads)} INSERT triples for space {space_id}")
            else:
                logger.error(f"Failed to store INSERT triples for space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error storing INSERT triples: {e}")
            return False
    
    
    async def _store_delete_triples(self, space_id: str, triples: List[tuple], transaction: Any) -> bool:
        """Remove triples from PostgreSQL primary storage within a transaction."""
        try:
            if not triples:
                return True
            
            logger.debug(f"Backing up {len(triples)} DELETE triples for space {space_id}")
            
            # Triples are already in tuple format from SPARQL parser: (subject, predicate, object, graph)
            # Use them directly as quads for PostgreSQL storage
            quads = triples
            # for quad in quads:
            #     logger.info(f"🔍 DELETE quad: {quad}")
            
            # Use PostgreSQL implementation to remove quads within the transaction
            # Using unified method with batch optimization
            logger.debug(f"🔍 Calling remove_quads_from_postgresql with {len(quads)} quads")
            success = await self.postgresql_impl.remove_quads_from_postgresql(
                space_id, quads, transaction
            )
            logger.debug(f"🎯 PostgreSQL remove_quads_from_postgresql result: {success}")
            
            if success:
                logger.debug(f"✅ Successfully removed {len(triples)} DELETE triples from PostgreSQL for space {space_id}")
            else:
                logger.error(f"❌ Failed to remove DELETE triples from PostgreSQL for space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error removing DELETE triples from PostgreSQL: {e}")
            return False
    
    async def _rollback_postgresql_changes(self, space_id: str, parsed_operation: Dict[str, Any]) -> bool:
        """Rollback PostgreSQL changes by applying inverse operations."""
        try:
            operation_type = parsed_operation['operation_type']
            
            logger.warning(f"Rolling back PostgreSQL changes for space {space_id}, operation: {operation_type}")
            
            # Start new transaction for rollback
            pg_transaction = await self.postgresql_impl.begin_transaction()
            
            # Apply inverse operations
            if operation_type in ['insert', 'insert_data']:
                # Rollback INSERT by removing the inserted triples
                success = await self._store_delete_triples(
                    space_id, parsed_operation['insert_triples'], pg_transaction
                )
            elif operation_type in ['delete', 'delete_data']:
                # Rollback DELETE by re-inserting the deleted triples
                success = await self._store_insert_triples(
                    space_id, parsed_operation['delete_triples'], pg_transaction
                )
            elif operation_type == 'delete_insert':
                # Rollback DELETE/INSERT by INSERT/DELETE
                delete_success = await self._store_delete_triples(
                    space_id, parsed_operation['insert_triples'], pg_transaction
                )
                insert_success = await self._store_insert_triples(
                    space_id, parsed_operation['delete_triples'], pg_transaction
                )
                success = delete_success and insert_success
            else:
                success = True
            
            if success:
                await self.postgresql_impl.commit_transaction(pg_transaction)
                logger.info(f"PostgreSQL rollback successful for space {space_id}")
            else:
                await self.postgresql_impl.rollback_transaction(pg_transaction)
                logger.error(f"PostgreSQL rollback failed for space {space_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error rolling back PostgreSQL changes: {e}")
            return False
    
    async def _remove_quads_from_fuseki(self, space_id: str, quads: List[tuple]) -> bool:
        """
        Remove RDF quads from Fuseki dataset using SPARQL DELETE.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to remove
            
        Returns:
            True if removal succeeded, False otherwise
        """
        try:
            import time
            build_start = time.time()
            
            # Group quads by graph for proper DELETE DATA formatting
            graph_quads = {}
            for i, quad in enumerate(quads):
                # Handle tuple format: (subject, predicate, object, graph, [object_type])
                # 5-tuple: includes object_type as 5th element for explicit type info
                # 4-tuple: standard quad, use _format_sparql_term for proper detection
                if len(quad) >= 5:
                    # 5-tuple with explicit type info from delete_entity_graph
                    subject, predicate, obj, graph, obj_type = quad[:5]
                    
                    # Log first few quads to debug formatting issues
                    if i < 3:
                        logger.info(f"🔥 FUSEKI_DELETE: Quad {i}: 5-tuple, obj_type={obj_type}, obj={repr(obj)[:100]}")
                    
                    graph = str(graph)
                    if graph not in graph_quads:
                        graph_quads[graph] = []
                    
                    # Format with explicit type info
                    subject_formatted = f"<{subject}>"
                    predicate_formatted = f"<{predicate}>"
                    
                    if obj_type == 'literal':
                        escaped_obj = str(obj).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                        obj_formatted = f'"{escaped_obj}"'
                    else:
                        obj_formatted = f"<{obj}>"
                    
                    if subject_formatted and predicate_formatted and obj_formatted:
                        graph_quads[graph].append(f"{subject_formatted} {predicate_formatted} {obj_formatted}")
                
                elif len(quad) >= 4:
                    # 4-tuple: standard quad from other sources, use _format_sparql_term
                    subject, predicate, obj, graph = quad[:4]
                    
                    # Log first few quads to debug formatting issues
                    if i < 3:
                        logger.info(f"🔥 FUSEKI_DELETE: Quad {i}: 4-tuple, obj type={type(obj).__name__}, obj={repr(obj)[:100]}")
                    
                    graph = str(graph)
                    if graph not in graph_quads:
                        graph_quads[graph] = []
                    
                    # Use _format_sparql_term for proper type detection - DON'T call str() first
                    # Let _format_sparql_term handle RDFLib objects directly
                    subject_formatted = self._format_sparql_term(subject)
                    predicate_formatted = self._format_sparql_term(predicate)
                    obj_formatted = self._format_sparql_term(obj)
                    
                    # Log first few formatted triples to debug double < issue
                    if i < 3:
                        triple = f"{subject_formatted} {predicate_formatted} {obj_formatted}"
                        logger.info(f"🔥 FUSEKI_DELETE: Formatted triple {i}: {triple[:200]}")
                    
                    if subject_formatted is not None and predicate_formatted is not None and obj_formatted is not None:
                        graph_quads[graph].append(f"{subject_formatted} {predicate_formatted} {obj_formatted}")
                
                else:
                    # 3-tuple: rare case
                    subject, predicate, obj = quad[:3]
                    graph = 'default'
                    
                    if graph not in graph_quads:
                        graph_quads[graph] = []
                    
                    subject_formatted = self._format_sparql_term(str(subject))
                    predicate_formatted = self._format_sparql_term(str(predicate))
                    obj_formatted = self._format_sparql_term(obj)
                    
                    if subject_formatted is not None and predicate_formatted is not None and obj_formatted is not None:
                        graph_quads[graph].append(f"{subject_formatted} {predicate_formatted} {obj_formatted}")
            
            if graph_quads:
                # Build DELETE DATA with proper graph blocks
                graph_blocks = []
                for graph, triples in graph_quads.items():
                    if graph and graph != 'default':
                        graph_formatted = self._format_sparql_term(graph)
                        triples_str = " .\n        ".join(triples)
                        graph_blocks.append(f"GRAPH {graph_formatted} {{\n        {triples_str}\n    }}")
                    else:
                        triples_str = " .\n    ".join(triples)
                        graph_blocks.append(triples_str)
                
                delete_query = f"""DELETE DATA {{
    {"\n    ".join(graph_blocks)}
}}"""
                
                build_time = time.time() - build_start
                logger.info(f"🔥 FUSEKI_DELETE: Built DELETE DATA query for {sum(len(t) for t in graph_quads.values())} triples in {len(graph_quads)} graph(s) in {build_time:.3f}s (query length: {len(delete_query)} chars)")
                logger.info(f"🔥 FUSEKI_DELETE: Query preview (first 5000 chars):\n{delete_query[:5000]}")
                
                # Execute delete query on Fuseki dataset
                exec_start = time.time()
                logger.info(f"🔥 FUSEKI_DELETE: Executing DELETE DATA query on Fuseki...")
                result = await self.fuseki_manager.update_dataset(space_id, delete_query)
                exec_time = time.time() - exec_start
                logger.info(f"🔥 FUSEKI_DELETE: Fuseki DELETE DATA execution completed in {exec_time:.3f}s (success={result})")
                return result
            
            return True
            
        except Exception as e:
            logger.error(f"🔥 FUSEKI_DELETE: Error removing quads from Fuseki for space {space_id}: {e}")
            return False
    
    async def _remove_quads_from_postgresql(self, space_id: str, quads: List[tuple], transaction: Any,
                                              skip_orphan_cleanup: bool = False) -> bool:
        """
        Remove RDF quads from PostgreSQL primary data tables within a transaction.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to remove
            transaction: PostgreSQL transaction context
            skip_orphan_cleanup: If True, skip orphan term cleanup (used by update_quads)
            
        Returns:
            True if removal succeeded, False otherwise
        """
        try:
            # Use PostgreSQL implementation to remove quads
            logger.debug(f"Removing {len(quads)} quads from PostgreSQL primary data for space {space_id}")
            success = await self.postgresql_impl.remove_quads_from_postgresql(
                space_id, quads, transaction, skip_orphan_cleanup=skip_orphan_cleanup)
            return success
            
        except Exception as e:
            logger.error(f"Error removing quads from PostgreSQL for space {space_id}: {e}")
            return False
    
    async def _rollback_postgresql_quads(self, space_id: str, quads: List[tuple]) -> bool:
        """
        Rollback PostgreSQL quads by removing them.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to remove
            
        Returns:
            True if rollback succeeded, False otherwise
        """
        try:
            logger.debug(f"Rolling back PostgreSQL quads for space {space_id}")
            # Use postgresql_impl directly for rollback (no transaction context needed)
            return await self.postgresql_impl.remove_quads_from_postgresql(space_id, quads)
            
        except Exception as e:
            logger.error(f"Error rolling back PostgreSQL quads for space {space_id}: {e}")
            return False
    
    async def _rollback_fuseki_quads(self, space_id: str, quads: List[tuple]) -> bool:
        """
        Rollback Fuseki quads by removing them.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to remove
            
        Returns:
            True if rollback succeeded, False otherwise
        """
        try:
            logger.debug(f"Rolling back Fuseki quads for space {space_id}")
            return await self._remove_quads_from_fuseki(space_id, quads)
            
        except Exception as e:
            logger.error(f"Error rolling back Fuseki quads for space {space_id}: {e}")
            return False
    
    def _generate_graph_name(self, graph_uri: str) -> str:
        """
        Generate a human-readable graph name from URI.
        Clips to max field size (255 characters).
        
        Args:
            graph_uri: Graph URI to extract name from
            
        Returns:
            Graph name clipped to 255 characters
            
        Examples:
            urn:multi_org_crud_graph -> multi_org_crud_graph
            http://example.org/graphs/my_graph -> my_graph
            haley:test_graph -> test_graph
        """
        # Extract last segment after '/' or ':'
        if '/' in graph_uri:
            name = graph_uri.split('/')[-1]
        elif ':' in graph_uri:
            name = graph_uri.split(':')[-1]
        else:
            name = graph_uri
        
        # Clip to max field size (graph_name VARCHAR(255))
        return name[:255] if name else graph_uri[:255]
    
    def _extract_graph_uris_from_quads(self, quads: List[tuple]) -> List[str]:
        """
        Extract unique graph URIs from quad tuples.
        
        Args:
            quads: List of quad tuples (subject, predicate, object, graph)
            
        Returns:
            List of unique graph URI strings (excluding 'default')
        """
        graph_uris = set()
        
        for quad in quads:
            if len(quad) >= 4:
                graph_uri = quad[3]
                # Convert to string and filter out 'default' graph
                graph_uri_str = str(graph_uri) if graph_uri else None
                if graph_uri_str and graph_uri_str != 'default':
                    graph_uris.add(graph_uri_str)
        
        return list(graph_uris)
    
    async def _ensure_graph_registered(self, space_id: str, graph_uri: str) -> bool:
        """
        Ensure graph is registered in PostgreSQL graph table.
        Checks existing graphs first before attempting to create.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to register
            
        Returns:
            True if graph is registered (new or existing), False on error
        """
        try:
            if self.graph_manager is None:
                logger.warning(f"Graph manager not available for registration")
                return False
            
            # Check if graph already exists
            existing_graph = await self.graph_manager.get_graph(space_id, graph_uri)
            if existing_graph:
                logger.debug(f"Graph already registered: {graph_uri} in space {space_id}")
                return True
            
            # Graph doesn't exist, create it
            graph_name = self._generate_graph_name(graph_uri)
            success = await self.graph_manager.create_graph(
                space_id, graph_uri, graph_name
            )
            
            if success:
                logger.debug(f"Graph registered: {graph_uri} in space {space_id}")
            else:
                logger.warning(f"Graph registration failed: {graph_uri} in space {space_id}")
            
            return success
            
        except Exception as e:
            logger.warning(f"Graph registration error for {graph_uri}: {e}")
            # Don't fail the operation - graph registration is metadata management
            return False
    
    async def _materialize_edge_properties(
        self, 
        space_id: str, 
        insert_quads: List[tuple], 
        delete_quads: List[tuple]
    ) -> bool:
        """
        Materialize direct edge properties in Fuseki.
        
        Detects edge objects in quad operations and generates corresponding
        direct property triples (vg-direct:*) that bypass edge objects for
        fast hierarchical queries.
        
        Args:
            space_id: Target space
            insert_quads: Quads being inserted
            delete_quads: Quads being deleted
            
        Returns:
            True if materialization succeeded or not needed
        """
        try:
            return await self.materialization_manager.materialize_from_quads(
                space_id, insert_quads, delete_quads
            )
        except Exception as e:
            logger.warning(f"Edge materialization failed: {e}")
            # Don't fail the operation - materialization is optimization
            return True
    
    def _build_delete_data_body(self, quads: List[tuple]) -> Optional[str]:
        """
        Build the body of a DELETE DATA query from quads (without the
        DELETE DATA { ... } wrapper).  Returns None when there are no
        formattable quads.
        """
        graph_quads: Dict[str, list] = {}
        for i, quad in enumerate(quads):
            if len(quad) >= 5:
                subject, predicate, obj, graph, obj_type = quad[:5]
                graph = str(graph)
                if graph not in graph_quads:
                    graph_quads[graph] = []
                subject_formatted = f"<{subject}>"
                predicate_formatted = f"<{predicate}>"
                if obj_type == 'literal':
                    escaped = str(obj).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    obj_formatted = f'"{escaped}"'
                else:
                    obj_formatted = f"<{obj}>"
                if subject_formatted and predicate_formatted and obj_formatted:
                    graph_quads[graph].append(f"{subject_formatted} {predicate_formatted} {obj_formatted}")
            elif len(quad) >= 4:
                subject, predicate, obj, graph = quad[:4]
                graph = str(graph)
                if graph not in graph_quads:
                    graph_quads[graph] = []
                subject_formatted = self._format_sparql_term(subject)
                predicate_formatted = self._format_sparql_term(predicate)
                obj_formatted = self._format_sparql_term(obj)
                if subject_formatted is not None and predicate_formatted is not None and obj_formatted is not None:
                    graph_quads[graph].append(f"{subject_formatted} {predicate_formatted} {obj_formatted}")
            else:
                subject, predicate, obj = quad[:3]
                graph = 'default'
                if graph not in graph_quads:
                    graph_quads[graph] = []
                subject_formatted = self._format_sparql_term(str(subject))
                predicate_formatted = self._format_sparql_term(str(predicate))
                obj_formatted = self._format_sparql_term(obj)
                if subject_formatted is not None and predicate_formatted is not None and obj_formatted is not None:
                    graph_quads[graph].append(f"{subject_formatted} {predicate_formatted} {obj_formatted}")

        if not graph_quads:
            return None

        graph_blocks = []
        for graph, triples in graph_quads.items():
            if graph and graph != 'default':
                graph_formatted = self._format_sparql_term(graph)
                triples_str = " .\n        ".join(triples)
                graph_blocks.append(f"GRAPH {graph_formatted} {{\n        {triples_str}\n    }}")
            else:
                triples_str = " .\n    ".join(triples)
                graph_blocks.append(triples_str)
        return "    " + "\n    ".join(graph_blocks)

    def _format_sparql_term(self, term: Any) -> Optional[str]:
        """
        Format an RDF term for SPARQL queries.
        
        Args:
            term: RDF term (URI, literal, blank node, or RDFLib object)
            
        Returns:
            Formatted SPARQL term string or None
        """
        if term is None:
            return None
        
        # Handle RDFLib objects
        try:
            from rdflib import URIRef, Literal, BNode
            
            if isinstance(term, URIRef):
                return f"<{str(term)}>"
            elif isinstance(term, Literal):
                value = str(term)
                # Escape special characters in literal values for SPARQL
                escaped_value = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                
                if term.language:
                    return f'"{escaped_value}"@{term.language}'
                elif term.datatype:
                    return f'"{escaped_value}"^^<{term.datatype}>'
                else:
                    return f'"{escaped_value}"'
            elif isinstance(term, BNode):
                return f"_:{term}"
        except ImportError:
            pass
        
        # Handle dict format (from SPARQL query results)
        if isinstance(term, dict):
            term_type = term.get('type')
            value = term.get('value')
            
            if term_type == 'uri':
                return f"<{value}>"
            elif term_type == 'literal':
                datatype = term.get('datatype')
                language = term.get('language')
                
                # Escape special characters in literal values for SPARQL
                escaped_value = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                
                if language:
                    return f'"{escaped_value}"@{language}'
                elif datatype:
                    return f'"{escaped_value}"^^<{datatype}>'
                else:
                    return f'"{escaped_value}"'
            elif term_type == 'bnode':
                return f"_:{value}"
        
        # Handle plain strings - detect if URI or literal using VitalSigns validation
        elif isinstance(term, str):
            # Use RFC 3986 compliant validation to detect if it's a URI
            if validate_rfc3986(term, rule='URI'):
                return f"<{term}>"
            else:
                # It's a literal value - escape and quote it
                escaped_value = term.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                return f'"{escaped_value}"'
        
        return None
