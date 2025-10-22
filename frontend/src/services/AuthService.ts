/**
 * Enhanced Authentication Service for VitalGraph with JWT token management.
 * 
 * This service handles:
 * - JWT access and refresh tokens
 * - Automatic token refresh
 * - Token persistence and recovery
 * - Bearer token authentication
 */

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  username: string;
  full_name: string;
  email: string;
  profile_image: string;
  role: string;
}

export interface LoginResponse extends AuthTokens {
  username: string;
  full_name: string;
  email: string;
  profile_image: string;
  role: string;
}

export class AuthService {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private tokenExpiry: Date | null = null;
  private refreshTimer: number | null = null;
  private user: User | null = null;

  constructor() {
    // Load tokens from localStorage on initialization
    this.loadStoredTokens();
  }

  /**
   * Load stored tokens from localStorage
   */
  private loadStoredTokens(): void {
    try {
      const storedAccessToken = localStorage.getItem('access_token');
      const storedRefreshToken = localStorage.getItem('refresh_token');
      const storedExpiry = localStorage.getItem('token_expiry');
      const storedUser = localStorage.getItem('auth_user');

      if (storedAccessToken && storedRefreshToken && storedExpiry && storedUser) {
        const expiry = new Date(storedExpiry);
        
        // Check if token is still valid (not expired)
        if (expiry > new Date()) {
          this.accessToken = storedAccessToken;
          this.refreshToken = storedRefreshToken;
          this.tokenExpiry = expiry;
          this.user = JSON.parse(storedUser);
          
          // Schedule refresh for this token
          this.scheduleTokenRefresh();
          
          console.log('✅ Restored valid tokens from localStorage');
        } else {
          console.log('⏰ Stored tokens expired, attempting refresh...');
          // Try to refresh with the stored refresh token
          this.refreshToken = storedRefreshToken;
          this.refreshAccessToken();
        }
      }
    } catch (error) {
      console.error('Error loading stored tokens:', error);
      this.clearStoredTokens();
    }
  }

  /**
   * Login with username and password
   */
  async login(username: string, password: string): Promise<boolean> {
    try {
      console.log('🔐 Attempting login with JWT authentication...');
      
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username, password })
      });

      if (response.ok) {
        const data: LoginResponse = await response.json();
        
        // Extract user data
        const userData: User = {
          username: data.username,
          full_name: data.full_name,
          email: data.email,
          profile_image: data.profile_image,
          role: data.role
        };

        // Set tokens and user data
        this.setTokens({
          access_token: data.access_token,
          refresh_token: data.refresh_token,
          token_type: data.token_type,
          expires_in: data.expires_in
        }, userData);

        console.log('✅ Login successful with JWT tokens');
        console.log(`   Access token expires in: ${data.expires_in} seconds`);
        
        return true;
      } else {
        console.error('❌ Login failed:', response.status, response.statusText);
        return false;
      }
    } catch (error) {
      console.error('❌ Login error:', error);
      return false;
    }
  }

  /**
   * Set tokens and user data with automatic refresh scheduling
   */
  private setTokens(tokens: AuthTokens, userData?: User): void {
    this.accessToken = tokens.access_token;
    this.refreshToken = tokens.refresh_token;
    this.tokenExpiry = new Date(Date.now() + tokens.expires_in * 1000);
    
    if (userData) {
      this.user = userData;
    }
    
    // Store in localStorage for persistence
    localStorage.setItem('access_token', this.accessToken);
    localStorage.setItem('refresh_token', this.refreshToken);
    localStorage.setItem('token_expiry', this.tokenExpiry.toISOString());
    
    if (this.user) {
      localStorage.setItem('auth_user', JSON.stringify(this.user));
    }
    
    // Schedule automatic token refresh
    this.scheduleTokenRefresh();
  }

  /**
   * Refresh access token using refresh token
   */
  async refreshAccessToken(): Promise<boolean> {
    if (!this.refreshToken) {
      console.warn('⚠️ No refresh token available');
      return false;
    }

    try {
      console.log('🔄 Refreshing access token...');
      
      const response = await fetch('/api/refresh', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.refreshToken}`
        },
        body: JSON.stringify({ refresh_token: this.refreshToken })
      });

      if (response.ok) {
        const data = await response.json();
        
        // Update access token and expiry
        this.accessToken = data.access_token;
        this.tokenExpiry = new Date(Date.now() + data.expires_in * 1000);
        
        // Update localStorage
        if (this.accessToken) {
          localStorage.setItem('access_token', this.accessToken);
        }
        if (this.tokenExpiry) {
          localStorage.setItem('token_expiry', this.tokenExpiry.toISOString());
        }
        
        // Schedule next refresh
        this.scheduleTokenRefresh();
        
        console.log('✅ Token refresh successful');
        console.log(`   New token expires in: ${data.expires_in} seconds`);
        
        return true;
      } else {
        console.error('❌ Token refresh failed:', response.status, response.statusText);
        
        // If refresh fails, clear all tokens and redirect to login
        this.logout();
        return false;
      }
    } catch (error) {
      console.error('❌ Token refresh error:', error);
      this.logout();
      return false;
    }
  }

  /**
   * Schedule automatic token refresh (5 minutes before expiry)
   */
  private scheduleTokenRefresh(): void {
    // Clear existing timer
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
    }

    if (this.tokenExpiry) {
      // Refresh 5 minutes before expiry
      const refreshTime = this.tokenExpiry.getTime() - Date.now() - (5 * 60 * 1000);
      
      if (refreshTime > 0) {
        this.refreshTimer = setTimeout(() => {
          console.log('⏰ Automatic token refresh triggered');
          this.refreshAccessToken();
        }, refreshTime);
        
        console.log(`⏰ Token refresh scheduled in ${Math.round(refreshTime / 1000)} seconds`);
      } else {
        // Token expires soon, refresh immediately
        console.log('⚠️ Token expires soon, refreshing immediately');
        this.refreshAccessToken();
      }
    }
  }

  /**
   * Get current access token (with automatic refresh if needed)
   */
  getAccessToken(): string | null {
    // Check if token is expired or expires soon (within 1 minute)
    if (this.tokenExpiry && new Date() >= new Date(this.tokenExpiry.getTime() - 60000)) {
      console.log('⚠️ Token expired or expires soon, triggering refresh');
      this.refreshAccessToken();
    }
    
    return this.accessToken;
  }

  /**
   * Get current user data
   */
  getUser(): User | null {
    return this.user;
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return !!(this.accessToken && this.tokenExpiry && new Date() < this.tokenExpiry);
  }

  /**
   * Logout and clear all tokens
   */
  logout(): void {
    console.log('🚪 Logging out...');
    
    // Clear timers
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    
    // Call logout API if we have a token
    if (this.accessToken) {
      fetch('/api/logout', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.accessToken}`,
          'Content-Type': 'application/json'
        }
      }).catch(error => {
        // Ignore errors on logout
        console.warn('Logout API call failed (ignored):', error);
      });
    }
    
    // Clear all tokens and user data
    this.accessToken = null;
    this.refreshToken = null;
    this.tokenExpiry = null;
    this.user = null;
    
    // Clear localStorage
    this.clearStoredTokens();
    
    console.log('✅ Logout complete');
  }

  /**
   * Clear stored tokens from localStorage
   */
  private clearStoredTokens(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('token_expiry');
    localStorage.removeItem('auth_user');
    localStorage.removeItem('auth_token'); // Legacy token key
  }

  /**
   * Get Authorization header for API requests
   */
  getAuthHeader(): { Authorization: string } | {} {
    const token = this.getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  /**
   * Make authenticated API request with automatic token refresh
   */
  async makeAuthenticatedRequest(url: string, options: RequestInit = {}): Promise<Response> {
    const token = this.getAccessToken();
    
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    };

    const response = await fetch(url, {
      ...options,
      headers
    });

    // Handle 401 responses (token expired)
    if (response.status === 401 && token) {
      console.log('🔄 Received 401, attempting token refresh...');
      
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        // Retry request with new token
        const newToken = this.getAccessToken();
        if (newToken) {
          const retryHeaders = {
            ...headers,
            Authorization: `Bearer ${newToken}`
          };
          
          return fetch(url, { ...options, headers: retryHeaders });
        }
      }
      
      // If refresh failed, redirect to login
      console.log('🚪 Token refresh failed, redirecting to login');
      this.logout();
      window.location.href = '/login';
    }

    return response;
  }
}

// Create singleton instance
export const authService = new AuthService();
export default authService;
