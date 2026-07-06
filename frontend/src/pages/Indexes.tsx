import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { HiPlus, HiTrash, HiRefresh, HiEye, HiExclamation, HiHome } from 'react-icons/hi';
import { vectorGeoService } from '../services/VectorGeoService';
import { searchFtsService } from '../services/SearchFtsService';
import { fuzzyMappingService } from '../services/FuzzyMappingService';
import { apiService } from '../services/ApiService';
import type { VectorIndex } from '../types/vectorGeo';
import type { FtsIndex } from '../types/searchFts';
import type { FuzzyMapping } from '../types/fuzzyMappings';
import { type SpaceInfo } from '../types/api';

type IndexType = 'vector' | 'fts' | 'fuzzy';

interface UnifiedIndex {
  name: string;
  type: IndexType;
  details: string;
  documentCount?: number;
  status?: string;
  // Original refs
  vectorIndex?: VectorIndex;
  ftsIndex?: FtsIndex;
  fuzzyMappingIds?: number[];
}

const TYPE_COLORS: Record<IndexType, string> = {
  vector: 'blue',
  fts: 'green',
  fuzzy: 'purple',
};

const Indexes: React.FC = () => {
  const navigate = useNavigate();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>('');
  const [indexes, setIndexes] = useState<UnifiedIndex[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);

  // Filters
  const [filterType, setFilterType] = useState<string>('');

  // Create modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createType, setCreateType] = useState<IndexType>('vector');
  const [createForm, setCreateForm] = useState({
    index_name: '',
    dimensions: 384,
    distance_metric: 'cosine',
    provider: '',
    model: '',
  });
  const [creating, setCreating] = useState(false);

  // Delete modal
  const [deleteTarget, setDeleteTarget] = useState<UnifiedIndex | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Rebuild
  const [rebuilding, setRebuilding] = useState<string | null>(null);

  // Load spaces (including registry pseudo-spaces)
  useEffect(() => {
    const loadSpaces = async () => {
      try {
        const spacesData = await apiService.getSpaces();
        const registrySpaces: SpaceInfo[] = [
          { space: 'entity_registry', space_name: 'Entity Registry', created_time: '', updated_time: '' },
          { space: 'agent_registry', space_name: 'Agent Registry', created_time: '', updated_time: '' },
        ];
        const allSpaces = [...spacesData, ...registrySpaces];
        setSpaces(allSpaces);
        if (allSpaces.length > 0) {
          setSelectedSpace(allSpaces[0].space);
        }
      } catch {
        setError('Failed to load spaces');
      } finally {
        setSpacesLoading(false);
      }
    };
    loadSpaces();
  }, []);

  // Load indexes
  const loadData = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const [vectorIndexes, ftsIndexes, fuzzyMappings] = await Promise.all([
        vectorGeoService.getVectorIndexes(selectedSpace),
        searchFtsService.getFtsIndexes(selectedSpace),
        fuzzyMappingService.getFuzzyMappings(selectedSpace),
      ]);

      const unified: UnifiedIndex[] = [];

      for (const vi of vectorIndexes) {
        unified.push({
          name: vi.index_name,
          type: 'vector',
          details: `${vi.dimensions}d (${vi.distance_metric || 'cosine'})`,
          documentCount: vi.row_count,
          status: vi.row_count != null ? 'active' : 'unknown',
          vectorIndex: vi,
        });
      }

      for (const fi of ftsIndexes) {
        unified.push({
          name: fi.index_name,
          type: 'fts',
          details: fi.languages?.join(', ') || 'english',
          documentCount: fi.row_count,
          status: 'active',
          ftsIndex: fi,
        });
      }

      // Group fuzzy mappings by index_name to show as fuzzy indexes
      const fuzzyByIndex = new Map<string, FuzzyMapping[]>();
      for (const fm of fuzzyMappings) {
        const group = fuzzyByIndex.get(fm.index_name) || [];
        group.push(fm);
        fuzzyByIndex.set(fm.index_name, group);
      }
      for (const [indexName, fmGroup] of fuzzyByIndex) {
        const mappingCount = fmGroup.length;
        const types = [...new Set(fmGroup.map((m) => m.mapping_type))].join(', ');
        unified.push({
          name: indexName,
          type: 'fuzzy',
          details: `${mappingCount} mapping${mappingCount > 1 ? 's' : ''} (${types})`,
          documentCount: undefined,
          status: fmGroup.some((m) => m.enabled) ? 'active' : 'disabled',
          fuzzyMappingIds: fmGroup.map((m) => m.mapping_id),
        });
      }

      const filtered = filterType
        ? unified.filter((idx) => idx.type === filterType)
        : unified;

      setIndexes(filtered);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load indexes');
      setIndexes([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, filterType]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Navigate to detail
  const handleViewDetail = (idx: UnifiedIndex) => {
    if (idx.type === 'vector') {
      navigate(`/space/${selectedSpace}/indexes/vector/${idx.name}`);
    } else if (idx.type === 'fts') {
      navigate(`/space/${selectedSpace}/indexes/fts/${idx.name}`);
    } else if (idx.type === 'fuzzy' && idx.fuzzyMappingIds?.length) {
      navigate(`/space/${selectedSpace}/fuzzy-mappings/${idx.fuzzyMappingIds[0]}`);
    }
  };

  // Rebuild/reindex
  const handleRebuild = async (idx: UnifiedIndex) => {
    if (!selectedSpace) return;
    setRebuilding(idx.name);
    try {
      if (idx.type === 'vector') {
        await vectorGeoService.reindex(selectedSpace, idx.name);
      } else if (idx.type === 'fts') {
        await searchFtsService.populateFts(selectedSpace, idx.name, { graph_uri: '' });
      } else if (idx.type === 'fuzzy' && idx.fuzzyMappingIds?.length) {
        await Promise.all(
          idx.fuzzyMappingIds.map((mid) => fuzzyMappingService.populate(selectedSpace, mid))
        );
      }
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Rebuild failed');
    } finally {
      setRebuilding(null);
    }
  };

  // Create
  const handleCreate = async () => {
    if (!selectedSpace || !createForm.index_name) return;
    setCreating(true);
    try {
      if (createType === 'vector') {
        await vectorGeoService.createVectorIndex(selectedSpace, {
          index_name: createForm.index_name,
          dimensions: createForm.dimensions,
          distance_metric: createForm.distance_metric,
          provider: createForm.provider || 'default',
        });
      } else if (createType === 'fts') {
        await searchFtsService.createFtsIndex(selectedSpace, {
          index_name: createForm.index_name,
        });
      }
      setShowCreateModal(false);
      setCreateForm({ index_name: '', dimensions: 384, distance_metric: 'cosine', provider: '', model: '' });
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create index');
    } finally {
      setCreating(false);
    }
  };

  // Delete
  const handleDelete = async () => {
    if (!selectedSpace || !deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.type === 'vector') {
        await vectorGeoService.deleteVectorIndex(selectedSpace, deleteTarget.name);
      } else if (deleteTarget.type === 'fts') {
        await searchFtsService.deleteFtsIndex(selectedSpace, deleteTarget.name);
      }
      setDeleteTarget(null);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete index');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div data-testid="indexes-page">
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Indexes</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Indexes</h1>
        <Button size="sm" color="blue" onClick={() => setShowCreateModal(true)}>
          <HiPlus className="mr-1 h-4 w-4" />
          Create Index
        </Button>
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Filters */}
      <div className="flex gap-4 mb-4 items-end">
        <div className="w-48">
          <Label htmlFor="space">Space</Label>
          {spacesLoading ? (
            <Spinner size="sm" />
          ) : (
            <Select id="space" value={selectedSpace} onChange={(e) => setSelectedSpace(e.target.value)}>
              {spaces.map((s) => (
                <option key={s.space} value={s.space}>{s.space_name || s.space}</option>
              ))}
            </Select>
          )}
        </div>
        <div className="w-40">
          <Label htmlFor="filterType">Type</Label>
          <Select id="filterType" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All</option>
            <option value="vector">Vector</option>
            <option value="fts">FTS</option>
            <option value="fuzzy">Fuzzy</option>
          </Select>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : indexes.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          No indexes found for this space.
        </div>
      ) : (
        <Table striped>
          <TableHead>
            <TableRow>
              <TableHeadCell>Index Name</TableHeadCell>
              <TableHeadCell>Type</TableHeadCell>
              <TableHeadCell>Details</TableHeadCell>
              <TableHeadCell>Documents</TableHeadCell>
              <TableHeadCell>Actions</TableHeadCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {indexes.map((idx) => (
              <TableRow key={`${idx.type}-${idx.name}`} className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700">
                <TableCell className="font-medium" onClick={() => handleViewDetail(idx)}>
                  {idx.name}
                </TableCell>
                <TableCell onClick={() => handleViewDetail(idx)}>
                  <Badge color={TYPE_COLORS[idx.type]}>{idx.type.toUpperCase()}</Badge>
                </TableCell>
                <TableCell onClick={() => handleViewDetail(idx)}>
                  {idx.details}
                </TableCell>
                <TableCell onClick={() => handleViewDetail(idx)}>
                  {idx.documentCount?.toLocaleString() ?? '—'}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button size="xs" color="gray" onClick={() => handleViewDetail(idx)}>
                      <HiEye className="h-3 w-3" />
                    </Button>
                    <Button
                      size="xs"
                      color="gray"
                      onClick={() => handleRebuild(idx)}
                      disabled={rebuilding === idx.name}
                    >
                      {rebuilding === idx.name ? (
                        <Spinner size="xs" />
                      ) : (
                        <HiRefresh className="h-3 w-3" />
                      )}
                    </Button>
                    <Button size="xs" color="failure" onClick={() => setDeleteTarget(idx)}>
                      <HiTrash className="h-3 w-3" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* Create Modal */}
      <Modal show={showCreateModal} onClose={() => setShowCreateModal(false)}>
        <ModalHeader>Create Index</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="createType">Index Type</Label>
              <Select
                id="createType"
                value={createType}
                onChange={(e) => setCreateType(e.target.value as IndexType)}
              >
                <option value="vector">Vector</option>
                <option value="fts">FTS</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="createName">Index Name</Label>
              <TextInput
                id="createName"
                value={createForm.index_name}
                onChange={(e) => setCreateForm({ ...createForm, index_name: e.target.value })}
                placeholder="e.g. entity_default"
              />
            </div>

            {/* Vector-specific fields */}
            {createType === 'vector' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="dimensions">Dimensions</Label>
                    <TextInput
                      id="dimensions"
                      type="number"
                      value={createForm.dimensions}
                      onChange={(e) => setCreateForm({ ...createForm, dimensions: parseInt(e.target.value) || 384 })}
                    />
                  </div>
                  <div>
                    <Label htmlFor="distanceMetric">Distance Metric</Label>
                    <Select
                      id="distanceMetric"
                      value={createForm.distance_metric}
                      onChange={(e) => setCreateForm({ ...createForm, distance_metric: e.target.value })}
                    >
                      <option value="cosine">Cosine</option>
                      <option value="l2">L2 (Euclidean)</option>
                      <option value="inner_product">Inner Product</option>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label htmlFor="provider">Provider (optional)</Label>
                  <TextInput
                    id="provider"
                    value={createForm.provider}
                    onChange={(e) => setCreateForm({ ...createForm, provider: e.target.value })}
                    placeholder="e.g. openai"
                  />
                </div>
                <div>
                  <Label htmlFor="model">Model (optional)</Label>
                  <TextInput
                    id="model"
                    value={createForm.model}
                    onChange={(e) => setCreateForm({ ...createForm, model: e.target.value })}
                    placeholder="e.g. text-embedding-3-small"
                  />
                </div>
              </>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="blue" onClick={handleCreate} disabled={creating || !createForm.index_name}>
            {creating ? <Spinner size="sm" className="mr-2" /> : null}
            Create
          </Button>
          <Button color="gray" onClick={() => setShowCreateModal(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="md">
        <ModalHeader>Delete Index</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500" />
            <p>
              Are you sure you want to delete index <strong>{deleteTarget?.name}</strong>?
              All indexed data will be lost. This action cannot be undone.
            </p>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="failure" onClick={handleDelete} disabled={deleting}>
            {deleting ? <Spinner size="sm" className="mr-2" /> : null}
            Delete
          </Button>
          <Button color="gray" onClick={() => setDeleteTarget(null)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default Indexes;
