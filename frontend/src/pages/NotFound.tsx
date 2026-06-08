import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Button } from 'flowbite-react';
import { HiHome, HiArrowLeft } from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';

const NotFound: React.FC = () => {
  usePageTitle('Page Not Found');
  const location = useLocation();

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4">
      <div className="text-8xl font-bold text-gray-200 dark:text-gray-700 mb-4">404</div>
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-white mb-2">
        Page Not Found
      </h1>
      <p className="text-gray-500 dark:text-gray-400 mb-2 max-w-md">
        The page you're looking for doesn't exist or has been moved.
      </p>
      <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mb-8 break-all max-w-sm">
        {location.pathname}
      </p>
      <div className="flex gap-3">
        <Link to="/">
          <Button color="blue">
            <HiHome className="mr-2 h-4 w-4" />
            Go Home
          </Button>
        </Link>
        <Button color="gray" onClick={() => window.history.back()}>
          <HiArrowLeft className="mr-2 h-4 w-4" />
          Go Back
        </Button>
      </div>
    </div>
  );
};

export default NotFound;
