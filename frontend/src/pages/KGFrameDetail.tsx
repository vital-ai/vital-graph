import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Badge, Spinner } from 'flowbite-react';
import { HiCollection } from 'react-icons/hi';
import { ObjectDetailRenderer } from '../components/ObjectDetailRenderer';
import { useObjectDetail, ObjectDetailConfig, BaseRDFObject } from './AbsObjectDetail';
import { apiService, vgClient } from '../services/ApiService';
import {
  hydrateQuads,
  getSlotDisplayValue,
  getSlotLabel,
  getShortClassName,
} from '../lib/entityGraphBuilder';
import type { Quad } from '../utils/QuadUtils';

interface SlotSummaryRow {
  name: string;
  slotType: string;
  value: unknown;
  dataType: string;
}

const KGFrameDetail: React.FC = () => {
  const params = useParams();
  const spaceId = params.spaceId || '';
  const graphId = params.graphId ? decodeURIComponent(params.graphId) : '';
  const frameId = params.frameId ? decodeURIComponent(params.frameId) : '';

  // Configuration for KG Frames
  const config: ObjectDetailConfig = {
    objectTypeName: 'KG Frame',
    objectTypeColor: 'indigo',
    crudOps: vgClient.kgframes,
    listRoute: '/objects/kgframes',
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

  // ─── Slot Summary Section ──────────────────────────────────────────
  const [slotSummary, setSlotSummary] = useState<SlotSummaryRow[]>([]);
  const [slotsLoading, setSlotsLoading] = useState(false);

  useEffect(() => {
    if (!spaceId || !graphId || !frameId) return;
    const fetchFrameGraph = async () => {
      try {
        setSlotsLoading(true);
        const resp = await apiService.getFrame(spaceId, graphId, frameId);
        const quads: Quad[] = (resp as any)?.results || [];
        if (quads.length === 0) { setSlotSummary([]); return; }

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const graphObjects: any[] = hydrateQuads(quads) as any[];
        // Extract slots linked to this frame via Edge_hasKGSlot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const { isKGSlot, isEdgeHasKGSlot } = await import('@vital-ai/vital-kg-model-ts') as any;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const slotEdges = graphObjects.filter((o: any) => isEdgeHasKGSlot(o) && o.edgeSource === frameId);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const slotsByUri = new Map(graphObjects.filter(isKGSlot).map((s: any) => [s.URI, s]));

        const rows: SlotSummaryRow[] = [];
        for (const edge of slotEdges) {
          const slot = slotsByUri.get(edge.edgeDestination);
          if (!slot) continue;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const { value, dataType } = getSlotDisplayValue(slot as any);
          rows.push({
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            name: getSlotLabel(slot as any),
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            slotType: getShortClassName((slot as any).vitaltype),
            value,
            dataType,
          });
        }
        setSlotSummary(rows);
      } catch {
        setSlotSummary([]);
      } finally {
        setSlotsLoading(false);
      }
    };
    fetchFrameGraph();
  }, [spaceId, graphId, frameId]);

  // Render with shared component + slot summary
  return (
    <div data-testid="kgframe-detail-page">
      <ObjectDetailRenderer {...hookData} config={config} />

      {/* Slot Summary Table */}
      {frameId && !hookData.isCreateMode && (
        <div className="mt-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
            <HiCollection className="w-5 h-5 text-indigo-500" />
            Slot Summary
          </h3>
          {slotsLoading ? (
            <div className="flex justify-center py-6"><Spinner size="md" /></div>
          ) : slotSummary.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400 italic">No slots found for this frame.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
                  <tr>
                    <th className="px-4 py-3">Slot Name</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {slotSummary.map((row, idx) => (
                    <tr key={idx} className="bg-white dark:bg-gray-900">
                      <td className="px-4 py-2 font-medium text-gray-900 dark:text-white">
                        {row.name}
                      </td>
                      <td className="px-4 py-2">
                        <Badge color="gray" size="xs">{row.slotType}</Badge>
                      </td>
                      <td className="px-4 py-2 text-gray-700 dark:text-gray-300 max-w-md truncate" title={String(row.value ?? '')}>
                        {row.value !== undefined && row.value !== null && row.value !== ''
                          ? String(row.value)
                          : <span className="text-gray-400 italic">empty</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default KGFrameDetail;
