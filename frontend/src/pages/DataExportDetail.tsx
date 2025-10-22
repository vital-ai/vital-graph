import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Card,
  Button,
  Select,
  Label,
  Alert,
  Spinner,
  Badge,
  Progress,
  Breadcrumb,
  BreadcrumbItem,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiPlay,
  HiStop,
  HiTrash,
  HiDownload,
  HiHome,
  HiExclamationCircle
} from 'react-icons/hi';
import { mockDataExports, type DataExport } from '../mock/data';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import DataIcon from '../components/icons/DataIcon';

const DataExportDetail: React.FC = () => {
  const navigate = useNavigate();
  const { exportId } = useParams<{ exportId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = exportId === 'new';
  
  const [exportData, setExportData] = useState<DataExport | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [deleting, setDeleting] = useState<boolean>(false);
  
  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    space_id: '',
    graph_id: 0,
    export_format: 'turtle' as 'rdf/xml' | 'turtle' | 'n-triples' | 'json-ld' | 'n-quads'
  });

  // Get URL parameters for prepopulation
  const urlSpaceId = searchParams.get('spaceId');
  const urlGraphId = searchParams.get('graphId');

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      // Simulate API calls
      await new Promise(resolve => setTimeout(resolve, 300));
      
      setSpaces(mockSpaces);
      setGraphs(mockGraphs);
      
      if (!isNew && exportId) {
        const existingExport = mockDataExports.find(exp => exp.id === parseInt(exportId));
        if (existingExport) {
          setExportData(existingExport);
          setFormData({
            name: existingExport.name,
            description: existingExport.description,
            space_id: existingExport.space_id,
            graph_id: existingExport.graph_id,
            export_format: existingExport.export_format
          });
        } else {
          setError('Export not found');
        }
      } else {
        // New export - initialize form with URL parameters if available
        const graphIdNum = urlGraphId ? parseInt(urlGraphId, 10) : 0;
        console.log('URL parameters:', { urlSpaceId, urlGraphId, graphIdNum });
        setFormData({
          name: '',
          description: '',
          space_id: urlSpaceId || '',
          graph_id: graphIdNum,
          export_format: 'turtle'
        });
      }
      
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to load data. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, [exportId, isNew, urlSpaceId, urlGraphId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Helper functions
  const getSpaceName = (spaceId: string) => {
    const space = spaces.find(s => s.space === spaceId);
    return space ? space.space_name : spaceId;
  };

  const getGraphName = (graphId: number) => {
    const graph = graphs.find(g => g.id === graphId);
    return graph ? graph.graph_name : `Graph ${graphId}`;
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'success';
      case 'processing': return 'info';
      case 'pending': return 'warning';
      case 'failed': return 'failure';
      case 'canceled': return 'gray';
      case 'expired': return 'gray';
      default: return 'gray';
    }
  };

  // Event handlers
  const handleInputChange = (field: string, value: string | number) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleSave = async () => {
    if (!formData.name.trim()) {
      setError('Name is required');
      return;
    }
    
    if (!formData.space_id) {
      setError('Space is required');
      return;
    }
    
    if (!formData.graph_id) {
      setError('Graph is required');
      return;
    }

    try {
      setSaving(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      if (isNew) {
        // Create new export
        console.log('Creating new export:', formData);
      } else {
        // Update existing export
        console.log('Updating export:', exportData?.id, formData);
      }
      
      navigate('/data/export');
    } catch (err) {
      console.error('Error saving export:', err);
      setError('Failed to save export. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async () => {
    if (!exportData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setExportData(prev => prev ? {
        ...prev,
        status: 'processing',
        started_time: new Date().toISOString(),
        progress: 10
      } : null);
    } catch (err) {
      console.error('Error starting export:', err);
      setError('Failed to start export. Please try again.');
    }
  };

  const handleCancel = async () => {
    if (!exportData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setExportData(prev => prev ? {
        ...prev,
        status: 'canceled',
        completed_time: new Date().toISOString()
      } : null);
    } catch (err) {
      console.error('Error canceling export:', err);
      setError('Failed to cancel export. Please try again.');
    }
  };

  const handleDownload = () => {
    if (exportData?.download_url) {
      // Create a temporary link and trigger download
      const link = document.createElement('a');
      link.href = exportData.download_url;
      link.download = `${exportData.name.replace(/\s+/g, '_')}.${exportData.export_format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  const handleDelete = async () => {
    if (!exportData) return;
    
    try {
      setDeleting(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      navigate('/data/export');
    } catch (err) {
      console.error('Error deleting export:', err);
      setError('Failed to delete export. Please try again.');
    } finally {
      setDeleting(false);
      setShowDeleteModal(false);
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
      {/* Breadcrumb */}
      <Breadcrumb className="mb-4">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        <BreadcrumbItem href="/data" icon={DataIcon}>
          Data
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isNew ? 'New Export' : exportData?.name || 'Export Details'}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Export' : 'Data Export Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Configure a new data export' : 'Manage your data export'}
        </p>
      </div>

      {error && (
        <Alert color="failure" className="mb-4">
          {error}
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Form */}
        <div className="lg:col-span-2">
          <Card>
            <div className="space-y-4">
              <div>
                <Label htmlFor="name">Name</Label>
                <input
                  type="text"
                  id="name"
                  className="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"
                  placeholder="Enter export name"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  disabled={!isNew && exportData?.status === 'processing'}
                />
              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <textarea
                  id="description"
                  rows={3}
                  className="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"
                  placeholder="Enter export description"
                  value={formData.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  disabled={!isNew && exportData?.status === 'processing'}
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="space">Space</Label>
                  <Select
                    id="space"
                    value={formData.space_id}
                    onChange={(e) => handleInputChange('space_id', e.target.value)}
                    disabled={!isNew && exportData?.status === 'processing'}
                  >
                    <option value="">Select a space</option>
                    {spaces.map((space) => (
                      <option key={space.space} value={space.space}>
                        {space.space_name}
                      </option>
                    ))}
                  </Select>
                </div>

                <div>
                  <Label htmlFor="graph">Graph</Label>
                  <Select
                    id="graph"
                    value={formData.graph_id}
                    onChange={(e) => handleInputChange('graph_id', parseInt(e.target.value))}
                    disabled={!formData.space_id || (!isNew && exportData?.status === 'processing')}
                  >
                    <option value={0}>Select a graph</option>
                    {graphs
                      .filter(graph => graph.space_id === formData.space_id)
                      .map((graph) => (
                        <option key={graph.id} value={graph.id}>
                          {graph.graph_name}
                        </option>
                      ))}
                  </Select>
                </div>
              </div>

              <div>
                <Label htmlFor="format">Export Format</Label>
                <Select
                  id="format"
                  value={formData.export_format}
                  onChange={(e) => handleInputChange('export_format', e.target.value)}
                  disabled={!isNew && exportData?.status === 'processing'}
                >
                  <option value="turtle">Turtle (.ttl)</option>
                  <option value="rdf/xml">RDF/XML (.rdf)</option>
                  <option value="n-triples">N-Triples (.nt)</option>
                  <option value="json-ld">JSON-LD (.jsonld)</option>
                  <option value="n-quads">N-Quads (.nq)</option>
                </Select>
              </div>

              <div className="flex gap-2 pt-4">
                <Button
                  color="gray"
                  onClick={() => navigate('/data/export')}
                >
                  <HiArrowLeft className="w-4 h-4 mr-2" />
                  Back to Data Exports
                </Button>
                
                {isNew ? (
                  <Button
                    color="blue"
                    onClick={handleSave}
                    disabled={saving}
                  >
                    {saving ? (
                      <Spinner size="sm" className="mr-2" />
                    ) : (
                      <HiDownload className="w-4 h-4 mr-2" />
                    )}
                    {saving ? 'Creating...' : 'Create Export'}
                  </Button>
                ) : (
                  <>
                    <Button
                      color="blue"
                      onClick={handleSave}
                      disabled={saving || exportData?.status === 'processing'}
                    >
                      {saving ? (
                        <Spinner size="sm" className="mr-2" />
                      ) : (
                        <HiDownload className="w-4 h-4 mr-2" />
                      )}
                      {saving ? 'Saving...' : 'Save Changes'}
                    </Button>
                    
                    {exportData?.status === 'pending' && (
                      <Button
                        color="green"
                        onClick={handleStart}
                      >
                        <HiPlay className="w-4 h-4 mr-2" />
                        Start Export
                      </Button>
                    )}
                    
                    {exportData?.status === 'processing' && (
                      <Button
                        color="red"
                        onClick={handleCancel}
                      >
                        <HiStop className="w-4 h-4 mr-2" />
                        Cancel Export
                      </Button>
                    )}
                    
                    {exportData?.status === 'completed' && exportData.download_url && (
                      <Button
                        color="green"
                        onClick={handleDownload}
                      >
                        <HiDownload className="w-4 h-4 mr-2" />
                        Download
                      </Button>
                    )}
                    
                    {exportData?.status !== 'processing' && (
                      <Button
                        color="red"
                        onClick={() => setShowDeleteModal(true)}
                      >
                        <HiTrash className="w-4 h-4 mr-2" />
                        Delete
                      </Button>
                    )}
                  </>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* Status Panel */}
        {!isNew && exportData && (
          <div className="lg:col-span-1">
            <Card>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Export Status
              </h3>
              
              <div className="space-y-4">
                <div>
                  <Label>Space</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {getSpaceName(exportData.space_id)}
                  </div>
                </div>

                <div>
                  <Label>Graph</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {getGraphName(exportData.graph_id)}
                  </div>
                </div>

                <div>
                  <Label>Status</Label>
                  <Badge color={getStatusColor(exportData.status)} className="mt-1">
                    {exportData.status}
                  </Badge>
                </div>

                <div>
                  <Label>Progress</Label>
                  <Progress
                    progress={exportData.progress}
                    color={exportData.status === 'failed' ? 'red' : 'blue'}
                    className="mt-1"
                  />
                  <div className="text-sm text-gray-500 mt-1">
                    {exportData.progress}% complete
                  </div>
                </div>

                <div>
                  <Label>Format</Label>
                  <Badge color="gray" className="mt-1">
                    {exportData.export_format}
                  </Badge>
                </div>

                {exportData.file_size && (
                  <div>
                    <Label>File Size</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatFileSize(exportData.file_size)}
                    </div>
                  </div>
                )}

                <div>
                  <Label>Created</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatDate(exportData.created_time)}
                  </div>
                </div>

                {exportData.started_time && (
                  <div>
                    <Label>Started</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(exportData.started_time)}
                    </div>
                  </div>
                )}

                {exportData.completed_time && (
                  <div>
                    <Label>Completed</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(exportData.completed_time)}
                    </div>
                  </div>
                )}

                {exportData.expires_at && (
                  <div>
                    <Label>Expires</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(exportData.expires_at)}
                    </div>
                  </div>
                )}

                {exportData.error_message && (
                  <div>
                    <Label>Error</Label>
                    <div className="text-sm text-red-600 dark:text-red-400">
                      {exportData.error_message}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)} size="md">
        <ModalHeader>
          <HiExclamationCircle className="mr-2 h-6 w-6 text-red-600" />
          Confirm Deletion
        </ModalHeader>
        <ModalBody>
          <p className="text-gray-500 dark:text-gray-400">
            Are you sure you want to delete this export? This action cannot be undone.
          </p>
          {exportData && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <p className="font-medium text-gray-900 dark:text-white">
                {exportData.name}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Status: {exportData.status}
              </p>
            </div>
          )}
        </ModalBody>
        <ModalFooter>
          <Button color="red" onClick={handleDelete} disabled={deleting}>
            {deleting ? (
              <>
                <Spinner size="sm" className="mr-2" />
                Deleting...
              </>
            ) : (
              <>
                <HiTrash className="mr-2 h-4 w-4" />
                Delete Export
              </>
            )}
          </Button>
          <Button color="gray" onClick={() => setShowDeleteModal(false)} disabled={deleting}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default DataExportDetail;
