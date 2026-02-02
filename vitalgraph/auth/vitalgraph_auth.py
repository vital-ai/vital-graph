
from typing import Dict, Optional
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from .jwt_auth import JWTAuth


class VitalGraphAuth:
    def __init__(self, secret_key: str = "your-secret-key-change-in-production"):
        # For production, you would use a more secure method for storing and validating users
        self.users_db = {
            "admin": {
                "username": "admin",
                "password": "admin",
                "full_name": "Admin User",
                "email": "admin@example.com",
                "profile_image": "/images/users/bonnie-green.png",
                "role": "Administrator",
            }
        }
        
        # Initialize JWT handler
        self.jwt_auth = JWTAuth(secret_key)
        
        # Initialize OAuth2 scheme
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate a user against the user database."""
        if username in self.users_db and self.users_db[username]["password"] == password:
            return self.users_db[username]
        return None
    
    def create_tokens(self, user_data: Dict, token_expiry_seconds: Optional[int] = None) -> Dict[str, str]:
        """Create access and refresh tokens for a user"""
        token_data = {
            "sub": user_data["username"],
            "full_name": user_data["full_name"],
            "email": user_data["email"],
            "role": user_data["role"]
        }
        
        # Create tokens with optional custom expiry
        access_token = self.jwt_auth.create_access_token(token_data, expiry_seconds=token_expiry_seconds)
        refresh_token = self.jwt_auth.create_refresh_token(token_data)
        
        # Calculate expires_in based on custom or default expiry
        if token_expiry_seconds is not None:
            expires_in = token_expiry_seconds
        else:
            expires_in = self.jwt_auth.access_token_expire_minutes * 60
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in
        }
    
    def create_get_current_user_dependency(self):
        """Create a dependency function for getting current user"""
        def get_current_user(token: str = Depends(self.oauth2_scheme)):
            # Try to validate as access token first
            try:
                payload = self.jwt_auth.verify_token(token, "access")
                username = payload.get("sub")
                
                if username not in self.users_db:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="User not found"
                    )
                
                return self.users_db[username]
            except HTTPException:
                # If access token validation fails, try refresh token
                try:
                    payload = self.jwt_auth.verify_token(token, "refresh")
                    username = payload.get("sub")
                    
                    if username not in self.users_db:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User not found"
                        )
                    
                    return self.users_db[username]
                except HTTPException:
                    # If both fail, raise unauthorized
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired token"
                    )
        
        return get_current_user

