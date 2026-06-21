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
} from 'react-icons/hi';
import { searchFtsService } from '../services/SearchFtsService';
import type {
  SearchMapping,
  SearchMappingType,
  SearchSourceType,
  SearchPropertyRole,
  SearchMappingIndex,
  IndexType,
  UpdateSearchMappingRequest,
} from '../types/searchFts';
import { vectorGeoService } from '../services/VectorGeoService';

const MAPPING_TYPE_COLORS: Record<SearchMappingType, string> = {
  kgentity: 'info',
  kgdocument: 'purple',
  kgframe: 'success',
  kgslot: 'warning',
};

const PROPERTY_ROLE_COLORS: Record<SearchPropertyRole, string> = {
  include: 'success',
  exclude: 'failure',
};

const SearchMappingDetail: React.FC = () => {
  const { spaceId, mappingId } = useParams<{ spaceId: string; mappingId: string }>();
  const navigate = useNavigate();

  const [mapping, setMapping] = useState<SearchMapping | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Edit form state
  const [editEnabled, setEditEnabled] = useState(true);
  const [editSourceType, setEditSourceType] = useState<SearchSourceType>('default');
  const [editSeparator, setEditSeparator] = useState('. ');
  const [editIncludePredName, setEditIncludePredName] = useState(false);

  // Add property modal
  const [showAddProperty, setShowAddProperty] = useState(false);
  const [newPropertyUri, setNewPropertyUri] = useState('');
  const [newPropertyRole, setNewPropertyRole] = useState<SearchPropertyRole>('include');
  const [addingProperty, setAddingProperty] = useState(false);

  // Delete property
  const [deletingPropertyId, setDeletingPropertyId] = useState<number | null>(null);

  // Index associations
  const [indexes, setIndexes] = useState<SearchMappingIndex[]>([]);
  const [showAddIndex, setShowAddIndex] = useState(false);
  const [addIndexType, setAddIndexType] = useState<IndexType>('fts');
  const [addIndexName, setAddIndexName] = useState('');
  const [addingIndex, setAddingIndex] = useState(false);
  const [removingIndexId, setRemovingIndexId] = useState<number | null>(null);
  // FTS creation fields
  const [addFtsLanguages, setAddFtsLanguages] = useState('english');
  // Vector creation fields
  const [addVecProvider, setAddVecProvider] = useState('sentence_transformers');
  const [addVecDimensions, setAddVecDimensions] = useState(384);
  const [addVecModel, setAddVecModel] = useState('all-MiniLM-L6-v2');
  const [addVecMetric, setAddVecMetric] = useState('cosine');

  // Load mapping
  const loadMapping = useCallback(async () => {
    if (!spaceId || !mappingId) return;
    setLoading(true);
    try {
      const data = await searchFtsService.getSearchMapping(spaceId, parseInt(mappingId));
      setMapping(data);
      setEditEnabled(data.enabled);
      setEditSourceType(data.source_type);
      setEditSeparator(data.separator || '. ');
      setEditIncludePredName(data.include_pred_name);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load search mapping');
    } finally {
      setLoading(false);
    }
  }, [spaceId, mappingId]);

  const loadIndexes = useCallback(async () => {
    if (!spaceId || !mappingId) return;
    try {
      const data = await searchFtsService.listMappingIndexes(spaceId, parseInt(mappingId));
      setIndexes(data);
    } catch {
      // indexes may not exist yet — not critical
      setIndexes([]);
    }
  }, [spaceId, mappingId]);


  useEffect(() => {
    loadMapping();
    loadIndexes();
  }, [loadMapping, loadIndexes]);

  // Save settings
  const handleSave = async () => {
    if (!spaceId || !mapping) return;
    setSaving(true);
    setError(null);
    try {
      const updates: UpdateSearchMappingRequest = {};
      if (editEnabled !== mapping.enabled) updates.enabled = editEnabled;
      if (editSourceType !== mapping.source_type) updates.source_type = editSourceType;
      if (editSeparator !== (mapping.separator || '. ')) updates.separator = editSeparator;
      if (editIncludePredName !== mapping.include_pred_name) updates.include_pred_name = editIncludePredName;

      if (Object.keys(updates).length === 0) {
        setSuccess('No changes to save');
        setSaving(false);
        return;
      }

      const updated = await searchFtsService.updateSearchMapping(spaceId, mapping.mapping_id, updates);
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
      await searchFtsService.addMappingProperty(spaceId, mapping.mapping_id, {
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
      await searchFtsService.removeMappingProperty(spaceId, mapping.mapping_id, propertyId);
      setSuccess('Property removed');
      loadMapping();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to remove property');
    } finally {
      setDeletingPropertyId(null);
    }
  };

  // Create index and associate with mapping
  const handleAddIndex = async () => {
    if (!spaceId || !mapping || !addIndexName) return;
    setAddingIndex(true);
    setError(null);
    try {
      // 1. Create the index
      if (addIndexType === 'fts') {
        const languages = addFtsLanguages.split(',').map((l) => l.trim()).filter(Boolean);
        await searchFtsService.createFtsIndex(spaceId, {
          index_name: addIndexName,
          languages: languages.length > 0 ? languages : ['english'],
        });
      } else {
        await vectorGeoService.createVectorIndex(spaceId, {
          index_name: addIndexName,
          provider: addVecProvider,
          dimensions: addVecDimensions,
          model_name: addVecModel,
          distance_metric: addVecMetric,
        });
      }
      // 2. Associate the new index with this mapping
      await searchFtsService.addMappingIndex(spaceId, mapping.mapping_id, {
        index_type: addIndexType,
        index_name: addIndexName,
      });
      setShowAddIndex(false);
      setAddIndexName('');
      setSuccess(`${addIndexType.toUpperCase()} index "${addIndexName}" created and associated`);
      loadIndexes();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create index');
    } finally {
      setAddingIndex(false);
    }
  };

  // Remove index association
  const handleRemoveIndex = async (junctionId: number) => {
    if (!spaceId || !mapping) return;
    setRemovingIndexId(junctionId);
    try {
      await searchFtsService.removeMappingIndex(spaceId, mapping.mapping_id, junctionId);
      setSuccess('Index association removed');
      loadIndexes();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to remove index association');
    } finally {
      setRemovingIndexId(null);
    }
  };

  const isDirty =
    mapping &&
    (editEnabled !== mapping.enabled ||
      editSourceType !== mapping.source_type ||
      editSeparator !== (mapping.separator || '. ') ||
      editIncludePredName !== mapping.include_pred_name);

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
        Search mapping not found
      </Alert>
    );
  }

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href={`/index-mappings?space=${spaceId}`}>Search Mappings</BreadcrumbItem>
        <BreadcrumbItem>Mapping #{mapping.mapping_id}</BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Button size="sm" color="light" onClick={() => navigate(`/index-mappings?space=${spaceId}`)}>
          <HiArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Search Mapping #{mapping.mapping_id}
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

      {/* Settings + Info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="space-y-4 p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Settings</h3>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-700 dark:text-gray-300">Enabled</span>
            <ToggleSwitch checked={editEnabled} onChange={setEditEnabled} />
          </div>
          <div>
            <Label htmlFor="source-type">Source Type</Label>
            <Select
              id="source-type"
              value={editSourceType}
              onChange={(e) => setEditSourceType(e.target.value as SearchSourceType)}
              sizing="sm"
            >
              <option value="type_description">Type Description only (from KG Types)</option>
              <option value="properties">Properties only (specific URIs)</option>
              <option value="properties_type">Properties + Type Description</option>
              <option value="default">Default (hasKGraphDescription + type desc)</option>
              <option value="slots">Slots (slot content)</option>
            </Select>
          </div>
          <div>
            <Label htmlFor="separator">Separator</Label>
            <TextInput
              id="separator"
              value={editSeparator}
              onChange={(e) => setEditSeparator(e.target.value)}
              sizing="sm"
            />
            <p className="text-xs text-gray-500 mt-1">String used to join property values</p>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-700 dark:text-gray-300">Include predicate names</span>
            <ToggleSwitch checked={editIncludePredName} onChange={setEditIncludePredName} />
          </div>
        </div>

        <div className="p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Info</h3>
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
              <dt className="text-gray-500 dark:text-gray-400">Source Type</dt>
              <dd className="text-gray-900 dark:text-white">{mapping.source_type}</dd>
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

      {/* Associated Indexes section */}
      <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Associated Indexes ({indexes.length})
          </h3>
          <Button size="xs" onClick={() => setShowAddIndex(true)}>
            <HiPlus className="mr-1 h-4 w-4" />
            Add Index
          </Button>
        </div>

        {indexes.length > 0 ? (
          <div className="space-y-2">
            {indexes.map((idx) => (
              <div
                key={idx.id}
                className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg"
              >
                <Badge color={idx.index_type === 'vector' ? 'purple' : 'info'}>
                  {idx.index_type}
                </Badge>
                <span className="flex-1 text-sm font-mono text-gray-900 dark:text-white">
                  {idx.index_name}
                </span>
                <Button
                  size="xs"
                  color="failure"
                  onClick={() => handleRemoveIndex(idx.id)}
                  disabled={removingIndexId === idx.id}
                >
                  {removingIndexId === idx.id ? (
                    <Spinner size="xs" />
                  ) : (
                    <HiTrash className="h-3 w-3" />
                  )}
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-6 text-gray-500 dark:text-gray-400">
            <p className="mb-1">No indexes associated</p>
            <p className="text-sm">
              Associate vector or FTS indexes to enable search on this mapping.
            </p>
          </div>
        )}
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
              Add property URIs to control which RDF properties are indexed for search.
              Use role "include" to specify properties, or "exclude" to skip specific ones.
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
                placeholder="e.g. http://vital.ai/ontology/vital-core#hasName"
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
                onChange={(e) => setNewPropertyRole(e.target.value as SearchPropertyRole)}
              >
                <option value="include">Include (index this property)</option>
                <option value="exclude">Exclude (skip this property)</option>
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

      {/* Create Index Modal */}
      <Modal show={showAddIndex} onClose={() => setShowAddIndex(false)}>
        <ModalHeader>Create Index</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div>
              <Label htmlFor="idx-type">Index Type</Label>
              <Select
                id="idx-type"
                value={addIndexType}
                onChange={(e) => {
                  setAddIndexType(e.target.value as IndexType);
                  setAddIndexName('');
                }}
              >
                <option value="fts">FTS Index</option>
                <option value="vector">Vector Index</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="idx-name">Index Name</Label>
              <TextInput
                id="idx-name"
                placeholder="e.g. my_search_index"
                value={addIndexName}
                onChange={(e) => setAddIndexName(e.target.value)}
              />
            </div>

            {addIndexType === 'fts' && (
              <div>
                <Label htmlFor="idx-languages">Languages (comma-separated)</Label>
                <TextInput
                  id="idx-languages"
                  placeholder="english"
                  value={addFtsLanguages}
                  onChange={(e) => setAddFtsLanguages(e.target.value)}
                />
              </div>
            )}

            {addIndexType === 'vector' && (
              <>
                <div>
                  <Label htmlFor="idx-provider">Provider</Label>
                  <Select
                    id="idx-provider"
                    value={addVecProvider}
                    onChange={(e) => setAddVecProvider(e.target.value)}
                  >
                    <option value="sentence_transformers">Sentence Transformers</option>
                    <option value="openai">OpenAI</option>
                    <option value="cohere">Cohere</option>
                  </Select>
                </div>
                <div>
                  <Label htmlFor="idx-dimensions">Dimensions</Label>
                  <TextInput
                    id="idx-dimensions"
                    type="number"
                    value={addVecDimensions}
                    onChange={(e) => setAddVecDimensions(parseInt(e.target.value) || 384)}
                  />
                </div>
                <div>
                  <Label htmlFor="idx-model">Model Name</Label>
                  <TextInput
                    id="idx-model"
                    placeholder="all-MiniLM-L6-v2"
                    value={addVecModel}
                    onChange={(e) => setAddVecModel(e.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="idx-metric">Distance Metric</Label>
                  <Select
                    id="idx-metric"
                    value={addVecMetric}
                    onChange={(e) => setAddVecMetric(e.target.value)}
                  >
                    <option value="cosine">Cosine</option>
                    <option value="euclidean">Euclidean</option>
                    <option value="dot_product">Dot Product</option>
                  </Select>
                </div>
              </>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={handleAddIndex} disabled={addingIndex || !addIndexName}>
            {addingIndex ? <Spinner size="sm" className="mr-2" /> : null}
            Create Index
          </Button>
          <Button color="gray" onClick={() => setShowAddIndex(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default SearchMappingDetail;
