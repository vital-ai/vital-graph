import React, { useState, useEffect, useCallback } from 'react';
import {
  Alert, Badge, Button, Card, Label, Spinner, TextInput, Textarea,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
} from 'flowbite-react';
import {
  HiPlus, HiTag, HiCollection, HiFolder, HiLink, HiLocationMarker, HiIdentification,
  HiTrash, HiEye, HiEyeOff,
} from 'react-icons/hi';
import { apiService } from '../services/ApiService';
import { usePageTitle } from '../hooks/usePageTitle';
import { invalidateRegistryLookups } from '../hooks/useRegistryLookups';
import ConfirmDialog from '../components/ConfirmDialog';

interface MetadataRow {
  key: string;
  label: string;
  description: string | null;
  inverse_key: string | null;
  is_active: boolean;
  usage_count: number;
}

// API kind slugs (also used as tab ids and testids).
type Kind =
  | 'entity-types' | 'categories' | 'relationship-types'
  | 'location-types' | 'identifier-types' | 'alias-types';

const KINDS: { id: Kind; label: string; singular: string; icon: React.ReactNode }[] = [
  { id: 'entity-types', label: 'Entity Types', singular: 'Entity Type', icon: <HiCollection className="h-4 w-4" /> },
  { id: 'categories', label: 'Categories', singular: 'Category', icon: <HiFolder className="h-4 w-4" /> },
  { id: 'relationship-types', label: 'Relationship Types', singular: 'Relationship Type', icon: <HiLink className="h-4 w-4" /> },
  { id: 'location-types', label: 'Location Types', singular: 'Location Type', icon: <HiLocationMarker className="h-4 w-4" /> },
  { id: 'identifier-types', label: 'Identifier Types', singular: 'Identifier Type', icon: <HiIdentification className="h-4 w-4" /> },
  { id: 'alias-types', label: 'Alias Types', singular: 'Alias Type', icon: <HiTag className="h-4 w-4" /> },
];

// Machine key: letters, digits, underscore, dot, dash. Allows both the
// lowercase FK-table convention (lead_new) and the uppercase namespace
// convention (SF_LEAD_ID, EIN).
const KEY_PATTERN = /^[A-Za-z0-9_.-]{1,255}$/;

const emptyForm = { key: '', label: '', description: '', inverse_key: '' };

const RegistryMetadata: React.FC = () => {
  usePageTitle('Registry Metadata');

  const [rows, setRows] = useState<Record<string, MetadataRow[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activeKind, setActiveKind] = useState<Kind>('entity-types');

  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // One targeted call per kind (replaces the old single summary call).
  const fetchAll = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const results = await Promise.all(
        KINDS.map(k => apiService.listRegistryMetadata(k.id, { includeUsage: true, includeInactive: true })),
      );
      const map: Record<string, MetadataRow[]> = {};
      KINDS.forEach((k, i) => { map[k.id] = (results[i] as MetadataRow[]) || []; });
      setRows(map);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load registry metadata');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const resetForm = () => setForm(emptyForm);
  const active = KINDS.find(k => k.id === activeKind)!;
  const activeRows = rows[activeKind] || [];
  const keyValid = KEY_PATTERN.test(form.key);
  const canSubmit = keyValid && form.label.trim().length > 0 && !saving;

  const handleCreate = async () => {
    setConfirmOpen(false);
    try {
      setSaving(true);
      setError(null);
      await apiService.createRegistryMetadata(activeKind, {
        key: form.key,
        label: form.label,
        description: form.description || undefined,
        inverse_key: activeKind === 'relationship-types' ? (form.inverse_key || undefined) : undefined,
      });
      invalidateRegistryLookups();
      setNotice(`Created "${form.key}".`);
      resetForm();
      await fetchAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (row: MetadataRow) => {
    try {
      setError(null);
      await apiService.updateRegistryMetadata(activeKind, row.key, { is_active: !row.is_active });
      invalidateRegistryLookups();
      await fetchAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  const handleDelete = async () => {
    const key = deleteTarget;
    setDeleteTarget(null);
    if (!key) return;
    try {
      setError(null);
      await apiService.deleteRegistryMetadata(activeKind, key);
      invalidateRegistryLookups();
      setNotice(`Deleted "${key}".`);
      await fetchAll();
    } catch (err) {
      // The server returns 409 with a usage count when the value is in use.
      const msg = err instanceof Error ? err.message : String(err);
      setError(/in_use|409|in use/i.test(msg)
        ? `Cannot delete "${key}" — it is still in use. Deactivate it instead to hide it from pickers.`
        : msg);
    }
  };

  const isRel = activeKind === 'relationship-types';

  return (
    <div className="space-y-6" data-testid="registry-metadata-page">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
          <HiTag className="h-6 w-6 text-indigo-600" />
          Registry Metadata
        </h2>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
          Shared vocabularies for the entity registry. These are global — every entity
          in this database draws on the same set. A value in use cannot be deleted;
          deactivate it to hide it from pickers.
        </p>
      </div>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}
      {notice && <Alert color="success" onDismiss={() => setNotice(null)}>{notice}</Alert>}

      <div className="border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
        <nav className="flex gap-2 min-w-max">
          {KINDS.map(k => (
            <button
              key={k.id}
              onClick={() => { setActiveKind(k.id); resetForm(); setError(null); }}
              data-testid={`metadata-tab-${k.id}`}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeKind === k.id
                  ? 'border-blue-600 text-blue-600 dark:border-blue-500 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
              }`}
            >
              {k.icon}{k.label} ({(rows[k.id] || []).length})
            </button>
          ))}
        </nav>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      ) : (
        <>
          {/* Add form */}
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Add {active.singular}</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="meta-key">Key *</Label>
                <TextInput
                  id="meta-key"
                  data-testid="metadata-key-input"
                  placeholder="e.g. lead_new or SF_LEAD_ID"
                  value={form.key}
                  onChange={(e) => setForm(f => ({ ...f, key: e.target.value }))}
                  color={form.key && !keyValid ? 'failure' : undefined}
                />
                <p className={`mt-1 text-xs ${form.key && !keyValid ? 'text-red-600' : 'text-gray-500'}`}>
                  {form.key && !keyValid
                    ? 'Letters, digits, _ . - only (no spaces).'
                    : 'Permanent — the key cannot be renamed. It can be deactivated or, if unused, deleted.'}
                </p>
              </div>
              <div>
                <Label htmlFor="meta-label">Label *</Label>
                <TextInput
                  id="meta-label"
                  data-testid="metadata-label-input"
                  placeholder="Human readable name"
                  value={form.label}
                  onChange={(e) => setForm(f => ({ ...f, label: e.target.value }))}
                />
              </div>
              {isRel && (
                <div>
                  <Label htmlFor="meta-inverse">Inverse key</Label>
                  <TextInput
                    id="meta-inverse"
                    data-testid="metadata-inverse-input"
                    placeholder="e.g. owned_by"
                    value={form.inverse_key}
                    onChange={(e) => setForm(f => ({ ...f, inverse_key: e.target.value }))}
                  />
                  <p className="mt-1 text-xs text-gray-500">How the relation reads from the other side.</p>
                </div>
              )}
              <div className="sm:col-span-2">
                <Label htmlFor="meta-desc">Description</Label>
                <Textarea
                  id="meta-desc"
                  rows={2}
                  value={form.description}
                  onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div>
                <Button color="blue" data-testid="metadata-create-button" disabled={!canSubmit} onClick={() => setConfirmOpen(true)}>
                  <HiPlus className="mr-1.5 h-4 w-4" />{saving ? 'Creating...' : 'Create'}
                </Button>
              </div>
            </div>
          </Card>

          {/* Existing rows */}
          <Card>
            {activeRows.length === 0 ? (
              <p className="text-sm text-gray-500">None defined.</p>
            ) : (
              <Table striped>
                <TableHead>
                  <TableHeadCell>Key</TableHeadCell>
                  <TableHeadCell>Label</TableHeadCell>
                  {isRel && <TableHeadCell>Inverse</TableHeadCell>}
                  <TableHeadCell>Description</TableHeadCell>
                  <TableHeadCell>Usage</TableHeadCell>
                  <TableHeadCell>Status</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableHead>
                <TableBody>
                  {activeRows.map(r => (
                    <TableRow key={r.key} data-testid={`metadata-row-${r.key}`} className={r.is_active ? '' : 'opacity-60'}>
                      <TableCell className="font-mono text-xs text-gray-900 dark:text-white">{r.key}</TableCell>
                      <TableCell>{r.label}</TableCell>
                      {isRel && <TableCell className="font-mono text-xs text-gray-500">{r.inverse_key || '—'}</TableCell>}
                      <TableCell className="text-sm text-gray-500 max-w-[280px] truncate">{r.description || '—'}</TableCell>
                      <TableCell>
                        {r.usage_count > 0
                          ? r.usage_count.toLocaleString()
                          : <span className="text-gray-400">unused</span>}
                      </TableCell>
                      <TableCell>
                        {r.is_active
                          ? <Badge color="success" size="xs">Active</Badge>
                          : <Badge color="gray" size="xs">Inactive</Badge>}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button size="xs" color="light" data-testid="metadata-toggle-active"
                                  title={r.is_active ? 'Deactivate (hide from pickers)' : 'Reactivate'}
                                  onClick={() => toggleActive(r)}>
                            {r.is_active ? <HiEyeOff className="h-3 w-3" /> : <HiEye className="h-3 w-3" />}
                          </Button>
                          <Button size="xs" color="light" data-testid="metadata-delete-button"
                                  title={r.usage_count > 0 ? 'In use — cannot delete' : 'Delete'}
                                  disabled={r.usage_count > 0}
                                  onClick={() => setDeleteTarget(r.key)}>
                            <HiTrash className="h-3 w-3" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onConfirm={handleCreate}
        onCancel={() => setConfirmOpen(false)}
        title={`Create ${active.singular}`}
        description={
          <>
            Create <strong>{form.key}</strong> ("{form.label}")? This is available to every
            entity in this database. The key cannot be renamed afterwards, though it can be
            deactivated or deleted while unused.
          </>
        }
        confirmLabel="Create"
        variant="warning"
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        title={`Delete ${active.singular}`}
        description={<>Permanently delete <strong>{deleteTarget}</strong>? This cannot be undone.</>}
        confirmLabel="Delete"
        variant="danger"
      />
    </div>
  );
};

export default RegistryMetadata;
