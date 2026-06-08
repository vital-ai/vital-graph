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
        predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
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

  // Build API request data from object properties as quads
  const buildApiRequestData = (object: BaseRDFObject) => {
    const quads = (object.properties || [])
      .filter(p => p.predicate && p.object)
      .map(p => ({
        s: object.object_uri || '',
        p: p.predicate,
        o: p.object,
        o_type: p.object_type,
      }));
    return { quads };
  };

  // Use the shared hook
  const hookData = useObjectDetail(config, createDefaultObject, buildApiRequestData);

  // Render with shared component
  return <ObjectDetailRenderer {...hookData} config={config} />;
};

export default KGFrameDetail;
