import React, { useState, useMemo } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { Alert, Button, Card, Checkbox, Label, TextInput } from 'flowbite-react';
import { useAuth } from '../contexts/AuthContext';
import FormField from '../components/FormField';
import { useFormValidation } from '../hooks/useFormValidation';

const Login: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const rules = useMemo(() => ({
    username: { required: 'Username is required' },
    password: { required: 'Password is required', minLength: [1, 'Password is required'] as [number, string] },
  }), []);

  const { errors: fieldErrors, validate, clearError } = useFormValidation(rules);

  // If user is already authenticated, redirect to home
  if (isAuthenticated) {
    return <Navigate to="/" />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validate({ username, password })) {
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
    } catch {
      setError('An error occurred during login. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-100 dark:bg-gray-900 px-4" data-testid="login-page">
      <Card className="w-full max-w-md">
        <div className="flex justify-center mb-4">
          <img 
            src="/images/vital-logo-black.png" 
            className="h-16 w-auto block dark:hidden" 
            alt="VitalGraph Logo" 
          />
          <img 
            src="/images/vitallogo_offwhite_normal.png" 
            className="h-16 w-auto hidden dark:block" 
            alt="VitalGraph Logo" 
          />
        </div>
        <h1 className="text-xl font-bold text-center mb-6 dark:text-white">
          Sign in to VitalGraph
        </h1>
        
        {error && (
          <Alert color="failure" className="mb-4">
            {error}
          </Alert>
        )}
        
        <form className="flex flex-col gap-4" onSubmit={handleSubmit} data-testid="login-form">
          <FormField label="Username" htmlFor="username" error={fieldErrors.username} required>
            <TextInput
              id="username"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => { setUsername(e.target.value); clearError('username'); }}
              disabled={isLoading}
              color={fieldErrors.username ? 'failure' : undefined}
            />
          </FormField>
          
          <FormField label="Password" htmlFor="password" error={fieldErrors.password} required>
            <TextInput
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => { setPassword(e.target.value); clearError('password'); }}
              disabled={isLoading}
              color={fieldErrors.password ? 'failure' : undefined}
            />
          </FormField>
          
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
            data-testid="login-submit"
          >
            {isLoading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </div>
  );
};

export default Login;
