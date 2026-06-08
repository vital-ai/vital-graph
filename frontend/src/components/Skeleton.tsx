import React from 'react';

const pulse = 'animate-pulse bg-gray-200 dark:bg-gray-700 rounded';

/** A single animated bar */
export const SkeletonBar: React.FC<{ className?: string }> = ({ className = 'h-4 w-full' }) => (
  <div className={`${pulse} ${className}`} />
);

/** Skeleton for a stat card grid (e.g., Home dashboard) */
export const SkeletonStatCards: React.FC<{ count?: number }> = ({ count = 4 }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    {Array.from({ length: count }).map((_, i) => (
      <div key={i} className="p-5 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-4">
          <div className={`${pulse} h-12 w-12 rounded-lg`} />
          <div className="flex-1 space-y-2">
            <SkeletonBar className="h-3 w-16" />
            <SkeletonBar className="h-6 w-24" />
          </div>
        </div>
      </div>
    ))}
  </div>
);

/** Skeleton for a table with rows */
export const SkeletonTable: React.FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 4 }) => (
  <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
    {/* Header */}
    <div className="flex gap-4 px-4 py-3 bg-gray-50 dark:bg-gray-800">
      {Array.from({ length: cols }).map((_, i) => (
        <SkeletonBar key={i} className="h-3 w-20" />
      ))}
    </div>
    {/* Rows */}
    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} className="flex gap-4 px-4 py-3 border-t border-gray-100 dark:border-gray-700">
        {Array.from({ length: cols }).map((_, j) => (
          <SkeletonBar key={j} className={`h-4 ${j === 0 ? 'w-48' : 'w-24'}`} />
        ))}
      </div>
    ))}
  </div>
);

/** Skeleton for the Objects/Entities card list */
export const SkeletonCardList: React.FC<{ rows?: number }> = ({ rows = 5 }) => (
  <div className="space-y-3">
    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} className="p-4 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-4">
          <div className={`${pulse} h-10 w-10 rounded-full`} />
          <div className="flex-1 space-y-2">
            <SkeletonBar className="h-4 w-48" />
            <SkeletonBar className="h-3 w-32" />
          </div>
          <SkeletonBar className="h-6 w-16 rounded-full" />
        </div>
      </div>
    ))}
  </div>
);

/** Skeleton for the full page layout (header + content) */
export const SkeletonPage: React.FC = () => (
  <div className="space-y-6">
    <div className="space-y-2">
      <SkeletonBar className="h-7 w-48" />
      <SkeletonBar className="h-4 w-64" />
    </div>
    <SkeletonStatCards count={4} />
    <SkeletonTable rows={5} cols={4} />
  </div>
);
