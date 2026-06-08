import React from 'react';
import { Spinner } from 'flowbite-react';

interface LoadingSkeletonProps {
  message?: string;
  fullHeight?: boolean;
}

const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({ message = 'Loading...', fullHeight = false }) => {
  return (
    <div className={`flex flex-col justify-center items-center ${fullHeight ? 'h-64' : 'h-40'}`}>
      <Spinner size="xl" />
      <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">{message}</p>
    </div>
  );
};

export default LoadingSkeleton;
