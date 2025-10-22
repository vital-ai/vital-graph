from typing import Dict, Optional, Any, List
from fastapi import HTTPException, status, Request, Body
from fastapi.security import OAuth2PasswordRequestForm


class VitalGraphAPI:
    def __init__(self, auth_handler, db_impl=None, space_manager=None):
        self.auth = auth_handler
        self.db = db_impl
        self.space_manager = space_manager
    
    async def health(self):
        """Health check endpoint"""
        return {"status": "ok"}
    
    async def login(self, form_data: OAuth2PasswordRequestForm):
        """Enhanced login with JWT tokens"""
        user = self.auth.authenticate_user(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Create JWT tokens
        tokens = self.auth.create_tokens(user)
        
        return {
            **tokens,
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
    
    async def refresh_token(self, refresh_token: str = Body(..., embed=True)):
        """Refresh access token using refresh token"""
        try:
            payload = self.auth.jwt_auth.verify_token(refresh_token, "refresh")
            username = payload.get("sub")
            
            if username not in self.auth.users_db:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )
            
            user = self.auth.users_db[username]
            tokens = self.auth.create_tokens(user)
            
            return {
                "access_token": tokens["access_token"],
                "token_type": "bearer",
                "expires_in": tokens["expires_in"]
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
    
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
        """Add a new space with full lifecycle management (database record + tables)."""
        print(f"➕ API add_space called:")
        print(f"   User: {current_user.get('username', 'unknown')}")
        print(f"   Incoming space_data: {space_data}")
        
        if self.space_manager is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Space Manager not configured"
            )
        
        try:
            # Extract parameters for Space Manager method
            space_id = space_data.get('space')
            space_name = space_data.get('space_name')
            space_description = space_data.get('space_description')
            
            # Use Space Manager for full lifecycle management (record + tables)
            success = await self.space_manager.create_space_with_tables(space_id, space_name, space_description)
            
            if success:
                # Return the created space data by querying the database
                spaces = await self.db.list_spaces()
                created_space = next((s for s in spaces if s.get('space') == space_id), None)
            else:
                created_space = None
            if created_space:
                print(f"   ✅ Created space with tables result: {created_space}")
                return created_space  # Return the created space data directly
            else:
                print(f"   ❌ Add failed - could not create space with tables")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to add space with tables"
                )
        except ValueError as e:
            # Handle validation errors (e.g., space ID too long, uniqueness violations)
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
        """Delete a space with full lifecycle management (tables + database record)."""
        print(f"🗑️ API delete_space called:")
        print(f"   Space ID: {space_id}")
        print(f"   User: {current_user.get('username', 'unknown')}")
        
        if self.space_manager is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Space Manager not configured"
            )
        
        try:
            # First, convert database ID to space identifier if needed
            # Check if space_id is a database ID (numeric) or space identifier (string)
            actual_space_id = space_id
            if isinstance(space_id, int) or (isinstance(space_id, str) and space_id.isdigit()):
                # It's a database ID, need to look up the space identifier
                db_spaces = await self.space_manager.db_impl.list_spaces()
                space_record = next((s for s in db_spaces if str(s.get('id')) == str(space_id)), None)
                if space_record:
                    actual_space_id = space_record.get('space')
                    print(f"   🔄 Converted database ID {space_id} to space identifier '{actual_space_id}'")
                else:
                    print(f"   ❌ No space found with database ID {space_id}")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Space with ID {space_id} not found"
                    )
            
            print(f"   📋 Calling space_manager.delete_space_with_tables({actual_space_id})...")
            success = await self.space_manager.delete_space_with_tables(actual_space_id)
            print(f"   📋 Space Manager delete result: {success}")
            
            if success:
                result = {"message": "space deleted successfully with tables", "id": space_id}
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
        if not self.auth:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Auth system not configured"
            )
        
        try:
            # Return users from the auth system's users_db, not from database tables
            users = []
            for username, user_data in self.auth.users_db.items():
                # Remove password from response for security
                user_dict = {k: v for k, v in user_data.items() if k != 'password'}
                # Add an ID field for consistency with frontend expectations
                user_dict['id'] = username
                users.append(user_dict)
            return users
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
        if not self.auth:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Auth system not configured"
            )
        
        try:
            # Look up user in auth system's users_db by username (which is the ID)
            if user_id in self.auth.users_db:
                user_data = self.auth.users_db[user_id]
                # Remove password from response for security
                user_dict = {k: v for k, v in user_data.items() if k != 'password'}
                # Add an ID field for consistency with frontend expectations
                user_dict['id'] = user_id
                return user_dict
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



