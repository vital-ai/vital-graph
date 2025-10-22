import React, { useState, useCallback, useEffect } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Card,
  Button,
  TextInput,
  Textarea,
  Select,
  Label,
  Alert,
  Spinner,
  Badge,
  Breadcrumb,
  BreadcrumbItem,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiSave,
  HiClock,
  HiFingerPrint,
  HiTrash,
  HiHome,
  HiExclamationCircle
} from 'react-icons/hi';
import { mockDataCheckpoints, DataCheckpoint } from '../mock/data';
import { mockSpaces, Space } from '../mock/spaces';
import { mockGraphs, Graph } from '../mock/graphs';
import DataIcon from '../components/icons/DataIcon';

const DataCheckpointDetail: React.FC = () => {
  const navigate = useNavigate();
  const { checkpointId } = useParams<{ checkpointId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = checkpointId === 'new';

  // State
  const [checkpointData, setCheckpointData] = useState<DataCheckpoint | null>(null);
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
    external_system: ''
  });

  // Get URL parameters for prepopulation
  const urlSpaceId = searchParams.get('spaceId');
  const urlGraphId = searchParams.get('graphId');

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      // Simulate API calls
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setSpaces(mockSpaces);
      setGraphs(mockGraphs);
      
      if (!isNew && checkpointId) {
        const existingCheckpoint = mockDataCheckpoints.find(checkpoint => checkpoint.id === parseInt(checkpointId));
        if (existingCheckpoint) {
          setCheckpointData(existingCheckpoint);
          setFormData({
            name: existingCheckpoint.name,
            description: existingCheckpoint.description,
            space_id: existingCheckpoint.space_id,
            graph_id: existingCheckpoint.graph_id,
            external_system: existingCheckpoint.external_system || ''
          });
        } else {
          setError('Checkpoint not found');
        }
      } else {
        // New checkpoint - initialize form with URL parameters if available
        const graphIdNum = urlGraphId ? parseInt(urlGraphId, 10) : 0;
        setFormData({
          name: '',
          description: '',
          space_id: urlSpaceId || '',
          graph_id: graphIdNum,
          external_system: ''
        });
      }
      
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to load data. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, [checkpointId, isNew, urlSpaceId, urlGraphId]);

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

  const getFilteredGraphs = () => {
    if (!formData.space_id) return [];
    return graphs.filter(g => g.space_id === formData.space_id);
  };

  // Form handlers
  const handleInputChange = (field: string, value: string | number) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleSpaceChange = (spaceId: string) => {
    setFormData(prev => ({
      ...prev,
      space_id: spaceId,
      graph_id: 0 // Reset graph selection when space changes
    }));
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      
      // Validate required fields
      if (!formData.name.trim()) {
        setError('Checkpoint name is required');
        return;
      }
      
      if (!formData.space_id) {
        setError('Space selection is required');
        return;
      }
      
      if (!formData.graph_id) {
        setError('Graph selection is required');
        return;
      }

      
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Navigate back to data page
      navigate('/data/checkpoint');
    } catch (err) {
      console.error('Error saving checkpoint:', err);
      setError('Failed to save checkpoint. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!checkpointData) return;
    
    try {
      setDeleting(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      navigate('/data/checkpoint');
    } catch (err) {
      console.error('Error deleting checkpoint:', err);
      setError('Failed to delete checkpoint. Please try again.');
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
          {isNew ? 'New Checkpoint' : checkpointData?.name || 'Checkpoint Details'}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Checkpoint' : 'Data Checkpoint Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Configure a new data checkpoint' : 'Manage your data checkpoint'}
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
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                  Checkpoint Information
                </h3>
              </div>

              <div>
                <Label htmlFor="name">Checkpoint Name</Label>
                <TextInput
                  id="name"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  placeholder="Enter checkpoint name"
                  disabled={!isNew && checkpointData?.checkpoint_timestamp !== undefined}
                />
              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  placeholder="Optional description of the checkpoint"
                  rows={3}
                  disabled={!isNew && checkpointData?.checkpoint_timestamp !== undefined}
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="space_id">Space</Label>
                  <Select
                    id="space_id"
                    value={formData.space_id}
                    onChange={(e) => handleSpaceChange(e.target.value)}
                    disabled={!isNew && checkpointData?.checkpoint_timestamp !== undefined}
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
                  <Label htmlFor="graph_id">Graph</Label>
                  <Select
                    id="graph_id"
                    value={formData.graph_id}
                    onChange={(e) => handleInputChange('graph_id', parseInt(e.target.value))}
                    disabled={!formData.space_id || (!isNew && checkpointData?.checkpoint_timestamp !== undefined)}
                  >
                    <option value={0}>Select a graph</option>
                    {getFilteredGraphs().map((graph) => (
                      <option key={graph.id} value={graph.id}>
                        {graph.graph_name}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>

              <div>
                <Label htmlFor="external_system">External System (Optional)</Label>
                <TextInput
                  id="external_system"
                  value={formData.external_system}
                  onChange={(e) => handleInputChange('external_system', e.target.value)}
                  placeholder="e.g., Backup Service, CRM System"
                  disabled={!isNew && checkpointData?.checkpoint_timestamp !== undefined}
                />
              </div>
            </div>

            
            {/* Action Buttons */}
            <div className="flex flex-wrap gap-2 pt-4">
              <Button
                color="gray"
                onClick={() => navigate('/data/checkpoint')}
              >
                <HiArrowLeft className="w-4 h-4 mr-2" />
                Back to Data Checkpoints
              </Button>
              
              {!checkpointData ? (
                <Button
                  color="blue"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? (
                    <Spinner size="sm" className="mr-2" />
                  ) : (
                    <HiSave className="w-4 h-4 mr-2" />
                  )}
                  {saving ? 'Creating...' : 'Create Checkpoint'}
                </Button>
              ) : (
                <>
                  <Button
                    color="blue"
                    onClick={handleSave}
                    disabled={saving || checkpointData?.checkpoint_timestamp !== undefined}
                  >
                    {saving ? (
                      <Spinner size="sm" className="mr-2" />
                    ) : (
                      <HiSave className="w-4 h-4 mr-2" />
                    )}
                    {saving ? 'Saving...' : 'Save Changes'}
                  </Button>
                  
                  <Button
                    color="red"
                    onClick={() => setShowDeleteModal(true)}
                  >
                    <HiTrash className="w-4 h-4 mr-2" />
                    Delete
                  </Button>
                </>
              )}
            </div>
          </Card>
        </div>

        {/* Status Panel */}
        <div className="lg:col-span-1">
          <Card>
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Checkpoint Status
              </h3>
            </div>
              
            <div className="space-y-4">
              {!isNew && checkpointData ? (
                <>
                  <div>
                    <Label>Space/Graph</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      <div className="font-medium">{getSpaceName(checkpointData.space_id)}</div>
                      <div className="text-gray-500">{getGraphName(checkpointData.graph_id)}</div>
                    </div>
                  </div>

                  {checkpointData.external_system && (
                    <div>
                      <Label>External System</Label>
                      <div className="text-sm text-gray-900 dark:text-white">
                        {checkpointData.external_system}
                      </div>
                    </div>
                  )}

                  <div>
                    <Label>Status</Label>
                    <Badge color={checkpointData.checkpoint_timestamp ? 'green' : 'yellow'} className="mt-1">
                      {checkpointData.checkpoint_timestamp ? 'Completed' : 'Pending'}
                    </Badge>
                  </div>

                  {checkpointData.checkpoint_timestamp && (
                    <div>
                      <Label>Checkpoint Timestamp</Label>
                      <div className="flex items-center space-x-2 mt-1">
                        <HiClock className="w-4 h-4 text-gray-500" />
                        <span className="text-sm text-gray-900 dark:text-white">
                          {new Date(checkpointData.checkpoint_timestamp).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  )}

                  {checkpointData.checkpoint_hash && (
                    <div>
                      <Label>Checkpoint Hash</Label>
                      <div className="flex items-center space-x-2 mt-1">
                        <HiFingerPrint className="w-4 h-4 text-gray-500" />
                        <span className="text-xs font-mono text-gray-600 dark:text-gray-400 break-all">
                          {checkpointData.checkpoint_hash}
                        </span>
                      </div>
                    </div>
                  )}

                  <div>
                    <Label>Created</Label>
                    <div className="text-sm text-gray-500">
                      {new Date(checkpointData.created_time).toLocaleString()}
                      {checkpointData.created_by && (
                        <div className="text-xs">by {checkpointData.created_by}</div>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <HiClock className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                  <p>Checkpoint will be created when you save</p>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)} size="md">
        <ModalHeader>
          <HiExclamationCircle className="mr-2 h-6 w-6 text-red-600" />
          Confirm Deletion
        </ModalHeader>
        <ModalBody>
          <p className="text-gray-500 dark:text-gray-400">
            Are you sure you want to delete this checkpoint? This action cannot be undone.
          </p>
          {checkpointData && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <p className="font-medium text-gray-900 dark:text-white">
                {checkpointData.name}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Status: {checkpointData.checkpoint_timestamp ? 'Completed' : 'Pending'}
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
                Delete Checkpoint
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

export default DataCheckpointDetail;
