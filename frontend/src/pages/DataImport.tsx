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
  HiPlay,
  HiStop
} from 'react-icons/hi';
import { mockDataImports, type DataImport } from '../mock/data';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';
import DataIcon from '../components/icons/DataIcon';

const DataImport: React.FC = () => {
  const navigate = useNavigate();
  const [imports, setImports] = useState<DataImport[]>([]);
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
      
      setImports(mockDataImports);
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

  const handleDeleteImport = async (importId: number) => {
    if (window.confirm('Are you sure you want to delete this import?')) {
      setImports(prev => prev.filter(imp => imp.id !== importId));
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
            Data Import
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Import data into your RDF graphs
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
        </div>
      </Card>
    </div>
  );
};

export default DataImport;
