import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Button,
  Card,
  Label,
  TextInput,
  Textarea,
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
  HiStop,
  HiTrash,
  HiUpload,
  HiHome
} from 'react-icons/hi';
import { mockDataImports, type DataImport } from '../mock/data';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import DataIcon from '../components/icons/DataIcon';

const DataImportDetail: React.FC = () => {
  const navigate = useNavigate();
  const { importId } = useParams<{ importId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = importId === 'new';
  
  const [importData, setImportData] = useState<DataImport | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  
  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    space_id: '',
    graph_id: 0
  });

  // Get URL parameters for prepopulation
  const urlSpaceId = searchParams.get('spaceId');
  const urlGraphId = searchParams.get('graphId');

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      // Simulate API calls
      await new Promise(resolve => setTimeout(resolve, 100));
      
      setSpaces(mockSpaces);
      setGraphs(mockGraphs);
      
      if (!isNew && importId) {
        const existingImport = mockDataImports.find(imp => imp.id === parseInt(importId));
        if (existingImport) {
          setImportData(existingImport);
          setFormData({
            name: existingImport.name,
            description: existingImport.description,
            space_id: existingImport.space_id,
            graph_id: existingImport.graph_id
          });
        } else {
          setError('Import not found');
        }
      } else {
        // New import - initialize form with URL parameters if available
        const graphIdNum = urlGraphId ? parseInt(urlGraphId, 10) : 0;
        console.log('URL parameters:', { urlSpaceId, urlGraphId, graphIdNum });
        setFormData({
          name: '',
          description: '',
          space_id: urlSpaceId || '',
          graph_id: graphIdNum
        });
      }
      
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to load data. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, [importId, isNew, urlSpaceId, urlGraphId]);


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

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file || null);
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
    
    if (isNew && !selectedFile) {
      setError('File is required for new imports');
      return;
    }

    try {
      setSaving(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      if (isNew) {
        // Create new import
        console.log('Creating new import:', formData, selectedFile);
      } else {
        // Update existing import
        console.log('Updating import:', importData?.id, formData);
      }
      
      navigate('/data/import');
    } catch (err) {
      console.error('Error saving import:', err);
      setError('Failed to save import. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async () => {
    if (!importData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setImportData(prev => prev ? {
        ...prev,
        status: 'processing',
        started_time: new Date().toISOString(),
        progress: 10
      } : null);
    } catch (err) {
      console.error('Error starting import:', err);
      setError('Failed to start import. Please try again.');
    }
  };

  const handleCancel = async () => {
    if (!importData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setImportData(prev => prev ? {
        ...prev,
        status: 'canceled',
        completed_time: new Date().toISOString()
      } : null);
    } catch (err) {
      console.error('Error canceling import:', err);
      setError('Failed to cancel import. Please try again.');
    }
  };

  const handleDelete = async () => {
    if (!importData || !window.confirm('Are you sure you want to delete this import?')) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      navigate('/data/import');
    } catch (err) {
      console.error('Error deleting import:', err);
      setError('Failed to delete import. Please try again.');
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
          {isNew ? 'New Import' : importData?.name || 'Import Details'}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Import' : 'Data Import Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Configure and upload a new data import' : 'Manage your data import'}
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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="space">Space</Label>
                  <Select
                    id="space"
                    value={formData.space_id}
                    onChange={(e) => handleInputChange('space_id', e.target.value)}
                    disabled={importId !== 'new' && importData?.status === 'processing'}
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
                    disabled={!formData.space_id || (importId !== 'new' && importData?.status === 'processing')}
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
                <Label htmlFor="name">Import Name</Label>
                <TextInput
                  id="name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  placeholder="Enter import name"
                  disabled={importId !== 'new' && importData?.status === 'processing'}
                />
              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  placeholder="Enter import description"
                  rows={3}
                  disabled={importId !== 'new' && importData?.status === 'processing'}
                />
              </div>

              {!importData && (
                <div>
                  <Label htmlFor="file">Import File</Label>
                  <div 
                    className="flex flex-col items-center justify-center w-full h-64 border-2 border-gray-300 border-dashed rounded-lg cursor-pointer bg-gray-50 dark:hover:bg-bray-800 dark:bg-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:hover:border-gray-500 dark:hover:bg-gray-600"
                    onDrop={(e) => {
                      e.preventDefault();
                      const files = e.dataTransfer.files;
                      if (files.length > 0) {
                        setSelectedFile(files[0]);
                      }
                    }}
                    onDragOver={(e) => e.preventDefault()}
                    onDragEnter={(e) => e.preventDefault()}
                    onClick={() => document.getElementById('file')?.click()}
                  >
                    <div className="flex flex-col items-center justify-center pt-5 pb-6">
                      <svg className="w-8 h-8 mb-4 text-gray-500 dark:text-gray-400" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 16">
                        <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 13h3a3 3 0 0 0 0-6h-.025A5.56 5.56 0 0 0 16 6.5 5.5 5.5 0 0 0 5.207 5.021C5.137 5.017 5.071 5 5 5a4 4 0 0 0 0 8h2.167M10 15V6m0 0L8 8m2-2 2 2"/>
                      </svg>
                      {selectedFile ? (
                        <div className="text-center">
                          <p className="mb-2 text-sm text-gray-500 dark:text-gray-400">
                            <span className="font-semibold">{selectedFile.name}</span>
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {formatFileSize(selectedFile.size)}
                          </p>
                          <p className="mt-2 text-xs text-blue-500 dark:text-blue-400">
                            Click to change file or drag and drop to replace
                          </p>
                        </div>
                      ) : (
                        <div className="text-center">
                          <p className="mb-2 text-sm text-gray-500 dark:text-gray-400">
                            <span className="font-semibold">Click to upload</span> or drag and drop
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Turtle (.ttl), RDF/XML (.rdf), OWL (.owl), N-Triples (.nt), N-Quads (.nq), JSON-LD (.jsonld)
                          </p>
                        </div>
                      )}
                    </div>
                    <input 
                      id="file" 
                      type="file" 
                      className="hidden" 
                      onChange={handleFileChange}
                      accept=".ttl,.rdf,.owl,.nt,.nq,.jsonld"
                    />
                  </div>
                </div>
              )}

              <div className="flex gap-2 pt-4">
                <Button
                  color="gray"
                  onClick={() => navigate('/data/import')}
                >
                  <HiArrowLeft className="w-4 h-4 mr-2" />
                  Back to Data Imports
                </Button>
                
                {!importData ? (
                  <Button
                    color="blue"
                    onClick={handleSave}
                    disabled={saving}
                  >
                    {saving ? (
                      <Spinner size="sm" className="mr-2" />
                    ) : (
                      <HiUpload className="w-4 h-4 mr-2" />
                    )}
                    {saving ? 'Creating...' : 'Create Import'}
                  </Button>
                ) : (
                  <>
                    {importData?.status === 'pending' && (
                      <Button
                        color="green"
                        onClick={handleStart}
                      >
                        <HiPlay className="w-4 h-4 mr-2" />
                        Start Import
                      </Button>
                    )}
                    
                    {importData?.status === 'processing' && (
                      <Button
                        color="red"
                        onClick={handleCancel}
                      >
                        <HiStop className="w-4 h-4 mr-2" />
                        Cancel Import
                      </Button>
                    )}
                    
                    <Button
                      color="red"
                      onClick={handleDelete}
                      disabled={importData?.status === 'processing'}
                    >
                      <HiTrash className="w-4 h-4 mr-2" />
                      Delete
                    </Button>
                  </>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* Status Panel */}
        {importData && (
          <div className="lg:col-span-1">
            <Card>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Import Status
              </h3>
              
              <div className="space-y-4">
                <div>
                  <Label>Space</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {getSpaceName(importData.space_id)}
                  </div>
                </div>

                <div>
                  <Label>Graph</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {getGraphName(importData.graph_id)}
                  </div>
                </div>

                <div>
                  <Label>Status</Label>
                  <Badge color={getStatusColor(importData.status)} className="mt-1">
                    {importData.status}
                  </Badge>
                </div>

                <div>
                  <Label>Progress</Label>
                  <Progress
                    progress={importData.progress}
                    color={importData.status === 'failed' ? 'red' : 'blue'}
                    className="mt-1"
                  />
                  <div className="text-sm text-gray-500 mt-1">
                    {importData.progress}% complete
                  </div>
                </div>

                <div>
                  <Label>File</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {importData.file_name}
                  </div>
                  <div className="text-sm text-gray-500">
                    {formatFileSize(importData.file_size)}
                  </div>
                </div>

                <div>
                  <Label>Created</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatDate(importData.created_time)}
                  </div>
                </div>

                {importData.started_time && (
                  <div>
                    <Label>Started</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(importData.started_time)}
                    </div>
                  </div>
                )}

                {importData.completed_time && (
                  <div>
                    <Label>Completed</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(importData.completed_time)}
                    </div>
                  </div>
                )}

                {importData.error_message && (
                  <div>
                    <Label>Error</Label>
                    <div className="text-sm text-red-600 dark:text-red-400">
                      {importData.error_message}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};

export default DataImportDetail;
