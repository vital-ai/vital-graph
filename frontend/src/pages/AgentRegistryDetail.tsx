import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Label, Spinner, TextInput, Textarea,
  Breadcrumb, BreadcrumbItem,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
} from 'flowbite-react';
import {
  HiHome, HiChip, HiPencil, HiTrash, HiSave, HiX,
  HiGlobe, HiCode, HiClipboardList,
} from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import ConfirmDialog from '../components/ConfirmDialog';
import TimeAgo from '../components/TimeAgo';

interface AgentData {
  agent_id: string;
  agent_uri: string;
  name: string;
  agent_type: string;
  description: string | null;
  status: string;
  version: string | null;
  created_time: string | null;
  updated_time: string | null;
}

interface Endpoint {
  endpoint_id: number;
  endpoint_uri: string;
  endpoint_url: string;
  protocol: string;
  status: string;
  notes: string | null;
}

interface AgentFunction {
  function_id: number;
  function_uri: string;
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
}

interface ChangelogEntry {
  id: number;
  change_type: string;
  field_name: string | null;
  old_value: string | null;
  new_value: string | null;
  changed_by: string | null;
  changed_at: string;
}

const statusBadge = (status: string) => {
  switch (status) {
    case 'active': return <Badge color="success" size="xs">Active</Badge>;
    case 'inactive': return <Badge color="gray" size="xs">Inactive</Badge>;
    case 'deprecated': return <Badge color="warning" size="xs">Deprecated</Badge>;
    case 'error': return <Badge color="failure" size="xs">Error</Badge>;
    default: return <Badge color="gray" size="xs">{status}</Badge>;
  }
};

const AgentRegistryDetail: React.FC = () => {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const isNew = agentId === 'new';
  usePageTitle(isNew ? 'New Agent' : 'Agent Detail');

  const [agent, setAgent] = useState<AgentData | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(isNew);
  const [saving, setSaving] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [activeTab, setActiveTab] = useState<'endpoints' | 'functions' | 'changelog'>('endpoints');

  // Form
  const [form, setForm] = useState({ name: '', agent_uri: '', agent_type: '', description: '', version: '', status: 'active' });

  // Sub-data
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [functions, setFunctions] = useState<AgentFunction[]>([]);
  const [changelog, setChangelog] = useState<ChangelogEntry[]>([]);
  const [subLoading, setSubLoading] = useState(false);

  const fetchAgent = useCallback(async () => {
    if (!agentId || isNew) return;
    try {
      setLoading(true);
      const data = await apiService.getAgent(agentId);
      const a = data.agent || data;
      setAgent(a);
      setForm({
        name: a.name || '',
        agent_uri: a.agent_uri || '',
        agent_type: a.agent_type || '',
        description: a.description || '',
        version: a.version || '',
        status: a.status || 'active',
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agent');
    } finally {
      setLoading(false);
    }
  }, [agentId, isNew]);

  const fetchSubData = useCallback(async () => {
    if (!agentId || isNew) return;
    try {
      setSubLoading(true);
      const [epData, fnData, clData] = await Promise.allSettled([
        apiService.getAgentEndpoints(agentId),
        apiService.getAgentFunctions(agentId),
        apiService.getAgentChangelog(agentId),
      ]);
      if (epData.status === 'fulfilled') setEndpoints(Array.isArray(epData.value) ? epData.value : []);
      if (fnData.status === 'fulfilled') setFunctions(Array.isArray(fnData.value) ? fnData.value : []);
      if (clData.status === 'fulfilled') setChangelog(clData.value.entries || []);
    } finally {
      setSubLoading(false);
    }
  }, [agentId, isNew]);

  useEffect(() => { fetchAgent(); }, [fetchAgent]);
  useEffect(() => { fetchSubData(); }, [fetchSubData]);

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      if (isNew) {
        await apiService.createAgent(form);
        navigate('/agent-registry');
      } else {
        await apiService.updateAgent(agentId!, form);
        await fetchAgent();
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
      await apiService.deleteAgent(agentId!);
      navigate('/agent-registry');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    }
    setShowDelete(false);
  };

  const handleStatusChange = async (newStatus: string) => {
    try {
      await apiService.changeAgentStatus(agentId!, newStatus);
      await fetchAgent();
      await fetchSubData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change status');
    }
  };

  if (loading) return <div className="flex justify-center py-12"><Spinner size="xl" /></div>;
  if (error && !agent && !isNew) {
    return (
      <div className="space-y-4">
        <Alert color="failure">{error}</Alert>
        <Button size="sm" color="light" onClick={() => navigate('/agent-registry')}>Back</Button>
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
        <BreadcrumbItem href="/agent-registry" icon={HiChip}>Agent Registry</BreadcrumbItem>
        <BreadcrumbItem>{isNew ? 'New Agent' : agent?.name || agentId}</BreadcrumbItem>
      </Breadcrumb>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isNew ? 'Register Agent' : agent?.name}
          </h1>
          {!isNew && agent && (
            <div className="flex items-center gap-2 mt-1">
              <Badge color="cyan" size="sm">{agent.agent_type}</Badge>
              {statusBadge(agent.status)}
              {agent.version && <Badge color="gray" size="sm">v{agent.version}</Badge>}
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
                {agent?.status === 'active' && (
                  <Button size="sm" color="warning" onClick={() => handleStatusChange('inactive')}>Deactivate</Button>
                )}
                {agent?.status === 'inactive' && (
                  <Button size="sm" color="success" onClick={() => handleStatusChange('active')}>Activate</Button>
                )}
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
              <Label htmlFor="uri">Agent URI *</Label>
              <TextInput id="uri" value={form.agent_uri} onChange={(e) => setForm(f => ({ ...f, agent_uri: e.target.value }))} disabled={!isNew} />
            </div>
            <div>
              <Label htmlFor="type">Type</Label>
              <TextInput id="type" value={form.agent_type} onChange={(e) => setForm(f => ({ ...f, agent_type: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="version">Version</Label>
              <TextInput id="version" value={form.version} onChange={(e) => setForm(f => ({ ...f, version: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="desc">Description</Label>
              <Textarea id="desc" rows={3} value={form.description} onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))} />
            </div>
            {isNew && (
              <div className="sm:col-span-2">
                <Button color="blue" onClick={handleSave} disabled={saving || !form.name || !form.agent_uri}>
                  {saving ? 'Creating...' : 'Register Agent'}
                </Button>
              </div>
            )}
          </div>
        ) : agent && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><p className="text-sm font-medium text-gray-500">Name</p><p className="text-sm text-gray-900 dark:text-white">{agent.name}</p></div>
            <div><p className="text-sm font-medium text-gray-500">URI</p><p className="text-xs text-gray-900 dark:text-white font-mono">{agent.agent_uri}</p></div>
            <div><p className="text-sm font-medium text-gray-500">Type</p><p className="text-sm text-gray-900 dark:text-white">{agent.agent_type}</p></div>
            <div><p className="text-sm font-medium text-gray-500">Version</p><p className="text-sm text-gray-900 dark:text-white">{agent.version || '—'}</p></div>
            <div className="sm:col-span-2"><p className="text-sm font-medium text-gray-500">Description</p><p className="text-sm text-gray-900 dark:text-white">{agent.description || '—'}</p></div>
          </div>
        )}
      </Card>

      {/* Tabs */}
      {!isNew && agent && (
        <>
          <div className="border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
            <nav className="flex gap-4 min-w-max">
              {tabBtn('endpoints', <HiGlobe className="h-4 w-4" />, `Endpoints (${endpoints.length})`)}
              {tabBtn('functions', <HiCode className="h-4 w-4" />, `Functions (${functions.length})`)}
              {tabBtn('changelog', <HiClipboardList className="h-4 w-4" />, `Changelog (${changelog.length})`)}
            </nav>
          </div>

          {subLoading ? (
            <div className="flex justify-center py-8"><Spinner size="lg" /></div>
          ) : (
            <Card>
              {activeTab === 'endpoints' && (
                endpoints.length === 0 ? <p className="text-sm text-gray-500">No endpoints configured.</p> : (
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>URI</TableHeadCell>
                      <TableHeadCell>URL</TableHeadCell>
                      <TableHeadCell>Protocol</TableHeadCell>
                      <TableHeadCell>Status</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {endpoints.map(ep => (
                        <TableRow key={ep.endpoint_id}>
                          <TableCell className="font-mono text-xs">{ep.endpoint_uri}</TableCell>
                          <TableCell className="text-sm text-blue-600">{ep.endpoint_url}</TableCell>
                          <TableCell><Badge color="gray" size="xs">{ep.protocol}</Badge></TableCell>
                          <TableCell>{statusBadge(ep.status)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )
              )}

              {activeTab === 'functions' && (
                functions.length === 0 ? <p className="text-sm text-gray-500">No functions registered.</p> : (
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>Name</TableHeadCell>
                      <TableHeadCell>URI</TableHeadCell>
                      <TableHeadCell>Description</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {functions.map(fn => (
                        <TableRow key={fn.function_id}>
                          <TableCell className="font-medium text-gray-900 dark:text-white">{fn.name}</TableCell>
                          <TableCell className="font-mono text-xs text-gray-500">{fn.function_uri}</TableCell>
                          <TableCell className="text-sm text-gray-500 max-w-[250px] truncate">{fn.description || '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )
              )}

              {activeTab === 'changelog' && (
                changelog.length === 0 ? <p className="text-sm text-gray-500">No changelog entries.</p> : (
                  <Table striped>
                    <TableHead>
                      <TableHeadCell>Time</TableHeadCell>
                      <TableHeadCell>Change</TableHeadCell>
                      <TableHeadCell>Field</TableHeadCell>
                      <TableHeadCell>Old</TableHeadCell>
                      <TableHeadCell>New</TableHeadCell>
                      <TableHeadCell>By</TableHeadCell>
                    </TableHead>
                    <TableBody>
                      {changelog.map(entry => (
                        <TableRow key={entry.id}>
                          <TableCell className="text-xs text-gray-500"><TimeAgo date={entry.changed_at} /></TableCell>
                          <TableCell><Badge color="info" size="xs">{entry.change_type}</Badge></TableCell>
                          <TableCell className="text-sm">{entry.field_name || '—'}</TableCell>
                          <TableCell className="text-xs text-gray-500 max-w-[100px] truncate">{entry.old_value || '—'}</TableCell>
                          <TableCell className="text-xs text-gray-500 max-w-[100px] truncate">{entry.new_value || '—'}</TableCell>
                          <TableCell className="text-sm">{entry.changed_by || '—'}</TableCell>
                        </TableRow>
                      ))}
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
        title="Delete Agent"
        description={<>Permanently delete agent <strong>{agent?.name}</strong>?</>}
        confirmLabel="Delete"
        variant="danger"
      />
    </div>
  );
};

export default AgentRegistryDetail;
