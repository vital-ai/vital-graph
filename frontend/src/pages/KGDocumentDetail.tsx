import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { HiDocumentText, HiChevronDown, HiChevronRight, HiExternalLink, HiPlay, HiRefresh } from 'react-icons/hi';
import { Alert, Badge, Button, Card, Spinner } from 'flowbite-react';
import { ObjectDetailRenderer } from '../components/ObjectDetailRenderer';
import { useObjectDetail, ObjectDetailConfig, BaseRDFObject } from './AbsObjectDetail';
import { apiService, vgClient } from '../services/ApiService';
import { shortenUri } from '../utils/QuadUtils';

// -------------------------------------------------------------------
// Types
// -------------------------------------------------------------------

interface SegmentEntry {
  uri: string;
  name: string;
  headline: string;
  content: string;
  segment_index: number | null;
  segment_method: string;
  segment_type: string;
  token_length: number | null;
}

// Known haley-ai-kg predicates
const PRED = {
  content:     'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent',
  headline:    'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentHeadline',
  docType:     'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentType',
  segIndex:    'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentIndex',
  segMethod:   'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentMethodURI',
  segType:     'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI',
  tokenLen:    'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTokenLength',
  url:         'http://vital.ai/ontology/haley-ai-kg#hasKGDocumentURL',
  description: 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription',
  name:        'http://vital.ai/ontology/vital-core#hasName',
};

// -------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------

/** Extract a property value from the loaded BaseRDFObject */
function propValue(obj: BaseRDFObject | null, predicate: string): string {
  if (!obj?.properties) return '';
  const prop = obj.properties.find(p => p.predicate === predicate);
  return prop?.object ?? '';
}

function segmentTypeBadge(segType: string) {
  if (segType.includes('segmentation_parent')) return <Badge color="purple" size="xs">Parent Copy</Badge>;
  if (segType.includes('markdown_section'))    return <Badge color="indigo" size="xs">Markdown Section</Badge>;
  if (segType.includes('text_chunk'))          return <Badge color="cyan" size="xs">Text Chunk</Badge>;
  return <Badge color="gray" size="xs">{segType.split(':').pop()}</Badge>;
}

function methodLabel(uri: string) {
  if (uri.includes('markdown')) return 'Markdown';
  if (uri.includes('plain'))    return 'Plain';
  return uri.split(':').pop() || uri;
}

interface SegmentationStatus {
  job_id: number;
  status: string;  // pending | in_progress | completed | failed | cancelled
  attempt_count: number;
  segment_count: number | null;
  error_message: string | null;
  updated_at: string | null;
}

function segStatusBadge(status: string) {
  switch (status) {
    case 'pending':     return <Badge color="warning" size="xs">Pending</Badge>;
    case 'in_progress': return <Badge color="info" size="xs">In Progress</Badge>;
    case 'completed':   return <Badge color="success" size="xs">Completed</Badge>;
    case 'failed':      return <Badge color="failure" size="xs">Failed</Badge>;
    case 'cancelled':   return <Badge color="gray" size="xs">Cancelled</Badge>;
    default:            return <Badge color="gray" size="xs">{status}</Badge>;
  }
}

// -------------------------------------------------------------------
// Component
// -------------------------------------------------------------------

const KGDocumentDetail: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId, documentId } = useParams<{
    spaceId?: string;
    graphId?: string;
    documentId?: string;
  }>();

  // ---- AbsObjectDetail hook for properties / CRUD ----
  const config: ObjectDetailConfig = {
    objectTypeName: 'KG Document',
    objectTypeColor: 'blue',
    crudOps: vgClient.kgdocuments,
    listRoute: '/objects/kgdocuments',
    defaultRdfType: 'http://vital.ai/ontology/haley-ai-kg#KGDocument',
    paramName: 'documentId',
    uriFieldName: 'Document URI',
    icon: HiDocumentText,
  };

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
    properties_count: 2,
    properties: [
      { predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', object: config.defaultRdfType, object_type: 'uri' },
      { predicate: PRED.description, object: '', object_type: 'literal' },
    ],
  });

  const buildApiRequestData = (object: BaseRDFObject) => {
    const quads = (object.properties || [])
      .filter(p => p.predicate && p.object)
      .map(p => ({ s: object.object_uri || '', p: p.predicate, o: p.object, o_type: p.object_type }));
    return { quads };
  };

  const hookData = useObjectDetail(config, createDefaultObject, buildApiRequestData);

  // ---- Document metadata derived from loaded properties ----
  const docContent  = propValue(hookData.object, PRED.content) || propValue(hookData.object, PRED.description);
  const docHeadline = propValue(hookData.object, PRED.headline) || propValue(hookData.object, PRED.name);
  const docType     = propValue(hookData.object, PRED.docType);
  const docUrl      = propValue(hookData.object, PRED.url);
  const segType     = propValue(hookData.object, PRED.segType);
  const isSegment   = segType !== '' && segType !== 'urn:segtype:segmentation_parent';
  const isParent    = segType === 'urn:segtype:segmentation_parent';

  // ---- Segments section (loaded via SPARQL) ----
  const [segments, setSegments] = useState<SegmentEntry[]>([]);
  const [segmentsLoading, setSegmentsLoading] = useState(false);
  const [segmentsError, setSegmentsError] = useState<string | null>(null);
  const [expandedSegments, setExpandedSegments] = useState<Set<string>>(new Set());

  // ---- Segmentation status polling ----
  const [segStatus, setSegStatus] = useState<SegmentationStatus | null>(null);
  const [segTriggering, setSegTriggering] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const decodedGraphId = graphId ? decodeURIComponent(graphId) : '';
  const documentUri = documentId ? decodeURIComponent(documentId) : '';

  const fetchSegments = useCallback(async () => {
    if (!spaceId || !decodedGraphId || !documentUri) return;
    // Only load segments for original / parent documents — not for leaf segments
    if (isSegment) return;

    try {
      setSegmentsLoading(true);
      setSegmentsError(null);

      const sparql = `
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>

        SELECT DISTINCT ?seg ?name ?headline ?content ?segIndex ?segMethod ?segType ?tokenLen
        WHERE {
          GRAPH <${decodedGraphId}> {
            {
              # 1-hop: viewing a parent copy → direct children
              ?e1 vital:hasEdgeSource <${documentUri}> .
              ?e1 vital:hasEdgeDestination ?seg .
            }
            UNION
            {
              # 2-hop: viewing the original → parent → segments
              ?ea vital:hasEdgeSource <${documentUri}> .
              ?ea vital:hasEdgeDestination ?mid .
              ?eb vital:hasEdgeSource ?mid .
              ?eb vital:hasEdgeDestination ?seg .
            }
            ?seg a haley:KGDocument .
            ?seg haley:hasKGDocumentSegmentTypeURI ?segType .
            FILTER(?segType != "urn:segtype:segmentation_parent")
            OPTIONAL { ?seg vital:hasName ?name }
            OPTIONAL { ?seg haley:hasKGDocumentHeadline ?headline }
            OPTIONAL { ?seg haley:hasKGDocumentContent ?content }
            OPTIONAL { ?seg haley:hasKGDocumentSegmentIndex ?segIndex }
            OPTIONAL { ?seg haley:hasKGDocumentSegmentMethodURI ?segMethod }
            OPTIONAL { ?seg haley:hasKGDocumentSegmentTokenLength ?tokenLen }
          }
        }
        ORDER BY ?segIndex
        LIMIT 500
      `;

      const response = await apiService.executeSparqlQuery(spaceId, sparql);
      const results: SegmentEntry[] = (response?.results?.bindings || []).map(
        (row: Record<string, { value?: string }>) => ({
          uri:            row.seg?.value || '',
          name:           row.name?.value || '',
          headline:       row.headline?.value || '',
          content:        row.content?.value || '',
          segment_index:  row.segIndex?.value != null ? parseInt(row.segIndex.value) : null,
          segment_method: row.segMethod?.value || '',
          segment_type:   row.segType?.value || '',
          token_length:   row.tokenLen?.value != null ? parseInt(row.tokenLen.value) : null,
        })
      );
      setSegments(results);
    } catch (e: unknown) {
      setSegmentsError(`Failed to load segments: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSegmentsLoading(false);
    }
  }, [spaceId, decodedGraphId, documentUri, isSegment]);

  useEffect(() => {
    if (hookData.object) {
      fetchSegments();
    }
  }, [hookData.object, fetchSegments]);

  // ---- Segmentation status fetch ----
  const fetchSegStatus = useCallback(async () => {
    if (!spaceId || !documentUri) return;
    try {
      const resp = await apiService.getSegmentationStatus(spaceId, documentUri, undefined, 1, 0);
      const jobs = resp?.jobs ?? [];
      if (jobs.length > 0) {
        setSegStatus(jobs[0] as SegmentationStatus);
      } else {
        setSegStatus(null);
      }
    } catch {
      // silently ignore — status endpoint may not exist yet
    }
  }, [spaceId, documentUri]);

  // Initial fetch + auto-poll when job in progress
  useEffect(() => {
    if (hookData.object && !isSegment) {
      fetchSegStatus();
    }
  }, [hookData.object, isSegment, fetchSegStatus]);

  useEffect(() => {
    // Poll every 3s while pending or in_progress
    if (segStatus && (segStatus.status === 'pending' || segStatus.status === 'in_progress')) {
      pollRef.current = setInterval(fetchSegStatus, 3000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [segStatus, fetchSegStatus]);

  // When segmentation completes, refresh segments list
  useEffect(() => {
    if (segStatus?.status === 'completed') {
      fetchSegments();
    }
  }, [segStatus?.status, fetchSegments]);

  const triggerSegmentation = useCallback(async () => {
    if (!spaceId || !decodedGraphId || !documentUri) return;
    setSegTriggering(true);
    try {
      await apiService.segmentDocument(spaceId, decodedGraphId, documentUri);
      // Give server a moment, then refresh status
      setTimeout(fetchSegStatus, 500);
    } catch (e: unknown) {
      console.error('Segmentation trigger failed:', e);
    } finally {
      setSegTriggering(false);
    }
  }, [spaceId, decodedGraphId, documentUri, fetchSegStatus]);

  const toggleSegment = (uri: string) => {
    setExpandedSegments(prev => {
      const next = new Set(prev);
      if (next.has(uri)) next.delete(uri);
      else next.add(uri);
      return next;
    });
  };

  // ---- Render ----
  return (
    <div data-testid="kgdocument-detail-page">
      {/* Standard properties section (breadcrumb, header, properties table) */}
      <ObjectDetailRenderer {...hookData} config={config} />

      {/* Document metadata card */}
      {hookData.object && !hookData.loading && (
        <div className="mt-6 space-y-6">

          {/* Quick metadata badges */}
          <Card>
            <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-3">Document Info</h2>
            <div className="flex flex-wrap gap-2 mb-3">
              {isSegment && segmentTypeBadge(segType)}
              {isParent && <Badge color="purple" size="sm">Segmentation Parent</Badge>}
              {!isSegment && !isParent && <Badge color="gray" size="sm">Original Document</Badge>}
              {docType && <Badge color="dark" size="sm">{shortenUri(docType)}</Badge>}
              {propValue(hookData.object, PRED.segMethod) && (
                <Badge color="info" size="sm">
                  {methodLabel(propValue(hookData.object, PRED.segMethod))}
                </Badge>
              )}
              {propValue(hookData.object, PRED.tokenLen) && (
                <Badge color="light" size="sm">
                  {propValue(hookData.object, PRED.tokenLen)} tokens
                </Badge>
              )}
            </div>
            {docHeadline && (
              <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">{docHeadline}</p>
            )}
            {docUrl && (
              <a
                href={docUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1 mt-1 hover:underline"
              >
                <HiExternalLink className="h-4 w-4" /> {docUrl}
              </a>
            )}
          </Card>

          {/* Segmentation status */}
          {!isSegment && (
            <Card>
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-lg font-bold text-gray-900 dark:text-white">Segmentation</h2>
                <div className="flex items-center gap-2">
                  {segStatus && segStatusBadge(segStatus.status)}
                  {(!segStatus || segStatus.status === 'completed' || segStatus.status === 'failed' || segStatus.status === 'cancelled') && (
                    <Button
                      size="xs"
                      color={segStatus?.status === 'failed' ? 'failure' : 'blue'}
                      onClick={triggerSegmentation}
                      disabled={segTriggering}
                    >
                      {segTriggering ? (
                        <Spinner size="xs" className="mr-1" />
                      ) : segStatus?.status === 'failed' ? (
                        <HiRefresh className="h-3.5 w-3.5 mr-1" />
                      ) : (
                        <HiPlay className="h-3.5 w-3.5 mr-1" />
                      )}
                      {segStatus?.status === 'failed' ? 'Retry' : 'Segment'}
                    </Button>
                  )}
                  {segStatus && (segStatus.status === 'pending' || segStatus.status === 'in_progress') && (
                    <Spinner size="xs" />
                  )}
                </div>
              </div>
              {segStatus ? (
                <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
                  <p>
                    <span className="font-medium">Job #{segStatus.job_id}</span>
                    {segStatus.segment_count != null && (
                      <> &mdash; {segStatus.segment_count} segment{segStatus.segment_count !== 1 ? 's' : ''}</>
                    )}
                    {segStatus.attempt_count > 1 && (
                      <> &middot; attempt {segStatus.attempt_count}</>
                    )}
                  </p>
                  {segStatus.error_message && (
                    <Alert color="failure" className="mt-2 text-xs">{segStatus.error_message}</Alert>
                  )}
                  {segStatus.updated_at && (
                    <p className="text-xs text-gray-400">Updated: {new Date(segStatus.updated_at).toLocaleString()}</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  No segmentation jobs found for this document.
                </p>
              )}
            </Card>
          )}

          {/* Content preview */}
          {docContent && (
            <Card>
              <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-3">Content Preview</h2>
              <pre className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300 font-mono bg-gray-50 dark:bg-gray-800 p-4 rounded-lg max-h-96 overflow-y-auto">
                {docContent}
              </pre>
            </Card>
          )}

          {/* Segments section */}
          {!isSegment && (
            <Card>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-bold text-gray-900 dark:text-white">
                  Segments {segments.length > 0 && <span className="text-sm font-normal text-gray-500">({segments.length})</span>}
                </h2>
                <Button size="xs" color="light" onClick={fetchSegments} disabled={segmentsLoading}>
                  Refresh
                </Button>
              </div>

              {segmentsError && <Alert color="failure" className="mb-3">{segmentsError}</Alert>}

              {segmentsLoading ? (
                <div className="flex justify-center py-6"><Spinner size="lg" /></div>
              ) : segments.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
                  No segments found. This document has not been segmented yet.
                </p>
              ) : (
                <div className="space-y-2">
                  {segments.map(seg => {
                    const expanded = expandedSegments.has(seg.uri);
                    return (
                      <div
                        key={seg.uri}
                        className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
                      >
                        {/* Segment header — always visible */}
                        <button
                          className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors"
                          onClick={() => toggleSegment(seg.uri)}
                        >
                          {expanded
                            ? <HiChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />
                            : <HiChevronRight className="h-4 w-4 text-gray-400 flex-shrink-0" />
                          }
                          <span className="text-xs font-mono text-gray-400 flex-shrink-0">
                            #{seg.segment_index ?? '—'}
                          </span>
                          {segmentTypeBadge(seg.segment_type)}
                          {seg.token_length != null && (
                            <Badge color="light" size="xs">{seg.token_length} tok</Badge>
                          )}
                          <span className="text-sm text-gray-800 dark:text-gray-200 truncate flex-1">
                            {seg.headline || seg.name || shortenUri(seg.uri)}
                          </span>
                          <Button
                            size="xs"
                            color="light"
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              navigate(
                                `/space/${spaceId}/graph/${encodeURIComponent(decodedGraphId)}/document/${encodeURIComponent(seg.uri)}`
                              );
                            }}
                          >
                            View
                          </Button>
                        </button>

                        {/* Expanded content */}
                        {expanded && seg.content && (
                          <div className="px-4 pb-3 pt-0">
                            <pre className="whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-400 font-mono bg-gray-50 dark:bg-gray-800 p-3 rounded max-h-48 overflow-y-auto">
                              {seg.content}
                            </pre>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  );
};

export default KGDocumentDetail;
