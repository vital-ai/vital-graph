import React from 'react';

/**
 * A thin animated progress bar fixed to the top of the viewport.
 * Used as a loading indicator during page transitions (Suspense fallback).
 */
const TopLoader: React.FC = () => {
  return (
    <div className="fixed top-0 left-0 right-0 z-[200] h-1 bg-gray-200 dark:bg-gray-700 overflow-hidden">
      <div className="h-full bg-blue-600 dark:bg-blue-500 animate-top-loader rounded-r" />
    </div>
  );
};

export default TopLoader;
