import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Badge,
  Progress,
  Spinner,
  Alert
} from 'flowbite-react';
import {
  HiPlus,
  HiEye,
  HiTrash,
  HiPlay,
  HiStop
} from 'react-icons/hi';
import { importExportService, type ImportExportJob } from '../services/ImportExportService';
import DataIcon from '../components/icons/DataIcon';
import { formatFileSize, formatDateTime, getJobStatusColor } from '../utils/formatUtils';

const POLL_INTERVAL_MS = 2000;

const DataImportPage: React.FC = () => {
  const navigate = useNavigate();
  const [imports, setImports] = useState<ImportExportJob[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch import jobs from API
  const fetchData = useCallback(async () => {
    try {
      const jobs = await importExportService.listImportJobs();
      setImports(jobs);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load import jobs.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll active jobs for progress
  useEffect(() => {
    const hasActive = imports.some(j => j.status === 'running' || j.status === 'processing');
    if (hasActive) {
      pollRef.current = setInterval(fetchData, POLL_INTERVAL_MS);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [imports, fetchData]);

  const formatDate = (s: string | null | undefined) => formatDateTime(s || '');

  const getStatusColor = getJobStatusColor;

  // Action handlers
  const handleExecuteImport = async (jobId: string) => {
    try {
      await importExportService.executeImportJob(jobId);
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start import');
    }
  };

  const handleDeleteImport = async (jobId: string) => {
    if (!window.confirm('Are you sure you want to delete this import job?')) return;
    try {
      await importExportService.deleteImportJob(jobId);
      setImports(prev => prev.filter(j => j.job_id !== jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-40">
        <Spinner size="xl" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Data Import
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Import data into your RDF graphs
        </p>
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card>
        <div className="p-6">
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Import Jobs
              </h2>
              <Button
                color="blue"
                onClick={() => navigate('/data/import/new')}
              >
                <HiPlus className="w-4 h-4 mr-2" />
                New Import
              </Button>
            </div>

            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeadCell>Job ID</TableHeadCell>
                    <TableHeadCell>Space</TableHeadCell>
                    <TableHeadCell>Graph</TableHeadCell>
                    <TableHeadCell>File</TableHeadCell>
                    <TableHeadCell>Format</TableHeadCell>
                    <TableHeadCell>Status</TableHeadCell>
                    <TableHeadCell>Progress</TableHeadCell>
                    <TableHeadCell>Created</TableHeadCell>
                    <TableHeadCell>Actions</TableHeadCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {imports.map((job) => (
                    <TableRow key={job.job_id}>
                      <TableCell className="font-mono text-xs">
                        {job.job_id.slice(0, 8)}...
                      </TableCell>
                      <TableCell>{job.space_id}</TableCell>
                      <TableCell className="text-xs max-w-[120px] truncate">
                        {job.graph_uri || '-'}
                      </TableCell>
                      <TableCell>
                        <div>
                          <div className="font-medium text-sm">{job.file_name || '-'}</div>
                          <div className="text-xs text-gray-500">
                            {formatFileSize(job.file_size)}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge color="gray">{job.file_format || '-'}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge color={getStatusColor(job.status)}>
                          {job.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="w-24">
                          <Progress
                            progress={job.progress_pct}
                            color={job.status === 'failed' ? 'red' : 'blue'}
                            size="sm"
                          />
                          <div className="text-xs text-gray-500 mt-1">
                            {job.progress_pct.toFixed(0)}%
                            {job.records_done > 0 && (
                              <span className="ml-1">({job.records_done.toLocaleString()})</span>
                            )}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs">
                        {formatDate(job.created_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            size="xs"
                            color="blue"
                            onClick={() => navigate(`/data/import/${job.job_id}`)}
                          >
                            <HiEye className="w-3 h-3" />
                          </Button>
                          {job.status === 'created' && job.file_name && (
                            <Button
                              size="xs"
                              color="green"
                              onClick={() => handleExecuteImport(job.job_id)}
                            >
                              <HiPlay className="w-3 h-3" />
                            </Button>
                          )}
                          {(job.status === 'running' || job.status === 'processing') && (
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteImport(job.job_id)}
                            >
                              <HiStop className="w-3 h-3" />
                            </Button>
                          )}
                          {job.status !== 'running' && job.status !== 'processing' && (
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteImport(job.job_id)}
                            >
                              <HiTrash className="w-3 h-3" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {imports.length === 0 && (
              <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                No import jobs found. Create your first import to get started.
              </div>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
};

export default DataImportPage;
