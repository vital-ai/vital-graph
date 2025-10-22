"""
KGFrame Implementation for VitalGraph

Provides KGFrame-specific CRUD operations using the correct VitalGraph patterns:
- JSON-LD to GraphObjects conversion with KGFrame validation
- Transaction-based database operations using add_rdf_quads_batch()
- Proper conflict detection and error handling

KGFrames are objects with vitaltype of KGFrame or its subclasses.
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


class KGFrameImpl:
    """Implementation for KGFrame operations using proper VitalGraph patterns."""
    
    def __init__(self, space_manager):
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.KGFrameImpl")
        
        # Initialize VitalSigns for vitaltype validation
        self.vitalsigns = None
        self.ontology_manager = None
        self._init_vitalsigns()
    
    def _init_vitalsigns(self):
        """Initialize VitalSigns and ontology manager."""
        try:
            self.vitalsigns = VitalSigns()
            self.ontology_manager = self.vitalsigns.get_ontology_manager()
            self.logger.info("VitalSigns ontology manager initialized")
        except Exception as e:
            self.logger.warning(f"Failed to initialize VitalSigns ontology manager: {e}")
            self.ontology_manager = None
    
    def get_kgframe_vitaltypes(self) -> List[str]:
        """
        Get all vitaltype URIs for KGFrame and its subclasses.
        
        Returns:
            List of vitaltype URIs including KGFrame and all its subclasses
        """
        kgframe_uri = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
        vitaltypes = [kgframe_uri]  # Start with base KGFrame
        
        if self.ontology_manager:
            try:
                # Get all subclasses of KGFrame
                subclass_list = self.ontology_manager.get_subclass_uri_list(kgframe_uri)
                vitaltypes.extend(subclass_list)
                self.logger.info(f"Found {len(subclass_list)} KGFrame subclasses")
            except Exception as e:
                self.logger.warning(f"Failed to get KGFrame subclasses: {e}")
        else:
            self.logger.warning("Ontology manager not available, using only base KGFrame type")
        
        return vitaltypes
    
    def validate_kgframe_vitaltype(self, vitaltype_uri: str) -> bool:
        """
        Validate that a vitaltype URI is a KGFrame or subclass.
        
        Args:
            vitaltype_uri: The vitaltype URI to validate
            
        Returns:
            True if the vitaltype is valid for KGFrame, False otherwise
        """
        valid_vitaltypes = self.get_kgframe_vitaltypes()
        is_valid = vitaltype_uri in valid_vitaltypes
        
        if not is_valid:
            self.logger.warning(f"Invalid KGFrame vitaltype: {vitaltype_uri}")
            self.logger.debug(f"Valid KGFrame vitaltypes: {valid_vitaltypes}")
        
        return is_valid
    
    async def create_kgframe(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> str:
        """
        Create a new KGFrame with proper validation and transaction management using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            jsonld_document: Complete JSON-LD document containing KGFrame with @context and @graph
            graph_id: Graph identifier (required)
            
        Returns:
            URI of the created KGFrame
            
        Raises:
            ImplValidationError: If validation fails
            ImplConflictError: If URI conflicts with existing object
        """
        try:
            self.logger.info(f"Creating KGFrame in space {space_id}, graph {graph_id}")
            
            # Step 1: Convert JSON-LD to GraphObjects using VitalSigns native functionality
            # Use shared utility with KGFrame-specific validator
            graph_objects = await jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgframe_vitaltype
            )
            graph_object = graph_objects[0]
            
            # Step 2: Check for conflicts using shared utility
            subject_uri = str(graph_object.URI)
            conflicts = await check_subject_uri_conflicts(
                self.space_manager, space_id, [subject_uri]
            )
            if conflicts:
                raise ImplConflictError(f"Object with URI {subject_uri} already exists")
            
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
                return subject_uri
            
            result = await execute_with_transaction(
                self.space_manager, space_id, create_operation
            )
            
            self.logger.info(f"Successfully created KGFrame: {result}")
            return result
            
        except ImplValidationError:
            raise  # Re-raise validation errors
        except ImplConflictError:
            raise  # Re-raise conflict errors
        except Exception as e:
            raise ImplValidationError(f"Failed to create KGFrame: {e}")
    
    async def update_kgframe(self, space_id: str, kgframe_uri: str, jsonld_document: Dict[str, Any], graph_id: str) -> bool:
        """
        Update an existing KGFrame with proper validation and transaction management using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            kgframe_uri: URI of the KGFrame to update
            jsonld_document: Complete JSON-LD document containing updated KGFrame with @context and @graph
            graph_id: Graph identifier (required)
            
        Returns:
            True if update was successful
            
        Raises:
            ImplValidationError: If validation fails
        """
        try:
            self.logger.info(f"Updating KGFrame {kgframe_uri} in space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for this object
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, [kgframe_uri]
            )
            
            if not existing_quads:
                raise ImplValidationError(f"KGFrame {kgframe_uri} not found")
            
            # Step 2: Convert JSON-LD to GraphObjects using VitalSigns native functionality
            # Validate new data
            graph_objects = await jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgframe_vitaltype
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
                
                self.logger.info(f"Updated KGFrame {kgframe_uri}: removed {removed_count}, added {added_count} quads")
                return True
            
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated KGFrame: {kgframe_uri}")
            return result
            
        except ImplValidationError:
            raise
        except Exception as e:
            raise ImplValidationError(f"Failed to update KGFrame: {e}")
    
    async def delete_kgframe(self, space_id: str, kgframe_uri: str, graph_id: str) -> bool:
        """
        Delete a KGFrame object with proper transaction management.
        
        Args:
            space_id: Space identifier
            kgframe_uri: URI of the KGFrame to delete
            graph_id: Graph identifier (required)
            
        Returns:
            True if deletion was successful
            
        Raises:
            ImplValidationError: If validation fails
        """
        try:
            self.logger.info(f"Deleting KGFrame {kgframe_uri} from space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for this object
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, [kgframe_uri]
            )
            
            if not existing_quads:
                self.logger.warning(f"KGFrame {kgframe_uri} not found for deletion")
                return False
            
            # Step 2: Execute deletion in transaction
            async def delete_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                removed_count = await db_space_impl.db_ops.remove_rdf_quads_batch(
                    space_id, existing_quads, auto_commit=False, transaction=transaction
                )
                
                self.logger.info(f"Deleted KGFrame {kgframe_uri}: removed {removed_count} quads")
                return True
            
            result = await execute_with_transaction(
                self.space_manager, space_id, delete_operation
            )
            
            self.logger.info(f"Successfully deleted KGFrame: {kgframe_uri}")
            return result
            
        except Exception as e:
            raise ImplValidationError(f"Failed to delete KGFrame: {e}")
    
    async def delete_kgframes(self, space_id: str, kgframe_uris: List[str], graph_id: str) -> int:
        """
        Delete multiple KGFrame objects with proper transaction management.
        
        Args:
            space_id: Space identifier
            kgframe_uris: List of KGFrame URIs to delete
            graph_id: Graph identifier (required)
            
        Returns:
            Number of KGFrames successfully deleted
        """
        try:
            self.logger.info(f"Deleting {len(kgframe_uris)} KGFrames from space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for all objects
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, kgframe_uris
            )
            
            if not existing_quads:
                self.logger.warning("No KGFrames found for deletion")
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
                
                self.logger.info(f"Deleted {deleted_count} KGFrames: removed {removed_count} quads")
                return deleted_count
            
            result = await execute_with_transaction(
                self.space_manager, space_id, delete_operation
            )
            
            self.logger.info(f"Successfully deleted {result} KGFrames")
            return result
            
        except Exception as e:
            raise ImplValidationError(f"Failed to delete KGFrames: {e}")
    
    async def get_kgframe_by_uri(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single KGFrame by URI and return as complete JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            uri: KGFrame URI to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            Complete JSON-LD document or None if not found
        """
        try:
            self.logger.info(f"Getting KGFrame {uri} from space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Use db_objects to get the object by URI
            graph_object = await db_space_impl.db_objects.get_object_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not graph_object:
                self.logger.info(f"KGFrame {uri} not found")
                return None
            
            # Use VitalSigns native JSON-LD conversion directly
            jsonld_document = graph_object.to_jsonld()
            
            self.logger.debug(f"Successfully converted KGFrame {uri} to JSON-LD using VitalSigns native functionality")
            return jsonld_document
            
        except Exception as e:
            self.logger.error(f"Error getting KGFrame by URI: {e}")
            return None
    
    async def get_kgframes_by_uris(self, space_id: str, uris: List[str], graph_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get multiple KGFrames by URI list and return as complete JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            uris: List of KGFrame URIs to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            Complete JSON-LD document with @context and @graph containing all KGFrames
        """
        try:
            self.logger.info(f"Getting {len(uris)} KGFrames from space {space_id}, graph {graph_id}")
            
            if not uris:
                # Use VitalSigns to create empty JSON-LD document
                from vital_ai_vitalsigns.vitalsigns import VitalSigns
                vitalsigns = VitalSigns()
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
            
            self.logger.info(f"Retrieved {len(graph_objects)} KGFrames")
            return jsonld_document
            
        except Exception as e:
            self.logger.error(f"Error getting KGFrames by URIs: {e}")
            # Use VitalSigns to create empty JSON-LD document on error
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            return vitalsigns.to_jsonld_list([])
    
    async def list_kgframes(self, space_id: str, graph_id: Optional[str] = None, 
                           page_size: int = 100, offset: int = 0, 
                           frame_type_filter: Optional[str] = None, 
                           search_text: Optional[str] = None) -> tuple[Dict[str, Any], int]:
        """
        List KGFrames with pagination and filtering using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of frames per page
            offset: Offset for pagination
            frame_type_filter: Filter by frame type URI
            search_text: Search text in frame properties
            
        Returns:
            Tuple of (complete JSON-LD document, total count)
        """
        try:
            self.logger.info(f"Listing KGFrames in space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Use db_objects to list objects with filtering
            filters = {}
            if frame_type_filter:
                filters['vitaltype_uri'] = frame_type_filter
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
            
            self.logger.info(f"Listed {len(graph_objects)} KGFrames (total: {total_count})")
            return jsonld_document, total_count
            
        except Exception as e:
            self.logger.error(f"Error listing KGFrames: {e}")
            # Use VitalSigns to create empty JSON-LD document on error
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            return vitalsigns.to_jsonld_list([]), 0
    
    async def create_kgframes_batch(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Create multiple KGFrames in a single transaction with proper validation.
        
        Args:
            space_id: Space identifier
            kgframes_data: List of dictionaries containing KGFrame properties
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the created KGFrames
            
        Raises:
            ImplValidationError: If validation fails
            ImplConflictError: If any URI conflicts with existing objects
        """
        try:
            kgframes_data = jsonld_document.get("@graph", [])
            self.logger.info(f"Creating {len(kgframes_data)} KGFrames in space {space_id}, graph {graph_id}")
            
            if not kgframes_data:
                return []
            
            # Step 1: Convert JSON-LD to GraphObjects using batch utility
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgframe_vitaltype
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
                
                self.logger.info(f"Created {len(subject_uris)} KGFrames: added {added_count} quads")
                return subject_uris
            
            result = await execute_with_transaction(
                self.space_manager, space_id, create_operation
            )
            
            self.logger.info(f"Successfully created {len(result)} KGFrames")
            return result
            
        except ImplValidationError:
            raise  # Re-raise validation errors
        except ImplConflictError:
            raise  # Re-raise conflict errors
        except Exception as e:
            raise ImplValidationError(f"Failed to create KGFrames batch: {e}")
    
    async def update_kgframes_batch(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Update multiple KGFrames in a single transaction with proper validation.
        
        Args:
            space_id: Space identifier
            kgframes_data: List of dictionaries containing updated KGFrame properties (must include URIs)
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the updated KGFrames
            
        Raises:
            ImplValidationError: If validation fails or any KGFrame not found
        """
        try:
            kgframes_data = jsonld_document.get("@graph", [])
            self.logger.info(f"Updating {len(kgframes_data)} KGFrames in space {space_id}, graph {graph_id}")
            
            if not kgframes_data:
                return []
            
            # Step 1: Extract URIs for existence check
            subject_uris = []
            for frame_data in kgframes_data:
                uri = frame_data.get('URI') or frame_data.get('@id')
                if not uri:
                    raise ImplValidationError("All KGFrames must have a URI for update")
                subject_uris.append(str(uri))
            
            # Step 2: Get existing quads for all objects
            existing_quads = await batch_get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, subject_uris
            )
            
            if not existing_quads:
                raise ImplValidationError("No KGFrames found for update")
            
            # Verify all objects exist by checking which URIs have quads
            existing_uris = set(str(quad[0]) for quad in existing_quads)
            missing_uris = [uri for uri in subject_uris if uri not in existing_uris]
            if missing_uris:
                raise ImplValidationError(f"KGFrames not found: {', '.join(missing_uris)}")
            
            # Step 3: Convert new data to GraphObjects for validation
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgframe_vitaltype
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
                
                self.logger.info(f"Updated {len(subject_uris)} KGFrames: removed {removed_count}, added {added_count} quads")
                return subject_uris
            
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated {len(result)} KGFrames")
            return result
            
        except ImplValidationError:
            raise
        except Exception as e:
            raise ImplValidationError(f"Failed to update KGFrames batch: {e}")
