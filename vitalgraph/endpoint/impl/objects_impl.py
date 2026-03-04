"""
Object Implementation for VitalGraph

Provides generic object CRUD operations using the correct VitalGraph patterns:
- GraphObjects conversion with VitalSigns validation
- Transaction-based database operations using add_rdf_quads_batch()
- Proper conflict detection and error handling

Objects can be ANY VitalSigns graph object type with a valid vitaltype.
"""

import logging
from typing import List, Optional, Dict, Any

from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Import implementation utilities for CRUD operations (following KGTypeImpl pattern)
from .impl_utils import (
    execute_with_transaction, check_subject_uri_conflicts, get_existing_quads_for_uris,
    ImplValidationError, ImplConflictError, validate_uri_format,
    extract_subject_uris, batch_check_subject_uri_conflicts, batch_get_existing_quads_for_uris
)

# Import data format utilities
from ...utils.data_format_utils import (
    graphobjects_to_quads, 
    batch_graphobjects_to_quads
)


class ObjectsImpl:
    """Implementation for generic VitalSigns object operations using proper VitalGraph patterns."""
    
    def __init__(self, space_manager):
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.ObjectsImpl")
        
        # Initialize VitalSigns for object validation
        try:
            self.vitalsigns = VitalSigns()
            self.registry = self.vitalsigns.get_registry()
            self.logger.info("VitalSigns registry initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize VitalSigns registry: {e}")
            self.vitalsigns = None
            self.registry = None
    
    def validate_object_vitaltype(self, vitaltype_uri: str) -> bool:
        """
        Validate that a vitaltype URI is registered in VitalSigns registry.
        
        Args:
            vitaltype_uri: The vitaltype URI to validate
            
        Returns:
            True if the vitaltype is valid for any VitalSigns object, False otherwise
        """
        if not self.registry:
            self.logger.warning("VitalSigns registry not available for validation")
            return True  # Allow if registry unavailable
        
        try:
            vitalsigns_class = self.registry.get_vitalsigns_class(vitaltype_uri)
            is_valid = vitalsigns_class is not None
            
            if not is_valid:
                self.logger.warning(f"Invalid vitaltype: {vitaltype_uri}")
                self.logger.debug(f"Vitaltype not found in VitalSigns registry")
            
            return is_valid
        except Exception as e:
            self.logger.warning(f"Failed to validate vitaltype {vitaltype_uri}: {e}")
            return False
    
    async def delete_objects(self, space_id: str, object_uris: List[str], graph_id: str) -> int:
        """
        Delete multiple objects with proper transaction management.
        
        Args:
            space_id: Space identifier
            object_uris: List of object URIs to delete
            graph_id: Graph identifier (required)
            
        Returns:
            Number of objects successfully deleted
        """
        try:
            self.logger.info(f"Deleting {len(object_uris)} objects from space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for all objects
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, object_uris
            )
            
            if not existing_quads:
                self.logger.warning("No objects found for deletion")
                return 0
            
            # Step 2: Execute batch deletion in transaction
            async def delete_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                removed_count = await db_space_impl.db_ops.remove_rdf_quads_batch(
                    space_id, existing_quads, auto_commit=False, transaction=transaction
                )
                
                # Count unique subjects deleted
                deleted_subjects = set(str(quad[0]) for quad in existing_quads)
                deleted_count = len(deleted_subjects)
                
                self.logger.info(f"Deleted {deleted_count} objects: removed {removed_count} quads")
                return deleted_count
            
            result = await execute_with_transaction(
                self.space_manager, space_id, delete_operation
            )
            
            self.logger.info(f"Successfully deleted {result} objects")
            return result
            
        except Exception as e:
            raise ImplValidationError(f"Failed to delete objects: {e}")
    
    async def get_object_by_uri(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> List:
        """
        Get a single object by URI.
        
        Returns:
            List[GraphObject] (empty if not found)
        """
        try:
            self.logger.info(f"Getting object {uri} from space {space_id}, graph {graph_id}")
            
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            quads = await db_space_impl.db_objects.get_objects_by_uris_batch(
                space_id=space_id,
                subject_uris=[uri],
                graph_id=graph_id
            )
            
            if not quads:
                self.logger.info(f"Object {uri} not found")
                return []
            
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            triples_list = [(s, p, o) for s, p, o, graph_ctx in quads]
            vitalsigns = VitalSigns()
            graph_objects = vitalsigns.from_triples_list(triples_list)
            
            self.logger.debug(f"Retrieved object {uri}: {len(graph_objects)} objects")
            return graph_objects
        except Exception as e:
            self.logger.error(f"Error getting object by URI: {e}")
            return []
    
    async def get_objects_by_uris(self, space_id: str, uris: List[str], graph_id: Optional[str] = None) -> List:
        """
        Get multiple objects by URI list.
        
        Returns:
            List[GraphObject]
        """
        try:
            self.logger.info(f"Getting {len(uris)} objects from space {space_id}, graph {graph_id}")
            
            if not uris:
                return []
            
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            graph_objects = await db_space_impl.db_objects.get_objects_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            self.logger.info(f"Retrieved {len(graph_objects)} objects")
            return graph_objects
            
        except Exception as e:
            self.logger.error(f"Error getting objects by URIs: {e}")
            return []
    
    async def list_objects(self, space_id: str, graph_id: Optional[str] = None, 
                          page_size: int = 100, offset: int = 0, 
                          vitaltype_filter: Optional[str] = None, 
                          search_text: Optional[str] = None) -> tuple[List, int]:
        """
        List objects with pagination and filtering.
        
        Returns:
            Tuple of (List[GraphObject], total_count)
        """
        try:
            self.logger.info(f"Listing objects in space {space_id}, graph {graph_id}")
            
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            filters = {}
            if vitaltype_filter:
                filters['vitaltype_uri'] = vitaltype_filter
            if search_text:
                filters['search_text'] = search_text
            
            graph_objects, total_count = await db_space_impl.db_objects.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                filters=filters
            )
            
            self.logger.info(f"Listed {len(graph_objects)} objects (total: {total_count})")
            return graph_objects, total_count
            
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            raise
    
    async def create_objects_batch(self, space_id: str, graph_objects: List, graph_id: str) -> List[str]:
        """
        Create multiple objects in a single transaction.
        
        Args:
            space_id: Space identifier
            graph_objects: List[GraphObject] to create
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the created objects
        """
        try:
            self.logger.info(f"Creating {len(graph_objects)} objects in space {space_id}, graph {graph_id}")
            
            if not graph_objects:
                return []
            
            # Step 1: Extract URIs and check for conflicts
            subject_uris = [str(obj.URI) for obj in graph_objects]
            conflicts = await batch_check_subject_uri_conflicts(
                self.space_manager, space_id, subject_uris
            )
            if conflicts:
                raise ImplConflictError(f"Objects with URIs already exist: {', '.join(conflicts)}")
            
            # Step 3: Convert GraphObjects to quads using batch utility
            quads = await batch_graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 4: Execute batch insert with transaction
            async def create_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, quads, auto_commit=False, transaction=transaction
                )
                
                if added_count != len(quads):
                    raise RuntimeError(f"Expected to add {len(quads)} quads, but added {added_count}")
                
                self.logger.info(f"Created {len(subject_uris)} objects: added {added_count} quads")
                return subject_uris
            
            result = await execute_with_transaction(
                self.space_manager, space_id, create_operation
            )
            
            self.logger.info(f"Successfully created {len(result)} objects")
            return result
            
        except ImplValidationError:
            raise  # Re-raise validation errors
        except ImplConflictError:
            raise  # Re-raise conflict errors
        except Exception as e:
            raise ImplValidationError(f"Failed to create objects batch: {e}")
    
    async def update_objects_batch(self, space_id: str, graph_objects: List, graph_id: str) -> List[str]:
        """
        Update multiple objects in a single transaction.
        
        Args:
            space_id: Space identifier
            graph_objects: List[GraphObject] with updated data (must have URIs)
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the updated objects
        """
        try:
            self.logger.info(f"Updating {len(graph_objects)} objects in space {space_id}, graph {graph_id}")
            
            if not graph_objects:
                return []
            
            # Step 1: Extract URIs
            subject_uris = []
            for i, obj in enumerate(graph_objects):
                uri = str(obj.URI) if hasattr(obj, 'URI') and obj.URI else None
                if not uri:
                    raise ImplValidationError(f"Object at index {i} missing URI")
                subject_uris.append(uri)
            
            # Step 2: Get existing quads for all objects
            existing_quads = await batch_get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, subject_uris
            )
            
            if not existing_quads:
                raise ImplValidationError("No objects found for update")
            
            # Verify all objects exist by checking which URIs have quads
            existing_uris = set(str(quad[0]) for quad in existing_quads)
            missing_uris = [uri for uri in subject_uris if uri not in existing_uris]
            if missing_uris:
                raise ImplValidationError(f"Objects not found: {', '.join(missing_uris)}")
            
            # Step 3: Convert GraphObjects to new quads
            new_quads = await batch_graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 4: Execute batch update in transaction (delete old + insert new)
            async def update_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                # Remove existing quads
                removed_count = await db_space_impl.db_ops.remove_rdf_quads_batch(
                    space_id, existing_quads, auto_commit=False, transaction=transaction
                )
                
                # Add new quads
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, new_quads, auto_commit=False, transaction=transaction
                )
                
                self.logger.info(f"Updated {len(subject_uris)} objects: removed {removed_count}, added {added_count} quads")
                return subject_uris
            
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated {len(result)} objects")
            return result
            
        except ImplValidationError:
            raise
        except Exception as e:
            raise ImplValidationError(f"Failed to update objects batch: {e}")
