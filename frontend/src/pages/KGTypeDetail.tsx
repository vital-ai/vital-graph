import React from 'react';
import { HiCube } from 'react-icons/hi';
import { ObjectDetailRenderer } from '../components/ObjectDetailRenderer';
import { useObjectDetail, ObjectDetailConfig, BaseRDFObject } from './AbsObjectDetail';

const KGTypeDetail: React.FC = () => {
  // Configuration for KG Types
  const config: ObjectDetailConfig = {
    objectTypeName: 'KG Type',
    objectTypeColor: 'purple',
    apiEndpoint: '/api/graphs/kgtypes',
    listRoute: '/kg-types',
    defaultRdfType: 'http://vital.ai/ontology/haley-ai-kg#KGEntityType',
    paramName: 'kgTypeId',
    uriFieldName: 'Type URI',
    icon: HiCube
  };

  // Create default object for new instances
  const createDefaultObject = (): BaseRDFObject => ({
    id: 0,
    space_id: '',
    graph_id: 0,
    object_uri: '',
    object_type: 'Node',
    rdf_type: config.defaultRdfType,
    subject: '',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: '',
    context: '',
    created_time: new Date().toISOString(),
    last_modified: new Date().toISOString(),
    properties_count: 3,
    properties: [
      {
        predicate: '@id',
        object: '',
        object_type: 'uri'
      },
      {
        predicate: '@type',
        object: config.defaultRdfType,
        object_type: 'uri'
      },
      {
        predicate: 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription',
        object: '',
        object_type: 'literal'
      }
    ]
  });

  // Build API request data from object (KG Types use special format)
  const buildApiRequestData = (object: BaseRDFObject) => {
    const updatedKGType: any = {};
    
    // Process properties and convert to KG type format
    if (object.properties) {
      object.properties.forEach(prop => {
        if (prop.predicate && prop.object) {
          try {
            // Try to parse as JSON first (for objects)
            const parsedValue = JSON.parse(prop.object);
            updatedKGType[prop.predicate] = parsedValue;
          } catch {
            // If not JSON, use as string
            updatedKGType[prop.predicate] = prop.object;
          }
        }
      });
    }

    // Create JSON-LD document format expected by the backend
    return {
      document: {
        "@context": {
          "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
          "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
          "vital": "http://vital.ai/ontology/vital-core#",
          "haley": "http://vital.ai/ontology/haley-ai-kg#"
        },
        "@graph": [updatedKGType]
      }
    };
  };

  // Use the shared hook
  const hookData = useObjectDetail(config, createDefaultObject, buildApiRequestData);

  // Render with shared component
  return <ObjectDetailRenderer {...hookData} config={config} />;
};

export default KGTypeDetail;
