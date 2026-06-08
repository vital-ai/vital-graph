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
  ToggleSwitch,
} from 'flowbite-react';
import { HiPlus, HiTrash, HiEye, HiExclamation, HiHome } from 'react-icons/hi';
import { vectorGeoService } from '../services/VectorGeoService';
import { apiService } from '../services/ApiService';
import type { VectorMapping, VectorIndex, MappingType, SourceType } from '../types/vectorGeo';
import { type SpaceInfo } from '../types/api';

const MAPPING_TYPE_COLORS: Record<MappingType, string> = {
  kgentity: 'info',
  kgdocument: 'purple',
  kgframe: 'success',
  kgslot: 'warning',
};

const VectorMappings: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();
  const navigate = useNavigate();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [mappings, setMappings] = useState<VectorMapping[]>([]);
  const [indexes, setIndexes] = useState<VectorIndex[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);

  // Filters
  const [filterIndex, setFilterIndex] = useState<string>('');
  const [filterType, setFilterType] = useState<string>('');

  // Create modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState({
    mapping_type: 'kgentity' as MappingType,
    type_uri: '',
    index_name: '',
    enabled: true,
    source_type: 'default' as SourceType,
    separator: ' ',
    include_pred_name: false,
    include_type_desc: false,
  });
  const [creating, setCreating] = useState(false);

  // Delete modal state
  const [deleteTarget, setDeleteTarget] = useState<VectorMapping | null>(null);
  const [deleting, setDeleting] = useState(false);

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

  // Load mappings and indexes when space changes
  const loadData = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const [mappingsData, indexesData] = await Promise.all([
        vectorGeoService.getVectorMappings(selectedSpace, {
          index_name: filterIndex || undefined,
          mapping_type: filterType || undefined,
        }),
        vectorGeoService.getVectorIndexes(selectedSpace),
      ]);
      setMappings(mappingsData);
      setIndexes(indexesData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
      setMappings([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, filterIndex, filterType]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handlers
  const handleSpaceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedSpace(e.target.value);
  };

  const handleToggleEnabled = async (mapping: VectorMapping) => {
    if (!selectedSpace) return;
    try {
      await vectorGeoService.updateVectorMapping(selectedSpace, mapping.mapping_id, {
        enabled: !mapping.enabled,
      });
      // Optimistic update
      setMappings((prev) =>
        prev.map((m) =>
          m.mapping_id === mapping.mapping_id ? { ...m, enabled: !m.enabled } : m
        )
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to toggle mapping');
      loadData(); // Revert on failure
    }
  };

  const handleCreate = async () => {
    if (!selectedSpace || !createForm.index_name) return;
    setCreating(true);
    try {
      await vectorGeoService.createVectorMapping(selectedSpace, {
        mapping_type: createForm.mapping_type,
        type_uri: createForm.type_uri || undefined,
        index_name: createForm.index_name,
        enabled: createForm.enabled,
        source_type: createForm.source_type,
        separator: createForm.separator,
        include_pred_name: createForm.include_pred_name,
        include_type_desc: createForm.include_type_desc,
      });
      setShowCreateModal(false);
      setCreateForm({
        mapping_type: 'kgentity',
        type_uri: '',
        index_name: '',
        enabled: true,
        source_type: 'default',
        separator: ' ',
        include_pred_name: false,
        include_type_desc: false,
      });
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create mapping');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedSpace || !deleteTarget) return;
    setDeleting(true);
    try {
      await vectorGeoService.deleteVectorMapping(selectedSpace, deleteTarget.mapping_id);
      setDeleteTarget(null);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete mapping');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div>
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Vector Mappings</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Vector Mappings</h1>
        <Button size="sm" onClick={() => setShowCreateModal(true)} disabled={!selectedSpace || indexes.length === 0}>
          <HiPlus className="mr-2 h-4 w-4" />
          Create Mapping
        </Button>
      </div>

      {/* Space selector + filters */}
      <div className="flex flex-wrap gap-4 mb-4">
        {!spaceId && (
          <div className="min-w-48">
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
        <div className="min-w-40">
          <Label htmlFor="filter-index">Index</Label>
          <Select id="filter-index" value={filterIndex} onChange={(e) => setFilterIndex(e.target.value)}>
            <option value="">All indexes</option>
            {indexes.map((idx) => (
              <option key={idx.index_name} value={idx.index_name}>
                {idx.index_name}
              </option>
            ))}
          </Select>
        </div>
        <div className="min-w-40">
          <Label htmlFor="filter-type">Type</Label>
          <Select id="filter-type" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All types</option>
            <option value="kgentity">KG Entity</option>
            <option value="kgdocument">KG Document</option>
            <option value="kgframe">KG Frame</option>
            <option value="kgslot">KG Slot</option>
          </Select>
        </div>
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Mappings table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : mappings.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="text-lg mb-2">No vector mappings found</p>
          <p className="text-sm">
            {selectedSpace
              ? indexes.length === 0
                ? 'Create a vector index first, then add mappings.'
                : 'Create a mapping to configure how entities are vectorized.'
              : 'Select a space to view vector mappings.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table hoverable>
            <TableHead>
              <TableHeadCell>Type</TableHeadCell>
              <TableHeadCell>Type URI</TableHeadCell>
              <TableHeadCell>Index</TableHeadCell>
              <TableHeadCell>Source</TableHeadCell>
              <TableHeadCell>Enabled</TableHeadCell>
              <TableHeadCell>Properties</TableHeadCell>
              <TableHeadCell>Actions</TableHeadCell>
            </TableHead>
            <TableBody className="divide-y">
              {mappings.map((mapping) => (
                <TableRow key={mapping.mapping_id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                  <TableCell>
                    <Badge color={MAPPING_TYPE_COLORS[mapping.mapping_type] || 'gray'}>
                      {mapping.mapping_type}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-gray-600 dark:text-gray-400 max-w-48 truncate">
                    {mapping.type_uri || '(all)'}
                  </TableCell>
                  <TableCell>
                    <Badge color="gray">{mapping.index_name}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">{mapping.source_type}</TableCell>
                  <TableCell>
                    <ToggleSwitch
                      checked={mapping.enabled}
                      onChange={() => handleToggleEnabled(mapping)}
                    />
                  </TableCell>
                  <TableCell className="text-sm text-gray-500">
                    {mapping.properties?.length || 0}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button size="xs" color="light" onClick={() => navigate(`/space/${selectedSpace}/vector-mappings/${mapping.mapping_id}`)}>
                        <HiEye className="h-4 w-4" />
                      </Button>
                      <Button size="xs" color="failure" onClick={() => setDeleteTarget(mapping)}>
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

      {/* Create Modal */}
      <Modal show={showCreateModal} onClose={() => setShowCreateModal(false)}>
        <ModalHeader>Create Vector Mapping</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="map-type">Mapping Type</Label>
              <Select
                id="map-type"
                value={createForm.mapping_type}
                onChange={(e) => setCreateForm({ ...createForm, mapping_type: e.target.value as MappingType })}
              >
                <option value="kgentity">KG Entity</option>
                <option value="kgdocument">KG Document</option>
                <option value="kgframe">KG Frame</option>
                <option value="kgslot">KG Slot</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="map-type-uri">Type URI (optional — leave empty for all)</Label>
              <TextInput
                id="map-type-uri"
                placeholder="e.g. http://vital.ai/ontology/vital-aimp#Person"
                value={createForm.type_uri}
                onChange={(e) => setCreateForm({ ...createForm, type_uri: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="map-index">Target Index</Label>
              <Select
                id="map-index"
                value={createForm.index_name}
                onChange={(e) => setCreateForm({ ...createForm, index_name: e.target.value })}
              >
                <option value="">Select an index...</option>
                {indexes.map((idx) => (
                  <option key={idx.index_name} value={idx.index_name}>
                    {idx.index_name} ({idx.dimensions}d, {idx.provider})
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="map-source">Source Type</Label>
              <Select
                id="map-source"
                value={createForm.source_type}
                onChange={(e) => setCreateForm({ ...createForm, source_type: e.target.value as SourceType })}
              >
                <option value="default">Default (all string properties)</option>
                <option value="properties">Properties (specific URIs)</option>
                <option value="slots">Slots (slot content)</option>
              </Select>
            </div>
            <div className="flex items-center gap-4">
              <ToggleSwitch
                checked={createForm.enabled}
                onChange={(val) => setCreateForm({ ...createForm, enabled: val })}
                label="Enabled"
              />
            </div>
            <div className="flex items-center gap-4">
              <ToggleSwitch
                checked={createForm.include_pred_name}
                onChange={(val) => setCreateForm({ ...createForm, include_pred_name: val })}
                label="Include predicate names"
              />
            </div>
            <div className="flex items-center gap-4">
              <ToggleSwitch
                checked={createForm.include_type_desc}
                onChange={(val) => setCreateForm({ ...createForm, include_type_desc: val })}
                label="Include type description"
              />
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={handleCreate} disabled={creating || !createForm.index_name}>
            {creating ? <Spinner size="sm" className="mr-2" /> : null}
            Create
          </Button>
          <Button color="gray" onClick={() => setShowCreateModal(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="md">
        <ModalHeader>Delete Vector Mapping</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500 flex-shrink-0" />
            <div>
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete this mapping?
              </p>
              <p className="text-sm text-gray-500 mt-1">
                {deleteTarget?.mapping_type} → {deleteTarget?.index_name}
                {deleteTarget?.type_uri && ` (${deleteTarget.type_uri})`}
              </p>
              <p className="text-sm text-red-500 mt-1">
                All associated mapping properties will also be deleted (CASCADE).
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

export default VectorMappings;
