import React from 'react';

interface GraphIconProps {
  className?: string;
}

const GraphIcon: React.FC<GraphIconProps> = ({ className = "h-5 w-5" }) => {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Top node */}
      <circle cx="18" cy="6" r="3" />
      
      {/* Bottom left node */}
      <circle cx="6" cy="18" r="3" />
      
      {/* Bottom right node */}
      <circle cx="18" cy="18" r="3" />
      
      {/* Connection lines */}
      <line x1="15.5" y1="7.5" x2="8.5" y2="16.5" stroke="currentColor" strokeWidth="2" />
      <line x1="18" y1="9" x2="18" y2="15" stroke="currentColor" strokeWidth="2" />
      <line x1="9" y1="18" x2="15" y2="18" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
};

export default GraphIcon;
