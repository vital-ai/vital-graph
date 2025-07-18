import React, { createContext, useState, useContext, useEffect, ReactNode } from 'react';
import axios from 'axios';

// Define types for our auth state and context
interface User {
  username: string;
  full_name: string;
  email: string;
  profile_image: string;
  role: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
}

// Create the auth context with default values
const AuthContext = createContext<AuthContextType>({
  token: null,
  user: null,
  isAuthenticated: false,
  isLoading: true,
  login: async () => false,
  logout: () => {},
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

  // Check for existing token in local storage on component mount
  useEffect(() => {
    const loadStoredAuth = async () => {
      const storedToken = localStorage.getItem('auth_token');
      const storedUser = localStorage.getItem('auth_user');
      
      if (storedToken && storedUser) {
        try {
          // Set up the authorization header for future requests
          axios.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
          
          setAuthState({
            token: storedToken,
            user: JSON.parse(storedUser),
            isAuthenticated: true,
            isLoading: false,
          });
        } catch (error) {
          // If parsing fails or token is invalid, clear storage
          localStorage.removeItem('auth_token');
          localStorage.removeItem('auth_user');
          setAuthState({
            token: null,
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
        }
      } else {
        setAuthState(prev => ({ ...prev, isLoading: false }));
      }
    };

    loadStoredAuth();
  }, []);

  // Login function that calls the API and updates auth state
  const login = async (username: string, password: string): Promise<boolean> => {
    try {
      console.log('Attempting login with:', { username });
      
      // Convert username and password to form data format expected by FastAPI
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);
      
      console.log('API URL:', window.location.origin + '/api/login');
      console.log('Sending request to:', '/api/login');
      
      const response = await axios.post('/api/login', formData, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });
      
      console.log('Login response:', response.data);
      
      const { access_token, token_type, ...userData } = response.data;
      
      // Store token and user data
      localStorage.setItem('auth_token', access_token);
      localStorage.setItem('auth_user', JSON.stringify(userData));
      
      // Set up the authorization header for future requests
      axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
      
      setAuthState({
        token: access_token,
        user: userData,
        isAuthenticated: true,
        isLoading: false,
      });
      
      return true;
    } catch (error) {
      console.error('Login failed:', error);
      
      // Type guard for axios error
      if (axios.isAxiosError(error)) {
        console.error('Error details:', error.response?.data || 'No response data');
        console.error('Status code:', error.response?.status || 'No status code');
      }
      
      return false;
    }
  };

  // Logout function
  const logout = () => {
    // Clear auth from local storage
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_user');
    
    // Remove authorization header
    delete axios.defaults.headers.common['Authorization'];
    
    // Reset auth state
    setAuthState({
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
    
    // Optionally call the logout API endpoint
    axios.post('/api/logout').catch(error => {
      console.error('Logout API call failed:', error);
    });
  };

  // Provide the auth context value to children components
  return (
    <AuthContext.Provider
      value={{
        ...authState,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;
