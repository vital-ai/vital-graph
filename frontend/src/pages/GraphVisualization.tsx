import { useState, useCallback, useRef, useEffect } from 'react';
import { TextInput, Button, Spinner, Select } from 'flowbite-react';
import { HiSearch, HiTrash, HiRefresh, HiZoomIn } from 'react-icons/hi';
import cytoscape, { Core, EventObject } from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import { useGraphVisualization, GraphNode, SearchResult } from '../hooks/useGraphVisualization';
import ApiService from '../services/ApiService';

// Register layout extension
cytoscape.use(coseBilkent);

// ---------------------------------------------------------------------------
// Space selector (uses same spaces endpoint as rest of app)
// ---------------------------------------------------------------------------

function useSpaces() {
  const [spaces, setSpaces] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    ApiService.getSpaces().then((data: unknown) => {
      const list = Array.isArray(data) ? data : [];
      const mapped = list
        .map((s: Record<string, unknown>) => ({
          id: String(s.space || ''),
          name: String(s.space_name || s.space || ''),
        }))
        .filter(s => s.id);
      setSpaces(mapped);
    }).catch(() => {});
  }, []);
  return spaces;
}

// ---------------------------------------------------------------------------
// Cytoscape styles
// ---------------------------------------------------------------------------

const cytoscapeStylesheet: cytoscape.StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': '#6366f1',
      'label': 'data(label)',
      'color': '#1f2937',
      'font-size': '11px',
      'text-wrap': 'ellipsis',
      'text-max-width': '120px',
      'text-valign': 'bottom',
      'text-margin-y': 6,
      'width': 28,
      'height': 28,
      'border-width': 2,
      'border-color': '#4f46e5',
    },
  },
  {
    selector: 'node[?expanded]',
    style: {
      'background-color': '#10b981',
      'border-color': '#059669',
    },
  },
  {
    selector: 'node:selected',
    style: {
      'background-color': '#f59e0b',
      'border-color': '#d97706',
      'border-width': 3,
    },
  },
  {
    selector: 'edge',
    style: {
      'width': 2,
      'line-color': '#9ca3af',
      'target-arrow-color': '#9ca3af',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'label': 'data(label)',
      'font-size': '9px',
      'color': '#6b7280',
      'text-rotation': 'autorotate',
      'text-margin-y': -8,
    },
  },
  {
    selector: 'edge:selected',
    style: {
      'line-color': '#f59e0b',
      'target-arrow-color': '#f59e0b',
      'width': 3,
    },
  },
];

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function GraphVisualization() {
  const spaces = useSpaces();
  const [spaceId, setSpaceId] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedSearchResult, setSelectedSearchResult] = useState<SearchResult | null>(null);
  const cyRef = useRef<Core | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Use first space as default
  useEffect(() => {
    if (spaces.length > 0 && !spaceId) {
      setSpaceId(spaces[0].id);
    }
  }, [spaces, spaceId]);

  const {
    graph,
    searching,
    expanding,
    searchResults,
    error,
    searchEntities,
    addNode,
    expandNode,
    collapseNode,
    getNodeDetail,
    clearGraph,
    removeNode,
  } = useGraphVisualization(spaceId);

  // Ref to current graph state (for event handlers that can't close over latest state)
  const graphRef = useRef(graph);
  graphRef.current = graph;

  // Initialize Cytoscape (once, on mount)
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      style: cytoscapeStylesheet,
      layout: { name: 'grid' },
      minZoom: 0.2,
      maxZoom: 5,
    });

    // Click to select node
    cy.on('tap', 'node', (evt: EventObject) => {
      const nodeId = evt.target.id();
      const nodeData = graphRef.current.nodes.get(nodeId);
      if (nodeData) {
        setSelectedNode(nodeData);
        if (!nodeData.type) {
          getNodeDetail(nodeId);
        }
      }
    });

    // Click background to deselect
    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) {
        setSelectedNode(null);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync graph state to Cytoscape
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      console.log('[GraphViz] sync: no cy instance');
      return;
    }

    // Ensure Cytoscape knows the container size
    cy.resize();

    // Collect desired element IDs
    const desiredNodeIds = new Set(graph.nodes.keys());
    const desiredEdgeIds = new Set(graph.edges.keys());

    // Remove nodes/edges no longer in state
    cy.nodes().forEach(n => {
      if (!desiredNodeIds.has(n.id())) n.remove();
    });
    cy.edges().forEach(e => {
      if (!desiredEdgeIds.has(e.id())) e.remove();
    });

    // Add/update nodes
    for (const [id, node] of graph.nodes) {
      const existing = cy.getElementById(id);
      if (existing.length === 0) {
        cy.add({
          group: 'nodes',
          data: { id, label: node.label, expanded: node.expanded || false },
        });
      } else {
        existing.data('label', node.label);
        existing.data('expanded', node.expanded || false);
      }
    }

    // Add edges
    for (const [id, edge] of graph.edges) {
      const existing = cy.getElementById(id);
      if (existing.length === 0) {
        // Only add if both source and target exist
        if (cy.getElementById(edge.source).length > 0 && cy.getElementById(edge.target).length > 0) {
          cy.add({
            group: 'edges',
            data: { id, source: edge.source, target: edge.target, label: edge.label },
          });
        }
      }
    }

    console.log('[GraphViz] sync: cy nodes=', cy.nodes().length, 'edges=', cy.edges().length);

    // Run layout if we have nodes
    if (cy.nodes().length > 0) {
      cy.layout({
        name: 'cose-bilkent',
        animate: true,
        animationDuration: 500,
        nodeDimensionsIncludeLabels: true,
        idealEdgeLength: 120,
        nodeRepulsion: 8000,
        fit: true,
        padding: 40,
      } as any).run();
    }
  }, [graph]);

  // Search handler
  const handleSearch = useCallback(() => {
    if (searchTerm.trim() && spaceId) {
      searchEntities(searchTerm);
    }
  }, [searchTerm, spaceId, searchEntities]);

  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  }, [handleSearch]);

  // Fit graph to viewport
  const fitGraph = useCallback(() => {
    cyRef.current?.fit(undefined, 40);
  }, []);

  return (
    <div className="flex flex-col h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="flex items-center gap-3 mb-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Graph Visualization</h1>
        <Select
          sizing="sm"
          value={spaceId}
          onChange={(e) => setSpaceId(e.target.value)}
          className="w-48"
        >
          {spaces.length === 0 && <option value="">Loading spaces...</option>}
          {spaces.map((s, i) => (
            <option key={`${s.id}-${i}`} value={s.id}>{s.name}</option>
          ))}
        </Select>
      </div>

      <div className="flex flex-1 gap-3 min-h-0">
        {/* Left panel - Search & Controls */}
        <div className="w-72 flex flex-col gap-3 overflow-hidden">
          {/* Search */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3">
            <div className="flex gap-2 mb-2">
              <TextInput
                sizing="sm"
                placeholder="Search entities..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={handleSearchKeyDown}
                className="flex-1"
              />
              <Button size="xs" onClick={handleSearch} disabled={searching || !spaceId}>
                {searching ? <Spinner size="xs" /> : <HiSearch />}
              </Button>
            </div>

            {/* Search results */}
            <div className="max-h-60 overflow-y-auto">
              {searchResults.map(r => (
                <button
                  key={r.uri}
                  onClick={() => setSelectedSearchResult(r)}
                  className={`w-full text-left px-2 py-1.5 text-sm rounded truncate ${
                    selectedSearchResult?.uri === r.uri
                      ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200 font-medium'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                  }`}
                  title={r.uri}
                >
                  {r.name}
                </button>
              ))}
              {searchResults.length === 0 && searchTerm && !searching && (
                <p className="text-xs text-gray-400 px-2 py-1">No results</p>
              )}
            </div>
            {selectedSearchResult && (
              <Button
                size="sm"
                className="w-full mt-2"
                onClick={() => {
                  addNode(selectedSearchResult.uri, selectedSearchResult.name);
                  expandNode(selectedSearchResult.uri);
                }}
              >
                Add to Graph
              </Button>
            )}
          </div>

          {/* Controls */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3 flex flex-wrap gap-2">
            <Button size="xs" color="light" onClick={fitGraph} title="Fit to view">
              <HiZoomIn className="mr-1" /> Fit
            </Button>
            <Button size="xs" color="light" onClick={clearGraph} title="Clear graph">
              <HiTrash className="mr-1" /> Clear
            </Button>
            {expanding && (
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Spinner size="xs" /> Expanding...
              </span>
            )}
          </div>

          {/* Selected node detail */}
          {selectedNode && (
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate mb-1" title={selectedNode.label}>
                {selectedNode.label}
              </h3>
              {selectedNode.type && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{selectedNode.type}</p>
              )}
              {selectedNode.description && (
                <p className="text-xs text-gray-600 dark:text-gray-300 mb-2 line-clamp-3">
                  {selectedNode.description}
                </p>
              )}
              <div className="flex gap-2 flex-wrap">
                {!selectedNode.expanded ? (
                  <Button size="xs" onClick={() => expandNode(selectedNode.id)}>
                    <HiRefresh className="mr-1" /> Expand
                  </Button>
                ) : (
                  <Button size="xs" color="light" onClick={() => collapseNode(selectedNode.id)}>
                    Collapse
                  </Button>
                )}
                <Button size="xs" color="failure" onClick={() => { removeNode(selectedNode.id); setSelectedNode(null); }}>
                  Remove
                </Button>
              </div>
            </div>
          )}

          {/* Error display */}
          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800 p-2">
              <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
            </div>
          )}
        </div>

        {/* Right panel - Cytoscape graph */}
        <div className="flex-1 h-full bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 relative overflow-hidden">
          <div ref={containerRef} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} />
          {graph.nodes.size === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <p className="text-gray-400 dark:text-gray-500 text-sm">
                Search for entities and click results to add them to the graph
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
