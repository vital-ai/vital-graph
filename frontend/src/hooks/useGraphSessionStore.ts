// ---------------------------------------------------------------------------
// Multi-Session Graph Store (Phase 2)
//
// Manages multiple concurrent graph investigation sessions, each with its
// own DataGraph and derived ViewGraph. Persists session recipes (not data)
// to localStorage for replay on restore.
//
// See: planning/planning_visualization/graph_session_architecture_plan.md §5
// ---------------------------------------------------------------------------

import { useState, useCallback, useMemo } from 'react';
import type { DataGraph, ViewGraph, KGEntityData, KGFrameData, KGSlotData, KGDocumentData, EdgeData } from './graphTypes';
import { createEmptyDataGraph } from './graphTypes';
import { buildViewGraph } from './buildViewGraph';

// ---------------------------------------------------------------------------
// Session types
// ---------------------------------------------------------------------------

export type RecipeStep =
  | { action: 'add_node'; uri: string; name: string }
  | { action: 'expand'; uri: string }
  | { action: 'remove_node'; uri: string }
  | { action: 'collapse'; uri: string }
  | { action: 'clear' };

export interface GraphSession {
  id: string;
  name: string;
  spaceId: string;
  createdAt: Date;
  updatedAt: Date;
  dataGraph: DataGraph;
  recipe: RecipeStep[];
  selectedUris?: string[];
}

export interface SessionSummary {
  id: string;
  name: string;
  spaceId: string;
  nodeCount: number;
  edgeCount: number;
  updatedAt: Date;
}

// ---------------------------------------------------------------------------
// localStorage persistence (includes DataGraph serialization)
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'vitalgraph:graph_sessions';

interface SerializedDataGraph {
  entities: [string, KGEntityData & { fetchedAt: string }][];
  frames: [string, KGFrameData & { fetchedAt: string }][];
  slots: [string, KGSlotData][];
  documents: [string, KGDocumentData & { fetchedAt: string }][];
  edges: [string, EdgeData][];
  fetchedExpansions: string[];
}

interface PersistedSession {
  id: string;
  name: string;
  spaceId: string;
  createdAt: string;
  updatedAt: string;
  recipe: RecipeStep[];
  entityUris?: string[];
  dataGraph?: SerializedDataGraph;
  pendingExpand?: string[];
  pendingSelect?: string;
  selectedUris?: string[];
}

function serializeDataGraph(dg: DataGraph): SerializedDataGraph {
  return {
    entities: [...dg.entities.entries()].map(([k, v]) => [k, { ...v, fetchedAt: v.fetchedAt.toISOString() }] as [string, KGEntityData & { fetchedAt: string }]),
    frames: [...dg.frames.entries()].map(([k, v]) => [k, { ...v, fetchedAt: v.fetchedAt.toISOString() }] as [string, KGFrameData & { fetchedAt: string }]),
    slots: [...dg.slots.entries()],
    documents: [...dg.documents.entries()].map(([k, v]) => [k, { ...v, fetchedAt: v.fetchedAt.toISOString() }] as [string, KGDocumentData & { fetchedAt: string }]),
    edges: [...dg.edges.entries()],
    fetchedExpansions: [...dg.fetchedExpansions],
  };
}

function deserializeDataGraph(raw: SerializedDataGraph | undefined): DataGraph {
  if (!raw) return createEmptyDataGraph();
  return {
    entities: new Map((raw.entities || []).map(([k, v]) => [k, { ...v, fetchedAt: new Date(v.fetchedAt) }])),
    frames: new Map((raw.frames || []).map(([k, v]) => [k, { ...v, fetchedAt: new Date(v.fetchedAt) }])),
    slots: new Map(raw.slots || []),
    documents: new Map((raw.documents || []).map(([k, v]) => [k, { ...v, fetchedAt: new Date(v.fetchedAt) }])),
    edges: new Map(raw.edges || []),
    fetchedExpansions: new Set(raw.fetchedExpansions || []),
  };
}

function loadPersistedSessions(): PersistedSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as PersistedSession[];
  } catch {
    return [];
  }
}

function savePersistedSessions(sessions: Map<string, GraphSession>): void {
  try {
    const arr: PersistedSession[] = [];
    for (const s of sessions.values()) {
      arr.push({
        id: s.id,
        name: s.name,
        spaceId: s.spaceId,
        createdAt: s.createdAt.toISOString(),
        updatedAt: s.updatedAt.toISOString(),
        recipe: s.recipe,
        entityUris: [...s.dataGraph.entities.keys()],
        dataGraph: serializeDataGraph(s.dataGraph),
        selectedUris: s.selectedUris,
      });
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
  } catch {
    // localStorage full or unavailable — degrade silently
  }
}

// ---------------------------------------------------------------------------
// Public utility — query sessions containing a URI (reads localStorage directly)
// ---------------------------------------------------------------------------

export interface SessionMatch {
  id: string;
  name: string;
  spaceId: string;
  updatedAt: string;
  containsUri?: boolean;
}

export function getSessionsForUri(uri: string): SessionMatch[] {
  const persisted = loadPersistedSessions();
  const matches: SessionMatch[] = [];
  for (const s of persisted) {
    if (s.entityUris && s.entityUris.includes(uri)) {
      matches.push({ id: s.id, name: s.name, spaceId: s.spaceId, updatedAt: s.updatedAt });
    }
  }
  return matches;
}

export function getSessionsForSpace(spaceId: string, entityUri?: string): SessionMatch[] {
  const persisted = loadPersistedSessions();
  const matches: SessionMatch[] = [];
  for (const s of persisted) {
    if (s.spaceId === spaceId) {
      const containsUri = entityUri ? (s.entityUris?.includes(entityUri) ?? false) : undefined;
      matches.push({ id: s.id, name: s.name, spaceId: s.spaceId, updatedAt: s.updatedAt, containsUri });
    }
  }
  return matches;
}

/**
 * Standalone function (callable outside of hooks) that prepares a visualization
 * session by writing to localStorage. Returns the session ID to navigate to.
 *
 * - If sessionId is provided, adds entityUri to that session's pendingExpand.
 * - If sessionId is null, creates a new session for the given space.
 */
export function prepareVisualization(spaceId: string, entityUri: string, sessionId?: string): string {
  const persisted = loadPersistedSessions();

  if (sessionId) {
    // Add to existing session's pending expand
    const idx = persisted.findIndex(s => s.id === sessionId);
    if (idx >= 0) {
      const existing = persisted[idx];
      const pending = existing.pendingExpand || [];
      if (!pending.includes(entityUri)) {
        pending.push(entityUri);
      }
      persisted[idx] = { ...existing, pendingExpand: pending, pendingSelect: entityUri, updatedAt: new Date().toISOString() };
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted)); } catch { /* */ }
      return sessionId;
    }
  }

  // Create new session
  _counter++;
  const newId = `session_${Date.now()}_${_counter}`;
  const newSession: PersistedSession = {
    id: newId,
    name: `Session ${persisted.length + 1}`,
    spaceId,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    recipe: [],
    entityUris: [],
    pendingExpand: [entityUri],
    pendingSelect: entityUri,
  };
  persisted.push(newSession);
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted)); } catch { /* */ }
  return newId;
}

/**
 * Read and clear pending expansions for a session from localStorage.
 */
export function consumePendingExpand(sessionId: string): string[] {
  const persisted = loadPersistedSessions();
  const idx = persisted.findIndex(s => s.id === sessionId);
  if (idx < 0) return [];
  const pending = persisted[idx].pendingExpand || [];
  if (pending.length === 0) return [];
  // Clear pending
  persisted[idx] = { ...persisted[idx], pendingExpand: [] };
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted)); } catch { /* */ }
  return pending;
}

/**
 * Read and clear pending selection for a session from localStorage.
 */
export function consumePendingSelect(sessionId: string): string | null {
  const persisted = loadPersistedSessions();
  const idx = persisted.findIndex(s => s.id === sessionId);
  if (idx < 0) return null;
  const uri = persisted[idx].pendingSelect || null;
  if (!uri) return null;
  persisted[idx] = { ...persisted[idx], pendingSelect: undefined };
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted)); } catch { /* */ }
  return uri;
}

function hydratePersistedSessions(): Map<string, GraphSession> {
  const persisted = loadPersistedSessions();
  const map = new Map<string, GraphSession>();
  for (const p of persisted) {
    map.set(p.id, {
      id: p.id,
      name: p.name,
      spaceId: p.spaceId,
      createdAt: new Date(p.createdAt),
      updatedAt: new Date(p.updatedAt),
      dataGraph: deserializeDataGraph(p.dataGraph),
      recipe: p.recipe,
      selectedUris: p.selectedUris,
    });
  }
  return map;
}

// ---------------------------------------------------------------------------
// ID generation
// ---------------------------------------------------------------------------

let _counter = 0;
function generateSessionId(): string {
  _counter++;
  return `session_${Date.now()}_${_counter}`;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGraphSessionStore(initialSessionId?: string | null) {
  const [sessions, setSessions] = useState<Map<string, GraphSession>>(hydratePersistedSessions);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => {
    const persisted = loadPersistedSessions();
    // If an initial session ID is provided and exists, use it
    if (initialSessionId && persisted.some(s => s.id === initialSessionId)) {
      return initialSessionId;
    }
    return persisted.length > 0 ? persisted[0].id : null;
  });

  // ── Derived state ─────────────────────────────────────────────────────────

  const activeSession = activeSessionId ? sessions.get(activeSessionId) ?? null : null;

  const activeViewGraph: ViewGraph | null = useMemo(() => {
    if (!activeSession) return null;
    return buildViewGraph(activeSession.dataGraph);
  }, [activeSession]);

  // ── Session CRUD ─────────────────────────────────────────────────────

  const createSession = useCallback((name: string, spaceId: string): GraphSession => {
    const session: GraphSession = {
      id: generateSessionId(),
      name,
      spaceId,
      createdAt: new Date(),
      updatedAt: new Date(),
      dataGraph: createEmptyDataGraph(),
      recipe: [],
    };
    setSessions(prev => {
      const next = new Map(prev);
      next.set(session.id, session);
      savePersistedSessions(next);
      return next;
    });
    setActiveSessionId(session.id);
    return session;
  }, []);

  const deleteSession = useCallback((sessionId: string) => {
    setSessions(prev => {
      const next = new Map(prev);
      next.delete(sessionId);
      savePersistedSessions(next);
      return next;
    });
    setActiveSessionId(prev => {
      if (prev === sessionId) {
        // Switch to first remaining session or null
        const remaining = [...sessions.keys()].filter(k => k !== sessionId);
        return remaining.length > 0 ? remaining[0] : null;
      }
      return prev;
    });
  }, [sessions]);

  const renameSession = useCallback((sessionId: string, name: string) => {
    setSessions(prev => {
      const session = prev.get(sessionId);
      if (!session) return prev;
      const next = new Map(prev);
      next.set(sessionId, { ...session, name, updatedAt: new Date() });
      savePersistedSessions(next);
      return next;
    });
  }, []);

  const duplicateSession = useCallback((sessionId: string): GraphSession | null => {
    const source = sessions.get(sessionId);
    if (!source) return null;
    const newSession: GraphSession = {
      id: generateSessionId(),
      name: `${source.name} (copy)`,
      spaceId: source.spaceId,
      createdAt: new Date(),
      updatedAt: new Date(),
      dataGraph: createEmptyDataGraph(), // will be rebuilt on replay
      recipe: [...source.recipe],
    };
    setSessions(prev => {
      const next = new Map(prev);
      next.set(newSession.id, newSession);
      savePersistedSessions(next);
      return next;
    });
    setActiveSessionId(newSession.id);
    return newSession;
  }, [sessions]);

  const switchSession = useCallback((sessionId: string) => {
    if (sessions.has(sessionId)) {
      setActiveSessionId(sessionId);
    }
  }, [sessions]);

  const updateSessionSpace = useCallback((sessionId: string, newSpaceId: string) => {
    setSessions(prev => {
      const session = prev.get(sessionId);
      if (!session) return prev;
      const next = new Map(prev);
      next.set(sessionId, { ...session, spaceId: newSpaceId, updatedAt: new Date() });
      savePersistedSessions(next);
      return next;
    });
  }, []);

  // ── DataGraph mutations (operate on active session) ──────────────────

  const updateActiveDataGraph = useCallback(
    (updater: (dg: DataGraph) => DataGraph, step?: RecipeStep) => {
      setSessions(prev => {
        if (!activeSessionId) return prev;
        const session = prev.get(activeSessionId);
        if (!session) return prev;

        const next = new Map(prev);
        const updatedSession: GraphSession = {
          ...session,
          dataGraph: updater(session.dataGraph),
          updatedAt: new Date(),
          recipe: step ? [...session.recipe, step] : session.recipe,
        };
        next.set(activeSessionId, updatedSession);
        savePersistedSessions(next);
        return next;
      });
    },
    [activeSessionId],
  );

  const updateActiveSelection = useCallback((uris: string[]) => {
    setSessions(prev => {
      if (!activeSessionId) return prev;
      const session = prev.get(activeSessionId);
      if (!session) return prev;
      const existing = session.selectedUris || [];
      if (existing.length === uris.length && existing.every((u, i) => u === uris[i])) return prev;
      const next = new Map(prev);
      next.set(activeSessionId, { ...session, selectedUris: uris.length > 0 ? uris : undefined });
      savePersistedSessions(next);
      return next;
    });
  }, [activeSessionId]);

  // ── Session list for UI ──────────────────────────────────────────────

  const sessionList: SessionSummary[] = useMemo(() => {
    const list: SessionSummary[] = [];
    for (const s of sessions.values()) {
      list.push({
        id: s.id,
        name: s.name,
        spaceId: s.spaceId,
        nodeCount: s.dataGraph.entities.size + s.dataGraph.documents.size,
        edgeCount: s.dataGraph.frames.size + s.dataGraph.edges.size,
        updatedAt: s.updatedAt,
      });
    }
    return list.sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime());
  }, [sessions]);

  return {
    sessions,
    activeSessionId,
    activeSession,
    activeViewGraph,
    sessionList,

    // Session CRUD
    createSession,
    deleteSession,
    renameSession,
    duplicateSession,
    switchSession,
    updateSessionSpace,

    // DataGraph mutation
    updateActiveDataGraph,

    // Selection
    updateActiveSelection,
  };
}
