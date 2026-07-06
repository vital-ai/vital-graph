import React, { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Label, Modal, ModalHeader, ModalBody, ModalFooter,
  Select, Spinner, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
  TextInput,
} from 'flowbite-react';
import { HiKey, HiPlus, HiTrash, HiClipboardCopy, HiExclamationCircle, HiCheck } from 'react-icons/hi';

interface ApiKey {
  key_id: string;
  prefix: string;
  name: string;
  username: string;
  is_active: boolean;
  created_time: string | null;
  last_used: string | null;
  expires_at: string | null;
}

const ApiKeys: React.FC = () => {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create dialog state
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyExpiry, setNewKeyExpiry] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Created key reveal state
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Revoke confirmation state
  const [revokingKey, setRevokingKey] = useState<ApiKey | null>(null);

  const fetchKeys = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.listApiKeys();
      setKeys(data.keys || []);
    } catch {
      setError('Failed to load API keys.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchKeys(); }, [fetchKeys]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);

    if (!newKeyName.trim()) {
      setCreateError('Key name is required');
      return;
    }

    try {
      setCreating(true);
      const expiryDays = newKeyExpiry ? parseInt(newKeyExpiry) : undefined;
      const result = await apiService.createApiKey(newKeyName.trim(), expiryDays);
      setCreatedKey(result.key);
      setShowCreate(false);
      setNewKeyName('');
      setNewKeyExpiry('');
      await fetchKeys();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create key');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (key: ApiKey) => {
    try {
      await apiService.revokeApiKey(key.key_id);
      setRevokingKey(null);
      await fetchKeys();
    } catch {
      setError('Failed to revoke key.');
      setRevokingKey(null);
    }
  };

  const handleCopyKey = async () => {
    if (createdKey) {
      await navigator.clipboard.writeText(createdKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  };

  return (
    <div className="space-y-5" data-testid="api-keys-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <HiKey className="h-6 w-6" />
            API Keys
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            Manage API keys for programmatic access. Keys use the <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">vg_</code> prefix.
          </p>
        </div>
        <Button size="sm" color="blue" onClick={() => setShowCreate(true)}>
          <HiPlus className="mr-1.5 h-4 w-4" />Create Key
        </Button>
      </div>

      {error && <Alert color="failure">{error}</Alert>}

      {/* Created key reveal */}
      {createdKey && (
        <Alert color="success" onDismiss={() => { setCreatedKey(null); setCopied(false); }}>
          <div className="space-y-2">
            <p className="font-medium">API key created successfully!</p>
            <p className="text-xs">Copy this key now — it cannot be retrieved again.</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700 rounded px-3 py-2 text-sm font-mono break-all select-all">
                {createdKey}
              </code>
              <Button size="xs" color="light" onClick={handleCopyKey}>
                {copied ? <HiCheck className="h-4 w-4 text-green-600" /> : <HiClipboardCopy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </Alert>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {/* Empty state */}
      {!loading && keys.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiKey className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">No API keys</p>
          <p className="text-sm mt-1">Create your first API key for programmatic access</p>
        </div>
      )}

      {/* Keys table */}
      {!loading && keys.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <Table striped>
            <TableHead>
              <TableHeadCell>Name</TableHeadCell>
              <TableHeadCell>Prefix</TableHeadCell>
              <TableHeadCell>Status</TableHeadCell>
              <TableHeadCell>Created</TableHeadCell>
              <TableHeadCell>Last Used</TableHeadCell>
              <TableHeadCell>Expires</TableHeadCell>
              <TableHeadCell className="w-20"></TableHeadCell>
            </TableHead>
            <TableBody>
              {keys.map((key) => (
                <TableRow key={key.key_id}>
                  <TableCell className="font-medium text-gray-900 dark:text-white">
                    {key.name}
                  </TableCell>
                  <TableCell>
                    <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">{key.prefix}</code>
                  </TableCell>
                  <TableCell>
                    {key.is_active ? (
                      <Badge color="success" size="sm">Active</Badge>
                    ) : (
                      <Badge color="gray" size="sm">Revoked</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-gray-500">{formatDate(key.created_time)}</TableCell>
                  <TableCell className="text-xs text-gray-500">{formatDate(key.last_used)}</TableCell>
                  <TableCell className="text-xs text-gray-500">{formatDate(key.expires_at)}</TableCell>
                  <TableCell>
                    {key.is_active && (
                      <Button size="xs" color="failure" onClick={() => setRevokingKey(key)}>
                        <HiTrash className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create Key Modal */}
      <Modal show={showCreate} onClose={() => { setShowCreate(false); setCreateError(null); }} size="md">
        <ModalHeader>Create API Key</ModalHeader>
        <form onSubmit={handleCreate}>
          <ModalBody>
            <div className="space-y-4">
              {createError && (
                <Alert color="failure" icon={HiExclamationCircle}>{createError}</Alert>
              )}
              <div>
                <Label htmlFor="key-name">Key Name</Label>
                <TextInput
                  id="key-name"
                  placeholder="e.g. CI/CD Pipeline"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  required
                />
              </div>
              <div>
                <Label htmlFor="key-expiry">Expiry</Label>
                <Select id="key-expiry" value={newKeyExpiry} onChange={(e) => setNewKeyExpiry(e.target.value)}>
                  <option value="">Never expires</option>
                  <option value="30">30 days</option>
                  <option value="90">90 days</option>
                  <option value="180">180 days</option>
                  <option value="365">1 year</option>
                </Select>
              </div>
            </div>
          </ModalBody>
          <ModalFooter>
            <Button type="submit" color="blue" disabled={creating}>
              {creating ? <><Spinner size="sm" className="mr-2" />Creating...</> : 'Create Key'}
            </Button>
            <Button color="gray" onClick={() => { setShowCreate(false); setCreateError(null); }} disabled={creating}>
              Cancel
            </Button>
          </ModalFooter>
        </form>
      </Modal>

      {/* Revoke Confirmation Modal */}
      <Modal show={!!revokingKey} onClose={() => setRevokingKey(null)} size="md">
        <ModalHeader>Revoke API Key</ModalHeader>
        <ModalBody>
          <p className="text-gray-600 dark:text-gray-300">
            Are you sure you want to revoke <span className="font-semibold">{revokingKey?.name}</span>?
            This action cannot be undone. Any applications using this key will lose access immediately.
          </p>
        </ModalBody>
        <ModalFooter>
          <Button color="failure" onClick={() => revokingKey && handleRevoke(revokingKey)}>
            Revoke Key
          </Button>
          <Button color="gray" onClick={() => setRevokingKey(null)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default ApiKeys;
