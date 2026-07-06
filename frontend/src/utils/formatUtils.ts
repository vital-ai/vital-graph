/**
 * formatUtils — Shared formatting helpers used across pages.
 */

/** Format a byte count into a human-readable size string */
export const formatFileSize = (bytes: number | null | undefined): string => {
  if (!bytes) return bytes === 0 ? '0 Bytes' : '-';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

/** Format an ISO date string into a locale-appropriate display string */
export const formatDateTime = (dateString: string): string => {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleString();
  } catch {
    return 'Invalid Date';
  }
};

/** Format an ISO date string as "Jan 15, 2025" */
export const formatDateShort = (dateString: string | undefined): string => {
  if (!dateString) return '—';
  const d = new Date(dateString);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
};

/** Format an ISO date string as "Jan 15, 2025, 03:45 PM" */
export const formatDateTimeFull = (dateString: string | undefined): string => {
  if (!dateString) return '—';
  const d = new Date(dateString);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

/** Format an ISO date string as a relative time string (e.g., "2 hours ago") */
export const formatRelativeTime = (dateString: string | undefined | null): string => {
  if (!dateString) return '—';
  const d = new Date(dateString);
  if (isNaN(d.getTime())) return '—';

  const now = Date.now();
  const diffMs = now - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);
  const diffWeek = Math.floor(diffDay / 7);
  const diffMonth = Math.floor(diffDay / 30);

  if (diffSec < 10) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  if (diffWeek < 5) return `${diffWeek}w ago`;
  if (diffMonth < 12) return `${diffMonth}mo ago`;
  return `${Math.floor(diffDay / 365)}y ago`;
};

/** Map a job status string to a Flowbite badge color */
export const getJobStatusColor = (status: string): string => {
  switch (status) {
    case 'completed': case 'vectorizing': return 'success';
    case 'running': case 'processing': case 'in_progress': return 'info';
    case 'created': case 'pending': return 'warning';
    case 'failed': return 'failure';
    case 'cancelled': case 'canceled': return 'gray';
    default: return 'gray';
  }
};
