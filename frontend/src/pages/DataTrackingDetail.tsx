import React, { useState, useEffect, useCallback } from 'react';
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
  Progress,
  Table,
  TableHead,
  TableRow,
  TableHeadCell,
  TableBody,
  TableCell,
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
  HiHome,
  HiChartBar,
  HiExclamationCircle
} from 'react-icons/hi';
import { mockDataTrackings, type DataTracking } from '../mock/data';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import DataIcon from '../components/icons/DataIcon';

const DataTrackingDetail: React.FC = () => {
  const navigate = useNavigate();
  const { trackingId } = useParams<{ trackingId: string }>();
  const [searchParams] = useSearchParams();
  const isNew = trackingId === 'new';
  
  const [trackingData, setTrackingData] = useState<DataTracking | null>(null);
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
    external_system: '',
    parallel_slices: 4
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
      
      if (!isNew && trackingId) {
        const existingTracking = mockDataTrackings.find(track => track.id === parseInt(trackingId));
        if (existingTracking) {
          setTrackingData(existingTracking);
          setFormData({
            name: existingTracking.name,
            description: existingTracking.description,
            space_id: existingTracking.space_id,
            graph_id: existingTracking.graph_id,
            external_system: existingTracking.external_system || '',
            parallel_slices: existingTracking.parallel_slices
          });
        } else {
          setError('Tracking not found');
        }
      } else {
        // New tracking - initialize form with URL parameters if available
        const graphIdNum = urlGraphId ? parseInt(urlGraphId, 10) : 0;
        setFormData({
          name: '',
          description: '',
          space_id: urlSpaceId || '',
          graph_id: graphIdNum,
          external_system: '',
          parallel_slices: 4
        });
      }
      
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to load data. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, [trackingId, isNew, urlSpaceId, urlGraphId]);

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
      case 'paused': return 'gray';
      default: return 'gray';
    }
  };

  const getRangeStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'success';
      case 'processing': return 'info';
      case 'pending': return 'warning';
      case 'failed': return 'failure';
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

    if (formData.parallel_slices < 1 || formData.parallel_slices > 1000) {
      setError('Parallel slices must be between 1 and 1000');
      return;
    }

    try {
      setSaving(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      if (isNew) {
        // Create new tracking
        console.log('Creating new tracking:', formData);
      } else {
        // Update existing tracking
        console.log('Updating tracking:', trackingData?.id, formData);
      }
      
      navigate('/data/tracking');
    } catch (err) {
      console.error('Error saving tracking:', err);
      setError('Failed to save tracking. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async () => {
    if (!trackingData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setTrackingData(prev => prev ? {
        ...prev,
        status: 'processing',
        started_time: new Date().toISOString(),
        overall_progress: 5,
        last_updated: new Date().toISOString()
      } : null);
    } catch (err) {
      console.error('Error starting tracking:', err);
      setError('Failed to start tracking. Please try again.');
    }
  };

  const handlePause = async () => {
    if (!trackingData) return;
    
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setTrackingData(prev => prev ? {
        ...prev,
        status: 'paused',
        last_updated: new Date().toISOString()
      } : null);
    } catch (err) {
      console.error('Error pausing tracking:', err);
      setError('Failed to pause tracking. Please try again.');
    }
  };

  const handleDelete = async () => {
    if (!trackingData) return;
    
    try {
      setDeleting(true);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      
      navigate('/data/track');
    } catch (err) {
      console.error('Error deleting tracking:', err);
      setError('Failed to delete tracking. Please try again.');
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
        <BreadcrumbItem href="/data/tracking">
          Tracking
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isNew ? 'New Tracking' : trackingData?.name || 'Tracking Details'}
        </BreadcrumbItem>
      </Breadcrumb>

      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <HiChartBar className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Data Tracking' : 'Data Tracking Details'}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          {isNew ? 'Configure a new data tracking operation with parallel processing ranges' : 'Manage your data tracking operation'}
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
                  <Label htmlFor="name">Tracking Name</Label>
                  <TextInput
                    id="name"
                    value={formData.name}
                    onChange={(e) => handleInputChange('name', e.target.value)}
                    placeholder="Enter tracking name"
                    disabled={!isNew && trackingData?.status === 'processing'}
                  />
                </div>

              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => handleInputChange('description', e.target.value)}
                  placeholder="Optional description of the tracking operation"
                  rows={3}
                  disabled={!isNew && trackingData?.status === 'processing'}
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="space">Space</Label>
                  <Select
                    id="space"
                    value={formData.space_id}
                    onChange={(e) => handleInputChange('space_id', e.target.value)}
                    disabled={!isNew && trackingData?.status === 'processing'}
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
                    disabled={!formData.space_id || (!isNew && trackingData?.status === 'processing')}
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

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="external_system">External System</Label>
                  <TextInput
                    id="external_system"
                    value={formData.external_system}
                    onChange={(e) => handleInputChange('external_system', e.target.value)}
                    placeholder="e.g., Salesforce, AWS S3, ML Pipeline"
                    disabled={!isNew && trackingData?.status === 'processing'}
                  />
                </div>

                <div>
                  <Label htmlFor="parallel_slices">Parallel Slices</Label>
                  <TextInput
                    id="parallel_slices"
                    type="number"
                    min="1"
                    max="1000"
                    value={formData.parallel_slices}
                    onChange={(e) => handleInputChange('parallel_slices', parseInt(e.target.value) || 1)}
                    placeholder="Enter number of parallel slices"
                    disabled={!isNew && trackingData?.status === 'processing'}
                  />
                  <div className="text-xs text-gray-500 mt-1">
                    Number of parallel processing ranges (1-1000)
                  </div>
                </div>
              </div>

              <div className="flex gap-2 pt-4">
                <Button
                  color="gray"
                  onClick={() => navigate('/data/tracking')}
                >
                  <HiArrowLeft className="w-4 h-4 mr-2" />
                  Back to Tracking
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
                      <HiChartBar className="w-4 h-4 mr-2" />
                    )}
                    {saving ? 'Creating...' : 'Create Tracking'}
                  </Button>
                ) : (
                  <>
                    <Button
                      color="blue"
                      onClick={handleSave}
                      disabled={saving || trackingData?.status === 'processing'}
                    >
                      {saving ? (
                        <Spinner size="sm" className="mr-2" />
                      ) : (
                        <HiChartBar className="w-4 h-4 mr-2" />
                      )}
                      {saving ? 'Saving...' : 'Save Changes'}
                    </Button>
                    
                    {trackingData?.status === 'pending' && (
                      <Button
                        color="green"
                        onClick={handleStart}
                      >
                        <HiPlay className="w-4 h-4 mr-2" />
                        Start Tracking
                      </Button>
                    )}
                    
                    {trackingData?.status === 'processing' && (
                      <Button
                        color="yellow"
                        onClick={handlePause}
                      >
                        <HiStop className="w-4 h-4 mr-2" />
                        Pause Tracking
                      </Button>
                    )}
                    
                    {trackingData && trackingData.status !== 'processing' && (
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

          {/* Range Details */}
          {!isNew && trackingData && trackingData.ranges.length > 0 && (
            <Card className="mt-6">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Processing Ranges
              </h3>
              
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>Range</TableHeadCell>
                      <TableHeadCell>Hash Range</TableHeadCell>
                      <TableHeadCell>Status</TableHeadCell>
                      <TableHeadCell>Progress</TableHeadCell>
                      <TableHeadCell>Records</TableHeadCell>
                      <TableHeadCell>Current Cursor</TableHeadCell>
                      <TableHeadCell>Duration</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {trackingData.ranges.map((range) => (
                      <TableRow key={range.range_id}>
                        <TableCell className="font-medium">
                          Range {range.range_id}
                        </TableCell>
                        <TableCell>
                          <div className="text-sm font-mono">
                            {range.hash_prefix_start}..{range.hash_prefix_end}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge color={getRangeStatusColor(range.status)}>
                            {range.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="w-20">
                            <Progress
                              progress={(range.records_processed / range.total_records) * 100}
                              color={range.status === 'failed' ? 'red' : 'blue'}
                              size="sm"
                            />
                            <div className="text-xs text-gray-500 mt-1">
                              {Math.round((range.records_processed / range.total_records) * 100)}%
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {range.records_processed.toLocaleString()} / {range.total_records.toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <div className="text-sm font-mono">
                            {range.current_cursor}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {range.started_time && (
                            <div>
                              <div>Started: {formatDate(range.started_time)}</div>
                              {range.completed_time && (
                                <div>Completed: {formatDate(range.completed_time)}</div>
                              )}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}
        </div>

        {/* Status Panel */}
        {!isNew && trackingData && (
          <div className="lg:col-span-1">
            <Card>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Tracking Status
              </h3>
              
              <div className="space-y-4">
                <div>
                  <Label>Space/Graph</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    <div className="font-medium">{getSpaceName(trackingData.space_id)}</div>
                    <div className="text-gray-500">{getGraphName(trackingData.graph_id)}</div>
                  </div>
                </div>


                {trackingData.external_system && (
                  <div>
                    <Label>External System</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {trackingData.external_system}
                    </div>
                  </div>
                )}

                <div>
                  <Label>Status</Label>
                  <Badge color={getStatusColor(trackingData.status)} className="mt-1">
                    {trackingData.status}
                  </Badge>
                </div>

                <div>
                  <Label>Overall Progress</Label>
                  <Progress
                    progress={trackingData.overall_progress}
                    color={trackingData.status === 'failed' ? 'red' : 'blue'}
                    className="mt-1"
                  />
                  <div className="text-sm text-gray-500 mt-1">
                    {trackingData.overall_progress}% complete
                  </div>
                </div>

                <div>
                  <Label>Parallel Slices</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {trackingData.parallel_slices} slices
                  </div>
                </div>

                <div>
                  <Label>Records</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {trackingData.records_processed.toLocaleString()} / {trackingData.total_records.toLocaleString()}
                  </div>
                </div>

                <div>
                  <Label>Created</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatDate(trackingData.created_time)}
                  </div>
                </div>

                {trackingData.started_time && (
                  <div>
                    <Label>Started</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(trackingData.started_time)}
                    </div>
                  </div>
                )}

                {trackingData.completed_time && (
                  <div>
                    <Label>Completed</Label>
                    <div className="text-sm text-gray-900 dark:text-white">
                      {formatDate(trackingData.completed_time)}
                    </div>
                  </div>
                )}

                <div>
                  <Label>Last Updated</Label>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatDate(trackingData.last_updated)}
                  </div>
                </div>

                {trackingData.error_message && (
                  <div>
                    <Label>Error</Label>
                    <div className="text-sm text-red-600 dark:text-red-400">
                      {trackingData.error_message}
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
            Are you sure you want to delete this tracking? This action cannot be undone.
          </p>
          {trackingData && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <p className="font-medium text-gray-900 dark:text-white">
                {trackingData.name}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Status: {trackingData.status}
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
                Delete Tracking
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

export default DataTrackingDetail;
