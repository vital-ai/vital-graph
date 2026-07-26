import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Label, Select, Spinner, TextInput, Textarea,
  Breadcrumb, BreadcrumbItem,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
} from 'flowbite-react';
import {
  HiHome, HiCollection, HiPencil, HiTrash, HiSave, HiX, HiPlus,
  HiTag, HiIdentification, HiFolder, HiLocationMarker, HiLink,
  HiArrowRight, HiArrowLeft,
} from 'react-icons/hi';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
import { usePageTitle } from '../hooks/usePageTitle';
import {
  useEntityTypes, useCategories, useRelationshipTypes,
  useIdentifierNamespaces, useAliasTypes,
} from '../hooks/useRegistryLookups';
import ConfirmDialog from '../components/ConfirmDialog';
import EntityPicker, { PickedEntity } from '../components/EntityPicker';
import TagInput from '../components/TagInput';

// Must match update_entity's valid_statuses in entity_registry_impl.py — an
// unlisted value is rejected with a 400. 'deleted' is omitted deliberately:
// it is terminal and set via the delete endpoint, not by editing the field.
const ENTITY_STATUSES = ['active', 'inactive', 'merged'];

interface RelationshipItem {
  relationship_id: number;
  entity_source: string;
  entity_destination: string;
  relationship_type_key: string;
  relationship_type_label: string | null;
  inverse_key: string | null;
  status: string;
  is_current: boolean;
  description: string | null;
}

// Fix default marker icons for leaflet in bundled apps
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({ iconRetinaUrl: markerIcon2x, iconUrl: markerIcon, shadowUrl: markerShadow });

/** Auto-fit map bounds to markers */
const FitBounds: React.FC<{ bounds: L.LatLngBoundsExpression }> = ({ bounds }) => {
  const map = useMap();
  useEffect(() => { map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 }); }, [map, bounds]);
  return null;
};

interface LocationItem {
  location_id: number;
  location_name: string | null;
  location_type_key: string;
  latitude: number | null;
  longitude: number | null;
  formatted_address: string | null;
}

const LocationsTabContent: React.FC<{ locations: LocationItem[] }> = ({ locations }) => {
  const geoLocations = locations.filter(l => l.latitude != null && l.longitude != null);
  const bounds = geoLocations.length > 0
    ? L.latLngBounds(geoLocations.map(l => [l.latitude!, l.longitude!] as L.LatLngTuple))
    : null;
  const center: L.LatLngTuple = geoLocations.length > 0
    ? [geoLocations[0].latitude!, geoLocations[0].longitude!]
    : [39.8283, -98.5795];

  return (
    <div className="space-y-4">
      {bounds && (
        <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700" style={{ height: '300px' }}>
          <MapContainer center={center} zoom={10} style={{ height: '100%', width: '100%' }} scrollWheelZoom>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <FitBounds bounds={bounds} />
            {geoLocations.map(l => (
              <Marker key={l.location_id} position={[l.latitude!, l.longitude!]}>
                <Popup>
                  <strong>{l.location_name || l.location_type_key}</strong>
                  {l.formatted_address && <><br /><span className="text-xs">{l.formatted_address}</span></>}
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>
      )}
      <Table striped>
        <TableHead><TableHeadCell>Name</TableHeadCell><TableHeadCell>Type</TableHeadCell><TableHeadCell>Address</TableHeadCell><TableHeadCell>Coordinates</TableHeadCell></TableHead>
        <TableBody>
          {locations.map(l => (
            <TableRow key={l.location_id}>
              <TableCell>{l.location_name || '\u2014'}</TableCell>
              <TableCell><Badge color="purple" size="xs">{l.location_type_key}</Badge></TableCell>
              <TableCell className="text-sm text-gray-500">{l.formatted_address || '\u2014'}</TableCell>
              <TableCell className="font-mono text-xs">{l.latitude != null && l.longitude != null ? `${l.latitude}, ${l.longitude}` : '\u2014'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

interface EntityData {
  entity_id: string;
  entity_uri: string;
  primary_name: string;
  type_key: string | null;
  type_label: string | null;
  description: string | null;
  status: string;
  created_time: string | null;
  updated_time: string | null;
}

const EntityRegistryDetail: React.FC = () => {
  const { entityId } = useParams<{ entityId: string }>();
  const navigate = useNavigate();
  const isNew = entityId === 'new';
  usePageTitle(isNew ? 'New Entity' : 'Entity Detail');

  const [entity, setEntity] = useState<EntityData | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(isNew);
  const [saving, setSaving] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [activeTab, setActiveTab] = useState<'aliases' | 'identifiers' | 'categories' | 'relationships' | 'locations'>('aliases');

  // Form
  const [form, setForm] = useState({ primary_name: '', entity_uri: '', type_key: '', description: '', status: 'active' });

  // Lookups
  const { items: entityTypes, error: typesError } = useEntityTypes();
  const { items: allCategories } = useCategories();
  const { items: relationshipTypes } = useRelationshipTypes();
  const [newCategoryKey, setNewCategoryKey] = useState('');
  const [categoryBusy, setCategoryBusy] = useState(false);

  // Relationships
  const [relationships, setRelationships] = useState<RelationshipItem[]>([]);
  const [relDirection, setRelDirection] = useState<'both' | 'outgoing' | 'incoming'>('both');
  const [relNames, setRelNames] = useState<Record<string, string>>({});
  const [newRelType, setNewRelType] = useState('');
  const [newRelTarget, setNewRelTarget] = useState<PickedEntity | null>(null);
  const [relBusy, setRelBusy] = useState(false);
  const relReqIdRef = useRef(0);

  // Identifiers / aliases — tag-style vocabularies, free text with suggestions
  const { names: namespaceSuggestions } = useIdentifierNamespaces();
  const { names: aliasTypeSuggestions } = useAliasTypes();
  const [newIdentifier, setNewIdentifier] = useState({ namespace: '', value: '' });
  const [newAlias, setNewAlias] = useState({ name: '', type: 'aka' });
  const [subBusy, setSubBusy] = useState(false);

  // Sub-data
  const [aliases, setAliases] = useState<{ alias_id: number; alias_name: string; alias_type: string; is_primary: boolean }[]>([]);
  const [identifiers, setIdentifiers] = useState<{ identifier_id: number; identifier_namespace: string; identifier_value: string; is_primary: boolean }[]>([]);
  const [categories, setCategories] = useState<{ entity_category_id: number; category_key: string; category_label: string | null }[]>([]);
  const [locations, setLocations] = useState<{ location_id: number; location_name: string | null; location_type_key: string; latitude: number | null; longitude: number | null; formatted_address: string | null }[]>([]);
  const [subLoading, setSubLoading] = useState(false);

  const fetchEntity = useCallback(async () => {
    if (!entityId || isNew) return;
    try {
      setLoading(true);
      const data = await apiService.getRegistryEntity(entityId);
      const e = data.entity || data;
      setEntity(e);
      setForm({
        primary_name: e.primary_name || '',
        entity_uri: e.entity_uri || '',
        type_key: e.type_key || '',
        description: e.description || '',
        status: e.status || 'active',
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entity');
    } finally {
      setLoading(false);
    }
  }, [entityId, isNew]);

  const fetchSubData = useCallback(async () => {
    if (!entityId || isNew) return;
    try {
      setSubLoading(true);
      const [aliasData, idData, catData, locData] = await Promise.allSettled([
        apiService.getEntityAliases(entityId),
        apiService.getEntityIdentifiers(entityId),
        apiService.getEntityCategories(entityId),
        apiService.getEntityLocations(entityId),
      ]);
      if (aliasData.status === 'fulfilled') setAliases(Array.isArray(aliasData.value) ? aliasData.value : aliasData.value.aliases || []);
      if (idData.status === 'fulfilled') setIdentifiers(Array.isArray(idData.value) ? idData.value : idData.value.identifiers || []);
      if (catData.status === 'fulfilled') setCategories(Array.isArray(catData.value) ? catData.value : catData.value.categories || []);
      if (locData.status === 'fulfilled') setLocations(Array.isArray(locData.value) ? locData.value : locData.value.locations || []);
    } finally {
      setSubLoading(false);
    }
  }, [entityId, isNew]);

  const fetchRelationships = useCallback(async () => {
    if (!entityId || isNew) return;
    // Changing the direction filter starts a new request while the previous one
    // may still be in flight; without this guard a slow earlier response can
    // land last and overwrite the filtered result.
    const reqId = ++relReqIdRef.current;
    try {
      const data = await apiService.getEntityRelationships(entityId, relDirection);
      if (reqId !== relReqIdRef.current) return;
      const rels: RelationshipItem[] = Array.isArray(data) ? data : data.relationships || [];
      setRelationships(rels);

      // The relationships endpoint returns endpoint IDs only, so resolve the
      // counterpart names separately to avoid rendering bare UUIDs.
      const counterparts = Array.from(new Set(
        rels.map(r => (r.entity_source === entityId ? r.entity_destination : r.entity_source)),
      )).filter(id => !(id in relNames));
      if (counterparts.length > 0) {
        const fetched = await Promise.allSettled(counterparts.map(id => apiService.getRegistryEntity(id)));
        const names: Record<string, string> = {};
        fetched.forEach((res, i) => {
          if (res.status === 'fulfilled') {
            const e = res.value.entity || res.value;
            if (e?.primary_name) names[counterparts[i]] = e.primary_name;
          }
        });
        if (Object.keys(names).length > 0) setRelNames(prev => ({ ...prev, ...names }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load relationships');
    }
    // relNames is read only to skip already-resolved IDs; including it would re-run on every resolve
  }, [entityId, isNew, relDirection]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchEntity(); }, [fetchEntity]);
  useEffect(() => { fetchSubData(); }, [fetchSubData]);
  useEffect(() => { fetchRelationships(); }, [fetchRelationships]);

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      if (isNew) {
        await apiService.createRegistryEntity(form);
        navigate('/entity-registry');
      } else {
        await apiService.updateRegistryEntity(entityId!, form);
        await fetchEntity();
        setIsEditing(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  /** Wrap a sub-resource mutation with busy state, error capture and refetch. */
  const runSubMutation = async (action: () => Promise<unknown>, failMessage: string) => {
    try {
      setSubBusy(true);
      setError(null);
      await action();
      await fetchSubData();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : failMessage);
      return false;
    } finally {
      setSubBusy(false);
    }
  };

  const handleAddIdentifier = async () => {
    if (!entityId || !newIdentifier.namespace.trim() || !newIdentifier.value.trim()) return;
    const ok = await runSubMutation(
      () => apiService.addEntityIdentifier(entityId, {
        identifier_namespace: newIdentifier.namespace.trim(),
        identifier_value: newIdentifier.value.trim(),
      }),
      'Failed to add identifier',
    );
    if (ok) setNewIdentifier({ namespace: '', value: '' });
  };

  const handleAddAlias = async () => {
    if (!entityId || !newAlias.name.trim()) return;
    const ok = await runSubMutation(
      () => apiService.addEntityAlias(entityId, {
        alias_name: newAlias.name.trim(),
        alias_type: newAlias.type.trim() || 'aka',
      }),
      'Failed to add alias',
    );
    if (ok) setNewAlias({ name: '', type: 'aka' });
  };

  const handleAddCategory = async () => {
    if (!entityId || !newCategoryKey) return;
    try {
      setCategoryBusy(true);
      setError(null);
      await apiService.addEntityCategory(entityId, newCategoryKey);
      setNewCategoryKey('');
      await fetchSubData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add category');
    } finally {
      setCategoryBusy(false);
    }
  };

  const handleRemoveCategory = async (categoryKey: string) => {
    if (!entityId) return;
    try {
      setCategoryBusy(true);
      setError(null);
      await apiService.removeEntityCategory(entityId, categoryKey);
      await fetchSubData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove category');
    } finally {
      setCategoryBusy(false);
    }
  };

  const handleAddRelationship = async () => {
    if (!entityId || !newRelType || !newRelTarget) return;
    try {
      setRelBusy(true);
      setError(null);
      await apiService.createEntityRelationship({
        entity_source: entityId,
        entity_destination: newRelTarget.entity_id,
        relationship_type_key: newRelType,
      });
      setNewRelType('');
      setNewRelTarget(null);
      await fetchRelationships();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add relationship');
    } finally {
      setRelBusy(false);
    }
  };

  const handleRemoveRelationship = async (relationshipId: number) => {
    try {
      setRelBusy(true);
      setError(null);
      await apiService.removeEntityRelationship(relationshipId);
      await fetchRelationships();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove relationship');
    } finally {
      setRelBusy(false);
    }
  };

  const handleDelete = async () => {
    try {
      await apiService.deleteRegistryEntity(entityId!);
      navigate('/entity-registry');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    }
    setShowDelete(false);
  };

  if (loading) return <div className="flex justify-center py-12"><Spinner size="xl" /></div>;
  if (error && !entity && !isNew) {
    return (
      <div className="space-y-4">
        <Alert color="failure">{error}</Alert>
        <Button size="sm" color="light" onClick={() => navigate('/entity-registry')}>Back</Button>
      </div>
    );
  }

  const assignedKeys = new Set(categories.map(c => c.category_key));
  const availableCategories = allCategories.filter(c => !assignedKeys.has(c.category_key));

  const tabBtn = (tab: typeof activeTab, icon: React.ReactNode, label: string) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        activeTab === tab
          ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
          : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
      }`}
    >
      {icon}{label}
    </button>
  );

  return (
    <div className="space-y-6" data-testid="entity-registry-detail-page">
      <Breadcrumb>
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/entity-registry" icon={HiCollection}>Entity Registry</BreadcrumbItem>
        <BreadcrumbItem>{isNew ? 'New Entity' : entity?.primary_name || entityId}</BreadcrumbItem>
      </Breadcrumb>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}
      {typesError && isEditing && <Alert color="warning">Entity types unavailable: {typesError}</Alert>}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Entity' : entity?.primary_name}
          </h1>
          {!isNew && entity && (
            <div className="flex items-center gap-2 mt-1">
              <Badge color="purple" size="sm">{entity.type_label || entity.type_key}</Badge>
              <Badge color={entity.status === 'active' ? 'success' : 'gray'} size="sm">{entity.status}</Badge>
            </div>
          )}
        </div>
        {!isNew && (
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <Button size="sm" color="blue" onClick={handleSave} disabled={saving}>
                  <HiSave className="mr-1.5 h-4 w-4" />{saving ? 'Saving...' : 'Save'}
                </Button>
                <Button size="sm" color="gray" onClick={() => setIsEditing(false)}><HiX className="mr-1.5 h-4 w-4" />Cancel</Button>
              </>
            ) : (
              <>
                <Button size="sm" color="blue" onClick={() => setIsEditing(true)}><HiPencil className="mr-1.5 h-4 w-4" />Edit</Button>
                <Button size="sm" color="failure" onClick={() => setShowDelete(true)}><HiTrash className="mr-1.5 h-4 w-4" />Delete</Button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Profile Card */}
      <Card>
        {isEditing ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl">
            <div>
              <Label htmlFor="name">Name *</Label>
              <TextInput id="name" value={form.primary_name} onChange={(e) => setForm(f => ({ ...f, primary_name: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="uri">Entity URI *</Label>
              <TextInput id="uri" value={form.entity_uri} onChange={(e) => setForm(f => ({ ...f, entity_uri: e.target.value }))} disabled={!isNew} />
            </div>
            <div>
              <Label htmlFor="type">Type *</Label>
              <Select
                id="type"
                data-testid="entity-type-select"
                value={form.type_key}
                onChange={(e) => setForm(f => ({ ...f, type_key: e.target.value }))}
              >
                <option value="">— Select a type —</option>
                {entityTypes.map(t => (
                  <option key={t.type_id} value={t.type_key}>{t.type_label || t.type_key}</option>
                ))}
                {/* Preserve a value the registry no longer lists rather than silently rewriting it */}
                {form.type_key && !entityTypes.some(t => t.type_key === form.type_key) && (
                  <option value={form.type_key}>{form.type_key} (unregistered)</option>
                )}
              </Select>
            </div>
            <div>
              <Label htmlFor="status">Status</Label>
              <Select
                id="status"
                data-testid="entity-status-select"
                value={form.status}
                onChange={(e) => setForm(f => ({ ...f, status: e.target.value }))}
              >
                {ENTITY_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                {form.status && !ENTITY_STATUSES.includes(form.status) && (
                  <option value={form.status}>{form.status}</option>
                )}
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="desc">Description</Label>
              <Textarea id="desc" rows={3} value={form.description} onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))} />
            </div>
            {isNew && (
              <div className="sm:col-span-2">
                <Button color="blue" onClick={handleSave} disabled={saving || !form.primary_name || !form.type_key}>
                  {saving ? 'Creating...' : 'Create Entity'}
                </Button>
              </div>
            )}
          </div>
        ) : entity && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><p className="text-sm font-medium text-gray-500">Name</p><p className="text-sm text-gray-900 dark:text-white">{entity.primary_name}</p></div>
            <div><p className="text-sm font-medium text-gray-500">URI</p><p className="text-sm text-gray-900 dark:text-white font-mono text-xs">{entity.entity_uri}</p></div>
            <div><p className="text-sm font-medium text-gray-500">Type</p><p className="text-sm text-gray-900 dark:text-white">{entity.type_label || entity.type_key || '—'}</p></div>
            <div><p className="text-sm font-medium text-gray-500">Status</p><Badge color={entity.status === 'active' ? 'success' : 'gray'} size="sm">{entity.status}</Badge></div>
            <div className="sm:col-span-2"><p className="text-sm font-medium text-gray-500">Description</p><p className="text-sm text-gray-900 dark:text-white">{entity.description || '—'}</p></div>
          </div>
        )}
      </Card>

      {/* Tabs (only for existing entities) */}
      {!isNew && entity && (
        <>
          <div className="border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
            <nav className="flex gap-4 min-w-max">
              {tabBtn('aliases', <HiTag className="h-4 w-4" />, `Aliases (${aliases.length})`)}
              {tabBtn('identifiers', <HiIdentification className="h-4 w-4" />, `Identifiers (${identifiers.length})`)}
              {tabBtn('categories', <HiFolder className="h-4 w-4" />, `Categories (${categories.length})`)}
              {tabBtn('relationships', <HiLink className="h-4 w-4" />, `Relationships (${relationships.length})`)}
              {tabBtn('locations', <HiLocationMarker className="h-4 w-4" />, `Locations (${locations.length})`)}
            </nav>
          </div>

          {subLoading ? (
            <div className="flex justify-center py-8"><Spinner size="lg" /></div>
          ) : (
            <Card>
              {activeTab === 'aliases' && (
                <div className="space-y-4" data-testid="aliases-tab">
                  <div className="flex flex-wrap gap-2 items-end">
                    <div className="w-64">
                      <Label htmlFor="alias-name">Alias name</Label>
                      <TextInput
                        id="alias-name"
                        data-testid="alias-name-input"
                        value={newAlias.name}
                        onChange={(e) => setNewAlias(a => ({ ...a, name: e.target.value }))}
                      />
                    </div>
                    <div className="w-48">
                      <Label htmlFor="alias-type">Type</Label>
                      <TagInput
                        id="alias-type"
                        data-testid="alias-type-input"
                        value={newAlias.type}
                        onChange={(v) => setNewAlias(a => ({ ...a, type: v }))}
                        suggestions={aliasTypeSuggestions}
                        placeholder="aka"
                      />
                    </div>
                    <Button size="sm" color="blue" data-testid="add-alias-button"
                            onClick={handleAddAlias} disabled={!newAlias.name.trim() || subBusy}>
                      <HiPlus className="mr-1.5 h-4 w-4" />Add
                    </Button>
                  </div>
                  {aliases.length === 0 ? <p className="text-sm text-gray-500">No aliases.</p> : (
                    <Table striped>
                      <TableHead><TableHeadCell>Name</TableHeadCell><TableHeadCell>Type</TableHeadCell><TableHeadCell>Primary</TableHeadCell><TableHeadCell>Actions</TableHeadCell></TableHead>
                      <TableBody>
                        {aliases.map(a => (
                          <TableRow key={a.alias_id}>
                            <TableCell>{a.alias_name}</TableCell>
                            <TableCell><Badge color="gray" size="xs">{a.alias_type}</Badge></TableCell>
                            <TableCell>{a.is_primary ? <Badge color="success" size="xs">Primary</Badge> : null}</TableCell>
                            <TableCell>
                              <Button size="xs" color="light" data-testid="remove-alias-button" disabled={subBusy}
                                      onClick={() => runSubMutation(() => apiService.removeEntityAlias(a.alias_id), 'Failed to remove alias')}>
                                <HiTrash className="h-3 w-3" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}
              {activeTab === 'identifiers' && (
                <div className="space-y-4" data-testid="identifiers-tab">
                  <div className="flex flex-wrap gap-2 items-end">
                    <div className="w-56">
                      <Label htmlFor="ident-ns">Namespace</Label>
                      <TagInput
                        id="ident-ns"
                        data-testid="identifier-namespace-input"
                        value={newIdentifier.namespace}
                        onChange={(v) => setNewIdentifier(i => ({ ...i, namespace: v }))}
                        suggestions={namespaceSuggestions}
                        placeholder="e.g. EIN, SF_LEAD_ID"
                      />
                    </div>
                    <div className="w-64">
                      <Label htmlFor="ident-value">Value</Label>
                      <TextInput
                        id="ident-value"
                        data-testid="identifier-value-input"
                        value={newIdentifier.value}
                        onChange={(e) => setNewIdentifier(i => ({ ...i, value: e.target.value }))}
                      />
                    </div>
                    <Button size="sm" color="blue" data-testid="add-identifier-button"
                            onClick={handleAddIdentifier}
                            disabled={!newIdentifier.namespace.trim() || !newIdentifier.value.trim() || subBusy}>
                      <HiPlus className="mr-1.5 h-4 w-4" />Add
                    </Button>
                  </div>
                  {identifiers.length === 0 ? <p className="text-sm text-gray-500">No identifiers.</p> : (
                    <Table striped>
                      <TableHead><TableHeadCell>Namespace</TableHeadCell><TableHeadCell>Value</TableHeadCell><TableHeadCell>Primary</TableHeadCell><TableHeadCell>Actions</TableHeadCell></TableHead>
                      <TableBody>
                        {identifiers.map(i => (
                          <TableRow key={i.identifier_id}>
                            <TableCell><Badge color="info" size="xs">{i.identifier_namespace}</Badge></TableCell>
                            <TableCell className="font-mono text-xs">{i.identifier_value}</TableCell>
                            <TableCell>{i.is_primary ? <Badge color="success" size="xs">Primary</Badge> : null}</TableCell>
                            <TableCell>
                              <Button size="xs" color="light" data-testid="remove-identifier-button" disabled={subBusy}
                                      onClick={() => runSubMutation(() => apiService.removeEntityIdentifier(i.identifier_id), 'Failed to remove identifier')}>
                                <HiTrash className="h-3 w-3" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}
              {activeTab === 'categories' && (
                <div className="space-y-4">
                  <div className="flex gap-2 items-end">
                    <div className="w-72">
                      <Label htmlFor="add-category">Assign category</Label>
                      <Select
                        id="add-category"
                        data-testid="add-category-select"
                        value={newCategoryKey}
                        onChange={(e) => setNewCategoryKey(e.target.value)}
                      >
                        <option value="">\u2014 Select a category \u2014</option>
                        {availableCategories.map(c => (
                          <option key={c.category_id} value={c.category_key}>{c.category_label || c.category_key}</option>
                        ))}
                      </Select>
                    </div>
                    <Button size="sm" color="blue" onClick={handleAddCategory} disabled={!newCategoryKey || categoryBusy}>
                      <HiPlus className="mr-1.5 h-4 w-4" />Add
                    </Button>
                  </div>
                  {categories.length === 0 ? <p className="text-sm text-gray-500">No categories.</p> : (
                    <Table striped>
                      <TableHead><TableHeadCell>Key</TableHeadCell><TableHeadCell>Label</TableHeadCell><TableHeadCell>Actions</TableHeadCell></TableHead>
                      <TableBody>
                        {categories.map(c => (
                          <TableRow key={c.entity_category_id}>
                            <TableCell className="font-mono text-xs">{c.category_key}</TableCell>
                            <TableCell>{c.category_label || '\u2014'}</TableCell>
                            <TableCell>
                              <Button size="xs" color="light" data-testid="remove-category-button" disabled={categoryBusy} onClick={() => handleRemoveCategory(c.category_key)}>
                                <HiTrash className="h-3 w-3" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}
              {activeTab === 'relationships' && (
                <div className="space-y-4" data-testid="relationships-tab">
                  {/* Create */}
                  <div className="flex flex-wrap gap-2 items-end">
                    <div className="w-64">
                      <Label htmlFor="rel-type">Relationship type</Label>
                      <Select
                        id="rel-type"
                        data-testid="relationship-type-select"
                        value={newRelType}
                        onChange={(e) => setNewRelType(e.target.value)}
                      >
                        <option value="">— Select a type —</option>
                        {relationshipTypes.map(rt => (
                          <option key={rt.relationship_type_id} value={rt.type_key}>
                            {rt.type_label || rt.type_key}
                            {rt.inverse_key ? ` (inverse: ${rt.inverse_key})` : ''}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <div className="w-72">
                      <Label htmlFor="rel-target">Target entity</Label>
                      <EntityPicker
                        id="rel-target"
                        data-testid="relationship-target-picker"
                        value={newRelTarget}
                        onChange={setNewRelTarget}
                        excludeIds={entityId ? [entityId] : []}
                        placeholder="Search for an entity..."
                      />
                    </div>
                    <Button
                      size="sm"
                      color="blue"
                      data-testid="add-relationship-button"
                      onClick={handleAddRelationship}
                      disabled={!newRelType || !newRelTarget || relBusy}
                    >
                      <HiPlus className="mr-1.5 h-4 w-4" />Add
                    </Button>
                  </div>

                  {/* Direction filter */}
                  <div className="w-48">
                    <Label htmlFor="rel-direction">Direction</Label>
                    <Select
                      id="rel-direction"
                      sizing="sm"
                      data-testid="relationship-direction-filter"
                      value={relDirection}
                      onChange={(e) => setRelDirection(e.target.value as typeof relDirection)}
                    >
                      <option value="both">Both</option>
                      <option value="outgoing">Outgoing</option>
                      <option value="incoming">Incoming</option>
                    </Select>
                  </div>

                  {relationships.length === 0 ? (
                    <p className="text-sm text-gray-500">No relationships.</p>
                  ) : (
                    <Table striped>
                      <TableHead>
                        <TableHeadCell>Direction</TableHeadCell>
                        <TableHeadCell>Type</TableHeadCell>
                        <TableHeadCell>Related entity</TableHeadCell>
                        <TableHeadCell>Status</TableHeadCell>
                        <TableHeadCell>Actions</TableHeadCell>
                      </TableHead>
                      <TableBody>
                        {relationships.map(r => {
                          const outgoing = r.entity_source === entityId;
                          const otherId = outgoing ? r.entity_destination : r.entity_source;
                          // An incoming edge reads as the inverse relation from this
                          // entity's side, so resolve inverse_key back to its label
                          // rather than showing the bare key.
                          const inverseLabel = r.inverse_key
                            ? relationshipTypes.find(rt => rt.type_key === r.inverse_key)?.type_label || r.inverse_key
                            : null;
                          const typeLabel = outgoing
                            ? (r.relationship_type_label || r.relationship_type_key)
                            : (inverseLabel || `${r.relationship_type_label || r.relationship_type_key} (inbound)`);
                          return (
                            <TableRow key={r.relationship_id}>
                              <TableCell>
                                {outgoing
                                  ? <HiArrowRight className="h-4 w-4 text-blue-500" title="Outgoing" />
                                  : <HiArrowLeft className="h-4 w-4 text-green-600" title="Incoming" />}
                              </TableCell>
                              <TableCell><Badge color="indigo" size="xs">{typeLabel}</Badge></TableCell>
                              <TableCell>
                                <button
                                  className="text-blue-600 hover:underline dark:text-blue-500"
                                  onClick={() => navigate(`/entity-registry/${otherId}`)}
                                >
                                  {relNames[otherId] || otherId}
                                </button>
                              </TableCell>
                              <TableCell>
                                <Badge color={r.is_current ? 'success' : 'gray'} size="xs">
                                  {r.is_current ? r.status : `${r.status} (expired)`}
                                </Badge>
                              </TableCell>
                              <TableCell>
                                <Button size="xs" color="light" data-testid="remove-relationship-button" disabled={relBusy} onClick={() => handleRemoveRelationship(r.relationship_id)}>
                                  <HiTrash className="h-3 w-3" />
                                </Button>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}
              {activeTab === 'locations' && (
                locations.length === 0 ? <p className="text-sm text-gray-500">No locations.</p> : (
                  <LocationsTabContent locations={locations} />
                )
              )}
            </Card>
          )}
        </>
      )}

      <ConfirmDialog
        open={showDelete}
        onConfirm={handleDelete}
        onCancel={() => setShowDelete(false)}
        title="Delete Entity"
        description={<>Permanently delete <strong>{entity?.primary_name}</strong> from the registry?</>}
        confirmLabel="Delete"
        variant="danger"
      />
    </div>
  );
};

export default EntityRegistryDetail;
