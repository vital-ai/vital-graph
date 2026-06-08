import React, { useState, useEffect, useCallback } from 'react';
import { apiService } from '../services/ApiService';
import {
  Alert, Button, Select, Spinner, Textarea, ToggleSwitch
} from 'flowbite-react';
import { HiPlay, HiSearch, HiDocumentText, HiDatabase, HiX, HiPencil, HiCheck } from 'react-icons/hi';
import { type SpaceInfo } from '../types/api';
import { usePageTitle } from '../hooks/usePageTitle';

type SparqlMode = 'query' | 'update';

interface QueryResult {
  head?: { vars: string[] };
  results?: {
    bindings: Record<string, { type: string; value: string; datatype?: string }>[];
  };
  boolean?: boolean;
  triples?: unknown[];
  query_time?: number;
}

interface UpdateResult {
  success?: boolean;
  message?: string;
  update_time?: number;
}

const SAMPLE_QUERIES = [
  { name: 'List all triples', query: `SELECT ?subject ?predicate ?object\nWHERE {\n  ?subject ?predicate ?object .\n}\nLIMIT 10` },
  { name: 'Count triples', query: `SELECT (COUNT(*) as ?count)\nWHERE {\n  ?subject ?predicate ?object .\n}` },
  { name: 'Find entities with names', query: `PREFIX vital: <http://vital.ai/ontology/vital-core#>\nSELECT ?entity ?name\nWHERE {\n  ?entity vital:hasName ?name .\n}\nLIMIT 10` },
];

const SAMPLE_UPDATES = [
  { name: 'Insert triple', query: `INSERT DATA {\n  GRAPH <urn:my-graph> {\n    <http://example.org/subject1> <http://example.org/predicate1> "value1" .\n  }\n}` },
  { name: 'Delete triple', query: `DELETE DATA {\n  GRAPH <urn:my-graph> {\n    <http://example.org/subject1> <http://example.org/predicate1> "value1" .\n  }\n}` },
  { name: 'Delete/Insert (modify)', query: `DELETE {\n  GRAPH <urn:my-graph> {\n    ?s <http://example.org/oldPred> ?o .\n  }\n}\nINSERT {\n  GRAPH <urn:my-graph> {\n    ?s <http://example.org/newPred> ?o .\n  }\n}\nWHERE {\n  GRAPH <urn:my-graph> {\n    ?s <http://example.org/oldPred> ?o .\n  }\n}` },
];

const SPARQL: React.FC = () => {
  usePageTitle('SPARQL');
  const [mode, setMode] = useState<SparqlMode>('query');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<QueryResult | null>(null);
  const [updateResult, setUpdateResult] = useState<UpdateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState('');
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [pagingEnabled, setPagingEnabled] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Fetch spaces
  useEffect(() => {
    (async () => {
      try {
        setSpacesLoading(true);
        const data = await apiService.getSpaces();
        setSpaces(data);
        if (data.length > 0) setSelectedSpace(data[0].space);
      } catch { setError('Failed to load spaces.'); }
      finally { setSpacesLoading(false); }
    })();
  }, []);

  // Build paginated query
  const buildQuery = useCallback((page: number): string => {
    if (!pagingEnabled) return query;
    const offset = (page - 1) * pageSize;
    const cleaned = query.trim().replace(/\s+(LIMIT|OFFSET)\s+\d+/gi, '');
    return `${cleaned}\nLIMIT ${pageSize} OFFSET ${offset}`;
  }, [query, pagingEnabled, pageSize]);

  const executeQuery = useCallback(async (page?: number) => {
    const p = page ?? currentPage;
    if (!query.trim()) { setError('Please enter a SPARQL query'); return; }
    if (!selectedSpace) { setError('Please select a space'); return; }
    try {
      setLoading(true);
      setError(null);
      setUpdateResult(null);
      const data = await apiService.executeSparqlQuery(selectedSpace, buildQuery(p));
      setResults(data);
      setCurrentPage(p);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to execute query.');
      setResults(null);
    } finally { setLoading(false); }
  }, [query, selectedSpace, buildQuery, currentPage]);

  const executeUpdate = useCallback(async () => {
    if (!query.trim()) { setError('Please enter a SPARQL update'); return; }
    if (!selectedSpace) { setError('Please select a space'); return; }
    try {
      setLoading(true);
      setError(null);
      setResults(null);
      const data = await apiService.executeSparqlUpdate(selectedSpace, query);
      setUpdateResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to execute update.');
      setUpdateResult(null);
    } finally { setLoading(false); }
  }, [query, selectedSpace]);

  const resultCount = results?.results?.bindings?.length || results?.triples?.length || 0;

  const renderResults = () => {
    if (!results) return null;

    const queryTimeLabel = results.query_time
      ? <span className="text-xs text-gray-400">{(results.query_time * 1000).toFixed(1)}ms</span>
      : null;

    // ASK query
    if (typeof results.boolean === 'boolean') {
      return (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-semibold text-gray-900 dark:text-white">Result</h3>
            {queryTimeLabel}
          </div>
          <span className={`text-2xl font-bold ${results.boolean ? 'text-green-500' : 'text-red-500'}`}>
            {results.boolean ? 'TRUE' : 'FALSE'}
          </span>
        </div>
      );
    }

    // SELECT query
    if (results.results?.bindings) {
      const bindings = results.results.bindings;
      const vars = results.head?.vars || [];
      if (bindings.length === 0) {
        return <Alert color="info">Query returned no results.</Alert>;
      }
      return (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {bindings.length} result{bindings.length !== 1 ? 's' : ''}
            </p>
            {queryTimeLabel}
          </div>
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                <tr>
                  {vars.map(v => <th key={v} className="px-4 py-3">?{v}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {bindings.map((binding, i) => (
                  <tr key={i} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800">
                    {vars.map(v => {
                      const cell = binding[v];
                      const val = cell?.value || '';
                      const dt = cell?.datatype;
                      return (
                        <td key={v} className="px-4 py-2 font-mono text-xs max-w-[20rem] truncate" title={val}>
                          {val}
                          {dt && <span className="ml-1 text-gray-400 font-sans">({dt.split('#').pop()})</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    // Fallback: raw JSON
    return (
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <p className="text-sm font-medium text-gray-900 dark:text-white">Raw Results</p>
          {queryTimeLabel}
        </div>
        <pre className="text-xs bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4 overflow-auto max-h-96">
          {JSON.stringify(results, null, 2)}
        </pre>
      </div>
    );
  };

  const clearAll = () => {
    setQuery('');
    setResults(null);
    setUpdateResult(null);
    setError(null);
    setCurrentPage(1);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <HiSearch className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">SPARQL</h1>
          </div>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
            {mode === 'query' ? 'Execute SPARQL queries against your RDF data' : 'Execute SPARQL updates (INSERT, DELETE, LOAD, CLEAR)'}
          </p>
        </div>
        {/* Mode toggle */}
        <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <button
            onClick={() => { setMode('query'); clearAll(); }}
            className={`px-4 py-2 text-sm font-medium flex items-center gap-1.5 transition-colors ${
              mode === 'query' ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            <HiSearch className="w-4 h-4" />Query
          </button>
          <button
            onClick={() => { setMode('update'); clearAll(); }}
            className={`px-4 py-2 text-sm font-medium flex items-center gap-1.5 transition-colors border-l border-gray-200 dark:border-gray-700 ${
              mode === 'update' ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            <HiPencil className="w-4 h-4" />Update
          </button>
        </div>
      </div>

      {/* Space selector */}
      <div className="flex items-center gap-3">
        <HiDatabase className="text-gray-400 flex-shrink-0" />
        <Select
          value={selectedSpace}
          onChange={(e) => setSelectedSpace(e.target.value)}
          disabled={spacesLoading || loading}
          className="flex-1 max-w-xs"
        >
          <option value="">Choose a space...</option>
          {spaces.map((s: SpaceInfo) => (
            <option key={s.space} value={s.space}>{s.space_name}</option>
          ))}
        </Select>
        {spacesLoading && <Spinner size="sm" />}
      </div>

      {/* Sample queries/updates */}
      <div>
        <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Quick start</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {(mode === 'query' ? SAMPLE_QUERIES : SAMPLE_UPDATES).map((s, i) => (
            <button
              key={i}
              onClick={() => { setQuery(s.query); setResults(null); setUpdateResult(null); setError(null); setCurrentPage(1); }}
              className={`text-left p-3 rounded-lg border border-gray-200 dark:border-gray-700 transition-colors ${
                mode === 'query' ? 'hover:border-blue-300 dark:hover:border-blue-600 hover:bg-blue-50 dark:hover:bg-gray-800' : 'hover:border-amber-300 dark:hover:border-amber-600 hover:bg-amber-50 dark:hover:bg-gray-800'
              }`}
            >
              <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                <HiDocumentText className="text-gray-400 flex-shrink-0" />{s.name}
              </p>
              <pre className="text-xs text-gray-400 mt-1 truncate">{s.query.substring(0, 80)}</pre>
            </button>
          ))}
        </div>
      </div>

      {/* Query editor */}
      <div>
        <Textarea
          placeholder={mode === 'query' ? 'Enter your SPARQL query here...' : 'Enter your SPARQL update here (INSERT DATA, DELETE DATA, etc.)...'}
          rows={8}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="font-mono text-sm"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {mode === 'query' ? (
            <Button
              onClick={() => executeQuery(1)}
              disabled={loading || !query.trim() || !selectedSpace}
              color="blue"
            >
              {loading ? <><Spinner size="sm" className="mr-2" />Running...</> : <><HiPlay className="mr-1.5 h-4 w-4" />Execute Query</>}
            </Button>
          ) : (
            <Button
              onClick={executeUpdate}
              disabled={loading || !query.trim() || !selectedSpace}
              color="warning"
            >
              {loading ? <><Spinner size="sm" className="mr-2" />Running...</> : <><HiPencil className="mr-1.5 h-4 w-4" />Execute Update</>}
            </Button>
          )}
          <Button color="gray" disabled={loading} onClick={clearAll}>
            <HiX className="mr-1.5 h-4 w-4" />Clear
          </Button>
          {mode === 'query' && (
            <div className="ml-auto flex items-center gap-3">
              <ToggleSwitch checked={pagingEnabled} label="Paginate" onChange={(v) => { setPagingEnabled(v); setCurrentPage(1); }} />
              {pagingEnabled && (
                <Select value={pageSize.toString()} onChange={(e) => { setPageSize(parseInt(e.target.value)); setCurrentPage(1); }} sizing="sm" className="w-20">
                  <option value="10">10</option>
                  <option value="20">20</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                </Select>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Pagination nav */}
      {pagingEnabled && results && resultCount > 0 && (
        <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-800 rounded-lg px-4 py-2">
          <span className="text-sm text-gray-500 dark:text-gray-400">Page {currentPage} · {resultCount} result{resultCount !== 1 ? 's' : ''}</span>
          <div className="flex gap-2">
            <Button size="xs" color="gray" disabled={currentPage === 1 || loading} onClick={() => executeQuery(currentPage - 1)}>Previous</Button>
            <Button size="xs" color="gray" disabled={resultCount < pageSize || loading} onClick={() => executeQuery(currentPage + 1)}>Next</Button>
          </div>
        </div>
      )}

      {error && <Alert color="failure" onDismiss={() => setError(null)}>{error}</Alert>}

      {/* Update result */}
      {updateResult && (
        <Alert color="success" icon={HiCheck}>
          <div className="flex items-center justify-between">
            <div>
              <span className="font-medium">Update successful.</span>
              {updateResult.message && <span className="ml-2">{updateResult.message}</span>}
            </div>
            {updateResult.update_time != null && (
              <span className="text-xs text-green-600 dark:text-green-400">{(updateResult.update_time * 1000).toFixed(1)}ms</span>
            )}
          </div>
        </Alert>
      )}

      {renderResults()}
    </div>
  );
};

export default SPARQL;
