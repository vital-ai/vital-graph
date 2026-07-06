import React, { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Label, Modal, ModalHeader, ModalBody, ModalFooter,
  Select, Spinner, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
} from 'flowbite-react';
import {
  HiCog, HiRefresh, HiCheckCircle, HiXCircle, HiClock,
  HiPlay, HiStatusOnline, HiDatabase,
} from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import TimeAgo from '../components/TimeAgo';

interface Process {
  process_id: string;
  process_type: string;
  process_subtype: string | null;
  status: string;
  progress_percent: number | null;
  progress_message: string | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

interface SchedulerStatus {
  enabled: boolean;
  running: boolean;
  jobs: Record<string, unknown>;
  active_locks: number;
}

const Admin: React.FC = () => {
  usePageTitle('Administration');
  // Health
  const [healthStatus, setHealthStatus] = useState<string | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  // Cache stats
  const [cacheStats, setCacheStats] = useState<Record<string, unknown> | null>(null);
  const [cacheLoading, setCacheLoading] = useState(false);

  // Scheduler
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [schedulerLoading, setSchedulerLoading] = useState(false);

  // Processes
  const [processes, setProcesses] = useState<Process[]>([]);
  const [processesLoading, setProcessesLoading] = useState(false);

  // Resync
  const [showResync, setShowResync] = useState(false);
  const [resyncSpace, setResyncSpace] = useState('');
  const [resyncLoading, setResyncLoading] = useState(false);
  const [resyncResult, setResyncResult] = useState<string | null>(null);

  // Trigger
  const [showTrigger, setShowTrigger] = useState(false);
  const [triggerType, setTriggerType] = useState('analyze');
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerResult, setTriggerResult] = useState<string | null>(null);

  // Spaces for resync picker
  const [spaces, setSpaces] = useState<{ id: string; name: string }[]>([]);

  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      setHealthLoading(true);
      const data = await apiService.healthCheck();
      setHealthStatus(data.status);
    } catch {
      setHealthStatus('error');
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const fetchCache = useCallback(async () => {
    try {
      setCacheLoading(true);
      const data = await apiService.cacheStats();
      setCacheStats(data.entity_graph_cache || data);
    } catch {
      setCacheStats(null);
    } finally {
      setCacheLoading(false);
    }
  }, []);

  const fetchScheduler = useCallback(async () => {
    try {
      setSchedulerLoading(true);
      const data = await apiService.getSchedulerStatus();
      setScheduler(data);
    } catch {
      setScheduler(null);
    } finally {
      setSchedulerLoading(false);
    }
  }, []);

  const fetchProcesses = useCallback(async () => {
    try {
      setProcessesLoading(true);
      const data = await apiService.listProcesses({ limit: 20 });
      setProcesses(data.processes || []);
    } catch {
      setProcesses([]);
    } finally {
      setProcessesLoading(false);
    }
  }, []);

  const fetchSpaces = useCallback(async () => {
    try {
      const list = await apiService.getSpaces() as { space?: string; space_name?: string }[];
      setSpaces(list.map((s) => ({ id: s.space || '', name: s.space_name || s.space || '' })));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    fetchCache();
    fetchScheduler();
    fetchProcesses();
    fetchSpaces();
  }, [fetchHealth, fetchCache, fetchScheduler, fetchProcesses, fetchSpaces]);

  const handleResync = async () => {
    if (!resyncSpace) return;
    try {
      setResyncLoading(true);
      setResyncResult(null);
      setError(null);
      const result = await apiService.adminResync(resyncSpace);
      setResyncResult(
        `Resync complete in ${result.elapsed_ms}ms — edges: ${result.edge_rows}, frame_entity: ${result.frame_entity_rows}, pred_stats: ${result.pred_stats_rows}, quad_stats: ${result.quad_stats_rows}`
      );
      setShowResync(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Resync failed');
    } finally {
      setResyncLoading(false);
    }
  };

  const handleTrigger = async () => {
    try {
      setTriggerLoading(true);
      setTriggerResult(null);
      setError(null);
      const result = await apiService.triggerProcess(triggerType);
      setTriggerResult(result.message);
      setShowTrigger(false);
      await fetchProcesses();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Trigger failed');
    } finally {
      setTriggerLoading(false);
    }
  };

  const statusBadge = (s: string) => {
    const color = s === 'completed' ? 'success' : s === 'running' ? 'info' : s === 'failed' ? 'failure' : 'gray';
    return <Badge color={color} size="sm">{s}</Badge>;
  };


  return (
    <div className="space-y-6" data-testid="admin-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <HiCog className="h-6 w-6" />
            System Administration
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            Health, cache, scheduler status, and maintenance operations.
          </p>
        </div>
        <Button size="sm" color="light" onClick={() => { fetchHealth(); fetchCache(); fetchScheduler(); fetchProcesses(); }}>
          <HiRefresh className="mr-1.5 h-4 w-4" />Refresh All
        </Button>
      </div>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}
      {resyncResult && <Alert color="success" onDismiss={() => setResyncResult(null)}>{resyncResult}</Alert>}
      {triggerResult && <Alert color="info" onDismiss={() => setTriggerResult(null)}>{triggerResult}</Alert>}

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Health Card */}
        <Card>
          <div className="flex items-center justify-between">
            <h5 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase">Service Health</h5>
            <HiStatusOnline className="h-5 w-5 text-gray-400" />
          </div>
          {healthLoading ? (
            <Spinner size="sm" />
          ) : (
            <div className="flex items-center gap-2 mt-2">
              {healthStatus === 'ok' ? (
                <><HiCheckCircle className="h-6 w-6 text-green-500" /><span className="text-lg font-semibold text-green-600">Healthy</span></>
              ) : (
                <><HiXCircle className="h-6 w-6 text-red-500" /><span className="text-lg font-semibold text-red-600">Error</span></>
              )}
            </div>
          )}
        </Card>

        {/* Scheduler Card */}
        <Card>
          <div className="flex items-center justify-between">
            <h5 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase">Scheduler</h5>
            <HiClock className="h-5 w-5 text-gray-400" />
          </div>
          {schedulerLoading ? (
            <Spinner size="sm" />
          ) : scheduler ? (
            <div className="mt-2 space-y-1">
              <div className="flex items-center gap-2">
                <Badge color={scheduler.enabled ? 'success' : 'gray'} size="sm">
                  {scheduler.enabled ? 'Enabled' : 'Disabled'}
                </Badge>
                <Badge color={scheduler.running ? 'info' : 'gray'} size="sm">
                  {scheduler.running ? 'Running' : 'Idle'}
                </Badge>
              </div>
              <p className="text-xs text-gray-500">Active locks: {scheduler.active_locks}</p>
              <p className="text-xs text-gray-500">Jobs: {Object.keys(scheduler.jobs).length}</p>
            </div>
          ) : (
            <p className="text-sm text-gray-400 mt-2">Unavailable</p>
          )}
        </Card>

        {/* Cache Card */}
        <Card>
          <div className="flex items-center justify-between">
            <h5 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase">Entity Cache</h5>
            <HiDatabase className="h-5 w-5 text-gray-400" />
          </div>
          {cacheLoading ? (
            <Spinner size="sm" />
          ) : cacheStats ? (
            <div className="mt-2 space-y-1 text-sm">
              {Object.entries(cacheStats).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs">
                  <span className="text-gray-500">{k.replace(/_/g, ' ')}</span>
                  <span className="font-mono text-gray-700 dark:text-gray-300">{String(v)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400 mt-2">Unavailable</p>
          )}
        </Card>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <Button size="sm" color="blue" onClick={() => setShowResync(true)}>
          <HiRefresh className="mr-1.5 h-4 w-4" />Resync Tables
        </Button>
        <Button size="sm" color="purple" onClick={() => setShowTrigger(true)}>
          <HiPlay className="mr-1.5 h-4 w-4" />Trigger Maintenance
        </Button>
      </div>

      {/* Processes Table */}
      <div>
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-3">Recent Processes</h3>
        {processesLoading ? (
          <div className="flex justify-center py-8"><Spinner size="xl" /></div>
        ) : processes.length === 0 ? (
          <p className="text-gray-500 text-sm py-4">No processes recorded.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <Table striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Type</TableHeadCell>
                  <TableHeadCell>Status</TableHeadCell>
                  <TableHeadCell>Progress</TableHeadCell>
                  <TableHeadCell>Started</TableHeadCell>
                  <TableHeadCell>Completed</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {processes.map((p) => (
                  <TableRow key={p.process_id}>
                    <TableCell className="font-medium text-gray-900 dark:text-white">
                      {p.process_type}
                      {p.process_subtype && <span className="text-xs text-gray-400 ml-1">/ {p.process_subtype}</span>}
                    </TableCell>
                    <TableCell>{statusBadge(p.status)}</TableCell>
                    <TableCell className="text-xs text-gray-500">
                      {p.progress_percent != null ? `${p.progress_percent}%` : '—'}
                      {p.progress_message && <span className="ml-1">{p.progress_message}</span>}
                      {p.error_message && <span className="text-red-500 ml-1">{p.error_message}</span>}
                    </TableCell>
                    <TableCell className="text-xs text-gray-500"><TimeAgo date={p.created_at} /></TableCell>
                    <TableCell className="text-xs text-gray-500"><TimeAgo date={p.completed_at} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Resync Modal */}
      <Modal show={showResync} onClose={() => setShowResync(false)} size="md">
        <ModalHeader>Resync Auxiliary Tables</ModalHeader>
        <ModalBody>
          <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
            Rebuilds edge, frame_entity, and stats tables from scratch. Use after bulk loads or manual DB edits.
          </p>
          <div>
            <Label htmlFor="resync-space">Space</Label>
            <Select id="resync-space" value={resyncSpace} onChange={(e) => setResyncSpace(e.target.value)}>
              <option value="">Select space...</option>
              {spaces.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="blue" onClick={handleResync} disabled={!resyncSpace || resyncLoading}>
            {resyncLoading ? <><Spinner size="sm" className="mr-2" />Running...</> : 'Run Resync'}
          </Button>
          <Button color="gray" onClick={() => setShowResync(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>

      {/* Trigger Modal */}
      <Modal show={showTrigger} onClose={() => setShowTrigger(false)} size="md">
        <ModalHeader>Trigger Maintenance Job</ModalHeader>
        <ModalBody>
          <div>
            <Label htmlFor="trigger-type">Operation Type</Label>
            <Select id="trigger-type" value={triggerType} onChange={(e) => setTriggerType(e.target.value)}>
              <option value="analyze">Analyze (VACUUM ANALYZE)</option>
              <option value="vacuum">Vacuum</option>
              <option value="stats_rebuild">Stats Rebuild</option>
              <option value="vector_reindex">Vector Reindex</option>
            </Select>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="purple" onClick={handleTrigger} disabled={triggerLoading}>
            {triggerLoading ? <><Spinner size="sm" className="mr-2" />Running...</> : 'Trigger'}
          </Button>
          <Button color="gray" onClick={() => setShowTrigger(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default Admin;
