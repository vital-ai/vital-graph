import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Pagination, Select, Spinner, TextInput
} from 'flowbite-react';
import { HiPlus, HiTrash, HiSearch, HiEye } from 'react-icons/hi';
import KGTypesIcon from '../components/icons/KGTypesIcon';
import NavigationBreadcrumb from '../components/NavigationBreadcrumb';
import {
  shortenUri, parseEntitiesFromQuads, getFirstValue,
  type Quad, type GroupedEntity,
} from '../utils/QuadUtils';
import ConfirmDialog from '../components/ConfirmDialog';

interface KGType {
  uri: string;
  type_name: string;
  type_uri: string;
  description: string;
  [key: string]: unknown;
}

type TabKey = 'all' | 'frame' | 'entity' | 'slot' | 'relation' | 'role';

interface TabDef {
  key: TabKey;
  label: string;
  type_uri?: string;
}

const TABS: TabDef[] = [
  { key: 'all', label: 'All Types' },
  { key: 'frame', label: 'Frame Types', type_uri: 'http://vital.ai/ontology/haley-ai-kg#KGFrameType' },
  { key: 'entity', label: 'Entity Types', type_uri: 'http://vital.ai/ontology/haley-ai-kg#KGEntityType' },
  { key: 'slot', label: 'Slot Types', type_uri: 'http://vital.ai/ontology/haley-ai-kg#KGSlotType' },
  { key: 'relation', label: 'Relation Types', type_uri: 'http://vital.ai/ontology/haley-ai-kg#KGRelationType' },
  { key: 'role', label: 'Role Types', type_uri: 'http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType' },
];

const SP_KG_TYPES = 'sp_kg_types';

const KGTypes: React.FC = () => {
  const navigate = useNavigate();

  // Always use the centralized KG Types system space
  const selectedSpace = SP_KG_TYPES;

  const [activeTab, setActiveTab] = useState<TabKey>('all');
  const [kgTypes, setKGTypes] = useState<KGType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [searchMode, setSearchMode] = useState<'keyword' | 'fts' | 'vector' | 'hybrid'>('keyword');
  const [searchResults, setSearchResults] = useState<KGType[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchTotalCount, setSearchTotalCount] = useState(0);
  const [committedSearch, setCommittedSearch] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [totalCount, setTotalCount] = useState(0);
  const [deletingType, setDeletingType] = useState<KGType | null>(null);


  // Resolve type_uri for the active tab
  const activeTabDef = TABS.find(t => t.key === activeTab)!;

  // Fetch KG types — re-fetches when tab, space, page, or search changes
  const fetchKGTypes = useCallback(async () => {
    if (!selectedSpace) { setKGTypes([]); setTotalCount(0); return; }
    if (committedSearch.trim()) return; // Skip list fetch when search is active
    try {
      setLoading(true);
      setError(null);
      const responseData = await apiService.getKGTypes(selectedSpace, {
        page_size: itemsPerPage,
        offset: (currentPage - 1) * itemsPerPage,
        type_uri: activeTabDef.type_uri,
      });

      // Parse quads into grouped entities, then map to KGType
      const VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype';
      const HAS_DESCRIPTION = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription';

      let normalized: KGType[] = [];
      if (responseData.results && Array.isArray(responseData.results)) {
        const quads: Quad[] = responseData.results;
        const entities: GroupedEntity[] = parseEntitiesFromQuads(quads);
        normalized = entities.map((e: GroupedEntity) => ({
          uri: e.uri,
          type_name: e.name || shortenUri(e.uri),
          type_uri: getFirstValue(e.properties, VITALTYPE) || e.rdf_type || '',
          description: getFirstValue(e.properties, HAS_DESCRIPTION),
        }));
      } else if (Array.isArray(responseData)) {
        normalized = responseData.map((t: KGType) => ({
          uri: t.uri || '',
          type_name: t.type_name || shortenUri(t.uri || ''),
          type_uri: t.type_uri || '',
          description: t.description || '',
        }));
      }

      setKGTypes(normalized);
      setTotalCount(responseData.total_count ?? normalized.length);
    } catch {
      setError('Failed to load KG types.');
      setKGTypes([]);
      setTotalCount(0);
    } finally { setLoading(false); }
  }, [selectedSpace, activeTabDef.type_uri, currentPage, itemsPerPage, committedSearch]);

  useEffect(() => { fetchKGTypes(); }, [fetchKGTypes]);

  // Server-side search with pagination
  const executeSearch = useCallback(async () => {
    if (!selectedSpace || !committedSearch.trim()) {
      setSearchResults(null);
      setSearchTotalCount(0);
      return;
    }
    try {
      setSearching(true);
      const resp = await apiService.searchKGTypes(selectedSpace, committedSearch, {
        search_mode: searchMode,
        type: activeTab !== 'all' ? activeTab : undefined,
        page_size: itemsPerPage,
        offset: (currentPage - 1) * itemsPerPage,
      });
      const results = (resp.types || []).map((r: Record<string, unknown>) => ({
        uri: String(r.uri || ''),
        type_name: String(r.name || '') || shortenUri(String(r.uri || '')),
        type_uri: String(r.vitaltype || r.type_uri || ''),
        description: String(r.description || ''),
        score: r.score as number | undefined,
      }));
      setSearchResults(results);
      setSearchTotalCount(resp.total_count ?? results.length);
    } catch {
      setError('Search failed.');
      setSearchResults(null);
      setSearchTotalCount(0);
    } finally { setSearching(false); }
  }, [selectedSpace, committedSearch, searchMode, activeTab, itemsPerPage, currentPage]);

  // Auto-execute search when committedSearch or currentPage changes
  useEffect(() => { executeSearch(); }, [executeSearch]);

  const handleSearch = useCallback(() => {
    setCommittedSearch(searchTerm);
    setCurrentPage(1);
  }, [searchTerm]);

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  const handleClearSearch = () => {
    setSearchTerm('');
    setCommittedSearch('');
    setSearchResults(null);
    setSearchTotalCount(0);
    setCurrentPage(1);
  };

  const isSearchActive = searchResults !== null;
  const filtered = isSearchActive ? searchResults : kgTypes;

  const displayTotalCount = isSearchActive ? searchTotalCount : totalCount;
  const totalPages = Math.max(1, Math.ceil(displayTotalCount / itemsPerPage));
  const hasSelection = true;

  const handleTabChange = (tab: TabKey) => {
    setActiveTab(tab);
    setCurrentPage(1);
    setSearchTerm('');
    setCommittedSearch('');
    setSearchResults(null);
    setSearchTotalCount(0);
  };

  const handleDelete = async (t: KGType) => {
    try {
      await apiService.deleteKGType(selectedSpace, t.uri);
      setDeletingType(null);
      await fetchKGTypes();
    } catch {
      setError('Failed to delete KG type.');
      setDeletingType(null);
    }
  };

  return (
    <div className="space-y-6" data-testid="kgtypes-page">
      <NavigationBreadcrumb spaceId={SP_KG_TYPES} currentPageName="KG Types" currentPageIcon={KGTypesIcon} />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <KGTypesIcon className="w-6 h-6 text-indigo-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white" data-testid="kgtypes-title">KG Types</h1>
          </div>
          {hasSelection && !loading && (
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">{displayTotalCount} type{displayTotalCount !== 1 ? 's' : ''}</p>
          )}
        </div>
        {hasSelection && (
          <Button size="sm" color="blue" onClick={() => navigate(`/kg-types/new?mode=create`)}>
            <HiPlus className="mr-1.5 h-4 w-4" />Add Type
          </Button>
        )}
      </div>

      {/* System space indicator */}
      <div className="text-xs text-gray-500 dark:text-gray-400">
        Centralized type definitions stored in <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">sp_kg_types</code>
      </div>

      {/* Tabs */}
      {hasSelection && (
        <div className="border-b border-gray-200 dark:border-gray-700">
          <nav className="-mb-px flex space-x-6 overflow-x-auto" aria-label="Type tabs">
            {TABS.map(tab => (
              <button
                key={tab.key}
                onClick={() => handleTabChange(tab.key)}
                className={`whitespace-nowrap py-2 px-1 border-b-2 font-medium text-sm ${
                  activeTab === tab.key
                    ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      )}

      {/* Search + mode + page size */}
      {hasSelection && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1 flex gap-2">
            <div className="flex-1">
              <TextInput icon={HiSearch}
                placeholder={`Search types (${searchMode})...`}
                value={searchTerm}
                onKeyDown={handleSearchKeyDown}
                onChange={(e) => setSearchTerm(e.target.value)} />
            </div>
            <Button size="sm" color="blue" onClick={handleSearch} disabled={!searchTerm.trim() || searching}>
              <HiSearch className="h-4 w-4" />
            </Button>
            {isSearchActive && (
              <Button size="sm" color="light" onClick={handleClearSearch}>
                Clear
              </Button>
            )}
          </div>
          <div className="w-36 shrink-0">
            <Select value={searchMode} onChange={(e) => { setSearchMode(e.target.value as typeof searchMode); setCurrentPage(1); }}>
              <option value="keyword">Keyword</option>
              <option value="fts">Full-text</option>
              <option value="vector">Vector</option>
              <option value="hybrid">Hybrid</option>
            </Select>
          </div>
          <div className="w-32 shrink-0">
            <Select value={itemsPerPage} onChange={(e) => { setItemsPerPage(parseInt(e.target.value)); setCurrentPage(1); }}>
              <option value={10}>10 / page</option>
              <option value={25}>25 / page</option>
              <option value={50}>50 / page</option>
              <option value={100}>100 / page</option>
            </Select>
          </div>
        </div>
      )}

      {/* Search loading indicator */}
      {searching && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Spinner size="sm" />
          <span>Searching...</span>
        </div>
      )}

      {/* Search result count */}
      {searchResults && !searching && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {searchTotalCount} result{searchTotalCount !== 1 ? 's' : ''} for &quot;{committedSearch}&quot; ({searchMode})
        </p>
      )}

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}


      {hasSelection && loading && (
        <div className="flex justify-center py-12"><Spinner size="xl" /></div>
      )}

      {hasSelection && !loading && filtered.length === 0 && !error && (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <KGTypesIcon className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {searchTerm ? (
            <>
              <p className="text-lg font-medium">No results for &quot;{searchTerm}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No {activeTabDef.label.toLowerCase()} yet</p>
              <p className="text-sm mt-1">Add your first KG type to get started</p>
            </>
          )}
        </div>
      )}

      {/* Types table */}
      {hasSelection && !loading && filtered.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  {activeTab === 'all' && <th className="px-4 py-3">RDF Type</th>}
                  <th className="px-4 py-3 hidden md:table-cell">Description</th>
                  <th className="px-4 py-3 w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {filtered.map((t, i) => (
                  <tr key={t.uri || i} data-testid="type-row" className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                    <td className="px-4 py-2.5">
                      <div className="max-w-xs">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{t.type_name}</p>
                        <p className="text-xs font-mono text-gray-400 truncate" title={t.uri}>{t.uri}</p>
                      </div>
                    </td>
                    {activeTab === 'all' && (
                      <td className="px-4 py-2.5">
                        <Badge color="indigo" size="xs">{shortenUri(t.type_uri) || 'Unknown'}</Badge>
                      </td>
                    )}
                    <td className="px-4 py-2.5 hidden md:table-cell text-xs text-gray-500 dark:text-gray-400 max-w-xs truncate">
                      {t.description || '-'}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-1">
                        <button
                          onClick={() => navigate(`/kg-types/${encodeURIComponent(t.uri)}?mode=view`)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors" title="View"
                        >
                          <HiEye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setDeletingType(t)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-red-500 transition-colors" title="Delete"
                        >
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

      {/* Delete Modal */}
      <ConfirmDialog
        open={!!deletingType}
        onConfirm={() => deletingType && handleDelete(deletingType)}
        onCancel={() => setDeletingType(null)}
        title="Delete KG Type"
        confirmLabel="Delete"
        variant="danger"
        detail={
          deletingType && (
            <>
              <p className="font-medium text-gray-800 dark:text-gray-200">{deletingType.type_name}</p>
              <p className="text-gray-400">{deletingType.uri}</p>
            </>
          )
        }
      />
    </div>
  );
};

export default KGTypes;
