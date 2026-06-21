import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Select,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Breadcrumb,
  BreadcrumbItem,
  Label,
} from 'flowbite-react';
import { HiTrash, HiRefresh, HiExclamation, HiHome, HiEye } from 'react-icons/hi';
import { vectorGeoService } from '../services/VectorGeoService';
import { apiService } from '../services/ApiService';
import type { VectorIndex } from '../types/vectorGeo';
import { type SpaceInfo } from '../types/api';
import { formatDateShort } from '../utils/formatUtils';

const VectorIndexes: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();
  const navigate = useNavigate();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [indexes, setIndexes] = useState<VectorIndex[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);


  // Delete modal state
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Reindex state
  const [reindexing, setReindexing] = useState<string | null>(null);
  const [reindexResult, setReindexResult] = useState<string | null>(null);

  // Load spaces
  useEffect(() => {
    const loadSpaces = async () => {
      try {
        const spacesData = await apiService.getSpaces();
        setSpaces(spacesData);
        if (!selectedSpace && spacesData.length > 0) {
          setSelectedSpace(spacesData[0].space);
        }
      } catch {
        setError('Failed to load spaces');
      } finally {
        setSpacesLoading(false);
      }
    };
    loadSpaces();
  }, []);

  // Load indexes when space changes
  const loadIndexes = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const data = await vectorGeoService.getVectorIndexes(selectedSpace);
      setIndexes(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load vector indexes');
      setIndexes([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace]);

  useEffect(() => {
    loadIndexes();
  }, [loadIndexes]);

  // Handlers
  const handleSpaceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedSpace(e.target.value);
  };


  const handleDelete = async () => {
    if (!selectedSpace || !deleteTarget) return;
    setDeleting(true);
    try {
      await vectorGeoService.deleteVectorIndex(selectedSpace, deleteTarget);
      setDeleteTarget(null);
      loadIndexes();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete index');
    } finally {
      setDeleting(false);
    }
  };

  const handleReindex = async (indexName: string) => {
    if (!selectedSpace) return;
    setReindexing(indexName);
    setReindexResult(null);
    try {
      const result = await vectorGeoService.reindex(selectedSpace, indexName);
      setReindexResult(result.message || `Reindex started for "${indexName}"`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to trigger reindex');
    } finally {
      setReindexing(null);
    }
  };

  const formatDate = formatDateShort;

  return (
    <div>
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Vector Indexes</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Vector Indexes</h1>
      </div>

      {/* Space selector */}
      {!spaceId && (
        <div className="mb-4 max-w-xs">
          <Label htmlFor="space-select">Space</Label>
          {spacesLoading ? (
            <Spinner size="sm" />
          ) : (
            <Select id="space-select" value={selectedSpace} onChange={handleSpaceChange}>
              <option value="">Select a space...</option>
              {spaces.map((s) => (
                <option key={s.space} value={s.space}>
                  {s.space_name || s.space}
                </option>
              ))}
            </Select>
          )}
        </div>
      )}

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {reindexResult && (
        <Alert color="success" className="mb-4" onDismiss={() => setReindexResult(null)}>
          {reindexResult}
        </Alert>
      )}

      {/* Index table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : indexes.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="text-lg mb-2">No vector indexes found</p>
          <p className="text-sm">
            {selectedSpace
              ? 'Create an index to enable vector similarity search.'
              : 'Select a space to view vector indexes.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table hoverable>
            <TableHead>
              <TableRow>
                <TableHeadCell>Index Name</TableHeadCell>
                <TableHeadCell>Provider</TableHeadCell>
                <TableHeadCell>Dimensions</TableHeadCell>
                <TableHeadCell>Model</TableHeadCell>
                <TableHeadCell>Metric</TableHeadCell>
                <TableHeadCell>Created</TableHeadCell>
                <TableHeadCell>Actions</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody className="divide-y">
              {indexes.map((idx) => (
                <TableRow key={idx.index_name} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                  <TableCell className="font-medium text-gray-900 dark:text-white">
                    {idx.index_name}
                  </TableCell>
                  <TableCell>
                    <Badge color="info">{idx.provider}</Badge>
                  </TableCell>
                  <TableCell>{idx.dimensions}</TableCell>
                  <TableCell className="text-sm text-gray-500 dark:text-gray-400 max-w-48 truncate">
                    {idx.model_name || '—'}
                  </TableCell>
                  <TableCell>
                    <Badge color="gray">{idx.distance_metric || 'cosine'}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-gray-500">
                    {formatDate(idx.created_time)}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button
                        size="xs"
                        color="light"
                        onClick={() => navigate(`/space/${selectedSpace}/vector-indexes/${idx.index_name}`)}
                        title="View"
                      >
                        <HiEye className="h-4 w-4" />
                      </Button>
                      <Button
                        size="xs"
                        color="light"
                        onClick={() => handleReindex(idx.index_name)}
                        disabled={reindexing === idx.index_name}
                      >
                        {reindexing === idx.index_name ? (
                          <Spinner size="xs" />
                        ) : (
                          <HiRefresh className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        size="xs"
                        color="failure"
                        onClick={() => setDeleteTarget(idx.index_name)}
                      >
                        <HiTrash className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}


      {/* Delete Confirmation Modal */}
      <Modal show={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="md">
        <ModalHeader>Delete Vector Index</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500 flex-shrink-0" />
            <div>
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete index <strong>{deleteTarget}</strong>?
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
          <Button color="gray" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default VectorIndexes;
