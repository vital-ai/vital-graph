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
  ToggleSwitch,
} from 'flowbite-react';
import {
  HiArrowLeft,
  HiHome,
  HiPlus,
  HiTrash,
  HiRefresh,
} from 'react-icons/hi';
import { fuzzyMappingService } from '../services/FuzzyMappingService';
import type { FuzzyMapping, FuzzyMappingStats, FuzzyMappingType, FuzzyPropertyRole, UpdateFuzzyMappingRequest } from '../types/fuzzyMappings';

const MAPPING_TYPE_COLORS: Record<FuzzyMappingType, string> = {
  kgentity: 'info',
  kgdocument: 'purple',
  kgframe: 'success',
  kgslot: 'warning',
};

const PROPERTY_ROLE_COLORS: Record<FuzzyPropertyRole, string> = {
  primary: 'info',
  alias: 'purple',
  include: 'success',
};

const FuzzyMappingDetail: React.FC = () => {
  const { spaceId, mappingId } = useParams<{ spaceId: string; mappingId: string }>();
  const navigate = useNavigate();

  const [mapping, setMapping] = useState<FuzzyMapping | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Edit form state
  const [editEnabled, setEditEnabled] = useState(false);
  const [editShingleK, setEditShingleK] = useState(3);
  const [editNumPerm, setEditNumPerm] = useState(64);
  const [editLshThreshold, setEditLshThreshold] = useState(0.3);
  const [editPhoneticBonus, setEditPhoneticBonus] = useState(10.0);

  // Add property modal
  const [showAddProperty, setShowAddProperty] = useState(false);
  const [newPropertyUri, setNewPropertyUri] = useState('');
  const [newPropertyRole, setNewPropertyRole] = useState<FuzzyPropertyRole>('include');
  const [addingProperty, setAddingProperty] = useState(false);

  // Delete property
  const [deletingPropertyId, setDeletingPropertyId] = useState<number | null>(null);

  // Populate
  const [populating, setPopulating] = useState(false);
  const [populateResult, setPopulateResult] = useState<string | null>(null);

  // Stats
  const [stats, setStats] = useState<FuzzyMappingStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // Load mapping
  const loadMapping = useCallback(async () => {
    if (!spaceId || !mappingId) return;
    setLoading(true);
    try {
      const data = await fuzzyMappingService.getFuzzyMapping(spaceId, parseInt(mappingId));
      setMapping(data);
      setEditEnabled(data.enabled);
      setEditShingleK(data.shingle_k);
      setEditNumPerm(data.num_perm);
      setEditLshThreshold(data.lsh_threshold);
      setEditPhoneticBonus(data.phonetic_bonus);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load fuzzy mapping');
    } finally {
      setLoading(false);
    }
  }, [spaceId, mappingId]);

  const loadStats = useCallback(async () => {
    if (!spaceId || !mappingId) return;
    setStatsLoading(true);
    try {
      const data = await fuzzyMappingService.getStats(spaceId, parseInt(mappingId));
      setStats(data);
    } catch {
      // Stats are non-critical — silently ignore errors
    } finally {
      setStatsLoading(false);
    }
  }, [spaceId, mappingId]);

  useEffect(() => {
    loadMapping();
    loadStats();
  }, [loadMapping, loadStats]);

  // Save settings
  const handleSave = async () => {
    if (!spaceId || !mapping) return;
    setSaving(true);
    setError(null);
    try {
      const updates: UpdateFuzzyMappingRequest = {};
      if (editEnabled !== mapping.enabled) updates.enabled = editEnabled;
      if (editShingleK !== mapping.shingle_k) updates.shingle_k = editShingleK;
      if (editNumPerm !== mapping.num_perm) updates.num_perm = editNumPerm;
      if (editLshThreshold !== mapping.lsh_threshold) updates.lsh_threshold = editLshThreshold;
      if (editPhoneticBonus !== mapping.phonetic_bonus) updates.phonetic_bonus = editPhoneticBonus;

      if (Object.keys(updates).length === 0) {
        setSuccess('No changes to save');
        setSaving(false);
        return;
      }

      const updated = await fuzzyMappingService.updateFuzzyMapping(spaceId, mapping.mapping_id, updates);
      setMapping(updated);
      setSuccess('Mapping updated successfully');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  // Add property
  const handleAddProperty = async () => {
    if (!spaceId || !mapping || !newPropertyUri.trim()) return;
    setAddingProperty(true);
    try {
      const nextOrdinal = mapping.properties?.length
        ? Math.max(...mapping.properties.map((p) => p.ordinal)) + 1
        : 0;
      await fuzzyMappingService.addMappingProperty(spaceId, mapping.mapping_id, {
        property_uri: newPropertyUri.trim(),
        property_role: newPropertyRole,
        ordinal: nextOrdinal,
      });
      setShowAddProperty(false);
      setNewPropertyUri('');
      setNewPropertyRole('include');
      setSuccess('Property added');
      loadMapping();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to add property');
    } finally {
      setAddingProperty(false);
    }
  };

  // Delete property
  const handleDeleteProperty = async (propertyId: number) => {
    if (!spaceId || !mapping) return;
    setDeletingPropertyId(propertyId);
    try {
      await fuzzyMappingService.removeMappingProperty(spaceId, mapping.mapping_id, propertyId);
      setSuccess('Property removed');
      loadMapping();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to remove property');
    } finally {
      setDeletingPropertyId(null);
    }
  };

  // Populate index
  const handlePopulate = async () => {
    if (!spaceId || !mapping) return;
    setPopulating(true);
    setPopulateResult(null);
    setError(null);
    try {
      const result = await fuzzyMappingService.populate(spaceId, mapping.mapping_id);
      setPopulateResult(
        `Populated: ${result.subjects_processed} subjects, ${result.bands_stored} bands in ${result.elapsed_seconds.toFixed(1)}s`
      );
      loadStats();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to populate index');
    } finally {
      setPopulating(false);
    }
  };

  const isDirty =
    mapping &&
    (editEnabled !== mapping.enabled ||
      editShingleK !== mapping.shingle_k ||
      editNumPerm !== mapping.num_perm ||
      editLshThreshold !== mapping.lsh_threshold ||
      editPhoneticBonus !== mapping.phonetic_bonus);

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="xl" />
      </div>
    );
  }

  if (!mapping) {
    return (
      <Alert color="failure">
        Fuzzy mapping not found
      </Alert>
    );
  }

  return (
    <div data-testid="fuzzy-mapping-detail-page">
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href={`/index-mappings?space=${spaceId}`}>Index Mappings</BreadcrumbItem>
        <BreadcrumbItem>Fuzzy Mapping #{mapping.mapping_id}</BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Button size="sm" color="light" onClick={() => navigate(`/index-mappings?space=${spaceId}`)}>
          <HiArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Fuzzy Mapping #{mapping.mapping_id}
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <Badge color={MAPPING_TYPE_COLORS[mapping.mapping_type]}>
              {mapping.mapping_type}
            </Badge>
            <span className="text-sm text-gray-500">→ {mapping.index_name}</span>
            {mapping.type_uri && (
              <code className="text-xs text-gray-400 bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded">
                {mapping.type_uri}
              </code>
            )}
          </div>
        </div>
        <Button size="sm" onClick={handleSave} disabled={saving || !isDirty}>
          {saving ? <Spinner size="sm" className="mr-2" /> : null}
          Save Changes
        </Button>
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
      {populateResult && (
        <Alert color="info" className="mb-4" onDismiss={() => setPopulateResult(null)}>
          {populateResult}
        </Alert>
      )}

      {/* === Mapping Configuration Section === */}
      <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-4 border-b pb-2">Mapping Configuration</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="space-y-4 p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Settings</h3>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-700 dark:text-gray-300">Enabled</span>
            <ToggleSwitch checked={editEnabled} onChange={setEditEnabled} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="shingle-k">Shingle K</Label>
              <TextInput
                id="shingle-k"
                type="number"
                min={2}
                max={10}
                value={editShingleK}
                onChange={(e) => setEditShingleK(parseInt(e.target.value) || 3)}
                sizing="sm"
              />
              <p className="text-xs text-gray-500 mt-1">Character n-gram size for shingling</p>
            </div>
            <div>
              <Label htmlFor="num-perm">Num Permutations</Label>
              <TextInput
                id="num-perm"
                type="number"
                min={16}
                max={256}
                value={editNumPerm}
                onChange={(e) => setEditNumPerm(parseInt(e.target.value) || 64)}
                sizing="sm"
              />
              <p className="text-xs text-gray-500 mt-1">MinHash signature length</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="lsh-threshold">LSH Threshold</Label>
              <TextInput
                id="lsh-threshold"
                type="number"
                min={0.1}
                max={1.0}
                step={0.05}
                value={editLshThreshold}
                onChange={(e) => setEditLshThreshold(parseFloat(e.target.value) || 0.3)}
                sizing="sm"
              />
              <p className="text-xs text-gray-500 mt-1">Jaccard similarity threshold for LSH bands</p>
            </div>
            <div>
              <Label htmlFor="phonetic-bonus">Phonetic Bonus</Label>
              <TextInput
                id="phonetic-bonus"
                type="number"
                min={0}
                max={50}
                step={1}
                value={editPhoneticBonus}
                onChange={(e) => setEditPhoneticBonus(parseFloat(e.target.value) || 10.0)}
                sizing="sm"
              />
              <p className="text-xs text-gray-500 mt-1">Score bonus for phonetic code match</p>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
            <h3 className="text-md font-semibold text-gray-900 dark:text-white mb-3">Info</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Mapping ID</dt>
                <dd className="text-gray-900 dark:text-white">{mapping.mapping_id}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Index Name</dt>
                <dd className="text-gray-900 dark:text-white">{mapping.index_name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Type</dt>
                <dd><Badge color={MAPPING_TYPE_COLORS[mapping.mapping_type]}>{mapping.mapping_type}</Badge></dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">Created</dt>
                <dd className="text-gray-900 dark:text-white">
                  {mapping.created_time ? new Date(mapping.created_time).toLocaleDateString() : '—'}
                </dd>
              </div>
              {mapping.type_uri && (
                <div>
                  <dt className="text-gray-500 dark:text-gray-400 mb-1">Type URI</dt>
                  <dd className="text-xs break-all font-mono text-gray-900 dark:text-white">
                    {mapping.type_uri}
                  </dd>
                </div>
              )}
            </dl>
          </div>

        </div>
      </div>

      {/* === Index Section === */}
      <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-4 border-b pb-2">Index</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-md font-semibold text-gray-900 dark:text-white">Statistics</h3>
            <Button size="xs" color="light" onClick={loadStats} disabled={statsLoading}>
              {statsLoading ? <Spinner size="xs" /> : <HiRefresh className="h-3 w-3" />}
            </Button>
          </div>
          {stats ? (
            <div className="grid grid-cols-3 gap-4 text-center">
              <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                  {stats.entity_count.toLocaleString()}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">Entities</div>
              </div>
              <div className="p-3 bg-green-50 dark:bg-green-900/20 rounded-lg">
                <div className="text-2xl font-bold text-green-600 dark:text-green-400">
                  {stats.band_count.toLocaleString()}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">LSH Bands</div>
              </div>
              <div className="p-3 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
                <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                  {stats.phonetic_band_count.toLocaleString()}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">Phonetic Bands</div>
              </div>
            </div>
          ) : statsLoading ? (
            <div className="flex justify-center py-4">
              <Spinner size="sm" />
            </div>
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
              No statistics available. Populate the index first.
            </p>
          )}
        </div>
        <div className="p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <h3 className="text-md font-semibold text-gray-900 dark:text-white mb-3">Populate</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
            Rebuild the fuzzy index bands from the current data in this space.
          </p>
          <Button size="sm" onClick={handlePopulate} disabled={populating}>
            {populating ? <Spinner size="sm" className="mr-2" /> : <HiRefresh className="mr-2 h-4 w-4" />}
            Populate Index
          </Button>
          {populateResult && (
            <p className="text-sm text-green-600 dark:text-green-400 mt-3">{populateResult}</p>
          )}
        </div>
      </div>

      {/* Properties section */}
      <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Properties ({mapping.properties?.length || 0})
          </h3>
          <Button size="xs" onClick={() => setShowAddProperty(true)}>
            <HiPlus className="mr-1 h-4 w-4" />
            Add Property
          </Button>
        </div>

        {mapping.properties && mapping.properties.length > 0 ? (
          <div className="space-y-2">
            {[...mapping.properties]
              .sort((a, b) => a.ordinal - b.ordinal)
              .map((prop) => (
                <div
                  key={prop.property_id}
                  className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg"
                >
                  <span className="w-8 text-center font-mono text-sm text-gray-500">{prop.ordinal}</span>
                  <span className="flex-1 text-xs font-mono break-all text-gray-900 dark:text-white">
                    {prop.property_uri}
                  </span>
                  <Badge color={PROPERTY_ROLE_COLORS[prop.property_role] || 'gray'}>
                    {prop.property_role}
                  </Badge>
                  <Button
                    size="xs"
                    color="failure"
                    onClick={() => handleDeleteProperty(prop.property_id)}
                    disabled={deletingPropertyId === prop.property_id}
                  >
                    {deletingPropertyId === prop.property_id ? (
                      <Spinner size="xs" />
                    ) : (
                      <HiTrash className="h-3 w-3" />
                    )}
                  </Button>
                </div>
              ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <p className="mb-1">No properties configured</p>
            <p className="text-sm">
              Add property URIs to control which RDF properties are indexed for fuzzy matching.
              Use role "primary" for the main name field and "alias" for alternative names.
            </p>
          </div>
        )}
      </div>

      {/* Add Property Modal */}
      <Modal show={showAddProperty} onClose={() => setShowAddProperty(false)}>
        <ModalHeader>Add Property</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="prop-uri">Property URI</Label>
              <TextInput
                id="prop-uri"
                placeholder="e.g. http://vital.ai/ontology/vital-aimp#hasName"
                value={newPropertyUri}
                onChange={(e) => setNewPropertyUri(e.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="prop-role">Role</Label>
              <Select
                id="prop-role"
                value={newPropertyRole}
                onChange={(e) => setNewPropertyRole(e.target.value as FuzzyPropertyRole)}
              >
                <option value="primary">Primary (main name field — used for scoring weight)</option>
                <option value="alias">Alias (alternative names — also searched and scored)</option>
                <option value="include">Include (generic — treated as alias)</option>
              </Select>
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={handleAddProperty} disabled={addingProperty || !newPropertyUri.trim()}>
            {addingProperty ? <Spinner size="sm" className="mr-2" /> : null}
            Add
          </Button>
          <Button color="gray" onClick={() => setShowAddProperty(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default FuzzyMappingDetail;
