import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Alert, Button, Spinner, Textarea, Card, Select, Label, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow, ToggleSwitch } from 'flowbite-react';
import { HiPlay, HiDocumentText, HiDatabase } from 'react-icons/hi';

interface Space {
  id: number;
  tenant: string;
  space: string;
  space_name: string;
  space_description: string;
  update_time: string;
}

interface QueryResult {
  head?: {
    vars: string[];
  };
  results?: {
    bindings: Record<string, { type: string; value: string }>[];
  };
  boolean?: boolean;
  triples?: any[]; // For CONSTRUCT/DESCRIBE queries
  query_time?: number;
}

const SPARQL: React.FC = () => {
  const [query, setQuery] = useState<string>('');
  const [results, setResults] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>('');
  const [spacesLoading, setSpacesLoading] = useState<boolean>(true);
  const [pagingEnabled, setPagingEnabled] = useState<boolean>(false);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(20);
  const [totalResults, setTotalResults] = useState<number>(0);

  // Fetch available spaces
  useEffect(() => {
    const fetchSpaces = async () => {
      try {
        setSpacesLoading(true);
        const response = await axios.get('/api/spaces');
        const spacesData = Array.isArray(response.data) ? response.data : response.data.spaces || [];
        setSpaces(spacesData);
        // Auto-select first space if available
        if (spacesData.length > 0) {
          setSelectedSpace(spacesData[0].space);
        }
      } catch (err) {
        console.error('Error fetching spaces:', err);
        setError('Failed to load spaces. Please try again later.');
      } finally {
        setSpacesLoading(false);
      }
    };

    fetchSpaces();
  }, []);

  // Sample SPARQL queries for quick testing
  const sampleQueries = [
    {
      name: 'List all triples',
      query: `SELECT ?subject ?predicate ?object
WHERE {
  ?subject ?predicate ?object .
}
LIMIT 10`
    },
    {
      name: 'Count triples',
      query: `SELECT (COUNT(*) as ?count)
WHERE {
  ?subject ?predicate ?object .
}`
    },
    {
      name: 'Find entities with names',
      query: `PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name
WHERE {
  ?entity vital:hasName ?name .
}
LIMIT 10`
    }
  ];

  const executeQuery = async () => {
    if (!query.trim()) {
      setError('Please enter a SPARQL query');
      return;
    }

    if (!selectedSpace) {
      setError('Please select a space');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      
      const paginatedQuery = addPaginationToQuery(query, currentPage, pageSize);
      
      const response = await axios.post(`/api/graphs/sparql/${selectedSpace}/query`, {
        query: paginatedQuery
      }, {
        headers: {
          'Content-Type': 'application/json'
        }
      });

      console.log('SPARQL Response:', response.data);
      console.log('Query sent to backend:', paginatedQuery);
      console.log('Results count:', response.data.results?.bindings?.length || response.data.triples?.length || 'N/A');
      console.log('Pagination state:', { currentPage, pageSize, pagingEnabled });
      console.log('Expected offset:', pagingEnabled ? (currentPage - 1) * pageSize : 'N/A');
      
      setResults(response.data);
      
      // Update total results count for pagination
      const currentResultCount = response.data.results?.bindings?.length || response.data.triples?.length || 0;
      if (currentResultCount > 0) {
        if (pagingEnabled) {
          // For paged results, we need to track the actual count
          // This is an approximation - ideally we'd run a COUNT query
          if (currentResultCount === pageSize) {
            // Likely more results available
            setTotalResults(currentPage * pageSize + 1);
          } else {
            // This is the last page
            setTotalResults((currentPage - 1) * pageSize + currentResultCount);
          }
        } else {
          setTotalResults(currentResultCount);
        }
      }
    } catch (err: any) {
      console.error('Error executing SPARQL query:', err);
      setError(err.response?.data?.detail || 'Failed to execute SPARQL query. Please check your query syntax.');
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const loadSampleQuery = (sampleQuery: string) => {
    setQuery(sampleQuery);
    setResults(null);
    setError(null);
    setCurrentPage(1); // Reset to first page when loading new query
  };

  // Add pagination to SPARQL query
  const addPaginationToQuery = (originalQuery: string, page: number, size: number): string => {
    console.log('🔧 addPaginationToQuery called:', { pagingEnabled, page, size });
    
    if (!pagingEnabled) {
      console.log('🔧 Pagination disabled, returning original query');
      return originalQuery;
    }
    
    const offset = (page - 1) * size;
    const trimmedQuery = originalQuery.trim();
    
    // Check if query already has LIMIT/OFFSET and remove them
    const queryWithoutPaging = trimmedQuery.replace(/\s+(LIMIT|OFFSET)\s+\d+/gi, '');
    
    const paginatedQuery = `${queryWithoutPaging}\nLIMIT ${size} OFFSET ${offset}`;
    console.log('🔧 Generated paginated query:', paginatedQuery);
    
    return paginatedQuery;
  };

  // Reset pagination when paging is toggled
  const handlePagingToggle = (enabled: boolean) => {
    setPagingEnabled(enabled);
    setCurrentPage(1);
    if (results) {
      // If we have results and are enabling paging, re-run the query
      if (enabled) {
        executeQuery();
      }
    }
  };

  const renderResults = () => {
    if (!results) return null;

    // Handle ASK queries (boolean results)
    if (typeof results.boolean === 'boolean') {
      return (
        <Card>
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Query Result
            </h3>
            {results.query_time && (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                Executed in {(results.query_time * 1000).toFixed(2)}ms
              </div>
            )}
          </div>
          <div className={`text-xl font-bold ${results.boolean ? 'text-green-600' : 'text-red-600'}`}>
            {results.boolean ? 'TRUE' : 'FALSE'}
          </div>
        </Card>
      );
    }

    // Handle SELECT queries
    if (results.results?.bindings) {
      const bindings = results.results.bindings;
      const variables = results.head?.vars || [];

      if (bindings.length === 0) {
        return (
          <Alert color="info">
            Query executed successfully but returned no results.
          </Alert>
        );
      }

      return (
        <Card>
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Query Results ({bindings.length} result{bindings.length !== 1 ? 's' : ''})
            </h3>
            {results.query_time && (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                Executed in {(results.query_time * 1000).toFixed(2)}ms
              </div>
            )}
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  {variables.map((variable) => (
                    <TableHeadCell key={variable}>
                      {variable}
                    </TableHeadCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {bindings.map((binding, index) => (
                  <TableRow key={index} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    {variables.map((variable) => {
                      // Handle both SPARQL JSON format and simplified format
                      const cellValue = binding[variable];
                      const displayValue = typeof cellValue === 'string' ? cellValue : (cellValue?.value || '');
                      const valueType = typeof cellValue === 'object' ? cellValue?.type : null;
                      
                      return (
                        <TableCell key={variable} className="whitespace-nowrap">
                          <div className="max-w-xs truncate" title={displayValue}>
                            {displayValue}
                          </div>
                          {valueType && (
                            <div className="text-xs text-gray-400 mt-1">
                              {valueType}
                            </div>
                          )}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      );
    }

    // Handle other result types
    return (
      <Card>
        <div className="flex justify-between items-center mb-2">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Raw Results
          </h3>
          {results.query_time && (
            <div className="text-sm text-gray-500 dark:text-gray-400">
              Executed in {(results.query_time * 1000).toFixed(2)}ms
            </div>
          )}
        </div>
        <pre className="text-sm bg-gray-100 dark:bg-gray-700 p-4 rounded overflow-auto">
          {JSON.stringify(results, null, 2)}
        </pre>
      </Card>
    );
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="mb-2 text-2xl font-bold text-gray-900 dark:text-white">SPARQL Query Interface</h1>
        <p className="text-gray-500 dark:text-gray-400">
          Execute SPARQL queries against your VitalGraph knowledge base.
        </p>
      </div>

      {/* Space Selection */}
      <div className="mb-6">
        <Card>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <Label htmlFor="space-select" className="mb-2 block text-sm font-medium text-gray-900 dark:text-white">
                <HiDatabase className="inline mr-2" />
                Select Space
              </Label>
              <Select
                id="space-select"
                value={selectedSpace}
                onChange={(e) => setSelectedSpace(e.target.value)}
                disabled={spacesLoading || loading}
                required
              >
                <option value="">Choose a space...</option>
                {spaces.map((space) => (
                  <option key={space.id} value={space.space}>
                    {space.space_name} ({space.space})
                  </option>
                ))}
              </Select>
            </div>
            {selectedSpace && (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                <div className="font-medium">
                  {spaces.find(s => s.space === selectedSpace)?.space_name}
                </div>
                <div className="text-xs">
                  {spaces.find(s => s.space === selectedSpace)?.space_description || 'No description'}
                </div>
              </div>
            )}
          </div>
          {spacesLoading && (
            <div className="flex items-center gap-2 mt-2 text-sm text-gray-500">
              <Spinner size="sm" />
              Loading spaces...
            </div>
          )}
        </Card>
      </div>

      {/* Sample Queries */}
      <div className="mb-6">
        <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">Sample Queries</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {sampleQueries.map((sample, index) => (
            <Card key={index} className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700">
              <div onClick={() => loadSampleQuery(sample.query)}>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                  <HiDocumentText className="inline mr-2" />
                  {sample.name}
                </h3>
                <pre className="text-xs text-gray-500 dark:text-gray-400 overflow-hidden">
                  {sample.query.substring(0, 100)}...
                </pre>
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Query Editor */}
      <div className="mb-6">
        <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">SPARQL Query</h2>
        <Textarea
          id="sparql-query"
          placeholder="Enter your SPARQL query here..."
          rows={10}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="font-mono text-sm"
        />
        <div className="mt-4 flex gap-4">
          <Button
            onClick={() => {
              setCurrentPage(1); // Reset to first page on new query
              executeQuery();
            }}
            disabled={loading || !query.trim() || !selectedSpace}
            color="blue"
          >
            {loading ? (
              <>
                <Spinner size="sm" className="mr-2" />
                Executing...
              </>
            ) : (
              <>
                <HiPlay className="mr-2 h-4 w-4" />
                Execute Query
              </>
            )}
          </Button>
          <Button
            onClick={() => {
              setQuery('');
              setResults(null);
              setError(null);
              setCurrentPage(1);
              setTotalResults(0);
            }}
            color="gray"
            disabled={loading}
          >
            Clear
          </Button>
        </div>
        
        {/* Pagination Controls */}
        <div className="mt-4 flex items-center gap-4">
          <ToggleSwitch
            checked={pagingEnabled}
            label="Enable Pagination"
            onChange={handlePagingToggle}
          />
          {pagingEnabled && (
            <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
              <span>Page size:</span>
              <Select
                value={pageSize.toString()}
                onChange={(e) => {
                  setPageSize(parseInt(e.target.value));
                  setCurrentPage(1);
                }}
                sizing="sm"
                className="w-20"
              >
                <option value="10">10</option>
                <option value="20">20</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </Select>
            </div>
          )}
        </div>
      </div>

      {/* Pagination Display */}
      {pagingEnabled && results && (results.results?.bindings || results.triples) && (
        <div className="mb-4">
          <Card>
            <div className="flex justify-between items-center">
              <div className="text-sm text-gray-500 dark:text-gray-400">
                Page {currentPage} • Showing {results.results?.bindings?.length || results.triples?.length || 0} results
                {totalResults > pageSize && ` • Estimated ${totalResults}+ total`}
              </div>
              <div className="flex items-center gap-4">
                <Button
                  size="sm"
                  color="gray"
                  disabled={currentPage === 1 || loading}
                  onClick={() => {
                    setCurrentPage(currentPage - 1);
                    executeQuery();
                  }}
                >
                  Previous
                </Button>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  Page {currentPage}
                </span>
                <Button
                  size="sm"
                  color="gray"
                  disabled={(results.results?.bindings?.length || results.triples?.length || 0) < pageSize || loading}
                  onClick={() => {
                    setCurrentPage(currentPage + 1);
                    executeQuery();
                  }}
                >
                  Next
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}
      
      {/* Error Display */}
      {error && (
        <Alert color="failure" className="mb-6">
          <span className="font-medium">Error:</span> {error}
        </Alert>
      )}

      {/* Results Display */}
      {renderResults()}
    </div>
  );
};

export default SPARQL;
