import React from 'react';

interface RdfIconProps {
  className?: string;
  size?: number;
}

const RdfIcon: React.FC<RdfIconProps> = ({ className = "w-5 h-5", size = 20 }) => {
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
      {/* Three nodes connected by edges — RDF triple graph */}
      <circle cx="12" cy="4" r="2.5" fill="currentColor" />
      <circle cx="5" cy="19" r="2.5" fill="currentColor" />
      <circle cx="19" cy="19" r="2.5" fill="currentColor" />
      <path d="M12 6.5 L6.5 17" strokeWidth="2" />
      <path d="M12 6.5 L17.5 17" strokeWidth="2" />
      <path d="M7.5 19 L16.5 19" strokeWidth="2" />
    </svg>
  );
};

export default RdfIcon;
