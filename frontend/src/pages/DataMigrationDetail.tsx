import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Button,
  Card,
  Label,
  Select,
  Badge,
  Progress,
  Alert,
  Spinner,
  Breadcrumb,
  BreadcrumbItem,
  TextInput,
  Textarea,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiSwitchHorizontal,
  HiPlay,
  HiStop,
  HiTrash,
  HiHome,
  HiExclamationCircle
} from 'react-icons/hi';
import { mockDataMigrations, type DataMigration } from '../mock/data';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import DataIcon from '../components/icons/DataIcon';

const DataMigrationDetail: React.FC = () => {
  const navigate = useNavigate();
  const { migrationId } = useParams<{ migrationId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = migrationId === 'new';
  
  const [migrationData, setMigrationData] = useState<DataMigration | null>(null);
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
    source_space_id: '',
    source_graph_id: 0,
    target_space_id: '',
    target_graph_id: 0,
    migration_type: 'copy' as 'copy' | 'move' | 'sync'
  });

  // Get URL parameters for prepopulation
  const urlSourceSpaceId = searchParams.get('sourceSpaceId');
  const urlSourceGraphId = searchParams.get('sourceGraphId');
  const urlTargetSpaceId = searchParams.get('targetSpaceId');
  const urlTargetGraphId = searchParams.get('targetGraphId');

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      // Simulate API calls
      await new Promise(resolve => setTimeout(resolve, 300));
      
      setSpaces(mockSpaces);
      setGraphs(mockGraphs);
      
      if (!isNew && migrationId) {
        const existingMigration = mockDataMigrations.find(mig => mig.id === parseInt(migrationId));
        if (existingMigration) {
          setMigrationData(existingMigration);
          setFormData({
            name: existingMigration.name,
            description: existingMigration.description,
            source_space_id: existingMigration.source_space_id,
            source_graph_id: existingMigration.source_graph_id,
            target_space_id: existingMigration.target_space_id,
            target_graph_id: existingMigration.target_graph_id,
            migration_type: existingMigration.migration_type
          });
        } else {
          setError('Migration not found');
        }
      } else {
        // New migration - initialize form with URL parameters if available
        const sourceGraphIdNum = urlSourceGraphId ? parseInt(urlSourceGraphId, 10) : 0;
        const targetGraphIdNum = urlTargetGraphId ? parseInt(urlTargetGraphId, 10) : 0;
        setFormData({
          name: '',
          description: '',
          source_space_id: urlSourceSpaceId || '',
          source_graph_id: sourceGraphIdNum,
          target_space_id: urlTargetSpaceId || '',
          target_graph_id: targetGraphIdNum,
          migration_type: 'copy'
        });
      }
      
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to load data. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, [migrationId, isNew, urlSourceSpaceId, urlSourceGraphId, urlTargetSpaceId, urlTargetGraphId]);

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

  const handleSave = async () => {
    if (!formData.name.trim()) {
      setError('Name is required');
      return;
    }
    
    if (!formData.source_space_id) {
      setError('Source space is required');
      return;
    }
    
    if (!formData.source_graph_id) {
      setError('Source graph is required');
      return;
    }

    if (!formData.target_space_id) {
      setError('Target space is required');
      return;
    }
    
    if (!formData.target_graph_id) {
      setError('Target graph is required');
      return;
    }

    if (formData.source_space_id === formData.target_space_id && 
        formData.source_graph_id === formData.target_graph_id) {
      setError('Source and target cannot be the same');
      return;
    }

    try {
      setSaving(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      if (isNew) {
        // Create new migration
        console.log('Creating new migration:', formData);
      } else {
        // Update existing migration
        console.log('Updating migration:', migrationData?.id, formData);
      }
      
      navigate('/data/migrate');
    } catch (err) {
      console.error('Error saving migration:', err);
      setError('Failed to save migration. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async () => {
    if (!migrationData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setMigrationData(prev => prev ? {
        ...prev,
        status: 'processing',
        started_time: new Date().toISOString(),
        progress: 10
      } : null);
    } catch (err) {
      console.error('Error starting migration:', err);
      setError('Failed to start migration. Please try again.');
    }
  };

  const handleCancel = async () => {
    if (!migrationData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setMigrationData(prev => prev ? {
        ...prev,
        status: 'canceled',
        completed_time: new Date().toISOString()
      } : null);
    } catch (err) {
      console.error('Error canceling migration:', err);
      setError('Failed to cancel migration. Please try again.');
    }
  };

  const handleDelete = async () => {
    if (!migrationData) return;
    
    try {
      setDeleting(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      navigate('/data/migrate');
    } catch (err) {
      console.error('Error deleting migration:', err);
      setError('Failed to delete migration. Please try again.');
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
        <BreadcrumbItem href="/data/migrate">
          Migrate
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isNew ? 'New Migration' : migrationData?.name || 'Migration Details'}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <HiSwitchHorizontal className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Migration' : 'Data Migration Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Configure a new data migration between spaces and graphs' : 'Manage your data migration'}
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
                  <Label htmlFor="name">Migration Name</Label>
                  <TextInput
                    id="name"
                    value={formData.name}
                    onChange={(e) => handleInputChange('name', e.target.value)}
                    placeholder="Enter migration name"
                    disabled={!isNew && migrationData?.status === 'processing'}
                  />
                </div>

                <div>
                  <Label htmlFor="migration_type">Migration Type</Label>
                  <Select
                    id="migration_type"
                    value={formData.migration_type}
                    onChange={(e) => handleInputChange('migration_type', e.target.value)}
                    disabled={!isNew && migrationData?.status === 'processing'}
                  >
                    <option value="copy">Copy (duplicate data)</option>
                    <option value="move">Move (transfer data)</option>
                    <option value="sync">Sync (synchronize data)</option>
                  </Select>
                </div>
              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  placeholder="Optional description of the migration"
                  rows={3}
                  disabled={!isNew && migrationData?.status === 'processing'}
                />
              </div>

              {/* Source Section */}
              <div className="border-t pt-4">
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Source</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="source_space">Source Space</Label>
                    <Select
                      id="source_space"
                      value={formData.source_space_id}
                      onChange={(e) => handleInputChange('source_space_id', e.target.value)}
                      disabled={!isNew && migrationData?.status === 'processing'}
                    >
                      <option value="">Select source space</option>
                      {spaces.map((space) => (
                        <option key={space.space} value={space.space}>
                          {space.space_name}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="source_graph">Source Graph</Label>
                    <Select
                      id="source_graph"
                      value={formData.source_graph_id}
                      onChange={(e) => handleInputChange('source_graph_id', parseInt(e.target.value))}
                      disabled={!formData.source_space_id || (!isNew && migrationData?.status === 'processing')}
                    >
                      <option value={0}>Select source graph</option>
                      {graphs
                        .filter(graph => graph.space_id === formData.source_space_id)
                        .map((graph) => (
                          <option key={graph.id} value={graph.id}>
                            {graph.graph_name}
                          </option>
                        ))}
                    </Select>
                  </div>
                </div>
              </div>

              {/* Target Section */}
              <div className="border-t pt-4">
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Target</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="target_space">Target Space</Label>
                    <Select
                      id="target_space"
                      value={formData.target_space_id}
                      onChange={(e) => handleInputChange('target_space_id', e.target.value)}
                      disabled={!isNew && migrationData?.status === 'processing'}
                    >
                      <option value="">Select target space</option>
                      {spaces.map((space) => (
                        <option key={space.space} value={space.space}>
                          {space.space_name}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="target_graph">Target Graph</Label>
                    <Select
                      id="target_graph"
                      value={formData.target_graph_id}
                      onChange={(e) => handleInputChange('target_graph_id', parseInt(e.target.value))}
                      disabled={!formData.target_space_id || (!isNew && migrationData?.status === 'processing')}
                    >
                      <option value={0}>Select target graph</option>
                      {graphs
                        .filter(graph => graph.space_id === formData.target_space_id)
                        .map((graph) => (
                          <option key={graph.id} value={graph.id}>
                            {graph.graph_name}
                          </option>
                        ))}
                    </Select>
                  </div>
                </div>
              </div>

              <div className="flex gap-2 pt-4">
                <Button
                  color="gray"
                  onClick={() => navigate('/data/migrate')}
                >
                  <HiArrowLeft className="w-4 h-4 mr-2" />
                  Back to Migrations
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
                      <HiSwitchHorizontal className="w-4 h-4 mr-2" />
                    )}
                    {saving ? 'Creating...' : 'Create Migration'}
                  </Button>
                ) : (
                  <>
                    <Button
                      color="blue"
                      onClick={handleSave}
                      disabled={saving || migrationData?.status === 'processing'}
                    >
                      {saving ? (
                        <Spinner size="sm" className="mr-2" />
                      ) : (
                        <HiSwitchHorizontal className="w-4 h-4 mr-2" />
                      )}
                      {saving ? 'Saving...' : 'Save Changes'}
                    </Button>
                    
                    {migrationData?.status === 'pending' && (
                      <Button
                        color="green"
                        onClick={handleStart}
                      >
                        <HiPlay className="w-4 h-4 mr-2" />
                        Start Migration
                      </Button>
                    )}
                    
                    {migrationData?.status === 'processing' && (
                      <Button
                        color="red"
                        onClick={handleCancel}
                      >
                        <HiStop className="w-4 h-4 mr-2" />
                        Cancel Migration
                      </Button>
                    )}
                    
                    {migrationData && ['completed', 'failed', 'canceled'].includes(migrationData.status) && (
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
        {!isNew && migrationData && (
          <div className="lg:col-span-1">
            <Card>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Migration Status
              </h3>
              
              <div className="space-y-4">
                <div>
                  <Label>Source</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    <div className="font-medium">{getSpaceName(migrationData.source_space_id)}</div>
                    <div className="text-gray-500">{getGraphName(migrationData.source_graph_id)}</div>
                  </div>
                </div>

                <div>
                  <Label>Target</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    <div className="font-medium">{getSpaceName(migrationData.target_space_id)}</div>
                    <div className="text-gray-500">{getGraphName(migrationData.target_graph_id)}</div>
                  </div>
                </div>

                <div>
                  <Label>Type</Label>
                  <Badge color="gray" className="mt-1">
                    {migrationData.migration_type}
                  </Badge>
                </div>

                <div>
                  <Label>Status</Label>
                  <Badge color={getStatusColor(migrationData.status)} className="mt-1">
                    {migrationData.status}
                  </Badge>
                </div>

                <div>
                  <Label>Progress</Label>
                  <Progress
                    progress={migrationData.progress}
                    color={migrationData.status === 'failed' ? 'red' : 'blue'}
                    className="mt-1"
                  />
                  <div className="text-sm text-gray-500 mt-1">
                    {migrationData.progress}% complete
                  </div>
                </div>

                <div>
                  <Label>Triples</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {migrationData.triples_migrated ? migrationData.triples_migrated.toLocaleString() : '0'} / {migrationData.total_triples ? migrationData.total_triples.toLocaleString() : '0'}
                  </div>
                </div>

                <div>
                  <Label>Created</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatDate(migrationData.created_time)}
                  </div>
                </div>

                {migrationData.started_time && (
                  <div>
                    <Label>Started</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(migrationData.started_time)}
                    </div>
                  </div>
                )}

                {migrationData.completed_time && (
                  <div>
                    <Label>Completed</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(migrationData.completed_time)}
                    </div>
                  </div>
                )}

                {migrationData.error_message && (
                  <div>
                    <Label>Error</Label>
                    <div className="text-sm text-red-600 dark:text-red-400">
                      {migrationData.error_message}
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
            Are you sure you want to delete this migration? This action cannot be undone.
          </p>
          {migrationData && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <p className="font-medium text-gray-900 dark:text-white">
                {migrationData.name}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Status: {migrationData.status}
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
                Delete Migration
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

export default DataMigrationDetail;
