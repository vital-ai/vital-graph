"""
Files Implementation Layer

Implementation of file operations for the VitalGraph Files endpoint.
Follows the same pattern as Objects, KGEntities, KGFrames, and KGTypes endpoints.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class FilesImpl:
    """Implementation layer for Files operations."""
    
    def __init__(self, space_manager):
        """
        Initialize Files implementation.
        
        Args:
            space_manager: SpaceManager instance for database access
        """
        self.space_manager = space_manager
        self.logger = logger
    
    async def list_files(self, space_id: str, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0,
                        file_filter: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
        """
        List FileNode objects with pagination and filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of files per page
            offset: Offset for pagination
            file_filter: Filter keyword for file names
            
        Returns:
            Tuple of (JSON-LD document, total count)
        """
        try:
            self.logger.info(f"Listing files in space {space_id}, graph {graph_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Build filters for FileNode objects
            # Note: VitalSigns FileNode uses 'vital#FileNode' not 'vital-core#FileNode'
            filters = {
                'vitaltype_filter': 'http://vital.ai/ontology/vital#FileNode'
            }
            
            if file_filter:
                filters['search_text'] = file_filter
            
            # Query for FileNode objects with pagination
            if not graph_id:
                raise ValueError("graph_id is required for listing files")
            
            graph_objects, total_count = await db_space_impl.db_objects.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                filters=filters
            )
            
            # Use VitalSigns native functionality to convert GraphObjects to JSON-LD document
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Let VitalSigns handle the complete JSON-LD document creation
            jsonld_document = GraphObject.to_jsonld_list(graph_objects)
            
            self.logger.info(f"Listed {len(graph_objects)} files (total: {total_count})")
            return jsonld_document, total_count
            
        except Exception as e:
            self.logger.error(f"Error listing files: {e}")
            raise
    
    async def get_file_by_uri(self, space_id: str, uri: str, graph_id: Optional[str] = None):
        """
        Get a single FileNode by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI
            graph_id: Graph identifier (optional)
            
        Returns:
            FileNode GraphObject
        """
        try:
            self.logger.info(f"Getting file {uri} from space {space_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Get the file object (returns GraphObject)
            graph_object = await db_space_impl.db_objects.get_object_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not graph_object:
                raise ValueError(f"File not found: {uri}")
            
            self.logger.info(f"Retrieved file {uri}")
            return graph_object
            
        except Exception as e:
            self.logger.error(f"Error getting file {uri}: {e}")
            raise
    
    async def get_files_by_uris(self, space_id: str, uri_list: List[str], 
                               graph_id: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
        """
        Get multiple FileNode objects by URI list.
        
        Args:
            space_id: Space identifier
            uri_list: List of file URIs
            graph_id: Graph identifier (optional)
            
        Returns:
            Tuple of (JSON-LD document, count)
        """
        try:
            self.logger.info(f"Getting {len(uri_list)} files from space {space_id}")
            
            # Get database space implementation
            from .impl_utils import get_db_space_impl
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            
            # Get the file objects
            graph_objects = []
            for uri in uri_list:
                try:
                    graph_object = await db_space_impl.db_objects.get_object_by_uri(
                        space_id=space_id,
                        uri=uri,
                        graph_id=graph_id
                    )
                    if graph_object:
                        graph_objects.append(graph_object)
                except Exception as e:
                    self.logger.warning(f"Could not retrieve file {uri}: {e}")
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_document = GraphObject.to_jsonld_list(graph_objects)
            
            self.logger.info(f"Retrieved {len(graph_objects)} files")
            return jsonld_document, len(graph_objects)
            
        except Exception as e:
            self.logger.error(f"Error getting files by URIs: {e}")
            raise
    
    async def create_files(self, space_id: str, jsonld_document: Dict[str, Any], graph_id: str) -> List[str]:
        """
        Create FileNode objects in the database.
        
        Args:
            space_id: Space identifier
            jsonld_document: JSON-LD document with FileNode objects
            graph_id: Graph identifier (required)
            
        Returns:
            List of created file URIs
        """
        try:
            from .impl_utils import get_db_space_impl, batch_check_subject_uri_conflicts
            from ...utils.data_format_utils import batch_jsonld_to_graphobjects, batch_graphobjects_to_quads
            
            objects_data = jsonld_document.get("@graph", [])
            self.logger.info(f"Creating {len(objects_data)} file nodes in space {space_id}, graph {graph_id}")
            
            if not objects_data:
                return []
            
            # Convert JSON-LD to GraphObjects (FileNode objects)
            # Note: VitalSigns FileNode uses 'vital#FileNode' not 'vital-core#FileNode'
            graph_objects = await batch_jsonld_to_graphobjects(
                jsonld_document,
                vitaltype_validator=lambda vt: vt == 'http://vital.ai/ontology/vital#FileNode'
            )
            
            # Check for URI conflicts
            subject_uris = [str(obj.URI) for obj in graph_objects]
            conflicts = await batch_check_subject_uri_conflicts(
                self.space_manager, space_id, subject_uris
            )
            if conflicts:
                raise ValueError(f"Files with URIs already exist: {', '.join(conflicts)}")
            
            # Convert to quads
            quads = await batch_graphobjects_to_quads(graph_objects, graph_id)
            
            # Store in database with transaction
            async def create_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, quads, auto_commit=False, transaction=transaction
                )
                
                if added_count != len(quads):
                    raise RuntimeError(f"Expected to add {len(quads)} quads, but added {added_count}")
                
                self.logger.info(f"Created {len(subject_uris)} file nodes: added {added_count} quads")
                return subject_uris
            
            from .impl_utils import execute_with_transaction
            result = await execute_with_transaction(
                self.space_manager, space_id, create_operation
            )
            
            self.logger.info(f"Successfully created {len(result)} file nodes")
            return result
            
        except Exception as e:
            self.logger.error(f"Error creating files: {e}")
            raise
    
    async def update_files(self, space_id: str, file_nodes: List, graph_id: str) -> List[str]:
        """
        Update FileNode objects in the database.
        
        Args:
            space_id: Space identifier
            file_nodes: List of FileNode GraphObjects to update
            graph_id: Graph identifier (required)
            
        Returns:
            List of updated file URIs
        """
        try:
            from .impl_utils import get_db_space_impl
            from ...utils.data_format_utils import batch_graphobjects_to_quads
            
            self.logger.info(f"Updating {len(file_nodes)} file nodes in space {space_id}, graph {graph_id}")
            
            if not file_nodes:
                return []
            
            # Use the GraphObjects directly
            graph_objects = file_nodes
            
            subject_uris = [str(obj.URI) for obj in graph_objects]
            
            # Convert to quads
            quads = await batch_graphobjects_to_quads(graph_objects, graph_id)
            
            # Update in database (delete old + insert new) with transaction
            async def update_operation(transaction):
                from .impl_utils import get_db_space_impl
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                # Delete existing quads for these URIs
                await db_space_impl.db_ops.remove_quads_by_subject_uris(
                    space_id, subject_uris, graph_id=graph_id, transaction=transaction
                )
                
                # Insert new quads
                added_count = await db_space_impl.db_ops.add_rdf_quads_batch(
                    space_id, quads, auto_commit=False, transaction=transaction
                )
                
                self.logger.info(f"Updated {len(subject_uris)} file nodes: added {added_count} quads")
                return subject_uris
            
            from .impl_utils import execute_with_transaction
            result = await execute_with_transaction(
                self.space_manager, space_id, update_operation
            )
            
            self.logger.info(f"Successfully updated {len(result)} file nodes")
            return result
            
        except Exception as e:
            self.logger.error(f"Error updating files: {e}")
            raise
    
    async def delete_files(self, space_id: str, uris: List[str], graph_id: str) -> int:
        """
        Delete FileNode objects from the database.
        
        Args:
            space_id: Space identifier
            uris: List of file URIs to delete
            graph_id: Graph identifier (required)
            
        Returns:
            Number of files successfully deleted
        """
        try:
            from .impl_utils import get_existing_quads_for_uris, execute_with_transaction, get_db_space_impl
            
            self.logger.info(f"Deleting {len(uris)} file nodes from space {space_id}, graph {graph_id}")
            
            # Step 1: Get existing quads for all files
            existing_quads = await get_existing_quads_for_uris(
                self.space_manager, space_id, graph_id, uris
            )
            
            if not existing_quads:
                self.logger.warning("No files found for deletion")
                return 0
            
            # Step 2: Execute batch deletion in transaction
            async def delete_operation(transaction):
                db_space_impl = await get_db_space_impl(self.space_manager, space_id)
                
                removed_count = await db_space_impl.db_ops.remove_rdf_quads_batch(
                    space_id, existing_quads, auto_commit=False, transaction=transaction
                )
                
                # Count unique subjects deleted
                deleted_subjects = set(str(quad[0]) for quad in existing_quads)
                deleted_count = len(deleted_subjects)
                
                self.logger.info(f"Deleted {deleted_count} file nodes: removed {removed_count} quads")
                return deleted_count
            
            result = await execute_with_transaction(
                self.space_manager, space_id, delete_operation
            )
            
            self.logger.info(f"Successfully deleted {result} file nodes")
            return result
            
        except Exception as e:
            self.logger.error(f"Error deleting files: {e}")
            raise
