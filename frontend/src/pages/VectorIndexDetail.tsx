import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Alert,
  Badge,
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Spinner,
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiHome,
  HiRefresh,
  HiTrash,
  HiExclamation,
} from 'react-icons/hi';
import { vectorGeoService } from '../services/VectorGeoService';
import type { VectorIndex } from '../types/vectorGeo';
import { formatDateShort } from '../utils/formatUtils';

const VectorIndexDetail: React.FC = () => {
  const { spaceId, indexName } = useParams<{ spaceId: string; indexName: string }>();
  const navigate = useNavigate();

  const [index, setIndex] = useState<VectorIndex | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Reindex
  const [reindexing, setReindexing] = useState(false);

  // Delete
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadIndex = useCallback(async () => {
    if (!spaceId || !indexName) return;
    setLoading(true);
    try {
      const data = await vectorGeoService.getVectorIndex(spaceId, indexName);
      setIndex(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load vector index');
    } finally {
      setLoading(false);
    }
  }, [spaceId, indexName]);

  useEffect(() => {
    loadIndex();
  }, [loadIndex]);

  const handleReindex = async () => {
    if (!spaceId || !indexName) return;
    setReindexing(true);
    try {
      const result = await vectorGeoService.reindex(spaceId, indexName);
      setSuccess(result.message || `Reindex started for "${indexName}"`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to trigger reindex');
    } finally {
      setReindexing(false);
    }
  };

  const handleDelete = async () => {
    if (!spaceId || !indexName) return;
    setDeleting(true);
    try {
      await vectorGeoService.deleteVectorIndex(spaceId, indexName);
      navigate('/vector-indexes');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete index');
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="xl" />
      </div>
    );
  }

  if (!index) {
    return (
      <Alert color="failure">
        Vector index not found
      </Alert>
    );
  }

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/vector-indexes">Vector Indexes</BreadcrumbItem>
        <BreadcrumbItem>{index.index_name}</BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Button size="sm" color="light" onClick={() => navigate('/vector-indexes')}>
          <HiArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {index.index_name}
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <Badge color="purple">vector</Badge>
            <Badge color="info">{index.provider}</Badge>
            <span className="text-sm text-gray-500">{index.dimensions}d · {index.distance_metric}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" color="light" onClick={handleReindex} disabled={reindexing}>
            {reindexing ? <Spinner size="sm" className="mr-2" /> : <HiRefresh className="mr-2 h-4 w-4" />}
            Re-Index
          </Button>
          <Button size="sm" color="failure" onClick={() => setShowDelete(true)}>
            <HiTrash className="mr-2 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert color="success" className="mb-4" onDismiss={() => setSuccess(null)}>
          {success}
        </Alert>
      )}

      {/* Info panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Configuration</h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Index Name</dt>
              <dd className="text-gray-900 dark:text-white font-mono">{index.index_name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Provider</dt>
              <dd><Badge color="info">{index.provider}</Badge></dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Dimensions</dt>
              <dd className="text-gray-900 dark:text-white">{index.dimensions}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Distance Metric</dt>
              <dd><Badge color="gray">{index.distance_metric}</Badge></dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Model</dt>
              <dd className="text-gray-900 dark:text-white">{index.model_name || '—'}</dd>
            </div>
            {index.description && (
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Description</dt>
                <dd className="text-gray-900 dark:text-white">{index.description}</dd>
              </div>
            )}
          </dl>
        </div>

        <div className="p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Stats</h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Space</dt>
              <dd className="text-gray-900 dark:text-white font-mono">{spaceId}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Row Count</dt>
              <dd className="text-gray-900 dark:text-white">
                {index.row_count !== undefined ? index.row_count.toLocaleString() : '—'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Created</dt>
              <dd className="text-gray-900 dark:text-white">
                {formatDateShort(index.created_time)}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Provider config if present */}
      {index.provider_config && Object.keys(index.provider_config).length > 0 && (
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 mb-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Provider Config</h3>
          <pre className="text-xs bg-gray-50 dark:bg-gray-800 p-3 rounded overflow-x-auto">
            {JSON.stringify(index.provider_config, null, 2)}
          </pre>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <Modal show={showDelete} onClose={() => setShowDelete(false)} size="md">
        <ModalHeader>Delete Vector Index</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500 flex-shrink-0" />
            <div>
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete index <strong>{index.index_name}</strong>?
              </p>
              <p className="text-sm text-gray-500 mt-1">
                This will permanently delete all stored embeddings. This action cannot be undone.
              </p>
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="failure" onClick={handleDelete} disabled={deleting}>
            {deleting ? <Spinner size="sm" className="mr-2" /> : null}
            Delete
          </Button>
          <Button color="gray" onClick={() => setShowDelete(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default VectorIndexDetail;
