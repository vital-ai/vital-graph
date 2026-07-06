import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { type SpaceInfo } from '../types/api';
import { 
  Alert, 
  Button, 
  Card, 
  Label, 
  TextInput, 
  Textarea, 
  Spinner,
  Breadcrumb,
  BreadcrumbItem,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter
} from 'flowbite-react';
import { 
  HiPencil, 
  HiSave, 
  HiX, 
  HiHome, 
  HiViewBoards,
  HiTrash,
  HiExclamationCircle,
  HiChartBar,
  HiCog
} from 'react-icons/hi';
import SpaceOverview from '../components/SpaceOverview';
const SpaceAnalytics = React.lazy(() => import('../components/SpaceAnalytics'));
const SpaceMetrics = React.lazy(() => import('../components/SpaceMetrics'));

type Space = SpaceInfo;

interface BannerMessage {
  type: 'success' | 'error';
  message: string;
}

const SpaceDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  
  // Check if this is creation mode
  const isCreating = id === 'new';
  
  const [space, setSpace] = useState<Space | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState<boolean>(isCreating); // Start in edit mode for creation
  const [saving, setSaving] = useState<boolean>(false);
  const [bannerMessage, setBannerMessage] = useState<BannerMessage | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [deleting, setDeleting] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'settings' | 'analytics' | 'metrics'>('overview');
  
  // Form state for editing
  const [editForm, setEditForm] = useState({
    space: '',
    space_name: '',
    space_description: ''
  });

  // Track if form has changes
  const [hasChanges, setHasChanges] = useState<boolean>(false);

  // Fetch space details or initialize for creation
  useEffect(() => {
    const fetchSpace = async () => {
      if (!id) {
        setError('Space ID is required');
        setLoading(false);
        return;
      }

      // If creating new space, initialize with empty form
      if (isCreating) {
        setEditForm({
          space: '',
          space_name: '',
          space_description: ''
        });
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const responseData = await apiService.getSpaceInfo(id);
        const spaceData = responseData.space || responseData;
        setSpace(spaceData);
        
        // Initialize edit form with current values
        setEditForm({
          space: spaceData.space || '',
          space_name: spaceData.space_name || '',
          space_description: spaceData.space_description || ''
        });
        
        setError(null);
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load space details';
        
        setError(errorMessage);
        setSpace(null);
      } finally {
        setLoading(false);
      }
    };

    fetchSpace();
  }, [id, isCreating]);

  // Check for changes when form values change
  useEffect(() => {
    if (isCreating) {
      // For creation mode, check if any required fields are filled
      const hasRequiredFields = editForm.space.trim() !== '' && editForm.space_name.trim() !== '';
      setHasChanges(hasRequiredFields);
    } else {
      if (!space) return;
      
      const hasFormChanges = 
        editForm.space !== (space.space || '') ||
        editForm.space_name !== (space.space_name || '') ||
        editForm.space_description !== (space.space_description || '');
      
      setHasChanges(hasFormChanges);
    }
  }, [editForm, space, isCreating]);

  // Show banner message with auto-dismiss
  const showBanner = (type: 'success' | 'error', message: string) => {
    setBannerMessage({ type, message });
    setTimeout(() => {
      setBannerMessage(null);
    }, 5000); // Dismiss after 5 seconds
  };

  const handleEdit = () => {
    setIsEditing(true);
  };

  const handleCancel = () => {
    if (isCreating) {
      // For creation mode, navigate back to spaces list
      navigate('/spaces');
      return;
    }
    
    if (!space) return;
    
    // Reset form to original values
    setEditForm({
      space: space.space || '',
      space_name: space.space_name || '',
      space_description: space.space_description || ''
    });
    
    setIsEditing(false);
    setHasChanges(false);
  };

  const handleSave = async () => {
    if (!hasChanges) return;

    try {
      setSaving(true);
      
      if (isCreating) {
        // Create new space
        const createData = {
          ...editForm
        };

        const responseData = await apiService.createSpace(createData);
        // SpaceCreateResponse has space field
        const createdSpace = responseData.space || responseData;
        
        showBanner('success', 'Space created successfully!');
        
        // Navigate to the created space's detail page using the space identifier
        navigate(`/space/${createdSpace.space || editForm.space}`);
      } else {
        // Update existing space
        if (!space) return;
        
        const updateData = {
          ...editForm
        };

        const updatedSpace = await apiService.updateSpace(space.space, updateData);
        
        setSpace(updatedSpace);
        setIsEditing(false);
        setHasChanges(false);
        
        showBanner('success', 'Space updated successfully!');
      }
    } catch (err: unknown) {
      const action = isCreating ? 'create' : 'update';
      showBanner('error', err instanceof Error ? err.message : `Failed to ${action} space`);
    } finally {
      setSaving(false);
    }
  };

  const handleInputChange = (field: keyof typeof editForm, value: string) => {
    setEditForm(prev => ({ ...prev, [field]: value }));
  };

  const handleDelete = () => {
    setShowDeleteModal(true);
  };

  const handleDeleteConfirm = async () => {
    if (!space) return;
    
    try {
      setDeleting(true);
      await apiService.deleteSpace(space.space);
      
      // Show success message and navigate back to spaces list
      showBanner('success', 'Space deleted successfully');
      setTimeout(() => {
        navigate('/spaces');
      }, 1000);
    } catch (err: unknown) {
      showBanner('error', err instanceof Error ? err.message : 'Failed to delete space');
    } finally {
      setDeleting(false);
      setShowDeleteModal(false);
    }
  };

  const handleDeleteCancel = () => {
    setShowDeleteModal(false);
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-40">
        <Spinner size="xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <Alert color="failure" className="mb-6">
          <span className="font-medium">Error:</span> {error}
        </Alert>
        <Button onClick={() => navigate('/spaces')} color="gray">
          Back to Spaces
        </Button>
      </div>
    );
  }

  if (!space && !isCreating) {
    return (
      <div>
        <Alert color="warning" className="mb-6">
          Space not found
        </Alert>
        <Button onClick={() => navigate('/spaces')} color="gray">
          Back to Spaces
        </Button>
      </div>
    );
  }

  return (
    <div data-testid="space-detail-page">
      {/* Banner Message Area */}
      <div className="mb-4 min-h-[60px]">
        {bannerMessage && (
          <Alert 
            color={bannerMessage.type === 'success' ? 'success' : 'failure'}
            className="mb-4"
            onDismiss={() => setBannerMessage(null)}
          >
            <span className="font-medium">
              {bannerMessage.type === 'success' ? 'Success:' : 'Error:'}
            </span>{' '}
            {bannerMessage.message}
          </Alert>
        )}
      </div>

      {/* Breadcrumbs */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        <BreadcrumbItem href="/spaces" icon={HiViewBoards}>
          Spaces
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isCreating ? 'New Space' : (space?.space_name || space?.space || 'Space')}
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-4">
          <HiViewBoards className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Space Details
          </h1>
        </div>
        <div className="flex justify-between items-start">
          <div>
            <p className="text-gray-500 dark:text-gray-400">
              {isEditing ? 'Modify space information' : 'View space information and settings'}
            </p>
          </div>
          
          {/* Action Buttons */}
          <div className="flex flex-col sm:flex-row gap-2">
            {isEditing ? (
              <>
                <Button 
                  onClick={handleSave} 
                  color="blue" 
                  disabled={saving || !hasChanges}
                >
                  {saving ? (
                    <>
                      <Spinner size="sm" className="mr-2" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <HiSave className="mr-2 h-4 w-4" />
                      {isCreating ? 'Create Space' : 'Save Changes'}
                    </>
                  )}
                </Button>
                <Button onClick={handleCancel} color="gray">
                  <HiX className="mr-2 h-4 w-4" />
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button onClick={handleEdit} color="blue">
                  <HiPencil className="mr-2 h-4 w-4" />
                  Edit
                </Button>
                {/* Only show delete button for existing spaces */}
                {!isCreating && (
                  <Button onClick={handleDelete} color="blue">
                    <HiTrash className="mr-2 h-4 w-4" />
                    Delete
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      {!isCreating && (
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6 overflow-x-auto">
          <nav className="flex gap-4 min-w-max">
            <button
              onClick={() => setActiveTab('overview')}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'overview'
                  ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              <HiViewBoards className="h-4 w-4" />
              Overview
            </button>
            <button
              onClick={() => setActiveTab('settings')}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'settings'
                  ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              <HiCog className="h-4 w-4" />
              Settings
            </button>
            <button
              onClick={() => setActiveTab('analytics')}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'analytics'
                  ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              <HiChartBar className="h-4 w-4" />
              Analytics
            </button>
            <button
              onClick={() => setActiveTab('metrics')}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'metrics'
                  ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              <HiChartBar className="h-4 w-4" />
              Metrics
            </button>
          </nav>
        </div>
      )}

      {/* Tab Content */}
      {activeTab === 'overview' && !isCreating && id && (
        <SpaceOverview spaceId={id} />
      )}

      {(activeTab === 'settings' || isCreating) && (
        <Card>
          <div className="space-y-6">
            {/* Space Identifier */}
            <div>
              <Label htmlFor="space-identifier">Space Identifier</Label>
              {isEditing ? (
                <TextInput
                  id="space-identifier"
                  type="text"
                  value={editForm.space}
                  onChange={(e) => handleInputChange('space', e.target.value)}
                  placeholder="Enter space identifier"
                  className="mt-1"
                />
              ) : (
                <TextInput
                  id="space-identifier"
                  type="text"
                  value={space?.space || ''}
                  disabled
                  className="mt-1"
                />
              )}
            </div>

            {/* Space Name */}
            <div>
              <Label htmlFor="space-name">Space Name</Label>
              {isEditing ? (
                <TextInput
                  id="space-name"
                  type="text"
                  value={editForm.space_name}
                  onChange={(e) => handleInputChange('space_name', e.target.value)}
                  placeholder="Enter space name"
                  className="mt-1"
                />
              ) : (
                <TextInput
                  id="space-name"
                  type="text"
                  value={space?.space_name || ''}
                  disabled
                  className="mt-1"
                />
              )}
            </div>

            {/* Space Description */}
            <div>
              <Label htmlFor="space-description">Description</Label>
              {isEditing ? (
                <Textarea
                  id="space-description"
                  value={editForm.space_description}
                  onChange={(e) => handleInputChange('space_description', e.target.value)}
                  placeholder="Enter space description"
                  rows={4}
                  className="mt-1"
                />
              ) : (
                <Textarea
                  id="space-description"
                  value={space?.space_description || ''}
                  disabled
                  rows={4}
                  className="mt-1"
                />
              )}
            </div>

          </div>
        </Card>
      )}

      {activeTab === 'analytics' && !isCreating && id && (
        <React.Suspense fallback={<Spinner size="lg" className="mx-auto mt-8" />}>
          <SpaceAnalytics spaceId={id} />
        </React.Suspense>
      )}

      {activeTab === 'metrics' && !isCreating && id && (
        <React.Suspense fallback={<Spinner size="lg" className="mx-auto mt-8" />}>
          <SpaceMetrics spaceId={id} />
        </React.Suspense>
      )}

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={handleDeleteCancel} size="md" dismissible>
        <ModalHeader>
          <div className="flex items-center">
            <HiExclamationCircle className="mr-2 h-6 w-6 text-red-500" />
            Confirm Delete
          </div>
        </ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <p className="text-gray-700 dark:text-gray-300">
              Are you sure you want to delete the space <strong>"{space?.space_name || space?.space}"</strong>?
            </p>
            <p className="text-sm text-red-600 dark:text-red-400">
              This action cannot be undone. All data associated with this space will be permanently removed.
            </p>
          </div>
        </ModalBody>
        <ModalFooter>
          <div className="flex flex-col-reverse sm:flex-row gap-2 w-full sm:w-auto">
            <Button 
              onClick={handleDeleteCancel} 
              color="gray"
              className="w-full sm:w-auto"
            >
              Cancel
            </Button>
            <Button 
              onClick={handleDeleteConfirm} 
              color="blue"
              disabled={deleting}
              className="w-full sm:w-auto"
            >
              {deleting ? (
                <>
                  <Spinner size="sm" className="mr-2" />
                  Deleting...
                </>
              ) : (
                <>
                  <HiTrash className="mr-2 h-4 w-4" />
                  Delete Space
                </>
              )}
            </Button>
          </div>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default SpaceDetail;
