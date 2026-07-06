import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Badge } from 'flowbite-react';
import {
  stripBrackets,
  parseObjectTerm,
  shortenUri,
  RDF_TYPE,
  type Quad,
} from '../utils/QuadUtils';
import { formatDateTime } from '../utils/formatUtils';

// Base RDF Object interface
export interface BaseRDFObject {
  id?: number;
  space_id?: string;
  graph_id?: number;
  object_uri?: string;
  object_type?: 'Node' | 'Edge';
  rdf_type?: string;
  subject?: string;
  predicate?: string;
  object?: string;
  context?: string;
  created_time?: string;
  last_modified?: string;
  properties_count?: number;
  properties?: Array<{
    predicate: string;
    object: string;
    object_type: 'uri' | 'literal';
  }>;
}

// Typed CRUD operations that delegate to the correct vgClient endpoint
export interface CrudOps {
  get(spaceId: string, graphId: string, uri: string): Promise<unknown>;
  create(spaceId: string, graphId: string, data: unknown): Promise<unknown>;
  update(spaceId: string, graphId: string, uri: string, data: unknown): Promise<unknown>;
  delete(spaceId: string, graphId: string, uri: string): Promise<unknown>;
}

// Configuration interface for different object types
export interface ObjectDetailConfig {
  objectTypeName: string;
  objectTypeColor: string;
  crudOps: CrudOps;
  listRoute: string;
  defaultRdfType: string;
  paramName: string;
  uriFieldName: string;
  icon: React.ComponentType<Record<string, unknown>>;
  graphIdRequired?: boolean; // default true; set false for endpoints that derive graph from space
  spaceIdOverride?: string;  // hardcode spaceId instead of reading from URL params
}

// Custom hook for shared object detail functionality
export function useObjectDetail<T extends BaseRDFObject = BaseRDFObject>(
  config: ObjectDetailConfig,
  createDefaultObject: () => T,
  buildApiRequestData: (object: T) => unknown
) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const params = useParams();
  
  const spaceId = config.spaceIdOverride || params.spaceId;
  const graphId = params.graphId;
  const objectId = params[config.paramName];
  const mode = searchParams.get('mode') || 'view';
  const isCreateMode = mode === 'create' || objectId === 'new';

  const [object, setObject] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showDeleteObjectModal, setShowDeleteObjectModal] = useState<boolean>(false);
  const [newProperty, setNewProperty] = useState({
    predicate: '',
    value: '',
    type: 'literal' as 'uri' | 'literal'
  });

  // Utility functions
  const extractLocalName = shortenUri;


  const getObjectTypeBadge = (type: string) => {
    const badgeConfig = type === 'Node' 
      ? { color: 'blue', text: 'Node' }
      : { color: 'green', text: 'Edge' };
    return <Badge color={badgeConfig.color}>{badgeConfig.text}</Badge>;
  };

  // Generate a random URI for new objects
  const generateUri = () => {
    const uuid = crypto.randomUUID();
    return `urn:${config.objectTypeName.toLowerCase().replace(/\s+/g, '')}:${uuid}`;
  };

  // API functions
  const fetchObject = async () => {
    if (isCreateMode) {
      const newObject = createDefaultObject();
      setObject(newObject);
      setLoading(false);
      return;
    }

    const needsGraphId = config.graphIdRequired !== false;
    if (!spaceId || (needsGraphId && !graphId) || !objectId) {
      setError('Missing required parameters');
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      
      const responseData = await config.crudOps.get(
        spaceId,
        decodeURIComponent(graphId || ''),
        decodeURIComponent(objectId),
      ) as { results?: Quad[]; total_count?: number };

      // All endpoints return QuadResponse: { results: [{s,p,o,g}], total_count }
      const quads: Quad[] = responseData.results || [];
      if (quads.length === 0) {
        setError(`${config.objectTypeName} not found`);
      } else {
        const convertedObject = convertQuadsToObject(quads);
        setObject(convertedObject);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to load ${config.objectTypeName.toLowerCase()}`);
    } finally {
      setLoading(false);
    }
  };

  const convertQuadsToObject = (quads: Quad[]): T => {
    const subjectUri = stripBrackets(quads[0].s);

    const properties: Array<{predicate: string; object: string; object_type: 'uri' | 'literal'}> = [];
    let rdfType = 'Unknown';

    for (const quad of quads) {
      const { value, type } = parseObjectTerm(quad.o);
      const pred = stripBrackets(quad.p);

      if (pred === RDF_TYPE) {
        rdfType = value;
      }

      properties.push({ predicate: pred, object: value, object_type: type });
    }

    const convertedObject: BaseRDFObject = {
      id: 0,
      space_id: spaceId || '',
      graph_id: 0,
      object_uri: subjectUri,
      object_type: rdfType.toLowerCase().includes('edge') ? 'Edge' : 'Node',
      rdf_type: rdfType,
      subject: subjectUri,
      predicate: RDF_TYPE,
      object: rdfType,
      context: decodeURIComponent(graphId || ''),
      created_time: new Date().toISOString(),
      last_modified: new Date().toISOString(),
      properties_count: properties.length,
      properties,
    };

    return convertedObject as T;
  };


  // Property management
  const updateProperty = (index: number, field: 'predicate' | 'object' | 'object_type', value: string | 'uri' | 'literal') => {
    if (!object || !object.properties) return;
    
    const updatedProperties = [...object.properties];
    updatedProperties[index] = {
      ...updatedProperties[index],
      [field]: value
    };
    
    setObject({
      ...object,
      properties: updatedProperties
    });
  };

  const removeProperty = (index: number) => {
    if (!object || !object.properties) return;
    
    const updatedProperties = object.properties.filter((_, i) => i !== index);
    setObject({
      ...object,
      properties: updatedProperties,
      properties_count: updatedProperties.length
    });
  };

  const handleAddProperty = () => {
    if (!object || !newProperty.predicate || !newProperty.value) return;
    
    const propertyToAdd = {
      predicate: newProperty.predicate,
      object: newProperty.value,
      object_type: newProperty.type
    };
    
    const updatedObject = {
      ...object,
      properties: [...(object.properties || []), propertyToAdd],
      properties_count: (object.properties?.length || 0) + 1
    };

    setObject(updatedObject);
    setNewProperty({ predicate: '', value: '', type: 'literal' });
  };

  // Mode handlers
  const handleSave = async () => {
    if (!object) return;

    try {
      setSaving(true);
      setError(null);
      // Auto-generate a URI for new objects if not provided
      const saveObject = isCreateMode && !object.object_uri
        ? { ...object, object_uri: generateUri() }
        : object;
      const requestData = buildApiRequestData(saveObject);

      if (isCreateMode) {
        await config.crudOps.create(
          spaceId!,
          decodeURIComponent(graphId || ''),
          requestData,
        );
      } else {
        await config.crudOps.update(
          spaceId!,
          decodeURIComponent(graphId || ''),
          decodeURIComponent(objectId!),
          requestData,
        );
      }

      if (isCreateMode) {
        const listPath = config.spaceIdOverride
          ? config.listRoute
          : graphId
            ? `/space/${spaceId}/graph/${graphId}${config.listRoute}`
            : `/space/${spaceId}${config.listRoute}`;
        navigate(listPath);
      } else {
        // Refresh the data and switch to view mode
        await fetchObject();
        setSearchParams({ mode: 'view' });
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to save ${config.objectTypeName.toLowerCase()}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const needsGraphId = config.graphIdRequired !== false;
    if (!spaceId || (needsGraphId && !graphId) || !objectId) return;
    try {
      await config.crudOps.delete(
        spaceId,
        decodeURIComponent(graphId || ''),
        decodeURIComponent(objectId),
      );
      navigate(-1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to delete ${config.objectTypeName.toLowerCase()}`);
      setShowDeleteObjectModal(false);
    }
  };

  // Title functions
  const getPageTitle = (): string => {
    if (isCreateMode) return `Create ${config.objectTypeName}`;
    if (mode === 'edit') return `Edit ${config.objectTypeName}`;
    return `${config.objectTypeName} Details`;
  };

  const getObjectDisplayName = (): string => {
    if (isCreateMode) return `New ${config.objectTypeName}`;
    return extractLocalName(object?.object_uri || objectId || `Unknown ${config.objectTypeName}`);
  };

  // Fetch data on mount
  useEffect(() => {
    fetchObject();
  }, [spaceId, graphId, objectId, isCreateMode]);

  return {
    // State
    object,
    loading,
    saving,
    error,
    showDeleteObjectModal,
    newProperty,
    // Derived state
    spaceId,
    graphId,
    objectId,
    mode,
    isCreateMode,
    // Functions
    setObject,
    setError,
    setShowDeleteObjectModal,
    setNewProperty,
    setSearchParams,
    navigate,
    extractLocalName,
    formatDateTime,
    getObjectTypeBadge,
    updateProperty,
    removeProperty,
    handleAddProperty,
    handleSave,
    handleDelete,
    getPageTitle,
    getObjectDisplayName,
    fetchObject
  };
}
