import React, { useState, useEffect, useCallback } from 'react';
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
} from 'flowbite-react';
import {
  HiDownload,
  HiTrash,
  HiExclamationCircle,
  HiDocument,
  HiDocumentDuplicate
} from 'react-icons/hi';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import { formatFileSize, formatDateTime } from '../utils/formatUtils';
import { apiService } from '../services/ApiService';
import {
  groupQuadsBySubject,
  getFirstValue,
  shortenUri,
  RDF_TYPE,
  HAS_NAME,
  type Quad,
} from '../utils/QuadUtils';

const HAS_FILE_TYPE = 'http://vital.ai/ontology/vital-core#hasFileType';
const HAS_FILE_SIZE = 'http://vital.ai/ontology/vital-core#hasFileLength';
const HAS_UPLOAD_TIME = 'http://vital.ai/ontology/vital-core#hasTimestamp';
const HAS_FILE_PATH = 'http://vital.ai/ontology/vital-core#hasFileNodeUri';

interface FileInfo {
  uri: string;
  filename: string;
  file_type: string;
  file_size: number;
  file_path: string;
  upload_time: string;
  rdf_type: string;
  properties: Map<string, string[]>;
}


const FileDetail: React.FC = () => {
  const { spaceId, graphId, fileId } = useParams<{ 
    spaceId?: string; 
    graphId?: string; 
    fileId?: string; 
  }>();
  
  const navigate = useNavigate();
  const [file, setFile] = useState<FileInfo | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [downloading, setDownloading] = useState<boolean>(false);

  const fetchFile = useCallback(async () => {
    if (!spaceId || !graphId || !fileId) {
      setError('Missing required parameters');
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getFile(spaceId, decodeURIComponent(graphId), decodeURIComponent(fileId));
      const quads: Quad[] = data.results || [];
      if (quads.length === 0) {
        setError('File not found');
        setFile(null);
      } else {
        const subjectMap = groupQuadsBySubject(quads);
        const [uri, preds] = subjectMap.entries().next().value!;
        const filename = getFirstValue(preds, HAS_NAME) || shortenUri(uri);
        const file_type = getFirstValue(preds, HAS_FILE_TYPE) || '';
        const file_size_str = getFirstValue(preds, HAS_FILE_SIZE) || '0';
        const file_size = parseInt(file_size_str) || 0;
        const upload_time = getFirstValue(preds, HAS_UPLOAD_TIME) || '';
        const file_path = getFirstValue(preds, HAS_FILE_PATH) || '';
        const rdf_type = getFirstValue(preds, RDF_TYPE) || 'Unknown';
        setFile({ uri, filename, file_type, file_size, file_path, upload_time, rdf_type, properties: preds });
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load file details');
    } finally {
      setLoading(false);
    }
  }, [spaceId, graphId, fileId]);

  useEffect(() => { fetchFile(); }, [fetchFile]);

  const handleDelete = async () => {
    if (!spaceId || !graphId || !file) return;
    try {
      setDeleting(true);
      await apiService.deleteFile(spaceId, decodeURIComponent(graphId), file.uri);
      navigate(-1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete file');
      setShowDeleteModal(false);
    } finally {
      setDeleting(false);
    }
  };

  const handleDownload = async () => {
    if (!spaceId || !graphId || !file) return;
    try {
      setDownloading(true);
      const blob = await apiService.downloadFile(spaceId, decodeURIComponent(graphId), file.uri);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = file.filename;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to download file');
    } finally {
      setDownloading(false);
    }
  };

  const formatDate = formatDateTime;

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
        {error && <Alert color="failure"><span className="font-medium">Error:</span> {error}</Alert>}
        {!error && (
          <Alert color="warning">File not found</Alert>
        )}
        <Button color="gray" size="sm" onClick={() => navigate(-1)}>← Go Back</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="file-detail-page">
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
            {file.rdf_type !== 'Unknown' ? shortenUri(file.rdf_type) : 'File'}
          </p>
        </div>
        
        <div className="flex gap-2 mt-4 sm:mt-0">
          <Button color="blue" onClick={handleDownload} disabled={downloading}>
            {downloading ? <Spinner size="sm" className="mr-2" /> : <HiDownload className="mr-2 h-4 w-4" />}
            Download
          </Button>
          <Button color="red" onClick={() => setShowDeleteModal(true)}>
            <HiTrash className="mr-2 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {/* File Details Card */}
      <Card>
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">
          File Information
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <Label>Filename</Label>
            <TextInput type="text" value={file.filename} disabled />
          </div>
          <div>
            <Label>File Type</Label>
            <TextInput type="text" value={file.file_type || 'N/A'} disabled />
          </div>
          <div>
            <Label>File Size</Label>
            <TextInput type="text" value={file.file_size ? formatFileSize(file.file_size) : 'Unknown'} disabled />
          </div>
          <div>
            <Label>Space</Label>
            <TextInput type="text" value={spaceId || ''} disabled />
          </div>
          {file.upload_time && (
            <div>
              <Label>Upload Time</Label>
              <TextInput type="text" value={formatDate(file.upload_time)} disabled />
            </div>
          )}
          {file.file_path && (
            <div>
              <Label>File Path</Label>
              <TextInput type="text" value={file.file_path} disabled />
            </div>
          )}
          <div>
            <Label>URI</Label>
            <TextInput type="text" value={file.uri} disabled className="font-mono text-xs" />
          </div>
        </div>

        {/* All properties */}
        <div className="mt-6">
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">All Properties ({file.properties.size})</h4>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-2">Predicate</th>
                  <th className="px-4 py-2">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {Array.from(file.properties.entries()).map(([pred, values]) => (
                  values.map((val, i) => (
                    <tr key={`${pred}-${i}`} className="bg-white dark:bg-gray-900">
                      <td className="px-4 py-2 font-mono text-xs text-gray-600 dark:text-gray-400 max-w-[16rem] truncate" title={pred}>
                        {shortenUri(pred)}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs max-w-[24rem] truncate" title={val}>
                        {val}
                      </td>
                    </tr>
                  ))
                ))}
              </tbody>
            </table>
          </div>
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
              {file.file_size ? `Size: ${formatFileSize(file.file_size)}` : ''}
            </p>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="red" onClick={handleDelete} disabled={deleting}>
            {deleting ? (
              <><Spinner size="sm" className="mr-2" />Deleting...</>
            ) : (
              <><HiTrash className="mr-2 h-4 w-4" />Delete File</>
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
