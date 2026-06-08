/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * API Service for VitalGraph with JWT authentication.
 * 
 * This service provides authenticated API calls with automatic token refresh
 * and proper Bearer token authentication headers.
 */

import { authService } from './AuthService';
import { type QuadResponse } from '../utils/QuadUtils';

export class ApiService {
  private baseUrl: string;

  constructor() {
    // Use current origin for API calls
    this.baseUrl = window.location.origin;
  }

  /**
   * Make authenticated API request with automatic token refresh
   */
  async makeRequest(url: string, options: RequestInit = {}): Promise<Response> {
    const fullUrl = url.startsWith('http') ? url : `${this.baseUrl}${url}`;
    
    // Get current token and add to headers
    const authHeader = authService.getAuthHeader();
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
      ...authHeader,
    };

    const response = await fetch(fullUrl, {
      ...options,
      headers
    });

    // Handle 401 responses (token expired)
    if (response.status === 401 && 'Authorization' in authHeader) {
      console.log('🔄 Received 401, attempting token refresh...');
      
      const refreshed = await authService.refreshAccessToken();
      if (refreshed) {
        // Retry request with new token
        const newAuthHeader = authService.getAuthHeader();
        const retryHeaders = {
          ...headers,
          ...newAuthHeader
        };
        
        console.log('🔄 Retrying request with refreshed token...');
        return fetch(fullUrl, { ...options, headers: retryHeaders });
      }
      
      // If refresh failed, redirect to login
      console.log('🚪 Token refresh failed, redirecting to login');
      window.location.href = '/login';
    }

    return response;
  }

  /**
   * GET request with authentication
   */
  async get(url: string, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'GET'
    });
  }

  /**
   * POST request with authentication
   */
  async post(url: string, data?: any, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  /**
   * PUT request with authentication
   */
  async put(url: string, data?: any, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  /**
   * DELETE request with authentication
   */
  async delete(url: string, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'DELETE'
    });
  }

  /**
   * PATCH request with authentication
   */
  async patch(url: string, data?: any, options: RequestInit = {}): Promise<Response> {
    return this.makeRequest(url, {
      ...options,
      method: 'PATCH',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  // Convenience methods for common API calls

  /**
   * Get spaces
   */
  async getSpaces(): Promise<any[]> {
    const response = await this.get('/api/spaces');
    if (response.ok) {
      const data = await response.json();
      // Extract spaces array from SpacesListResponse structure
      return data.spaces || [];
    }
    throw new Error(`Failed to get spaces: ${response.status} ${response.statusText}`);
  }

  /**
   * Get users
   */
  async getUsers(): Promise<any[]> {
    const response = await this.get('/api/users');
    if (response.ok) {
      const data = await response.json();
      // Extract users array from UsersListResponse structure
      return data.users || [];
    }
    throw new Error(`Failed to get users: ${response.status} ${response.statusText}`);
  }

  /**
   * Create space
   */
  async createSpace(spaceData: any): Promise<any> {
    const response = await this.post('/api/spaces', spaceData);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to create space: ${response.status} ${response.statusText}`);
  }

  /**
   * Update space
   */
  async updateSpace(spaceId: string, spaceData: any): Promise<any> {
    const response = await this.put(`/api/spaces/${spaceId}`, spaceData);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to update space: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete space
   */
  async deleteSpace(spaceId: string): Promise<any> {
    const response = await this.delete(`/api/spaces/${spaceId}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to delete space: ${response.status} ${response.statusText}`);
  }

  /**
   * Get space info (basic statistics)
   */
  async getSpaceInfo(spaceId: string): Promise<any> {
    const response = await this.get(`/api/spaces/${spaceId}/info`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get space info: ${response.status} ${response.statusText}`);
  }

  /**
   * Get space analytics (KG type distributions, relations, etc.)
   */
  async getSpaceAnalytics(spaceId: string, refresh: boolean = false, graphUri?: string): Promise<any> {
    const params = new URLSearchParams();
    if (refresh) params.set('refresh', 'true');
    if (graphUri) params.set('graph_uri', graphUri);
    const qs = params.toString();
    const url = `/api/spaces/${spaceId}/analytics${qs ? '?' + qs : ''}`;
    const response = await this.get(url);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get space analytics: ${response.status} ${response.statusText}`);
  }

  /**
   * Get space query metrics (time-series request/latency data)
   */
  async getSpaceMetrics(spaceId: string, range: string = 'realtime'): Promise<any> {
    const response = await this.get(`/api/spaces/${spaceId}/metrics?range=${range}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get space metrics: ${response.status} ${response.statusText}`);
  }

  /**
   * Get recent slow queries for a space
   */
  async getSpaceSlowQueries(spaceId: string, limit: number = 50): Promise<any> {
    const response = await this.get(`/api/spaces/${spaceId}/metrics/slow?limit=${limit}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get slow queries: ${response.status} ${response.statusText}`);
  }

  /**
   * Execute SPARQL query
   */
  async executeSparqlQuery(spaceId: string, query: string): Promise<any> {
    const response = await this.post(`/api/graphs/sparql/${spaceId}/query`, { query });
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to execute SPARQL query: ${response.status} ${response.statusText}`);
  }

  /**
   * Execute SPARQL update (INSERT, DELETE, LOAD, CLEAR, etc.)
   */
  async executeSparqlUpdate(spaceId: string, update: string): Promise<any> {
    const response = await this.post(`/api/graphs/sparql/${spaceId}/update`, { update });
    if (response.ok) {
      return response.json();
    }
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `SPARQL update failed: ${response.status} ${response.statusText}`);
  }

  // Graph management methods

  /**
   * Get graphs for a space
   */
  async getGraphs(spaceId: string): Promise<any[]> {
    const response = await this.get(`/api/graphs/${spaceId}/graphs`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get graphs: ${response.status} ${response.statusText}`);
  }

  /**
   * Get specific graph info
   */
  async getGraph(spaceId: string, graphUri: string): Promise<any> {
    const encodedGraphUri = encodeURIComponent(graphUri);
    const response = await this.get(`/api/graphs/${spaceId}/graph/${encodedGraphUri}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get graph: ${response.status} ${response.statusText}`);
  }

  /**
   * Create a new graph
   */
  async createGraph(spaceId: string, graphUri: string): Promise<any> {
    const encodedGraphUri = encodeURIComponent(graphUri);
    const response = await this.put(`/api/graphs/${spaceId}/graph/${encodedGraphUri}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to create graph: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a graph
   */
  async deleteGraph(spaceId: string, graphUri: string, silent: boolean = false): Promise<any> {
    const encodedGraphUri = encodeURIComponent(graphUri);
    const url = silent 
      ? `/api/graphs/${spaceId}/graph/${encodedGraphUri}?silent=true`
      : `/api/graphs/${spaceId}/graph/${encodedGraphUri}`;
    const response = await this.delete(url);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to delete graph: ${response.status} ${response.statusText}`);
  }

  /**
   * Execute graph operation (CREATE, DROP, CLEAR, etc.)
   */
  async executeGraphOperation(spaceId: string, operation: string, targetGraphUri?: string, sourceGraphUri?: string, silent: boolean = false): Promise<any> {
    const requestBody = {
      operation,
      target_graph_uri: targetGraphUri,
      source_graph_uri: sourceGraphUri,
      silent
    };
    
    const response = await this.post(`/api/graphs/${spaceId}/graph`, requestBody);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to execute graph operation: ${response.status} ${response.statusText}`);
  }

  // Triples management methods

  /**
   * Get triples for a specific graph with pagination and filtering
   */
  async getTriples(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    subject?: string;
    predicate?: string;
    object?: string;
    object_filter?: string;
  } = {}): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.append('space_id', spaceId);
    params.append('graph_id', graphId);
    
    if (options.page_size) params.append('page_size', options.page_size.toString());
    if (options.offset) params.append('offset', options.offset.toString());
    if (options.subject) params.append('subject', options.subject);
    if (options.predicate) params.append('predicate', options.predicate);
    if (options.object) params.append('object', options.object);
    if (options.object_filter) params.append('object_filter', options.object_filter);

    const response = await this.get(`/api/graphs/triples?${params.toString()}`);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to get triples: ${response.status} ${response.statusText}`);
  }

  /**
   * Add triples via quads array
   */
  async addTriples(spaceId: string, graphId: string, data: any): Promise<any> {
    const params = new URLSearchParams();
    params.append('space_id', spaceId);
    params.append('graph_id', graphId);

    const response = await this.post(`/api/graphs/triples?${params.toString()}`, data);
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to add triples: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete triples via quads array
   */
  async deleteTriples(spaceId: string, graphId: string, data: any): Promise<any> {
    const params = new URLSearchParams();
    params.append('space_id', spaceId);
    params.append('graph_id', graphId);

    const response = await this.delete(`/api/graphs/triples?${params.toString()}`, {
      body: JSON.stringify(data)
    });
    if (response.ok) {
      return response.json();
    }
    throw new Error(`Failed to delete triples: ${response.status} ${response.statusText}`);
  }

  // Object/Entity/Frame methods

  /**
   * Get graph objects for a space+graph with pagination
   */
  async getObjects(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    search?: string;
  } = {}): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    if (options.page_size) params.set('page_size', options.page_size.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    if (options.search) params.set('search', options.search);

    const response = await this.get(`/api/graphs/objects?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get objects: ${response.status} ${response.statusText}`);
  }

  /**
   * Get a single object by URI
   */
  async getObject(spaceId: string, graphId: string, objectUri: string): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', objectUri);

    const response = await this.get(`/api/graphs/objects?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get object: ${response.status} ${response.statusText}`);
  }

  /**
   * Get KG entities for a space+graph with pagination
   */
  async getEntities(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    search?: string;
    entity_type_uri?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  } = {}): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    if (options.page_size) params.set('page_size', options.page_size.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    if (options.search) params.set('search', options.search);
    if (options.entity_type_uri) params.set('entity_type_uri', options.entity_type_uri);
    if (options.sort_by) params.set('sort_by', options.sort_by);
    if (options.sort_order) params.set('sort_order', options.sort_order);

    const response = await this.get(`/api/graphs/kgentities?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entities: ${response.status} ${response.statusText}`);
  }

  /**
   * Get a single KG entity by URI
   */
  async getEntity(spaceId: string, graphId: string, entityUri: string): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', entityUri);

    const response = await this.get(`/api/graphs/kgentities?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entity: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a KG entity by URI
   */
  async deleteEntity(spaceId: string, graphId: string, entityUri: string): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', entityUri);

    const response = await this.delete(`/api/graphs/kgentities?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete entity: ${response.status} ${response.statusText}`);
  }

  /**
   * Get KG frames for a space+graph with pagination
   */
  async getFrames(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  } = {}): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    if (options.page_size) params.set('page_size', options.page_size.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    if (options.search) params.set('search', options.search);
    if (options.sort_by) params.set('sort_by', options.sort_by);
    if (options.sort_order) params.set('sort_order', options.sort_order);

    const response = await this.get(`/api/graphs/kgframes?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get frames: ${response.status} ${response.statusText}`);
  }

  /**
   * Get a single KG frame by URI
   */
  async getFrame(spaceId: string, graphId: string, frameUri: string): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', frameUri);

    const response = await this.get(`/api/graphs/kgframes?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get frame: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a KG frame by URI
   */
  async deleteFrame(spaceId: string, graphId: string, frameUri: string): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', frameUri);

    const response = await this.delete(`/api/graphs/kgframes?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete frame: ${response.status} ${response.statusText}`);
  }

  // KG Relations methods

  async getRelations(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    entity_source_uri?: string;
    entity_destination_uri?: string;
    relation_type_uri?: string;
    direction?: string;
  } = {}): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    if (options.page_size) params.set('page_size', options.page_size.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    if (options.entity_source_uri) params.set('entity_source_uri', options.entity_source_uri);
    if (options.entity_destination_uri) params.set('entity_destination_uri', options.entity_destination_uri);
    if (options.relation_type_uri) params.set('relation_type_uri', options.relation_type_uri);
    if (options.direction) params.set('direction', options.direction);

    const response = await this.get(`/api/graphs/kgrelations?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get relations: ${response.status} ${response.statusText}`);
  }

  async deleteRelation(spaceId: string, graphId: string, relationUri: string): Promise<any> {
    const response = await this.makeRequest(
      `/api/graphs/kgrelations?space_id=${encodeURIComponent(spaceId)}&graph_id=${encodeURIComponent(graphId)}`,
      { method: 'DELETE', body: JSON.stringify({ relation_uris: [relationUri] }) }
    );
    if (response.ok) return response.json();
    throw new Error(`Failed to delete relation: ${response.status} ${response.statusText}`);
  }

  // KG Types methods

  /**
   * Get KG types for a space+graph
   */
  async getKGTypes(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    search?: string;
  } = {}): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    if (options.page_size) params.set('page_size', options.page_size.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    if (options.search) params.set('search', options.search);

    const response = await this.get(`/api/graphs/kgtypes?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get KG types: ${response.status} ${response.statusText}`);
  }

  /**
   * Get a single KG type by URI
   */
  async getKGType(spaceId: string, graphId: string, typeUri: string): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', typeUri);

    const response = await this.get(`/api/graphs/kgtypes?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get KG type: ${response.status} ${response.statusText}`);
  }

  /**
   * Create or update a KG type
   */
  async saveKGType(spaceId: string, graphId: string, typeData: any): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);

    const response = await this.post(`/api/graphs/kgtypes?${params.toString()}`, typeData);
    if (response.ok) return response.json();
    throw new Error(`Failed to save KG type: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a KG type by URI
   */
  async deleteKGType(spaceId: string, graphId: string, typeUri: string): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', typeUri);

    const response = await this.delete(`/api/graphs/kgtypes?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete KG type: ${response.status} ${response.statusText}`);
  }

  // File methods

  /**
   * Get files for a space+graph with pagination
   */
  async getFiles(spaceId: string, graphId: string, options: {
    page_size?: number;
    offset?: number;
    search?: string;
  } = {}): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    if (options.page_size) params.set('page_size', options.page_size.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    if (options.search) params.set('search', options.search);

    const response = await this.get(`/api/files?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get files: ${response.status} ${response.statusText}`);
  }

  /**
   * Get a single file by URI
   */
  async getFile(spaceId: string, graphId: string, fileUri: string): Promise<QuadResponse> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', fileUri);

    const response = await this.get(`/api/files?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get file: ${response.status} ${response.statusText}`);
  }

  /**
   * Upload a file
   */
  async uploadFile(spaceId: string, graphId: string, file: File, metadata?: Record<string, string>): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    if (metadata) {
      Object.entries(metadata).forEach(([key, value]) => {
        formData.append(key, value);
      });
    }

    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);

    // Override Content-Type to let browser set multipart boundary
    const response = await this.makeRequest(`/api/files/upload?${params.toString()}`, {
      method: 'POST',
      body: formData,
      headers: { 'Content-Type': '' } // Will be overridden by makeRequest but FormData needs no explicit type
    });
    if (response.ok) return response.json();
    throw new Error(`Failed to upload file: ${response.status} ${response.statusText}`);
  }

  /**
   * Download a file by URI
   */
  async downloadFile(spaceId: string, graphId: string, fileUri: string): Promise<Blob> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', fileUri);

    const response = await this.get(`/api/files/download?${params.toString()}`);
    if (response.ok) return response.blob();
    throw new Error(`Failed to download file: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a file by URI
   */
  async deleteFile(spaceId: string, graphId: string, fileUri: string): Promise<any> {
    const params = new URLSearchParams();
    params.set('space_id', spaceId);
    params.set('graph_id', graphId);
    params.set('uri', fileUri);

    const response = await this.delete(`/api/files?${params.toString()}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete file: ${response.status} ${response.statusText}`);
  }

  // User methods

  /**
   * Get a specific user by ID/username
   */
  async getUser(userId: string): Promise<any> {
    const response = await this.get(`/api/users/${userId}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get user: ${response.status} ${response.statusText}`);
  }

  /**
   * Create a new user
   */
  async createUser(userData: { username: string; password: string; role?: string; email?: string; full_name?: string }): Promise<any> {
    const response = await this.post('/api/users', userData);
    if (response.ok) return response.json();
    throw new Error(`Failed to create user: ${response.status} ${response.statusText}`);
  }

  /**
   * Update a user
   */
  async updateUser(userId: string, userData: Record<string, unknown>): Promise<any> {
    const response = await this.put(`/api/users/${userId}`, userData);
    if (response.ok) return response.json();
    throw new Error(`Failed to update user: ${response.status} ${response.statusText}`);
  }

  /**
   * Delete a user
   */
  async deleteUser(userId: string): Promise<any> {
    const response = await this.delete(`/api/users/${userId}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete user: ${response.status} ${response.statusText}`);
  }

  // ─── User Space Access ──────────────────────────────────────────

  async getUserSpaces(username: string): Promise<{ username: string; spaces: Record<string, string> }> {
    const response = await this.get(`/api/users/${username}/spaces`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get user spaces: ${response.status}`);
  }

  async grantSpaceAccess(username: string, spaceId: string, accessLevel: 'rw' | 'r'): Promise<{ message: string }> {
    const response = await this.put(`/api/users/${username}/spaces/${spaceId}`, { access_level: accessLevel });
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to grant space access: ${response.status}`);
  }

  async revokeSpaceAccess(username: string, spaceId: string): Promise<{ message: string }> {
    const response = await this.delete(`/api/users/${username}/spaces/${spaceId}`);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to revoke space access: ${response.status}`);
  }

  // ─── API Keys ────────────────────────────────────────────────────

  async listApiKeys(username?: string): Promise<{ keys: any[]; total_count: number }> {
    const params = new URLSearchParams();
    if (username) params.set('username', username);
    const url = `/api/keys${params.toString() ? '?' + params.toString() : ''}`;
    const response = await this.get(url);
    if (response.ok) return response.json();
    throw new Error(`Failed to list API keys: ${response.status}`);
  }

  async createApiKey(name: string, expiresInDays?: number, username?: string): Promise<{
    key_id: string;
    key: string;
    prefix: string;
    name: string;
    username: string;
    expires_at: string | null;
    message: string;
  }> {
    const body: Record<string, unknown> = { name };
    if (expiresInDays) body.expires_in_days = expiresInDays;
    if (username) body.username = username;
    const response = await this.post('/api/keys', body);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to create API key: ${response.status}`);
  }

  async revokeApiKey(keyId: string): Promise<{ message: string; key_id: string }> {
    const response = await this.delete(`/api/keys/${keyId}`);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to revoke API key: ${response.status}`);
  }

  /**
   * Change own password (self-service)
   */
  async changePassword(currentPassword: string, newPassword: string): Promise<{ message: string; tokens_invalidated: boolean }> {
    const response = await this.post('/api/users/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to change password: ${response.status} ${response.statusText}`);
  }

  // ─── Admin / Health ──────────────────────────────────────────────

  async healthCheck(): Promise<{ status: string }> {
    const response = await this.get('/health');
    if (response.ok) return response.json();
    throw new Error(`Health check failed: ${response.status}`);
  }

  async cacheStats(): Promise<{ entity_graph_cache: Record<string, unknown> }> {
    const response = await this.get('/health/cache');
    if (response.ok) return response.json();
    throw new Error(`Cache stats failed: ${response.status}`);
  }

  async listProcesses(options: { process_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<any> {
    const params = new URLSearchParams();
    if (options.process_type) params.set('process_type', options.process_type);
    if (options.status) params.set('status', options.status);
    if (options.limit) params.set('limit', options.limit.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    const url = `/api/processes${params.toString() ? '?' + params.toString() : ''}`;
    const response = await this.get(url);
    if (response.ok) return response.json();
    throw new Error(`Failed to list processes: ${response.status}`);
  }

  async getSchedulerStatus(): Promise<{ enabled: boolean; running: boolean; jobs: Record<string, unknown>; active_locks: number }> {
    const response = await this.get('/api/processes/scheduler');
    if (response.ok) return response.json();
    throw new Error(`Failed to get scheduler status: ${response.status}`);
  }

  async triggerProcess(processType: string, spaceId?: string): Promise<{ triggered: boolean; message: string; result?: Record<string, unknown> }> {
    const body: Record<string, unknown> = { process_type: processType };
    if (spaceId) body.space_id = spaceId;
    const response = await this.post('/api/processes/trigger', body);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to trigger process: ${response.status}`);
  }

  async adminResync(spaceId: string): Promise<{ space_id: string; edge_rows: number; frame_entity_rows: number; pred_stats_rows: number; quad_stats_rows: number; elapsed_ms: number }> {
    const response = await this.post(`/api/admin/resync?space_id=${encodeURIComponent(spaceId)}`, {});
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Resync failed: ${response.status}`);
  }

  // ─── KG Queries ────────────────────────────────────────────────────

  async kgQuery(spaceId: string, graphId: string, body: Record<string, unknown>): Promise<any> {
    const params = new URLSearchParams({ space_id: spaceId, graph_id: graphId });
    const response = await this.post(`/api/graphs/kgqueries?${params.toString()}`, body);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `KG query failed: ${response.status}`);
  }

  // ─── Audit Log ─────────────────────────────────────────────────────

  async getAuditLog(options: { event?: string; actor?: string; level?: string; last?: string; limit?: number; offset?: number } = {}): Promise<{
    entries: { id: number; timestamp: string; event: string; actor: string; target: string | null; ip: string | null; user_agent: string | null; details: Record<string, unknown> | null; level: string }[];
    total_count: number; limit: number; offset: number;
  }> {
    const params = new URLSearchParams();
    if (options.event) params.set('event', options.event);
    if (options.actor) params.set('actor', options.actor);
    if (options.level) params.set('level', options.level);
    if (options.last) params.set('last', options.last);
    if (options.limit) params.set('limit', options.limit.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    const url = `/api/admin/audit${params.toString() ? '?' + params.toString() : ''}`;
    const response = await this.get(url);
    if (response.ok) return response.json();
    throw new Error(`Failed to get audit log: ${response.status}`);
  }

  // ─── Entity Registry ───────────────────────────────────────────────

  async listRegistryEntities(options: { query?: string; entity_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<any> {
    const params = new URLSearchParams();
    if (options.query) params.set('query', options.query);
    if (options.entity_type) params.set('entity_type', options.entity_type);
    if (options.status) params.set('status', options.status);
    if (options.limit) params.set('limit', options.limit.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    const url = `/api/entity${params.toString() ? '?' + params.toString() : ''}`;
    const response = await this.get(url);
    if (response.ok) return response.json();
    throw new Error(`Failed to list entities: ${response.status}`);
  }

  async getRegistryEntity(entityId: string): Promise<any> {
    const response = await this.get(`/api/entity?entity_id=${encodeURIComponent(entityId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entity: ${response.status}`);
  }

  async createRegistryEntity(data: Record<string, unknown>): Promise<any> {
    const response = await this.post('/api/entity', data);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to create entity: ${response.status}`);
  }

  async updateRegistryEntity(entityId: string, data: Record<string, unknown>): Promise<any> {
    const response = await this.put(`/api/entity?entity_id=${encodeURIComponent(entityId)}`, data);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to update entity: ${response.status}`);
  }

  async deleteRegistryEntity(entityId: string): Promise<any> {
    const response = await this.delete(`/api/entity?entity_id=${encodeURIComponent(entityId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete entity: ${response.status}`);
  }

  async getEntityAliases(entityId: string): Promise<any> {
    const response = await this.get(`/api/entity/aliases?entity_id=${encodeURIComponent(entityId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entity aliases: ${response.status}`);
  }

  async getEntityIdentifiers(entityId: string): Promise<any> {
    const response = await this.get(`/api/entity/identifiers?entity_id=${encodeURIComponent(entityId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entity identifiers: ${response.status}`);
  }

  async getEntityCategories(entityId: string): Promise<any> {
    const response = await this.get(`/api/entity/categories?entity_id=${encodeURIComponent(entityId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entity categories: ${response.status}`);
  }

  async getEntityLocations(entityId: string): Promise<any> {
    const response = await this.get(`/api/entity/locations?entity_id=${encodeURIComponent(entityId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get entity locations: ${response.status}`);
  }

  // ─── Agent Registry ────────────────────────────────────────────────

  async listAgentTypes(): Promise<any[]> {
    const response = await this.get('/api/agent/types');
    if (response.ok) return response.json();
    throw new Error(`Failed to list agent types: ${response.status}`);
  }

  async listAgents(options: { query?: string; agent_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<any> {
    const params = new URLSearchParams();
    if (options.query) params.set('query', options.query);
    if (options.agent_type) params.set('agent_type', options.agent_type);
    if (options.status) params.set('status', options.status);
    if (options.limit) params.set('limit', options.limit.toString());
    if (options.offset) params.set('offset', options.offset.toString());
    const url = `/api/agent${params.toString() ? '?' + params.toString() : ''}`;
    const response = await this.get(url);
    if (response.ok) return response.json();
    throw new Error(`Failed to list agents: ${response.status}`);
  }

  async getAgent(agentId: string): Promise<any> {
    const response = await this.get(`/api/agent?agent_id=${encodeURIComponent(agentId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get agent: ${response.status}`);
  }

  async createAgent(data: Record<string, unknown>): Promise<any> {
    const response = await this.post('/api/agent', data);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to create agent: ${response.status}`);
  }

  async updateAgent(agentId: string, data: Record<string, unknown>): Promise<any> {
    const response = await this.put(`/api/agent?agent_id=${encodeURIComponent(agentId)}`, data);
    if (response.ok) return response.json();
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to update agent: ${response.status}`);
  }

  async deleteAgent(agentId: string): Promise<any> {
    const response = await this.delete(`/api/agent?agent_id=${encodeURIComponent(agentId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to delete agent: ${response.status}`);
  }

  async changeAgentStatus(agentId: string, status: string, reason?: string): Promise<any> {
    const response = await this.put(`/api/agent/status?agent_id=${encodeURIComponent(agentId)}`, { status, reason });
    if (response.ok) return response.json();
    throw new Error(`Failed to change agent status: ${response.status}`);
  }

  async getAgentEndpoints(agentId: string): Promise<any[]> {
    const response = await this.get(`/api/agent/endpoints?agent_id=${encodeURIComponent(agentId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get agent endpoints: ${response.status}`);
  }

  async getAgentFunctions(agentId: string): Promise<any[]> {
    const response = await this.get(`/api/agent/functions?agent_id=${encodeURIComponent(agentId)}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get agent functions: ${response.status}`);
  }

  async getAgentChangelog(agentId: string, limit: number = 50): Promise<any> {
    const response = await this.get(`/api/agent/changelog?agent_id=${encodeURIComponent(agentId)}&limit=${limit}`);
    if (response.ok) return response.json();
    throw new Error(`Failed to get agent changelog: ${response.status}`);
  }
}

// Create singleton instance
export const apiService = new ApiService();
export default apiService;
