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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  TextInput,
} from 'flowbite-react';
import { HiTrash, HiRefresh, HiExclamation, HiHome, HiChartBar, HiEye } from 'react-icons/hi';
import { searchFtsService } from '../services/SearchFtsService';
import { apiService } from '../services/ApiService';
import type { FtsIndex, FtsIndexStats } from '../types/searchFts';
import { type SpaceInfo } from '../types/api';
import { formatDateShort } from '../utils/formatUtils';

const FtsIndexes: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();
  const navigate = useNavigate();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [indexes, setIndexes] = useState<FtsIndex[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);

  // Delete modal state
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Stats state
  const [statsTarget, setStatsTarget] = useState<string | null>(null);
  const [stats, setStats] = useState<FtsIndexStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // Populate state
  const [populateTarget, setPopulateTarget] = useState<string | null>(null);
  const [populateResult, setPopulateResult] = useState<string | null>(null);
  const [populating, setPopulating] = useState(false);
  const [populateForm, setPopulateForm] = useState({
    graph_uri: '',
    mapping_type: '',
    batch_size: 100,
  });

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
      const data = await searchFtsService.getFtsIndexes(selectedSpace);
      setIndexes(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load FTS indexes');
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
      await searchFtsService.deleteFtsIndex(selectedSpace, deleteTarget);
      setDeleteTarget(null);
      loadIndexes();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete FTS index');
    } finally {
      setDeleting(false);
    }
  };

  const handleShowStats = async (indexName: string) => {
    if (!selectedSpace) return;
    setStatsTarget(indexName);
    setStatsLoading(true);
    try {
      const data = await searchFtsService.getFtsStats(selectedSpace, indexName);
      setStats(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load stats');
      setStatsTarget(null);
    } finally {
      setStatsLoading(false);
    }
  };

  const handlePopulate = async () => {
    if (!selectedSpace || !populateTarget || !populateForm.graph_uri.trim()) return;
    setPopulating(true);
    setPopulateResult(null);
    try {
      const result = await searchFtsService.populateFts(selectedSpace, populateTarget, {
        graph_uri: populateForm.graph_uri.trim(),
        mapping_type: populateForm.mapping_type || undefined,
        batch_size: populateForm.batch_size,
      });
      setPopulateResult(
        result.message || `FTS population started for "${populateTarget}"`
      );
      setPopulateTarget(null);
      loadIndexes();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to populate FTS index');
    } finally {
      setPopulating(false);
    }
  };

  const formatDate = formatDateShort;

  return (
    <div data-testid="fts-indexes-page">
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>FTS Indexes</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">FTS Indexes</h1>
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

      {populateResult && (
        <Alert color="success" className="mb-4" onDismiss={() => setPopulateResult(null)}>
          {populateResult}
        </Alert>
      )}

      {/* Index table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : indexes.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="text-lg mb-2">No FTS indexes found</p>
          <p className="text-sm">
            {selectedSpace
              ? 'Create an FTS index to enable full-text search.'
              : 'Select a space to view FTS indexes.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table hoverable>
            <TableHead>
              <TableRow>
                <TableHeadCell>Index Name</TableHeadCell>
                <TableHeadCell>Languages</TableHeadCell>
                <TableHeadCell>Rows</TableHeadCell>
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
                    <div className="flex flex-wrap gap-1">
                      {idx.languages.map((lang) => (
                        <Badge key={lang} color="info" size="xs">
                          {lang}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-gray-500">
                    {idx.row_count ?? '—'}
                  </TableCell>
                  <TableCell className="text-sm text-gray-500">
                    {formatDate(idx.created_time ?? undefined)}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button
                        size="xs"
                        color="light"
                        onClick={() => navigate(`/space/${selectedSpace}/fts-indexes/${idx.index_name}`)}
                        title="View"
                      >
                        <HiEye className="h-4 w-4" />
                      </Button>
                      <Button
                        size="xs"
                        color="light"
                        onClick={() => handleShowStats(idx.index_name)}
                        title="Stats"
                      >
                        <HiChartBar className="h-4 w-4" />
                      </Button>
                      <Button
                        size="xs"
                        color="light"
                        onClick={() => {
                          setPopulateTarget(idx.index_name);
                          setPopulateForm({ graph_uri: '', mapping_type: '', batch_size: 100 });
                        }}
                        title="Populate"
                      >
                        <HiRefresh className="h-4 w-4" />
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


      {/* Stats Modal */}
      <Modal show={!!statsTarget} onClose={() => { setStatsTarget(null); setStats(null); }} size="md">
        <ModalHeader>FTS Index Stats — {statsTarget}</ModalHeader>
        <ModalBody>
          {statsLoading ? (
            <div className="flex justify-center py-8"><Spinner size="lg" /></div>
          ) : stats ? (
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Total rows:</span>
                <span className="font-medium">{stats.row_count.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Distinct entities:</span>
                <span className="font-medium">{stats.distinct_entity_count.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Rows with tsvector:</span>
                <span className="font-medium">{stats.has_tsv_count.toLocaleString()}</span>
              </div>
            </div>
          ) : (
            <p className="text-gray-500">No stats available.</p>
          )}
        </ModalBody>
        <ModalFooter>
          <Button color="gray" onClick={() => { setStatsTarget(null); setStats(null); }}>
            Close
          </Button>
        </ModalFooter>
      </Modal>

      {/* Populate Modal */}
      <Modal show={!!populateTarget} onClose={() => setPopulateTarget(null)}>
        <ModalHeader>Populate FTS Index — {populateTarget}</ModalHeader>
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
          <Button color="gray" onClick={() => setPopulateTarget(null)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="md">
        <ModalHeader>Delete FTS Index</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500 flex-shrink-0" />
            <div>
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete index <strong>{deleteTarget}</strong>?
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
          <Button color="gray" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default FtsIndexes;
