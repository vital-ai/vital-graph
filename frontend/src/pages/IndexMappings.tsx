import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
import { searchFtsService } from '../services/SearchFtsService';
import { fuzzyMappingService } from '../services/FuzzyMappingService';
import { apiService } from '../services/ApiService';
import type { SearchMapping, SearchMappingType, SearchSourceType } from '../types/searchFts';
import type { FuzzyMapping, FuzzyMappingType } from '../types/fuzzyMappings';
import { type SpaceInfo } from '../types/api';
import TypeURIPicker, { MAPPING_TYPE_TO_KG_CLASS } from '../components/TypeURIPicker';
import PropertySelector, { type SelectedProperty } from '../components/PropertySelector';

type MappingKind = 'fts_vector' | 'fuzzy';

interface UnifiedMapping {
  id: number;
  kind: MappingKind;
  index_name: string;
  mapping_type: string;
  type_uri?: string;
  enabled: boolean;
  created_at?: string;
  // Original refs for actions
  searchMapping?: SearchMapping;
  fuzzyMapping?: FuzzyMapping;
}

const IndexMappings: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(searchParams.get('space') || '');
  const [mappings, setMappings] = useState<UnifiedMapping[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);

  // Filters
  const [filterKind, setFilterKind] = useState<string>(searchParams.get('kind') || '');
  const [filterType, setFilterType] = useState<string>(searchParams.get('type') || '');

  // Sync state → URL params
  useEffect(() => {
    const params: Record<string, string> = {};
    if (selectedSpace) params.space = selectedSpace;
    if (filterKind) params.kind = filterKind;
    if (filterType) params.type = filterType;
    setSearchParams(params, { replace: true });
  }, [selectedSpace, filterKind, filterType, setSearchParams]);

  // Create modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createKind, setCreateKind] = useState<MappingKind>('fts_vector');
  const [createForm, setCreateForm] = useState({
    mapping_type: 'kgentity' as SearchMappingType | FuzzyMappingType,
    type_uri: '',
    index_name: '',
    enabled: true,
    // FTS/Vector fields
    source_type: 'default' as SearchSourceType,
    separator: '. ',
    include_pred_name: false,
    // Fuzzy fields
    shingle_k: 3,
    num_perm: 64,
    lsh_threshold: 0.3,
    phonetic_bonus: 10.0,
  });
  const [selectedTypeUris, setSelectedTypeUris] = useState<string[]>([]);
  const [selectedProperties, setSelectedProperties] = useState<SelectedProperty[]>([]);
  const [propertySourceMode, setPropertySourceMode] = useState<'properties' | 'default'>('default');
  const [creating, setCreating] = useState(false);

  // Delete modal
  const [deleteTarget, setDeleteTarget] = useState<UnifiedMapping | null>(null);
  const [deleting, setDeleting] = useState(false);

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
        if (allSpaces.length > 0 && !searchParams.get('space')) {
          setSelectedSpace(allSpaces[0].space);
        }
      } catch {
        setError('Failed to load spaces');
      } finally {
        setSpacesLoading(false);
      }
    };
    loadSpaces();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load mappings from both endpoints
  const loadData = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const [searchMappings, fuzzyMappings] = await Promise.all([
        searchFtsService.getSearchMappings(selectedSpace, {
          mapping_type: filterType || undefined,
        }),
        fuzzyMappingService.getFuzzyMappings(selectedSpace),
      ]);

      const unified: UnifiedMapping[] = [];

      for (const sm of searchMappings) {
        unified.push({
          id: sm.mapping_id,
          kind: 'fts_vector',
          index_name: sm.index_name,
          mapping_type: sm.mapping_type,
          type_uri: sm.type_uri ?? undefined,
          enabled: sm.enabled,
          created_at: sm.created_time ?? undefined,
          searchMapping: sm,
        });
      }

      for (const fm of fuzzyMappings) {
        unified.push({
          id: fm.mapping_id,
          kind: 'fuzzy',
          index_name: fm.index_name,
          mapping_type: fm.mapping_type,
          type_uri: fm.type_uri ?? undefined,
          enabled: fm.enabled,
          created_at: fm.created_time ?? undefined,
          fuzzyMapping: fm,
        });
      }

      // Apply kind filter
      const filtered = filterKind
        ? unified.filter((m) => m.kind === filterKind)
        : unified;

      setMappings(filtered);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load mappings');
      setMappings([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, filterKind, filterType]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Navigate to detail
  const handleViewDetail = (mapping: UnifiedMapping) => {
    if (mapping.kind === 'fts_vector' && mapping.searchMapping) {
      navigate(`/space/${selectedSpace}/index-mappings/${mapping.searchMapping.mapping_id}`);
    } else if (mapping.kind === 'fuzzy' && mapping.fuzzyMapping) {
      navigate(`/space/${selectedSpace}/fuzzy-mappings/${mapping.fuzzyMapping.mapping_id}`);
    }
  };

  // Toggle enabled
  const handleToggleEnabled = async (mapping: UnifiedMapping) => {
    if (!selectedSpace) return;
    try {
      if (mapping.kind === 'fts_vector' && mapping.searchMapping) {
        await searchFtsService.updateSearchMapping(selectedSpace, mapping.id, {
          enabled: !mapping.enabled,
        });
      } else if (mapping.kind === 'fuzzy' && mapping.fuzzyMapping) {
        await fuzzyMappingService.updateFuzzyMapping(selectedSpace, mapping.id, {
          enabled: !mapping.enabled,
        });
      }
      setMappings((prev) =>
        prev.map((m) => m.id === mapping.id && m.kind === mapping.kind
          ? { ...m, enabled: !m.enabled }
          : m
        )
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to toggle mapping');
      loadData();
    }
  };

  // Create
  const handleCreate = async () => {
    if (!selectedSpace || !createForm.index_name) return;
    setCreating(true);
    try {
      const sourceType = propertySourceMode === 'properties' ? 'concat_properties' as SearchSourceType : createForm.source_type;

      // Helper to add properties to a newly created mapping
      const addProperties = async (mappingId: number, kind: MappingKind) => {
        if (selectedProperties.length === 0) return;
        for (let ordinal = 0; ordinal < selectedProperties.length; ordinal++) {
          const prop = selectedProperties[ordinal];
          if (kind === 'fts_vector') {
            await searchFtsService.addMappingProperty(selectedSpace, mappingId, {
              property_uri: prop.uri,
              property_role: prop.role || 'include',
              ordinal: ordinal + 1,
            });
          } else {
            await fuzzyMappingService.addMappingProperty(selectedSpace, mappingId, {
              property_uri: prop.uri,
              property_role: prop.role || 'include',
              ordinal: ordinal + 1,
            });
          }
        }
      };

      // Collect all type URIs to create mappings for (at least one iteration)
      const typeUris = selectedTypeUris.length > 0 ? selectedTypeUris : [undefined];

      for (const uri of typeUris) {
        if (createKind === 'fts_vector') {
          const created = await searchFtsService.createSearchMapping(selectedSpace, {
            mapping_type: createForm.mapping_type as SearchMappingType,
            type_uri: uri,
            index_name: createForm.index_name,
            enabled: createForm.enabled,
            source_type: sourceType,
            separator: createForm.separator,
            include_pred_name: createForm.include_pred_name,
          });
          await addProperties(created.mapping_id, 'fts_vector');
        } else {
          const created = await fuzzyMappingService.createFuzzyMapping(selectedSpace, {
            mapping_type: createForm.mapping_type as FuzzyMappingType,
            type_uri: uri,
            index_name: createForm.index_name,
            enabled: createForm.enabled,
            shingle_k: createForm.shingle_k,
            num_perm: createForm.num_perm,
            lsh_threshold: createForm.lsh_threshold,
            phonetic_bonus: createForm.phonetic_bonus,
          });
          await addProperties(created.mapping_id, 'fuzzy');
        }
      }

      setShowCreateModal(false);
      setSelectedTypeUris([]);
      setSelectedProperties([]);
      setPropertySourceMode('default');
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create mapping');
    } finally {
      setCreating(false);
    }
  };

  // Delete
  const handleDelete = async () => {
    if (!selectedSpace || !deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.kind === 'fts_vector') {
        await searchFtsService.deleteSearchMapping(selectedSpace, deleteTarget.id);
      } else {
        await fuzzyMappingService.deleteFuzzyMapping(selectedSpace, deleteTarget.id);
      }
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
        <BreadcrumbItem>Index Mappings</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Index Mappings</h1>
        <Button size="sm" color="blue" onClick={() => setShowCreateModal(true)}>
          <HiPlus className="mr-1 h-4 w-4" />
          Create Mapping
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
          <Label htmlFor="filterKind">Type</Label>
          <Select id="filterKind" value={filterKind} onChange={(e) => setFilterKind(e.target.value)}>
            <option value="">All</option>
            <option value="fts_vector">FTS / Vector</option>
            <option value="fuzzy">Fuzzy</option>
          </Select>
        </div>
        <div className="w-40">
          <Label htmlFor="filterType">Object Type</Label>
          <Select id="filterType" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All</option>
            <option value="kgentity">Entity</option>
            <option value="kgdocument">Document</option>
            <option value="kgframe">Frame</option>
          </Select>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : mappings.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          No mappings found for this space.
        </div>
      ) : (
        <Table striped>
          <TableHead>
            <TableRow>
              <TableHeadCell>Index Name</TableHeadCell>
              <TableHeadCell>Kind</TableHeadCell>
              <TableHeadCell>Object Type</TableHeadCell>
              <TableHeadCell>Type URI</TableHeadCell>
              <TableHeadCell>Enabled</TableHeadCell>
              <TableHeadCell>Actions</TableHeadCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {mappings.map((m) => (
              <TableRow key={`${m.kind}-${m.id}`} className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700">
                <TableCell className="font-medium" onClick={() => handleViewDetail(m)}>
                  {m.index_name}
                </TableCell>
                <TableCell onClick={() => handleViewDetail(m)}>
                  <Badge color={m.kind === 'fuzzy' ? 'purple' : 'blue'}>
                    {m.kind === 'fuzzy' ? 'Fuzzy' : 'FTS / Vector'}
                  </Badge>
                </TableCell>
                <TableCell onClick={() => handleViewDetail(m)}>
                  <Badge color="gray">{m.mapping_type}</Badge>
                </TableCell>
                <TableCell className="max-w-xs truncate" title={m.type_uri} onClick={() => handleViewDetail(m)}>
                  {m.type_uri || '—'}
                </TableCell>
                <TableCell>
                  <ToggleSwitch
                    checked={m.enabled}
                    onChange={() => handleToggleEnabled(m)}
                    label=""
                  />
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button size="xs" color="gray" onClick={() => handleViewDetail(m)}>
                      <HiEye className="h-3 w-3" />
                    </Button>
                    <Button size="xs" color="failure" onClick={() => setDeleteTarget(m)}>
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
        <ModalHeader>Create Mapping</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="createKind">Mapping Kind</Label>
              <Select
                id="createKind"
                value={createKind}
                onChange={(e) => setCreateKind(e.target.value as MappingKind)}
              >
                <option value="fts_vector">FTS / Vector</option>
                <option value="fuzzy">Fuzzy</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="createIndexName">Index Name</Label>
              <TextInput
                id="createIndexName"
                value={createForm.index_name}
                onChange={(e) => setCreateForm({ ...createForm, index_name: e.target.value })}
                placeholder="e.g. entity_default"
              />
            </div>
            <div>
              <Label htmlFor="createMappingType">Object Type</Label>
              <Select
                id="createMappingType"
                value={createForm.mapping_type}
                onChange={(e) => setCreateForm({ ...createForm, mapping_type: e.target.value as SearchMappingType })}
              >
                <option value="kgentity">Entity</option>
                <option value="kgdocument">Document</option>
                <option value="kgframe">Frame</option>
              </Select>
            </div>
            <div>
              <Label>Type URIs (optional — filter which subjects get indexed)</Label>
              <TypeURIPicker
                spaceId={selectedSpace}
                typeFilter={MAPPING_TYPE_TO_KG_CLASS[createForm.mapping_type] || undefined}
                selected={selectedTypeUris}
                onChange={setSelectedTypeUris}
                placeholder={`Search ${createForm.mapping_type} types...`}
              />
            </div>

            <div>
              <Label>Properties</Label>
              <PropertySelector
                selected={selectedProperties}
                onChange={setSelectedProperties}
                showRoles={createKind === 'fuzzy'}
                sourceMode={propertySourceMode}
                onSourceModeChange={setPropertySourceMode}
              />
            </div>

            {/* Fuzzy-specific fields */}
            {createKind === 'fuzzy' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="shingleK">Shingle K</Label>
                    <TextInput
                      id="shingleK"
                      type="number"
                      value={createForm.shingle_k}
                      onChange={(e) => setCreateForm({ ...createForm, shingle_k: parseInt(e.target.value) || 3 })}
                    />
                  </div>
                  <div>
                    <Label htmlFor="numPerm">Num Permutations</Label>
                    <TextInput
                      id="numPerm"
                      type="number"
                      value={createForm.num_perm}
                      onChange={(e) => setCreateForm({ ...createForm, num_perm: parseInt(e.target.value) || 64 })}
                    />
                  </div>
                  <div>
                    <Label htmlFor="lshThreshold">LSH Threshold</Label>
                    <TextInput
                      id="lshThreshold"
                      type="number"
                      step="0.05"
                      value={createForm.lsh_threshold}
                      onChange={(e) => setCreateForm({ ...createForm, lsh_threshold: parseFloat(e.target.value) || 0.3 })}
                    />
                  </div>
                  <div>
                    <Label htmlFor="phoneticBonus">Phonetic Bonus</Label>
                    <TextInput
                      id="phoneticBonus"
                      type="number"
                      step="1"
                      value={createForm.phonetic_bonus}
                      onChange={(e) => setCreateForm({ ...createForm, phonetic_bonus: parseFloat(e.target.value) || 10 })}
                    />
                  </div>
                </div>
              </>
            )}

            {/* FTS/Vector-specific fields */}
            {createKind === 'fts_vector' && (
              <>
                <div className="flex gap-4">
                  <ToggleSwitch
                    checked={createForm.include_pred_name}
                    onChange={(val) => setCreateForm({ ...createForm, include_pred_name: val })}
                    label="Include predicate names"
                  />
                </div>
              </>
            )}

            <ToggleSwitch
              checked={createForm.enabled}
              onChange={(val) => setCreateForm({ ...createForm, enabled: val })}
              label="Enabled"
            />
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
        <ModalHeader>Delete Mapping</ModalHeader>
        <ModalBody>
          <div className="flex items-center gap-3">
            <HiExclamation className="h-8 w-8 text-red-500" />
            <p>
              Are you sure you want to delete mapping <strong>{deleteTarget?.index_name}</strong>?
              This action cannot be undone.
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

export default IndexMappings;
