"""
Object Implementation for VitalGraph

Provides generic object CRUD operations using the correct VitalGraph patterns:
- JSON-LD to GraphObjects conversion with VitalSigns validation
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
    jsonld_to_graphobjects, graphobjects_to_quads, 
    batch_jsonld_to_graphobjects, batch_graphobjects_to_quads
)


class ObjectImpl:
    """Implementation for generic VitalSigns object operations using proper VitalGraph patterns."""
    
    def __init__(self, space_manager):
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.ObjectImpl")
        
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
    
    async def create_objects(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Create multiple objects with proper validation and transaction management using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            jsonld_document: JSON-LD document containing objects with @context and @graph
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the created objects
            
        Raises:
            ImplValidationError: If validation fails
            ImplConflictError: If URI conflicts with existing objects
        """
        try:
            objects_count = len(jsonld_document.get("@graph", [])) if isinstance(jsonld_document, dict) else 0
            self.logger.info(f"Creating {objects_count} objects in space {space_id}, graph {graph_id}")
            
            # Step 1: Convert JSON-LD to GraphObjects using VitalSigns native functionality
            graph_objects = await jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_object_vitaltype
            )
            
            # Step 2: Check for conflicts using shared utility
            subject_uris = [str(obj.URI) for obj in graph_objects]
            conflicts = await check_subject_uri_conflicts(
                self.space_manager, space_id, subject_uris
            )
            if conflicts:
                raise ImplConflictError(f"Objects with URIs {conflicts} already exist")
            
            # Step 3: Convert GraphObjects back to quads using shared utility
            quads = await graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 4: Execute with transaction using shared utility
            async def create_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, quads, auto_commit=False, transaction=transaction
                )
                if added_count != len(quads):
                    raise RuntimeError(f"Expected to add {len(quads)} quads, but added {added_count}")
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
            raise ImplValidationError(f"Failed to create objects: {e}")
    
    async def update_objects(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> int:
        """
        Update multiple existing objects with proper validation and transaction management using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            jsonld_document: JSON-LD document containing updated objects with @context and @graph
            graph_id: Graph identifier (required)
            
        Returns:
            Number of objects successfully updated
            
        Raises:
            ImplValidationError: If validation fails or objects not found
        """
        try:
            objects_data = jsonld_document.get("@graph", [])
            objects_count = len(objects_data) if isinstance(objects_data, list) else 0
            self.logger.info(f"Updating {objects_count} objects in space {space_id}, graph {graph_id}")
            
            if not objects_data:
                return 0
            
            # Step 1: Extract URIs for existence check
            subject_uris = []
            for obj_data in objects_data:
                uri = obj_data.get('URI') or obj_data.get('@id')
                if not uri:
                    raise ImplValidationError("All objects must have a URI for update")
                subject_uris.append(str(uri))
            
            # Step 1: Get existing quads for all objects
            existing_quads = await batch_get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, subject_uris
            )
            
            if not existing_quads:
                raise ImplValidationError("No objects found for update")
            
            # Step 2: Convert JSON-LD document to GraphObjects using VitalSigns native functionality
            # Ensure URIs are preserved in the data
            for i, obj_data in enumerate(objects_data):
                uri = subject_uris[i]
                obj_data['@id'] = uri
                obj_data['URI'] = uri
            
            # Validate new data using the provided JSON-LD document
            graph_objects = await jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_object_vitaltype
            )
            
            # Step 3: Convert to new quads
            new_quads = await graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 4: Execute update in transaction (delete old + insert new)
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
                
                # Count unique subjects updated
                updated_subjects = set(str(obj.URI) for obj in graph_objects)
                updated_count = len(updated_subjects)
                
                self.logger.info(f"Updated {updated_count} objects: removed {removed_count}, added {added_count} quads")
                return updated_count
            
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated {result} objects")
            return result
            
        except ImplValidationError:
            raise
        except Exception as e:
            raise ImplValidationError(f"Failed to update objects: {e}")
    
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
    
    async def get_object_by_uri(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single object by URI and return as complete JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            uri: Object URI to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            Complete JSON-LD document with @context and object data, or None if not found
        """
        try:
            self.logger.info(f"Getting object {uri} from space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Get quads for this specific URI (following KGType pattern)
            quads = await db_space_impl.db_objects.get_objects_by_uris_batch(
                space_id=space_id,
                subject_uris=[uri],
                graph_id=graph_id
            )
            
            if not quads:
                self.logger.info(f"Object {uri} not found")
                return None
            
            # Convert quads directly to VitalSigns object using native functionality
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            
            # Extract triples (remove graph context for VitalSigns)
            triples_list = [(s, p, o) for s, p, o, graph_ctx in quads]
            
            # Use VitalSigns to convert triples to GraphObjects
            vitalsigns = VitalSigns()
            graph_objects = vitalsigns.from_triples_list(triples_list)
            
            if not graph_objects:
                self.logger.info(f"Object {uri} could not be converted to VitalSigns object")
                return None
            
            # Use VitalSigns native JSON-LD conversion directly
            graph_object = graph_objects[0]
            
            # Let VitalSigns handle the complete JSON-LD document creation
            jsonld_document = graph_object.to_jsonld()
            
            self.logger.debug(f"Successfully converted object {uri} to JSON-LD using VitalSigns native functionality")
            return jsonld_document
        except Exception as e:
            self.logger.error(f"Error getting object by URI: {e}")
            return None
    
    async def get_objects_by_uris(self, space_id: str, uris: List[str], graph_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get multiple objects by URI list and return as complete JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            uris: List of object URIs to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            Complete JSON-LD document with @context and @graph containing all objects
        """
        try:
            self.logger.info(f"Getting {len(uris)} objects from space {space_id}, graph {graph_id}")
            
            if not uris:
                # Use VitalSigns to create empty JSON-LD document
                from vital_ai_vitalsigns.vitalsigns import VitalSigns
                vitalsigns = VitalSigns()
                # Create empty document using VitalSigns native functionality
                empty_doc = vitalsigns.to_jsonld_list([])
                return empty_doc
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Use db_objects to get objects by URIs
            graph_objects = await db_space_impl.db_objects.get_objects_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            # Use VitalSigns native functionality to convert GraphObjects to JSON-LD document
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            
            # Let VitalSigns handle the complete JSON-LD document creation for multiple objects
            jsonld_document = vitalsigns.to_jsonld_list(graph_objects)
            
            self.logger.info(f"Retrieved {len(graph_objects)} objects")
            return jsonld_document
            
        except Exception as e:
            self.logger.error(f"Error getting objects by URIs: {e}")
            # Use VitalSigns to create empty JSON-LD document on error
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            return vitalsigns.to_jsonld_list([])
    
    async def list_objects(self, space_id: str, graph_id: Optional[str] = None, 
                          page_size: int = 100, offset: int = 0, 
                          vitaltype_filter: Optional[str] = None, 
                          search_text: Optional[str] = None) -> tuple[Dict[str, Any], int]:
        """
        List objects with pagination and filtering using VitalGraph db_objects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of objects per page
            offset: Offset for pagination
            vitaltype_filter: Filter by vitaltype URI
            search_text: Search text in object properties
            
        Returns:
            Tuple of (objects list, total count)
        """
        try:
            self.logger.info(f"Listing objects in space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Use db_objects to list objects with filtering
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
            
            # Use VitalSigns native functionality to convert GraphObjects to JSON-LD document
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            
            # Let VitalSigns handle the complete JSON-LD document creation for multiple objects
            jsonld_document = vitalsigns.to_jsonld_list(graph_objects)
            
            self.logger.info(f"Listed {len(graph_objects)} objects (total: {total_count})")
            return jsonld_document, total_count
            
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            raise
    
    async def create_objects_batch(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Create multiple objects in a single transaction with proper validation.
        
        Args:
            space_id: Space identifier
            objects_data: List of dictionaries containing object properties
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the created objects
            
        Raises:
            ImplValidationError: If validation fails
            ImplConflictError: If any URI conflicts with existing objects
        """
        try:
            objects_data = jsonld_document.get("@graph", [])
            self.logger.info(f"Creating {len(objects_data)} objects in space {space_id}, graph {graph_id}")
            
            if not objects_data:
                return []
            
            # Step 1: Convert JSON-LD to GraphObjects using batch utility
            # Use generic object validator (validates any VitalSigns vitaltype)
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_object_vitaltype
            )
            
            # Step 2: Extract URIs and check for conflicts
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
    
    async def update_objects_batch(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Update multiple objects in a single transaction with proper validation.
        
        Args:
            space_id: Space identifier
            objects_data: List of dictionaries containing updated object properties (must include URIs)
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the updated objects
            
        Raises:
            ImplValidationError: If validation fails or any object not found
        """
        try:
            self.logger.info(f"Updating {len(objects_data)} objects in space {space_id}, graph {graph_id}")
            
            if not objects_data:
                return []
            
            # Step 1: Extract URIs and ensure they're present in the data
            subject_uris = []
            for i, object_data in enumerate(objects_data):
                uri = object_data.get('@id') or object_data.get('URI')
                if not uri:
                    raise ImplValidationError(f"Object at index {i} missing URI (@id or URI field)")
                
                # Ensure URI is in both fields for consistency
                object_data['@id'] = uri
                object_data['URI'] = uri
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
            
            # Step 3: Convert new data to GraphObjects for validation
            # Use generic object validator (validates any VitalSigns vitaltype)
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_object_vitaltype
            )
            
            # Step 4: Convert to new quads
            new_quads = await batch_graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 5: Execute batch update in transaction (delete old + insert new)
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
