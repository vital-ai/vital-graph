import React, { useState, useEffect, useCallback } from 'react';
import { Alert, Badge, Card, Spinner } from 'flowbite-react';
import {
  HiUsers,
  HiViewBoards,
  HiDocumentDuplicate,
  HiUpload,
  HiDownload,
  HiChevronRight,
  HiSearch,
  HiDatabase,
  HiClock,
  HiCube,
  HiCog,
} from 'react-icons/hi';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { apiService } from '../services/ApiService';
import GraphIcon from '../components/icons/GraphIcon';
import ObjectIcon from '../components/icons/ObjectIcon';
import TriplesIcon from '../components/icons/TriplesIcon';
import { SkeletonCardList } from '../components/Skeleton';
import { usePageTitle } from '../hooks/usePageTitle';
import TimeAgo from '../components/TimeAgo';

interface DashboardStats {
  spacesCount: number;
  usersCount: number;
  totalGraphs: number;
  totalTriples: number;
}

interface SpaceSummary {
  space: string;
  space_name: string;
  graphCount: number;
  tripleCount: number;
}

interface RecentProcess {
  process_id: string;
  process_type: string;
  status: string;
  created_time: string;
  space_id?: string;
}

const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: number | string;
  linkTo: string;
  color: string;
  loading?: boolean;
}> = ({ icon, label, value, linkTo, color, loading }) => (
  <Link to={linkTo} className="block">
    <Card className="hover:shadow-md transition-shadow cursor-pointer">
      <div className="flex items-center gap-4">
        <div className={`p-3 rounded-lg ${color}`}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
          {loading ? (
            <Spinner size="sm" className="mt-1" />
          ) : (
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {typeof value === 'number' ? value.toLocaleString() : value}
            </p>
          )}
        </div>
        <HiChevronRight className="w-5 h-5 text-gray-400" />
      </div>
    </Card>
  </Link>
);

const NavItem: React.FC<{
  to: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}> = ({ to, icon, label, description }) => (
  <Link
    to={to}
    className="flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors group"
  >
    <div className="flex-shrink-0 text-gray-400 group-hover:text-blue-500 transition-colors">
      {icon}
    </div>
    <div className="flex-1 min-w-0">
      <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
      <p className="text-xs text-gray-500 dark:text-gray-400">{description}</p>
    </div>
    <HiChevronRight className="w-4 h-4 text-gray-300 group-hover:text-gray-500 transition-colors" />
  </Link>
);

const Home: React.FC = () => {
  usePageTitle('Dashboard');
  const { user, showLoginSuccess, setShowLoginSuccess } = useAuth();
  const [showWelcome, setShowWelcome] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [stats, setStats] = useState<DashboardStats>({ spacesCount: 0, usersCount: 0, totalGraphs: 0, totalTriples: 0 });
  const [spaces, setSpaces] = useState<SpaceSummary[]>([]);
  const [recentProcesses, setRecentProcesses] = useState<RecentProcess[]>([]);
  const [statsLoading, setStatsLoading] = useState(true);

  useEffect(() => {
    if (showLoginSuccess) {
      setShowWelcome(true);
      setTimeout(() => setIsVisible(true), 100);
      
      const fadeTimer = setTimeout(() => {
        setIsVisible(false);
      }, 2500);
      
      const hideTimer = setTimeout(() => {
        setShowWelcome(false);
        setShowLoginSuccess(false);
      }, 3000);
      
      return () => {
        clearTimeout(fadeTimer);
        clearTimeout(hideTimer);
      };
    }
  }, [showLoginSuccess, setShowLoginSuccess]);

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const [spacesData, usersData] = await Promise.all([
        apiService.getSpaces().catch(() => []),
        apiService.getUsers().catch(() => []),
      ]);

      // Load graph counts per space
      const spaceSummaries: SpaceSummary[] = [];
      let totalGraphs = 0;
      let totalTriples = 0;

      await Promise.all(
        spacesData.map(async (s: { space: string; space_name?: string }) => {
          try {
            const graphs = await apiService.getGraphs(s.space);
            const graphCount = graphs.length;
            const tripleCount = graphs.reduce((sum: number, g: { triple_count?: number }) => sum + (g.triple_count || 0), 0);
            spaceSummaries.push({
              space: s.space,
              space_name: s.space_name || s.space,
              graphCount,
              tripleCount,
            });
            totalGraphs += graphCount;
            totalTriples += tripleCount;
          } catch {
            spaceSummaries.push({ space: s.space, space_name: s.space_name || s.space, graphCount: 0, tripleCount: 0 });
          }
        })
      );

      setStats({
        spacesCount: spacesData.length,
        usersCount: usersData.length,
        totalGraphs,
        totalTriples,
      });
      setSpaces(spaceSummaries.sort((a, b) => b.tripleCount - a.tripleCount));

      // Fetch recent processes
      try {
        const procs = await apiService.listProcesses({ limit: 5 });
        setRecentProcesses((procs.processes || procs || []).slice(0, 5));
      } catch {
        // non-critical
      }
    } catch {
      // Stats are best-effort
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Dashboard
        </h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Welcome back{user?.full_name ? `, ${user.full_name}` : ''}
        </p>
      </div>

      {showWelcome && (
        <Alert
          color="info"
          className={`transition-opacity duration-500 ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        >
          <div className="font-medium">
            Hello, {user?.full_name || 'Admin User'}!
          </div>
          <div>
            You are successfully logged in as {user?.role || 'Administrator'}.
          </div>
        </Alert>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<HiViewBoards className="w-6 h-6 text-blue-600" />}
          label="Spaces"
          value={stats.spacesCount}
          linkTo="/spaces"
          color="bg-blue-50 dark:bg-blue-900/20"
          loading={statsLoading}
        />
        <StatCard
          icon={<GraphIcon className="w-6 h-6 text-purple-600" />}
          label="Graphs"
          value={stats.totalGraphs}
          linkTo="/graphs"
          color="bg-purple-50 dark:bg-purple-900/20"
          loading={statsLoading}
        />
        <StatCard
          icon={<TriplesIcon className="w-6 h-6 text-indigo-600" />}
          label="Triples"
          value={stats.totalTriples}
          linkTo="/triples"
          color="bg-indigo-50 dark:bg-indigo-900/20"
          loading={statsLoading}
        />
        <StatCard
          icon={<HiUsers className="w-6 h-6 text-green-600" />}
          label="Users"
          value={stats.usersCount}
          linkTo="/users"
          color="bg-green-50 dark:bg-green-900/20"
          loading={statsLoading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Spaces Overview */}
        <div className="lg:col-span-2">
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Spaces</h2>
              <Link to="/spaces" className="text-sm text-blue-600 hover:underline">View all →</Link>
            </div>
            {statsLoading ? (
              <SkeletonCardList rows={3} />
            ) : spaces.length === 0 ? (
              <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                <HiDatabase className="w-12 h-12 mx-auto mb-3 text-gray-300 dark:text-gray-600" />
                <p className="font-medium">No spaces yet</p>
                <p className="text-sm mt-1">Create a space to get started</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-700">
                {spaces.slice(0, 5).map((s) => (
                  <Link
                    key={s.space}
                    to={`/space/${s.space}`}
                    className="flex items-center justify-between py-3 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors group"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <HiViewBoards className="w-5 h-5 text-blue-500 flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="font-medium text-gray-900 dark:text-white truncate">{s.space_name}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">{s.space}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 flex-shrink-0">
                      <div className="text-right">
                        <p className="text-sm font-medium text-gray-900 dark:text-white">{s.graphCount}</p>
                        <p className="text-xs text-gray-500">graphs</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-gray-900 dark:text-white">{s.tripleCount.toLocaleString()}</p>
                        <p className="text-xs text-gray-500">triples</p>
                      </div>
                      <HiChevronRight className="w-4 h-4 text-gray-300 group-hover:text-gray-500" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Quick Navigation */}
        <div className="space-y-6">
          <Card>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Quick Access</h2>
            <div className="space-y-1">
              <NavItem
                to="/sparql"
                icon={<HiSearch className="w-5 h-5" />}
                label="SPARQL Query"
                description="Run queries against your graphs"
              />
              <NavItem
                to="/objects"
                icon={<ObjectIcon className="w-5 h-5" />}
                label="Knowledge Graph"
                description="Objects, entities, frames, relations"
              />
              <NavItem
                to="/data/import"
                icon={<HiUpload className="w-5 h-5" />}
                label="Import Data"
                description="Load RDF data into graphs"
              />
              <NavItem
                to="/data/export"
                icon={<HiDownload className="w-5 h-5" />}
                label="Export Data"
                description="Download graph data"
              />
              <NavItem
                to="/semantic-search"
                icon={<HiCube className="w-5 h-5" />}
                label="Semantic Indexes"
                description="Search, mappings, indexes"
              />
              <NavItem
                to="/files"
                icon={<HiDocumentDuplicate className="w-5 h-5" />}
                label="Files"
                description="Manage uploaded files"
              />
              {user?.role === 'admin' && (
                <NavItem
                  to="/admin"
                  icon={<HiCog className="w-5 h-5" />}
                  label="Administration"
                  description="System health & maintenance"
                />
              )}
            </div>
          </Card>

          {/* Recent Activity */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
              <Link to="/admin" className="text-sm text-blue-600 hover:underline">View all →</Link>
            </div>
            {recentProcesses.length === 0 ? (
              <div className="text-center py-6 text-gray-500 dark:text-gray-400">
                <HiClock className="w-8 h-8 mx-auto mb-2 text-gray-300 dark:text-gray-600" />
                <p className="text-sm">No recent activity</p>
              </div>
            ) : (
              <div className="space-y-2">
                {recentProcesses.map((p) => (
                  <div key={p.process_id} className="flex items-center gap-3 p-2 rounded text-sm">
                    <HiClock className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-gray-900 dark:text-white font-medium truncate">
                        {p.process_type.replace(/_/g, ' ')}
                      </p>
                      <TimeAgo date={p.created_time} className="text-xs text-gray-500" />
                    </div>
                    <Badge
                      color={p.status === 'completed' ? 'success' : p.status === 'failed' ? 'failure' : 'warning'}
                      size="xs"
                    >
                      {p.status}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};

export default Home;
