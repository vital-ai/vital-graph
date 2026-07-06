import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Button,
  Card,
  Label,
  TextInput,
  Select,
  Alert,
  Badge,
  Progress,
  Spinner,
  Breadcrumb,
  BreadcrumbItem
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiPlay,
  HiTrash,
  HiUpload,
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

const DataImportDetail: React.FC = () => {
  const navigate = useNavigate();
  const { importId } = useParams<{ importId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = !importId || importId === 'new';

  const [job, setJob] = useState<ImportExportJob | null>(null);
  const [spaces, setSpaces] = useState<SpaceOption[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Form state for new imports
  const [formData, setFormData] = useState({
    space_id: '',
    graph_uri: '',
    mode: 'append' as 'append' | 'replace',
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

      if (!isNew && importId) {
        const jobData = await importExportService.getImportJob(importId);
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
  }, [importId, isNew, urlSpaceId, urlGraphUri]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll active job for progress
  useEffect(() => {
    if (job && (job.status === 'running' || job.status === 'processing')) {
      pollRef.current = setInterval(async () => {
        try {
          const updated = await importExportService.getImportJob(job.job_id);
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

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file || null);
  };

  const handleCreateAndUpload = async () => {
    if (!formData.space_id) { setError('Space is required'); return; }
    if (!selectedFile) { setError('File is required'); return; }

    try {
      setSaving(true);
      setError(null);

      // 1. Create job
      const newJob = await importExportService.createImportJob({
        space_id: formData.space_id,
        graph_uri: formData.graph_uri || undefined,
        mode: formData.mode,
        file_format: formData.file_format || undefined,
      });

      // 2. Upload file
      await importExportService.uploadImportFile(newJob.job_id, selectedFile);

      // 3. Execute immediately
      await importExportService.executeImportJob(newJob.job_id);

      // Navigate to the job detail page
      navigate(`/data/import/${newJob.job_id}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create import.');
    } finally {
      setSaving(false);
    }
  };

  const handleExecute = async () => {
    if (!job) return;
    try {
      await importExportService.executeImportJob(job.job_id);
      const updated = await importExportService.getImportJob(job.job_id);
      setJob(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start import.');
    }
  };

  const handleDelete = async () => {
    if (!job || !window.confirm('Are you sure you want to delete this import job?')) return;
    try {
      await importExportService.deleteImportJob(job.job_id);
      navigate('/data/import');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete import.');
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
    <div className="space-y-6" data-testid="data-import-detail-page">
      {/* Breadcrumb */}
      <Breadcrumb className="mb-4">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        <BreadcrumbItem href="/data" icon={DataIcon}>
          Data
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isNew ? 'New Import' : `Import ${job?.job_id?.slice(0, 8) || ''}`}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Import' : 'Import Job Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Select a space, upload a file, and start importing' : 'View and manage your import job'}
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
                      <Label htmlFor="mode">Mode</Label>
                      <Select
                        id="mode"
                        value={formData.mode}
                        onChange={(e) => handleInputChange('mode', e.target.value)}
                      >
                        <option value="append">Append</option>
                        <option value="replace">Replace</option>
                      </Select>
                    </div>
                  </div>

                  <div>
                    <Label htmlFor="graph_uri">Graph URI (optional)</Label>
                    <TextInput
                      id="graph_uri"
                      type="text"
                      value={formData.graph_uri}
                      onChange={(e) => handleInputChange('graph_uri', e.target.value)}
                      placeholder="urn:my-space or leave blank for default"
                    />
                  </div>

                  <div>
                    <Label htmlFor="file_format">File Format</Label>
                    <Select
                      id="file_format"
                      value={formData.file_format}
                      onChange={(e) => handleInputChange('file_format', e.target.value)}
                    >
                      <option value="nt">N-Triples (.nt)</option>
                      <option value="nq">N-Quads (.nq)</option>
                      <option value="jsonl">JSONL (.jsonl)</option>
                      <option value="ttl">Turtle (.ttl)</option>
                    </Select>
                  </div>

                  {/* File upload zone */}
                  <div>
                    <Label htmlFor="file">Import File *</Label>
                    <div
                      className="flex flex-col items-center justify-center w-full h-48 border-2 border-gray-300 border-dashed rounded-lg cursor-pointer bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:hover:border-gray-500 dark:hover:bg-gray-600"
                      onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length > 0) setSelectedFile(e.dataTransfer.files[0]); }}
                      onDragOver={(e) => e.preventDefault()}
                      onClick={() => document.getElementById('file')?.click()}
                    >
                      <div className="flex flex-col items-center justify-center pt-5 pb-6">
                        <svg className="w-8 h-8 mb-4 text-gray-500 dark:text-gray-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 16">
                          <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 13h3a3 3 0 0 0 0-6h-.025A5.56 5.56 0 0 0 16 6.5 5.5 5.5 0 0 0 5.207 5.021C5.137 5.017 5.071 5 5 5a4 4 0 0 0 0 8h2.167M10 15V6m0 0L8 8m2-2 2 2"/>
                        </svg>
                        {selectedFile ? (
                          <div className="text-center">
                            <p className="mb-1 text-sm font-semibold text-gray-700 dark:text-gray-300">{selectedFile.name}</p>
                            <p className="text-xs text-gray-500">{formatFileSize(selectedFile.size)}</p>
                            <p className="mt-1 text-xs text-blue-500">Click to change</p>
                          </div>
                        ) : (
                          <div className="text-center">
                            <p className="mb-1 text-sm text-gray-500"><span className="font-semibold">Click to upload</span> or drag and drop</p>
                            <p className="text-xs text-gray-500">.nt, .nq, .jsonl, .ttl</p>
                          </div>
                        )}
                      </div>
                      <input id="file" type="file" className="hidden" onChange={handleFileChange} accept=".nt,.nq,.jsonl,.ttl" />
                    </div>
                  </div>

                  <div className="flex gap-2 pt-4">
                    <Button color="gray" onClick={() => navigate('/data/import')}>
                      <HiArrowLeft className="w-4 h-4 mr-2" />
                      Cancel
                    </Button>
                    <Button color="blue" onClick={handleCreateAndUpload} disabled={saving}>
                      {saving ? <Spinner size="sm" className="mr-2" /> : <HiUpload className="w-4 h-4 mr-2" />}
                      {saving ? 'Creating...' : 'Create & Start Import'}
                    </Button>
                  </div>
                </>
              ) : job ? (
                <>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div><Label>Job ID</Label><p className="font-mono text-gray-700 dark:text-gray-300">{job.job_id}</p></div>
                    <div><Label>Space</Label><p className="text-gray-700 dark:text-gray-300">{job.space_id}</p></div>
                    <div><Label>Graph URI</Label><p className="text-gray-700 dark:text-gray-300">{job.graph_uri || '(default)'}</p></div>
                    <div><Label>Mode</Label><p className="text-gray-700 dark:text-gray-300">{job.mode || 'append'}</p></div>
                    <div><Label>Format</Label><p className="text-gray-700 dark:text-gray-300">{job.file_format || '-'}</p></div>
                    <div><Label>File</Label><p className="text-gray-700 dark:text-gray-300">{job.file_name || '-'} ({formatFileSize(job.file_size)})</p></div>
                  </div>

                  <div className="flex gap-2 pt-4">
                    <Button color="gray" onClick={() => navigate('/data/import')}>
                      <HiArrowLeft className="w-4 h-4 mr-2" />
                      Back
                    </Button>
                    {job.status === 'created' && job.file_name && (
                      <Button color="green" onClick={handleExecute}>
                        <HiPlay className="w-4 h-4 mr-2" />
                        Start Import
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
                Import Status
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
          fetchLog={importExportService.getImportLog.bind(importExportService)}
        />
      )}
    </div>
  );
};

export default DataImportDetail;
