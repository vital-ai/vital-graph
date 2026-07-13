import React from 'react';
import { useNavigate } from 'react-router-dom';
import { HiCube } from 'react-icons/hi';
import { ObjectDetailRenderer } from '../components/ObjectDetailRenderer';
import { useObjectDetail, ObjectDetailConfig, BaseRDFObject } from './AbsObjectDetail';
import { vgClient } from '../services/ApiService';
import TypeRelationshipsPanel from '../components/TypeRelationshipsPanel';
import TypeDocumentationPanel from '../components/TypeDocumentationPanel';
import { VisualizeInGraphButton } from '../components/VisualizeInGraphButton';

const VITALTYPE_PREDICATE = 'http://vital.ai/ontology/vital-core#vitaltype';

const RELATIONSHIP_TYPES = new Set([
  'http://vital.ai/ontology/haley-ai-kg#KGFrameType',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotType',
  'http://vital.ai/ontology/haley-ai-kg#KGEntityType',
  'http://vital.ai/ontology/haley-ai-kg#KGRelationType',
]);

const KGTypeDetail: React.FC = () => {
  const navigate = useNavigate();
  // KG Types API no longer takes graphId — wrap to match CrudOps interface
  const kgTypesCrud = {
    get: (spaceId: string, _graphId: string, uri: string) =>
      (vgClient.kgtypes as any).get(spaceId, uri),
    create: (spaceId: string, _graphId: string, data: unknown) =>
      (vgClient.kgtypes as any).create(spaceId, data),
    update: (spaceId: string, _graphId: string, uri: string, data: unknown) =>
      (vgClient.kgtypes as any).update(spaceId, uri, data),
    delete: (spaceId: string, _graphId: string, uri: string) =>
      (vgClient.kgtypes as any).delete(spaceId, uri),
  };

  // Configuration for KG Types
  const config: ObjectDetailConfig = {
    objectTypeName: 'KG Type',
    objectTypeColor: 'purple',
    crudOps: kgTypesCrud,
    listRoute: '/kg-types',
    defaultRdfType: 'http://vital.ai/ontology/haley-ai-kg#KGEntityType',
    paramName: 'kgTypeId',
    uriFieldName: 'Type URI',
    icon: HiCube,
    graphIdRequired: false,
    spaceIdOverride: 'sp_kg_types',
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

  // Derive vitaltype from loaded object's properties
  const vitaltype = hookData.object?.properties?.find(
    p => p.predicate === VITALTYPE_PREDICATE
  )?.object || hookData.object?.rdf_type || '';

  const showRelationships =
    hookData.spaceId &&
    hookData.object?.object_uri &&
    !hookData.isCreateMode &&
    RELATIONSHIP_TYPES.has(vitaltype);

  const showDocumentation =
    hookData.spaceId &&
    hookData.object?.object_uri &&
    !hookData.isCreateMode;

  return (
    <div data-testid="kgtype-detail-page">
      <ObjectDetailRenderer {...hookData} config={config} />

      {hookData.spaceId && hookData.object?.object_uri && !hookData.isCreateMode && (
        <VisualizeInGraphButton
          spaceId={hookData.spaceId || 'sp_kg_types'}
          entityUri={hookData.object.object_uri}
          navigate={navigate}
        />
      )}

      {showRelationships && (
        <div className="mt-6">
          <TypeRelationshipsPanel
            spaceId={hookData.spaceId!}
            typeUri={hookData.object!.object_uri!}
            typeVitaltype={vitaltype}
          />
        </div>
      )}

      {showDocumentation && (
        <div className="mt-6">
          <TypeDocumentationPanel
            spaceId={hookData.spaceId!}
            typeUri={hookData.object!.object_uri!}
          />
        </div>
      )}
    </div>
  );
};

export default KGTypeDetail;
