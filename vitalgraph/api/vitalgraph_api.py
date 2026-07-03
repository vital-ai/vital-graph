from typing import Dict, Optional, Any, List
from fastapi import HTTPException, status, Request, Body
from fastapi.security import OAuth2PasswordRequestForm
import logging

from vitalgraph.auth.audit import emit_audit_event

logger = logging.getLogger(__name__)


class VitalGraphAPI:
    def __init__(self, auth_handler, db_impl=None, space_manager=None, signal_manager=None):
        self.auth = auth_handler
        self.db = db_impl
        self.space_manager = space_manager
        self.signal_manager = signal_manager
    
    async def health(self):
        """Health check endpoint"""
        return {"status": "ok"}
    
    async def login(self, form_data: OAuth2PasswordRequestForm, token_expiry_seconds: Optional[int] = None):
        """Enhanced login with JWT tokens"""
        user = await self.auth.authenticate_user(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Validate token_expiry_seconds if provided (for testing)
        if token_expiry_seconds is not None:
            MAX_EXPIRY_SECONDS = 1800  # 30 minutes
            if token_expiry_seconds > MAX_EXPIRY_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"token_expiry_seconds cannot exceed {MAX_EXPIRY_SECONDS} seconds (30 minutes)"
                )
            if token_expiry_seconds < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="token_expiry_seconds must be at least 1 second"
                )
            logger.info(f"Creating tokens with custom expiry: {token_expiry_seconds} seconds")
        
        # Update last login
        if self.db:
            await self.db.update_last_login(user["username"])
        
        # Create JWT tokens with optional custom expiry
        tokens = self.auth.create_tokens(user, token_expiry_seconds=token_expiry_seconds)
        
        return {
            **tokens,
            "username": user["username"],
            "full_name": user.get("full_name", ""),
            "email": user.get("email", ""),
            "profile_image": user.get("profile_image", ""),
            "role": user.get("role", "user")
        }
    
    async def logout(self, request: Request, current_user: Dict):
        """Logout endpoint"""
        request.session.clear()
        emit_audit_event("auth.logout", current_user.get("username", "unknown"))
        return {"status": "logged out"}
    
    async def refresh_token(self, refresh_token: str = Body(..., embed=True)):
        """Refresh access token using refresh token"""
        try:
            payload = self.auth.jwt_auth.verify_token(refresh_token, "refresh")
            username = payload.get("sub")
            
            if not username:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token"
                )
            
            # Re-fetch user from DB to get current role/spaces
            user = await self.auth._get_user_from_db(username)
            if user is None:
                # Fallback to claims from the refresh token
                user = {
                    "username": username,
                    "full_name": payload.get("full_name", ""),
                    "email": payload.get("email", ""),
                    "role": payload.get("role", "user"),
                    "spaces": payload.get("spaces", {}),
                    "token_version": payload.get("token_version", 0),
                }
            
            # Check if user is still active
            if not user.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is deactivated"
                )
            
            # Check token_version hasn't been bumped (tokens invalidated)
            token_ver_in_jwt = payload.get("token_version", 0)
            token_ver_in_db = user.get("token_version", 0)
            if token_ver_in_jwt < token_ver_in_db:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked"
                )
            
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
        if self.space_manager is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Space Manager not configured"
            )
        
        try:
            logger.debug(f"API REQUEST DEBUG: self.space_manager = {self.space_manager}")
            logger.debug(f"API REQUEST DEBUG: space_manager type: {type(self.space_manager)}")
            logger.debug(f"API REQUEST DEBUG: VitalGraphAPI object id: {id(self)}")
            logger.debug(f"API REQUEST DEBUG: VitalGraphAPI object: {self}")

            if self.space_manager is None:
                logger.error(f"API REQUEST ERROR: space_manager is None during request")
                logger.debug(f"API REQUEST DEBUG: This suggests a different API instance is being used")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Space Manager not configured"
                )
            
            logger.debug(f"About to call space_manager.list_space_records()")
            logger.debug(f"space_manager initialized: {getattr(self.space_manager, '_initialized', 'unknown')}")
            
            # Use space_manager to list spaces (works with any backend)
            space_records = self.space_manager.list_space_records()
            logger.debug(f"Got {len(space_records)} space records")
            
            # Filter spaces based on user access
            user_role = current_user.get('role', 'user')
            user_spaces = current_user.get('spaces', {})
            
            spaces = []
            for space_record in space_records:
                logger.debug(f"Processing space_record: {space_record}")
                # Admin sees all; non-admin sees only assigned (or wildcard) spaces
                if user_role == 'admin' or '*' in user_spaces or space_record.space_id in user_spaces:
                    spaces.append({
                        'space': space_record.space_id,
                        'space_name': getattr(space_record.space_impl, 'space_name', space_record.space_id),
                        'space_description': getattr(space_record.space_impl, 'space_description', ''),
                        'exists': True
                    })
            logger.debug(f"Returning {len(spaces)} spaces")
            return spaces
        except Exception as e:
            logger.error(f"Error in list_spaces: {e}", exc_info=True)
            logger.debug(f"Exception type: {type(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list spaces: {str(e)}"
            )
    
    async def add_space(self, space_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Add a new space with full lifecycle management (database record + tables)."""
        logger.info(f"add_space called for user: {current_user.get('username', 'unknown')}")
        logger.debug(f"Incoming space_data: {space_data}")
        
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
                # Return the created space data - use space_manager instead of db directly
                try:
                    # Get space info from space manager
                    space_record = self.space_manager.get_space(space_id)
                    if space_record:
                        created_space = {
                            'space': space_id,
                            'space_name': space_name,
                            'space_description': space_description,
                            'exists': True
                        }
                    else:
                        created_space = None
                except Exception as e:
                    logger.warning(f"Could not retrieve created space info: {e}")
                    # Still return success even if we can't get the details
                    created_space = {
                        'space': space_id,
                        'space_name': space_name,
                        'space_description': space_description,
                        'exists': True
                    }
            else:
                created_space = None
            if created_space:
                logger.info(f"Created space with tables: {created_space}")
                return created_space  # Return the created space data directly
            else:
                logger.error(f"Add failed - could not create space with tables")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to add space with tables"
                )
        except ValueError as e:
            # Handle validation errors (e.g., space ID too long, uniqueness violations)
            logger.error(f"Validation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"Add exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error adding space: {str(e)}"
            )
    
    async def update_space(self, space_id: str, space_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Update an existing space."""
        logger.info(f"update_space called for space_id: {space_id}, user: {current_user.get('username', 'unknown')}")
        logger.debug(f"Incoming space_data: {space_data}")
        
        if not self.space_manager:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Space manager not configured"
            )
        
        try:
            # Check if space exists (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                logger.error(f"Space not found: {space_id}")
                raise HTTPException(status_code=404, detail="Space not found")
            
            # Persist to database
            backend = self.space_manager.space_backend or self.space_manager.db_impl
            if backend and hasattr(backend, 'update_space_metadata'):
                db_ok = await backend.update_space_metadata(space_id, space_data)
                if not db_ok:
                    logger.warning(f"update_space: DB persist failed for '{space_id}'")

            # Update in-memory cache too
            if hasattr(space_record.space_impl, 'space_name') and 'space_name' in space_data:
                space_record.space_impl.space_name = space_data['space_name']
            if hasattr(space_record.space_impl, 'space_description') and 'space_description' in space_data:
                space_record.space_impl.space_description = space_data['space_description']
            
            updated_space = {
                'space': space_id,
                'space_name': getattr(space_record.space_impl, 'space_name', space_id),
                'space_description': getattr(space_record.space_impl, 'space_description', ''),
                'exists': True
            }
            logger.info(f"Updated space: {updated_space}")
            return updated_space
        except Exception as e:
            logger.error(f"Update exception: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating space: {str(e)}"
            )
    
    async def delete_space(self, space_id: str, current_user: Dict) -> Dict[str, Any]:
        """Delete a space with full lifecycle management (tables + database record)."""
        logger.info(f"delete_space called for space_id: {space_id}, user: {current_user.get('username', 'unknown')}")
        
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
                # For generic backends, numeric IDs are not supported - use space_id as-is
                logger.warning(f"Numeric space ID {space_id} not supported with generic backends, using as string")
                actual_space_id = str(space_id)
            
            logger.debug(f"Calling space_manager.delete_space_with_tables({actual_space_id})")
            success = await self.space_manager.delete_space_with_tables(actual_space_id)
            logger.debug(f"Space Manager delete result: {success}")
            
            if success:
                result = {"message": "space deleted successfully with tables", "id": space_id}
                logger.info(f"Delete successful: {result}")
                return result
            else:
                logger.error(f"Delete failed - space not found or deletion failed")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Space not found or deletion failed"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Delete exception: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting space: {str(e)}"
            )
    
    async def get_space_by_id(self, space_id: str, current_user: Dict) -> Dict[str, Any]:
        """Get a specific space by ID."""
        logger.info(f"get_space_by_id called for space_id: {space_id}, user: {current_user.get('username', 'unknown')}")
        
        if not self.space_manager:
            raise HTTPException(
                status_code=500, 
                detail="Space manager not configured"
            )
        
        try:
            # Get space record (with DB fallback on cache miss)
            space_record = await self.space_manager.get_space_or_load(space_id)
            if space_record:
                # Call get_space_info to trigger backend operations like quad logging
                # but don't use its return value - we construct our own response
                await self.space_manager.get_space_info(space_id)
                
                # Return structured space data
                space_data = {
                    'space': space_id,
                    'space_name': getattr(space_record.space_impl, 'space_name', space_id),
                    'space_description': getattr(space_record.space_impl, 'space_description', ''),
                    'exists': True
                }
                logger.debug(f"Found space: {space_data}")
                return space_data
            else:
                logger.error(f"Space not found: {space_id}")
                raise HTTPException(status_code=404, detail="Space not found")
        except Exception as e:
            logger.error(f"Get exception: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"Error getting space: {str(e)}"
            )
    
    async def filter_spaces_by_name(self, name_filter: str, current_user: Dict) -> List[Dict[str, Any]]:
        """Filter spaces by name for the authenticated user."""
        if not self.space_manager:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Space manager not configured"
            )
        
        try:
            # Get all spaces from SpaceManager and filter by name
            all_spaces = []
            for space_id, space_record in self.space_manager._spaces.items():
                space_name = getattr(space_record.space_impl, 'space_name', space_id)
                if (name_filter.lower() in space_name.lower()
                        or name_filter.lower() in space_id.lower()):
                    space_data = {
                        'space': space_id,
                        'space_name': space_name,
                        'space_description': getattr(space_record.space_impl, 'space_description', ''),
                        'exists': True
                    }
                    all_spaces.append(space_data)
            
            return all_spaces
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to filter spaces: {str(e)}"
            )
    
    # User management methods
    async def list_users(self, current_user: Dict, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """List users for the authenticated admin user."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            users = await self.db.list_all_users()
            # Add an ID field for consistency with frontend expectations
            for u in users:
                u['id'] = u.get('username', '')
            if name_filter:
                lf = name_filter.lower()
                users = [
                    u for u in users
                    if lf in (u.get('username') or '').lower()
                    or lf in (u.get('full_name') or '').lower()
                ]
            return users
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list users: {str(e)}"
            )
    
    async def add_user(self, user_data: Dict[str, Any], current_user: Dict) -> Dict[str, Any]:
        """Add a new user with hashed password."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            from vitalgraph.auth.password import hash_password
            username = user_data.get('username', '')
            password = user_data.get('password', '')
            role = user_data.get('role', 'user')
            if not username:
                raise ValueError("Username is required")
            if not password:
                raise ValueError("Password is required")
            password_hash = hash_password(password)
            created_user = await self.db.create_user(
                username=username,
                password_hash=password_hash,
                role=role,
                email=user_data.get('email', ''),
                full_name=user_data.get('full_name', ''),
            )
            if created_user:
                logger.debug(f"Created user result: {created_user}")
                created_user['id'] = username
                emit_audit_event("auth.user.created", current_user.get("username", "system"),
                                 target=username, role=role)
                return created_user
            else:
                logger.error(f"Add failed - could not create user")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to add user"
                )
        except ValueError as e:
            logger.warning(f"Validation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Add exception: {str(e)}")
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
            # Capture pre-update state for audit
            old_user = await self.db.get_user_by_username(user_id)
            if not old_user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            old_role = old_user.get("role")
            old_active = old_user.get("is_active")
            db_user_id = old_user["user_id"]

            updated_user = await self.db.update_user(
                db_user_id,
                email=user_data.get("email"),
                full_name=user_data.get("full_name"),
                role=user_data.get("role"),
                is_active=user_data.get("is_active"),
            )
            if updated_user:
                actor = current_user.get("username", "system")
                # Audit role change
                new_role = user_data.get("role")
                if new_role and new_role != old_role:
                    emit_audit_event("auth.role.changed", actor, target=user_id,
                                     level="WARN", old_role=old_role, new_role=new_role)
                # Audit activation/deactivation
                new_active = user_data.get("is_active")
                if new_active is not None and new_active != old_active:
                    if new_active:
                        emit_audit_event("auth.user.activated", actor, target=user_id)
                    else:
                        emit_audit_event("auth.user.deactivated", actor, target=user_id,
                                         level="WARN")
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
        """Delete a user by username."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            user = await self.db.get_user_by_username(user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            await self.db.delete_user(user['user_id'])
            emit_audit_event("auth.user.deleted", current_user.get("username", "system"),
                             target=user_id, level="WARN")
            return {"message": "user deleted successfully", "id": user_id}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting user: {str(e)}"
            )
    
    async def get_user_by_id(self, user_id: str, current_user: Dict) -> Dict[str, Any]:
        """Get a specific user by username or numeric ID."""
        if not self.db:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not configured"
            )
        
        try:
            user = await self.db.get_user_by_username(user_id)
            if user:
                user['id'] = user.get('username', user_id)
                return user
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



