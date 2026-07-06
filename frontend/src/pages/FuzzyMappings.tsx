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
import { fuzzyMappingService } from '../services/FuzzyMappingService';
import { apiService } from '../services/ApiService';
import type { FuzzyMapping, FuzzyMappingType } from '../types/fuzzyMappings';
import { type SpaceInfo } from '../types/api';

const MAPPING_TYPE_COLORS: Record<FuzzyMappingType, string> = {
  kgentity: 'info',
  kgdocument: 'purple',
  kgframe: 'success',
  kgslot: 'warning',
};

const FuzzyMappings: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();
  const navigate = useNavigate();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [mappings, setMappings] = useState<FuzzyMapping[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);

  // Filters
  const [filterType, setFilterType] = useState<string>('');

  // Create modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState({
    mapping_type: 'kgentity' as FuzzyMappingType,
    type_uri: '',
    index_name: '',
    enabled: true,
    shingle_k: 3,
    num_perm: 64,
    lsh_threshold: 0.3,
    phonetic_bonus: 10.0,
  });
  const [creating, setCreating] = useState(false);

  // Delete modal state
  const [deleteTarget, setDeleteTarget] = useState<FuzzyMapping | null>(null);
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

  // Load mappings when space changes
  const loadData = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const mappingsData = await fuzzyMappingService.getFuzzyMappings(selectedSpace, {
        mapping_type: filterType || undefined,
      });
      setMappings(mappingsData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load fuzzy mappings');
      setMappings([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, filterType]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handlers
  const handleSpaceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedSpace(e.target.value);
  };

  const handleToggleEnabled = async (mapping: FuzzyMapping) => {
    if (!selectedSpace) return;
    try {
      await fuzzyMappingService.updateFuzzyMapping(selectedSpace, mapping.mapping_id, {
        enabled: !mapping.enabled,
      });
      setMappings((prev) =>
        prev.map((m) =>
          m.mapping_id === mapping.mapping_id ? { ...m, enabled: !m.enabled } : m
        )
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to toggle mapping');
      loadData();
    }
  };

  const handleCreate = async () => {
    if (!selectedSpace || !createForm.index_name) return;
    setCreating(true);
    try {
      await fuzzyMappingService.createFuzzyMapping(selectedSpace, {
        mapping_type: createForm.mapping_type,
        type_uri: createForm.type_uri || undefined,
        index_name: createForm.index_name,
        enabled: createForm.enabled,
        shingle_k: createForm.shingle_k,
        num_perm: createForm.num_perm,
        lsh_threshold: createForm.lsh_threshold,
        phonetic_bonus: createForm.phonetic_bonus,
      });
      setShowCreateModal(false);
      setCreateForm({
        mapping_type: 'kgentity',
        type_uri: '',
        index_name: '',
        enabled: true,
        shingle_k: 3,
        num_perm: 64,
        lsh_threshold: 0.3,
        phonetic_bonus: 10.0,
      });
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create fuzzy mapping');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedSpace || !deleteTarget) return;
    setDeleting(true);
    try {
      await fuzzyMappingService.deleteFuzzyMapping(selectedSpace, deleteTarget.mapping_id);
      setDeleteTarget(null);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to delete fuzzy mapping');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div data-testid="fuzzy-mappings-page">
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Fuzzy Mappings</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Fuzzy Mappings</h1>
        <Button size="sm" onClick={() => setShowCreateModal(true)} disabled={!selectedSpace}>
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
          <p className="text-lg mb-2">No fuzzy mappings found</p>
          <p className="text-sm">
            {selectedSpace
              ? 'Create a mapping to configure how entities are indexed for fuzzy search.'
              : 'Select a space to view fuzzy mappings.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table hoverable>
            <TableHead>
              <TableHeadCell>Type</TableHeadCell>
              <TableHeadCell>Type URI</TableHeadCell>
              <TableHeadCell>Index Name</TableHeadCell>
              <TableHeadCell>Shingle K</TableHeadCell>
              <TableHeadCell>Threshold</TableHeadCell>
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
                  <TableCell className="text-sm">{mapping.shingle_k}</TableCell>
                  <TableCell className="text-sm">{mapping.lsh_threshold}</TableCell>
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
                      <Button size="xs" color="light" onClick={() => navigate(`/space/${selectedSpace}/fuzzy-mappings/${mapping.mapping_id}`)}>
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
        <ModalHeader>Create Fuzzy Mapping</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="map-type">Mapping Type</Label>
              <Select
                id="map-type"
                value={createForm.mapping_type}
                onChange={(e) => setCreateForm({ ...createForm, mapping_type: e.target.value as FuzzyMappingType })}
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
              <Label htmlFor="map-index-name">Index Name</Label>
              <TextInput
                id="map-index-name"
                placeholder="e.g. entity_default"
                value={createForm.index_name}
                onChange={(e) => setCreateForm({ ...createForm, index_name: e.target.value })}
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="map-shingle-k">Shingle K</Label>
                <TextInput
                  id="map-shingle-k"
                  type="number"
                  min={2}
                  max={10}
                  value={createForm.shingle_k}
                  onChange={(e) => setCreateForm({ ...createForm, shingle_k: parseInt(e.target.value) || 3 })}
                />
              </div>
              <div>
                <Label htmlFor="map-num-perm">Num Permutations</Label>
                <TextInput
                  id="map-num-perm"
                  type="number"
                  min={16}
                  max={256}
                  value={createForm.num_perm}
                  onChange={(e) => setCreateForm({ ...createForm, num_perm: parseInt(e.target.value) || 64 })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="map-threshold">LSH Threshold</Label>
                <TextInput
                  id="map-threshold"
                  type="number"
                  min={0.1}
                  max={1.0}
                  step={0.05}
                  value={createForm.lsh_threshold}
                  onChange={(e) => setCreateForm({ ...createForm, lsh_threshold: parseFloat(e.target.value) || 0.3 })}
                />
              </div>
              <div>
                <Label htmlFor="map-phonetic">Phonetic Bonus</Label>
                <TextInput
                  id="map-phonetic"
                  type="number"
                  min={0}
                  max={50}
                  step={1}
                  value={createForm.phonetic_bonus}
                  onChange={(e) => setCreateForm({ ...createForm, phonetic_bonus: parseFloat(e.target.value) || 10.0 })}
                />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <ToggleSwitch
                checked={createForm.enabled}
                onChange={(val) => setCreateForm({ ...createForm, enabled: val })}
                label="Enabled"
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
        <ModalHeader>Delete Fuzzy Mapping</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500 flex-shrink-0" />
            <div>
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete this fuzzy mapping?
              </p>
              <p className="text-sm text-gray-500 mt-1">
                {deleteTarget?.mapping_type} → {deleteTarget?.index_name}
                {deleteTarget?.type_uri && ` (${deleteTarget.type_uri})`}
              </p>
              <p className="text-sm text-red-500 mt-1">
                All associated band data and properties will also be deleted.
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

export default FuzzyMappings;
