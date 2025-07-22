from typing import Dict, Optional, Any, List
from fastapi import HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm


class VitalGraphAPI:
    def __init__(self, auth_handler, db_impl=None):
        self.auth = auth_handler
        self.db = db_impl
    
    async def health(self):
        """Health check endpoint"""
        return {"status": "ok"}
    
    async def login(self, form_data: OAuth2PasswordRequestForm):
        """Login endpoint"""
        user = self.auth.authenticate_user(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # In a production app, we would use JWT tokens here
        # For simplicity, we're just returning a simple token
        token = f"user-{form_data.username}-token"
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "username": user["username"],
            "full_name": user["full_name"],
            "email": user["email"],
            "profile_image": user["profile_image"],
            "role": user["role"]
        }
    
    async def logout(self, request: Request, current_user: Dict):
        """Logout endpoint"""
        request.session.clear()
        return {"status": "logged out"}
    
    async def refresh_database(self) -> Dict[str, Any]:
        """Refresh database connection."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        success = await self.db.refresh()
        if success:
            return {"status": "database refreshed successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database refresh failed"
            )
    
    # Space management methods
    async def list_spaces(self, current_user: Dict) -> List[Dict[str, Any]]:
        """List graph spaces for the authenticated user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            spaces = await self.db.list_spaces()
            return spaces  # Return list directly, not wrapped in dict
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list spaces: {str(e)}"
            )
    
    async def add_space(self, space_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Add a new space."""
        print(f"➕ API add_space called:")
        print(f"   User: {current_user.get('username', 'unknown')}")
        print(f"   Incoming space_data: {space_data}")
        
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            created_space = await self.db.add_space(space_data)
            if created_space:
                print(f"   ✅ Created space result: {created_space}")
                return created_space  # Return the created space data directly
            else:
                print(f"   ❌ Add failed - could not create space")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to add space"
                )
        except ValueError as e:
            # Handle uniqueness constraint violations
            print(f"   ❌ Validation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            print(f"   ❌ Add exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error adding space: {str(e)}"
            )
    
    async def update_space(self, space_id: str, space_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Update an existing space."""
        print(f"🔄 API update_space called:")
        print(f"   Space ID: {space_id}")
        print(f"   User: {current_user.get('username', 'unknown')}")
        print(f"   Incoming space_data: {space_data}")
        
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            updated_space = await self.db.update_space(space_id, space_data)
            if updated_space:
                print(f"   ✅ Updated space result: {updated_space}")
                return updated_space  # Return the updated space data directly
            else:
                print(f"   ❌ Update failed - space not found or update failed")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Space not found or update failed"
                )
        except ValueError as e:
            # Handle uniqueness constraint violations
            print(f"   ❌ Validation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            print(f"   ❌ Update exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating space: {str(e)}"
            )
    
    async def delete_space(self, space_id: str, current_user: Dict) -> Dict[str, Any]:
        """Delete a space."""
        print(f"🗑️ API delete_space called:")
        print(f"   Space ID: {space_id}")
        print(f"   User: {current_user.get('username', 'unknown')}")
        
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            print(f"   📋 Calling db.remove_space({space_id})...")
            success = await self.db.remove_space(space_id)
            print(f"   📋 Database remove_space result: {success}")
            
            if success:
                result = {"message": "space deleted successfully", "id": int(space_id)}
                print(f"   ✅ Delete successful: {result}")
                return result
            else:
                print(f"   ❌ Delete failed - space not found or deletion failed")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Space not found or deletion failed"
                )
        except HTTPException:
            raise
        except Exception as e:
            print(f"   ❌ Delete exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting space: {str(e)}"
            )
    
    async def get_space_by_id(self, space_id: str, current_user: Dict) -> Dict[str, Any]:
        """Get a specific space by ID."""
        print(f"🔍 API get_space_by_id called:")
        print(f"   Space ID: {space_id}")
        print(f"   User: {current_user.get('username', 'unknown')}")
        
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            space = await self.db.get_space_by_id(space_id)
            if space:
                print(f"   ✅ Found space: {space}")
                return space  # Return space data directly, not wrapped in dict
            else:
                print(f"   ❌ Space not found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Space with ID {space_id} not found"
                )
        except HTTPException:
            raise
        except Exception as e:
            print(f"   ❌ Get exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error getting space: {str(e)}"
            )
    
    async def filter_spaces_by_name(self, name_filter: str, current_user: Dict) -> List[Dict[str, Any]]:
        """Filter spaces by name for the authenticated user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            spaces = await self.db.filter_spaces_by_name(name_filter)
            return spaces  # Return list directly, not wrapped in dict
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to filter spaces: {str(e)}"
            )
    
    # User management methods
    async def list_users(self, current_user: Dict) -> List[Dict[str, Any]]:
        """List users for the authenticated user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            users = await self.db.list_users()
            return users  # Return list directly, not wrapped in dict
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list users: {str(e)}"
            )
    
    async def add_user(self, user_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Add a new user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            created_user = await self.db.add_user(user_data)
            if created_user:
                print(f"   ✅ Created user result: {created_user}")
                return created_user  # Return the created user data directly
            else:
                print(f"   ❌ Add failed - could not create user")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to add user"
                )
        except ValueError as e:
            # Handle uniqueness constraint violations
            print(f"   ❌ Validation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            print(f"   ❌ Add exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error adding user: {str(e)}"
            )
    
    async def update_user(self, user_id: str, user_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Update an existing user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            updated_user = await self.db.update_user(user_id, user_data)
            if updated_user:
                return updated_user  # Return the updated user data directly
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found or update failed"
                )
        except ValueError as e:
            # Handle uniqueness constraint violations
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating user: {str(e)}"
            )
    
    async def delete_user(self, user_id: str, current_user: Dict) -> Dict[str, Any]:
        """Delete a user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            success = await self.db.remove_user(user_id)
            if success:
                return {"message": "user deleted successfully", "id": int(user_id)}
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found or deletion failed"
                )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting user: {str(e)}"
            )
    
    async def get_user_by_id(self, user_id: str, current_user: Dict) -> Dict[str, Any]:
        """Get a specific user by ID."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            user = await self.db.get_user_by_id(user_id)
            if user:
                return user  # Return user object directly for FastAPI validation
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with ID {user_id} not found"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error getting user: {str(e)}"
            )
    
    async def filter_users_by_name(self, name_filter: str, current_user: Dict) -> List[Dict[str, Any]]:
        """Filter users by name for the authenticated user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            users = await self.db.filter_users_by_name(name_filter)
            return users  # Return list directly, not wrapped in dict
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error filtering users: {str(e)}"
            )
    
    # SPARQL query execution
    async def execute_sparql_query(self, query: str, current_user: Dict) -> Dict[str, Any]:
        """Execute a SPARQL query."""
        # For now, return dummy response until SPARQL integration is implemented
        return {
            "results": {
                "bindings": [
                    {"subject": {"value": "http://example.org/subject1"}},
                    {"subject": {"value": "http://example.org/subject2"}}
                ]
            },
            "query": query,
            "user": current_user["username"]
        }
    
    # Database administration methods
    async def get_database_info(self, current_user: Dict) -> Dict[str, Any]:
        """Get database information."""
        if not self.db:
            return {"status": "database not configured"}
        
        try:
            info = await self.db.get_database_info()
            return info
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error getting database info: {str(e)}"
            )



