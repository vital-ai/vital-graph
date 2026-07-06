import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Card,
  Button,
  Select,
  Label,
  TextInput,
  Alert,
  Spinner,
  Badge,
  Progress,
  Breadcrumb,
  BreadcrumbItem
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiPlay,
  HiTrash,
  HiDownload,
  HiHome
} from 'react-icons/hi';
import { importExportService, type ImportExportJob } from '../services/ImportExportService';
import { apiService } from '../services/ApiService';
import DataIcon from '../components/icons/DataIcon';
import JobLogViewer from '../components/JobLogViewer';
import { formatFileSize, formatDateTime, getJobStatusColor } from '../utils/formatUtils';

const POLL_INTERVAL_MS = 2000;

interface SpaceOption {
  space: string;
  space_name: string;
}

const DataExportDetail: React.FC = () => {
  const navigate = useNavigate();
  const { exportId } = useParams<{ exportId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = !exportId || exportId === 'new';

  const [job, setJob] = useState<ImportExportJob | null>(null);
  const [spaces, setSpaces] = useState<SpaceOption[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Form state for new exports
  const [formData, setFormData] = useState({
    space_id: '',
    graph_uri: '',
    file_format: 'nt',
  });

  // Get URL parameters for prepopulation
  const urlSpaceId = searchParams.get('spaceId');
  const urlGraphUri = searchParams.get('graphUri');

  // Fetch spaces list and job details
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const spacesList = await apiService.getSpaces();
      setSpaces(spacesList);

      if (!isNew && exportId) {
        const jobData = await importExportService.getExportJob(exportId);
        setJob(jobData);
      } else {
        setFormData(prev => ({
          ...prev,
          space_id: urlSpaceId || prev.space_id,
          graph_uri: urlGraphUri || prev.graph_uri,
        }));
      }
      setError(null);
    } catch {
      setError('Failed to load data.');
    } finally {
      setLoading(false);
    }
  }, [exportId, isNew, urlSpaceId, urlGraphUri]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll active job for progress
  useEffect(() => {
    if (job && (job.status === 'running' || job.status === 'processing')) {
      pollRef.current = setInterval(async () => {
        try {
          const updated = await importExportService.getExportJob(job.job_id);
          setJob(updated);
          if (updated.status !== 'running' && updated.status !== 'processing') {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch { /* ignore poll errors */ }
      }, POLL_INTERVAL_MS);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job?.job_id, job?.status]);

  const formatDate = (s: string | null | undefined) => formatDateTime(s || '');

  const getStatusColor = getJobStatusColor;

  // Event handlers
  const handleInputChange = (field: string, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleCreateAndExecute = async () => {
    if (!formData.space_id) { setError('Space is required'); return; }

    try {
      setSaving(true);
      setError(null);

      // 1. Create export job
      const newJob = await importExportService.createExportJob({
        space_id: formData.space_id,
        graph_uri: formData.graph_uri || undefined,
        file_format: formData.file_format || undefined,
      });

      // 2. Execute immediately
      await importExportService.executeExportJob(newJob.job_id);

      // Navigate to the job detail page
      navigate(`/data/export/${newJob.job_id}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create export.');
    } finally {
      setSaving(false);
    }
  };

  const handleExecute = async () => {
    if (!job) return;
    try {
      await importExportService.executeExportJob(job.job_id);
      const updated = await importExportService.getExportJob(job.job_id);
      setJob(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start export.');
    }
  };

  const handleDownload = async () => {
    if (!job) return;
    const url = importExportService.getExportDownloadUrl(job.job_id);
    const token = localStorage.getItem('access_token');
    const resp = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = job.file_name || 'export';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(blobUrl);
  };

  const handleDelete = async () => {
    if (!job || !window.confirm('Are you sure you want to delete this export job?')) return;
    try {
      await importExportService.deleteExportJob(job.job_id);
      navigate('/data/export');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete export.');
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
    <div className="space-y-6" data-testid="data-export-detail-page">
      {/* Breadcrumb */}
      <Breadcrumb className="mb-4">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        <BreadcrumbItem href="/data" icon={DataIcon}>
          Data
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isNew ? 'New Export' : `Export ${job?.job_id?.slice(0, 8) || ''}`}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Export' : 'Export Job Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Select a space, format, and start exporting' : 'View and manage your export job'}
        </p>
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Form / Details */}
        <div className="lg:col-span-2">
          <Card>
            <div className="space-y-4">
              {isNew ? (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="space">Space *</Label>
                      <Select
                        id="space"
                        value={formData.space_id}
                        onChange={(e) => handleInputChange('space_id', e.target.value)}
                      >
                        <option value="">Select a space</option>
                        {spaces.map((space) => (
                          <option key={space.space} value={space.space}>
                            {space.space_name || space.space}
                          </option>
                        ))}
                      </Select>
                    </div>

                    <div>
                      <Label htmlFor="file_format">Format</Label>
                      <Select
                        id="file_format"
                        value={formData.file_format}
                        onChange={(e) => handleInputChange('file_format', e.target.value)}
                      >
                        <option value="nt">N-Triples (.nt)</option>
                        <option value="nq">N-Quads (.nq)</option>
                        <option value="jsonl">JSONL (.jsonl)</option>
                      </Select>
                    </div>
                  </div>

                  <div>
                    <Label htmlFor="graph_uri">Graph URI (optional — leave blank for all graphs)</Label>
                    <TextInput
                      id="graph_uri"
                      type="text"
                      value={formData.graph_uri}
                      onChange={(e) => handleInputChange('graph_uri', e.target.value)}
                      placeholder="urn:my-space or leave blank for all"
                    />
                  </div>

                  <div className="flex gap-2 pt-4">
                    <Button color="gray" onClick={() => navigate('/data/export')}>
                      <HiArrowLeft className="w-4 h-4 mr-2" />
                      Cancel
                    </Button>
                    <Button color="blue" onClick={handleCreateAndExecute} disabled={saving}>
                      {saving ? <Spinner size="sm" className="mr-2" /> : <HiPlay className="w-4 h-4 mr-2" />}
                      {saving ? 'Creating...' : 'Create & Start Export'}
                    </Button>
                  </div>
                </>
              ) : job ? (
                <>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div><Label>Job ID</Label><p className="font-mono text-gray-700 dark:text-gray-300">{job.job_id}</p></div>
                    <div><Label>Space</Label><p className="text-gray-700 dark:text-gray-300">{job.space_id}</p></div>
                    <div><Label>Graph URI</Label><p className="text-gray-700 dark:text-gray-300">{job.graph_uri || '(all)'}</p></div>
                    <div><Label>Format</Label><p className="text-gray-700 dark:text-gray-300">{job.file_format || '-'}</p></div>
                    <div><Label>File</Label><p className="text-gray-700 dark:text-gray-300">{job.file_name || '-'} ({formatFileSize(job.file_size)})</p></div>
                  </div>

                  <div className="flex gap-2 pt-4">
                    <Button color="gray" onClick={() => navigate('/data/export')}>
                      <HiArrowLeft className="w-4 h-4 mr-2" />
                      Back
                    </Button>
                    {job.status === 'created' && (
                      <Button color="green" onClick={handleExecute}>
                        <HiPlay className="w-4 h-4 mr-2" />
                        Start Export
                      </Button>
                    )}
                    {job.status === 'completed' && (
                      <Button color="green" onClick={handleDownload}>
                        <HiDownload className="w-4 h-4 mr-2" />
                        Download
                      </Button>
                    )}
                    {job.status !== 'running' && job.status !== 'processing' && (
                      <Button color="red" onClick={handleDelete}>
                        <HiTrash className="w-4 h-4 mr-2" />
                        Delete
                      </Button>
                    )}
                  </div>
                </>
              ) : (
                <p className="text-gray-500">Job not found.</p>
              )}
            </div>
          </Card>
        </div>

        {/* Status Panel */}
        {job && (
          <div className="lg:col-span-1">
            <Card>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Export Status
              </h3>
              <div className="space-y-4">
                <div>
                  <Label>Status</Label>
                  <Badge color={getStatusColor(job.status)} className="mt-1">
                    {job.status}
                  </Badge>
                </div>

                <div>
                  <Label>Progress</Label>
                  <Progress
                    progress={job.progress_pct}
                    color={job.status === 'failed' ? 'red' : 'blue'}
                    className="mt-1"
                  />
                  <div className="text-sm text-gray-500 mt-1">
                    {job.progress_pct.toFixed(1)}% — {job.records_done.toLocaleString()} records
                    {job.records_total ? ` / ${job.records_total.toLocaleString()}` : ''}
                  </div>
                </div>

                <div>
                  <Label>Created</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatDate(job.created_at)}
                  </div>
                </div>

                {job.started_at && (
                  <div>
                    <Label>Started</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(job.started_at)}
                    </div>
                  </div>
                )}

                {job.completed_at && (
                  <div>
                    <Label>Completed</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(job.completed_at)}
                    </div>
                  </div>
                )}

                {job.error_message && (
                  <div>
                    <Label>Error</Label>
                    <div className="text-sm text-red-600 dark:text-red-400">
                      {job.error_message}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* Log viewer for existing jobs */}
      {job && !isNew && (
        <JobLogViewer
          jobId={job.job_id}
          jobStatus={job.status}
          fetchLog={async (id) => {
            const j = await importExportService.getExportJob(id);
            const entries = (j.log_entries || []).map(e =>
              typeof e === 'string' ? { message: e } : e
            );
            return { job_id: id, log_entries: entries, total_entries: entries.length };
          }}
        />
      )}
    </div>
  );
};

export default DataExportDetail;
