import React, { useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Label,
  TextInput,
  Alert,
  Spinner,
  Breadcrumb,
  BreadcrumbItem,
  Progress,
  Textarea
} from 'flowbite-react';
import {
  HiHome,
  HiUpload,
  HiX,
  HiDocumentAdd,
  HiExclamationCircle,
  HiCheckCircle
} from 'react-icons/hi';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import axios from 'axios';

interface FileForm {
  name: string;
  description: string;
  file: File | null;
}

const FileUpload: React.FC = () => {
  const { spaceId, graphId } = useParams<{ spaceId: string; graphId: string }>();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const [space, setSpace] = useState<Space | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [fileForm, setFileForm] = useState<FileForm>({
    name: '',
    description: '',
    file: null
  });
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  React.useEffect(() => {
    // Load space and graph data
    if (spaceId) {
      const foundSpace = mockSpaces.find(s => s.space === spaceId);
      setSpace(foundSpace || null);
    }
    
    if (graphId) {
      const foundGraph = mockGraphs.find(g => g.id === parseInt(graphId));
      setGraph(foundGraph || null);
    }
  }, [spaceId, graphId]);

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    
    const file = files[0]; // Only take the first file
    setFileForm(prev => ({ ...prev, file }));
    setError(null);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    handleFileSelect(e.dataTransfer.files);
  };

  const removeFile = () => {
    setFileForm(prev => ({ ...prev, file: null }));
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleCancel = () => {
    navigate(`/space/${spaceId}/graph/${graphId}/files`);
  };

  const handleUpload = async () => {
    if (!fileForm.file || !fileForm.name.trim()) {
      setError('Please provide a file name and select a file to upload.');
      return;
    }
    
    setIsUploading(true);
    setError(null);
    setUploadProgress(0);
    
    try {
      const formData = new FormData();
      formData.append('file', fileForm.file);
      formData.append('name', fileForm.name.trim());
      formData.append('description', fileForm.description.trim());
      formData.append('space_id', spaceId || '');
      formData.append('graph_id', graphId || '');
      
      const response = await axios.post('/api/files/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(progress);
          }
        },
      });
      
      setSuccess(true);
      console.log('Upload successful:', response.data);
    } catch (err: any) {
      console.error('Upload failed:', err);
      setError(err.response?.data?.detail || 'Failed to upload file. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleStartOver = () => {
    setFileForm({ name: '', description: '', file: null });
    setSuccess(false);
    setError(null);
    setUploadProgress(0);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const isFormValid = fileForm.file && fileForm.name.trim().length > 0;

  return (
    <div className="p-6">
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        {space && (
          <BreadcrumbItem href={`/spaces/${spaceId}`}>
            {space.space_name}
          </BreadcrumbItem>
        )}
        <BreadcrumbItem href={`/space/${spaceId}/graphs`}>
          Graphs
        </BreadcrumbItem>
        {graph && (
          <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}`}>
            {graph.graph_name}
          </BreadcrumbItem>
        )}
        <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}/files`}>
          Files
        </BreadcrumbItem>
        <BreadcrumbItem>
          Upload
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center gap-2 mb-6">
        <HiUpload className="w-6 h-6 text-blue-600" />
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Upload Files
        </h1>
      </div>

      {space && graph && (
        <div className="mb-6">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Uploading to <span className="font-medium">{space.space_name}</span> → <span className="font-medium">{graph.graph_name}</span>
          </p>
        </div>
      )}

      <div className="max-w-4xl">
        {/* File Upload Form */}
        <Card className="mb-6">
          <div className="space-y-6">
            {/* Name Field */}
            <div>
              <Label htmlFor="fileName" className="mb-2 block">
                File Name <span className="text-red-500">*</span>
              </Label>
              <TextInput
                id="fileName"
                placeholder="Enter a short descriptive name for this file"
                value={fileForm.name}
                onChange={(e) => setFileForm(prev => ({ ...prev, name: e.target.value }))}
                disabled={isUploading || success}
                required
              />
            </div>

            {/* Description Field */}
            <div>
              <Label htmlFor="fileDescription" className="mb-2 block">
                Description
              </Label>
              <Textarea
                id="fileDescription"
                placeholder="Enter a longer description of this file's contents and purpose"
                value={fileForm.description}
                onChange={(e) => setFileForm(prev => ({ ...prev, description: e.target.value }))}
                disabled={isUploading || success}
                rows={3}
              />
            </div>

            {/* File Selection */}
            <div>
              <Label className="mb-2 block">
                File <span className="text-red-500">*</span>
              </Label>
              {!fileForm.file ? (
                <div
                  className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                    isDragOver
                      ? 'border-blue-400 bg-blue-50 dark:bg-blue-900/20'
                      : 'border-gray-300 dark:border-gray-600'
                  }`}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <HiUpload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
                  <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                    Drop a file here or click to browse
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                    Supported formats: RDF/XML, Turtle, N-Triples, JSON-LD, N-Quads
                  </p>
                  <Button
                    color="blue"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading || success}
                  >
                    <HiDocumentAdd className="mr-2 h-4 w-4" />
                    Choose File
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".rdf,.xml,.ttl,.nt,.jsonld,.nq,.n3"
                    onChange={(e) => handleFileSelect(e.target.files)}
                    className="hidden"
                  />
                </div>
              ) : (
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                  <div className="flex items-center space-x-3">
                    <HiDocumentAdd className="h-5 w-5 text-blue-500" />
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                        {fileForm.file.name}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {formatFileSize(fileForm.file.size)} • {fileForm.file.type || 'Unknown type'}
                      </p>
                    </div>
                  </div>
                  {!isUploading && !success && (
                    <Button size="xs" color="gray" onClick={removeFile}>
                      <HiX className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              )}
            </div>

            {/* Upload Progress */}
            {isUploading && (
              <div>
                <div className="flex justify-between text-sm text-gray-600 dark:text-gray-400 mb-2">
                  <span>Uploading...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <Progress progress={uploadProgress} size="sm" />
              </div>
            )}

            {/* Error Display */}
            {error && (
              <Alert color="failure">
                <HiExclamationCircle className="h-4 w-4" />
                <span className="font-medium">Upload failed:</span> {error}
              </Alert>
            )}

            {/* Action Buttons */}
            <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-600">
              <Button
                color="gray"
                onClick={handleCancel}
                disabled={isUploading}
              >
                Cancel
              </Button>
              <Button
                color="blue"
                onClick={handleUpload}
                disabled={!isFormValid || isUploading || success}
              >
                {isUploading ? (
                  <>
                    <Spinner size="sm" className="mr-2" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <HiUpload className="mr-2 h-4 w-4" />
                    Upload File
                  </>
                )}
              </Button>
            </div>
          </div>
        </Card>


        {/* Success State */}
        {success && (
          <Card>
            <div className="text-center">
              <HiCheckCircle className="mx-auto h-12 w-12 text-green-500 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                Upload Complete!
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
                Your file has been uploaded successfully.
              </p>
              <div className="flex justify-center gap-3">
                <Button color="blue" onClick={handleCancel}>
                  View Files
                </Button>
                <Button color="gray" onClick={handleStartOver}>
                  Upload Another File
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
};

export default FileUpload;
