import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
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
  HiExclamationCircle
} from 'react-icons/hi';

interface Space {
  id: number;
  tenant: string;
  space: string;
  space_name: string;
  space_description: string;
  update_time: string;
}

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
  
  // Form state for editing
  const [editForm, setEditForm] = useState({
    space: '',
    space_name: '',
    space_description: '',
    tenant: ''
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
          space_description: '',
          tenant: ''
        });
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const response = await axios.get(`/api/spaces/${id}`);
        const spaceData = response.data;
        setSpace(spaceData);
        
        // Initialize edit form with current values
        setEditForm({
          space: spaceData.space || '',
          space_name: spaceData.space_name || '',
          space_description: spaceData.space_description || '',
          tenant: spaceData.tenant || ''
        });
        
        setError(null);
      } catch (err: any) {
        console.error('Error fetching space:', err);
        setError(err.response?.data?.detail || 'Failed to load space details');
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
        editForm.space_description !== (space.space_description || '') ||
        editForm.tenant !== (space.tenant || '');
      
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
      space_description: space.space_description || '',
      tenant: space.tenant || ''
    });
    
    setIsEditing(false);
    setHasChanges(false);
  };

  const handleSave = async () => {
    if (!hasChanges) return;

    try {
      setSaving(true);
      
      if (isCreating) {
        // Create new space - don't include ID in payload
        const createData = {
          ...editForm
        };

        const response = await axios.post('/api/spaces', createData);
        const createdSpace = response.data;
        
        showBanner('success', 'Space created successfully!');
        
        // Navigate to the created space's detail page
        navigate(`/space/${createdSpace.id}`);
      } else {
        // Update existing space
        if (!space) return;
        
        const updateData = {
          id: space.id,
          ...editForm
        };

        const response = await axios.put(`/api/spaces/${space.id}`, updateData);
        const updatedSpace = response.data;
        
        setSpace(updatedSpace);
        setIsEditing(false);
        setHasChanges(false);
        
        showBanner('success', 'Space updated successfully!');
      }
    } catch (err: any) {
      console.error('Error saving space:', err);
      const action = isCreating ? 'create' : 'update';
      showBanner('error', err.response?.data?.detail || `Failed to ${action} space`);
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
      await axios.delete(`/api/spaces/${space.id}`);
      
      // Show success message and navigate back to spaces list
      showBanner('success', 'Space deleted successfully');
      setTimeout(() => {
        navigate('/spaces');
      }, 1000);
    } catch (err: any) {
      console.error('Error deleting space:', err);
      const errorMessage = err.response?.data?.detail || 'Failed to delete space';
      showBanner('error', errorMessage);
    } finally {
      setDeleting(false);
      setShowDeleteModal(false);
    }
  };

  const handleDeleteCancel = () => {
    setShowDeleteModal(false);
  };

  const formatDate = (dateString: string) => {
    try {
      return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateString;
    }
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
    <div>
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
          {isCreating ? 'New Space' : (space?.space_name || space?.space || `Space ${space?.id}`)}
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="mb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="mb-2 text-2xl font-bold text-gray-900 dark:text-white">
              {isCreating ? 'Create New Space' : (isEditing ? 'Edit Space' : 'Space Details')}
            </h1>
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

      {/* Space Details Card */}
      <Card>
        <div className="space-y-6">
          {/* Space ID (Read-only) - Only show for existing spaces */}
          {!isCreating && (
            <div>
              <Label htmlFor="space-id">Space ID</Label>
              <TextInput
                id="space-id"
                type="text"
                value={space?.id || ''}
                disabled
                className="mt-1"
              />
            </div>
          )}

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

          {/* Tenant */}
          <div>
            <Label htmlFor="tenant">Tenant</Label>
            {isEditing ? (
              <TextInput
                id="tenant"
                type="text"
                value={editForm.tenant}
                onChange={(e) => handleInputChange('tenant', e.target.value)}
                placeholder="Enter tenant"
                className="mt-1"
              />
            ) : (
              <TextInput
                id="tenant"
                type="text"
                value={space?.tenant || ''}
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

          {/* Last Updated (Read-only) - Only show for existing spaces */}
          {!isCreating && (
            <div>
              <Label htmlFor="last-updated">Last Updated</Label>
              <TextInput
                id="last-updated"
                type="text"
                value={space?.update_time ? formatDate(space.update_time) : ''}
                disabled
                className="mt-1"
              />
            </div>
          )}
        </div>
      </Card>

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
