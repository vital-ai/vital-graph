"""
Fuseki Authentication Module

Provides JWT token management for authenticated Fuseki connections using Keycloak.
"""

import logging
import time
from typing import Optional, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)


class FusekiAuthManager:
    """Manages JWT authentication for Fuseki connections via Keycloak."""
    
    def __init__(self, keycloak_config: Dict[str, Any]):
        """
        Initialize Fuseki authentication manager.
        
        Args:
            keycloak_config: Keycloak configuration dictionary containing:
                - url: Keycloak server URL
                - realm: Keycloak realm name
                - client_id: Client ID for authentication
                - client_secret: Optional client secret for confidential clients
                - username: Service account username
                - password: Service account password
        """
        self.keycloak_url = keycloak_config.get('url')
        self.realm = keycloak_config.get('realm')
        self.client_id = keycloak_config.get('client_id')
        self.client_secret = keycloak_config.get('client_secret')
        self.username = keycloak_config.get('username')
        self.password = keycloak_config.get('password')
        
        # Token storage
        self.access_token: Optional[str] = None
        self.token_type: str = 'Bearer'
        self.token_expiry: float = 0
        self.refresh_token: Optional[str] = None
        
        # Validate configuration
        self._validate_config()
        
        logger.info(f"FusekiAuthManager initialized for Keycloak: {self.keycloak_url}")
    
    def _validate_config(self) -> None:
        """Validate that required configuration is present."""
        required = ['url', 'realm', 'client_id', 'username', 'password']
        missing = [key for key in required if not getattr(self, f'keycloak_{key}' if key == 'url' else key)]
        
        if missing:
            raise ValueError(f"Missing required Keycloak configuration: {', '.join(missing)}")
    
    async def get_token(self, session: aiohttp.ClientSession) -> Optional[str]:
        """
        Get a valid JWT token, refreshing if necessary.
        
        Args:
            session: aiohttp ClientSession for making requests
            
        Returns:
            JWT access token string, or None if authentication fails
        """
        # Check if current token is still valid (with 60 second buffer)
        if self.access_token and time.time() < (self.token_expiry - 60):
            return self.access_token
        
        # Token expired or doesn't exist, get a new one
        return await self._obtain_token(session)
    
    async def _obtain_token(self, session: aiohttp.ClientSession) -> Optional[str]:
        """
        Obtain a new JWT token from Keycloak.
        
        Args:
            session: aiohttp ClientSession for making requests
            
        Returns:
            JWT access token string, or None if authentication fails
        """
        token_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        
        # Prepare token request data
        data = {
            'grant_type': 'password',
            'client_id': self.client_id,
            'username': self.username,
            'password': self.password,
        }
        
        # Add client secret if provided (for confidential clients)
        if self.client_secret:
            data['client_secret'] = self.client_secret
        
        try:
            async with session.post(
                token_url,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self.access_token = token_data.get('access_token')
                    self.token_type = token_data.get('token_type', 'Bearer')
                    self.refresh_token = token_data.get('refresh_token')
                    
                    # Calculate token expiry time
                    expires_in = token_data.get('expires_in', 300)
                    self.token_expiry = time.time() + expires_in
                    
                    logger.info(f"Successfully obtained JWT token from Keycloak (expires in {expires_in}s)")
                    return self.access_token
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to obtain JWT token: {response.status} - {error_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error obtaining JWT token from Keycloak: {e}")
            return None
    
    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers with JWT authorization.
        
        Returns:
            Dictionary with Authorization header
        """
        if not self.access_token:
            logger.warning("No JWT token available for authorization headers")
            return {}
        
        return {
            'Authorization': f'{self.token_type} {self.access_token}'
        }
    
    async def refresh_token_if_needed(self, session: aiohttp.ClientSession) -> bool:
        """
        Refresh token if it's close to expiring.
        
        Args:
            session: aiohttp ClientSession for making requests
            
        Returns:
            True if token is valid or successfully refreshed, False otherwise
        """
        # Check if token needs refresh (within 2 minutes of expiry)
        if time.time() >= (self.token_expiry - 120):
            token = await self._obtain_token(session)
            return token is not None
        
        return True
