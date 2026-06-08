import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Label, Spinner, TextInput, Textarea,
  Breadcrumb, BreadcrumbItem,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
} from 'flowbite-react';
import {
  HiHome, HiCollection, HiPencil, HiTrash, HiSave, HiX,
  HiTag, HiIdentification, HiFolder, HiLocationMarker,
} from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import ConfirmDialog from '../components/ConfirmDialog';

interface EntityData {
  entity_id: string;
  entity_uri: string;
  name: string;
  entity_type: string;
  description: string | null;
  status: string;
  source: string | null;
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
  const [activeTab, setActiveTab] = useState<'aliases' | 'identifiers' | 'categories' | 'locations'>('aliases');

  // Form
  const [form, setForm] = useState({ name: '', entity_uri: '', entity_type: '', description: '', status: 'active' });

  // Sub-data
  const [aliases, setAliases] = useState<{ alias_id: number; alias: string; language: string }[]>([]);
  const [identifiers, setIdentifiers] = useState<{ identifier_id: number; scheme: string; value: string }[]>([]);
  const [categories, setCategories] = useState<{ category_id: number; category: string; source: string }[]>([]);
  const [locations, setLocations] = useState<{ location_id: number; latitude: number; longitude: number; label: string }[]>([]);
  const [subLoading, setSubLoading] = useState(false);

  const fetchEntity = useCallback(async () => {
    if (!entityId || isNew) return;
    try {
      setLoading(true);
      const data = await apiService.getRegistryEntity(entityId);
      const e = data.entity || data;
      setEntity(e);
      setForm({
        name: e.name || '',
        entity_uri: e.entity_uri || '',
        entity_type: e.entity_type || '',
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
      if (aliasData.status === 'fulfilled') setAliases(aliasData.value.aliases || []);
      if (idData.status === 'fulfilled') setIdentifiers(idData.value.identifiers || []);
      if (catData.status === 'fulfilled') setCategories(catData.value.categories || []);
      if (locData.status === 'fulfilled') setLocations(locData.value.locations || []);
    } finally {
      setSubLoading(false);
    }
  }, [entityId, isNew]);

  useEffect(() => { fetchEntity(); }, [fetchEntity]);
  useEffect(() => { fetchSubData(); }, [fetchSubData]);

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
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/entity-registry" icon={HiCollection}>Entity Registry</BreadcrumbItem>
        <BreadcrumbItem>{isNew ? 'New Entity' : entity?.name || entityId}</BreadcrumbItem>
      </Breadcrumb>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Create Entity' : entity?.name}
          </h1>
          {!isNew && entity && (
            <div className="flex items-center gap-2 mt-1">
              <Badge color="purple" size="sm">{entity.entity_type}</Badge>
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
              <TextInput id="name" value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="uri">Entity URI *</Label>
              <TextInput id="uri" value={form.entity_uri} onChange={(e) => setForm(f => ({ ...f, entity_uri: e.target.value }))} disabled={!isNew} />
            </div>
            <div>
              <Label htmlFor="type">Type</Label>
              <TextInput id="type" value={form.entity_type} onChange={(e) => setForm(f => ({ ...f, entity_type: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="status">Status</Label>
              <TextInput id="status" value={form.status} onChange={(e) => setForm(f => ({ ...f, status: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="desc">Description</Label>
              <Textarea id="desc" rows={3} value={form.description} onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))} />
            </div>
            {isNew && (
              <div className="sm:col-span-2">
                <Button color="blue" onClick={handleSave} disabled={saving || !form.name || !form.entity_uri}>
                  {saving ? 'Creating...' : 'Create Entity'}
                </Button>
              </div>
            )}
          </div>
        ) : entity && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><p className="text-sm font-medium text-gray-500">Name</p><p className="text-sm text-gray-900 dark:text-white">{entity.name}</p></div>
            <div><p className="text-sm font-medium text-gray-500">URI</p><p className="text-sm text-gray-900 dark:text-white font-mono text-xs">{entity.entity_uri}</p></div>
            <div><p className="text-sm font-medium text-gray-500">Type</p><p className="text-sm text-gray-900 dark:text-white">{entity.entity_type}</p></div>
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
              {tabBtn('locations', <HiLocationMarker className="h-4 w-4" />, `Locations (${locations.length})`)}
            </nav>
          </div>

          {subLoading ? (
            <div className="flex justify-center py-8"><Spinner size="lg" /></div>
          ) : (
            <Card>
              {activeTab === 'aliases' && (
                aliases.length === 0 ? <p className="text-sm text-gray-500">No aliases.</p> : (
                  <Table striped>
                    <TableHead><TableHeadCell>Alias</TableHeadCell><TableHeadCell>Language</TableHeadCell></TableHead>
                    <TableBody>
                      {aliases.map(a => <TableRow key={a.alias_id}><TableCell>{a.alias}</TableCell><TableCell><Badge color="gray" size="xs">{a.language}</Badge></TableCell></TableRow>)}
                    </TableBody>
                  </Table>
                )
              )}
              {activeTab === 'identifiers' && (
                identifiers.length === 0 ? <p className="text-sm text-gray-500">No identifiers.</p> : (
                  <Table striped>
                    <TableHead><TableHeadCell>Scheme</TableHeadCell><TableHeadCell>Value</TableHeadCell></TableHead>
                    <TableBody>
                      {identifiers.map(i => <TableRow key={i.identifier_id}><TableCell><Badge color="info" size="xs">{i.scheme}</Badge></TableCell><TableCell className="font-mono text-xs">{i.value}</TableCell></TableRow>)}
                    </TableBody>
                  </Table>
                )
              )}
              {activeTab === 'categories' && (
                categories.length === 0 ? <p className="text-sm text-gray-500">No categories.</p> : (
                  <Table striped>
                    <TableHead><TableHeadCell>Category</TableHeadCell><TableHeadCell>Source</TableHeadCell></TableHead>
                    <TableBody>
                      {categories.map(c => <TableRow key={c.category_id}><TableCell>{c.category}</TableCell><TableCell className="text-xs text-gray-500">{c.source}</TableCell></TableRow>)}
                    </TableBody>
                  </Table>
                )
              )}
              {activeTab === 'locations' && (
                locations.length === 0 ? <p className="text-sm text-gray-500">No locations.</p> : (
                  <Table striped>
                    <TableHead><TableHeadCell>Label</TableHeadCell><TableHeadCell>Latitude</TableHeadCell><TableHeadCell>Longitude</TableHeadCell></TableHead>
                    <TableBody>
                      {locations.map(l => <TableRow key={l.location_id}><TableCell>{l.label}</TableCell><TableCell className="font-mono text-xs">{l.latitude}</TableCell><TableCell className="font-mono text-xs">{l.longitude}</TableCell></TableRow>)}
                    </TableBody>
                  </Table>
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
        description={<>Permanently delete <strong>{entity?.name}</strong> from the registry?</>}
        confirmLabel="Delete"
        variant="danger"
      />
    </div>
  );
};

export default EntityRegistryDetail;
