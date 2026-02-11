"""
JWT Authentication module for VitalGraph.

This module provides JWT token creation, validation, and refresh functionality
for secure authentication in the VitalGraph system.
"""

import jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from fastapi import HTTPException, status

# Handle different PyJWT versions
try:
    from jwt import InvalidTokenError
except ImportError:
    # Fallback for older PyJWT versions
    InvalidTokenError = jwt.DecodeError


class JWTAuth:
    """JWT Authentication handler for VitalGraph."""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        """
        Initialize JWT authentication.
        
        Args:
            secret_key: Secret key for JWT signing
            algorithm: JWT algorithm (default: HS256)
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = 30
        self.refresh_token_expire_days = 7
    
    def create_access_token(self, data: dict, expiry_seconds: int = None) -> str:
        """
        Create JWT access token with expiration.
        
        Args:
            data: Token payload data
            expiry_seconds: Optional custom expiry in seconds (for testing, max 1800)
            
        Returns:
            Encoded JWT access token
        """
        to_encode = data.copy()
        
        # Use custom expiry if provided, otherwise use default minutes
        if expiry_seconds is not None:
            expire = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.access_token_expire_minutes)
            
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(self, data: dict) -> str:
        """
        Create JWT refresh token with longer expiration.
        
        Args:
            data: Token payload data
            
        Returns:
            Encoded JWT refresh token
        """
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(days=self.refresh_token_expire_days)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str, token_type: str = "access") -> Dict:
        """
        Verify and decode JWT token.
        
        Args:
            token: JWT token to verify
            token_type: Expected token type ("access" or "refresh")
            
        Returns:
            Decoded token payload
            
        Raises:
            HTTPException: If token is invalid, expired, or wrong type
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type"
                )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except (InvalidTokenError, jwt.DecodeError, jwt.InvalidSignatureError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
    
    def get_token_expiry(self, token: str) -> Optional[datetime]:
        """
        Get token expiration time without validation.
        
        Args:
            token: JWT token
            
        Returns:
            Token expiration datetime or None if invalid
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm], options={"verify_exp": False})
            exp_timestamp = payload.get("exp")
            if exp_timestamp:
                return datetime.utcfromtimestamp(exp_timestamp)
        except (InvalidTokenError, jwt.DecodeError, jwt.InvalidSignatureError, ValueError):
            pass
        return None
