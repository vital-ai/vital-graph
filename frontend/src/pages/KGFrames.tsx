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
interface KGFrame {
  uri: string;
  rdf_type: string;
  name: string;
  properties_count: number;
}

const KGFrames: React.FC = () => {
  const navigate = useNavigate();
  
  // Get shared state from parent ObjectsLayout
  const context = useOutletContext<{
    selectedSpace: string;
    selectedGraph: string;
    spacesLoading: boolean;
    graphsLoading: boolean;
    error: string | null;
  }>();

  // Handle case where context might be undefined initially
  const {
    selectedSpace = '',
    selectedGraph = '',
    spacesLoading = true,
  } = context || {};

  // Local state management
  const [frames, setFrames] = useState<KGFrame[]>([]);
  const [filteredFrames, setFilteredFrames] = useState<KGFrame[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [itemsPerPage, setItemsPerPage] = useState<number>(10);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [frameToDelete, setFrameToDelete] = useState<KGFrame | null>(null);

  // Space and graph selection is now handled by parent ObjectsLayout

  const [totalCount, setTotalCount] = useState<number>(0);

  const stripBrackets = (v: string): string => v.replace(/^<|>$/g, '');
  const stripLiteral = (v: string): string => v.replace(/^"/, '').replace(/"(@[a-z-]+|\^\^<[^>]+>)?$/, '');

  // Fetch KG frames for selected space and graph
  const fetchFrames = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await axios.get('/api/graphs/kgframes', {
        params: {
          space_id: selectedSpace,
          graph_id: selectedGraph,
          page_size: itemsPerPage,
          offset: (currentPage - 1) * itemsPerPage
        }
      });
      
      const data = response.data;
      // API returns QuadResponse: { results: [{s,p,o,g}], total_count, page_size, offset }
      const quads: Array<{s: string; p: string; o: string; g?: string}> = data.results || [];
      
      // Group quads by subject
      const subjectMap = new Map<string, Map<string, string[]>>();
      for (const quad of quads) {
        const subj = stripBrackets(quad.s);
        if (!subjectMap.has(subj)) subjectMap.set(subj, new Map());
        const preds = subjectMap.get(subj)!;
        const pred = stripBrackets(quad.p);
        if (!preds.has(pred)) preds.set(pred, []);
        preds.get(pred)!.push(quad.o);
      }
      
      const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
      const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
      
      const frames: KGFrame[] = [];
      for (const [uri, preds] of subjectMap) {
        const typeVals = preds.get(RDF_TYPE) || [];
        const rdfType = typeVals.length > 0 ? stripBrackets(typeVals[0]) : 'Unknown';
        const nameVals = preds.get(HAS_NAME) || [];
        const name = nameVals.length > 0 ? stripLiteral(nameVals[0]) : uri.split(/[/#]/).pop() || uri;
        
        frames.push({
          uri,
          rdf_type: rdfType,
          name,
          properties_count: preds.size,
        });
      }
      
      setFrames(frames);
      setTotalCount(data.total_count ?? frames.length);
    } catch (err) {
      console.error('Error fetching KG frames:', err);
      setError('Failed to load KG frames. Please try again later.');
      setFrames([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, selectedGraph, itemsPerPage, currentPage]);

  // Set frames directly since filtering is done server-side
  useEffect(() => {
    setFilteredFrames(frames);
  }, [frames]);

  useEffect(() => {
    fetchFrames();
    // Reset pagination when component mounts or tab becomes active
    setCurrentPage(1);
  }, [fetchFrames]);
  const currentFrames = filteredFrames;
  const totalPages = Math.max(1, Math.ceil(totalCount / itemsPerPage));

  return (
    <>

      {/* Add Frame Button */}
      {selectedSpace && selectedGraph && (
        <div className="mb-6">
          <Button 
            onClick={() => {
              navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/frame/new?mode=create`);
            }} 
            color="blue"
          >
            <HiPlus className="mr-2 h-4 w-4" />
            Add KG Frame
          </Button>
        </div>
      )}

      {/* Search and Filter */}
      {selectedSpace && selectedGraph && (
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
      
      {selectedSpace && !selectedGraph && (
        <div className="text-center py-12">
          <div className="text-gray-500 dark:text-gray-400">
            <p className="text-lg mb-2">Select a graph to view KG frames</p>
            <p className="text-sm">Choose a graph from the dropdown above to see its frames.</p>
          </div>
        </div>
      )}

      {/* Loading Spinner */}
      {selectedSpace && selectedGraph && loading && (
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
      {selectedSpace && selectedGraph && !loading && filteredFrames.length === 0 && !error ? (
        <Alert color="info">
          {searchTerm ? 
            `No KG frames found matching "${searchTerm}". Try a different search term.` :
            'No KG frames found in this graph. Add your first frame to get started.'
          }
        </Alert>
      ) : selectedSpace && selectedGraph && !loading && currentFrames.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeadCell>Frame URI</TableHeadCell>
                  <TableHeadCell>RDF Type</TableHeadCell>
                  <TableHeadCell>Frame Type</TableHeadCell>
                  <TableHeadCell>Properties</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {currentFrames.map((frame) => (
                  <TableRow key={frame.uri}>
                    <TableCell className="font-medium">
                      <div className="max-w-xs">
                        <div className="font-mono text-sm text-blue-600 truncate" title={frame.uri}>
                          {frame.name}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {frame.uri}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm truncate max-w-xs" title={frame.rdf_type}>
                      {frame.rdf_type.split(/[/#]/).pop()}
                    </TableCell>
                    <TableCell>
                      <Badge color="purple">KG Frame</Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {frame.properties_count} properties
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex space-x-2">
                        <Button
                          size="xs"
                          color="blue"
                          onClick={() => {
                            navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/frame/${encodeURIComponent(frame.uri)}`);
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
                {frameToDelete.name}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {frameToDelete.uri}
              </p>
            </div>
          )}
          <div className="flex justify-end gap-3">
            <Button 
              onClick={() => {
                console.log('Deleting frame:', frameToDelete?.uri);
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
