import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Alert,
  Badge,
  Breadcrumb,
  BreadcrumbItem,
  Button,
  Card,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
} from 'flowbite-react';
import { HiHome, HiSearch, HiExternalLink } from 'react-icons/hi';
import { apiService } from '../services/ApiService';

const VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype';

// Map vitaltype URIs to their detail routes
const TYPE_ROUTE_MAP: Record<string, { label: string; pathSegment: string }> = {
  'http://vital.ai/ontology/haley-ai-kg#KGEntity': { label: 'KG Entity', pathSegment: 'entity' },
  'http://vital.ai/ontology/haley-ai-kg#KGNewsEntity': { label: 'KG Entity', pathSegment: 'entity' },
  'http://vital.ai/ontology/haley-ai-kg#KGProductEntity': { label: 'KG Entity', pathSegment: 'entity' },
  'http://vital.ai/ontology/haley-ai-kg#KGWebEntity': { label: 'KG Entity', pathSegment: 'entity' },
  'http://vital.ai/ontology/haley-ai-kg#KGFrame': { label: 'KG Frame', pathSegment: 'frame' },
  'http://vital.ai/ontology/haley-ai-kg#KGDocument': { label: 'KG Document', pathSegment: 'document' },
  'http://vital.ai/ontology/haley-ai-kg#KGType': { label: 'KG Type', pathSegment: 'kg-types' },
  'http://vital.ai/ontology/haley-ai-kg#KGFrameType': { label: 'KG Type', pathSegment: 'kg-types' },
  'http://vital.ai/ontology/haley-ai-kg#KGSlotType': { label: 'KG Type', pathSegment: 'kg-types' },
  'http://vital.ai/ontology/haley-ai-kg#KGEntityType': { label: 'KG Type', pathSegment: 'kg-types' },
  'http://vital.ai/ontology/haley-ai-kg#KGRelationType': { label: 'KG Type', pathSegment: 'kg-types' },
};

// Check if a vitaltype is a KGSlot subclass (matches @vital-ai/vital-kg-model-ts isKGSlot pattern)
function isSlotVitaltype(vitaltype: string): boolean {
  return vitaltype.includes('KGSlot');
}

// Grouping URI predicates — direct properties on slot objects
const HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI';
const HAS_FRAME_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI';

interface QuadProperty {
  predicate: string;
  object: string;
  object_type: 'uri' | 'literal';
}

function shortenUri(uri: string): string {
  if (!uri) return '';
  const hashIdx = uri.lastIndexOf('#');
  if (hashIdx >= 0) return uri.slice(hashIdx + 1);
  const slashIdx = uri.lastIndexOf('/');
  if (slashIdx >= 0) return uri.slice(slashIdx + 1);
  return uri;
}

const SearchResultDetail: React.FC = () => {
  const navigate = useNavigate();
  const { spaceId, graphId, subjectUri } = useParams<{
    spaceId: string;
    graphId: string;
    subjectUri: string;
  }>();

  const [properties, setProperties] = useState<QuadProperty[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rdfTypes, setRdfTypes] = useState<string[]>([]);

  const decodedUri = subjectUri ? decodeURIComponent(subjectUri) : '';
  const decodedGraphId = graphId ? decodeURIComponent(graphId) : '';

  useEffect(() => {
    const fetchQuads = async () => {
      if (!spaceId || !graphId || !subjectUri) return;
      setLoading(true);
      setError(null);
      try {
        const sparql = `SELECT ?p ?o WHERE { <${decodedUri}> ?p ?o }`;
        const response = await apiService.executeSparqlQuery(spaceId, sparql);
        const bindings = response?.results?.bindings || [];

        const props: QuadProperty[] = bindings.map((b: { p?: { value?: string }; o?: { value?: string; type?: string } }) => ({
          predicate: b.p?.value || '',
          object: b.o?.value || '',
          object_type: b.o?.type === 'uri' ? 'uri' as const : 'literal' as const,
        }));
        setProperties(props);

        // Extract vitaltype values
        const types = props
          .filter((p) => p.predicate === VITALTYPE)
          .map((p) => p.object);
        setRdfTypes(types);

      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load quads for subject');
      } finally {
        setLoading(false);
      }
    };
    fetchQuads();
  }, [spaceId, graphId, subjectUri, decodedGraphId, decodedUri]);

  // Find a matching typed detail route
  const isSlotType = rdfTypes.some((t) => isSlotVitaltype(t));

  // For slot types, resolve enclosing container from grouping URI properties
  let typedDetailPath: string | null = null;
  let typedDetailLabel = '';
  if (isSlotType && spaceId && graphId) {
    // hasKGGraphURI → enclosing entity
    const entityGrouping = properties.find((p) => p.predicate === HAS_KG_GRAPH_URI);
    // hasFrameGraphURI → enclosing frame
    const frameGrouping = properties.find((p) => p.predicate === HAS_FRAME_GRAPH_URI);
    if (entityGrouping?.object) {
      typedDetailPath = `/space/${encodeURIComponent(spaceId)}/graph/${encodeURIComponent(decodedGraphId)}/entity/${encodeURIComponent(entityGrouping.object)}`;
      typedDetailLabel = 'View Enclosing Entity';
    } else if (frameGrouping?.object) {
      typedDetailPath = `/space/${encodeURIComponent(spaceId)}/graph/${encodeURIComponent(decodedGraphId)}/frame/${encodeURIComponent(frameGrouping.object)}`;
      typedDetailLabel = 'View Enclosing Frame';
    }
  } else {
    const typeLink = rdfTypes.map((t) => TYPE_ROUTE_MAP[t]).find((entry) => entry != null) || null;
    if (typeLink && spaceId && graphId) {
      if (typeLink.pathSegment === 'kg-types') {
        // KG Types use an absolute route, not relative to space/graph
        typedDetailPath = `/kg-types/${encodeURIComponent(decodedUri)}?mode=view`;
      } else {
        typedDetailPath = `/space/${encodeURIComponent(spaceId)}/graph/${encodeURIComponent(decodedGraphId)}/${typeLink.pathSegment}/${encodeURIComponent(decodedUri)}`;
      }
      typedDetailLabel = `View as ${typeLink.label}`;
    }
  }

  return (
    <div data-testid="search-result-detail-page">
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/semantic-search" icon={HiSearch}>Semantic Search</BreadcrumbItem>
        <BreadcrumbItem>Search Result Detail</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white truncate max-w-3xl" title={decodedUri}>
            {shortenUri(decodedUri)}
          </h1>
          <p className="text-sm text-gray-500 font-mono truncate max-w-3xl">{decodedUri}</p>
        </div>
        <div className="flex gap-2">
          {typedDetailPath && (
            <Button size="sm" color="blue" onClick={() => navigate(typedDetailPath!)}>
              <HiExternalLink className="mr-1.5 h-4 w-4" />
              {typedDetailLabel}
            </Button>
          )}
          <Button size="sm" color="gray" onClick={() => navigate(-1)}>
            ← Back
          </Button>
        </div>
      </div>

      {/* Metadata badges */}
      <div className="flex gap-2 mb-4">
        <Badge color="gray">Space: {spaceId}</Badge>
        <Badge color="gray">Graph: {shortenUri(decodedGraphId)}</Badge>
        {rdfTypes.map((t) => (
          <Badge key={t} color="info">{shortenUri(t)}</Badge>
        ))}
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : properties.length === 0 ? (
        <Card>
          <p className="text-gray-500">No quads found for this subject.</p>
        </Card>
      ) : (
        <Card>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold">Properties ({properties.length})</h2>
          </div>
          <div className="overflow-x-auto">
            <Table striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="w-1/3">Predicate</TableHeadCell>
                  <TableHeadCell>Value</TableHeadCell>
                  <TableHeadCell className="w-20">Type</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {properties.map((prop, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-xs text-gray-700 dark:text-gray-300" title={prop.predicate}>
                      {shortenUri(prop.predicate)}
                    </TableCell>
                    <TableCell className="text-sm break-all" title={prop.object}>
                      {prop.object_type === 'uri' ? (
                        <span className="font-mono text-xs text-blue-600 dark:text-blue-400">{prop.object}</span>
                      ) : (
                        <span>{prop.object.length > 200 ? prop.object.slice(0, 200) + '…' : prop.object}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge color={prop.object_type === 'uri' ? 'purple' : 'gray'} size="xs">
                        {prop.object_type}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      )}
    </div>
  );
};

export default SearchResultDetail;
