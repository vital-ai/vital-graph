// ---------------------------------------------------------------------------
// Layout Options Builder
//
// Translates a LayoutConfig into Cytoscape layout options object.
// See: planning/planning_visualization/graph_layout_algorithms_plan.md
// ---------------------------------------------------------------------------

import type { Core } from 'cytoscape';
import type { LayoutConfig } from './graphTypes';

const LANE_PREFIX = '__timeline_lane_';

/** Remove any virtual lane parents from a previous event-timeline layout */
function cleanupLaneParents(cy: Core): void {
  const laneNodes = cy.nodes().filter(n => n.id().startsWith(LANE_PREFIX));
  if (laneNodes.length === 0) return;
  // Un-parent all children first
  cy.nodes().forEach(n => {
    if (!n.id().startsWith(LANE_PREFIX) && n.data('parent')?.startsWith(LANE_PREFIX)) {
      n.move({ parent: null });
    }
  });
  laneNodes.remove();
}

export function buildLayoutOptions(config: LayoutConfig, nodeCount: number = 0, _cy?: Core): Record<string, unknown> {
  // Clean up lane parents when switching away from event-timeline
  if (_cy && config.algorithm !== 'event-timeline') {
    cleanupLaneParents(_cy);
  }

  const shouldAnimate = config.animate && nodeCount < 500;
  const base = {
    animate: shouldAnimate,
    animationDuration: config.animationDuration,
    fit: false,
    padding: 20,
  };

  switch (config.algorithm) {
    case 'cose-bilkent':
      return {
        name: 'cose-bilkent',
        ...base,
        nodeDimensionsIncludeLabels: true,
        idealEdgeLength: config.params.idealEdgeLength ?? 120,
        nodeRepulsion: config.params.nodeRepulsion ?? 8000,
      };

    case 'fcose':
      return {
        name: 'fcose',
        ...base,
        nodeDimensionsIncludeLabels: true,
        idealEdgeLength: config.params.idealEdgeLength ?? 120,
        nodeRepulsion: config.params.nodeRepulsion ?? 8000,
        gravity: config.params.gravity ?? 0.25,
        quality: 'default',
      };

    case 'dagre':
      return {
        name: 'dagre',
        ...base,
        rankDir: config.params.rankDir ?? 'TB',
        nodeSep: config.params.nodeSep ?? 50,
        rankSep: config.params.rankSep ?? 75,
      };

    case 'breadthfirst':
      return {
        name: 'breadthfirst',
        ...base,
        directed: true,
        spacingFactor: config.params.spacingFactor ?? 1.75,
      };

    case 'circle':
      return {
        name: 'circle',
        ...base,
      };

    case 'cola':
      return {
        name: 'cola',
        ...base,
        nodeSpacing: config.params.nodeSpacing ?? 30,
        edgeLength: config.params.edgeLength ?? 120,
        convergenceThreshold: 0.01,
        maxSimulationTime: config.params.maxSimulationTime ?? 4000,
        infinite: false,
      };

    case 'elk-stress':
      return {
        name: 'elk',
        ...base,
        elk: {
          algorithm: 'stress',
          'stress.desiredEdgeLength': config.params.desiredEdgeLength ?? 120,
          'nodePlacement.strategy': 'SIMPLE',
        },
      };

    case 'elk-layered':
      return {
        name: 'elk',
        ...base,
        elk: {
          algorithm: 'layered',
          'elk.direction': config.params.elkDirection ?? 'DOWN',
          'spacing.nodeNode': config.params.nodeSpacing ?? 50,
          'layered.spacing.nodeNodeBetweenLayers': config.params.layerSpacing ?? 75,
        },
      };

    case 'concentric':
      return {
        name: 'concentric',
        ...base,
        minNodeSpacing: config.params.minNodeSpacing ?? 50,
        concentric: (node: { degree: () => number }) => node.degree(),
        levelWidth: () => 2,
      };

    case 'grid':
      return {
        name: 'grid',
        ...base,
        condense: true,
      };

    case 'event-timeline': {
      // Deterministic timeline layout:
      // - Events flow L→R, backbone at bottom (lane 0)
      // - Branches go UP one laneHeight per fork
      // - Refs above highest event lane by one laneHeight, at X of source event
      // - No leftward edges (guaranteed by topological rank)
      if (!_cy || _cy.nodes().length === 0) {
        return { name: 'preset', ...base, positions: () => ({ x: 0, y: 0 }) };
      }
      const cy = _cy;
      cleanupLaneParents(cy);

      const xSpacing = (config.params.xSpacing as number) ?? 180;
      const laneHeight = (config.params.laneHeight as number) ?? 140;

      // Identify event (backbone) nodes
      const isEventNode = (n: ReturnType<typeof cy.nodes>[0]) => {
        const nt = n.data('nodeType');
        if (nt !== 'entity' && nt !== 'kgtype') return false;
        const typeDesc: string = n.data('entityType') || '';
        return typeDesc.toLowerCase().includes('event');
      };

      const eventNodeIds = new Set<string>();
      cy.nodes().forEach(n => { if (isEventNode(n)) eventNodeIds.add(n.id()); });

      // Build adjacency (event-to-event edges only)
      const adjOut = new Map<string, string[]>();
      const adjIn = new Map<string, string[]>();
      for (const id of eventNodeIds) { adjOut.set(id, []); adjIn.set(id, []); }
      cy.edges().forEach(edge => {
        const s = edge.source().id(), t = edge.target().id();
        if (eventNodeIds.has(s) && eventNodeIds.has(t)) {
          adjOut.get(s)!.push(t);
          adjIn.get(t)!.push(s);
        }
      });

      // BFS lane assignment: first child inherits lane, extra children fork UP
      const sources = [...eventNodeIds].filter(id => adjIn.get(id)!.length === 0);
      const lane = new Map<string, number>();
      let nextLane = 0;
      const bfsQ: { id: string; l: number }[] = [];
      for (const s of sources) {
        if (!lane.has(s)) { lane.set(s, nextLane); bfsQ.push({ id: s, l: nextLane }); nextLane++; }
      }
      if (bfsQ.length === 0 && eventNodeIds.size > 0) {
        const first = [...eventNodeIds][0];
        lane.set(first, 0); bfsQ.push({ id: first, l: 0 }); nextLane = 1;
      }
      while (bfsQ.length > 0) {
        const { id, l } = bfsQ.shift()!;
        const children = adjOut.get(id) || [];
        let isFirst = true;
        for (const child of children) {
          if (lane.has(child)) continue;
          if (isFirst) {
            lane.set(child, l); bfsQ.push({ id: child, l }); isFirst = false;
          } else {
            lane.set(child, nextLane); bfsQ.push({ id: child, l: nextLane }); nextLane++;
          }
        }
      }

      // Topological rank for L→R ordering (rank = max predecessor rank + 1)
      const rank = new Map<string, number>();
      const computeRank = (nodeId: string): number => {
        if (rank.has(nodeId)) return rank.get(nodeId)!;
        const preds = adjIn.get(nodeId) || [];
        if (preds.length === 0) { rank.set(nodeId, 0); return 0; }
        let maxR = 0;
        for (const p of preds) maxR = Math.max(maxR, computeRank(p) + 1);
        rank.set(nodeId, maxR);
        return maxR;
      };
      for (const id of eventNodeIds) computeRank(id);

      // Find max event lane for ref positioning
      let maxEventLane = 0;
      for (const l of lane.values()) maxEventLane = Math.max(maxEventLane, l);

      // Compute all positions
      const positions = new Map<string, { x: number; y: number }>();

      // Event positions: X = rank * xSpacing, Y = -lane * laneHeight (lane 0 bottom, higher lanes up)
      for (const id of eventNodeIds) {
        positions.set(id, {
          x: (rank.get(id) ?? 0) * xSpacing,
          y: -(lane.get(id) ?? 0) * laneHeight,
        });
      }

      // Reference positions: Y = one laneHeight above highest event lane
      // X = above their source event, shifted right for multiples
      const refY = -(maxEventLane + 1) * laneHeight;
      const refXSpread = 70;
      const eventRefCount = new Map<string, number>();

      cy.nodes().forEach(n => {
        if (eventNodeIds.has(n.id())) return;
        const connEvents = n.neighborhood('node').filter(
          (nn: ReturnType<typeof cy.nodes>[0]) => eventNodeIds.has(nn.id())
        );
        if (connEvents.length > 0) {
          // Find rightmost connected event as anchor so no edges point leftward
          let anchorId = connEvents[0].id();
          let anchorX = positions.get(anchorId)?.x ?? 0;
          connEvents.forEach((ev: ReturnType<typeof cy.nodes>[0]) => {
            const ex = positions.get(ev.id())?.x ?? 0;
            if (ex > anchorX) { anchorX = ex; anchorId = ev.id(); }
          });
          const idx = eventRefCount.get(anchorId) ?? 0;
          eventRefCount.set(anchorId, idx + 1);
          positions.set(n.id(), { x: anchorX + idx * refXSpread, y: refY });
        } else {
          positions.set(n.id(), { x: 0, y: refY });
        }
      });

      return {
        name: 'preset',
        ...base,
        animate: false,
        positions: (node: { data: (key: string) => string }) => {
          return positions.get(node.data('id')) || { x: 0, y: 0 };
        },
      };
    }

    default:
      return { name: config.algorithm, ...base };
  }
}
