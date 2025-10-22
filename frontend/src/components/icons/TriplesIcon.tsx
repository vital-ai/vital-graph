import React from 'react';

interface TriplesIconProps {
  className?: string;
  size?: number;
}

const TriplesIcon: React.FC<TriplesIconProps> = ({ className = "w-5 h-5", size = 20 }) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {/* Arrow pointing right with dot at left endpoint */}
      {/* Dot at left endpoint */}
      <circle cx="4" cy="12" r="2.5" fill="currentColor" />
      
      {/* Arrow shaft */}
      <path d="M7 12 L18 12" strokeWidth="2.5" />
      
      {/* Arrow head */}
      <path d="M15 9 L18 12 L15 15" strokeWidth="2.5" />
    </svg>
  );
};

export default TriplesIcon;
