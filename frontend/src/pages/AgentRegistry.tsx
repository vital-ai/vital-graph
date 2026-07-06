import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Spinner, TextInput,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
  Pagination, Select,
} from 'flowbite-react';
import { HiSearch, HiPlus, HiEye, HiChip } from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import TimeAgo from '../components/TimeAgo';

interface Agent {
  agent_id: string;
  agent_uri: string;
  agent_name: string;
  agent_type_key: string;
  agent_type_label: string;
  description: string | null;
  status: string;
  version: string | null;
  created_time: string | null;
  updated_time: string | null;
}

const PAGE_SIZE = 25;

const statusBadge = (status: string) => {
  switch (status) {
    case 'active': return <Badge color="success" size="xs">Active</Badge>;
    case 'inactive': return <Badge color="gray" size="xs">Inactive</Badge>;
    case 'deprecated': return <Badge color="warning" size="xs">Deprecated</Badge>;
    case 'error': return <Badge color="failure" size="xs">Error</Badge>;
    default: return <Badge color="gray" size="xs">{status}</Badge>;
  }
};

const AgentRegistry: React.FC = () => {
  usePageTitle('Agent Registry');
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const fetchAgents = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.listAgents({
        query: search || undefined,
        status: statusFilter || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setAgents(data.agents || []);
      setTotalCount(data.total_count || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, page]);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

  return (
    <div className="space-y-6" data-testid="agent-registry-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <HiChip className="h-6 w-6 text-cyan-600" />
            Agent Registry
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            {totalCount.toLocaleString()} registered agent{totalCount !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <div className="w-56">
            <TextInput
              sizing="sm"
              icon={HiSearch}
              placeholder="Search agents..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            />
          </div>
          <Select sizing="sm" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="deprecated">Deprecated</option>
          </Select>
          <Button size="sm" color="blue" onClick={() => navigate('/agent-registry/new')}>
            <HiPlus className="mr-1.5 h-4 w-4" />New
          </Button>
        </div>
      </div>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      ) : agents.length === 0 ? (
        <Card>
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <HiChip className="w-12 h-12 mx-auto mb-3 text-gray-300" />
            <p className="text-lg font-medium">No agents found</p>
            <p className="text-sm mt-1">{search ? 'Try a different search term' : 'Register your first agent'}</p>
          </div>
        </Card>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <Table striped hoverable>
              <TableHead>
                <TableHeadCell>Name</TableHeadCell>
                <TableHeadCell>Type</TableHeadCell>
                <TableHeadCell>Status</TableHeadCell>
                <TableHeadCell>Version</TableHeadCell>
                <TableHeadCell>Description</TableHeadCell>
                <TableHeadCell>Updated</TableHeadCell>
                <TableHeadCell>Actions</TableHeadCell>
              </TableHead>
              <TableBody>
                {agents.map((agent) => (
                  <TableRow key={agent.agent_id} className="cursor-pointer" onClick={() => navigate(`/agent-registry/${agent.agent_id}`)}>
                    <TableCell className="font-medium text-gray-900 dark:text-white">
                      {agent.agent_name}
                      <div className="text-xs text-gray-400 font-mono truncate max-w-[180px]">{agent.agent_uri}</div>
                    </TableCell>
                    <TableCell>
                      <Badge color="cyan" size="xs">{agent.agent_type_label || agent.agent_type_key}</Badge>
                    </TableCell>
                    <TableCell>{statusBadge(agent.status)}</TableCell>
                    <TableCell className="text-xs text-gray-500 font-mono">{agent.version || '—'}</TableCell>
                    <TableCell className="text-sm text-gray-500 max-w-[180px] truncate">
                      {agent.description || '—'}
                    </TableCell>
                    <TableCell className="text-xs text-gray-500">
                      <TimeAgo date={agent.updated_time || agent.created_time} />
                    </TableCell>
                    <TableCell>
                      <Button size="xs" color="light" onClick={(e: React.MouseEvent) => { e.stopPropagation(); navigate(`/agent-registry/${agent.agent_id}`); }}>
                        <HiEye className="h-3 w-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {totalPages > 1 && (
            <div className="flex justify-center">
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} showIcons />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default AgentRegistry;
