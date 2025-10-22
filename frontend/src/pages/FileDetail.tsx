import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Label,
  TextInput,
  Alert,
  Spinner,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Textarea
} from 'flowbite-react';
import {
  HiDownload,
  HiPencil,
  HiTrash,
  HiSave,
  HiX,
  HiExclamationCircle,
  HiDocument,
  HiDocumentDuplicate
} from 'react-icons/hi';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import { mockFiles, mockSpaces, type File } from '../mock';

interface EditForm {
  filename: string;
  file_type: string;
  description: string;
}


const FileDetail: React.FC = () => {
  const { spaceId, graphId, fileId } = useParams<{ 
    spaceId?: string; 
    graphId?: string; 
    fileId?: string; 
  }>();
  
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [saving] = useState<boolean>(false);
  const [deleting] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [editForm, setEditForm] = useState<EditForm>({
    filename: '',
    file_type: '',
    description: ''
  });

  // Mock data loading
  useEffect(() => {
    // Simulate loading with mock data
    setTimeout(() => {
      const fileIdNum = parseInt(fileId || '0');
      
      // Find the file by ID
      const foundFile = mockFiles.find(f => f.id === fileIdNum);

      setFile(foundFile || null);
      setEditForm({
        filename: foundFile?.filename || '',
        file_type: foundFile?.file_type || '',
        description: '' // Description not available in centralized mock data
      });
      setLoading(false);
    }, 500);
  }, [fileId, spaceId, graphId]);

  // Check for changes when form values change
  useEffect(() => {
    if (!file) return;

    const hasFormChanges = 
      editForm.filename !== file.filename ||
      editForm.description !== '' || // Description always starts empty since not in mock data
      editForm.file_type !== file.file_type;
    
    setHasChanges(hasFormChanges);
  }, [editForm, file]);

  const handleEdit = () => {
    setIsEditing(true);
  };

  const handleCancel = () => {
    // Reset form to original values
    if (file) {
      setEditForm({
        filename: file.filename,
        description: '', // Description not available in centralized mock data
        file_type: file.file_type
      });
    }
    setIsEditing(false);
  };

  const handleSave = () => {
    // Mock save - show alert instead of backend call
    alert('Save functionality will be available when backend is ready');
    setIsEditing(false);
  };

  const handleDelete = () => {
    // Mock delete - show alert instead of backend call
    alert('Delete functionality will be available when backend is ready');
    setShowDeleteModal(false);
  };

  const handleDownload = () => {
    // Mock download - show alert instead of backend call
    alert('Download functionality will be available when backend is ready');
  };

  const formatDate = (dateString: string): string => {
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return 'Invalid date';
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!file) {
    return (
      <div className="space-y-6">
        <Alert color="failure">
          <span className="font-medium">Error:</span> File not found
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb Navigation */}
      <NavigationBreadcrumb 
        spaceId={spaceId} 
        graphId={graphId} 
        currentPageName={file.filename} 
        currentPageIcon={HiDocument}
        parentPageName="Files"
        parentPagePath={spaceId && graphId ? `/space/${spaceId}/graph/${graphId}/files` : '/files'}
        parentPageIcon={HiDocumentDuplicate}
      />

      {/* Back Navigation Button */}
      <div className="flex items-center gap-2">
        <Button
          color="gray"
          size="sm"
          onClick={() => {
            if (spaceId && graphId) {
              navigate(`/space/${spaceId}/graph/${graphId}/files`);
            } else {
              navigate('/files');
            }
          }}
        >
          ← Back to Files
        </Button>
      </div>

      {/* Error Display */}
      {error && (
        <Alert color="failure">
          <span className="font-medium">Error:</span> {error}
        </Alert>
      )}

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <HiDocumentDuplicate className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              {file.filename}
            </h1>
          </div>
          <p className="mt-2 text-sm text-gray-700 dark:text-gray-300">
            View and manage file details
          </p>
        </div>
        
        <div className="flex gap-2 mt-4 sm:mt-0">
          <Button color="blue" onClick={handleDownload}>
            <HiDownload className="mr-2 h-4 w-4" />
            Download
          </Button>
          {!isEditing && (
            <Button color="blue" onClick={handleEdit}>
              <HiPencil className="mr-2 h-4 w-4" />
              Edit
            </Button>
          )}
          {!isEditing && (
            <Button color="red" onClick={() => setShowDeleteModal(true)}>
              <HiTrash className="mr-2 h-4 w-4" />
              Delete
            </Button>
          )}
        </div>
      </div>

      {/* File Details Card */}
      <Card>
        <div className="space-y-6">
          <div>
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">
              File Information
            </h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Filename */}
              <div>
                <Label htmlFor="filename">Filename</Label>
                <TextInput
                  id="filename"
                  type="text"
                  value={editForm.filename}
                  onChange={(e) => setEditForm({ ...editForm, filename: e.target.value })}
                  disabled={!isEditing}
                  required
                />
              </div>

              {/* File Type */}
              <div>
                <Label htmlFor="file_type">File Type</Label>
                <TextInput
                  id="file_type"
                  type="text"
                  value={editForm.file_type}
                  onChange={(e) => setEditForm({ ...editForm, file_type: e.target.value })}
                  disabled={!isEditing}
                />
              </div>

              {/* File Size (read-only) */}
              <div>
                <Label htmlFor="file_size">File Size</Label>
                <TextInput
                  id="file_size"
                  type="text"
                  value={formatFileSize(file.file_size)}
                  disabled
                />
              </div>

              {/* Space (read-only) */}
              {spaceId && (
                <div>
                  <Label htmlFor="space">Space</Label>
                  <TextInput
                    id="space"
                    type="text"
                    value={mockSpaces.find(s => s.space === spaceId)?.space_name || spaceId}
                    disabled
                  />
                </div>
              )}

              {/* Upload Time (read-only) */}
              <div>
                <Label htmlFor="upload_time">Upload Time</Label>
                <TextInput
                  id="upload_time"
                  type="text"
                  value={formatDate(file.upload_time)}
                  disabled
                />
              </div>

              {/* Last Modified (read-only) */}
              <div>
                <Label htmlFor="last_modified">Last Modified</Label>
                <TextInput
                  id="last_modified"
                  type="text"
                  value={formatDate(file.last_modified)}
                  disabled
                />
              </div>
            </div>

            {/* Description */}
            <div className="mt-6">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                rows={4}
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                disabled={!isEditing}
                placeholder="Enter file description..."
              />
            </div>
          </div>

          {/* Action Buttons */}
          {isEditing && (
            <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button 
                color="blue" 
                onClick={handleSave}
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
                    Save Changes
                  </>
                )}
              </Button>
              <Button color="gray" onClick={handleCancel} disabled={saving}>
                <HiX className="mr-2 h-4 w-4" />
                Cancel
              </Button>
            </div>
          )}
        </div>
      </Card>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)}>
        <ModalHeader>
          <HiExclamationCircle className="mr-2 h-6 w-6 text-red-600" />
          Confirm Deletion
        </ModalHeader>
        <ModalBody>
          <p className="text-gray-500 dark:text-gray-400">
            Are you sure you want to delete this file? This action cannot be undone.
          </p>
          <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
            <p className="font-medium text-gray-900 dark:text-white">
              {file.filename}
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Size: {formatFileSize(file.file_size)}
            </p>
          </div>
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
                Delete File
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

export default FileDetail;
