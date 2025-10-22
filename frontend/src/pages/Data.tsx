import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Button,
  Card,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Badge,
  Progress,
  Spinner,
  Alert,
  Modal
} from 'flowbite-react';
import {
  HiPlus,
  HiEye,
  HiTrash,
  HiDownload,
  HiPlay,
  HiStop
} from 'react-icons/hi';
import { 
  mockDataImports, 
  mockDataExports, 
  mockDataMigrations, 
  mockDataTrackings, 
  mockDataCheckpoints,
  DataImport,
  DataExport,
  DataMigration,
  DataTracking,
  DataCheckpoint
} from '../mock/data';
import { mockSpaces, Space } from '../mock/spaces';
import { mockGraphs, Graph } from '../mock/graphs';
import DataIcon from '../components/icons/DataIcon';

const Data: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [activeTab, setActiveTab] = useState<string>('import');
  const [imports, setImports] = useState<DataImport[]>([]);
  const [exports, setExports] = useState<DataExport[]>([]);
  const [migrations, setMigrations] = useState<DataMigration[]>([]);
  const [trackings, setTrackings] = useState<DataTracking[]>([]);
  const [checkpoints, setCheckpoints] = useState<DataCheckpoint[]>([]);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  
  // Modal states
  const [showDeleteImportModal, setShowDeleteImportModal] = useState<boolean>(false);
  const [showDeleteExportModal, setShowDeleteExportModal] = useState<boolean>(false);
  const [showDeleteMigrationModal, setShowDeleteMigrationModal] = useState<boolean>(false);
  const [showDeleteTrackingModal, setShowDeleteTrackingModal] = useState<boolean>(false);
  const [showDeleteCheckpointModal, setShowDeleteCheckpointModal] = useState<boolean>(false);
  const [importToDelete, setImportToDelete] = useState<DataImport | null>(null);
  const [exportToDelete, setExportToDelete] = useState<DataExport | null>(null);
  const [migrationToDelete, setMigrationToDelete] = useState<DataMigration | null>(null);
  const [trackingToDelete, setTrackingToDelete] = useState<DataTracking | null>(null);
  const [checkpointToDelete, setCheckpointToDelete] = useState<DataCheckpoint | null>(null);

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      // Simulate API calls
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setImports(mockDataImports);
      setExports(mockDataExports);
      setMigrations(mockDataMigrations);
      setTrackings(mockDataTrackings);
      setCheckpoints(mockDataCheckpoints);
      setSpaces(mockSpaces);
      setGraphs(mockGraphs);
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to load data. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    
    // Set active tab based on URL path
    if (location.pathname === '/data/export') {
      setActiveTab('export');
    } else if (location.pathname === '/data/migrate') {
      setActiveTab('migrate');
    } else if (location.pathname === '/data/tracking') {
      setActiveTab('tracking');
    } else if (location.pathname === '/data/checkpoint') {
      setActiveTab('checkpoint');
    } else {
      setActiveTab('import');
    }
  }, [fetchData, location.pathname]);

  // Helper functions
  const getSpaceName = (spaceId: string) => {
    const space = spaces.find(s => s.space === spaceId);
    return space ? space.space_name : spaceId;
  };

  const getGraphName = (graphId: number) => {
    const graph = graphs.find(g => g.id === graphId);
    return graph ? graph.graph_name : `Graph ${graphId}`;
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'success';
      case 'processing': return 'info';
      case 'pending': return 'warning';
      case 'failed': return 'failure';
      case 'canceled': return 'gray';
      case 'expired': return 'gray';
      default: return 'gray';
    }
  };

  // Action handlers
  const handleStartImport = async (importId: number) => {
    setImports(prev => prev.map(imp => 
      imp.id === importId 
        ? { ...imp, status: 'processing', started_time: new Date().toISOString(), progress: 10 }
        : imp
    ));
  };

  const handleCancelImport = async (importId: number) => {
    setImports(prev => prev.map(imp => 
      imp.id === importId 
        ? { ...imp, status: 'canceled', completed_time: new Date().toISOString() }
        : imp
    ));
  };

  const handleStartExport = async (exportId: number) => {
    setExports(prev => prev.map(exp => 
      exp.id === exportId 
        ? { ...exp, status: 'processing', started_time: new Date().toISOString(), progress: 10 }
        : exp
    ));
  };

  const handleCancelExport = async (exportId: number) => {
    setExports(prev => prev.map(exp => 
      exp.id === exportId 
        ? { ...exp, status: 'canceled', completed_time: new Date().toISOString() }
        : exp
    ));
  };

  const handleStartMigration = async (migrationId: number) => {
    setMigrations(prev => prev.map(mig => 
      mig.id === migrationId 
        ? { ...mig, status: 'processing', started_time: new Date().toISOString(), progress: 10 }
        : mig
    ));
  };

  const handleCancelMigration = async (migrationId: number) => {
    setMigrations(prev => prev.map(mig => 
      mig.id === migrationId 
        ? { ...mig, status: 'canceled', completed_time: new Date().toISOString() }
        : mig
    ));
  };

  const handleDownload = (exportItem: DataExport) => {
    if (exportItem.download_url) {
      // Create a temporary link and trigger download
      const link = document.createElement('a');
      link.href = exportItem.download_url;
      link.download = `${exportItem.name.replace(/\s+/g, '_')}.${exportItem.export_format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  const handleDeleteImport = async (importId: number) => {
    const importItem = imports.find(imp => imp.id === importId);
    if (importItem) {
      setImportToDelete(importItem);
      setShowDeleteImportModal(true);
    }
  };

  const confirmDeleteImport = async () => {
    if (importToDelete) {
      setImports(prev => prev.filter(imp => imp.id !== importToDelete.id));
      setShowDeleteImportModal(false);
      setImportToDelete(null);
    }
  };

  const handleDeleteExport = async (exportId: number) => {
    const exportItem = exports.find(exp => exp.id === exportId);
    if (exportItem) {
      setExportToDelete(exportItem);
      setShowDeleteExportModal(true);
    }
  };

  const confirmDeleteExport = async () => {
    if (exportToDelete) {
      setExports(prev => prev.filter(exp => exp.id !== exportToDelete.id));
      setShowDeleteExportModal(false);
      setExportToDelete(null);
    }
  };

  const handleDeleteMigration = async (migrationId: number) => {
    const migration = migrations.find(mig => mig.id === migrationId);
    if (migration) {
      setMigrationToDelete(migration);
      setShowDeleteMigrationModal(true);
    }
  };

  const confirmDeleteMigration = async () => {
    if (migrationToDelete) {
      setMigrations(prev => prev.filter(mig => mig.id !== migrationToDelete.id));
      setShowDeleteMigrationModal(false);
      setMigrationToDelete(null);
    }
  };

  const handleStartTracking = async (trackingId: number) => {
    setTrackings(prev => prev.map(track => 
      track.id === trackingId 
        ? { ...track, status: 'processing', started_time: new Date().toISOString(), overall_progress: 5 }
        : track
    ));
  };

  const handlePauseTracking = async (trackingId: number) => {
    setTrackings(prev => prev.map(track => 
      track.id === trackingId 
        ? { ...track, status: 'paused', last_updated: new Date().toISOString() }
        : track
    ));
  };

  const handleResumeTracking = async (trackingId: number) => {
    setTrackings(prev => prev.map(track => 
      track.id === trackingId 
        ? { ...track, status: 'processing', last_updated: new Date().toISOString() }
        : track
    ));
  };

  const handleDeleteTracking = async (trackingId: number) => {
    const tracking = trackings.find(track => track.id === trackingId);
    if (tracking) {
      setTrackingToDelete(tracking);
      setShowDeleteTrackingModal(true);
    }
  };

  const confirmDeleteTracking = async () => {
    if (trackingToDelete) {
      setTrackings(prev => prev.filter(track => track.id !== trackingToDelete.id));
      setShowDeleteTrackingModal(false);
      setTrackingToDelete(null);
    }
  };

  const handleDeleteCheckpoint = async (checkpointId: number) => {
    const checkpoint = checkpoints.find(cp => cp.id === checkpointId);
    if (checkpoint) {
      setCheckpointToDelete(checkpoint);
      setShowDeleteCheckpointModal(true);
    }
  };

  const confirmDeleteCheckpoint = async () => {
    if (checkpointToDelete) {
      setCheckpoints(prev => prev.filter(cp => cp.id !== checkpointToDelete.id));
      setShowDeleteCheckpointModal(false);
      setCheckpointToDelete(null);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-40">
        <Spinner size="xl" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Data Management
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Manage data imports and exports for your RDF graphs
        </p>
      </div>

      {error && (
        <Alert color="failure" className="mb-4">
          {error}
        </Alert>
      )}

      <Card>
        <div className="border-b border-gray-200 dark:border-gray-700">
          <nav className="-mb-px flex space-x-8">
            <button
              onClick={() => navigate('/data/import')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'import'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Import
            </button>
            <button
              onClick={() => navigate('/data/export')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'export'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Export
            </button>
            <button
              onClick={() => navigate('/data/migrate')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'migrate'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Migrate
            </button>
            <button
              onClick={() => navigate('/data/tracking')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'tracking'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Tracking
            </button>
            <button
              onClick={() => navigate('/data/checkpoint')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'checkpoint'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Checkpoint
            </button>
          </nav>
        </div>
        
        <div className="p-6">
          {activeTab === 'import' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Data Imports
                </h2>
                <Button
                  color="blue"
                  onClick={() => navigate('/data/import/new')}
                >
                  <HiPlus className="w-4 h-4 mr-2" />
                  Add Data Import
                </Button>
              </div>

              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>Name</TableHeadCell>
                      <TableHeadCell>Space</TableHeadCell>
                      <TableHeadCell>Graph</TableHeadCell>
                      <TableHeadCell>File</TableHeadCell>
                      <TableHeadCell>Status</TableHeadCell>
                      <TableHeadCell>Progress</TableHeadCell>
                      <TableHeadCell>Created</TableHeadCell>
                      <TableHeadCell>Actions</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {imports.map((importItem) => (
                      <TableRow key={importItem.id}>
                        <TableCell className="font-medium">
                          {importItem.name}
                        </TableCell>
                        <TableCell>{getSpaceName(importItem.space_id)}</TableCell>
                        <TableCell>{getGraphName(importItem.graph_id)}</TableCell>
                        <TableCell>
                          <div>
                            <div className="font-medium">{importItem.file_name}</div>
                            <div className="text-sm text-gray-500">
                              {formatFileSize(importItem.file_size)}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge color={getStatusColor(importItem.status)}>
                            {importItem.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="w-24">
                            <Progress
                              progress={importItem.progress}
                              color={importItem.status === 'failed' ? 'red' : 'blue'}
                              size="sm"
                            />
                            <div className="text-xs text-gray-500 mt-1">
                              {importItem.progress}%
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {formatDate(importItem.created_time)}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => navigate(`/data/import/${importItem.id}`)}
                            >
                              <HiEye className="w-3 h-3 mr-1" />
                              Details
                            </Button>
                            {importItem.status === 'pending' && (
                              <Button
                                size="xs"
                                color="green"
                                onClick={() => handleStartImport(importItem.id)}
                              >
                                <HiPlay className="w-3 h-3 mr-1" />
                                Start
                              </Button>
                            )}
                            {importItem.status === 'processing' && (
                              <Button
                                size="xs"
                                color="red"
                                onClick={() => handleCancelImport(importItem.id)}
                              >
                                <HiStop className="w-3 h-3 mr-1" />
                                Cancel
                              </Button>
                            )}
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteImport(importItem.id)}
                              disabled={importItem.status === 'processing'}
                            >
                              <HiTrash className="w-3 h-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {imports.length === 0 && (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No data imports found. Create your first import to get started.
                </div>
              )}
            </div>
          )}
          
          {activeTab === 'export' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Data Exports
                </h2>
                <Button
                  color="blue"
                  onClick={() => navigate('/data/export/new')}
                >
                  <HiPlus className="w-4 h-4 mr-2" />
                  Add Data Export
                </Button>
              </div>

              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>Space</TableHeadCell>
                      <TableHeadCell>Graph</TableHeadCell>
                      <TableHeadCell>Format</TableHeadCell>
                      <TableHeadCell>Status</TableHeadCell>
                      <TableHeadCell>Progress</TableHeadCell>
                      <TableHeadCell>Size</TableHeadCell>
                      <TableHeadCell>Created</TableHeadCell>
                      <TableHeadCell>Actions</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {exports.map((exportItem) => (
                      <TableRow key={exportItem.id}>
                        <TableCell className="font-medium">{getSpaceName(exportItem.space_id)}</TableCell>
                        <TableCell>{getGraphName(exportItem.graph_id)}</TableCell>
                        <TableCell>
                          <Badge color="gray">{exportItem.export_format}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge color={getStatusColor(exportItem.status)}>
                            {exportItem.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="w-24">
                            <Progress
                              progress={exportItem.progress}
                              color={exportItem.status === 'failed' ? 'red' : 'blue'}
                              size="sm"
                            />
                            <div className="text-xs text-gray-500 mt-1">
                              {exportItem.progress}%
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {exportItem.file_size ? formatFileSize(exportItem.file_size) : '-'}
                        </TableCell>
                        <TableCell className="text-sm">
                          {formatDate(exportItem.created_time)}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => navigate(`/data/export/${exportItem.id}`)}
                            >
                              <HiEye className="w-3 h-3 mr-1" />
                              Details
                            </Button>
                            {exportItem.status === 'pending' && (
                              <Button
                                size="xs"
                                color="green"
                                onClick={() => handleStartExport(exportItem.id)}
                              >
                                <HiPlay className="w-3 h-3 mr-1" />
                                Start
                              </Button>
                            )}
                            {exportItem.status === 'processing' && (
                              <Button
                                size="xs"
                                color="red"
                                onClick={() => handleCancelExport(exportItem.id)}
                              >
                                <HiStop className="w-3 h-3 mr-1" />
                                Cancel
                              </Button>
                            )}
                            {exportItem.status === 'completed' && exportItem.download_url && (
                              <Button
                                size="xs"
                                color="green"
                                onClick={() => handleDownload(exportItem)}
                              >
                                <HiDownload className="w-3 h-3 mr-1" />
                                Download
                              </Button>
                            )}
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteExport(exportItem.id)}
                              disabled={exportItem.status === 'processing'}
                            >
                              <HiTrash className="w-3 h-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {exports.length === 0 && (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No data exports found. Create your first export to get started.
                </div>
              )}
            </div>
          )}
          
          {activeTab === 'migrate' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Data Migrations
                </h2>
                <Button
                  color="blue"
                  onClick={() => navigate('/data/migrate/new')}
                >
                  <HiPlus className="w-4 h-4 mr-2" />
                  Add Data Migration
                </Button>
              </div>

              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>Source Space</TableHeadCell>
                      <TableHeadCell>Source Graph</TableHeadCell>
                      <TableHeadCell>Target Space</TableHeadCell>
                      <TableHeadCell>Target Graph</TableHeadCell>
                      <TableHeadCell>Type</TableHeadCell>
                      <TableHeadCell>Status</TableHeadCell>
                      <TableHeadCell>Progress</TableHeadCell>
                      <TableHeadCell>Triples</TableHeadCell>
                      <TableHeadCell>Created</TableHeadCell>
                      <TableHeadCell>Actions</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {migrations.map((migration) => (
                      <TableRow key={migration.id}>
                        <TableCell>
                          <div className="font-medium">{getSpaceName(migration.source_space_id)}</div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-900 dark:text-white">
                            {getGraphName(migration.source_graph_id)}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="font-medium">{getSpaceName(migration.target_space_id)}</div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-900 dark:text-white">
                            {getGraphName(migration.target_graph_id)}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge color="gray">{migration.migration_type}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge color={getStatusColor(migration.status)}>
                            {migration.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="w-24">
                            <Progress
                              progress={migration.progress}
                              color={migration.status === 'failed' ? 'red' : 'blue'}
                              size="sm"
                            />
                            <div className="text-xs text-gray-500 mt-1">
                              {migration.progress}%
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {migration.triples_migrated ? `${migration.triples_migrated.toLocaleString()}` : '0'} / {migration.total_triples ? migration.total_triples.toLocaleString() : '0'}
                        </TableCell>
                        <TableCell className="text-sm">
                          {formatDate(migration.created_time)}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => navigate(`/data/migrate/${migration.id}`)}
                            >
                              <HiEye className="w-3 h-3 mr-1" />
                              Details
                            </Button>
                            {migration.status === 'pending' && (
                              <Button
                                size="xs"
                                color="green"
                                onClick={() => handleStartMigration(migration.id)}
                              >
                                <HiPlay className="w-3 h-3 mr-1" />
                                Start
                              </Button>
                            )}
                            {migration.status === 'processing' && (
                              <Button
                                size="xs"
                                color="red"
                                onClick={() => handleCancelMigration(migration.id)}
                              >
                                <HiStop className="w-3 h-3 mr-1" />
                                Cancel
                              </Button>
                            )}
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteMigration(migration.id)}
                              disabled={migration.status === 'processing'}
                            >
                              <HiTrash className="w-3 h-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {migrations.length === 0 && (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No data migrations found. Create your first migration to get started.
                </div>
              )}
            </div>
          )}
          
          {activeTab === 'tracking' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Data Tracking</h2>
                  <p className="text-gray-600 dark:text-gray-400">Monitor data processing operations</p>
                </div>
                <Button onClick={() => navigate('/data/tracking/new')}>
                  <HiPlus className="w-4 h-4 mr-2" />
                  Add Data Tracking
                </Button>
              </div>

              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>Name</TableHeadCell>
                      <TableHeadCell>Space</TableHeadCell>
                      <TableHeadCell>Graph</TableHeadCell>
                      <TableHeadCell>External System</TableHeadCell>
                      <TableHeadCell>Status</TableHeadCell>
                      <TableHeadCell>Progress</TableHeadCell>
                      <TableHeadCell>Slices</TableHeadCell>
                      <TableHeadCell>Records</TableHeadCell>
                      <TableHeadCell>Last Updated</TableHeadCell>
                      <TableHeadCell>Actions</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {trackings.map((tracking) => (
                      <TableRow key={tracking.id}>
                        <TableCell className="font-medium">
                          {tracking.name}
                        </TableCell>
                        <TableCell>
                          <div className="font-medium">{getSpaceName(tracking.space_id)}</div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-900 dark:text-white">
                            {getGraphName(tracking.graph_id)}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">
                            {tracking.external_system || 'N/A'}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge color={getStatusColor(tracking.status)}>
                            {tracking.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="w-full bg-gray-200 rounded-full h-2.5 dark:bg-gray-700">
                            <div 
                              className="bg-blue-600 h-2.5 rounded-full" 
                              style={{ width: `${tracking.overall_progress}%` }}
                            ></div>
                          </div>
                          <span className="text-xs text-gray-500 mt-1">
                            {tracking.overall_progress}%
                          </span>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">
                            {tracking.parallel_slices}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">
                            {tracking.records_processed.toLocaleString()} / {tracking.total_records.toLocaleString()}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-500">
                            {new Date(tracking.last_updated).toLocaleDateString()}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => navigate(`/data/tracking/${tracking.id}`)}
                            >
                              <HiEye className="w-3 h-3 mr-1" />
                              Details
                            </Button>
                            {tracking.status === 'pending' ? (
                              <Button
                                size="xs"
                                color="green"
                                onClick={() => handleStartTracking(tracking.id)}
                              >
                                <HiPlay className="w-3 h-3 mr-1" />
                                Start
                              </Button>
                            ) : tracking.status === 'paused' ? (
                              <Button
                                size="xs"
                                color="green"
                                onClick={() => handleResumeTracking(tracking.id)}
                              >
                                <HiPlay className="w-3 h-3 mr-1" />
                                Resume
                              </Button>
                            ) : tracking.status === 'processing' ? (
                              <Button
                                size="xs"
                                color="red"
                                onClick={() => handlePauseTracking(tracking.id)}
                              >
                                <HiStop className="w-3 h-3 mr-1" />
                                Pause
                              </Button>
                            ) : null}
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteTracking(tracking.id)}
                              disabled={tracking.status === 'processing'}
                            >
                              <HiTrash className="w-3 h-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {trackings.length === 0 && (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No data tracking found. Create your first tracking to get started.
                </div>
              )}
            </div>
          )}
          
          {activeTab === 'checkpoint' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Data Checkpoint</h2>
                  <p className="text-gray-600 dark:text-gray-400">Manage data checkpoints and snapshots</p>
                </div>
                <Button onClick={() => navigate('/data/checkpoint/new')}>
                  <HiPlus className="w-4 h-4 mr-2" />
                  Add Data Checkpoint
                </Button>
              </div>

              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>Name</TableHeadCell>
                      <TableHeadCell>Space</TableHeadCell>
                      <TableHeadCell>Graph</TableHeadCell>
                      <TableHeadCell>Timestamp</TableHeadCell>
                      <TableHeadCell>Hash</TableHeadCell>
                      <TableHeadCell>External System</TableHeadCell>
                      <TableHeadCell>Created</TableHeadCell>
                      <TableHeadCell>Actions</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {checkpoints.map((checkpoint) => (
                      <TableRow key={checkpoint.id}>
                        <TableCell className="font-medium">
                          {checkpoint.name}
                        </TableCell>
                        <TableCell>
                          <div className="font-medium">{getSpaceName(checkpoint.space_id)}</div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-900 dark:text-white">
                            {getGraphName(checkpoint.graph_id)}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-900 dark:text-white">
                            {new Date(checkpoint.checkpoint_timestamp).toLocaleString()}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-xs font-mono text-gray-600 dark:text-gray-400">
                            {checkpoint.checkpoint_hash.substring(0, 12)}...
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">
                            {checkpoint.external_system || 'N/A'}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm text-gray-500">
                            {new Date(checkpoint.created_time).toLocaleDateString()}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => navigate(`/data/checkpoint/${checkpoint.id}`)}
                            >
                              <HiEye className="w-3 h-3 mr-1" />
                              Details
                            </Button>
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => handleDeleteCheckpoint(checkpoint.id)}
                            >
                              <HiTrash className="w-3 h-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {checkpoints.length === 0 && (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No data checkpoints found. Create your first checkpoint to get started.
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Delete Import Confirmation Modal */}
      <Modal show={showDeleteImportModal} onClose={() => setShowDeleteImportModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Import</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this import? This action cannot be undone.
          </p>
          {importToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded-lg mb-6">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                <strong>Import:</strong> {importToDelete.name}
              </p>
            </div>
          )}
          <div className="flex gap-3">
            <Button 
              onClick={confirmDeleteImport}
              color="failure"
              className="flex-1"
            >
              Yes, Delete Import
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteImportModal(false);
                setImportToDelete(null);
              }}
              className="flex-1"
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Export Confirmation Modal */}
      <Modal show={showDeleteExportModal} onClose={() => setShowDeleteExportModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Export</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this export? This action cannot be undone.
          </p>
          {exportToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded-lg mb-6">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                <strong>Export:</strong> {exportToDelete.name}
              </p>
            </div>
          )}
          <div className="flex gap-3">
            <Button 
              onClick={confirmDeleteExport}
              color="failure"
              className="flex-1"
            >
              Yes, Delete Export
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteExportModal(false);
                setExportToDelete(null);
              }}
              className="flex-1"
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Migration Confirmation Modal */}
      <Modal show={showDeleteMigrationModal} onClose={() => setShowDeleteMigrationModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Migration</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this migration? This action cannot be undone.
          </p>
          {migrationToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded-lg mb-6">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                <strong>Migration:</strong> {getSpaceName(migrationToDelete.source_space_id)} → {getSpaceName(migrationToDelete.target_space_id)}
              </p>
            </div>
          )}
          <div className="flex gap-3">
            <Button 
              onClick={confirmDeleteMigration}
              color="failure"
              className="flex-1"
            >
              Yes, Delete Migration
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteMigrationModal(false);
                setMigrationToDelete(null);
              }}
              className="flex-1"
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Tracking Confirmation Modal */}
      <Modal show={showDeleteTrackingModal} onClose={() => setShowDeleteTrackingModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Tracking</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this tracking operation? This action cannot be undone.
          </p>
          {trackingToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded-lg mb-6">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                <strong>Tracking:</strong> {trackingToDelete.name}
              </p>
            </div>
          )}
          <div className="flex gap-3">
            <Button 
              onClick={confirmDeleteTracking}
              color="failure"
              className="flex-1"
            >
              Yes, Delete Tracking
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteTrackingModal(false);
                setTrackingToDelete(null);
              }}
              className="flex-1"
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Delete Checkpoint Confirmation Modal */}
      <Modal show={showDeleteCheckpointModal} onClose={() => setShowDeleteCheckpointModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Checkpoint</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this checkpoint? This action cannot be undone.
          </p>
          {checkpointToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded-lg mb-6">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                <strong>Checkpoint:</strong> {checkpointToDelete.name}
              </p>
            </div>
          )}
          <div className="flex gap-3">
            <Button 
              onClick={confirmDeleteCheckpoint}
              color="failure"
              className="flex-1"
            >
              Yes, Delete Checkpoint
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteCheckpointModal(false);
                setCheckpointToDelete(null);
              }}
              className="flex-1"
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );

};

export default Data;
