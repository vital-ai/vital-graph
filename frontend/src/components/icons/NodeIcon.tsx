import React from 'react';

interface NodeIconProps {
  className?: string;
}

const NodeIcon: React.FC<NodeIconProps> = ({ className = "h-5 w-5" }) => {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Central node (larger) */}
      <circle cx="12" cy="12" r="4" />
      
      {/* Connection lines extending outward */}
      <line x1="12" y1="8" x2="12" y2="4" stroke="currentColor" strokeWidth="2" />
      <line x1="16" y1="12" x2="20" y2="12" stroke="currentColor" strokeWidth="2" />
      <line x1="12" y1="16" x2="12" y2="20" stroke="currentColor" strokeWidth="2" />
      <line x1="8" y1="12" x2="4" y2="12" stroke="currentColor" strokeWidth="2" />
      
      {/* Small endpoint nodes */}
      <circle cx="12" cy="4" r="1.5" />
      <circle cx="20" cy="12" r="1.5" />
      <circle cx="12" cy="20" r="1.5" />
      <circle cx="4" cy="12" r="1.5" />
    </svg>
  );
};

export default NodeIcon;
