import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Select, Spinner, TextInput,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
  Pagination,
} from 'flowbite-react';
import { HiSearch, HiPlus, HiEye, HiCollection } from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import { useEntityTypes } from '../hooks/useRegistryLookups';
import TimeAgo from '../components/TimeAgo';

interface RegistryEntity {
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

const PAGE_SIZE = 25;

const statusBadge = (status: string) => {
  switch (status) {
    case 'active': return <Badge color="success" size="xs">Active</Badge>;
    case 'inactive': return <Badge color="gray" size="xs">Inactive</Badge>;
    case 'merged': return <Badge color="warning" size="xs">Merged</Badge>;
    case 'deleted': return <Badge color="failure" size="xs">Deleted</Badge>;
    default: return <Badge color="gray" size="xs">{status}</Badge>;
  }
};

const EntityRegistry: React.FC = () => {
  usePageTitle('Entity Registry');
  const navigate = useNavigate();
  const [entities, setEntities] = useState<RegistryEntity[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('active');
  const { items: entityTypes, error: typesError } = useEntityTypes();
  const fetchIdRef = useRef(0);

  const fetchEntities = useCallback(async () => {
    // Search refetches on every keystroke, so several requests can be in flight
    // at once. Without this guard a slow earlier response lands last and
    // replaces the filtered list with stale results — most visibly, typing a
    // search reverts to unfiltered page 1.
    const reqId = ++fetchIdRef.current;
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.listRegistryEntities({
        query: search || undefined,
        entity_type: typeFilter || undefined,
        status: statusFilter, // '' means all statuses
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      if (reqId !== fetchIdRef.current) return;
      setEntities(data.entities || []);
      setTotalCount(data.total_count || 0);
    } catch (err) {
      if (reqId !== fetchIdRef.current) return;
      setError(err instanceof Error ? err.message : 'Failed to load entities');
    } finally {
      if (reqId === fetchIdRef.current) setLoading(false);
    }
  }, [search, typeFilter, statusFilter, page]);

  useEffect(() => { fetchEntities(); }, [fetchEntities]);

  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

  return (
    <div className="space-y-6" data-testid="entity-registry-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <HiCollection className="h-6 w-6 text-indigo-600" />
            Entity Registry
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            {totalCount.toLocaleString()} registered entit{totalCount !== 1 ? 'ies' : 'y'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="w-64">
            <TextInput
              sizing="sm"
              icon={HiSearch}
              placeholder="Search entities..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            />
          </div>
          <Select
            sizing="sm"
            data-testid="entity-type-filter"
            value={typeFilter}
            onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
          >
            <option value="">All types</option>
            {entityTypes.map((t) => (
              <option key={t.type_id} value={t.type_key}>{t.type_label || t.type_key}</option>
            ))}
          </Select>
          <Select
            sizing="sm"
            data-testid="entity-status-filter"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="merged">Merged</option>
            <option value="deleted">Deleted</option>
            <option value="">All statuses</option>
          </Select>
          <Button size="sm" color="blue" onClick={() => navigate('/entity-registry/new')}>
            <HiPlus className="mr-1.5 h-4 w-4" />New
          </Button>
        </div>
      </div>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}
      {typesError && <Alert color="warning">Entity types unavailable: {typesError}</Alert>}

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      ) : entities.length === 0 ? (
        <Card>
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <HiCollection className="w-12 h-12 mx-auto mb-3 text-gray-300" />
            <p className="text-lg font-medium">No entities found</p>
            <p className="text-sm mt-1">{search ? 'Try a different search term' : 'Register your first entity'}</p>
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
                <TableHeadCell>Description</TableHeadCell>
                <TableHeadCell>Updated</TableHeadCell>
                <TableHeadCell>Actions</TableHeadCell>
              </TableHead>
              <TableBody>
                {entities.map((entity) => (
                  <TableRow key={entity.entity_id} className="cursor-pointer" onClick={() => navigate(`/entity-registry/${entity.entity_id}`)}>
                    <TableCell className="font-medium text-gray-900 dark:text-white">
                      {entity.primary_name}
                      <div className="text-xs text-gray-400 font-mono truncate max-w-[200px]">{entity.entity_uri}</div>
                    </TableCell>
                    <TableCell>
                      <Badge color="purple" size="xs">{entity.type_label || entity.type_key || '—'}</Badge>
                    </TableCell>
                    <TableCell>{statusBadge(entity.status)}</TableCell>
                    <TableCell className="text-sm text-gray-500 max-w-[200px] truncate">
                      {entity.description || '—'}
                    </TableCell>
                    <TableCell className="text-xs text-gray-500">
                      <TimeAgo date={entity.updated_time || entity.created_time} />
                    </TableCell>
                    <TableCell>
                      <Button size="xs" color="light" onClick={(e: React.MouseEvent) => { e.stopPropagation(); navigate(`/entity-registry/${entity.entity_id}`); }}>
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

export default EntityRegistry;
