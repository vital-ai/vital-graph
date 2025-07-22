
from typing import Dict, Optional
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer


class VitalGraphAuth:
    def __init__(self):
        # For production, you would use a more secure method for storing and validating users
        self.users_db = {
            "admin": {
                "username": "admin",
                "password": "admin",  # In production, this would be hashed
                "full_name": "Admin User",
                "email": "admin@example.com",
                "profile_image": "/images/users/bonnie-green.png",
                "role": "Administrator",
            }
        }
        
        # Initialize OAuth2 scheme
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate a user against the user database."""
        if username in self.users_db and self.users_db[username]["password"] == password:
            return self.users_db[username]
        return None
    
    def create_get_current_user_dependency(self):
        """Create a dependency function for getting current user"""
        def get_current_user(token: str = Depends(self.oauth2_scheme)):
            # In a real app, this would validate a JWT token
            # For our simple example, we'll just check if it follows our pattern
            if not token.startswith("user-") or not token.endswith("-token"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            # Extract username from token
            username = token.split("-")[1]
            if username not in self.users_db:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return self.users_db[username]
        
        return get_current_user

