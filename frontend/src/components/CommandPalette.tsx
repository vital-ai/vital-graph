import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  HiHome,
  HiViewBoards,
  HiDatabase,
  HiSearch,
  HiCube,
  HiCog,
  HiDocumentDuplicate,
  HiUserGroup,
  HiKey,
  HiUpload,
  HiDownload,
} from 'react-icons/hi';
import GraphIcon from './icons/GraphIcon';

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: React.ReactNode;
  path: string;
  keywords?: string[];
}

const COMMANDS: CommandItem[] = [
  { id: 'home', label: 'Home', description: 'Dashboard', icon: <HiHome className="w-5 h-5" />, path: '/', keywords: ['dashboard'] },
  { id: 'spaces', label: 'Spaces', description: 'Manage spaces', icon: <HiViewBoards className="w-5 h-5" />, path: '/spaces', keywords: ['namespace'] },
  { id: 'graphs', label: 'Graphs', description: 'Named graphs', icon: <GraphIcon className="w-5 h-5" />, path: '/graphs', keywords: ['named'] },
  { id: 'objects', label: 'Objects', description: 'Knowledge Graph objects', icon: <HiCube className="w-5 h-5" />, path: '/objects', keywords: ['entities', 'frames'] },
  { id: 'kgdocuments', label: 'KG Documents', description: 'Knowledge Graph documents & segments', icon: <HiDocumentDuplicate className="w-5 h-5" />, path: '/objects/kgdocuments', keywords: ['documents', 'segmentation', 'kgdocument', 'segments', 'content'] },
  { id: 'triples', label: 'Triples', description: 'RDF statements', icon: <HiDatabase className="w-5 h-5" />, path: '/triples', keywords: ['rdf', 'quads'] },
  { id: 'files', label: 'Files', description: 'Manage files', icon: <HiDocumentDuplicate className="w-5 h-5" />, path: '/files', keywords: ['documents', 'upload'] },
  { id: 'sparql', label: 'SPARQL', description: 'Query editor', icon: <HiSearch className="w-5 h-5" />, path: '/sparql', keywords: ['query', 'sql'] },
  { id: 'import', label: 'Data Import', description: 'Import data', icon: <HiUpload className="w-5 h-5" />, path: '/data/import', keywords: ['upload', 'load'] },
  { id: 'export', label: 'Data Export', description: 'Export data', icon: <HiDownload className="w-5 h-5" />, path: '/data/export', keywords: ['download', 'backup'] },
  { id: 'vector-search', label: 'Vector Search', description: 'Semantic search', icon: <HiSearch className="w-5 h-5" />, path: '/vector-search', keywords: ['semantic', 'embedding'] },
  { id: 'vector-indexes', label: 'Vector Indexes', description: 'Manage indexes', icon: <HiCube className="w-5 h-5" />, path: '/vector-indexes', keywords: ['weaviate'] },
  { id: 'users', label: 'Users', description: 'User management', icon: <HiUserGroup className="w-5 h-5" />, path: '/users', keywords: ['accounts'] },
  { id: 'api-keys', label: 'API Keys', description: 'Manage API keys', icon: <HiKey className="w-5 h-5" />, path: '/api-keys', keywords: ['token', 'auth'] },
  { id: 'admin', label: 'Administration', description: 'System admin', icon: <HiCog className="w-5 h-5" />, path: '/admin', keywords: ['system', 'health', 'resync'] },
];

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const filtered = useMemo(() => {
    if (!query.trim()) return COMMANDS;
    const q = query.toLowerCase();
    return COMMANDS.filter(
      (cmd) =>
        cmd.label.toLowerCase().includes(q) ||
        (cmd.description || '').toLowerCase().includes(q) ||
        (cmd.keywords || []).some((k) => k.includes(q))
    );
  }, [query]);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [filtered.length]);

  const handleSelect = (item: CommandItem) => {
    onClose();
    navigate(item.path);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && filtered[selectedIndex]) {
      e.preventDefault();
      handleSelect(filtered[selectedIndex]);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh]" role="dialog" aria-modal="true" aria-label="Command palette">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />

      {/* Palette */}
      <div className="relative w-full max-w-lg mx-4 bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Search Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <HiSearch className="w-5 h-5 text-gray-400 flex-shrink-0" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search pages..."
            aria-label="Search pages"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 bg-transparent border-none outline-none text-gray-900 dark:text-white placeholder-gray-400 text-sm focus:ring-0"
          />
          <kbd className="hidden sm:inline-flex items-center px-2 py-0.5 text-xs font-mono text-gray-400 bg-gray-100 dark:bg-gray-700 rounded">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-72 overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
              No results for &quot;{query}&quot;
            </div>
          ) : (
            filtered.map((item, idx) => (
              <button
                key={item.id}
                onClick={() => handleSelect(item)}
                onMouseEnter={() => setSelectedIndex(idx)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                  idx === selectedIndex
                    ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50'
                }`}
              >
                <span className="flex-shrink-0 text-gray-400">{item.icon}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{item.label}</p>
                  {item.description && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{item.description}</p>
                  )}
                </div>
              </button>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-400">
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded font-mono">↑↓</kbd>
            navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded font-mono">↵</kbd>
            select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded font-mono">esc</kbd>
            close
          </span>
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;
