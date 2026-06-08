import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert, Badge, Button, Modal, Pagination, Select, Spinner,
  Label, TextInput, Textarea
} from 'flowbite-react';
import { HiPlus, HiPencil, HiTrash, HiSearch, HiDatabase } from 'react-icons/hi';
import { type SpaceInfo } from '../types/api';
import { type GraphInfo } from '../types/graphs';
import { apiService } from '../services/ApiService';
import TriplesIcon from '../components/icons/TriplesIcon';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import {
  stripBrackets,
  parseObjectTerm,
  buildQuad,
  shortenUri,
  extractGraphName,
  type Quad,
} from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';

interface ParsedTriple {
  key: string;
  subject: string;
  predicate: string;
  object: string;
  objectType: 'uri' | 'literal';
}

const Triples: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId } = useParams<{ spaceId?: string; graphId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState(spaceId || '');
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedGraph, setSelectedGraph] = useState(graphId ? decodeURIComponent(graphId) : '');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [graphsLoading, setGraphsLoading] = useState(false);

  const [triples, setTriples] = useState<ParsedTriple[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);

  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Modal state
  const [modalMode, setModalMode] = useState<'add' | 'edit' | null>(null);
  const [editingOriginal, setEditingOriginal] = useState<ParsedTriple | null>(null);
  const [deletingTriple, setDeletingTriple] = useState<ParsedTriple | null>(null);
  const [tripleForm, setTripleForm] = useState({ subject: '', predicate: '', object: '', objectType: 'uri' as 'uri' | 'literal' });

  // Navigate to hierarchical URL when space/graph selection changes
  useEffect(() => {
    if (selectedSpace && selectedGraph && !spaceId && !graphId) {
      navigate(`/space/${selectedSpace}/graph/${encodeURIComponent(selectedGraph)}/triples`);
    }
  }, [selectedSpace, selectedGraph, navigate, spaceId, graphId]);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => { setDebouncedSearch(searchTerm); setCurrentPage(1); }, 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  // Fetch spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setSpacesLoading(true);
      setSpaces(await apiService.getSpaces());
    } catch { setError('Failed to load spaces.'); }
    finally { setSpacesLoading(false); }
  }, []);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  // Fetch graphs
  const fetchGraphs = useCallback(async () => {
    if (!selectedSpace) { setGraphs([]); return; }
    try {
      setGraphsLoading(true);
      setGraphs(await apiService.getGraphs(selectedSpace));
    } catch { setError('Failed to load graphs.'); setGraphs([]); }
    finally { setGraphsLoading(false); }
  }, [selectedSpace]);

  useEffect(() => {
    fetchGraphs();
    if (!graphId) setSelectedGraph('');
  }, [fetchGraphs, graphId]);

  // Fetch triples
  const fetchTriples = useCallback(async () => {
    if (!selectedSpace || !selectedGraph) return;
    try {
      setLoading(true);
      setError(null);
      const offset = (currentPage - 1) * itemsPerPage;
      const data = await apiService.getTriples(selectedSpace, selectedGraph, {
        page_size: itemsPerPage,
        offset,
        object_filter: debouncedSearch || undefined
      });
      const quads: Quad[] = data.results || [];
      const parsed: ParsedTriple[] = quads.map((q, i) => {
        const { value: objectValue, type: objectType } = parseObjectTerm(q.o);
        return {
          key: `${offset + i}`,
          subject: stripBrackets(q.s),
          predicate: stripBrackets(q.p),
          object: objectValue,
          objectType,
        };
      });
      setTriples(parsed);
      setTotalCount(data.total_count || parsed.length);
    } catch {
      setError('Failed to load triples.');
      setTriples([]);
      setTotalCount(0);
    } finally { setLoading(false); }
  }, [selectedSpace, selectedGraph, debouncedSearch, currentPage, itemsPerPage]);

  useEffect(() => { fetchTriples(); }, [fetchTriples]);

  const totalPages = Math.max(1, Math.ceil(totalCount / itemsPerPage));

  // CRUD helpers

  const handleSaveTriple = async () => {
    if (!tripleForm.subject || !tripleForm.predicate || !tripleForm.object || !selectedGraph) return;
    try {
      if (modalMode === 'edit' && editingOriginal) {
        // Delete old, add new
        await apiService.deleteTriples(selectedSpace, selectedGraph, {
          quads: [buildQuad(editingOriginal.subject, editingOriginal.predicate, editingOriginal.object, editingOriginal.objectType, selectedGraph)]
        });
      }
      await apiService.addTriples(selectedSpace, selectedGraph, {
        quads: [buildQuad(tripleForm.subject, tripleForm.predicate, tripleForm.object, tripleForm.objectType, selectedGraph)]
      });
      setModalMode(null);
      setEditingOriginal(null);
      setTripleForm({ subject: '', predicate: '', object: '', objectType: 'uri' });
      await fetchTriples();
    } catch {
      setError(`Failed to ${modalMode === 'edit' ? 'update' : 'add'} triple.`);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deletingTriple || !selectedGraph) return;
    try {
      await apiService.deleteTriples(selectedSpace, selectedGraph, {
        quads: [buildQuad(deletingTriple.subject, deletingTriple.predicate, deletingTriple.object, deletingTriple.objectType, selectedGraph)]
      });
      setDeletingTriple(null);
      await fetchTriples();
    } catch {
      setError('Failed to delete triple.');
      setDeletingTriple(null);
    }
  };

  const openAdd = () => {
    setTripleForm({ subject: '', predicate: '', object: '', objectType: 'uri' });
    setEditingOriginal(null);
    setModalMode('add');
  };

  const openEdit = (t: ParsedTriple) => {
    setTripleForm({ subject: t.subject, predicate: t.predicate, object: t.object, objectType: t.objectType });
    setEditingOriginal(t);
    setModalMode('edit');
  };

  const hasSelection = selectedSpace && selectedGraph;

  return (
    <div className="space-y-6">
      <NavigationBreadcrumb
        spaceId={spaceId}
        graphId={graphId}
        currentPageName="Triples"
        currentPageIcon={TriplesIcon}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <TriplesIcon className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Triples</h1>
          </div>
          {hasSelection && !loading && (
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
              {totalCount.toLocaleString()} triple{totalCount !== 1 ? 's' : ''}
            </p>
          )}
        </div>
        {hasSelection && (
          <Button size="sm" color="blue" onClick={openAdd}>
            <HiPlus className="mr-1.5 h-4 w-4" />Add Triple
          </Button>
        )}
      </div>

      {/* Space / Graph selectors */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="flex-1 max-w-xs">
          <Label htmlFor="space-select" className="text-xs">Space</Label>
          <Select
            id="space-select"
            value={selectedSpace}
            onChange={(e) => { setSelectedSpace(e.target.value); setSelectedGraph(''); }}
            disabled={spacesLoading}
          >
            <option value="">Choose a space...</option>
            {spaces.map((s: SpaceInfo) => (
              <option key={s.space} value={s.space}>{s.space_name}</option>
            ))}
          </Select>
        </div>
        <div className="flex-1 max-w-xs">
          <Label htmlFor="graph-select" className="text-xs">Graph</Label>
          <Select
            id="graph-select"
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            disabled={!selectedSpace || graphsLoading}
          >
            <option value="">Choose a graph...</option>
            {graphs.map((g: GraphInfo) => (
              <option key={g.graph_uri} value={g.graph_uri}>{extractGraphName(g.graph_uri)}</option>
            ))}
          </Select>
        </div>
      </div>

      {/* Search + page size */}
      {hasSelection && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <TextInput
              icon={HiSearch}
              placeholder="Filter triples..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div className="w-32 flex-shrink-0">
            <Select
              value={itemsPerPage}
              onChange={(e) => { setItemsPerPage(parseInt(e.target.value)); setCurrentPage(1); }}
            >
              <option value={10}>10 / page</option>
              <option value={25}>25 / page</option>
              <option value={50}>50 / page</option>
              <option value={100}>100 / page</option>
            </Select>
          </div>
        </div>
      )}

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Prompt to select */}
      {!selectedSpace && !spacesLoading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiDatabase className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a space</p>
          <p className="text-sm mt-1">Choose a space from the dropdown above</p>
        </div>
      )}
      {selectedSpace && !selectedGraph && !graphsLoading && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <TriplesIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-lg font-medium">Select a graph</p>
          <p className="text-sm mt-1">Choose a graph to browse its RDF triples</p>
        </div>
      )}

      {/* Loading */}
      {hasSelection && loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {/* Empty */}
      {hasSelection && !loading && triples.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <TriplesIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {debouncedSearch ? (
            <>
              <p className="text-lg font-medium">No results for &quot;{debouncedSearch}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No triples yet</p>
              <p className="text-sm mt-1">Add your first triple to get started</p>
            </>
          )}
        </div>
      )}

      {/* Triples table */}
      {hasSelection && !loading && triples.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-3">Subject</th>
                  <th className="px-4 py-3">Predicate</th>
                  <th className="px-4 py-3">Object</th>
                  <th className="px-4 py-3 w-20">Type</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {triples.map((t) => (
                  <tr key={t.key} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-900 dark:text-white max-w-[14rem] truncate" title={t.subject}>
                      {shortenUri(t.subject)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-blue-600 dark:text-blue-400 max-w-[14rem] truncate" title={t.predicate}>
                      {shortenUri(t.predicate)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 dark:text-gray-300 max-w-[18rem] truncate" title={t.object}>
                      {t.objectType === 'uri' ? shortenUri(t.object) : t.object}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge color={t.objectType === 'uri' ? 'blue' : 'purple'} size="xs">
                        {t.objectType}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-1">
                        <button onClick={() => openEdit(t)} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors" title="Edit">
                          <HiPencil className="h-4 w-4" />
                        </button>
                        <button onClick={() => setDeletingTriple(t)} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-red-500 transition-colors" title="Delete">
                          <HiTrash className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex justify-center">
              <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={setCurrentPage} showIcons />
            </div>
          )}
        </>
      )}

      {/* Add / Edit Modal (unified) */}
      <Modal show={modalMode !== null} onClose={() => setModalMode(null)} size="lg">
        <div className="p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            {modalMode === 'edit' ? 'Edit Triple' : 'Add Triple'}
          </h3>
          <div className="space-y-4">
            <div>
              <Label htmlFor="m-subject">Subject</Label>
              <TextInput id="m-subject" placeholder="URI" value={tripleForm.subject}
                onChange={(e) => setTripleForm({ ...tripleForm, subject: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="m-predicate">Predicate</Label>
              <TextInput id="m-predicate" placeholder="URI" value={tripleForm.predicate}
                onChange={(e) => setTripleForm({ ...tripleForm, predicate: e.target.value })} />
            </div>
            <div className="flex gap-4">
              <div className="flex-1">
                <Label htmlFor="m-object">Object</Label>
                {tripleForm.objectType === 'literal' ? (
                  <Textarea id="m-object" placeholder="Literal value" value={tripleForm.object} rows={2}
                    onChange={(e) => setTripleForm({ ...tripleForm, object: e.target.value })} />
                ) : (
                  <TextInput id="m-object" placeholder="URI" value={tripleForm.object}
                    onChange={(e) => setTripleForm({ ...tripleForm, object: e.target.value })} />
                )}
              </div>
              <div className="w-28 flex-shrink-0">
                <Label htmlFor="m-otype">Type</Label>
                <Select id="m-otype" value={tripleForm.objectType}
                  onChange={(e) => setTripleForm({ ...tripleForm, objectType: e.target.value as 'uri' | 'literal' })}>
                  <option value="uri">URI</option>
                  <option value="literal">Literal</option>
                </Select>
              </div>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-6">
            <Button color="blue" onClick={handleSaveTriple}
              disabled={!tripleForm.subject || !tripleForm.predicate || !tripleForm.object}>
              {modalMode === 'edit' ? 'Save Changes' : 'Add Triple'}
            </Button>
            <Button color="gray" onClick={() => setModalMode(null)}>Cancel</Button>
          </div>
        </div>
      </Modal>

      {/* Delete Modal */}
      <ConfirmDialog
        open={!!deletingTriple}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeletingTriple(null)}
        title="Delete Triple"
        description="Remove this triple?"
        confirmLabel="Delete"
        variant="danger"
        detail={
          deletingTriple && (
            <>
              <p><span className="text-gray-400">S:</span> {deletingTriple.subject}</p>
              <p><span className="text-gray-400">P:</span> {deletingTriple.predicate}</p>
              <p><span className="text-gray-400">O:</span> {deletingTriple.object}</p>
            </>
          )
        }
      />
    </div>
  );
};

export default Triples;
