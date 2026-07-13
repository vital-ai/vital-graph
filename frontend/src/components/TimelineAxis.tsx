import { useEffect, useState, useCallback, useRef } from 'react';
import type { Core } from 'cytoscape';

// ---------------------------------------------------------------------------
// TimelineAxis — Renders a time ruler overlay at the bottom of the Cytoscape
// canvas, showing timestamps aligned with event nodes.
//
// Timestamps are pre-extracted by the visualization hook via a SPARQL query
// that properly traverses: entity → Edge_hasEntityKGFrame → frame →
// Edge_hasKGSlot → slot (KGDateTimeSlot) → hasDateTimeSlotValue.
// ---------------------------------------------------------------------------

interface TimelineTick {
  screenX: number;
  label: string;
  sublabel?: string;
}

interface TimelineAxisProps {
  cy: Core | null;
  /** Map from entity URI → ISO datetime string, extracted via entity graph traversal */
  eventTimestamps: Map<string, string>;
  visible: boolean;
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatRelative(date: Date, baseDate: Date): string {
  const diffMs = date.getTime() - baseDate.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `+${diffSec}s`;
  const mins = Math.floor(diffSec / 60);
  const secs = diffSec % 60;
  return secs > 0 ? `+${mins}m ${secs}s` : `+${mins}m`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TimelineAxis({ cy, eventTimestamps, visible }: TimelineAxisProps) {
  const [ticks, setTicks] = useState<TimelineTick[]>([]);
  const rafRef = useRef<number | null>(null);

  const computeTicks = useCallback(() => {
    if (!cy || !visible || eventTimestamps.size === 0) { setTicks([]); return; }

    // Get event nodes that have timestamps (matched by URI)
    const eventNodes = cy.nodes().filter(n => eventTimestamps.has(n.id()));
    if (eventNodes.length === 0) { setTicks([]); return; }

    // Parse timestamps and find base date (earliest)
    let baseDate: Date | null = null;
    const parsed = new Map<string, Date>();
    eventNodes.forEach(n => {
      const isoStr = eventTimestamps.get(n.id())!;
      const date = new Date(isoStr);
      if (!isNaN(date.getTime())) {
        parsed.set(n.id(), date);
        if (!baseDate || date < baseDate) baseDate = date;
      }
    });

    if (parsed.size === 0) { setTicks([]); return; }

    // Compute screen positions
    const containerBB = cy.container()?.getBoundingClientRect();
    if (!containerBB) { setTicks([]); return; }

    const newTicks: TimelineTick[] = [];
    eventNodes.forEach(n => {
      const ts = parsed.get(n.id());
      if (!ts) return;
      const rp = n.renderedPosition();
      newTicks.push({
        screenX: rp.x,
        label: formatTime(ts),
        sublabel: baseDate ? formatRelative(ts, baseDate) : undefined,
      });
    });

    // Sort by X and deduplicate close ticks (within 40px)
    newTicks.sort((a, b) => a.screenX - b.screenX);
    const filtered: TimelineTick[] = [];
    for (const tick of newTicks) {
      if (filtered.length === 0 || tick.screenX - filtered[filtered.length - 1].screenX > 40) {
        filtered.push(tick);
      }
    }

    setTicks(filtered);
  }, [cy, eventTimestamps, visible]);

  useEffect(() => {
    if (!cy || !visible) { setTicks([]); return; }

    const handleViewport = () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(computeTicks);
    };

    // Initial compute
    computeTicks();

    // Delayed recompute — covers case where layout runs in a setTimeout
    // after this effect registers (preset layout positions nodes then emits layoutstop)
    const delayedId = setTimeout(handleViewport, 150);

    // Listen to viewport changes, layout completion, and node position/structure changes
    cy.on('viewport resize', handleViewport);
    cy.on('layoutstop', handleViewport);
    cy.on('position', handleViewport);
    cy.on('add remove', handleViewport);

    return () => {
      clearTimeout(delayedId);
      cy.off('viewport resize', handleViewport);
      cy.off('layoutstop', handleViewport);
      cy.off('position', handleViewport);
      cy.off('add remove', handleViewport);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [cy, visible, computeTicks]);

  if (!visible || ticks.length === 0) return null;

  return (
    <div className="absolute bottom-0 left-0 right-0 h-10 pointer-events-none z-10 overflow-hidden">
      {/* Axis line */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gray-300 dark:bg-gray-600" />
      {/* Ticks */}
      {ticks.map((tick, i) => (
        <div
          key={i}
          className="absolute top-0 flex flex-col items-center"
          style={{ left: `${tick.screenX}px`, transform: 'translateX(-50%)' }}
        >
          <div className="w-px h-2 bg-gray-400 dark:bg-gray-500" />
          <span className="text-[9px] text-gray-600 dark:text-gray-400 whitespace-nowrap mt-0.5 font-mono">
            {tick.label}
          </span>
          {tick.sublabel && (
            <span className="text-[8px] text-gray-400 dark:text-gray-500 whitespace-nowrap font-mono">
              {tick.sublabel}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
