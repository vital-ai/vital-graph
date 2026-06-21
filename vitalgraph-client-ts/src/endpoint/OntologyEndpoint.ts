import { BaseEndpoint } from './BaseEndpoint.js';
import type { VitalGraphResponse } from '../response/types.js';

export interface OntologyProperty {
  uri: string;
  local_name?: string;
  short_name?: string;
  property_class?: string;
}

export interface OntologyPropertiesResponse extends VitalGraphResponse {
  class_uri: string;
  properties: OntologyProperty[];
  total_count: number;
}

export interface OntologyClassesResponse extends VitalGraphResponse {
  classes: string[];
}

export class OntologyEndpoint extends BaseEndpoint {
  /**
   * Get available RDF properties for a given VitalSigns class URI.
   */
  async getProperties(classUri: string): Promise<OntologyPropertiesResponse> {
    return this.request<OntologyPropertiesResponse>('GET', '/api/ontology/properties', {
      params: { class_uri: classUri },
    });
  }

  /**
   * List known class URIs supported by the ontology endpoint.
   */
  async getClasses(): Promise<OntologyClassesResponse> {
    return this.request<OntologyClassesResponse>('GET', '/api/ontology/classes');
  }
}
