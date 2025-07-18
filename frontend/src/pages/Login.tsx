import React, { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { Alert, Button, Card, Checkbox, Label, TextInput } from 'flowbite-react';
import { useAuth } from '../contexts/AuthContext';

const Login: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  // If user is already authenticated, redirect to home
  if (isAuthenticated) {
    return <Navigate to="/" />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // Validate form
    if (!username || !password) {
      setError('Please enter both username and password');
      return;
    }
    
    setIsLoading(true);
    setError(null);
    
    try {
      // Call login function from auth context
      const success = await login(username, password);
      
      if (success) {
        navigate('/');
      } else {
        setError('Invalid username or password');
      }
    } catch (err) {
      setError('An error occurred during login. Please try again.');
      console.error('Login error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-100 dark:bg-gray-900 px-4">
      <Card className="w-full max-w-md">
        <div className="flex justify-center mb-4">
          <img src="/flowbite-react.svg" className="h-12" alt="VitalGraph Logo" />
        </div>
        <h1 className="text-xl font-bold text-center mb-6 dark:text-white">
          Sign in to VitalGraph
        </h1>
        
        {error && (
          <Alert color="failure" className="mb-4">
            {error}
          </Alert>
        )}
        
        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <div>
            <div className="mb-2 block">
              <Label htmlFor="username">Username</Label>
            </div>
            <TextInput
              id="username"
              placeholder="Enter your username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isLoading}
            />
          </div>
          
          <div>
            <div className="mb-2 block">
              <Label htmlFor="password">Password</Label>
            </div>
            <TextInput
              id="password"
              type="password"
              placeholder="••••••••"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />
          </div>
          
          <div className="flex items-center gap-2">
            <Checkbox 
              id="remember" 
              checked={rememberMe}
              onChange={() => setRememberMe(!rememberMe)}
              disabled={isLoading}
            />
            <Label htmlFor="remember">Remember me</Label>
          </div>
          
          <Button 
            type="submit" 
            disabled={isLoading}
          >
            {isLoading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </div>
  );
};

export default Login;
