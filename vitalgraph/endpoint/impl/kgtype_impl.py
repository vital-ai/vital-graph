"""
KGType Implementation for VitalGraph

Provides KGType-specific operations using the correct VitalGraph patterns:
- JSON-LD to GraphObjects conversion with validation
- Transaction-based database operations using add_rdf_quads_batch()
- Proper conflict detection and error handling
"""

import logging
from typing import List, Optional, Dict, Any

from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Import implementation utilities for shared functionality
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

# Import KGTypeFilter from model
from ...model.kgtypes_model import KGTypeFilter


class KGTypeImpl:
    """Implementation for KGType operations using proper VitalGraph patterns."""
    
    def __init__(self, space_manager):
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.KGTypeImpl")
        
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
    
    def get_kgtype_vitaltypes(self) -> List[str]:
        """
        Get all vitaltype URIs for KGType and its subclasses.
        
        Returns:
            List of vitaltype URIs including KGType and all its subclasses
        """
        kgtype_uri = "http://vital.ai/ontology/haley-ai-kg#KGType"
        vitaltypes = [kgtype_uri]  # Start with base KGType
        
        if self.ontology_manager:
            try:
                # Get all subclasses of KGType
                subclass_list = self.ontology_manager.get_subclass_uri_list(kgtype_uri)
                vitaltypes.extend(subclass_list)
                self.logger.info(f"Found {len(subclass_list)} KGType subclasses")
                self.logger.debug(f"KGType vitaltypes: {vitaltypes}")
            except Exception as e:
                self.logger.warning(f"Failed to get KGType subclasses: {e}")
        else:
            self.logger.warning("Ontology manager not available, using only base KGType type")
        
        return vitaltypes
    
    def validate_kgtype_vitaltype(self, vitaltype_uri: str) -> bool:
        """
        Validate that a vitaltype URI is a KGType or KGType subclass.
        
        Args:
            vitaltype_uri: The vitaltype URI to validate
            
        Returns:
            True if the vitaltype is a valid KGType or subclass
        """
        valid_vitaltypes = self.get_kgtype_vitaltypes()
        is_valid = vitaltype_uri in valid_vitaltypes
        
        if not is_valid:
            self.logger.warning(f"Invalid KGType vitaltype: {vitaltype_uri}")
            self.logger.debug(f"Valid KGType vitaltypes: {valid_vitaltypes}")
        
        return is_valid
    
    async def create_kgtype(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> str:
        """
        Create a new KGType with proper validation and transaction management using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            jsonld_document: Complete JSON-LD document containing KGType with @context and @graph
            graph_id: Graph identifier (required)
            
        Returns:
            URI of the created KGType
            
        Raises:
            ImplValidationError: If validation fails
            ImplConflictError: If URI conflicts with existing object
        """
        try:
            self.logger.info(f"Creating KGType in space {space_id}, graph {graph_id}")
            
            # Step 1: Convert JSON-LD to GraphObjects using VitalSigns native functionality
            # Use shared utility with KGType-specific validator
            graph_objects = await jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgtype_vitaltype
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
                    space_id, quads, transaction=transaction
                )
                if added_count != len(quads):
                    raise RuntimeError(f"Expected to add {len(quads)} quads, but added {added_count}")
                return subject_uri
            
            result = await execute_with_transaction(
                self.space_manager, space_id, create_operation
            )
            
            self.logger.info(f"Successfully created KGType: {result}")
            return result
            
        except ImplValidationError:
            raise  # Re-raise validation errors
        except ImplConflictError:
            raise  # Re-raise conflict errors
        except Exception as e:
            raise ImplValidationError(f"Failed to create KGType: {e}")
    
    async def update_kgtype(self, space_id: str, kgtype_uri: str, jsonld_document: Dict[str, Any], graph_id: str) -> bool:
        """
        Update an existing KGType with proper validation and transaction management using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            kgtype_uri: URI of the KGType to update
            jsonld_document: Complete JSON-LD document containing updated KGType with @context and @graph
            graph_id: Graph identifier (required)
            
        Returns:
            True if update was successful
            
        Raises:
            ImplValidationError: If validation fails
        """
        try:
            self.logger.info(f"Updating KGType {kgtype_uri} in space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for this object
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, [kgtype_uri]
            )
            
            if not existing_quads:
                raise ImplValidationError(f"KGType {kgtype_uri} not found")
            
            # Step 2: Convert JSON-LD to GraphObjects using VitalSigns native functionality
            # Validate new data
            graph_objects = await jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgtype_vitaltype
            )
            
            # Step 3: Convert to new quads
            new_quads = await graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 4: Execute update in transaction (delete old + insert new)
            async def update_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                # Remove existing quads using text-based removal (same as delete method)
                removed_count = await db_space_impl.db_ops.remove_quads_by_subject_uris(
                    space_id, [kgtype_uri], graph_id, transaction=transaction
                )
                
                # Add new quads
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, new_quads, transaction=transaction
                )
                
                self.logger.info(f"Updated KGType {kgtype_uri}: removed {removed_count}, added {added_count} quads")
                return True
            
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated KGType: {kgtype_uri}")
            return result
            
        except ImplValidationError:
            raise
        except Exception as e:
            raise ImplValidationError(f"Failed to update KGType: {e}")
    
    async def delete_kgtype(self, space_id: str, kgtype_uri: str, graph_id: str) -> bool:
        """
        Delete a KGType object with proper transaction management.
        
        Args:
            space_id: Space identifier
            kgtype_uri: URI of the KGType to delete
            graph_id: Graph identifier (required)
            
        Returns:
            True if deletion was successful
            
        Raises:
            ImplValidationError: If validation fails
        """
        try:
            self.logger.info(f"Deleting KGType {kgtype_uri} from space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for this object
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, [kgtype_uri]
            )
            
            if not existing_quads:
                self.logger.warning(f"KGType {kgtype_uri} not found for deletion")
                return False
            
            # Step 2: Execute deletion in transaction using text-based matching
            async def delete_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                # Use new text-based removal method to avoid UUID matching issues
                removed_count = await db_space_impl.db_ops.remove_quads_by_subject_uris(
                    space_id, [kgtype_uri], graph_id, transaction=transaction
                )
                
                self.logger.info(f"Deleted KGType {kgtype_uri}: removed {removed_count} quads")
                return True
            
            result = await execute_with_transaction(
                self.space_manager, space_id, delete_operation
            )
            
            self.logger.info(f"Successfully deleted KGType: {kgtype_uri}")
            return result
            
        except Exception as e:
            raise ImplValidationError(f"Failed to delete KGType: {e}")
    
    async def delete_kgtypes(self, space_id: str, kgtype_uris: List[str], graph_id: str) -> int:
        """
        Delete multiple KGType objects with proper transaction management.
        
        Args:
            space_id: Space identifier
            kgtype_uris: List of KGType URIs to delete
            graph_id: Graph identifier (required)
            
        Returns:
            Number of KGTypes successfully deleted
        """
        try:
            self.logger.info(f"Deleting {len(kgtype_uris)} KGTypes from space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for all objects
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, kgtype_uris
            )
            
            if not existing_quads:
                self.logger.warning("No KGTypes found for deletion")
                return 0
            
            # Step 2: Execute batch deletion in transaction using text-based matching
            async def delete_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                # Use new text-based removal method to avoid UUID matching issues
                removed_count = await db_space_impl.db_ops.remove_quads_by_subject_uris(
                    space_id, kgtype_uris, graph_id, transaction=transaction
                )
                
                # Return the number of URIs we attempted to delete
                deleted_count = len(kgtype_uris)
                
                self.logger.info(f"Deleted {deleted_count} KGTypes: removed {removed_count} quads")
                return deleted_count
            
            result = await execute_with_transaction(
                self.space_manager, space_id, delete_operation
            )
            
            self.logger.info(f"Successfully deleted {result} KGTypes")
            return result
            
        except Exception as e:
            raise ImplValidationError(f"Failed to delete KGTypes: {e}")
    
    async def create_kgtypes_batch(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Create multiple KGTypes in a single transaction with proper validation.
        
        Args:
            space_id: Space identifier
            kgtypes_data: List of dictionaries containing KGType properties
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the created KGTypes
            
        Raises:
            ImplValidationError: If validation fails
            ImplConflictError: If any URI conflicts with existing objects
        """
        try:
            kgtypes_data = jsonld_document.get("@graph", [])
            self.logger.info(f"Creating {len(kgtypes_data)} KGTypes in space {space_id}, graph {graph_id}")
            
            if not kgtypes_data:
                return []
            
            # Step 1: Convert JSON-LD to GraphObjects using batch utility
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgtype_vitaltype
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
                    space_id, quads, transaction=transaction
                )
                
                if added_count != len(quads):
                    raise RuntimeError(f"Expected to add {len(quads)} quads, but added {added_count}")
                
                self.logger.info(f"Created {len(subject_uris)} KGTypes: added {added_count} quads")
                return subject_uris
            
            result = await execute_with_transaction(
                self.space_manager, space_id, create_operation
            )
            
            self.logger.info(f"Successfully created {len(result)} KGTypes")
            return result
            
        except ImplValidationError:
            raise  # Re-raise validation errors
        except ImplConflictError:
            raise  # Re-raise conflict errors
        except Exception as e:
            raise ImplValidationError(f"Failed to create KGTypes batch: {e}")
    
    async def update_kgtypes_batch(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Update multiple KGTypes in a single transaction with proper validation.
        
        Args:
            space_id: Space identifier
            kgtypes_data: List of dictionaries containing updated KGType properties (must include URIs)
            graph_id: Graph identifier (required)
            
        Returns:
            List of URIs of the updated KGTypes
            
        Raises:
            ImplValidationError: If validation fails or any KGType not found
        """
        try:
            kgtypes_data = jsonld_document.get("@graph", [])
            self.logger.info(f"Updating {len(kgtypes_data)} KGTypes in space {space_id}, graph {graph_id}")
            
            if not kgtypes_data:
                return []
            
            # Step 1: Extract URIs for existence check
            subject_uris = []
            for kgtype_data in kgtypes_data:
                uri = kgtype_data.get('URI') or kgtype_data.get('@id')
                if not uri:
                    raise ImplValidationError("All KGTypes must have a URI for update")
                subject_uris.append(str(uri))
            
            # Step 2: Get existing quads for all objects
            existing_quads = await batch_get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, subject_uris
            )
            
            if not existing_quads:
                raise ImplValidationError("No KGTypes found for update")
            
            # Verify all objects exist by checking which URIs have quads
            existing_uris = set(str(quad[0]) for quad in existing_quads)
            missing_uris = [uri for uri in subject_uris if uri not in existing_uris]
            if missing_uris:
                raise ImplValidationError(f"KGTypes not found: {', '.join(missing_uris)}")
            
            # Step 3: Convert new data to GraphObjects for validation
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document, 
                vitaltype_validator=self.validate_kgtype_vitaltype
            )
            
            # Step 4: Convert to new quads
            new_quads = await batch_graphobjects_to_quads(graph_objects, graph_id)
            
            # Step 5: Execute batch update in transaction (delete old + insert new)
            async def update_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                # Remove existing quads
                removed_count = await db_space_impl.db_ops.remove_rdf_quads_batch(
                    space_id, existing_quads, transaction=transaction
                )
                
                # Add new quads
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, new_quads, transaction=transaction
                )
                
                self.logger.info(f"Updated {len(subject_uris)} KGTypes: removed {removed_count}, added {added_count} quads")
                return subject_uris
            
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated {len(result)} KGTypes")
            return result
            
        except ImplValidationError:
            raise
        except Exception as e:
            raise ImplValidationError(f"Failed to update KGTypes batch: {e}")
    
    async def list_kgtypes(self, space_id: str, graph_id: Optional[str] = None, 
                          page_size: int = 100, offset: int = 0, 
                          filters: Optional[KGTypeFilter] = None) -> tuple[Dict[str, Any], int]:
        """
        List KGTypes with pagination and filtering using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of types per page
            offset: Offset for pagination
            filters: KGTypeFilter object with search criteria
            
        Returns:
            Tuple of (complete JSON-LD document, total count)
        """
        try:
            self.logger.info(f"Listing KGTypes in space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Use db_objects to list objects with filtering
            db_filters = {}
            if filters:
                if filters.vitaltype_filter:
                    db_filters['vitaltype_filter'] = filters.vitaltype_filter
                if filters.search_text:
                    db_filters['search_text'] = filters.search_text
                if filters.subject_uri:
                    db_filters['subject_uri'] = filters.subject_uri
            
            graph_objects, total_count = await db_space_impl.db_objects.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                filters=db_filters
            )
            
            # Use VitalSigns native functionality to convert GraphObjects to JSON-LD document
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            
            # Let VitalSigns handle the complete JSON-LD document creation for multiple objects
            jsonld_document = vitalsigns.to_jsonld_list(graph_objects)
            
            self.logger.info(f"Listed {len(graph_objects)} KGTypes (total: {total_count})")
            return jsonld_document, total_count
            
        except Exception as e:
            self.logger.error(f"Error listing KGTypes: {e}")
            # Use VitalSigns to create empty JSON-LD document on error
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            return vitalsigns.to_jsonld_list([]), 0
    
    async def get_kgtype_by_uri(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single KGType by URI and return as JSON-LD using VitalGraph db_objects.
        
        Args:
            space_id: Space identifier
            uri: KGType URI to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            JSON-LD object dictionary or None if not found
        """
        try:
            self.logger.info(f"Getting KGType {uri} from space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Get quads for this specific URI
            quads = await db_space_impl.db_objects.get_objects_by_uris_batch(
                space_id=space_id,
                subject_uris=[uri],
                graph_id=graph_id
            )
            
            if not quads:
                self.logger.info(f"KGType {uri} not found")
                return None
            
            # Convert quads directly to VitalSigns object using native functionality
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            
            # Extract triples (remove graph context for VitalSigns)
            triples_list = [(s, p, o) for s, p, o, graph_ctx in quads]
            
            # Use VitalSigns to convert triples to GraphObjects
            vitalsigns = VitalSigns()
            graph_objects = vitalsigns.from_triples_list(triples_list)
            
            if not graph_objects:
                self.logger.info(f"KGType {uri} could not be converted to VitalSigns object")
                return None
            
            # Use VitalSigns native JSON-LD conversion directly
            graph_object = graph_objects[0]
            
            # Let VitalSigns handle the complete JSON-LD document creation
            jsonld_document = graph_object.to_jsonld()
            
            self.logger.debug(f"Successfully converted KGType {uri} to JSON-LD using VitalSigns native functionality")
            return jsonld_document
            
        except Exception as e:
            self.logger.error(f"Error getting KGType by URI: {e}")
            return None
    
    async def get_kgtypes_by_uris(self, space_id: str, uris: List[str], graph_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get multiple KGTypes by URI list and return as complete JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            uris: List of KGType URIs to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            Complete JSON-LD document with @context and @graph containing all KGTypes
        """
        try:
            self.logger.info(f"Getting {len(uris)} KGTypes from space {space_id}, graph {graph_id}")
            
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
            
            self.logger.info(f"Retrieved {len(graph_objects)} KGTypes")
            return jsonld_document
            
        except Exception as e:
            self.logger.error(f"Error getting KGTypes by URIs: {e}")
            # Use VitalSigns to create empty JSON-LD document on error
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            return vitalsigns.to_jsonld_list([])
