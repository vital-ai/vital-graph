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

const KGEntities: React.FC = () => {
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
  const [entities, setEntities] = useState<KGType[]>([]);
  const [filteredEntities, setFilteredEntities] = useState<KGType[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [itemsPerPage, setItemsPerPage] = useState<number>(10);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [entityToDelete, setEntityToDelete] = useState<KGType | null>(null);

  // Space and graph selection is now handled by parent ObjectsLayout

  // Fetch entities for selected space and graph
  const fetchEntities = useCallback(async () => {
    if (!selectedSpace || selectedGraph === '') return;
    
    try {
      setLoading(true);
      setError('');
      
      // Find the selected graph to get its URI
      const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
      if (!selectedGraphObj) {
        setError('Selected graph not found');
        setEntities([]);
        return;
      }
      
      // Make API call to fetch KG entities using axios (handles auth automatically)
      console.log('Fetching entities for space:', selectedSpace, 'graph:', selectedGraphObj.graph_uri);
      
      const response = await axios.get('/api/graphs/kgentities', {
        params: {
          space_id: selectedSpace,
          graph_id: selectedGraphObj.graph_uri,
          page_size: itemsPerPage,
          offset: (currentPage - 1) * itemsPerPage
        }
      });
      
      const data = response.data;
      console.log('KG Entities API response:', data);
      
      // Handle the response data structure - entities data is in data.entities
      if (data.entities && data.entities['@graph'] && Array.isArray(data.entities['@graph'])) {
        // Transform JSON-LD entities to KGType format
        const transformedEntities = data.entities['@graph'].map((entity: any, index: number) => ({
          id: index,
          type_name: entity['@id'] || entity.URI || `entity-${index}`,
          type_uri: entity['@id'] || entity.URI || '',
          uri: entity['@id'] || entity.URI || '',
          description: entity['http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription'] || 'No description',
          created_at: entity.created_time || new Date().toISOString(),
          updated_at: entity.last_modified || new Date().toISOString(),
          space_id: selectedSpace,
          graph_id: typeof selectedGraph === 'number' ? selectedGraph : 0,
          properties: Object.keys(entity).filter(key => 
            key !== '@context' && key !== '@id' && key !== '@type' && key !== 'URI'
          )
        }));
        setEntities(transformedEntities);
      } else if (Array.isArray(data.entities)) {
        setEntities(data.entities);
      } else if (Array.isArray(data)) {
        setEntities(data);
      } else {
        setEntities([]);
      }
    } catch (err) {
      console.error('Error fetching KG entities:', err);
      setError('Failed to load KG entities. Please try again later.');
      setEntities([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage]);

  // Set entities directly since filtering is done server-side
  useEffect(() => {
    setFilteredEntities(entities);
  }, [entities]);

  // Space and graph selection is now handled by parent ObjectsLayout

  useEffect(() => {
    fetchEntities();
    // Reset pagination when component mounts or tab becomes active
    setCurrentPage(1);
  }, [fetchEntities]);

  // For server-side pagination, use the entities directly (no slicing needed)
  const currentEntities = filteredEntities;
  // TODO: Get total count from API response to calculate totalPages properly
  const totalPages = Math.ceil(filteredEntities.length / itemsPerPage);

  // Utility functions
  const formatDateTime = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  return (
    <>

      {/* Add Entity Button */}
      {selectedSpace && selectedGraph !== '' && (
        <div className="mb-6">
          <Button 
            onClick={() => {
              const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
              const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
              navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/entity/new?mode=create`);
            }} 
            color="blue"
          >
            <HiPlus className="mr-2 h-4 w-4" />
            Add KG Entity
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
                  placeholder="Search KG entities by name, description, or URI..."
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
            <p className="text-lg mb-2">Select a space to view KG entities</p>
            <p className="text-sm">Choose a space from the dropdown above to see available graphs.</p>
          </div>
        </div>
      )}
      
      {selectedSpace && selectedGraph === '' && graphs.length > 0 && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view KG entities</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its entities.</p>
          </div>
        </div>
      )}

      {/* Loading Spinner */}
      {selectedSpace && selectedGraph !== '' && loading && (
        <div className="mt-8 flex justify-center">
          <Spinner size="lg" />
          <span className="ml-2 text-gray-600 dark:text-gray-400">Loading KG entities...</span>
        </div>
      )}

      {error && (
        <Alert color="failure">
          {error}
        </Alert>
      )}

      {/* Entities Table */}
      {selectedSpace && selectedGraph !== '' && !loading && filteredEntities.length === 0 && !error ? (
        <Alert color="info">
          {searchTerm ? 
            `No KG entities found matching "${searchTerm}". Try a different search term.` :
            'No KG entities found in this graph. Add your first entity to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph !== '' && !loading && currentEntities.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Entity URI</TableHeadCell>
                  <TableHeadCell>RDF Type</TableHeadCell>
                  <TableHeadCell>Entity Type</TableHeadCell>
                  <TableHeadCell>Properties</TableHeadCell>
                  <TableHeadCell>Last Modified</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {currentEntities.map((entity) => (
                  <TableRow key={entity.id}>
                    <TableCell className="font-medium">
                      <div className="max-w-xs">
                        <div className="font-mono text-sm text-blue-600 truncate">
                          {entity.type_name}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {entity.uri}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {entity.type_uri}
                    </TableCell>
                    <TableCell>
                      <Badge color="blue">KG Entity</Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {entity.properties.length} properties
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-gray-600 dark:text-gray-400">
                      {formatDateTime(entity.updated_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex space-x-2">
                        <Button
                          size="xs"
                          color="blue"
                          onClick={() => {
                            const selectedGraphObj = graphs.find(g => g.id === selectedGraph);
                            const graphUri = selectedGraphObj ? selectedGraphObj.graph_uri : selectedGraph;
                            navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(graphUri)}/entity/${encodeURIComponent(entity.type_uri || entity.id?.toString() || '')}`);
                          }}
                        >
                          <HiEye className="h-3 w-3" />
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => {
                            setEntityToDelete(entity);
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
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Delete Entity</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this KG entity? This action cannot be undone.
          </p>
          {entityToDelete && (
            <div className="bg-gray-50 dark:bg-gray-700 p-3 rounded mb-6">
              <p className="text-sm font-mono text-gray-800 dark:text-gray-200">
                {entityToDelete.type_name}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {entityToDelete.uri}
              </p>
            </div>
          )}
          <div className="flex justify-end gap-3">
            <Button 
              onClick={() => {
                console.log('Deleting entity:', entityToDelete?.id);
                setShowDeleteModal(false);
                setEntityToDelete(null);
              }} 
              color="failure"
            >
              Delete
            </Button>
            <Button 
              color="gray" 
              onClick={() => {
                setShowDeleteModal(false);
                setEntityToDelete(null);
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

export default KGEntities;
