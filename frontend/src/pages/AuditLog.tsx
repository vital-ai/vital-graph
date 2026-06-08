import React, { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Select, Spinner, TextInput,
  Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow,
  Pagination,
} from 'flowbite-react';
import { HiSearch, HiRefresh, HiShieldCheck, HiFilter } from 'react-icons/hi';
import { usePageTitle } from '../hooks/usePageTitle';
import TimeAgo from '../components/TimeAgo';

interface AuditEntry {
  id: number;
  timestamp: string;
  event: string;
  actor: string;
  target: string | null;
  ip: string | null;
  user_agent: string | null;
  details: Record<string, unknown> | null;
  level: string;
}

const PAGE_SIZE = 50;

const levelBadge = (level: string) => {
  switch (level.toUpperCase()) {
    case 'WARN': return <Badge color="warning" size="xs">WARN</Badge>;
    case 'ERROR': return <Badge color="failure" size="xs">ERROR</Badge>;
    case 'DEBUG': return <Badge color="gray" size="xs">DEBUG</Badge>;
    default: return <Badge color="info" size="xs">INFO</Badge>;
  }
};

const eventBadge = (event: string) => {
  if (event.includes('failure') || event.includes('denied')) return <Badge color="failure" size="xs">{event}</Badge>;
  if (event.includes('success') || event.includes('created')) return <Badge color="success" size="xs">{event}</Badge>;
  if (event.includes('changed') || event.includes('revoked')) return <Badge color="warning" size="xs">{event}</Badge>;
  return <Badge color="gray" size="xs">{event}</Badge>;
};

const AuditLog: React.FC = () => {
  usePageTitle('Audit Log');
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  // Filters
  const [filterEvent, setFilterEvent] = useState('');
  const [filterActor, setFilterActor] = useState('');
  const [filterLevel, setFilterLevel] = useState('');
  const [filterLast, setFilterLast] = useState('24h');
  const [showFilters, setShowFilters] = useState(false);

  const fetchLogs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await apiService.getAuditLog({
        event: filterEvent || undefined,
        actor: filterActor || undefined,
        level: filterLevel || undefined,
        last: filterLast || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setEntries(data.entries);
      setTotalCount(data.total_count);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log');
    } finally {
      setLoading(false);
    }
  }, [filterEvent, filterActor, filterLevel, filterLast, page]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <HiShieldCheck className="h-6 w-6 text-green-600" />
            Audit Log
          </h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            {totalCount.toLocaleString()} event{totalCount !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" color="light" onClick={() => setShowFilters(!showFilters)}>
            <HiFilter className="mr-1.5 h-4 w-4" />Filters
          </Button>
          <Button size="sm" color="light" onClick={fetchLogs}>
            <HiRefresh className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        </div>
      </div>

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Filters */}
      {showFilters && (
        <Card>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Event</label>
              <TextInput
                sizing="sm"
                icon={HiSearch}
                placeholder="e.g. auth.login"
                value={filterEvent}
                onChange={(e) => { setFilterEvent(e.target.value); setPage(1); }}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Actor</label>
              <TextInput
                sizing="sm"
                placeholder="Username"
                value={filterActor}
                onChange={(e) => { setFilterActor(e.target.value); setPage(1); }}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Level</label>
              <Select sizing="sm" value={filterLevel} onChange={(e) => { setFilterLevel(e.target.value); setPage(1); }}>
                <option value="">All</option>
                <option value="INFO">INFO</option>
                <option value="WARN">WARN</option>
                <option value="ERROR">ERROR</option>
                <option value="DEBUG">DEBUG</option>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Time Range</label>
              <Select sizing="sm" value={filterLast} onChange={(e) => { setFilterLast(e.target.value); setPage(1); }}>
                <option value="1h">Last hour</option>
                <option value="24h">Last 24 hours</option>
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
                <option value="">All time</option>
              </Select>
            </div>
          </div>
        </Card>
      )}

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      ) : entries.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <HiShieldCheck className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="text-lg font-medium">No audit events found</p>
          <p className="text-sm mt-1">Try adjusting your filters</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <Table striped>
              <TableHead>
                <TableHeadCell>Time</TableHeadCell>
                <TableHeadCell>Level</TableHeadCell>
                <TableHeadCell>Event</TableHeadCell>
                <TableHeadCell>Actor</TableHeadCell>
                <TableHeadCell>Target</TableHeadCell>
                <TableHeadCell>IP</TableHeadCell>
                <TableHeadCell>Details</TableHeadCell>
              </TableHead>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="text-xs text-gray-500 whitespace-nowrap">
                      <TimeAgo date={entry.timestamp} />
                    </TableCell>
                    <TableCell>{levelBadge(entry.level)}</TableCell>
                    <TableCell>{eventBadge(entry.event)}</TableCell>
                    <TableCell className="text-sm font-medium text-gray-900 dark:text-white">
                      {entry.actor}
                    </TableCell>
                    <TableCell className="text-sm text-gray-500">
                      {entry.target || '—'}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-gray-400">
                      {entry.ip || '—'}
                    </TableCell>
                    <TableCell className="text-xs text-gray-500 max-w-[200px] truncate">
                      {entry.details ? JSON.stringify(entry.details) : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center">
              <Pagination
                currentPage={page}
                totalPages={totalPages}
                onPageChange={setPage}
                showIcons
              />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default AuditLog;
