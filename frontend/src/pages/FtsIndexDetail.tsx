import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Alert,
  Badge,
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Label,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Select,
  Spinner,
  TextInput,
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiHome,
  HiRefresh,
  HiTrash,
  HiExclamation,
} from 'react-icons/hi';
import { searchFtsService } from '../services/SearchFtsService';
import type { FtsIndex, FtsIndexStats } from '../types/searchFts';
import { formatDateShort } from '../utils/formatUtils';

const FtsIndexDetail: React.FC = () => {
  const { spaceId, indexName } = useParams<{ spaceId: string; indexName: string }>();
  const navigate = useNavigate();

  const [index, setIndex] = useState<FtsIndex | null>(null);
  const [stats, setStats] = useState<FtsIndexStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Populate
  const [showPopulate, setShowPopulate] = useState(false);
  const [populating, setPopulating] = useState(false);
  const [populateForm, setPopulateForm] = useState({
    graph_uri: '',
    mapping_type: '',
    batch_size: 100,
  });

  // Delete
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadIndex = useCallback(async () => {
    if (!spaceId || !indexName) return;
    setLoading(true);
    try {
      const indexes = await searchFtsService.getFtsIndexes(spaceId);
      const found = indexes.find((i) => i.index_name === indexName);
      if (found) {
        setIndex(found);
      } else {
        setError('FTS index not found');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load FTS index');
    } finally {
      setLoading(false);
    }
  }, [spaceId, indexName]);

  const loadStats = useCallback(async () => {
    if (!spaceId || !indexName) return;
    try {
      const data = await searchFtsService.getFtsStats(spaceId, indexName);
      setStats(data);
    } catch {
      // stats may not be available
    }
  }, [spaceId, indexName]);

  useEffect(() => {
    loadIndex();
    loadStats();
  }, [loadIndex, loadStats]);

  const handlePopulate = async () => {
    if (!spaceId || !indexName || !populateForm.graph_uri.trim()) return;
    setPopulating(true);
    try {
      const result = await searchFtsService.populateFts(spaceId, indexName, {
        graph_uri: populateForm.graph_uri.trim(),
        mapping_type: populateForm.mapping_type || undefined,
        batch_size: populateForm.batch_size,
      });
      setSuccess(result.message || `Populated ${result.rows_populated} rows in ${result.elapsed_seconds.toFixed(1)}s`);
      setShowPopulate(false);
      loadIndex();
      loadStats();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to populate FTS index');
    } finally {
      setPopulating(false);
    }
  };

  const handleDelete = async () => {
    if (!spaceId || !indexName) return;
    setDeleting(true);
    try {
      await searchFtsService.deleteFtsIndex(spaceId, indexName);
      navigate('/fts-indexes');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete FTS index');
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
        FTS index not found
      </Alert>
    );
  }

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/fts-indexes">FTS Indexes</BreadcrumbItem>
        <BreadcrumbItem>{index.index_name}</BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Button size="sm" color="light" onClick={() => navigate('/fts-indexes')}>
          <HiArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {index.index_name}
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <Badge color="info">fts</Badge>
            {index.languages.map((lang) => (
              <Badge key={lang} color="gray" size="xs">{lang}</Badge>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" color="light" onClick={() => setShowPopulate(true)}>
            <HiRefresh className="mr-2 h-4 w-4" />
            Populate
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
              <dt className="text-gray-500 dark:text-gray-400">Languages</dt>
              <dd className="flex gap-1">
                {index.languages.map((lang) => (
                  <Badge key={lang} color="info" size="xs">{lang}</Badge>
                ))}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Created</dt>
              <dd className="text-gray-900 dark:text-white">
                {formatDateShort(index.created_time ?? undefined)}
              </dd>
            </div>
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
                {stats ? stats.row_count.toLocaleString() : (index.row_count?.toLocaleString() ?? '—')}
              </dd>
            </div>
            {stats && (
              <>
                <div className="flex justify-between">
                  <dt className="text-gray-500 dark:text-gray-400">Distinct Entities</dt>
                  <dd className="text-gray-900 dark:text-white">{stats.distinct_entity_count.toLocaleString()}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500 dark:text-gray-400">Rows with tsvector</dt>
                  <dd className="text-gray-900 dark:text-white">{stats.has_tsv_count.toLocaleString()}</dd>
                </div>
              </>
            )}
          </dl>
        </div>
      </div>

      {/* Populate Modal */}
      <Modal show={showPopulate} onClose={() => setShowPopulate(false)}>
        <ModalHeader>Populate FTS Index — {index.index_name}</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="pop-graph">Graph URI</Label>
              <TextInput
                id="pop-graph"
                placeholder="e.g. urn:graph:default"
                value={populateForm.graph_uri}
                onChange={(e) => setPopulateForm({ ...populateForm, graph_uri: e.target.value })}
                required
              />
            </div>
            <div>
              <Label htmlFor="pop-type">Mapping Type (optional)</Label>
              <Select
                id="pop-type"
                value={populateForm.mapping_type}
                onChange={(e) => setPopulateForm({ ...populateForm, mapping_type: e.target.value })}
              >
                <option value="">All types</option>
                <option value="kgentity">KG Entity</option>
                <option value="kgdocument">KG Document</option>
                <option value="kgframe">KG Frame</option>
                <option value="kgslot">KG Slot</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="pop-batch">Batch Size</Label>
              <TextInput
                id="pop-batch"
                type="number"
                min={1}
                max={1000}
                value={populateForm.batch_size}
                onChange={(e) => setPopulateForm({ ...populateForm, batch_size: parseInt(e.target.value) || 100 })}
              />
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={handlePopulate} disabled={populating || !populateForm.graph_uri.trim()}>
            {populating ? <Spinner size="sm" className="mr-2" /> : null}
            Populate
          </Button>
          <Button color="gray" onClick={() => setShowPopulate(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={showDelete} onClose={() => setShowDelete(false)} size="md">
        <ModalHeader>Delete FTS Index</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500 flex-shrink-0" />
            <div>
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete index <strong>{index.index_name}</strong>?
              </p>
              <p className="text-sm text-gray-500 mt-1">
                This will permanently delete the FTS data table and all indexed text. This action cannot be undone.
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

export default FtsIndexDetail;
