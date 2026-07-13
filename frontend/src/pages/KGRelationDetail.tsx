import React from 'react';
import { useNavigate } from 'react-router-dom';
import { HiLink } from 'react-icons/hi';
import { ObjectDetailRenderer } from '../components/ObjectDetailRenderer';
import { useObjectDetail, ObjectDetailConfig, BaseRDFObject } from './AbsObjectDetail';
import { vgClient } from '../services/ApiService';
import { VisualizeInGraphButton } from '../components/VisualizeInGraphButton';

const KGRelationDetail: React.FC = () => {
  const navigate = useNavigate();

  // Configuration for KG Relations
  const config: ObjectDetailConfig = {
    objectTypeName: 'KG Relation',
    objectTypeColor: 'purple',
    crudOps: vgClient.kgrelations,
    listRoute: '/objects/kgrelations',
    defaultRdfType: 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame',
    paramName: 'relationId',
    uriFieldName: 'Relation URI',
    icon: HiLink
  };

  // Create default object for new instances
  const createDefaultObject = (): BaseRDFObject => ({
    id: 0,
    space_id: '',
    graph_id: 0,
    object_uri: '',
    object_type: 'Edge',
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
        predicate: 'http://vital.ai/ontology/vital-core#hasEdgeSource',
        object: '',
        object_type: 'uri'
      },
      {
        predicate: 'http://vital.ai/ontology/vital-core#hasEdgeDestination',
        object: '',
        object_type: 'uri'
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

  return (
    <div data-testid="kgrelation-detail-page">
      {/* Properties section (breadcrumb, header, properties table) */}
      <ObjectDetailRenderer {...hookData} config={config} />

      {/* Visualize in graph — session picker */}
      {hookData.spaceId && hookData.object?.object_uri && !hookData.isCreateMode && (
        <VisualizeInGraphButton
          spaceId={hookData.spaceId || ''}
          entityUri={hookData.object.object_uri}
          navigate={navigate}
        />
      )}
    </div>
  );
};

export default KGRelationDetail;
