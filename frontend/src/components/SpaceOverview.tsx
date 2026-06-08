import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Card, Spinner, Alert } from 'flowbite-react';
import { HiDatabase, HiCollection, HiViewGrid, HiClock, HiChevronRight, HiUpload, HiSearch } from 'react-icons/hi';
import { apiService } from '../services/ApiService';

interface GraphRow {
  graph_uri: string;
  graph_name?: string;
}

interface SpaceInfoResponse {
  success: boolean;
  message?: string;
  space?: {
    space: string;
    space_name: string;
    space_description?: string;
    update_time?: string;
  };
  statistics?: {
    space_id?: string;
    backend_type?: string;
    quad_count?: number;
    term_count?: number;
    graphs?: GraphRow[];
    created_time?: string;
    update_time?: string;
    storage_size_bytes?: number;
  };
}

interface Props {
  spaceId: string;
}

const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string | number;
  subtitle?: string;
}> = ({ icon, label, value, subtitle }) => (
  <Card>
    <div className="flex items-center gap-4">
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-50 dark:bg-blue-900/30">
        {icon}
      </div>
      <div>
        <div className="text-2xl font-bold text-gray-900 dark:text-white">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </div>
        <div className="text-sm text-gray-500 dark:text-gray-400">{label}</div>
        {subtitle && (
          <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{subtitle}</div>
        )}
      </div>
    </div>
  </Card>
);

const SpaceOverview: React.FC<Props> = ({ spaceId }) => {
  const [data, setData] = useState<SpaceInfoResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchInfo = useCallback(async () => {
    try {
      setLoading(true);
      const resp = await apiService.getSpaceInfo(spaceId);
      setData(resp);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load space info');
    } finally {
      setLoading(false);
    }
  }, [spaceId]);

  useEffect(() => {
    fetchInfo();
  }, [fetchInfo]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner size="lg" />
        <span className="ml-3 text-gray-500">Loading space info...</span>
      </div>
    );
  }

  if (error) {
    return (
      <Alert color="failure" className="mb-4">
        {error}
      </Alert>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-12 text-gray-500 dark:text-gray-400">
        No space information available.
      </div>
    );
  }

  const stats = data.statistics;
  const quadCount = stats?.quad_count ?? 0;
  const termCount = stats?.term_count ?? 0;
  const graphCount = stats?.graphs?.length ?? 0;
  const backendType = stats?.backend_type ?? 'unknown';
  const graphs = stats?.graphs ?? [];

  const formatBytes = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  return (
    <div className="space-y-6">
      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<HiDatabase className="h-6 w-6 text-blue-600 dark:text-blue-400" />}
          label="Triples"
          value={quadCount}
          subtitle="RDF quads stored"
        />
        <StatCard
          icon={<HiCollection className="h-6 w-6 text-purple-600 dark:text-purple-400" />}
          label="Terms"
          value={termCount}
          subtitle="Unique terms indexed"
        />
        <StatCard
          icon={<HiViewGrid className="h-6 w-6 text-teal-600 dark:text-teal-400" />}
          label="Graphs"
          value={graphCount}
          subtitle="Named graphs"
        />
        {stats?.storage_size_bytes != null ? (
          <StatCard
            icon={<HiClock className="h-6 w-6 text-orange-600 dark:text-orange-400" />}
            label="Storage"
            value={formatBytes(stats.storage_size_bytes)}
            subtitle="Disk usage"
          />
        ) : (
          <StatCard
            icon={<HiClock className="h-6 w-6 text-orange-600 dark:text-orange-400" />}
            label="Backend"
            value={backendType}
            subtitle="Storage engine"
          />
        )}
      </div>

      {/* Quick Actions */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Quick Actions</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Link
            to={`/data/import/new?spaceId=${spaceId}`}
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 hover:border-blue-300 transition-all group"
          >
            <HiUpload className="w-5 h-5 text-gray-400 group-hover:text-blue-500" />
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-white">Import Data</p>
              <p className="text-xs text-gray-500">Load triples into this space</p>
            </div>
            <HiChevronRight className="w-4 h-4 text-gray-300" />
          </Link>
          <Link
            to="/sparql"
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 hover:border-blue-300 transition-all group"
          >
            <HiSearch className="w-5 h-5 text-gray-400 group-hover:text-blue-500" />
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-white">SPARQL Query</p>
              <p className="text-xs text-gray-500">Query this space</p>
            </div>
            <HiChevronRight className="w-4 h-4 text-gray-300" />
          </Link>
          <Link
            to={`/space/${spaceId}/graphs`}
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 hover:border-blue-300 transition-all group"
          >
            <HiViewGrid className="w-5 h-5 text-gray-400 group-hover:text-blue-500" />
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-white">Manage Graphs</p>
              <p className="text-xs text-gray-500">Create, browse, delete graphs</p>
            </div>
            <HiChevronRight className="w-4 h-4 text-gray-300" />
          </Link>
        </div>
      </Card>

      {/* Graphs Table */}
      {graphs.length > 0 && (
        <Card>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
            Named Graphs ({graphs.length})
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-500 dark:text-gray-400">
              <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                <tr>
                  <th className="px-4 py-2">Graph URI</th>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {graphs.map((g: GraphRow, idx: number) => (
                  <tr key={idx} className="bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td className="px-4 py-2 font-mono text-xs break-all">
                      <Link to={`/space/${spaceId}/graph/${encodeURIComponent(g.graph_uri)}`} className="text-blue-600 hover:underline">
                        {g.graph_uri}
                      </Link>
                    </td>
                    <td className="px-4 py-2">
                      {g.graph_name || <span className="italic text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-2">
                      <Link to={`/space/${spaceId}/graph/${encodeURIComponent(g.graph_uri)}`}>
                        <HiChevronRight className="w-4 h-4 text-gray-400 hover:text-blue-500" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Metadata Footer */}
      <div className="flex flex-wrap gap-4 text-xs text-gray-400 dark:text-gray-500">
        {stats?.created_time && (
          <span>Created: {new Date(stats.created_time).toLocaleDateString()}</span>
        )}
        {(data.space?.update_time || stats?.update_time) && (
          <span>Last modified: {new Date((data.space?.update_time || stats?.update_time)!).toLocaleString()}</span>
        )}
        <span>Space ID: <code className="font-mono">{spaceId}</code></span>
      </div>
    </div>
  );
};

export default SpaceOverview;
