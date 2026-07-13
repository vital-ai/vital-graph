import React, { useState, useMemo } from 'react';
import { getSessionsForSpace, prepareVisualization } from '../hooks/useGraphSessionStore';

interface Props {
  spaceId: string;
  entityUri: string;
  navigate: (path: string) => void;
}

const GraphIcon = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <circle cx="8" cy="8" r="3" strokeWidth="1.5" />
    <circle cx="16" cy="16" r="3" strokeWidth="1.5" />
    <circle cx="18" cy="6" r="2" strokeWidth="1.5" />
    <line x1="10.5" y1="9.5" x2="14" y2="14" strokeWidth="1.5" />
    <line x1="16.5" y1="7.5" x2="17" y2="13.5" strokeWidth="1.5" />
  </svg>
);

export const VisualizeInGraphButton: React.FC<Props> = ({ spaceId, entityUri, navigate }) => {
  const [menuOpen, setMenuOpen] = useState(false);

  const matchingSessions = useMemo(
    () => getSessionsForSpace(spaceId, entityUri),
    [spaceId, entityUri],
  );

  const handleNewSession = () => {
    const sessionId = prepareVisualization(spaceId, entityUri);
    navigate(`/visualization?session=${encodeURIComponent(sessionId)}`);
    setMenuOpen(false);
  };

  const handleExistingSession = (sessionId: string) => {
    const targetId = prepareVisualization(spaceId, entityUri, sessionId);
    navigate(`/visualization?session=${encodeURIComponent(targetId)}`);
    setMenuOpen(false);
  };

  if (matchingSessions.length === 0) {
    // No existing sessions — create new on click
    return (
      <div className="mt-4">
        <button
          onClick={handleNewSession}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 dark:text-indigo-300 dark:bg-indigo-900/30 dark:hover:bg-indigo-900/50 rounded-lg transition-colors"
        >
          <GraphIcon />
          Visualize in Graph
        </button>
      </div>
    );
  }

  // 1+ matching sessions — show dropdown with existing + new option
  return (
    <div className="mt-4 relative inline-block">
      <button
        onClick={() => setMenuOpen(o => !o)}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 dark:text-indigo-300 dark:bg-indigo-900/30 dark:hover:bg-indigo-900/50 rounded-lg transition-colors"
      >
        <GraphIcon />
        Visualize in Graph
        <svg className={`w-3 h-3 transition-transform ${menuOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {menuOpen && (
        <>
          {/* Click-away backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-20 w-64 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg overflow-hidden">
            <div className="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider border-b border-gray-100 dark:border-gray-700">
              Open in existing session
            </div>
            <div className="max-h-48 overflow-y-auto">
              {matchingSessions.map(s => (
                <button
                  key={s.id}
                  onClick={() => handleExistingSession(s.id)}
                  className="w-full text-left px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 flex items-center justify-between gap-2 transition-colors"
                >
                  <span className="flex items-center gap-1.5 truncate">
                    {s.containsUri && (
                      <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" title="Already in session" />
                    )}
                    <span className="font-medium truncate">{s.name}</span>
                  </span>
                  <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">
                    {new Date(s.updatedAt).toLocaleDateString()}
                  </span>
                </button>
              ))}
            </div>
            <div className="border-t border-gray-100 dark:border-gray-700">
              <button
                onClick={handleNewSession}
                className="w-full text-left px-3 py-2 text-sm text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 font-medium transition-colors"
              >
                + New session
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default VisualizeInGraphButton;
