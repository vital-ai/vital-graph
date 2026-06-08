import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Card, Badge, Spinner } from 'flowbite-react';
import { HiRefresh } from 'react-icons/hi';
import { type LogEntry } from '../services/ImportExportService';

const POLL_INTERVAL_MS = 3000;

interface JobLogViewerProps {
  jobId: string;
  jobStatus: string;
  fetchLog: (jobId: string) => Promise<{ log_entries: LogEntry[]; total_entries: number }>;
}

const getLevelColor = (level?: string): string => {
  switch (level?.toLowerCase()) {
    case 'error': return 'text-red-600 dark:text-red-400';
    case 'warning': case 'warn': return 'text-yellow-600 dark:text-yellow-400';
    case 'info': return 'text-blue-600 dark:text-blue-400';
    case 'debug': return 'text-gray-500 dark:text-gray-500';
    default: return 'text-gray-700 dark:text-gray-300';
  }
};

const getLevelBadgeColor = (level?: string): string => {
  switch (level?.toLowerCase()) {
    case 'error': return 'failure';
    case 'warning': case 'warn': return 'warning';
    case 'info': return 'info';
    default: return 'gray';
  }
};

const JobLogViewer: React.FC<JobLogViewerProps> = ({ jobId, jobStatus, fetchLog }) => {
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadLog = useCallback(async () => {
    try {
      const data = await fetchLog(jobId);
      setLogEntries(data.log_entries || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load log');
    } finally {
      setLoading(false);
    }
  }, [jobId, fetchLog]);

  // Initial load
  useEffect(() => {
    loadLog();
  }, [loadLog]);

  // Poll while job is active
  useEffect(() => {
    const isActive = jobStatus === 'running' || jobStatus === 'processing';
    if (isActive) {
      pollRef.current = setInterval(loadLog, POLL_INTERVAL_MS);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobStatus, loadLog]);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logEntries.length]);

  if (loading) {
    return (
      <Card className="mt-6">
        <div className="flex justify-center items-center h-24">
          <Spinner size="md" />
        </div>
      </Card>
    );
  }

  return (
    <Card className="mt-6">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Job Log
          {logEntries.length > 0 && (
            <span className="ml-2 text-sm font-normal text-gray-500">
              ({logEntries.length} entries)
            </span>
          )}
        </h3>
        <button
          onClick={loadLog}
          className="p-1.5 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 rounded"
          title="Refresh log"
        >
          <HiRefresh className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <p className="text-sm text-red-500 mb-2">{error}</p>
      )}

      <div className="bg-gray-900 rounded-lg p-4 max-h-96 overflow-y-auto font-mono text-xs leading-relaxed">
        {logEntries.length === 0 ? (
          <p className="text-gray-500 italic">No log entries yet.</p>
        ) : (
          logEntries.map((entry, idx) => (
            <div key={idx} className="flex gap-2 py-0.5">
              {entry.timestamp && (
                <span className="text-gray-500 whitespace-nowrap shrink-0">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
              )}
              {entry.level && (
                <Badge color={getLevelBadgeColor(entry.level)} size="xs" className="shrink-0">
                  {entry.level.toUpperCase()}
                </Badge>
              )}
              <span className={getLevelColor(entry.level)}>
                {entry.message}
              </span>
            </div>
          ))
        )}
        <div ref={logEndRef} />
      </div>
    </Card>
  );
};

export default JobLogViewer;
