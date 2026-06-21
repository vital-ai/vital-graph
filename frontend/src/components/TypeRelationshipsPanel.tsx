import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spinner, Badge, TextInput, Button } from 'flowbite-react';
import { HiArrowRight, HiArrowLeft, HiExternalLink, HiPlus, HiX } from 'react-icons/hi';
import { apiService } from '../services/ApiService';
import { shortenUri } from '../utils/QuadUtils';

// ── Type URIs for display labels ──────────────────────────────────────

const EDGE_TYPE_LABELS: Record<string, string> = {
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType': 'Sub Frame Type',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasPartOfKGFrameType': 'Part-of Frame',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType': 'Entity → Frame',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType': 'Sub Entity Type',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGType': 'Sub Type',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSameAsKGType': 'Same As',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelationType': 'Relation Type',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType': 'Outgoing Relation',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType': 'Incoming Relation',
};

const VITALTYPE_LABELS: Record<string, string> = {
  'http://vital.ai/ontology/haley-ai-kg#KGFrameType': 'Frame Type',
  'http://vital.ai/ontology/haley-ai-kg#KGEntityType': 'Entity Type',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotType': 'Slot Type',
  'http://vital.ai/ontology/haley-ai-kg#KGRelationType': 'Relation Type',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType': 'Role Type',
};

const VITALTYPE_COLORS: Record<string, string> = {
  'http://vital.ai/ontology/haley-ai-kg#KGFrameType': 'blue',
  'http://vital.ai/ontology/haley-ai-kg#KGEntityType': 'green',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotType': 'yellow',
  'http://vital.ai/ontology/haley-ai-kg#KGRelationType': 'purple',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType': 'gray',
};

// ── Interfaces ────────────────────────────────────────────────────────

interface RelEdge {
  uri: string;
  edgeType: string;
  sourceURI: string;
  destinationURI: string;
  direction: 'outgoing' | 'incoming';
}

interface RelType {
  uri: string;
  name: string;
  vitaltype: string;
}

interface RelationshipsData {
  success: boolean;
  message: string;
  source_type: RelType;
  edges: RelEdge[];
  connected_types: RelType[];
}

// ── Types with edge info for deletion ─────────────────────────────────

interface RelTypeWithEdge extends RelType {
  edgeUri: string;
}

// ── Section component ─────────────────────────────────────────────────

interface RelSectionProps {
  title: string;
  types: RelTypeWithEdge[];
  spaceId: string;
  emptyLabel?: string;
  edgeTypeForAdd?: string;
  onAdd?: (edgeType: string, targetUri: string) => Promise<void>;
  onDelete?: (edgeUri: string) => Promise<void>;
}

const RelSection: React.FC<RelSectionProps> = ({
  title, types, spaceId, emptyLabel, edgeTypeForAdd, onAdd, onDelete,
}) => {
  const navigate = useNavigate();
  const [showAdd, setShowAdd] = useState(false);
  const [addUri, setAddUri] = useState('');
  const [addBusy, setAddBusy] = useState(false);
  const [deletingUri, setDeletingUri] = useState<string | null>(null);

  if (types.length === 0 && !emptyLabel && !edgeTypeForAdd) return null;

  const handleAdd = async () => {
    if (!onAdd || !edgeTypeForAdd || !addUri.trim()) return;
    setAddBusy(true);
    try {
      await onAdd(edgeTypeForAdd, addUri.trim());
      setAddUri('');
      setShowAdd(false);
    } finally { setAddBusy(false); }
  };

  const handleDelete = async (edgeUri: string) => {
    if (!onDelete) return;
    setDeletingUri(edgeUri);
    try {
      await onDelete(edgeUri);
    } finally { setDeletingUri(null); }
  };

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 mb-2">
        <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          {title}
        </h4>
        {edgeTypeForAdd && onAdd && (
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="p-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors"
            title={`Add ${title.toLowerCase()}`}
          >
            <HiPlus className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {showAdd && (
        <div className="flex items-center gap-2 mb-2">
          <TextInput
            sizing="sm"
            placeholder="Target type URI..."
            value={addUri}
            onChange={e => setAddUri(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleAdd()}
            className="flex-1 text-xs"
          />
          <Button size="xs" color="blue" onClick={handleAdd} disabled={addBusy || !addUri.trim()}>
            {addBusy ? <Spinner size="xs" /> : 'Add'}
          </Button>
          <Button size="xs" color="light" onClick={() => { setShowAdd(false); setAddUri(''); }}>
            <HiX className="w-3 h-3" />
          </Button>
        </div>
      )}

      {types.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">{emptyLabel}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {types.map(t => (
            <div key={t.uri} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm
              bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700
              text-gray-700 dark:text-gray-300 group">
              <button
                onClick={() => navigate(`/space/${spaceId}/kg-types/${encodeURIComponent(t.uri)}?mode=view`)}
                className="inline-flex items-center gap-1.5 hover:text-blue-500 transition-colors"
                title={t.uri}
              >
                <Badge color={VITALTYPE_COLORS[t.vitaltype] || 'gray'} size="xs">
                  {VITALTYPE_LABELS[t.vitaltype] || shortenUri(t.vitaltype)}
                </Badge>
                <span className="font-medium">{t.name || shortenUri(t.uri)}</span>
                <HiExternalLink className="w-3 h-3 text-gray-400" />
              </button>
              {onDelete && (
                <button
                  onClick={() => handleDelete(t.edgeUri)}
                  disabled={deletingUri === t.edgeUri}
                  className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-red-100 dark:hover:bg-red-900/30
                    text-gray-400 hover:text-red-500 transition-all"
                  title="Remove relationship"
                >
                  {deletingUri === t.edgeUri ? <Spinner size="xs" /> : <HiX className="w-3 h-3" />}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ── Main panel ────────────────────────────────────────────────────────

interface TypeRelationshipsPanelProps {
  spaceId: string;
  graphId?: string; // deprecated, ignored — backend derives graph from space
  typeUri: string;
  typeVitaltype: string;
}

const TypeRelationshipsPanel: React.FC<TypeRelationshipsPanelProps> = ({
  spaceId, typeUri, typeVitaltype,
}) => {
  const [data, setData] = useState<RelationshipsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRelationships = useCallback(async () => {
    if (!spaceId || !typeUri) return;
    try {
      setLoading(true);
      setError(null);
      const resp = await apiService.getKGTypeRelationships(spaceId, typeUri);
      setData(resp);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load relationships');
    } finally {
      setLoading(false);
    }
  }, [spaceId, typeUri]);

  useEffect(() => { fetchRelationships(); }, [fetchRelationships]);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-center justify-center py-8">
          <Spinner size="md" />
          <span className="ml-2 text-sm text-gray-500">Loading relationships...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        <p className="text-sm text-red-500">{error}</p>
      </div>
    );
  }

  const edges = data?.edges ?? [];
  const typeMap = new Map((data?.connected_types ?? []).map(t => [t.uri, t]));

  // Group edges into semantic sections based on vitaltype
  const isFrame = typeVitaltype === 'http://vital.ai/ontology/haley-ai-kg#KGFrameType';
  const isEntity = typeVitaltype === 'http://vital.ai/ontology/haley-ai-kg#KGEntityType';
  const isRelation = typeVitaltype === 'http://vital.ai/ontology/haley-ai-kg#KGRelationType';

  // Helper: resolve types from edges by filter (includes edge URI for deletion)
  const typesFromEdges = (filter: (e: RelEdge) => boolean): RelTypeWithEdge[] => {
    return edges.filter(filter).map(e => {
      const relatedUri = e.direction === 'outgoing' ? e.destinationURI : e.sourceURI;
      const t = typeMap.get(relatedUri);
      return t ? { ...t, edgeUri: e.uri } : undefined;
    }).filter(Boolean) as RelTypeWithEdge[];
  };

  const handleAdd = async (edgeType: string, targetUri: string) => {
    await apiService.createKGTypeRelationship(spaceId, typeUri, edgeType, targetUri);
    await fetchRelationships();
  };

  const handleDelete = async (edgeUri: string) => {
    await apiService.deleteKGTypeRelationship(spaceId, typeUri, edgeUri);
    await fetchRelationships();
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Type Relationships
          <Badge color="gray" size="xs" className="ml-2">{edges.length}</Badge>
        </h3>
      </div>

      {/* ── Frame Type sections ─────────────────────────────────── */}
      {isFrame && (
        <>
          <RelSection
            title="Parent Frame Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType' &&
              e.direction === 'incoming'
            )}
            spaceId={spaceId}
            emptyLabel="No parent frame types"
            onDelete={handleDelete}
          />
          <RelSection
            title="Sub Frame Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType' &&
              e.direction === 'outgoing'
            )}
            spaceId={spaceId}
            emptyLabel="No sub frame types"
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
          <RelSection
            title="Part-of Frame Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasPartOfKGFrameType' &&
              e.direction === 'outgoing'
            )}
            spaceId={spaceId}
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasPartOfKGFrameType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
          <RelSection
            title="Entity Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType' &&
              e.direction === 'incoming'
            )}
            spaceId={spaceId}
            onDelete={handleDelete}
          />
          <RelSection
            title="Same As"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasSameAsKGType'
            )}
            spaceId={spaceId}
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasSameAsKGType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
        </>
      )}

      {/* ── Entity Type sections ────────────────────────────────── */}
      {isEntity && (
        <>
          <RelSection
            title="Subtypes"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType' &&
              e.direction === 'outgoing'
            )}
            spaceId={spaceId}
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
          <RelSection
            title="Parent Entity Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType' &&
              e.direction === 'incoming'
            )}
            spaceId={spaceId}
            onDelete={handleDelete}
          />
          <RelSection
            title="Part-of Frame Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType' &&
              e.direction === 'outgoing'
            )}
            spaceId={spaceId}
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
          <RelSection
            title="Outgoing Relation Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType' &&
              e.direction === 'outgoing'
            )}
            spaceId={spaceId}
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
          <RelSection
            title="Incoming Relation Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType' &&
              e.direction === 'outgoing'
            )}
            spaceId={spaceId}
            edgeTypeForAdd="http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType"
            onAdd={handleAdd} onDelete={handleDelete}
          />
        </>
      )}

      {/* ── Relation Type sections ──────────────────────────────── */}
      {isRelation && (
        <>
          <RelSection
            title="Source Entity Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType' &&
              e.direction === 'incoming'
            )}
            spaceId={spaceId}
            emptyLabel="No source entity types linked"
            onDelete={handleDelete}
          />
          <RelSection
            title="Destination Entity Types"
            types={typesFromEdges(e =>
              e.edgeType === 'http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType' &&
              e.direction === 'incoming'
            )}
            spaceId={spaceId}
            emptyLabel="No destination entity types linked"
            onDelete={handleDelete}
          />
        </>
      )}

      {/* ── Generic fallback: all edges as a table ──────────────── */}
      {!isFrame && !isEntity && !isRelation && (
        <div className="space-y-1">
          {edges.map((e, i) => {
            const relatedUri = e.direction === 'outgoing' ? e.destinationURI : e.sourceURI;
            const relatedType = typeMap.get(relatedUri);
            return (
              <div key={e.uri || i} className="flex items-center gap-2 text-sm py-1">
                {e.direction === 'outgoing'
                  ? <HiArrowRight className="w-4 h-4 text-blue-400 flex-shrink-0" />
                  : <HiArrowLeft className="w-4 h-4 text-orange-400 flex-shrink-0" />
                }
                <Badge color="gray" size="xs">
                  {EDGE_TYPE_LABELS[e.edgeType] || shortenUri(e.edgeType)}
                </Badge>
                <span className="text-gray-700 dark:text-gray-300 font-medium">
                  {relatedType?.name || shortenUri(relatedUri)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default TypeRelationshipsPanel;
