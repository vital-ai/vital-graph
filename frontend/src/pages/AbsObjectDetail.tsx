import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { Badge } from 'flowbite-react';

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

// Configuration interface for different object types
export interface ObjectDetailConfig {
  objectTypeName: string;
  objectTypeColor: string;
  apiEndpoint: string;
  listRoute: string;
  defaultRdfType: string;
  paramName: string;
  uriFieldName: string;
  icon: React.ComponentType<any>;
}

// Custom hook for shared object detail functionality
export function useObjectDetail<T extends BaseRDFObject = BaseRDFObject>(
  config: ObjectDetailConfig,
  createDefaultObject: () => T,
  buildApiRequestData: (object: T) => any
) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const params = useParams();
  
  const spaceId = params.spaceId;
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
  const extractLocalName = (uri: string): string => {
    if (!uri) return '';
    const parts = uri.split(/[#/]/);
    return parts[parts.length - 1] || uri;
  };

  const formatDateTime = (dateString: string): string => {
    if (!dateString) return 'N/A';
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return 'Invalid Date';
    }
  };

  const getObjectTypeBadge = (type: string) => {
    const badgeConfig = type === 'Node' 
      ? { color: 'blue', text: 'Node' }
      : { color: 'green', text: 'Edge' };
    return <Badge color={badgeConfig.color}>{badgeConfig.text}</Badge>;
  };

  // API functions
  const fetchObject = async () => {
    if (isCreateMode) {
      const newObject = createDefaultObject();
      setObject(newObject);
      setLoading(false);
      return;
    }

    if (!spaceId || !graphId || !objectId) {
      setError('Missing required parameters');
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      
      // Different API call format for KG Types vs Graph Objects
      const isKGTypesAPI = config.apiEndpoint.includes('kgtypes');
      let response;
      
      if (isKGTypesAPI) {
        // KG Types API format
        response = await axios.get(config.apiEndpoint, {
          params: {
            space_id: spaceId,
            graph_id: decodeURIComponent(graphId),
            uri: decodeURIComponent(objectId),
            page_size: 1,
            offset: 0
          }
        });
      } else {
        // Graph Objects API format
        response = await axios.get(config.apiEndpoint, {
          params: {
            space_id: spaceId,
            graph_id: decodeURIComponent(graphId),
            uri: decodeURIComponent(objectId)
          }
        });
      }

      const responseData = response.data;
      let objectData = null;

      if (isKGTypesAPI) {
        // Handle KG Types API response format
        let kgTypesData = [];
        if (responseData.data && responseData.data['@graph']) {
          kgTypesData = responseData.data['@graph'];
        } else if (Array.isArray(responseData)) {
          kgTypesData = responseData;
        }
        
        if (kgTypesData.length > 0) {
          objectData = kgTypesData[0];
        }
      } else {
        // Handle Graph Objects API response format
        objectData = responseData && (responseData['@id'] || responseData.URI) ? responseData : null;
      }

      if (objectData) {
        const convertedObject = convertApiResponseToObject(objectData);
        setObject(convertedObject);
      } else {
        setError(`${config.objectTypeName} not found`);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to load ${config.objectTypeName.toLowerCase()}`);
    } finally {
      setLoading(false);
    }
  };

  const convertApiResponseToObject = (data: any): T => {
    const convertedObject: BaseRDFObject = {
      id: 0,
      space_id: spaceId || '',
      graph_id: 0,
      object_uri: data['@id'] || data.URI || decodeURIComponent(objectId || ''),
      object_type: data['@type']?.includes('Edge') ? 'Edge' : 'Node',
      rdf_type: data['@type'] || 'Unknown',
      subject: data['@id'] || data.URI || decodeURIComponent(objectId || ''),
      predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
      object: data['@type'] || 'Unknown',
      context: decodeURIComponent(graphId || ''),
      created_time: data.created_time || new Date().toISOString(),
      last_modified: data.last_modified || new Date().toISOString(),
      properties_count: Object.keys(data).length - 1,
      properties: []
    };

    Object.entries(data).forEach(([key, value]) => {
      if (key !== '@context' && key !== '@graph' && value !== null && value !== undefined) {
        // Properties should have exactly one value
        const propertyValue = typeof value === 'object' ? JSON.stringify(value) : String(value);
        
        const property = {
          predicate: key,
          object: propertyValue,
          object_type: (key.startsWith('http') || key === '@id' || key === '@type' || key === 'URI' ? 'uri' : 'literal') as 'uri' | 'literal'
        };
        convertedObject.properties!.push(property);
      }
    });

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
    
    const updatedProperties = object.properties.filter((_: any, i: number) => i !== index);
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
      const requestData = buildApiRequestData(object);

      // Different API call format for KG Types vs Graph Objects
      const isKGTypesAPI = config.apiEndpoint.includes('kgtypes');

      if (isCreateMode) {
        if (isKGTypesAPI) {
          // KG Types API format for create
          await axios.post(`${config.apiEndpoint}?space_id=${spaceId}&graph_id=${encodeURIComponent(graphId!)}`, requestData);
        } else {
          // Graph Objects API format for create
          await axios.post(config.apiEndpoint, requestData, {
            params: { space_id: spaceId, graph_id: decodeURIComponent(graphId || '') }
          });
        }
      } else {
        if (isKGTypesAPI) {
          // KG Types API format for update
          await axios.put(`${config.apiEndpoint}?space_id=${spaceId}&graph_id=${encodeURIComponent(graphId!)}`, requestData);
        } else {
          // Graph Objects API format for update
          await axios.put(config.apiEndpoint, requestData, {
            params: {
              space_id: spaceId,
              graph_id: decodeURIComponent(graphId || ''),
              uri: decodeURIComponent(objectId!)
            }
          });
        }
      }

      if (isCreateMode) {
        navigate(`/space/${spaceId}/graph/${graphId}${config.listRoute}`);
      } else {
        // Refresh the data and switch to view mode
        await fetchObject();
        setSearchParams({ mode: 'view' });
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to save ${config.objectTypeName.toLowerCase()}`);
    } finally {
      setSaving(false);
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
    getPageTitle,
    getObjectDisplayName,
    fetchObject
  };
}
