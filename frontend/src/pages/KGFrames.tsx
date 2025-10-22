import React, { useState, useEffect, useCallback } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Alert,
  TextInput,
  Select,
  Label,
  Pagination,
  Badge,
  Spinner,
  Modal
} from 'flowbite-react';
import { HiPlus, HiEye, HiTrash } from 'react-icons/hi2';
import { HiSearch } from 'react-icons/hi';
import { type Space, type Graph, type KGType } from '../mock';

const KGFrames: React.FC = () => {
  const navigate = useNavigate();
  
  // Get shared state from parent ObjectsLayout
  const context = useOutletContext<{
    selectedSpace: string;
    selectedGraph: number | '';
    spaces: Space[];
    graphs: Graph[];
    spacesLoading: boolean;
    graphsLoading: boolean;
    error: string | null;
  }>();

  // Handle case where context might be undefined initially
  const {
    selectedSpace = '',
    selectedGraph = '',
    graphs = [],
    spacesLoading = true
  } = context || {};

  // Local state management
  const [frames, setFrames] = useState<KGType[]>([]);
  const [filteredFrames, setFilteredFrames] = useState<KGType[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [itemsPerPage, setItemsPerPage] = useState<number>(10);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [frameToDelete, setFrameToDelete] = useState<KGType | null>(null);

  // Space and graph selection is now handled by parent ObjectsLayout

  // Fetch KG frames for selected space and graph
  const fetchFrames = useCallback(async () => {
    if (!selectedSpace || selectedGraph === '') return;
    
    try {
      setLoading(true);
      setError('');
      
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
      if (!selectedGraphObj) {
        setError('Selected graph not found');
        setFrames([]);
        return;
      }
      
      // Make API call to fetch KG frames using axios (handles auth automatically)
      console.log('Fetching frames for space:', selectedSpace, 'graph:', selectedGraphObj.graph_uri);
      
      const response = await axios.get('/api/graphs/kgframes', {
        params: {
          space_id: selectedSpace,
          graph_id: selectedGraphObj.graph_uri,
          page_size: itemsPerPage,
          offset: (currentPage - 1) * itemsPerPage
        }
      });
      
      const data = response.data;
      console.log('KG Frames API response:', data);
      
      // Handle the response data structure - frames data is in data.frames
      if (data.frames && data.frames['@graph'] && Array.isArray(data.frames['@graph'])) {
        // Transform JSON-LD frames to KGType format
        const transformedFrames = data.frames['@graph'].map((frame: any, index: number) => ({
          id: index,
          type_name: frame['@id'] || frame.URI || `frame-${index}`,
          type_uri: frame['@id'] || frame.URI || '',
          uri: frame['@id'] || frame.URI || '',
          description: frame['http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription'] || 'No description',
          created_at: frame.created_time || new Date().toISOString(),
          updated_at: frame.last_modified || new Date().toISOString(),
          space_id: selectedSpace,
          graph_id: typeof selectedGraph === 'number' ? selectedGraph : 0,
          properties: Object.keys(frame).filter(key => 
            key !== '@context' && key !== '@id' && key !== '@type' && key !== 'URI'
          )
        }));
        setFrames(transformedFrames);
      } else if (Array.isArray(data.frames)) {
        setFrames(data.frames);
      } else if (Array.isArray(data)) {
        setFrames(data);
      } else {
        setFrames([]);
      }
    } catch (err) {
      console.error('Error fetching KG frames:', err);
      setError('Failed to load KG frames. Please try again later.');
      setFrames([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, graphs, itemsPerPage, currentPage]);

  // Set frames directly since filtering is done server-side
  useEffect(() => {
    setFilteredFrames(frames);
  }, [frames]);

  useEffect(() => {
    fetchFrames();
    // Reset pagination when component mounts or tab becomes active
    setCurrentPage(1);
  }, [fetchFrames]);
  // For server-side pagination, use the frames directly (no slicing needed)
  const currentFrames = filteredFrames;
  // TODO: Get total count from API response to calculate totalPages properly
  const totalPages = Math.ceil(filteredFrames.length / itemsPerPage);

  // Utility functions
  const formatDateTime = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  return (
    <>

      {/* Add Frame Button */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mb-6">
          <Button 
            onClick={() => {
              const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
              const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
              navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/frame/new?mode=create`);
            }} 
            color="blue"
          >
            <HiPlus className="mr-2 h-4 w-4" />
            Add KG Frame
          </Button>
        </div>
      )}

      {/* Search and Filter */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
            <div className="flex-1">
              <div className="relative">
                <HiSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
                <TextInput
                  type="text"
                  placeholder="Search KG frames by name, description, or URI..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>
            <div className="flex-shrink-0">
              <Label htmlFor="page-size">Items per page</Label>
              <Select
                id="page-size"
                value={itemsPerPage}
                onChange={(e) => {
                  setItemsPerPage(parseInt(e.target.value));
                  setCurrentPage(1);
                }}
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </Select>
            </div>
          </div>
        </div>
      )}

      {/* Selection Required Messages */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a space to view KG frames</p>
            <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
          </div>
        </div>
      )}
      
      {selectedSpace && selectedGraph === '' && graphs.length > 0 && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view KG frames</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its frames.</p>
          </div>
        </div>
      )}

      {/* Loading Spinner */}
      {selectedSpace && selectedGraph !== '' && loading && (
        <div className="mt-8 flex justify-center">
          <Spinner size="lg" />
          <span className="ml-2 text-gray-600 dark:text-gray-400">Loading KG frames...</span>
        </div>
      )}

      {error && (
        <Alert color="failure">
          {error}
        </Alert>
      )}

      {/* Frames Table */}
      {selectedSpace && selectedGraph !== '' && !loading && filteredFrames.length === 0 && !error ? (
        <Alert color="info">
          {searchTerm ? 
            `No KG frames found matching "${searchTerm}". Try a different search term.` :
            'No KG frames found in this graph. Add your first frame to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph !== '' && !loading && currentFrames.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Frame URI</TableHeadCell>
                  <TableHeadCell>RDF Type</TableHeadCell>
                  <TableHeadCell>Frame Type</TableHeadCell>
                  <TableHeadCell>Properties</TableHeadCell>
                  <TableHeadCell>Last Modified</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {currentFrames.map((frame) => (
                  <TableRow key={frame.id}>
                    <TableCell className="font-medium">
                      <div className="max-w-xs">
                        <div className="font-mono text-sm text-blue-600 truncate">
                          {frame.type_name}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {frame.uri}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {frame.type_uri}
                    </TableCell>
                    <TableCell>
                      <Badge color="purple">KG Frame</Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {frame.properties.length} properties
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                      {formatDateTime(frame.updated_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex space-x-2">
                        <Button
                          size="xs"
                          color="blue"
                          onClick={() => {
                            const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
                            const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
                            navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/frame/${encodeURIComponent(frame.type_uri || frame.id?.toString() || '')}`);
                          }}
                        >
                          <HiEye className="h-3 w-3" />
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => {
                            setFrameToDelete(frame);
                            setShowDeleteModal(true);
                          }}
                        >
                          <HiTrash className="h-3 w-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center mt-6">
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={setCurrentPage}
                showIcons
              />
            </div>
          )}
        </>
      )}

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onClose={() => setShowDeleteModal(false)} size="md">
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Frame</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this KG frame? This action cannot be undone.
          </p>
          {frameToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded mb-6">
              <p className="text-sm font-mono text-gray-800 dark:text-gray-200">
                {frameToDelete.type_name}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {frameToDelete.uri}
              </p>
            </div>
          )}
          <div className="flex justify-end gap-3">
            <Button 
              onClick={() => {
                console.log('Deleting frame:', frameToDelete?.id);
                setShowDeleteModal(false);
                setFrameToDelete(null);
              }} 
              color="failure"
            >
              Delete
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteModal(false);
                setFrameToDelete(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
};

export default KGFrames;
