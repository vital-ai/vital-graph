/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * API Service for VitalGraph with JWT authentication.
 *
 * All API calls delegate to the typed @vital-ai/vitalgraph-client via a
 * browser-adapted FrontendVitalGraphClient. The singleton `vgClient` handles
 * URL construction, query-parameter serialization, and auth-header injection.
 */

import { vgClient } from './FrontendVitalGraphClient';
import { type QuadResponse } from '../utils/QuadUtils';

export { vgClient };

export class ApiService {
  /** The underlying typed TS client — use directly for advanced calls. */
  readonly client = vgClient;

  // ─── Spaces ───────────────────────────────────────────────────────

  async getSpaces(): Promise<any[]> {
    const data = await vgClient.spaces.list();
    return (data as any).spaces || [];
  }

  async createSpace(spaceData: any): Promise<any> {
    return vgClient.spaces.create(spaceData);
  }

  async updateSpace(spaceId: string, spaceData: any): Promise<any> {
    return vgClient.spaces.update(spaceId, spaceData);
  }

  async deleteSpace(spaceId: string): Promise<any> {
    return vgClient.spaces.delete(spaceId);
  }

  async getSpaceInfo(spaceId: string): Promise<any> {
    return vgClient.spaces.getInfo(spaceId);
  }

  async getSpaceAnalytics(spaceId: string, refresh = false, graphUri?: string): Promise<any> {
    return vgClient.spaces.getAnalytics(spaceId, { refresh: refresh || undefined, graph_uri: graphUri });
  }

  // ─── Metrics ──────────────────────────────────────────────────────

  async getSpaceMetrics(spaceId: string, range = 'realtime'): Promise<any> {
    return vgClient.metrics.getMetrics(spaceId, range);
  }

  async getSpaceSlowQueries(spaceId: string, limit = 50): Promise<any> {
    return vgClient.metrics.getSlowQueries(spaceId, limit);
  }

  // ─── SPARQL ───────────────────────────────────────────────────────

  async executeSparqlQuery(spaceId: string, query: string): Promise<any> {
    return vgClient.sparql.query(spaceId, query);
  }

  async executeSparqlUpdate(spaceId: string, update: string): Promise<any> {
    return vgClient.sparql.update(spaceId, update);
  }

  // ─── Graphs ───────────────────────────────────────────────────────

  async getGraphs(spaceId: string): Promise<any[]> {
    return vgClient.graphs.list(spaceId) as any;
  }

  async getGraphCounts(spaceId: string, graphId: string): Promise<{ entity_count: number; frame_count: number; relation_count: number }> {
    return vgClient.graphs.getCounts(spaceId, graphId) as any;
  }

  async getGraph(spaceId: string, graphUri: string): Promise<any> {
    return vgClient.graphs.getInfo(spaceId, graphUri);
  }

  async createGraph(spaceId: string, graphUri: string): Promise<any> {
    return vgClient.graphs.create(spaceId, graphUri);
  }

  async deleteGraph(spaceId: string, graphUri: string, _silent = false): Promise<any> {
    return vgClient.graphs.delete(spaceId, graphUri);
  }

  async executeGraphOperation(spaceId: string, operation: string, targetGraphUri?: string, sourceGraphUri?: string, silent = false): Promise<any> {
    return vgClient.graphs.executeOperation(spaceId, {
      operation,
      target_graph_uri: targetGraphUri,
      source_graph_uri: sourceGraphUri,
      silent,
    });
  }

  // ─── Triples ──────────────────────────────────────────────────────

  async getTriples(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    subject?: string;
    predicate?: string;
    object?: string;
    object_filter?: string;
  } = {}): Promise<QuadResponse> {
    return vgClient.triples.list(
      spaceId,
      graphId,
      options.subject,
      options.page_size ?? 100,
      options.offset ?? 0,
    ) as any;
  }

  async addTriples(spaceId: string, graphId: string, data: any): Promise<any> {
    return vgClient.triples.add(spaceId, graphId, data);
  }

  async deleteTriples(spaceId: string, graphId: string, data: any): Promise<any> {
    return vgClient.triples.delete(spaceId, graphId, data);
  }

  // ─── Objects ──────────────────────────────────────────────────────

  async getObjects(spaceId: string, graphId: string, options: {
    page_size?: number; offset?: number; search?: string;
  } = {}): Promise<QuadResponse> {
    return vgClient.objects.list(
      spaceId, graphId,
      options.page_size ?? 10, options.offset ?? 0,
      options.search,
    ) as any;
  }

  async getObject(spaceId: string, graphId: string, objectUri: string): Promise<QuadResponse> {
    return vgClient.objects.get(spaceId, graphId, objectUri) as any;
  }

  // ─── KG Entities ──────────────────────────────────────────────────

  async getEntities(spaceId: string, graphId: string, options: {
    page_size?: number; offset?: number; search?: string;
    entity_type_uri?: string; sort_by?: string; sort_order?: 'asc' | 'desc';
  } = {}): Promise<QuadResponse> {
    return vgClient.kgentities.list(spaceId, graphId, {
      pageSize: options.page_size,
      offset: options.offset,
      search: options.search,
      entityTypeUri: options.entity_type_uri,
      sortBy: options.sort_by,
      sortOrder: options.sort_order,
    }) as any;
  }

  async getEntity(spaceId: string, graphId: string, entityUri: string): Promise<QuadResponse> {
    return vgClient.kgentities.get(spaceId, graphId, entityUri) as any;
  }

  async getEntityGraph(spaceId: string, graphId: string, entityUri: string): Promise<QuadResponse> {
    return vgClient.kgentities.get(spaceId, graphId, entityUri, true) as any;
  }

  async deleteEntity(spaceId: string, graphId: string, entityUri: string): Promise<any> {
    return vgClient.kgentities.delete(spaceId, graphId, entityUri);
  }

  // ─── KG Frames ────────────────────────────────────────────────────

  async getFrames(spaceId: string, graphId: string, options: {
    page_size?: number; offset?: number; search?: string;
    sort_by?: string; sort_order?: 'asc' | 'desc';
    form_type?: string;
    frame_type_uri?: string;
    status?: string;
    exclude_status?: string;
    created_after?: string;
    created_before?: string;
    modified_after?: string;
    modified_before?: string;
  } = {}): Promise<QuadResponse> {
    const { page_size, offset, search } = options;
    // Note: filter opts (sort, frame_type, status, etc.) not yet supported by TS client
    return vgClient.kgframes.list(
      spaceId, graphId,
      page_size ?? 10, offset ?? 0,
      search,
    ) as any;
  }

  async getFrame(spaceId: string, graphId: string, frameUri: string): Promise<QuadResponse> {
    return vgClient.kgframes.get(spaceId, graphId, frameUri) as any;
  }

  async deleteFrame(spaceId: string, graphId: string, frameUri: string): Promise<any> {
    return vgClient.kgframes.delete(spaceId, graphId, frameUri);
  }

  // ─── KG Relations ─────────────────────────────────────────────────

  async getRelations(spaceId: string, graphId: string, options: {
    page_size?: number; offset?: number;
    entity_source_uri?: string; entity_destination_uri?: string;
    relation_type_uri?: string; direction?: string;
  } = {}): Promise<QuadResponse> {
    return vgClient.kgrelations.list(
      spaceId, graphId,
      options.page_size ?? 10, options.offset ?? 0,
    ) as any;
  }

  async deleteRelation(spaceId: string, graphId: string, relationUri: string): Promise<any> {
    return vgClient.kgrelations.delete(spaceId, graphId, relationUri);
  }

  // ─── KG Types ─────────────────────────────────────────────────────
  // NOTE: vgClient.kgtypes is cast to `any` because the locally installed
  // @vital-ai/vitalgraph-client may be stale. The TS client source has all
  // methods; Docker rebuild updates node_modules.
  private get _kgtypes(): any { return vgClient.kgtypes; }

  async getKGTypes(spaceId: string, options: {
    page_size?: number; offset?: number; search?: string; type_uri?: string;
  } = {}): Promise<any> {
    return this._kgtypes.list(
      spaceId,
      options.page_size ?? 10, options.offset ?? 0,
      options.search,
      options.type_uri,
    );
  }

  async getKGType(spaceId: string, typeUri: string): Promise<any> {
    return this._kgtypes.get(spaceId, typeUri);
  }

  async getKGTypeRelationships(spaceId: string, typeUri: string): Promise<any> {
    return this._kgtypes.getRelationships(spaceId, typeUri);
  }

  async saveKGType(spaceId: string, typeData: any): Promise<any> {
    return this._kgtypes.create(spaceId, typeData);
  }

  async deleteKGType(spaceId: string, typeUri: string): Promise<any> {
    return this._kgtypes.delete(spaceId, typeUri);
  }

  async createKGTypeRelationship(spaceId: string, typeUri: string, edgeType: string, targetUri: string): Promise<any> {
    return this._kgtypes.createRelationship(spaceId, typeUri, edgeType, targetUri);
  }

  async deleteKGTypeRelationship(spaceId: string, typeUri: string, edgeUri: string): Promise<any> {
    return this._kgtypes.deleteRelationship(spaceId, typeUri, edgeUri);
  }

  async getKGTypeDocumentation(spaceId: string, typeUri: string): Promise<any> {
    return this._kgtypes.getDocumentation(spaceId, typeUri);
  }

  async updateKGTypeDocumentation(spaceId: string, typeUri: string, content: string): Promise<any> {
    return this._kgtypes.updateDocumentation(spaceId, typeUri, content);
  }

  async deleteKGTypeDocumentation(spaceId: string, typeUri: string): Promise<any> {
    return this._kgtypes.deleteDocumentation(spaceId, typeUri);
  }

  async searchKGTypes(spaceId: string, query: string, options?: {
    type?: string; search_mode?: 'keyword' | 'fts' | 'vector' | 'hybrid'; alpha?: number;
  }): Promise<any> {
    return this._kgtypes.search(spaceId, query, options);
  }

  // ─── Files ────────────────────────────────────────────────────────

  async getFiles(spaceId: string, graphId: string, options: {
    page_size?: number; offset?: number; search?: string;
  } = {}): Promise<QuadResponse> {
    return vgClient.files.list(
      spaceId, graphId,
      options.page_size ?? 100, options.offset ?? 0,
      options.search,
    ) as any;
  }

  async getFile(spaceId: string, _graphId: string, fileUri: string): Promise<QuadResponse> {
    return vgClient.files.get(spaceId, fileUri) as any;
  }

  async uploadFile(spaceId: string, graphId: string, fileUri: string, file: File, metadata?: Record<string, string>): Promise<any> {
    return vgClient.files.upload(spaceId, graphId, fileUri, file, file.name, { metadata });
  }

  async downloadFile(spaceId: string, graphId: string, fileUri: string): Promise<Blob> {
    const buffer = await vgClient.files.download(spaceId, fileUri, graphId);
    return new Blob([buffer]);
  }

  async deleteFile(spaceId: string, _graphId: string, fileUri: string): Promise<any> {
    return vgClient.files.delete(spaceId, fileUri);
  }

  // ─── Users ────────────────────────────────────────────────────────

  async getUsers(): Promise<any[]> {
    const data = await vgClient.users.list();
    return (data as any).users || [];
  }

  async getUser(userId: string): Promise<any> {
    return vgClient.users.get(userId);
  }

  async createUser(userData: { username: string; password: string; role?: string; email?: string; full_name?: string }): Promise<any> {
    return vgClient.users.create(userData);
  }

  async updateUser(userId: string, userData: Record<string, unknown>): Promise<any> {
    return vgClient.users.update(userId, userData);
  }

  async deleteUser(userId: string): Promise<any> {
    return vgClient.users.delete(userId);
  }

  // ─── User Space Access ──────────────────────────────────────────

  async getUserSpaces(username: string): Promise<{ username: string; spaces: Record<string, string> }> {
    return vgClient.users.getSpaceAccess(username) as any;
  }

  async grantSpaceAccess(username: string, spaceId: string, accessLevel: 'rw' | 'r'): Promise<{ message: string }> {
    return vgClient.users.grantSpaceAccess(username, spaceId, { access_level: accessLevel }) as any;
  }

  async revokeSpaceAccess(username: string, spaceId: string): Promise<{ message: string }> {
    return vgClient.users.revokeSpaceAccess(username, spaceId) as any;
  }

  // ─── API Keys ────────────────────────────────────────────────────

  async listApiKeys(username?: string): Promise<{ keys: any[]; total_count: number }> {
    return vgClient.apiKeys.list(username) as any;
  }

  async createApiKey(name: string, expiresInDays?: number, username?: string): Promise<{
    key_id: string; key: string; prefix: string; name: string;
    username: string; expires_at: string | null; message: string;
  }> {
    const extra: Record<string, unknown> = {};
    if (expiresInDays) extra.expires_in_days = expiresInDays;
    if (username) extra.username = username;
    return vgClient.apiKeys.create(name, extra) as any;
  }

  async revokeApiKey(keyId: string): Promise<{ message: string; key_id: string }> {
    return vgClient.apiKeys.delete(keyId) as any;
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<{ message: string; tokens_invalidated: boolean }> {
    return vgClient.users.changePassword(currentPassword, newPassword) as any;
  }

  // ─── Admin / Health ──────────────────────────────────────────────

  async healthCheck(): Promise<{ status: string }> {
    return vgClient.admin.health() as any;
  }

  async cacheStats(): Promise<{ entity_graph_cache: Record<string, unknown> }> {
    return vgClient.admin.cacheStats() as any;
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async listProcesses(_options: { process_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<any> {
    return vgClient.processes.list();
  }

  async getSchedulerStatus(): Promise<{ enabled: boolean; running: boolean; jobs: Record<string, unknown>; active_locks: number }> {
    return vgClient.processes.getScheduler() as any;
  }

  async triggerProcess(processType: string, spaceId?: string): Promise<{ triggered: boolean; message: string; result?: Record<string, unknown> }> {
    return vgClient.processes.trigger(processType, spaceId ? { space_id: spaceId } : undefined) as any;
  }

  async adminResync(spaceId: string): Promise<{ space_id: string; edge_rows: number; frame_entity_rows: number; pred_stats_rows: number; quad_stats_rows: number; elapsed_ms: number }> {
    return vgClient.admin.resync(spaceId) as any;
  }

  // ─── KG Queries ────────────────────────────────────────────────────

  async kgQuery(spaceId: string, graphId: string, body: Record<string, unknown>): Promise<any> {
    return vgClient.kgqueries.query(spaceId, graphId, body);
  }

  // ─── Audit Log ─────────────────────────────────────────────────────

  async getAuditLog(options: { event?: string; actor?: string; level?: string; last?: string; limit?: number; offset?: number } = {}): Promise<{
    entries: { id: number; timestamp: string; event: string; actor: string; target: string | null; ip: string | null; user_agent: string | null; details: Record<string, unknown> | null; level: string }[];
    total_count: number; limit: number; offset: number;
  }> {
    return vgClient.admin.getAuditLog(options) as any;
  }

  // ─── Entity Registry ───────────────────────────────────────────────

  async listRegistryEntities(options: { query?: string; entity_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<any> {
    return vgClient.entityRegistry.searchEntities({
      query: options.query,
      typeKey: options.entity_type,
      status: options.status,
      pageSize: options.limit,
      page: options.offset && options.limit ? Math.floor(options.offset / options.limit) + 1 : undefined,
    });
  }

  async getRegistryEntity(entityId: string): Promise<any> {
    return vgClient.entityRegistry.getEntity(entityId);
  }

  async createRegistryEntity(data: Record<string, unknown>): Promise<any> {
    return vgClient.entityRegistry.createEntity(data);
  }

  async updateRegistryEntity(entityId: string, data: Record<string, unknown>): Promise<any> {
    return vgClient.entityRegistry.updateEntity(entityId, data);
  }

  async deleteRegistryEntity(entityId: string): Promise<any> {
    return vgClient.entityRegistry.deleteEntity(entityId);
  }

  async getEntityAliases(entityId: string): Promise<any> {
    return vgClient.entityRegistry.listAliases(entityId);
  }

  async getEntityIdentifiers(entityId: string): Promise<any> {
    return vgClient.entityRegistry.listIdentifiers(entityId);
  }

  async getEntityCategories(entityId: string): Promise<any> {
    return vgClient.entityRegistry.listEntityCategories(entityId);
  }

  async getEntityLocations(entityId: string): Promise<any> {
    return vgClient.entityRegistry.listLocations(entityId);
  }

  async findSimilarEntities(options: { name: string; type_key?: string; limit?: number; min_score?: number }): Promise<any> {
    return vgClient.entityRegistry.findSimilar({
      name: options.name,
      typeKey: options.type_key,
      limit: options.limit,
      minScore: options.min_score,
    });
  }

  async searchRegistryEntity(options: { q?: string; latitude?: number; longitude?: number; radius_km?: number; limit?: number; min_certainty?: number }): Promise<any> {
    return vgClient.entityRegistry.searchEntity({
      q: options.q,
      latitude: options.latitude,
      longitude: options.longitude,
      radiusKm: options.radius_km,
      limit: options.limit,
      minCertainty: options.min_certainty,
    });
  }

  // ─── Agent Registry ────────────────────────────────────────────────

  async listAgentTypes(): Promise<any[]> {
    return vgClient.agentRegistry.listAgentTypes() as any;
  }

  async listAgents(options: { query?: string; agent_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<any> {
    return vgClient.agentRegistry.searchAgents({
      query: options.query,
      typeKey: options.agent_type,
      status: options.status,
      pageSize: options.limit,
      page: options.offset && options.limit ? Math.floor(options.offset / options.limit) + 1 : undefined,
    });
  }

  async getAgent(agentId: string): Promise<any> {
    return vgClient.agentRegistry.getAgent(agentId);
  }

  async createAgent(data: Record<string, unknown>): Promise<any> {
    return vgClient.agentRegistry.createAgent(data);
  }

  async updateAgent(agentId: string, data: Record<string, unknown>): Promise<any> {
    return vgClient.agentRegistry.updateAgent(agentId, data);
  }

  async deleteAgent(agentId: string): Promise<any> {
    return vgClient.agentRegistry.deleteAgent(agentId);
  }

  async changeAgentStatus(agentId: string, status: string, reason?: string): Promise<any> {
    return vgClient.agentRegistry.changeAgentStatus(agentId, { status, reason });
  }

  async getAgentEndpoints(agentId: string): Promise<any[]> {
    return vgClient.agentRegistry.listEndpoints(agentId) as any;
  }

  async getAgentFunctions(agentId: string): Promise<any[]> {
    return vgClient.agentRegistry.listFunctions(agentId) as any;
  }

  async getAgentChangelog(agentId: string, limit = 50): Promise<any> {
    return vgClient.agentRegistry.getChangeLog(agentId, limit);
  }

  // ─── KGDocument Segmentation ───────────────────────────────────────

  async getSegmentationStatus(spaceId: string, documentUri?: string, status?: string, limit = 50, offset = 0): Promise<any> {
    return vgClient.kgdocuments.getSegmentationStatus(spaceId, {
      document_uri: documentUri,
      status,
      limit,
      offset,
    });
  }

  async segmentDocument(spaceId: string, graphId: string, documentUri: string, segmentMethodUri?: string, maxSegmentTokens?: number): Promise<any> {
    return vgClient.kgdocuments.segment(spaceId, graphId, {
      document_uri: documentUri,
      segment_method_uri: segmentMethodUri,
      max_segment_tokens: maxSegmentTokens,
    });
  }
  // ─── Ontology ──────────────────────────────────────────────────────
  // NOTE: vgClient.ontology may not be typed until client package is rebuilt.
  private get _ontology(): any { return (vgClient as any).ontology; }

  async getOntologyProperties(classUri: string): Promise<{ uri: string; local_name?: string; short_name?: string; property_class?: string }[]> {
    const resp = await this._ontology.getProperties(classUri);
    return resp.properties || [];
  }

  async getOntologyClasses(): Promise<string[]> {
    const resp = await this._ontology.getClasses();
    return resp.classes || [];
  }
}

// Create singleton instance
export const apiService = new ApiService();
export default apiService;
