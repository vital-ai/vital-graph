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
  HiMenu,
} from 'react-icons/hi';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { vectorGeoService } from '../services/VectorGeoService';
import type { VectorMapping, MappingProperty, MappingType, SourceType, UpdateVectorMappingRequest } from '../types/vectorGeo';

const MAPPING_TYPE_COLORS: Record<MappingType, string> = {
  kgentity: 'info',
  kgdocument: 'purple',
  kgframe: 'success',
  kgslot: 'warning',
};

// Sortable row component for drag-and-drop property reorder
interface SortablePropertyRowProps {
  prop: MappingProperty;
  onDelete: (id: number) => void;
  deleting: boolean;
}

function SortablePropertyRow({ prop, onDelete, deleting }: SortablePropertyRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: prop.property_id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg"
    >
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
      >
        <HiMenu className="h-5 w-5" />
      </button>
      <span className="w-8 text-center font-mono text-sm text-gray-500">{prop.ordinal}</span>
      <span className="flex-1 text-xs font-mono break-all text-gray-900 dark:text-white">
        {prop.property_uri}
      </span>
      <Badge color={prop.property_role === 'include' ? 'success' : 'failure'}>
        {prop.property_role}
      </Badge>
      <Button
        size="xs"
        color="failure"
        onClick={() => onDelete(prop.property_id)}
        disabled={deleting}
      >
        {deleting ? <Spinner size="xs" /> : <HiTrash className="h-3 w-3" />}
      </Button>
    </div>
  );
}

const VectorMappingDetail: React.FC = () => {
  const { spaceId, mappingId } = useParams<{ spaceId: string; mappingId: string }>();
  const navigate = useNavigate();

  const [mapping, setMapping] = useState<VectorMapping | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Edit form state (for toggles/settings)
  const [editEnabled, setEditEnabled] = useState(false);
  const [editSourceType, setEditSourceType] = useState<SourceType>('default');
  const [editSeparator, setEditSeparator] = useState(' ');
  const [editIncludePredName, setEditIncludePredName] = useState(false);
  const [editIncludeTypeDesc, setEditIncludeTypeDesc] = useState(false);

  // Add property modal
  const [showAddProperty, setShowAddProperty] = useState(false);
  const [newPropertyUri, setNewPropertyUri] = useState('');
  const [newPropertyRole, setNewPropertyRole] = useState<'include' | 'exclude'>('include');
  const [addingProperty, setAddingProperty] = useState(false);

  // Delete property
  const [deletingPropertyId, setDeletingPropertyId] = useState<number | null>(null);

  // Load mapping
  const loadMapping = useCallback(async () => {
    if (!spaceId || !mappingId) return;
    setLoading(true);
    try {
      const data = await vectorGeoService.getVectorMapping(spaceId, parseInt(mappingId));
      setMapping(data);
      setEditEnabled(data.enabled);
      setEditSourceType(data.source_type);
      setEditSeparator(data.separator);
      setEditIncludePredName(data.include_pred_name);
      setEditIncludeTypeDesc(data.include_type_desc);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load mapping');
    } finally {
      setLoading(false);
    }
  }, [spaceId, mappingId]);

  useEffect(() => {
    loadMapping();
  }, [loadMapping]);

  // Save settings
  const handleSave = async () => {
    if (!spaceId || !mapping) return;
    setSaving(true);
    setError(null);
    try {
      const updates: UpdateVectorMappingRequest = {};
      if (editEnabled !== mapping.enabled) updates.enabled = editEnabled;
      if (editSourceType !== mapping.source_type) updates.source_type = editSourceType;
      if (editSeparator !== mapping.separator) updates.separator = editSeparator;
      if (editIncludePredName !== mapping.include_pred_name) updates.include_pred_name = editIncludePredName;
      if (editIncludeTypeDesc !== mapping.include_type_desc) updates.include_type_desc = editIncludeTypeDesc;

      if (Object.keys(updates).length === 0) {
        setSuccess('No changes to save');
        setSaving(false);
        return;
      }

      const updated = await vectorGeoService.updateVectorMapping(spaceId, mapping.mapping_id, updates);
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
      await vectorGeoService.addMappingProperty(spaceId, mapping.mapping_id, {
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
      await vectorGeoService.removeMappingProperty(spaceId, mapping.mapping_id, propertyId);
      setSuccess('Property removed');
      loadMapping();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to remove property');
    } finally {
      setDeletingPropertyId(null);
    }
  };

  // Drag-and-drop reorder
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const handleDragEnd = (event: DragEndEvent) => {
    if (!mapping?.properties) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const sorted = [...mapping.properties].sort((a, b) => a.ordinal - b.ordinal);
    const oldIndex = sorted.findIndex((p) => p.property_id === active.id);
    const newIndex = sorted.findIndex((p) => p.property_id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(sorted, oldIndex, newIndex);
    // Reassign ordinals
    const updated = reordered.map((p, i) => ({ ...p, ordinal: i }));
    setMapping({ ...mapping, properties: updated });
  };

  const isDirty =
    mapping &&
    (editEnabled !== mapping.enabled ||
      editSourceType !== mapping.source_type ||
      editSeparator !== mapping.separator ||
      editIncludePredName !== mapping.include_pred_name ||
      editIncludeTypeDesc !== mapping.include_type_desc);

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
        Mapping not found
      </Alert>
    );
  }

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/vector-mappings">Vector Mappings</BreadcrumbItem>
        <BreadcrumbItem>Mapping #{mapping.mapping_id}</BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <Button size="sm" color="light" onClick={() => navigate('/vector-mappings')}>
          <HiArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Vector Mapping #{mapping.mapping_id}
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

      {/* Settings section */}
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
              onChange={(e) => setEditSourceType(e.target.value as SourceType)}
            >
              <option value="default">Default (all string properties)</option>
              <option value="properties">Properties (specific URIs)</option>
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
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-700 dark:text-gray-300">Include predicate names</span>
            <ToggleSwitch checked={editIncludePredName} onChange={setEditIncludePredName} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-700 dark:text-gray-300">Include type description</span>
            <ToggleSwitch checked={editIncludeTypeDesc} onChange={setEditIncludeTypeDesc} />
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
              <dt className="text-gray-500 dark:text-gray-400">Index</dt>
              <dd className="text-gray-900 dark:text-white">{mapping.index_name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Type</dt>
              <dd><Badge color={MAPPING_TYPE_COLORS[mapping.mapping_type]}>{mapping.mapping_type}</Badge></dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Created</dt>
              <dd className="text-gray-900 dark:text-white">
                {new Date(mapping.created_time).toLocaleDateString()}
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
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext
              items={[...mapping.properties].sort((a, b) => a.ordinal - b.ordinal).map((p) => p.property_id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-2">
                {[...mapping.properties]
                  .sort((a, b) => a.ordinal - b.ordinal)
                  .map((prop) => (
                    <SortablePropertyRow
                      key={prop.property_id}
                      prop={prop}
                      onDelete={handleDeleteProperty}
                      deleting={deletingPropertyId === prop.property_id}
                    />
                  ))}
              </div>
            </SortableContext>
          </DndContext>
        ) : (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <p className="mb-1">No properties configured</p>
            <p className="text-sm">
              When source type is "properties", add URIs here to control which properties are vectorized.
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
                onChange={(e) => setNewPropertyRole(e.target.value as 'include' | 'exclude')}
              >
                <option value="include">Include (vectorize this property)</option>
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
    </div>
  );
};

export default VectorMappingDetail;
