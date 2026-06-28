# VitalGraph Authentication Enhancement Plan

## Current Authentication System Analysis

### Backend Authentication (Current State)

**VitalGraphAuth Class** (`vitalgraph/auth/vitalgraph_auth.py`):
- Simple static user database with hardcoded credentials
- Basic token format: `user-{username}-token` 
- OAuth2PasswordBearer scheme for REST endpoints
- Simple token validation in `get_current_user` dependency

**Current REST API Authentication**:
- Login endpoint (`/api/login`) returns simple token format
- All protected endpoints use `Depends(get_current_user)` 
- Token validation checks format and user existence
- No expiration, refresh, or proper JWT implementation

**Current WebSocket Authentication**:
- Initial auth message with token during connection
- Token validation on each subsequent message
- Same token format as REST API
- Connection manager tracks authenticated users

### Frontend Authentication (Current State)

**WebSocket Service** (`frontend/src/services/WebSocketService.ts`):
- Sends auth message with token on connection
- Includes token in every WebSocket message
- Automatic reconnection with token validation
- Proper error handling for auth failures

**REST API Integration**:
- Uses same token format for both REST and WebSocket
- Token stored and managed by frontend auth system

## Enhanced Authentication Plan

### 1. JWT Token Implementation

#### Backend Changes

**New JWT Authentication Class** (`vitalgraph/auth/jwt_auth.py`):
```python
import jwt
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import HTTPException, status

class JWTAuth:
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = 30
        self.refresh_token_expire_days = 7
    
    def create_access_token(self, data: dict) -> str:
        """Create JWT access token with expiration"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(self, data: dict) -> str:
        """Create JWT refresh token with longer expiration"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=self.refresh_token_expire_days)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str, token_type: str = "access") -> Dict:
        """Verify and decode JWT token"""
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
        except jwt.JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
```

**Enhanced VitalGraphAuth Class**:
```python
class VitalGraphAuth:
    def __init__(self, secret_key: str):
        # Static user database (unchanged)
        self.users_db = {
            "admin": {
                "username": "admin",
                "password": "admin",  # In production, use hashed passwords
                "full_name": "Admin User",
                "email": "admin@example.com",
                "profile_image": "/images/users/bonnie-green.png",
                "role": "Administrator",
            }
        }
        
        # Initialize JWT handler
        self.jwt_auth = JWTAuth(secret_key)
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user and return user data"""
        if username in self.users_db and self.users_db[username]["password"] == password:
            return self.users_db[username]
        return None
    
    def create_tokens(self, user_data: Dict) -> Dict:
        """Create access and refresh tokens for authenticated user"""
        token_data = {
            "sub": user_data["username"],
            "username": user_data["username"],
            "full_name": user_data["full_name"],
            "email": user_data["email"],
            "role": user_data["role"]
        }
        
        access_token = self.jwt_auth.create_access_token(token_data)
        refresh_token = self.jwt_auth.create_refresh_token(token_data)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.jwt_auth.access_token_expire_minutes * 60
        }
    
    def create_get_current_user_dependency(self):
        """Create dependency for JWT token validation"""
        def get_current_user(token: str = Depends(self.oauth2_scheme)):
            payload = self.jwt_auth.verify_token(token, "access")
            username = payload.get("sub")
            
            if username not in self.users_db:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )
            
            return self.users_db[username]
        
        return get_current_user
```

### 2. New Authentication Endpoints

**Login Endpoint** (Enhanced):
```python
async def login(self, form_data: OAuth2PasswordRequestForm):
    """Enhanced login with JWT tokens"""
    user = self.auth.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    tokens = self.auth.create_tokens(user)
    
    return {
        **tokens,
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "profile_image": user["profile_image"],
        "role": user["role"]
    }
```

**New Refresh Token Endpoint**:
```python
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
```

### 3. WebSocket Authentication Enhancement

**Enhanced WebSocket Authentication**:
```python
async def connect(self, websocket: WebSocket, token: str) -> Optional[str]:
    """Connect WebSocket with JWT token validation"""
    try:
        # Verify JWT token
        payload = self.auth.jwt_auth.verify_token(token, "access")
        username = payload.get("sub")
        
        if username not in self.auth.users_db:
            logger.warning(f"User not found: {username}")
            return None
        
        # Store connection and return username
        if username not in self.active_connections:
            self.active_connections[username] = set()
        self.active_connections[username].add(websocket)
        
        logger.info(f"WebSocket connected for user: {username}")
        return username
        
    except HTTPException as e:
        logger.warning(f"JWT token validation failed: {e.detail}")
        return None
    except Exception as e:
        logger.error(f"Error during WebSocket connection: {e}")
        return None
```

**WebSocket Message Validation**:
```python
# In websocket_endpoint function
async def websocket_endpoint(websocket: WebSocket, connection_manager: ConnectionManager):
    # ... existing code ...
    
    while True:
        try:
            message = await websocket.receive_text()
            message_data = json.loads(message)
            
            # Validate JWT token in each message
            msg_token = message_data.get("token")
            if not msg_token:
                await websocket.send_text(json.dumps({
                    "type": "auth_error",
                    "message": "Token required in message"
                }))
                break
            
            try:
                payload = connection_manager.auth.jwt_auth.verify_token(msg_token, "access")
                token_username = payload.get("sub")
                
                if token_username != username:
                    await websocket.send_text(json.dumps({
                        "type": "auth_error",
                        "message": "Token username mismatch"
                    }))
                    break
                    
            except HTTPException:
                await websocket.send_text(json.dumps({
                    "type": "auth_error", 
                    "message": "Invalid or expired token"
                }))
                break
            
            await handler.handle_message(websocket, username, message_data)
            
        except WebSocketDisconnect:
            break
        # ... error handling ...
```

### 4. Frontend Authentication Updates

**Enhanced Authentication Service**:
```typescript
interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

class AuthService {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private tokenExpiry: Date | null = null;
  private refreshTimer: number | null = null;

  async login(username: string, password: string): Promise<boolean> {
    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username, password })
      });

      if (response.ok) {
        const data: AuthTokens = await response.json();
        this.setTokens(data);
        this.scheduleTokenRefresh();
        return true;
      }
      return false;
    } catch (error) {
      console.error('Login error:', error);
      return false;
    }
  }

  private setTokens(tokens: AuthTokens) {
    this.accessToken = tokens.access_token;
    this.refreshToken = tokens.refresh_token;
    this.tokenExpiry = new Date(Date.now() + tokens.expires_in * 1000);
    
    // Store in localStorage for persistence
    localStorage.setItem('access_token', this.accessToken);
    localStorage.setItem('refresh_token', this.refreshToken);
    localStorage.setItem('token_expiry', this.tokenExpiry.toISOString());
  }

  private async refreshAccessToken(): Promise<boolean> {
    if (!this.refreshToken) return false;

    try {
      const response = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: this.refreshToken })
      });

      if (response.ok) {
        const data = await response.json();
        this.accessToken = data.access_token;
        this.tokenExpiry = new Date(Date.now() + data.expires_in * 1000);
        
        localStorage.setItem('access_token', this.accessToken);
        localStorage.setItem('token_expiry', this.tokenExpiry.toISOString());
        
        this.scheduleTokenRefresh();
        return true;
      }
      return false;
    } catch (error) {
      console.error('Token refresh error:', error);
      return false;
    }
  }

  private scheduleTokenRefresh() {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
    }

    if (this.tokenExpiry) {
      // Refresh 5 minutes before expiry
      const refreshTime = this.tokenExpiry.getTime() - Date.now() - (5 * 60 * 1000);
      
      if (refreshTime > 0) {
        this.refreshTimer = setTimeout(() => {
          this.refreshAccessToken();
        }, refreshTime);
      }
    }
  }

  getAccessToken(): string | null {
    // Check if token is expired
    if (this.tokenExpiry && new Date() >= this.tokenExpiry) {
      this.refreshAccessToken();
    }
    return this.accessToken;
  }
}
```

**Enhanced WebSocket Service**:
```typescript
// Update WebSocket service to use JWT tokens
async connect(token: string): Promise<boolean> {
  // Validate token format (JWT)
  if (!token || token.split('.').length !== 3) {
    console.error('Invalid JWT token format');
    return false;
  }

  this.token = token;
  // ... rest of connection logic unchanged ...
}

send(data: any): void {
  if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
    console.warn('Cannot send message: WebSocket not connected');
    return;
  }
  
  // Always include current access token
  const currentToken = authService.getAccessToken();
  if (!currentToken) {
    console.error('No valid access token available');
    return;
  }
  
  const messageWithToken = {
    ...data,
    token: currentToken
  };
  
  try {
    this.ws.send(JSON.stringify(messageWithToken));
  } catch (error) {
    console.error('Error sending WebSocket message:', error);
  }
}
```

### 5. REST API Header Authentication

**Enhanced API Service**:
```typescript
class ApiService {
  private async makeRequest(url: string, options: RequestInit = {}): Promise<Response> {
    const token = authService.getAccessToken();
    
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };
    
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(url, {
      ...options,
      headers
    });
    
    // Handle token expiry
    if (response.status === 401) {
      const refreshed = await authService.refreshAccessToken();
      if (refreshed) {
        // Retry request with new token
        const newToken = authService.getAccessToken();
        if (newToken) {
          headers['Authorization'] = `Bearer ${newToken}`;
          return fetch(url, { ...options, headers });
        }
      }
      // Redirect to login if refresh fails
      window.location.href = '/login';
    }
    
    return response;
  }
}
```

### 6. Configuration and Security

**Environment Configuration**:
```bash
# .env file
JWT_SECRET_KEY=vitalgraph-super-secret-jwt-key-change-in-production-2025
APP_MODE=production
PORT=8001
HOST=0.0.0.0
```

**Docker Compose Configuration**:
```yaml
# docker-compose.yml
environment:
  - JWT_SECRET_KEY=${JWT_SECRET_KEY}
  - APP_MODE=production
  - PORT=${PORT:-8001}
  - HOST=${HOST:-0.0.0.0}
```

**JWT Settings** (hardcoded in JWTAuth class):
- Access Token Expiry: 30 minutes
- Refresh Token Expiry: 7 days  
- Algorithm: HS256

**Security Best Practices**:
1. Use strong, randomly generated JWT secret keys
2. Implement proper password hashing (bcrypt) for production
3. Add rate limiting for login attempts
4. Implement proper CORS policies
5. Use HTTPS in production
6. Add token blacklisting for logout
7. Implement proper session management

### 7. Migration Strategy

**Phase 1: Backend JWT Implementation**
1. Implement JWT authentication classes
2. Add refresh token endpoint
3. Update existing endpoints to use JWT validation

**Phase 2: WebSocket Enhancement**
1. Update WebSocket authentication to use JWT
2. Add token validation for each message
3. Handle token expiry in WebSocket connections

**Phase 3: Frontend Updates**
1. Implement JWT token management
2. Add automatic token refresh
3. Update WebSocket service for JWT
4. Update all API calls to use Bearer tokens

**Phase 4: Security Hardening**
1. Add proper password hashing
2. Implement rate limiting
3. Add token blacklisting
4. Security audit and testing

### 8. Testing Strategy

**Unit Tests**:
- JWT token creation and validation
- Token expiry handling
- Refresh token functionality
- WebSocket authentication

**Integration Tests**:
- End-to-end authentication flow
- Token refresh during API calls
- WebSocket connection with JWT
- Error handling for expired tokens

**Security Tests**:
- Token tampering detection
- Expired token rejection
- Invalid token handling
- Rate limiting effectiveness

This enhanced authentication system provides:
- Proper JWT token security
- Automatic token refresh
- Consistent authentication across REST and WebSocket
- Production-ready security features