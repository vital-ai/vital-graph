import React, { useState, useCallback, useEffect } from 'react';
import { TextInput, Button, Badge, Select, Spinner } from 'flowbite-react';
import { HiPlus, HiX, HiArrowUp, HiArrowDown } from 'react-icons/hi';
import { apiService } from '../services/ApiService';

/** Well-known properties available for search text building */
const COMMON_PROPERTIES: { uri: string; label: string }[] = [
  { uri: 'http://vital.ai/ontology/vital-core#hasName', label: 'hasName' },
  { uri: 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription', label: 'hasKGraphDescription' },
  { uri: 'http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue', label: 'hasTextSlotValue' },
  { uri: 'http://vital.ai/ontology/haley-ai-kg#hasKGEntityType', label: 'hasKGEntityType' },
  { uri: 'http://vital.ai/ontology/haley-ai-kg#hasKGFrameType', label: 'hasKGFrameType' },
  { uri: 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType', label: 'hasKGSlotType' },
  { uri: 'http://vital.ai/ontology/vital-core#hasDescription', label: 'hasDescription' },
  { uri: 'http://vital.ai/ontology/haley-ai-kg#hasKGEntityName', label: 'hasKGEntityName' },
];

export type PropertyRole = 'primary_name' | 'alias';

export interface SelectedProperty {
  uri: string;
  role?: PropertyRole;
}

interface PropertySelectorProps {
  /** Currently selected properties (ordered) */
  selected: SelectedProperty[];
  /** Called when selection changes */
  onChange: (properties: SelectedProperty[]) => void;
  /** Whether to show role assignment (for Fuzzy mappings) */
  showRoles?: boolean;
  /** Source mode: 'properties' = explicit list, 'default' = all */
  sourceMode: 'properties' | 'default';
  /** Called when source mode changes */
  onSourceModeChange: (mode: 'properties' | 'default') => void;
  /** Optional class URI to fetch dynamic properties from the ontology endpoint */
  classUri?: string;
}

/**
 * Property selector for search mappings.
 * Lets users choose which properties to include in search text.
 */
const PropertySelector: React.FC<PropertySelectorProps> = ({
  selected,
  onChange,
  showRoles = false,
  sourceMode,
  onSourceModeChange,
  classUri,
}) => {
  const [customUri, setCustomUri] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [dynamicProperties, setDynamicProperties] = useState<{ uri: string; label: string }[] | null>(null);
  const [loadingProps, setLoadingProps] = useState(false);

  // Fetch dynamic properties when classUri changes
  useEffect(() => {
    if (!classUri) {
      setDynamicProperties(null);
      return;
    }
    let cancelled = false;
    const fetchProps = async () => {
      setLoadingProps(true);
      try {
        const properties = await apiService.getOntologyProperties(classUri);
        if (!cancelled) {
          setDynamicProperties(
            properties.map((p) => ({
              uri: p.uri,
              label: p.local_name || p.short_name || p.uri.split('#').pop() || p.uri,
            }))
          );
        }
      } catch {
        if (!cancelled) setDynamicProperties(null);
      } finally {
        if (!cancelled) setLoadingProps(false);
      }
    };
    fetchProps();
    return () => { cancelled = true; };
  }, [classUri]);

  const addProperty = useCallback((uri: string) => {
    if (!selected.find((p) => p.uri === uri)) {
      onChange([...selected, { uri, role: showRoles ? 'primary_name' : undefined }]);
    }
    setCustomUri('');
    setShowDropdown(false);
  }, [selected, onChange, showRoles]);

  const removeProperty = useCallback((uri: string) => {
    onChange(selected.filter((p) => p.uri !== uri));
  }, [selected, onChange]);

  const moveUp = useCallback((index: number) => {
    if (index === 0) return;
    const newList = [...selected];
    [newList[index - 1], newList[index]] = [newList[index], newList[index - 1]];
    onChange(newList);
  }, [selected, onChange]);

  const moveDown = useCallback((index: number) => {
    if (index >= selected.length - 1) return;
    const newList = [...selected];
    [newList[index], newList[index + 1]] = [newList[index + 1], newList[index]];
    onChange(newList);
  }, [selected, onChange]);

  const setRole = useCallback((index: number, role: PropertyRole) => {
    const newList = [...selected];
    newList[index] = { ...newList[index], role };
    onChange(newList);
  }, [selected, onChange]);

  const getLabel = (uri: string) => {
    const common = COMMON_PROPERTIES.find((p) => p.uri === uri);
    return common?.label || uri.split('#').pop() || uri;
  };

  const propertyList = dynamicProperties || COMMON_PROPERTIES;
  const availableProperties = propertyList.filter(
    (p) => !selected.find((s) => s.uri === p.uri)
  );

  return (
    <div className="space-y-3">
      {/* Source mode toggle */}
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="sourceMode"
            checked={sourceMode === 'properties'}
            onChange={() => onSourceModeChange('properties')}
            className="text-blue-600"
          />
          <span className="text-sm">Selected properties</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="sourceMode"
            checked={sourceMode === 'default'}
            onChange={() => onSourceModeChange('default')}
            className="text-blue-600"
          />
          <span className="text-sm">All (default)</span>
        </label>
      </div>

      {/* Property list (only if source mode is 'properties') */}
      {sourceMode === 'properties' && (
        <>
          {/* Selected properties (ordered) */}
          {selected.length > 0 && (
            <div className="space-y-1">
              {selected.map((prop, idx) => (
                <div
                  key={prop.uri}
                  className="flex items-center gap-2 px-2 py-1.5 bg-gray-50 dark:bg-gray-700 rounded"
                >
                  <span className="text-xs text-gray-400 w-4">{idx + 1}.</span>
                  <Badge color="blue" className="flex-shrink-0">
                    {getLabel(prop.uri)}
                  </Badge>
                  <span className="text-xs text-gray-400 truncate flex-1" title={prop.uri}>
                    {prop.uri}
                  </span>
                  {showRoles && (
                    <Select
                      sizing="sm"
                      value={prop.role || 'primary_name'}
                      onChange={(e) => setRole(idx, e.target.value as PropertyRole)}
                      className="w-32"
                    >
                      <option value="primary_name">primary_name</option>
                      <option value="alias">alias</option>
                    </Select>
                  )}
                  <div className="flex gap-0.5">
                    <button
                      onClick={() => moveUp(idx)}
                      disabled={idx === 0}
                      className="p-0.5 text-gray-400 hover:text-gray-700 disabled:opacity-30"
                      type="button"
                    >
                      <HiArrowUp className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => moveDown(idx)}
                      disabled={idx === selected.length - 1}
                      className="p-0.5 text-gray-400 hover:text-gray-700 disabled:opacity-30"
                      type="button"
                    >
                      <HiArrowDown className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => removeProperty(prop.uri)}
                      className="p-0.5 text-red-400 hover:text-red-600"
                      type="button"
                    >
                      <HiX className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Add property */}
          {loadingProps && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Spinner size="sm" /> Loading properties...
            </div>
          )}
          <div className="relative">
            <div className="flex gap-2">
              <TextInput
                sizing="sm"
                value={customUri}
                onChange={(e) => {
                  setCustomUri(e.target.value);
                  setShowDropdown(true);
                }}
                onFocus={() => setShowDropdown(true)}
                placeholder="Add property URI..."
                className="flex-1"
              />
              <Button
                size="xs"
                color="gray"
                onClick={() => {
                  if (customUri.trim()) addProperty(customUri.trim());
                }}
                disabled={!customUri.trim()}
              >
                <HiPlus className="h-3 w-3" />
              </Button>
            </div>

            {/* Quick-pick dropdown */}
            {showDropdown && availableProperties.length > 0 && (
              <div className="absolute z-40 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {availableProperties
                  .filter((p) =>
                    !customUri || p.label.toLowerCase().includes(customUri.toLowerCase()) ||
                    p.uri.toLowerCase().includes(customUri.toLowerCase())
                  )
                  .map((p) => (
                    <button
                      key={p.uri}
                      onClick={() => addProperty(p.uri)}
                      className="w-full text-left px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 text-sm"
                      type="button"
                    >
                      <span className="font-medium">{p.label}</span>
                      <span className="text-xs text-gray-400 ml-2">{p.uri}</span>
                    </button>
                  ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default PropertySelector;
