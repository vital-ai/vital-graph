import React from 'react';

interface ObjectIconProps {
  className?: string;
  size?: number;
}

const ObjectIcon: React.FC<ObjectIconProps> = ({ className = "w-5 h-5", size = 20 }) => {
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
      {/* Larger 3D cube to match other icon sizes */}
      {/* Top face */}
      <path d="M12 2 L19 6 L12 10 L5 6 Z" fill="currentColor" fillOpacity="0.2" />
      
      {/* Left face */}
      <path d="M5 6 L5 15 L12 19 L12 10 Z" fill="currentColor" fillOpacity="0.1" />
      
      {/* Right face */}
      <path d="M12 10 L12 19 L19 15 L19 6 Z" fill="currentColor" fillOpacity="0.3" />
      
      {/* Cube outline */}
      <path d="M12 2 L19 6 L12 10 L5 6 Z" />
      <path d="M5 6 L5 15" />
      <path d="M19 6 L19 15" />
      <path d="M5 15 L12 19" />
      <path d="M19 15 L12 19" />
      <path d="M12 10 L12 19" />
      
      {/* Connection nodes at corners - larger to match scale */}
      <circle cx="12" cy="2" r="2" fill="currentColor" />
      <circle cx="5" cy="6" r="2" fill="currentColor" />
      <circle cx="19" cy="6" r="2" fill="currentColor" />
      <circle cx="12" cy="19" r="2" fill="currentColor" />
    </svg>
  );
};

export default ObjectIcon;
