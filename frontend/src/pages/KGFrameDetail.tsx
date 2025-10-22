import React from 'react';
import { HiCollection } from 'react-icons/hi';
import { ObjectDetailRenderer } from '../components/ObjectDetailRenderer';
import { useObjectDetail, ObjectDetailConfig, BaseRDFObject } from './AbsObjectDetail';

const KGFrameDetail: React.FC = () => {
  // Configuration for KG Frames
  const config: ObjectDetailConfig = {
    objectTypeName: 'KG Frame',
    objectTypeColor: 'indigo',
    apiEndpoint: '/api/graphs/kgframes',
    listRoute: '/kg-frames',
    defaultRdfType: 'http://vital.ai/ontology/haley-ai-kg#KGFrame',
    paramName: 'frameId',
    uriFieldName: 'Frame URI',
    icon: HiCollection
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

  // Build API request data from object
  const buildApiRequestData = (object: BaseRDFObject) => {
    const jsonLdObject: any = {
      '@context': {}
    };

    // Add properties from the object
    if (object.properties) {
      object.properties.forEach(prop => {
        if (prop.predicate && prop.object) {
          jsonLdObject[prop.predicate] = prop.object;
        }
      });
    }

    return {
      objects: {
        '@context': {},
        '@graph': [jsonLdObject]
      }
    };
  };

  // Use the shared hook
  const hookData = useObjectDetail(config, createDefaultObject, buildApiRequestData);

  // Render with shared component
  return <ObjectDetailRenderer {...hookData} config={config} />;
};

export default KGFrameDetail;
