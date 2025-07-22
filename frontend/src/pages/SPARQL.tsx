import React, { useState } from 'react';
import axios from 'axios';
import { Alert, Button, Spinner, Textarea, Card } from 'flowbite-react';
import { HiPlay, HiDocumentText } from 'react-icons/hi';

interface QueryResult {
  head?: {
    vars: string[];
  };
  results?: {
    bindings: Record<string, { type: string; value: string }>[];
  };
  boolean?: boolean;
}

const SPARQL: React.FC = () => {
  const [query, setQuery] = useState<string>('');
  const [results, setResults] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

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

    try {
      setLoading(true);
      setError(null);
      
      const response = await axios.post('/api/graphs/sparql', {
        query: query.trim()
      }, {
        headers: {
          'Content-Type': 'application/json'
        }
      });

      setResults(response.data);
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
  };

  const renderResults = () => {
    if (!results) return null;

    // Handle ASK queries (boolean results)
    if (typeof results.boolean === 'boolean') {
      return (
        <Card>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            Query Result
          </h3>
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
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Query Results ({bindings.length} result{bindings.length !== 1 ? 's' : ''})
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-500 dark:text-gray-400">
              <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                <tr>
                  {variables.map((variable) => (
                    <th key={variable} className="px-6 py-3">
                      {variable}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bindings.map((binding, index) => (
                  <tr key={index} className="bg-white border-b dark:bg-gray-800 dark:border-gray-700">
                    {variables.map((variable) => (
                      <td key={variable} className="px-6 py-4">
                        <div className="max-w-xs truncate" title={binding[variable]?.value || ''}>
                          {binding[variable]?.value || ''}
                        </div>
                        {binding[variable]?.type && (
                          <div className="text-xs text-gray-400 mt-1">
                            {binding[variable].type}
                          </div>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      );
    }

    // Handle other result types
    return (
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
          Raw Results
        </h3>
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
            onClick={executeQuery}
            disabled={loading || !query.trim()}
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
            }}
            color="gray"
            disabled={loading}
          >
            Clear
          </Button>
        </div>
      </div>

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
