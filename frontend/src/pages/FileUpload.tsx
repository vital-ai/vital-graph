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
import { apiService, vgClient } from '../services/ApiService';
import { extractGraphName } from '../utils/QuadUtils';
import { formatFileSize } from '../utils/formatUtils';

interface FileForm {
  name: string;
  description: string;
  file: File | null;
}

const FileUpload: React.FC = () => {
  const { spaceId, graphId } = useParams<{ spaceId: string; graphId: string }>();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const [spaceName, setSpaceName] = useState<string>('');
  const [graphName, setGraphName] = useState<string>('');
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
    // Load space and graph names
    const loadNames = async () => {
      if (spaceId) {
        try {
          const spaces = await apiService.getSpaces();
          const found = spaces.find((s: { space: string; space_name?: string }) => s.space === spaceId);
          setSpaceName(found?.space_name || spaceId);
        } catch {
          setSpaceName(spaceId);
        }
      }
      if (graphId) {
        setGraphName(extractGraphName(graphId));
      }
    };
    loadNames();
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
      // Step 1: Create file node with metadata
      setUploadProgress(20);
      const fileNodeQuad = {
        subject: '', // server assigns URI
        properties: {
          'http://vital.ai/ontology/vital-core#hasName': fileForm.name.trim(),
          'http://vital.ai/ontology/vital-core#hasDescription': fileForm.description.trim(),
          'http://vital.ai/ontology/vital-core#hasFileName': fileForm.file.name,
          'http://vital.ai/ontology/vital-core#hasFileSize': fileForm.file.size,
          'http://vital.ai/ontology/vital-core#hasMimeType': fileForm.file.type || 'application/octet-stream',
        },
        type: 'http://vital.ai/ontology/vital-core#FileNode',
      };
      const createResult = await vgClient.files.create(
        spaceId || '',
        graphId || '',
        { quads: [fileNodeQuad] },
      ) as { created_uris?: string[]; created_count?: number };

      const createdUri = createResult.created_uris?.[0];
      if (!createdUri) {
        throw new Error('Failed to create file node — no URI returned');
      }

      // Step 2: Upload file content to the created node
      setUploadProgress(50);
      await vgClient.files.upload(
        spaceId || '',
        graphId || '',
        createdUri,
        fileForm.file,
        fileForm.file.name,
      );
      
      setUploadProgress(100);
      setSuccess(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to upload file. Please try again.');
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

  const isFormValid = fileForm.file && fileForm.name.trim().length > 0;

  return (
    <div className="p-6" data-testid="file-upload-page">
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        {spaceName && (
          <BreadcrumbItem href={`/spaces/${spaceId}`}>
            {spaceName}
          </BreadcrumbItem>
        )}
        <BreadcrumbItem href={`/space/${spaceId}/graphs`}>
          Graphs
        </BreadcrumbItem>
        {graphName && (
          <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}`}>
            {graphName}
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

      {spaceName && graphName && (
        <div className="mb-6">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Uploading to <span className="font-medium">{spaceName}</span> → <span className="font-medium">{graphName}</span>
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
                    Supported formats: RDF/XML, Turtle, N-Triples, N-Quads
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
                    accept=".rdf,.xml,.ttl,.nt,.nq,.n3"
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
