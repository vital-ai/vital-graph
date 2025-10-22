import React, { createContext, useState, useContext, useEffect, ReactNode } from 'react';
import { authService, User } from '../services/AuthService';

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  showLoginSuccess: boolean;
  setShowLoginSuccess: (show: boolean) => void;
  refreshToken: () => Promise<boolean>;
  getAuthHeader: () => { Authorization: string } | {};
}

// Create the auth context with default values
const AuthContext = createContext<AuthContextType>({
  token: null,
  user: null,
  isAuthenticated: false,
  isLoading: true,
  login: async () => false,
  logout: () => {},
  showLoginSuccess: false,
  setShowLoginSuccess: () => {},
  refreshToken: async () => false,
  getAuthHeader: () => ({}),
});

// Custom hook to use the auth context
export const useAuth = () => useContext(AuthContext);

interface AuthProviderProps {
  children: ReactNode;
}

// Provider component that wraps the app and makes auth available to any child component
export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [authState, setAuthState] = useState<AuthState>({
    token: null,
    user: null,
    isAuthenticated: false,
    isLoading: true,
  });
  const [showLoginSuccess, setShowLoginSuccess] = useState(false);

  // Initialize auth state from AuthService on component mount
  useEffect(() => {
    const initializeAuth = () => {
      const token = authService.getAccessToken();
      const user = authService.getUser();
      const isAuthenticated = authService.isAuthenticated();
      
      setAuthState({
        token,
        user,
        isAuthenticated,
        isLoading: false,
      });
    };

    initializeAuth();
  }, []);

  // Login function using AuthService
  const login = async (username: string, password: string): Promise<boolean> => {
    try {
      console.log('🔐 Attempting JWT login with:', { username });
      
      const success = await authService.login(username, password);
      
      if (success) {
        // Update auth state
        const token = authService.getAccessToken();
        const user = authService.getUser();
        
        setAuthState({
          token,
          user,
          isAuthenticated: true,
          isLoading: false,
        });
        
        // Show login success banner
        setShowLoginSuccess(true);
        
        console.log('✅ Login successful with JWT tokens');
        return true;
      } else {
        console.error('❌ Login failed');
        return false;
      }
    } catch (error) {
      console.error('❌ Login error:', error);
      return false;
    }
  };

  // Logout function using AuthService
  const logout = () => {
    console.log('🚪 Logging out...');
    
    authService.logout();
    
    // Reset auth state
    setAuthState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
    
    console.log('✅ Logout complete');
  };

  // Refresh token function
  const refreshToken = async (): Promise<boolean> => {
    const success = await authService.refreshAccessToken();
    
    if (success) {
      // Update auth state with new token
      const token = authService.getAccessToken();
      const user = authService.getUser();
      
      setAuthState(prev => ({
        ...prev,
        token,
        user,
        isAuthenticated: true,
      }));
    }
    
    return success;
  };

  // Get auth header function
  const getAuthHeader = () => {
    return authService.getAuthHeader();
  };

  // Provide the auth context value to children components
  return (
    <AuthContext.Provider
      value={{
        ...authState,
        login,
        logout,
        refreshToken,
        getAuthHeader,
        showLoginSuccess,
        setShowLoginSuccess,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;
