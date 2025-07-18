import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Alert } from 'flowbite-react';

const Home: React.FC = () => {
  const { user } = useAuth();

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-gray-900 dark:text-white">Welcome to VitalGraph</h1>
      
      <Alert color="info" className="mb-4">
        <div className="font-medium">
          Hello, {user?.full_name || 'User'}!
        </div>
        <div>
          You are successfully logged in as {user?.role || 'User'}.
        </div>
      </Alert>
      
      <p className="text-base text-gray-500 dark:text-gray-400">
        This is the authenticated home page of your VitalGraph application.
        You now have access to all the features and data available for your account.
      </p>
    </div>
  );
};

export default Home;
