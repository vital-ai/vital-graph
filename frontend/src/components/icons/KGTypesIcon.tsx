import React from 'react';

interface KGTypesIconProps {
  className?: string;
}

const KGTypesIcon: React.FC<KGTypesIconProps> = ({ className = "h-6 w-6" }) => {
  return (
    <svg
      className={className}
      fill="currentColor"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
      <circle cx="7" cy="9" r="1.5" fill="currentColor"/>
      <circle cx="17" cy="9" r="1.5" fill="currentColor"/>
      <circle cx="12" cy="15" r="1.5" fill="currentColor"/>
    </svg>
  );
};

export default KGTypesIcon;
