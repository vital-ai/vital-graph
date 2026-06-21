import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { TextInput, Checkbox, Spinner, Badge } from 'flowbite-react';
import { HiX, HiSearch } from 'react-icons/hi';
import { apiService } from '../services/ApiService';

const ITEM_HEIGHT = 44; // px per item row
const VISIBLE_COUNT = 50; // items to render at a time
const BUFFER = 10; // extra items above/below viewport

interface KGTypeItem {
  uri: string;
  name: string;
}

const SP_KG_TYPES = 'sp_kg_types';

interface TypeURIPickerProps {
  /** @deprecated Ignored — types always come from the centralized sp_kg_types space */
  spaceId?: string;
  /** KG Type class to filter by (e.g. KGEntityType, KGFrameType) */
  typeFilter?: string;
  /** Currently selected URIs */
  selected: string[];
  /** Called when selection changes */
  onChange: (uris: string[]) => void;
  /** Placeholder text */
  placeholder?: string;
}

/** Mapping from mapping_type to the KG Type class URI used for filtering */
export const MAPPING_TYPE_TO_KG_CLASS: Record<string, string> = {
  kgentity: 'http://vital.ai/ontology/haley-ai-kg#KGEntityType',
  kgdocument: 'http://vital.ai/ontology/haley-ai-kg#KGDocumentType',
  kgframe: 'http://vital.ai/ontology/haley-ai-kg#KGFrameType',
  kgtype: 'http://vital.ai/ontology/haley-ai-kg#KGType',
};

/**
 * Windowed list sub-component for rendering large item lists efficiently.
 * Only renders items visible in the scroll viewport plus a buffer.
 */
const VirtualizedTypeList: React.FC<{
  items: KGTypeItem[];
  selected: string[];
  onToggle: (uri: string) => void;
}> = ({ items, selected, onToggle }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);

  const totalHeight = items.length * ITEM_HEIGHT;
  const startIdx = Math.max(0, Math.floor(scrollTop / ITEM_HEIGHT) - BUFFER);
  const endIdx = Math.min(items.length, startIdx + VISIBLE_COUNT + BUFFER * 2);
  const visibleItems = useMemo(() => items.slice(startIdx, endIdx), [items, startIdx, endIdx]);

  const handleScroll = useCallback(() => {
    if (scrollRef.current) {
      setScrollTop(scrollRef.current.scrollTop);
    }
  }, []);

  // For small lists (<= VISIBLE_COUNT), skip virtualization entirely
  if (items.length <= VISIBLE_COUNT) {
    return (
      <>
        {items.map((t) => (
          <label
            key={t.uri}
            className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
          >
            <Checkbox
              checked={selected.includes(t.uri)}
              onChange={() => onToggle(t.uri)}
            />
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium truncate">{t.name}</span>
              <span className="text-xs text-gray-400 truncate">{t.uri}</span>
            </div>
          </label>
        ))}
      </>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="max-h-60 overflow-y-auto"
    >
      <div style={{ height: totalHeight, position: 'relative' }}>
        <div style={{ position: 'absolute', top: startIdx * ITEM_HEIGHT, width: '100%' }}>
          {visibleItems.map((t) => (
            <label
              key={t.uri}
              className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              style={{ height: ITEM_HEIGHT }}
            >
              <Checkbox
                checked={selected.includes(t.uri)}
                onChange={() => onToggle(t.uri)}
              />
              <div className="flex flex-col min-w-0">
                <span className="text-sm font-medium truncate">{t.name}</span>
                <span className="text-xs text-gray-400 truncate">{t.uri}</span>
              </div>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
};

/**
 * Searchable multi-select picker for KG Type URIs.
 * Loads types from the API filtered by the given KG Type class.
 */
const TypeURIPicker: React.FC<TypeURIPickerProps> = ({
  spaceId: _spaceId,
  typeFilter,
  selected,
  onChange,
  placeholder = 'Search types...',
}) => {
  void _spaceId; // deprecated — always uses sp_kg_types
  const [types, setTypes] = useState<KGTypeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Load types from the centralized sp_kg_types space
  useEffect(() => {
    const loadTypes = async () => {
      setLoading(true);
      try {
        const resp = await apiService.getKGTypes(SP_KG_TYPES, {
          page_size: 200,
          type_uri: typeFilter,
        });
        // Response has .types array of GraphObjects with URI and name
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const items: KGTypeItem[] = (resp?.types || []).map((t: any) => ({
          uri: t.URI || t.uri || '',
          name: t.name || t.URI?.split('#').pop() || '?',
        }));
        setTypes(items);
      } catch {
        setTypes([]);
      } finally {
        setLoading(false);
      }
    };
    loadTypes();
  }, [typeFilter]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const filteredTypes = types.filter((t) =>
    t.name.toLowerCase().includes(searchText.toLowerCase()) ||
    t.uri.toLowerCase().includes(searchText.toLowerCase())
  );

  const toggleType = useCallback((uri: string) => {
    if (selected.includes(uri)) {
      onChange(selected.filter((u) => u !== uri));
    } else {
      onChange([...selected, uri]);
    }
  }, [selected, onChange]);

  const removeType = useCallback((uri: string) => {
    onChange(selected.filter((u) => u !== uri));
  }, [selected, onChange]);

  const selectAll = useCallback(() => {
    onChange(filteredTypes.map((t) => t.uri));
  }, [filteredTypes, onChange]);

  const clearAll = useCallback(() => {
    onChange([]);
  }, [onChange]);

  // Get name for a URI
  const getName = (uri: string) => {
    const t = types.find((x) => x.uri === uri);
    return t?.name || uri.split('#').pop() || uri;
  };

  return (
    <div ref={containerRef} className="relative">
      {/* Selected chips */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {selected.map((uri) => (
            <Badge key={uri} color="blue" className="flex items-center gap-1">
              <span className="text-xs">{getName(uri)}</span>
              <button
                onClick={() => removeType(uri)}
                className="ml-1 hover:text-red-500"
                type="button"
              >
                <HiX className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* Search input */}
      <div className="relative">
        <TextInput
          icon={HiSearch}
          value={searchText}
          onChange={(e) => {
            setSearchText(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder={placeholder}
          sizing="sm"
        />
        {loading && (
          <div className="absolute right-2 top-2">
            <Spinner size="sm" />
          </div>
        )}
      </div>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute z-50 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg max-h-64 overflow-hidden">
          {/* Actions bar */}
          <div className="flex justify-between px-3 py-1.5 border-b border-gray-100 dark:border-gray-700 text-xs">
            <button
              onClick={selectAll}
              className="text-blue-600 hover:underline"
              type="button"
            >
              Select All ({filteredTypes.length})
            </button>
            <button
              onClick={clearAll}
              className="text-gray-500 hover:underline"
              type="button"
            >
              Clear All
            </button>
          </div>

          {/* Type list (virtualized for large counts) */}
          {filteredTypes.length === 0 ? (
            <div className="px-3 py-2 text-sm text-gray-500">
              {loading ? 'Loading...' : 'No types found'}
            </div>
          ) : (
            <VirtualizedTypeList
              items={filteredTypes}
              selected={selected}
              onToggle={toggleType}
            />
          )}
        </div>
      )}

      {/* Summary */}
      {selected.length > 0 && (
        <p className="text-xs text-gray-500 mt-1">
          {selected.length} type{selected.length !== 1 ? 's' : ''} selected
          {selected.length === 0 && ' (all subjects will be indexed)'}
        </p>
      )}
      {selected.length === 0 && types.length > 0 && (
        <p className="text-xs text-gray-400 mt-1">
          No filter — all subjects of this object type will be indexed
        </p>
      )}
    </div>
  );
};

export default TypeURIPicker;
