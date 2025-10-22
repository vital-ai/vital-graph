"""
Mock implementation of SpacesEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- Real space manager operations for space lifecycle management
- VitalSigns native functionality for data conversions
- Proper space metadata handling
- No mock data generation - all operations use real space manager
"""

import time
from typing import Dict, Any, List, Optional
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.spaces_model import (
    Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse
)


class MockSpacesEndpoint(MockBaseEndpoint):
    """Mock implementation of SpacesEndpoint."""
    
    def list_spaces(self, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        List all spaces using real space manager operations.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse with real space data
        """
        self._log_method_call("list_spaces", tenant=tenant)
        
        try:
            # Get spaces from space manager
            if not self.space_manager:
                return SpacesListResponse(
                    spaces=[],
                    total_count=0,
                    page_size=10,
                    offset=0
                )
            
            # Get all spaces from space manager
            all_mock_spaces = self.space_manager.list_spaces()
            
            # Filter by tenant if specified
            if tenant:
                filtered_mock_spaces = [space for space in all_mock_spaces if space.tenant == tenant]
            else:
                filtered_mock_spaces = all_mock_spaces
            
            # Convert MockSpace objects to Space model objects
            spaces = []
            for mock_space in filtered_mock_spaces:
                space = Space(
                    id=mock_space.space_id,
                    space=mock_space.name,
                    space_name=mock_space.name,
                    space_description=getattr(mock_space, 'description', None),
                    tenant=mock_space.tenant,
                    update_time=mock_space.updated_at.isoformat() if hasattr(mock_space, 'updated_at') else None
                )
                spaces.append(space)
            
            return SpacesListResponse(
                spaces=spaces,
                total_count=len(spaces),
                page_size=10,
                offset=0
            )
            
        except Exception as e:
            self.logger.error(f"Error listing spaces: {e}")
            return SpacesListResponse(
                spaces=[],
                total_count=0,
                page_size=10,
                offset=0
            )
    
    def add_space(self, space: Space) -> SpaceCreateResponse:
        """
        Add a new space using real space manager operations.
        
        Args:
            space: Space object to create
            
        Returns:
            SpaceCreateResponse with real creation results
        """
        self._log_method_call("add_space", space=space)
        
        try:
            # Create the space in the space manager
            if not self.space_manager:
                return SpaceCreateResponse(
                    created_count=0,
                    created_uris=[],
                    message="Space manager not available"
                )
            
            created_space = self.space_manager.create_space(
                name=space.space,
                tenant=space.tenant,
                description=space.space_description
            )
            
            return SpaceCreateResponse(
                created_count=1,
                created_uris=[created_space.name],
                message="Space created successfully"
            )
            
        except Exception as e:
            self.logger.error(f"Error creating space: {e}")
            return SpaceCreateResponse(
                created_count=0,
                created_uris=[],
                message=str(e)
            )
    
    def get_space(self, space_id: str) -> Space:
        """
        Get a space by ID using real space manager operations.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Space object with real space data
        """
        self._log_method_call("get_space", space_id=space_id)
        
        try:
            # Get space from space manager
            if not self.space_manager:
                # Return minimal space object for non-existent space manager
                current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return Space(
                    id=0,
                    tenant="unknown",
                    space=space_id,
                    space_name=f"Space {space_id}",
                    space_description=f"Space {space_id}",
                    update_time=current_time
                )
            
            # Get space from space manager
            mock_space = self.space_manager.get_space(space_id)
            if mock_space:
                # Convert MockSpace to Space model
                return Space(
                    id=mock_space.space_id,
                    space=mock_space.name,
                    space_name=mock_space.name,
                    space_description=getattr(mock_space, 'description', None),
                    tenant=mock_space.tenant,
                    update_time=mock_space.updated_at.isoformat() if hasattr(mock_space, 'updated_at') else None
                )
            else:
                # Return minimal space object for non-existent space
                current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return Space(
                    id=0,
                    tenant="unknown",
                    space=space_id,
                    space_name=f"Space {space_id}",
                    space_description=f"Space {space_id} not found",
                    update_time=current_time
                )
                
        except Exception as e:
            self.logger.error(f"Error getting space {space_id}: {e}")
            current_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return Space(
                id=0,
                tenant="unknown",
                space=space_id,
                space_name=f"Space {space_id}",
                space_description=f"Error: {str(e)}",
                update_time=current_time
            )
    
    def update_space(self, space_id: str, space: Space) -> SpaceUpdateResponse:
        """
        Update a space using real space manager operations.
        
        Args:
            space_id: Space identifier
            space: Updated space object
            
        Returns:
            SpaceUpdateResponse with real update results
        """
        self._log_method_call("update_space", space_id=space_id, space=space)
        
        try:
            # Update space in space manager
            if not self.space_manager:
                return SpaceUpdateResponse(
                    updated_count=0,
                    updated_uri=None,
                    message="Space manager not available"
                )
            
            # Update space (implementation depends on space manager capabilities)
            # Convert space_id to int if needed and extract update parameters
            try:
                space_id_int = int(space_id) if isinstance(space_id, str) and space_id.isdigit() else space_id
            except (ValueError, TypeError):
                # If space_id is not numeric, try to find the space by name
                existing_space = self.space_manager.get_space(space_id)
                space_id_int = existing_space.space_id if existing_space else None
            
            if space_id_int is None:
                return SpaceUpdateResponse(
                    updated_uri=None,
                    message=f"Could not find space {space_id}"
                )
            
            # Extract update parameters from Space object
            update_params = {
                'name': space.space_name,
                'description': space.space_description,
                'tenant': space.tenant
            }
            
            updated = self.space_manager.update_space(space_id_int, **update_params)
            if updated:
                return SpaceUpdateResponse(
                    updated_uri=space_id,
                    message="Space updated successfully"
                )
            else:
                return SpaceUpdateResponse(
                    updated_uri=space_id,
                    message=f"Space {space_id} not found"
                )
                
        except Exception as e:
            self.logger.error(f"Error updating space {space_id}: {e}")
            return SpaceUpdateResponse(
                updated_uri=space_id,
                message=str(e)
            )
    
    def delete_space(self, space_id: str) -> SpaceDeleteResponse:
        """
        Delete a space using real space manager operations.
        
        Args:
            space_id: Space identifier
            
        Returns:
            SpaceDeleteResponse with real deletion results
        """
        self._log_method_call("delete_space", space_id=space_id)
        
        try:
            # Delete space from space manager
            if not self.space_manager:
                return SpaceDeleteResponse(
                    deleted_count=0,
                    message="Space manager not available"
                )
            
            # Delete space (implementation depends on space manager capabilities)
            # First, find the space to get its integer ID
            existing_space = self.space_manager.get_space(space_id)
            if not existing_space:
                return SpaceDeleteResponse(
                    deleted_count=0,
                    message=f"Space {space_id} not found"
                )
            
            # Delete using the integer space_id
            deleted = self.space_manager.delete_space(existing_space.space_id)
            if deleted:
                return SpaceDeleteResponse(
                    deleted_count=1,
                    message="Space deleted successfully"
                )
            else:
                return SpaceDeleteResponse(
                    deleted_count=0,
                    message=f"Space {space_id} not found"
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting space {space_id}: {e}")
            return SpaceDeleteResponse(
                deleted_count=0,
                message=str(e)
            )
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        Filter spaces by name using real space manager operations.
        
        Args:
            name_filter: Name filter term
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse with filtered space data
        """
        self._log_method_call("filter_spaces", name_filter=name_filter, tenant=tenant)
        
        try:
            # Get spaces from space manager
            if not self.space_manager:
                return SpacesListResponse(
                    spaces=[],
                    total_count=0,
                    page_size=10,
                    offset=0
                )
            
            # Get all spaces and filter
            all_mock_spaces = self.space_manager.list_spaces()
            
            # Apply filters and convert to Space objects
            filtered_spaces = []
            for mock_space in all_mock_spaces:
                # Filter by name
                if name_filter.lower() in mock_space.name.lower():
                    # Filter by tenant if specified
                    if tenant is None or mock_space.tenant == tenant:
                        # Convert MockSpace to Space model
                        space = Space(
                            id=mock_space.space_id,
                            space=mock_space.name,
                            space_name=mock_space.name,
                            space_description=getattr(mock_space, 'description', None),
                            tenant=mock_space.tenant,
                            update_time=mock_space.updated_at.isoformat() if hasattr(mock_space, 'updated_at') else None
                        )
                        filtered_spaces.append(space)
            
            return SpacesListResponse(
                spaces=filtered_spaces,
                total_count=len(filtered_spaces),
                page_size=10,
                offset=0
            )
            
        except Exception as e:
            self.logger.error(f"Error filtering spaces: {e}")
            return SpacesListResponse(
                spaces=[],
                total_count=0,
                page_size=10,
                offset=0
            )
