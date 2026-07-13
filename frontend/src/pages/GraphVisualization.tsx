import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Spinner } from 'flowbite-react';
import { HiSearch, HiTrash, HiRefresh, HiZoomIn, HiDownload, HiX, HiChevronRight, HiChevronDown, HiPlus, HiExternalLink, HiLockClosed, HiLockOpen } from 'react-icons/hi';
import cytoscape, { Core, EventObject } from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import fcose from 'cytoscape-fcose';
import dagre from 'cytoscape-dagre';
import cola from 'cytoscape-cola';
import elk from 'cytoscape-elk';
import contextMenus from 'cytoscape-context-menus';
import 'cytoscape-context-menus/cytoscape-context-menus.css';
import { useGraphVisualization } from '../hooks/useGraphVisualization';
import { useGraphSessionStore, consumePendingExpand, consumePendingSelect } from '../hooks/useGraphSessionStore';
import type { CyNode, CyEdge, LayoutAlgorithm } from '../hooks/graphTypes';
import { DEFAULT_LAYOUT_CONFIG, LAYOUT_OPTIONS } from '../hooks/graphTypes';
import { buildLayoutOptions } from '../hooks/layoutOptions';
import ApiService from '../services/ApiService';
import TimelineAxis from '../components/TimelineAxis';

// Register extensions
cytoscape.use(coseBilkent);
cytoscape.use(fcose);
cytoscape.use(dagre);
cytoscape.use(cola);
cytoscape.use(elk);
cytoscape.use(contextMenus);

// ---------------------------------------------------------------------------
// Space selector (uses same spaces endpoint as rest of app)
// ---------------------------------------------------------------------------

const SYSTEM_SPACES = new Set(['sp_kg_types']);

function useSpaces() {
  const [spaces, setSpaces] = useState<{ id: string; name: string; isSystem: boolean }[]>([]);
  useEffect(() => {
    ApiService.getSpaces().then((data: unknown) => {
      const list = Array.isArray(data) ? data : [];
      const mapped = list
        .map((s: Record<string, unknown>) => ({
          id: String(s.space || ''),
          name: String(s.space_name || s.space || ''),
          isSystem: SYSTEM_SPACES.has(String(s.space || '')),
        }))
        .filter(s => s.id);
      // Pin system spaces to the top
      mapped.sort((a, b) => {
        if (a.isSystem && !b.isSystem) return -1;
        if (!a.isSystem && b.isSystem) return 1;
        return 0;
      });
      setSpaces(mapped);
    }).catch(() => {});
  }, []);
  return spaces;
}

// ---------------------------------------------------------------------------
// Type display helpers
// ---------------------------------------------------------------------------

function shortenType(type: string): string {
  if (!type) return 'Unknown';
  const hashIdx = type.lastIndexOf('#');
  if (hashIdx >= 0) return type.slice(hashIdx + 1);
  const slashIdx = type.lastIndexOf('/');
  if (slashIdx >= 0) return type.slice(slashIdx + 1);
  return type;
}

const TYPE_COLORS: Record<string, string> = {
  'KGFrameType': '#f97316',    // orange
  'KGEntityType': '#06b6d4',   // cyan
  'KGSlotType': '#a855f7',     // purple
  'KGRelationType': '#ec4899', // pink
  'KGEntity': '#6366f1',       // indigo
  'KGFrame': '#10b981',        // emerald
  'document': '#64748b',       // slate
  'frame_hub': '#eab308',      // yellow
  'kgtype': '#8b5cf6',         // violet (fallback for generic kgtype)
  'entity': '#6366f1',         // indigo (fallback)
};

function getTypeColor(type: string): string {
  const short = shortenType(type);
  return TYPE_COLORS[short] || TYPE_COLORS[type] || '#6b7280';
}

// ---------------------------------------------------------------------------
// Toolbar icon button
// ---------------------------------------------------------------------------

function ToolbarButton({ onClick, title, disabled, active, children }: {
  onClick: () => void; title: string; disabled?: boolean; active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={`p-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        active
          ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
          : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-200'
      }`}
    >
      {children}
    </button>
  );
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
    selector: 'node.kgtype',
    style: {
      'background-color': '#8b5cf6',
      'border-color': '#7c3aed',
      'shape': 'diamond',
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
  // --- Event timeline styling ---
  {
    selector: 'node.entity[entityType]',
    style: {
      // Reference (non-event) entities: smaller, teal
      'width': 22,
      'height': 22,
      'background-color': '#14b8a6',
      'border-color': '#0d9488',
    },
  },
  {
    selector: 'node[entityType *= "Event"]',
    style: {
      // Event nodes: larger, blue, pill shape (overrides above)
      'background-color': '#3b82f6',
      'border-color': '#1d4ed8',
      'shape': 'round-rectangle',
      'width': 36,
      'height': 36,
    },
  },
  {
    selector: 'edge[label = "Follows Event"]',
    style: {
      'width': 3,
      'line-color': '#374151',
      'target-arrow-color': '#374151',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
    },
  },
  {
    selector: 'edge.relation[label != "Follows Event"]',
    style: {
      'width': 1.5,
      'line-color': '#d1d5db',
      'target-arrow-color': '#d1d5db',
      'line-style': 'dashed',
    },
  },
  // --- End timeline styling ---
  {
    selector: 'node[id ^= "__timeline_lane_"]',
    style: {
      'background-opacity': 0,
      'border-width': 0,
      'label': '',
      'opacity': 0,
    },
  },
  {
    selector: '.dimmed',
    style: {
      'opacity': 0.15,
    },
  },
  {
    selector: 'node:locked',
    style: {
      'border-style': 'double',
      'border-width': 4,
    },
  },
  {
    selector: '.highlighted',
    style: {
      'border-width': 3,
      'border-color': '#eab308',
      'background-color': '#fbbf24',
    },
  },
  {
    selector: 'edge.highlighted',
    style: {
      'line-color': '#eab308',
      'target-arrow-color': '#eab308',
      'width': 3,
      'opacity': 1,
    },
  },
];

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function GraphVisualization() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const spaces = useSpaces();
  const [graphUri, setGraphUri] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchMode, setSearchMode] = useState<'database' | 'local'>('database');
  const [localSearchTerm, setLocalSearchTerm] = useState('');
  const [selectedNode, setSelectedNode] = useState<CyNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<CyEdge | null>(null);
  const [multiSelection, setMultiSelection] = useState<{ nodes: number; edges: number; types: string[]; typeCounts: Map<string, number> } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [layoutConfig, setLayoutConfig] = useState(DEFAULT_LAYOUT_CONFIG);
  const layoutConfigRef = useRef(layoutConfig);
  layoutConfigRef.current = layoutConfig;
  const cyRef = useRef<Core | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const selectedNodeIdRef = useRef<string | null>(null);
  const selectedEdgeIdRef = useRef<string | null>(null);

  // Only URL param used: ?session=<id> to activate a specific session
  const targetSessionParam = searchParams.get('session');

  // ── Session management ──────────────────────────────────────────────────
  const {
    sessions,
    activeSessionId,
    sessionList,
    createSession,
    deleteSession,
    renameSession,
    switchSession,
    updateActiveDataGraph,
    updateActiveSelection,
    updateSessionSpace,
    activeSession,
  } = useGraphSessionStore(targetSessionParam);

  // spaceId is derived from the active session (session owns the space)
  const spaceId = activeSession?.spaceId || '';

  // Auto-create a default session if none exists
  useEffect(() => {
    if (sessionList.length === 0 && spaces.length > 0) {
      createSession('Session 1', spaces[0].id);
    }
  }, [sessionList.length, spaces, createSession]);

  // Handle ?session= URL param — switch to the specified session
  const sessionSwitchedRef = useRef(false);
  useEffect(() => {
    if (targetSessionParam && !sessionSwitchedRef.current && sessions.has(targetSessionParam)) {
      sessionSwitchedRef.current = true;
      switchSession(targetSessionParam);
    }
  }, [targetSessionParam, sessions, switchSession]);

  // When user changes the space dropdown, update the session
  const handleSpaceChange = useCallback((newSpaceId: string) => {
    if (activeSessionId && newSpaceId !== spaceId) {
      updateSessionSpace(activeSessionId, newSpaceId);
    }
  }, [activeSessionId, spaceId, updateSessionSpace]);

  // Fetch first graph URI for current space (needed for entity detail links)
  useEffect(() => {
    if (!spaceId) { setGraphUri(''); return; }
    ApiService.getGraphs(spaceId).then((graphs: { graph_uri?: string }[]) => {
      setGraphUri(graphs.length > 0 ? (graphs[0].graph_uri || '') : '');
    }).catch(() => setGraphUri(''));
  }, [spaceId]);

  const {
    viewGraph,
    dataGraph,
    eventTimestamps,
    searching,
    expanding,
    loading,
    canLoadFullSpace,
    searchResults,
    error,
    searchEntities,
    loadFullSpace,
    addNode,
    expandNode,
    collapseNode,
    getNodeDetail,
    clearGraph,
    restoreDataGraph,
    removeNode,
  } = useGraphVisualization(spaceId);

  // Restore session's DataGraph on mount (handles navigation away & back, and page reload)
  const sessionRestoredRef = useRef(false);
  useEffect(() => {
    if (sessionRestoredRef.current) return;
    if (!activeSession) return;
    if (activeSession.dataGraph.entities.size > 0 && dataGraph.entities.size === 0) {
      sessionRestoredRef.current = true;
      restoreDataGraph(activeSession.dataGraph);
    }
  }, [activeSession, dataGraph.entities.size, restoreDataGraph]);

  // Process pending expansions written by VisualizeInGraphButton
  const pendingProcessedRef = useRef(false);
  const pendingFocusRef = useRef<string | null>(null);
  const pendingSelectRef = useRef<string | null>(null);
  useEffect(() => {
    if (pendingProcessedRef.current) return;
    if (!activeSessionId || !spaceId) return;
    const pending = consumePendingExpand(activeSessionId);
    const selectUri = consumePendingSelect(activeSessionId);
    if (pending.length === 0 && !selectUri) return;
    pendingProcessedRef.current = true;
    pendingFocusRef.current = pending[0] || selectUri;
    if (selectUri) pendingSelectRef.current = selectUri;
    for (const uri of pending) {
      if (!activeSession?.dataGraph.fetchedExpansions.has(uri)) {
        addNode(uri, '');
        expandNode(uri);
      }
    }
  }, [activeSessionId, spaceId, activeSession, addNode, expandNode]);

  // Persist selection changes to the session store
  useEffect(() => {
    if (isSwitchingRef.current) return;
    const cy = cyRef.current;
    if (!cy) return;
    const selected = cy.$(':selected');
    const uris = selected.map(ele => ele.id());
    updateActiveSelection(uris);
  }, [selectedNode, selectedEdge, multiSelection, updateActiveSelection]);

  // Restore selection from session on switch (applies after viewGraph sync)
  const selectionRestoredRef = useRef(false);
  useEffect(() => {
    if (selectionRestoredRef.current) return;
    if (!activeSession) return;
    const uris = activeSession.selectedUris;
    if (!uris || uris.length === 0) return;
    // Wait for viewGraph to have at least one of the selected elements
    const hasAny = uris.some(u => viewGraph.cyNodes.has(u) || viewGraph.cyEdges.has(u));
    if (!hasAny) return;
    selectionRestoredRef.current = true;
    // Select in cytoscape
    const cy = cyRef.current;
    if (cy) {
      cy.$(':selected').unselect();
      for (const uri of uris) {
        const ele = cy.getElementById(uri);
        if (ele.length > 0) ele.select();
      }
    }
    // Update React state for the inspector panel
    if (uris.length === 1) {
      const node = viewGraph.cyNodes.get(uris[0]);
      if (node) { setSelectedNode(node); selectedNodeIdRef.current = uris[0]; setSelectedEdge(null); selectedEdgeIdRef.current = null; setMultiSelection(null); }
      else {
        const edge = viewGraph.cyEdges.get(uris[0]);
        if (edge) { setSelectedEdge(edge); selectedEdgeIdRef.current = uris[0]; setSelectedNode(null); selectedNodeIdRef.current = null; setMultiSelection(null); }
      }
    } else {
      // Multi-selection
      const nodes = uris.filter(u => viewGraph.cyNodes.has(u));
      const edges = uris.filter(u => viewGraph.cyEdges.has(u));
      const typeCounts = new Map<string, number>();
      for (const u of nodes) {
        const n = viewGraph.cyNodes.get(u);
        if (n) {
          const t = n.data.entityType || n.nodeType;
          typeCounts.set(t, (typeCounts.get(t) || 0) + 1);
        }
      }
      setMultiSelection({ nodes: nodes.length, edges: edges.length, types: Array.from(typeCounts.keys()), typeCounts });
      setSelectedNode(null); selectedNodeIdRef.current = null;
      setSelectedEdge(null); selectedEdgeIdRef.current = null;
    }
  }, [activeSession, viewGraph]);

  // Sync DataGraph changes to the active session store (only after data has been loaded)
  const isSwitchingRef = useRef(false);
  const hasHadDataRef = useRef(false);
  useEffect(() => {
    if (dataGraph.entities.size > 0 || dataGraph.documents.size > 0) {
      hasHadDataRef.current = true;
    }
    if (isSwitchingRef.current) return;
    if (activeSessionId && hasHadDataRef.current) {
      updateActiveDataGraph(() => dataGraph);
    }
  }, [dataGraph, activeSessionId, updateActiveDataGraph]);

  // Session switching: save current graph, restore target session's graph
  const handleSwitchSession = useCallback((targetSessionId: string) => {
    if (targetSessionId === activeSessionId) return;
    const targetSession = sessions.get(targetSessionId);
    isSwitchingRef.current = true;
    switchSession(targetSessionId);
    if (targetSession && targetSession.dataGraph.entities.size > 0) {
      hasHadDataRef.current = true;
      restoreDataGraph(targetSession.dataGraph);
    } else {
      restoreDataGraph({ entities: new Map(), frames: new Map(), slots: new Map(), documents: new Map(), edges: new Map(), fetchedExpansions: new Set() });
    }
    // Allow sync again on next tick (after the restore has settled)
    setTimeout(() => { isSwitchingRef.current = false; }, 0);
  }, [activeSessionId, sessions, switchSession, restoreDataGraph]);

  const handleNewSession = useCallback(() => {
    if (!spaceId) return;
    // Find max session number to avoid duplicate names
    const maxNum = sessionList.reduce((max, s) => {
      const m = s.name.match(/^Session (\d+)$/);
      return m ? Math.max(max, parseInt(m[1], 10)) : max;
    }, 0);
    isSwitchingRef.current = true;
    createSession(`Session ${maxNum + 1}`, spaceId);
    restoreDataGraph({ entities: new Map(), frames: new Map(), slots: new Map(), documents: new Map(), edges: new Map(), fetchedExpansions: new Set() });
    setTimeout(() => { isSwitchingRef.current = false; }, 0);
  }, [spaceId, sessionList, createSession, restoreDataGraph]);

  const handleCloseSession = useCallback((sessionId: string) => {
    isSwitchingRef.current = true;
    // Determine which session to switch to BEFORE deleting
    const remaining = sessionList.filter(s => s.id !== sessionId);
    const targetId = remaining.length > 0 ? remaining[0].id : null;

    deleteSession(sessionId);

    if (sessionId === activeSessionId && targetId) {
      // Explicitly switch and restore the target session's graph
      switchSession(targetId);
      const target = sessions.get(targetId);
      if (target && target.dataGraph.entities.size > 0) {
        hasHadDataRef.current = true;
        restoreDataGraph(target.dataGraph);
      } else {
        restoreDataGraph({ entities: new Map(), frames: new Map(), slots: new Map(), documents: new Map(), edges: new Map(), fetchedExpansions: new Set() });
      }
    } else if (sessionId === activeSessionId) {
      // Last session deleted — create a replacement
      restoreDataGraph({ entities: new Map(), frames: new Map(), slots: new Map(), documents: new Map(), edges: new Map(), fetchedExpansions: new Set() });
      if (spaceId) {
        createSession('Session 1', spaceId);
      }
    }
    setTimeout(() => { isSwitchingRef.current = false; }, 0);
  }, [deleteSession, activeSessionId, sessionList, sessions, switchSession, restoreDataGraph, spaceId, createSession]);

  // ── Legend data: entity types present in the graph ──
  const legendItems = useMemo(() => {
    const typeSet = new Map<string, number>();
    for (const node of viewGraph.cyNodes.values()) {
      const t = node.data.entityType || node.nodeType;
      typeSet.set(t, (typeSet.get(t) || 0) + 1);
    }
    return [...typeSet.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => ({ type, count }));
  }, [viewGraph]);

  // ── Graph statistics ──
  const graphStats = useMemo(() => {
    const nodeCount = viewGraph.cyNodes.size;
    const edgeCount = viewGraph.cyEdges.size;
    if (nodeCount === 0) return { nodeCount: 0, edgeCount: 0, avgDegree: 0, maxDegree: 0, maxDegreeNode: '', components: 0, typeBreakdown: [] as { type: string; count: number }[] };

    // Degree map
    const degree = new Map<string, number>();
    for (const id of viewGraph.cyNodes.keys()) degree.set(id, 0);
    for (const edge of viewGraph.cyEdges.values()) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }
    let maxDeg = 0;
    let maxDegNode = '';
    let totalDeg = 0;
    for (const [id, d] of degree) {
      totalDeg += d;
      if (d > maxDeg) { maxDeg = d; maxDegNode = id; }
    }

    // Connected components (BFS)
    const visited = new Set<string>();
    let components = 0;
    const adj = new Map<string, string[]>();
    for (const id of viewGraph.cyNodes.keys()) adj.set(id, []);
    for (const edge of viewGraph.cyEdges.values()) {
      adj.get(edge.source)?.push(edge.target);
      adj.get(edge.target)?.push(edge.source);
    }
    for (const id of viewGraph.cyNodes.keys()) {
      if (visited.has(id)) continue;
      components++;
      const queue = [id];
      visited.add(id);
      while (queue.length > 0) {
        const cur = queue.shift()!;
        for (const nb of adj.get(cur) || []) {
          if (!visited.has(nb)) { visited.add(nb); queue.push(nb); }
        }
      }
    }

    // Type breakdown (top 8)
    const typeMap = new Map<string, number>();
    for (const node of viewGraph.cyNodes.values()) {
      const t = node.data.entityType || node.nodeType || 'Unknown';
      typeMap.set(t, (typeMap.get(t) || 0) + 1);
    }
    const typeBreakdown = [...typeMap.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([type, count]) => ({ type, count }));

    return {
      nodeCount,
      edgeCount,
      avgDegree: nodeCount > 0 ? Math.round((totalDeg / nodeCount) * 10) / 10 : 0,
      maxDegree: maxDeg,
      maxDegreeNode: viewGraph.cyNodes.get(maxDegNode)?.label || maxDegNode,
      components,
      typeBreakdown,
    };
  }, [viewGraph]);

  // ── Export handlers ──
  const handleExportPng = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const png = cy.png({ full: true, scale: 2, bg: '#ffffff' });
    const link = document.createElement('a');
    link.href = png;
    link.download = `graph-export-${Date.now()}.png`;
    link.click();
  }, []);

  const handleExportJson = useCallback(() => {
    const obj = {
      entities: Object.fromEntries(dataGraph.entities),
      frames: Object.fromEntries(dataGraph.frames),
      edges: Object.fromEntries(dataGraph.edges),
      slots: Object.fromEntries(dataGraph.slots),
    };
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `graph-data-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  }, [dataGraph]);

  const handleExportSvg = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    // cytoscape-svg or built-in svg() — cast to any for type safety
    const svg = (cy as unknown as { svg: (opts: Record<string, unknown>) => string }).svg({ full: true, scale: 1, bg: '#ffffff' });
    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `graph-export-${Date.now()}.svg`;
    link.click();
    URL.revokeObjectURL(link.href);
  }, []);

  const handleExportCsv = useCallback(() => {
    const lines: string[] = [];
    // Nodes CSV
    lines.push('# Nodes');
    lines.push('uri,label,type,expanded');
    for (const [id, node] of viewGraph.cyNodes) {
      lines.push(`"${id}","${(node.label || '').replace(/"/g, '""')}","${node.nodeType || ''}","${node.data.expanded || false}"`);
    }
    lines.push('');
    // Edges CSV
    lines.push('# Edges');
    lines.push('source,target,label,type,frame_uri');
    for (const [, edge] of viewGraph.cyEdges) {
      lines.push(`"${edge.source}","${edge.target}","${(edge.label || '').replace(/"/g, '""')}","${edge.data.edgeType || ''}","${edge.data.frameUri || ''}"`);
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `graph-data-${Date.now()}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }, [viewGraph]);

  const viewGraphRef = useRef(viewGraph);
  viewGraphRef.current = viewGraph;

  const expandNodeRef = useRef(expandNode);
  expandNodeRef.current = expandNode;

  const getNodeDetailRef = useRef(getNodeDetail);
  getNodeDetailRef.current = getNodeDetail;

  // Open/close drawer based on selection state
  useEffect(() => {
    if (selectedNode || selectedEdge || multiSelection) setDrawerOpen(true);
    else setDrawerOpen(false);
  }, [selectedNode, selectedEdge, multiSelection]);

  // Initialize Cytoscape (once, on mount)
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      style: cytoscapeStylesheet,
      layout: { name: 'grid' },
      minZoom: 0.05,
      maxZoom: 5,
      boxSelectionEnabled: true,
      selectionType: 'additive',
    });

    // Log all Cytoscape selection events to trace exact event ordering
    cy.on('select', 'node, edge', (evt: EventObject) => {
      console.log(`[CY EVENT] select — id=${evt.target.id()} group=${evt.target.group()} | ref: node=${selectedNodeIdRef.current} edge=${selectedEdgeIdRef.current}`);
    });
    cy.on('unselect', 'node, edge', (evt: EventObject) => {
      console.log(`[CY EVENT] unselect — id=${evt.target.id()} group=${evt.target.group()} | ref: node=${selectedNodeIdRef.current} edge=${selectedEdgeIdRef.current}`);
    });
    cy.on('tapstart', 'node, edge', (evt: EventObject) => {
      console.log(`[CY EVENT] tapstart — id=${evt.target.id()} selected=${evt.target.selected()} | ref: node=${selectedNodeIdRef.current} edge=${selectedEdgeIdRef.current}`);
    });
    cy.on('tapend', 'node, edge', (evt: EventObject) => {
      console.log(`[CY EVENT] tapend — id=${evt.target.id()} selected=${evt.target.selected()} | ref: node=${selectedNodeIdRef.current} edge=${selectedEdgeIdRef.current}`);
    });

    // Selection is applied in setTimeout(0) to run AFTER Cytoscape's internal
    // post-tap selection processing, which would otherwise override our changes.
    cy.on('tap', 'node', (evt: EventObject) => {
      const orig = evt.originalEvent as MouseEvent;
      if (orig.shiftKey || orig.ctrlKey || orig.metaKey) return; // let Cytoscape handle multi-select
      const nodeId = evt.target.id();
      const toggleOff = selectedNodeIdRef.current === nodeId;
      console.log(`[TAP NODE] id=${nodeId} toggleOff=${toggleOff} ref=${selectedNodeIdRef.current}`);
      // Apply after Cytoscape's internal selection finishes
      setTimeout(() => {
        cy.$(':selected').unselect();
        if (toggleOff) {
          console.log(`[TAP NODE setTimeout] TOGGLE OFF`);
          setSelectedNode(null); selectedNodeIdRef.current = null;
          setSelectedEdge(null); selectedEdgeIdRef.current = null;
          setMultiSelection(null);
        } else {
          evt.target.select();
          const node = viewGraphRef.current.cyNodes.get(nodeId);
          if (node) {
            console.log(`[TAP NODE setTimeout] SELECT ref=${nodeId}`);
            const pinned = evt.target.locked();
            setSelectedNode({ ...node, data: { ...node.data, pinned } }); selectedNodeIdRef.current = nodeId;
            setSelectedEdge(null); selectedEdgeIdRef.current = null;
            setMultiSelection(null);
            if (!node.data.entityType) {
              getNodeDetailRef.current(nodeId).then(detail => {
                if (detail) {
                  // Update cy node label if name was enriched
                  if (detail.name) {
                    evt.target.data('label', detail.name);
                  }
                  // Update selected node panel
                  setSelectedNode(prev => {
                    if (prev && prev.id === nodeId) {
                      return { ...prev, label: detail.name || prev.label, data: { ...prev.data, entityType: detail.typeDescription || prev.data.entityType } };
                    }
                    return prev;
                  });
                }
              });
            }
          }
        }
      }, 0);
    });

    cy.on('tap', 'edge', (evt: EventObject) => {
      const orig = evt.originalEvent as MouseEvent;
      if (orig.shiftKey || orig.ctrlKey || orig.metaKey) return;
      const edgeId = evt.target.id();
      const toggleOff = selectedEdgeIdRef.current === edgeId;
      console.log(`[TAP EDGE] id=${edgeId} toggleOff=${toggleOff}`);
      setTimeout(() => {
        cy.$(':selected').unselect();
        if (toggleOff) {
          console.log(`[TAP EDGE setTimeout] TOGGLE OFF`);
          setSelectedNode(null); selectedNodeIdRef.current = null;
          setSelectedEdge(null); selectedEdgeIdRef.current = null;
          setMultiSelection(null);
        } else {
          const edge = viewGraphRef.current.cyEdges.get(edgeId);
          if (edge) {
            console.log(`[TAP EDGE setTimeout] SELECT ref=${edgeId}`);
            evt.target.select();
            setSelectedEdge(edge); selectedEdgeIdRef.current = edgeId;
            setSelectedNode(null); selectedNodeIdRef.current = null;
            setMultiSelection(null);
          }
        }
      }, 0);
    });

    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) {
        console.log(`[TAP BG]`);
        setTimeout(() => {
          cy.$(':selected').unselect();
          setSelectedNode(null); selectedNodeIdRef.current = null;
          setSelectedEdge(null); selectedEdgeIdRef.current = null;
          setMultiSelection(null);
        }, 0);
      }
    });

    // Multi-selection handler — only manages multiSelection state.
    // Tap handlers are the sole authority for selectedNode/selectedEdge.
    const updateMultiSelection = () => {
      const selected = cy.$(':selected');
      console.log(`[UPDATE_MULTI] selected.length=${selected.length} | ref: node=${selectedNodeIdRef.current} edge=${selectedEdgeIdRef.current}`);
      if (selected.length > 1) {
        const nodes = selected.nodes();
        const edges = selected.edges();
        const typeCounts = new Map<string, number>();
        nodes.forEach((n) => {
          const t = n.data('entityType') || n.data('nodeType') || 'Unknown';
          typeCounts.set(t, (typeCounts.get(t) || 0) + 1);
        });
        setMultiSelection({
          nodes: nodes.length,
          edges: edges.length,
          types: Array.from(typeCounts.keys()),
          typeCounts,
        });
        // Entering multi-select: clear single-element selection
        console.log(`[UPDATE_MULTI] multi-select mode — clearing single selection`);
        setSelectedNode(null); selectedNodeIdRef.current = null;
        setSelectedEdge(null); selectedEdgeIdRef.current = null;
      } else {
        setMultiSelection(null);
      }
    };
    cy.on('select unselect', updateMultiSelection);

    // Traditional right-click context menus
    const ctxMenu = cy.contextMenus({
      evtType: 'cxttap',
      menuItems: [
        {
          id: 'expand-node',
          content: 'Expand',
          tooltipText: 'Expand this node',
          selector: 'node',
          onClickFunction: (event) => {
            expandNodeRef.current(event.target.id());
          },
        },
        {
          id: 'remove-node',
          content: 'Remove',
          tooltipText: 'Remove this node',
          selector: 'node',
          onClickFunction: (event) => {
            removeNode(event.target.id());
            setSelectedNode(null); selectedNodeIdRef.current = null;
            setSelectedEdge(null); selectedEdgeIdRef.current = null;
            setMultiSelection(null);
          },
        },
        {
          id: 'pin-node',
          content: 'Pin',
          tooltipText: 'Lock node position',
          selector: 'node',
          onClickFunction: (event) => {
            const ele = event.target;
            ele.lock();
            setSelectedNode(prev => {
              if (prev && prev.id === ele.id()) {
                return { ...prev, data: { ...prev.data, pinned: true } };
              }
              return prev;
            });
          },
        },
        {
          id: 'unpin-node',
          content: 'Unpin',
          tooltipText: 'Unlock node position',
          selector: 'node',
          show: false,
          onClickFunction: (event) => {
            const ele = event.target;
            ele.unlock();
            setSelectedNode(prev => {
              if (prev && prev.id === ele.id()) {
                return { ...prev, data: { ...prev.data, pinned: false } };
              }
              return prev;
            });
          },
        },
        {
          id: 'inspect-edge',
          content: 'Inspect',
          tooltipText: 'View edge details',
          selector: 'edge',
          onClickFunction: (event) => {
            const edgeId = event.target.id();
            const edge = viewGraphRef.current.cyEdges.get(edgeId);
            if (edge) {
              setSelectedEdge(edge); selectedEdgeIdRef.current = edgeId;
              setSelectedNode(null); selectedNodeIdRef.current = null;
              setMultiSelection(null);
            }
          },
        },
      ],
    });

    // Dynamically show/hide Pin vs Unpin before context menu opens
    cy.on('cxttapstart', 'node', (evt) => {
      try {
        const isPinned = evt.target.locked();
        if (isPinned) {
          ctxMenu.hideMenuItem('pin-node');
          ctxMenu.showMenuItem('unpin-node');
        } else {
          ctxMenu.showMenuItem('pin-node');
          ctxMenu.hideMenuItem('unpin-node');
        }
      } catch {
        // Context menu items not yet registered — ignore
      }
    });

    cyRef.current = cy;

    // Keep Cytoscape in sync with container size changes
    const ro = new ResizeObserver(() => {
      cy.resize();
      if (cy.nodes().length > 0) cy.fit(undefined, 20);
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.resize();

    let structureChanged = false;

    const desiredNodeIds = new Set(viewGraph.cyNodes.keys());
    const desiredEdgeIds = new Set(viewGraph.cyEdges.keys());

    cy.nodes().forEach(n => {
      if (!desiredNodeIds.has(n.id())) { n.remove(); structureChanged = true; }
    });
    cy.edges().forEach(e => {
      if (!desiredEdgeIds.has(e.id())) { e.remove(); structureChanged = true; }
    });

    for (const [id, node] of viewGraph.cyNodes) {
      const existing = cy.getElementById(id);
      if (existing.length === 0) {
        cy.add({
          group: 'nodes',
          data: { id, label: node.label, expanded: node.data.expanded || false, nodeType: node.nodeType, entityType: node.data.entityType },
          classes: node.classes.join(' '),
        });
        structureChanged = true;
      } else {
        existing.data('label', node.label);
        existing.data('expanded', node.data.expanded || false);
        existing.data('nodeType', node.nodeType);
        if (node.data.entityType) existing.data('entityType', node.data.entityType);
      }
    }

    for (const [id, edge] of viewGraph.cyEdges) {
      const existing = cy.getElementById(id);
      if (existing.length === 0) {
        if (cy.getElementById(edge.source).length > 0 && cy.getElementById(edge.target).length > 0) {
          cy.add({
            group: 'edges',
            data: { id, source: edge.source, target: edge.target, label: edge.label, edgeType: edge.data.edgeType },
            classes: edge.classes.join(' '),
          });
          structureChanged = true;
        }
      }
    }

    // Apply pending selection after structure sync
    const applyPendingSelect = () => {
      const selectId = pendingSelectRef.current;
      if (selectId) {
        const ele = cy.getElementById(selectId);
        if (ele.length > 0) {
          pendingSelectRef.current = null;
          cy.$(':selected').unselect();
          ele.select();
          const node = viewGraph.cyNodes.get(selectId);
          if (node) {
            setSelectedNode(node); selectedNodeIdRef.current = selectId;
            setSelectedEdge(null); selectedEdgeIdRef.current = null;
            setMultiSelection(null);
          } else {
            const edge = viewGraph.cyEdges.get(selectId);
            if (edge) {
              setSelectedEdge(edge); selectedEdgeIdRef.current = selectId;
              setSelectedNode(null); selectedNodeIdRef.current = null;
              setMultiSelection(null);
            }
          }
        }
      }
    };

    if (structureChanged && cy.nodes().length > 0 && layoutConfigRef.current.autoLayoutOnChange) {
      const opts = buildLayoutOptions(layoutConfigRef.current, cy.nodes().length, cy);
      const layout = cy.layout(opts as any);
      layout.on('layoutstop', () => {
        requestAnimationFrame(() => {
          cy.resize();
          const focusId = pendingFocusRef.current;
          if (focusId) {
            const focusEle = cy.getElementById(focusId);
            if (focusEle.length > 0) {
              cy.animate({ center: { eles: focusEle }, zoom: 1.5 }, { duration: 400 });
              pendingFocusRef.current = null;
            }
          } else {
            cy.fit(undefined, 20);
          }
          applyPendingSelect();
        });
      });
      layout.run();
    } else {
      applyPendingSelect();
    }
  }, [viewGraph]);

  // Re-layout on demand or when algorithm changes
  const runLayout = useCallback(() => {
    const cy = cyRef.current;
    if (!cy || cy.nodes().length === 0) return;
    const opts = buildLayoutOptions(layoutConfigRef.current, cy.nodes().length, cy);
    const layout = cy.layout(opts as any);
    layout.on('layoutstop', () => { requestAnimationFrame(() => { cy.resize(); cy.fit(undefined, 20); }); });
    layout.run();
  }, []);

  const handleLayoutChange = useCallback((algorithm: LayoutAlgorithm) => {
    setLayoutConfig(prev => ({ ...prev, algorithm }));
    setTimeout(() => {
      const cy = cyRef.current;
      if (!cy || cy.nodes().length === 0) return;
      const newConfig = { ...layoutConfigRef.current, algorithm };
      layoutConfigRef.current = newConfig;
      const opts = buildLayoutOptions(newConfig, cy.nodes().length, cy);
      const layout = cy.layout(opts as any);
      layout.on('layoutstop', () => { requestAnimationFrame(() => { cy.resize(); cy.fit(undefined, 20); }); });
      layout.run();
    }, 0);
  }, []);

  const handleSearch = useCallback(() => {
    if (searchTerm.trim() && spaceId) {
      searchEntities(searchTerm);
      setSearchOpen(true);
    }
  }, [searchTerm, spaceId, searchEntities]);

  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      if (searchMode === 'database') handleSearch();
    }
    if (e.key === 'Escape') {
      if (searchMode === 'local') { setLocalSearchTerm(''); }
      setSearchOpen(false);
    }
  }, [handleSearch, searchMode]);

  // Local search: highlight matching elements, dim the rest
  const localMatchCount = useRef(0);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const term = localSearchTerm.trim().toLowerCase();
    if (!term) {
      cy.elements().removeClass('dimmed highlighted');
      localMatchCount.current = 0;
      return;
    }
    const matched = cy.elements().filter((ele) => {
      const label = (ele.data('label') || '').toLowerCase();
      const uri = (ele.data('id') || '').toLowerCase();
      const nodeType = (ele.data('nodeType') || '').toLowerCase();
      return label.includes(term) || uri.includes(term) || nodeType.includes(term);
    });
    cy.elements().removeClass('highlighted').addClass('dimmed');
    matched.removeClass('dimmed').addClass('highlighted');
    // Also un-dim edges between highlighted nodes
    matched.nodes().connectedEdges().filter((e) => {
      const src = e.source();
      const tgt = e.target();
      return src.hasClass('highlighted') && tgt.hasClass('highlighted');
    }).removeClass('dimmed');
    localMatchCount.current = matched.length;
    // Center on matched elements
    if (matched.length > 0) {
      cy.animate({ fit: { eles: matched, padding: 40 } }, { duration: 300 });
    }
  }, [localSearchTerm]);

  const fitGraph = useCallback(() => {
    cyRef.current?.fit(undefined, 40);
  }, []);

  const nodeCount = viewGraph.cyNodes.size;
  const edgeCount = viewGraph.cyEdges.size;

  return (
    <div className="flex flex-col h-[calc(100vh-120px)] w-full max-w-full overflow-hidden" data-testid="graph-visualization-page">
      {/* ── Toolbar ── */}
      <div className="h-10 flex items-center gap-1 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 px-2 shrink-0">
        {/* Space */}
        <select
          value={spaceId}
          onChange={(e) => handleSpaceChange(e.target.value)}
          className="h-7 text-xs bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded px-2 pr-6 text-gray-700 dark:text-gray-300 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
        >
          {spaces.length === 0 && <option value="">Loading…</option>}
          {spaces.map((s, i) => (
            <option key={`${s.id}-${i}`} value={s.id}>{s.isSystem ? `⚙ ${s.name}` : s.name}</option>
          ))}
        </select>

        <div className="w-px h-5 bg-gray-300 dark:bg-gray-600 mx-1" />

        {/* Search toggle */}
        <ToolbarButton onClick={() => { setSearchOpen(o => !o); setTimeout(() => searchInputRef.current?.focus(), 50); }} title="Search (Ctrl+F)" active={searchOpen}>
          <HiSearch className="w-4 h-4" />
        </ToolbarButton>

        <div className="w-px h-5 bg-gray-300 dark:bg-gray-600 mx-1" />

        {/* Layout */}
        <select
          value={layoutConfig.algorithm}
          onChange={(e) => handleLayoutChange(e.target.value as LayoutAlgorithm)}
          className="h-7 text-xs bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded px-2 pr-6 text-gray-700 dark:text-gray-300 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
        >
          {LAYOUT_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        <ToolbarButton onClick={runLayout} title="Re-run layout">
          <HiRefresh className="w-4 h-4" />
        </ToolbarButton>

        <div className="w-px h-5 bg-gray-300 dark:bg-gray-600 mx-1" />

        {/* Graph actions */}
        <ToolbarButton onClick={fitGraph} title="Fit to viewport">
          <HiZoomIn className="w-4 h-4" />
        </ToolbarButton>
        {canLoadFullSpace && (
          <ToolbarButton onClick={loadFullSpace} title="Load entire space" disabled={loading}>
            {loading ? <Spinner size="xs" /> : <HiDownload className="w-4 h-4" />}
          </ToolbarButton>
        )}
        <ToolbarButton onClick={() => { sessionRestoredRef.current = true; clearGraph(); setSelectedNode(null); selectedNodeIdRef.current = null; setSelectedEdge(null); selectedEdgeIdRef.current = null; setMultiSelection(null); setDrawerOpen(false); }} title="Clear graph">
          <HiTrash className="w-4 h-4" />
        </ToolbarButton>

        <div className="w-px h-5 bg-gray-300 dark:bg-gray-600 mx-1" />

        {/* Legend / Export */}
        <ToolbarButton onClick={() => setLegendOpen(o => !o)} title="Toggle legend" active={legendOpen}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><rect x="3" y="3" width="7" height="7" rx="1" strokeWidth="2"/><path strokeLinecap="round" strokeWidth="2" d="M14 5h7M14 12h7M14 19h7M3 14h7M3 19h7"/></svg>
        </ToolbarButton>
        <ToolbarButton onClick={() => setStatsOpen(o => !o)} title="Toggle statistics" active={statsOpen}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
        </ToolbarButton>
        <ToolbarButton onClick={handleExportPng} title="Export PNG">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
        </ToolbarButton>
        <ToolbarButton onClick={handleExportJson} title="Export JSON">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
        </ToolbarButton>
        <ToolbarButton onClick={handleExportSvg} title="Export SVG">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 17l2-2 2 2m-2-2v-4"/></svg>
        </ToolbarButton>
        <ToolbarButton onClick={handleExportCsv} title="Export CSV">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 10h18M3 14h18M3 6h18M3 18h18"/></svg>
        </ToolbarButton>
        <ToolbarButton onClick={() => { cyRef.current?.nodes().unlock(); }} title="Unpin all nodes">
          <HiLockOpen className="w-4 h-4" />
        </ToolbarButton>

        {/* Right-side status */}
        <div className="ml-auto flex items-center gap-2">
          {(expanding || loading) && (
            <span className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
              <Spinner size="xs" /> {loading ? 'Loading…' : 'Expanding…'}
            </span>
          )}
          {error && (
            <span className="text-xs text-red-500" title={error}>Error</span>
          )}
        </div>
      </div>

      {/* ── Session tab bar ── */}
      <div className="h-8 flex items-center bg-gray-100 dark:bg-gray-850 border-b border-gray-200 dark:border-gray-700 px-1 shrink-0 overflow-x-auto gap-0.5">
        {sessionList.map(s => (
          <div
            key={s.id}
            className={`group flex items-center gap-1 h-6 px-2 rounded text-xs cursor-pointer transition-colors shrink-0 ${
              s.id === activeSessionId
                ? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-white shadow-sm border border-gray-200 dark:border-gray-600'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
            onClick={() => handleSwitchSession(s.id)}
            onDoubleClick={() => {
              const newName = prompt('Rename session:', s.name);
              if (newName && newName.trim()) renameSession(s.id, newName.trim());
            }}
            title={`${s.name} — ${s.nodeCount} nodes, ${s.edgeCount} edges`}
          >
            <span className="truncate max-w-24">{s.name}</span>
            <button
              onClick={(e) => { e.stopPropagation(); handleCloseSession(s.id); }}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-gray-300 dark:hover:bg-gray-600 transition-opacity"
              title="Close session"
            >
              <HiX className="w-3 h-3" />
            </button>
          </div>
        ))}
        <button
          onClick={handleNewSession}
          className="h-6 w-6 flex items-center justify-center rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 shrink-0 transition-colors"
          title="New session"
        >
          <HiPlus className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* ── Canvas area ── */}
      <div className="flex-1 min-h-0 relative bg-gray-100 dark:bg-gray-950 overflow-hidden">
        {/* Cytoscape container */}
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

        {/* ── Timeline axis overlay ── */}
        <TimelineAxis
          cy={cyRef.current}
          eventTimestamps={eventTimestamps}
          visible={layoutConfig.algorithm === 'event-timeline'}
        />

        {/* ── Legend overlay (bottom-left) ── */}
        {legendOpen && legendItems.length > 0 && (
          <div className="absolute bottom-3 left-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 z-10 max-h-48 overflow-y-auto min-w-36">
            <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Legend</div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-xs">
                <span className="w-3 h-3 rounded-full bg-indigo-500 shrink-0" />
                <span className="text-gray-600 dark:text-gray-300">Unexpanded</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="w-3 h-3 rounded-full bg-emerald-500 shrink-0" />
                <span className="text-gray-600 dark:text-gray-300">Expanded</span>
              </div>
              <div className="border-t border-gray-100 dark:border-gray-700 my-1.5" />
              {legendItems.map(item => (
                <div key={item.type} className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: getTypeColor(item.type) }} />
                  <span className="text-gray-600 dark:text-gray-300 truncate flex-1">{shortenType(item.type)}</span>
                  <span className="text-gray-400 dark:text-gray-500 shrink-0">{item.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Statistics overlay (bottom-right) ── */}
        {statsOpen && graphStats.nodeCount > 0 && (
          <div className="absolute bottom-3 right-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 z-10 w-56">
            <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Statistics</div>
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 dark:text-gray-400">Nodes</span>
                <span className="text-gray-700 dark:text-gray-300 font-medium">{graphStats.nodeCount}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 dark:text-gray-400">Edges</span>
                <span className="text-gray-700 dark:text-gray-300 font-medium">{graphStats.edgeCount}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 dark:text-gray-400">Components</span>
                <span className="text-gray-700 dark:text-gray-300 font-medium">{graphStats.components}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 dark:text-gray-400">Avg Degree</span>
                <span className="text-gray-700 dark:text-gray-300 font-medium">{graphStats.avgDegree}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 dark:text-gray-400">Max Degree</span>
                <span className="text-gray-700 dark:text-gray-300 font-medium">{graphStats.maxDegree}</span>
              </div>
              {graphStats.maxDegreeNode && (
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500 dark:text-gray-400">Hub Node</span>
                  <span className="text-gray-700 dark:text-gray-300 font-medium truncate ml-2 max-w-24" title={graphStats.maxDegreeNode}>{graphStats.maxDegreeNode}</span>
                </div>
              )}
              {graphStats.typeBreakdown.length > 0 && (
                <>
                  <div className="border-t border-gray-100 dark:border-gray-700 my-1.5" />
                  <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">Types</div>
                  {graphStats.typeBreakdown.map(item => (
                    <div key={item.type} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-gray-600 dark:text-gray-300 truncate">{item.type}</span>
                      <span className="text-gray-400 dark:text-gray-500 shrink-0">{item.count}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        )}

        {/* Empty state */}
        {nodeCount === 0 && !loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-200 dark:bg-gray-800 flex items-center justify-center">
                <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <circle cx="8" cy="8" r="3" strokeWidth="1.5" />
                  <circle cx="16" cy="16" r="3" strokeWidth="1.5" />
                  <circle cx="18" cy="6" r="2" strokeWidth="1.5" />
                  <line x1="10.5" y1="9.5" x2="14" y2="14" strokeWidth="1.5" />
                  <line x1="16.5" y1="7.5" x2="17" y2="13.5" strokeWidth="1.5" />
                </svg>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">No graph data loaded</p>
              <p className="text-xs text-gray-400 dark:text-gray-500">
                Use <kbd className="px-1.5 py-0.5 bg-gray-200 dark:bg-gray-700 rounded text-xs">Search</kbd> to find entities or load the full space
              </p>
            </div>
          </div>
        )}

        {/* ── Search panel (floating, top-left) ── */}
        {searchOpen && (
          <div className="absolute top-3 left-3 z-20 w-72">
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              {/* Mode toggle */}
              <div className="flex border-b border-gray-100 dark:border-gray-700">
                <button
                  onClick={() => { setSearchMode('database'); setLocalSearchTerm(''); }}
                  className={`flex-1 text-xs py-1.5 font-medium transition-colors ${
                    searchMode === 'database'
                      ? 'text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-500'
                      : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
                  }`}
                >
                  Database
                </button>
                <button
                  onClick={() => setSearchMode('local')}
                  className={`flex-1 text-xs py-1.5 font-medium transition-colors ${
                    searchMode === 'local'
                      ? 'text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-500'
                      : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
                  }`}
                >
                  Local
                </button>
              </div>
              {/* Search input */}
              <div className="flex items-center border-b border-gray-100 dark:border-gray-700">
                <HiSearch className="w-4 h-4 text-gray-400 ml-3 shrink-0" />
                {searchMode === 'database' ? (
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
                    placeholder="Search database…"
                    className="flex-1 px-2 py-2.5 text-sm bg-transparent border-none outline-none text-gray-900 dark:text-white placeholder-gray-400"
                  />
                ) : (
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={localSearchTerm}
                    onChange={(e) => setLocalSearchTerm(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
                    placeholder="Filter displayed graph…"
                    className="flex-1 px-2 py-2.5 text-sm bg-transparent border-none outline-none text-gray-900 dark:text-white placeholder-gray-400"
                  />
                )}
                {searching && searchMode === 'database' && <Spinner size="xs" className="mr-2" />}
                <button onClick={() => { setSearchOpen(false); setLocalSearchTerm(''); }} className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                  <HiX className="w-4 h-4" />
                </button>
              </div>
              {/* Database results */}
              {searchMode === 'database' && searchResults.length > 0 && (
                <div className="max-h-64 overflow-y-auto">
                  {searchResults.map(r => (
                    <button
                      key={r.uri}
                      onClick={() => {
                        addNode(r.uri, r.name, r.typeDescription);
                        expandNode(r.uri);
                      }}
                      className="w-full text-left px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors flex items-center gap-2"
                      title={r.uri}
                    >
                      <span className="w-2 h-2 rounded-full bg-indigo-400 shrink-0" />
                      <span className="truncate">{r.name}</span>
                    </button>
                  ))}
                </div>
              )}
              {searchMode === 'database' && searchResults.length === 0 && searchTerm && !searching && (
                <p className="px-3 py-3 text-xs text-gray-400">No results for &ldquo;{searchTerm}&rdquo;</p>
              )}
              {/* Local search status */}
              {searchMode === 'local' && localSearchTerm.trim() && (
                <div className="px-3 py-2.5 text-xs text-gray-500 dark:text-gray-400">
                  {localMatchCount.current > 0
                    ? <span><span className="font-medium text-indigo-600 dark:text-indigo-400">{localMatchCount.current}</span> element{localMatchCount.current !== 1 ? 's' : ''} matched</span>
                    : <span>No matches in displayed graph</span>
                  }
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Inspector drawer (right side) ── */}
        <div className={`absolute top-0 right-0 h-full w-72 bg-white dark:bg-gray-800 border-l border-gray-200 dark:border-gray-700 shadow-xl z-20 transition-transform duration-200 ${
          drawerOpen && (selectedNode || selectedEdge || multiSelection) ? 'translate-x-0' : 'translate-x-full'
        }`}>
          {/* Drawer header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700">
            <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Inspector</span>
            <button
              onClick={() => { setDrawerOpen(false); setSelectedNode(null); selectedNodeIdRef.current = null; setSelectedEdge(null); selectedEdgeIdRef.current = null; setMultiSelection(null); }}
              className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              <HiX className="w-4 h-4" />
            </button>
          </div>

          {/* ── Node view ── */}
          {selectedNode && (
            <>
              <div className="px-4 py-4 border-b border-gray-100 dark:border-gray-700">
                <div className="flex items-start gap-3">
                  <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-white text-xs font-bold ${
                    selectedNode.data.expanded ? 'bg-emerald-500' : 'bg-indigo-500'
                  }`}>
                    {selectedNode.label.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate" title={selectedNode.label}>
                      {selectedNode.label}
                    </h3>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate" title={selectedNode.id}>
                      {selectedNode.nodeType}
                    </p>
                  </div>
                </div>
              </div>

              <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
                  <HiChevronDown className="w-3 h-3" />
                  Properties
                </div>
                <div className="space-y-1.5">
                  {selectedNode.data.entityType && (
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500 dark:text-gray-400">Entity Type</span>
                      <span className="text-gray-700 dark:text-gray-300 truncate ml-2 max-w-32">{selectedNode.data.entityType}</span>
                    </div>
                  )}
                  {selectedNode.data.frameType && (
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500 dark:text-gray-400">Frame Type</span>
                      <span className="text-gray-700 dark:text-gray-300 truncate ml-2 max-w-32">{selectedNode.data.frameType}</span>
                    </div>
                  )}
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-gray-400">State</span>
                    <span className={`font-medium ${selectedNode.data.expanded ? 'text-emerald-600' : 'text-gray-500'}`}>
                      {selectedNode.data.expanded ? 'Expanded' : 'Collapsed'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="px-4 py-3">
                <div className="space-y-2">
                  {!selectedNode.data.expanded ? (
                    <button
                      onClick={() => expandNode(selectedNode.id)}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
                    >
                      <HiChevronRight className="w-4 h-4" /> Expand Node
                    </button>
                  ) : (
                    <button
                      onClick={() => collapseNode(selectedNode.id)}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors"
                    >
                      <HiChevronDown className="w-4 h-4" /> Collapse Node
                    </button>
                  )}
                  <button
                    onClick={() => { removeNode(selectedNode.id); setSelectedNode(null); selectedNodeIdRef.current = null; setDrawerOpen(false); }}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 rounded-lg transition-colors"
                  >
                    <HiTrash className="w-4 h-4" /> Remove
                  </button>
                  {(selectedNode.nodeType === 'entity' || selectedNode.nodeType === 'kgtype') && (
                    <button
                      onClick={() => {
                        if (selectedNode.nodeType === 'kgtype') {
                          navigate(`/kg-types/${encodeURIComponent(selectedNode.id)}`);
                        } else {
                          navigate(`/space/${spaceId}/graph/${encodeURIComponent(graphUri || 'default')}/entity/${encodeURIComponent(selectedNode.id)}`);
                        }
                      }}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <HiExternalLink className="w-4 h-4" /> View Detail
                    </button>
                  )}
                  <button
                    onClick={() => {
                      const cy = cyRef.current;
                      if (!cy) return;
                      const ele = cy.getElementById(selectedNode.id);
                      if (ele.length === 0) return;
                      const isPinned = ele.locked();
                      if (isPinned) { ele.unlock(); } else { ele.lock(); }
                      setSelectedNode({ ...selectedNode, data: { ...selectedNode.data, pinned: !isPinned } });
                    }}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors"
                  >
                    {selectedNode.data.pinned ? <HiLockOpen className="w-4 h-4" /> : <HiLockClosed className="w-4 h-4" />}
                    {selectedNode.data.pinned ? 'Unpin Node' : 'Pin Node'}
                  </button>
                </div>
              </div>
            </>
          )}

          {/* ── Edge view ── */}
          {selectedEdge && !selectedNode && (
            <>
              <div className="px-4 py-4 border-b border-gray-100 dark:border-gray-700">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded shrink-0 flex items-center justify-center bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate" title={selectedEdge.label}>
                      {selectedEdge.label || '(unlabeled edge)'}
                    </h3>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                      {selectedEdge.data.edgeType}
                    </p>
                  </div>
                </div>
              </div>

              <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
                  <HiChevronDown className="w-3 h-3" />
                  Connection
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-gray-400">Source</span>
                    <span className="text-gray-700 dark:text-gray-300 truncate ml-2 max-w-36" title={selectedEdge.source}>
                      {viewGraph.cyNodes.get(selectedEdge.source)?.label || selectedEdge.source}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-gray-400">Target</span>
                    <span className="text-gray-700 dark:text-gray-300 truncate ml-2 max-w-36" title={selectedEdge.target}>
                      {viewGraph.cyNodes.get(selectedEdge.target)?.label || selectedEdge.target}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-gray-400">Type</span>
                    <span className="text-gray-700 dark:text-gray-300 truncate ml-2 max-w-36">{selectedEdge.data.edgeType}</span>
                  </div>
                  {selectedEdge.data.frameUri && (
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500 dark:text-gray-400">Frame</span>
                      <button
                        onClick={() => navigate(`/space/${spaceId}/graph/${encodeURIComponent('default')}/frame/${encodeURIComponent(selectedEdge.data.frameUri!)}`)}
                        className="text-indigo-600 dark:text-indigo-400 hover:underline truncate ml-2 max-w-36"
                        title={selectedEdge.data.frameUri}
                      >
                        {selectedEdge.data.frameUri.split('/').pop()}
                      </button>
                    </div>
                  )}
                  {selectedEdge.data.slotType && (
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500 dark:text-gray-400">Slot Type</span>
                      <span className="text-gray-700 dark:text-gray-300 truncate ml-2 max-w-36">{selectedEdge.data.slotType}</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="px-4 py-3">
                <div className="space-y-2">
                  {selectedEdge.data.edgeType === 'relation' && (
                    <button
                      onClick={() => {
                        const relationUri = selectedEdge.id.replace(/^relation:/, '');
                        navigate(`/space/${spaceId}/graph/${encodeURIComponent(graphUri || 'default')}/relation/${encodeURIComponent(relationUri)}`);
                      }}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <HiExternalLink className="w-4 h-4" /> View Detail
                    </button>
                  )}
                  {selectedEdge.data.edgeType === 'collapsed_frame' && selectedEdge.data.frameUri && (
                    <button
                      onClick={() => {
                        navigate(`/space/${spaceId}/graph/${encodeURIComponent(graphUri || 'default')}/frame/${encodeURIComponent(selectedEdge.data.frameUri!)}`);
                      }}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <HiExternalLink className="w-4 h-4" /> View Frame Detail
                    </button>
                  )}
                  <button
                    onClick={() => {
                      const cy = cyRef.current;
                      if (!cy) return;
                      const ele = cy.getElementById(selectedEdge.id);
                      if (ele.length > 0) ele.remove();
                      setSelectedEdge(null); selectedEdgeIdRef.current = null; setDrawerOpen(false);
                    }}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 rounded-lg transition-colors"
                  >
                    <HiTrash className="w-4 h-4" /> Remove
                  </button>
                </div>
              </div>
            </>
          )}

          {/* ── Multi-selection summary ── */}
          {multiSelection && !selectedNode && !selectedEdge && (
            <>
              <div className="px-4 py-4 border-b border-gray-100 dark:border-gray-700">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded shrink-0 flex items-center justify-center bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                      Selection Summary
                    </h3>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                      {multiSelection.nodes + multiSelection.edges} elements selected
                    </p>
                  </div>
                </div>
              </div>

              <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
                  <HiChevronDown className="w-3 h-3" />
                  Breakdown
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-gray-400">Nodes</span>
                    <span className="text-gray-700 dark:text-gray-300 font-medium">{multiSelection.nodes}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-gray-400">Edges</span>
                    <span className="text-gray-700 dark:text-gray-300 font-medium">{multiSelection.edges}</span>
                  </div>
                  {multiSelection.typeCounts.size > 0 && (
                    <div className="mt-2">
                      <span className="text-xs text-gray-500 dark:text-gray-400">By Class:</span>
                      <div className="space-y-1 mt-1">
                        {[...multiSelection.typeCounts.entries()]
                          .sort((a, b) => b[1] - a[1])
                          .map(([t, count]) => (
                            <div key={t} className="flex items-center gap-2 text-xs">
                              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: getTypeColor(t) }} />
                              <span className="text-gray-600 dark:text-gray-300 truncate flex-1">{shortenType(t)}</span>
                              <span className="text-gray-400 dark:text-gray-500 font-medium shrink-0">{count}</span>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Status bar ── */}
      <div className="h-7 flex items-center px-3 bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 shrink-0 gap-4">
        <span>{nodeCount} nodes</span>
        <span>{edgeCount} edges</span>
        {spaceId && <span className="text-gray-400 dark:text-gray-500">Space: {spaceId}</span>}
        {activeSessionId && <span className="text-gray-400 dark:text-gray-500">Session: {sessionList.find(s => s.id === activeSessionId)?.name}</span>}
        <span className="ml-auto text-gray-400 dark:text-gray-500">{layoutConfig.algorithm}</span>
      </div>
    </div>
  );
}
