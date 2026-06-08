import React, { useState, useEffect } from 'react';
import { formatRelativeTime, formatDateTimeFull } from '../utils/formatUtils';

interface TimeAgoProps {
  date: string | undefined | null;
  className?: string;
}

/**
 * Displays relative time (e.g., "2h ago") with full date/time on hover.
 * Auto-updates every 60s.
 */
const TimeAgo: React.FC<TimeAgoProps> = ({ date, className = '' }) => {
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 60000);
    return () => clearInterval(interval);
  }, []);

  if (!date) return <span className={className}>—</span>;

  return (
    <span className={className} title={formatDateTimeFull(date)}>
      {formatRelativeTime(date)}
    </span>
  );
};

export default TimeAgo;
