import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { 
  Alert, 
  Button, 
  Card, 
  Label, 
  TextInput, 
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
  HiTrash,
  HiSave,
  HiX,
  HiUser,
  HiHome,
  HiEye,
  HiEyeOff,
  HiExclamationCircle
} from 'react-icons/hi';

interface User {
  id: string;
  username: string;
  full_name: string;
  email: string;
  profile_image?: string;
  role: string;
  password?: string;
  tenant?: string;
  update_time?: string;
}

interface BannerMessage {
  type: 'success' | 'error';
  message: string;
}

const UserDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  
  // Check if this is creation mode
  const isCreating = id === 'new';
  
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState<boolean>(isCreating); // Start in edit mode for creation
  const [saving, setSaving] = useState<boolean>(false);
  const [bannerMessage, setBannerMessage] = useState<BannerMessage | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [deleting, setDeleting] = useState<boolean>(false);
  
  // Form state for editing
  const [editForm, setEditForm] = useState({
    username: '',
    full_name: '',
    email: '',
    profile_image: '',
    role: '',
    password: '',
    tenant: ''
  });

  // Track if form has changes
  const [hasChanges, setHasChanges] = useState<boolean>(false);
  
  // Password visibility toggle
  const [showPassword, setShowPassword] = useState<boolean>(false);

  // Fetch user details or initialize for creation
  useEffect(() => {
    const fetchUser = async () => {
      if (!id) {
        setError('User ID is required');
        setLoading(false);
        return;
      }

      // If creating new user, initialize with empty form
      if (isCreating) {
        setEditForm({
          username: '',
          full_name: '',
          email: '',
          profile_image: '',
          role: '',
          password: '',
          tenant: ''
        });
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const response = await axios.get(`/api/users/${id}`);
        const userData = response.data;
        setUser(userData);
        
        // Initialize edit form with current values
        setEditForm({
          username: userData.username || '',
          full_name: userData.full_name || '',
          email: userData.email || '',
          profile_image: userData.profile_image || '',
          role: userData.role || '',
          password: '', // Password field for editing (empty by default)
          tenant: '' // Tenant field for editing
        });
        
        setError(null);
      } catch (err: any) {
        console.error('Error fetching user:', err);
        setError(err.response?.data?.detail || 'Failed to load user details');
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    fetchUser();
  }, [id, isCreating]);

  // Check for changes when form values change
  useEffect(() => {
    if (isCreating) {
      // For creation mode, check if required fields are filled
      const hasRequiredFields = editForm.username.trim() !== '' && editForm.email.trim() !== '';
      setHasChanges(hasRequiredFields);
    } else {
      if (!user) return;
      
      const hasFormChanges = 
        editForm.username !== (user.username || '') ||
        editForm.full_name !== (user.full_name || '') ||
        editForm.email !== (user.email || '') ||
        editForm.profile_image !== (user.profile_image || '') ||
        editForm.role !== (user.role || '') ||
        editForm.password.trim() !== '' || // Password change if entered
        editForm.tenant.trim() !== ''; // Tenant change if entered
      
      setHasChanges(hasFormChanges);
    }
  }, [editForm, user, isCreating]);

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
      // For creation mode, navigate back to users list
      navigate('/users');
      return;
    }
    
    if (!user) return;
    
    // Reset form to original values
    setEditForm({
      username: user.username || '',
      full_name: user.full_name || '',
      email: user.email || '',
      profile_image: user.profile_image || '',
      role: user.role || '',
      password: user.password || '', // Reset to original password
      tenant: user.tenant || ''
    });
    
    setIsEditing(false);
    setHasChanges(false);
  };

  const handleSave = async () => {
    if (!hasChanges) return;

    try {
      setSaving(true);
      
      if (isCreating) {
        // Create new user - don't include ID in payload
        const createData = {
          ...editForm
        };

        const response = await axios.post('/api/users', createData);
        const createdUser = response.data;
        
        showBanner('success', 'User created successfully!');
        
        // Navigate to the created user's detail page
        navigate(`/user/${createdUser.id}`);
      } else {
        // Update existing user
        if (!user) return;
        
        const updateData = {
          id: user.id,
          ...editForm
        };

        const response = await axios.put(`/api/users/${user.id}`, updateData);
        const updatedUser = response.data;
        
        setUser(updatedUser);
        setIsEditing(false);
        setHasChanges(false);
        
        // Update edit form with new values from server response
        setEditForm({
          username: updatedUser.username || '',
          full_name: updatedUser.full_name || '',
          email: updatedUser.email || '',
          profile_image: updatedUser.profile_image || '',
          role: updatedUser.role || '',
          password: updatedUser.password || '',
          tenant: updatedUser.tenant || ''
        });
        
        showBanner('success', 'User updated successfully!');
      }
    } catch (err: any) {
      console.error('Error saving user:', err);
      const action = isCreating ? 'create' : 'update';
      showBanner('error', err.response?.data?.detail || `Failed to ${action} user`);
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
    if (!user) return;
    
    try {
      setDeleting(true);
      await axios.delete(`/api/users/${user.id}`);
      
      // Show success message and navigate back to users list
      showBanner('success', 'User deleted successfully');
      setTimeout(() => {
        navigate('/users');
      }, 1000);
    } catch (err: any) {
      console.error('Error deleting user:', err);
      const errorMessage = err.response?.data?.detail || 'Failed to delete user';
      showBanner('error', errorMessage);
    } finally {
      setDeleting(false);
      setShowDeleteModal(false);
    }
  };

  const handleDeleteCancel = () => {
    setShowDeleteModal(false);
  };

  const formatDate = (dateString: string | undefined) => {
    if (!dateString || dateString === '' || dateString === 'undefined' || dateString === 'null') {
      return 'Not available';
    }
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) {
        return 'Not available';
      }
      return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return 'Not available';
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
        <Button onClick={() => navigate('/users')} color="gray">
          Back to Users
        </Button>
      </div>
    );
  }

  if (!user && !isCreating) {
    return (
      <div>
        <Alert color="warning" className="mb-6">
          User not found
        </Alert>
        <Button onClick={() => navigate('/users')} color="gray">
          Back to Users
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumbs */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        <BreadcrumbItem href="/users" icon={HiUser}>
          Users
        </BreadcrumbItem>
        <BreadcrumbItem>
          {isCreating ? 'New User' : (user?.username || `User ${user?.id}`)}
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Banner Message Area */}
      {bannerMessage && (
        <Alert 
          color={bannerMessage.type === 'success' ? 'success' : 'failure'}
          className="mb-6"
          onDismiss={() => setBannerMessage(null)}
        >
          <span className="font-medium">
            {bannerMessage.type === 'success' ? 'Success:' : 'Error:'}
          </span>{' '}
          {bannerMessage.message}
        </Alert>
      )}

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-4">
          <HiUser className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            User Details
          </h1>
          <div className="flex flex-col sm:flex-row gap-2">
            {isEditing ? (
              <>
                <Button
                  onClick={handleSave}
                  disabled={!hasChanges || saving}
                  color="blue"
                >
                  <HiSave className="mr-2 h-4 w-4" />
                  {saving ? 'Saving...' : (isCreating ? 'Create' : 'Save')}
                </Button>
                <Button
                  onClick={handleCancel}
                  disabled={saving}
                  color="gray"
                >
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
                {/* Only show delete button for existing users */}
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

      {/* User Details Card */}
      <Card>
        <div className="space-y-6">
          {/* User ID (Read-only) - Only show for existing users */}
          {!isCreating && (
            <div>
              <Label htmlFor="user-id">User ID</Label>
              <TextInput
                id="user-id"
                type="text"
                value={user?.id || ''}
                disabled
                className="mt-1"
              />
            </div>
          )}

          {/* Username */}
          <div>
            <Label htmlFor="username">Username</Label>
            {isEditing ? (
              <TextInput
                id="username"
                type="text"
                value={editForm.username}
                onChange={(e) => handleInputChange('username', e.target.value)}
                placeholder="Enter username"
                className="mt-1"
                required
              />
            ) : (
              <TextInput
                id="username"
                type="text"
                value={user?.username || ''}
                disabled
                className="mt-1"
              />
            )}
          </div>

          {/* Email */}
          <div>
            <Label htmlFor="email">Email</Label>
            {isEditing ? (
              <TextInput
                id="email"
                type="email"
                value={editForm.email}
                onChange={(e) => handleInputChange('email', e.target.value)}
                placeholder="Enter email address"
                className="mt-1"
              />
            ) : (
              <TextInput
                id="email"
                type="email"
                value={user?.email || ''}
                disabled
                className="mt-1"
              />
            )}
          </div>

          {/* Password */}
          <div>
            <Label htmlFor="password">Password</Label>
            {isEditing ? (
              <div className="relative mt-1">
                <TextInput
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={editForm.password}
                  onChange={(e) => handleInputChange('password', e.target.value)}
                  placeholder={isCreating ? "Enter password" : "Enter new password (optional)"}
                  className="pr-10"
                  required={isCreating}
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? (
                    <HiEyeOff className="h-5 w-5" />
                  ) : (
                    <HiEye className="h-5 w-5" />
                  )}
                </button>
              </div>
            ) : (
              <div className="relative mt-1">
                <TextInput
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={user?.password || ''}
                  disabled
                  className="pr-10"
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? (
                    <HiEyeOff className="h-5 w-5" />
                  ) : (
                    <HiEye className="h-5 w-5" />
                  )}
                </button>
              </div>
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
                value={user?.tenant || ''}
                disabled
                className="mt-1"
              />
            )}
          </div>

          {/* Last Updated (Read-only) - Only show for existing users */}
          {!isCreating && (
            <div>
              <Label htmlFor="last-updated">Last Updated</Label>
              <TextInput
                id="last-updated"
                type="text"
                value={formatDate(user?.update_time)}
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
              Are you sure you want to delete the user <strong>"{user?.username}"</strong>?
            </p>
            <p className="text-sm text-red-600 dark:text-red-400">
              This action cannot be undone. All data associated with this user will be permanently removed.
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
                  Delete User
                </>
              )}
            </Button>
          </div>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default UserDetail;
