import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
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
  Alert
} from 'flowbite-react';
import {
  HiPlus,
  HiEye,
  HiTrash,
  HiDownload,
  HiPlay,
  HiStop
} from 'react-icons/hi';
import { mockDataExports, type DataExport } from '../mock/data';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import DataIcon from '../components/icons/DataIcon';

const DataExport: React.FC = () => {
  const navigate = useNavigate();
  const [exports, setExports] = useState<DataExport[]>([]);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      // Simulate API calls
      await new Promise(resolve => setTimeout(resolve, 500));
      
      setExports(mockDataExports);
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
  }, [fetchData]);

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

  const handleDeleteExport = async (exportId: number) => {
    if (window.confirm('Are you sure you want to delete this export?')) {
      setExports(prev => prev.filter(exp => exp.id !== exportId));
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
            Data Export
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Export data from your RDF graphs
        </p>
      </div>

      {error && (
        <Alert color="failure" className="mb-4">
          {error}
        </Alert>
      )}

      <Card>
        <div className="p-6">
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
                    <TableHeadCell>Name</TableHeadCell>
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
                      <TableCell className="font-medium">{exportItem.name}</TableCell>
                      <TableCell>{getSpaceName(exportItem.space_id)}</TableCell>
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
        </div>
      </Card>
    </div>
  );
};

export default DataExport;
