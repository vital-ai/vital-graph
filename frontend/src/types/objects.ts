/**
 * Object/Entity/Frame types for VitalGraph frontend
 */

export interface RDFProperty {
  predicate: string;
  object: string;
  datatype?: string;
  language?: string;
}

export interface GraphObject {
  uri: string;
  rdf_type: string;
  name?: string;
  properties_count: number;
}

export interface KGEntity {
  uri: string;
  rdf_type: string;
  name: string;
  properties_count: number;
}

export interface KGFrame {
  uri: string;
  rdf_type: string;
  name: string;
  properties_count: number;
  parent_entity_uri?: string;
}

export interface KGType {
  uri: string;
  type_name: string;
  parent_type_uri?: string;
  properties: KGTypeProperty[];
}

export interface KGTypeProperty {
  property_uri: string;
  property_name: string;
  data_type: string;
  cardinality?: string;
}

export interface ObjectListResponse {
  objects: GraphObject[];
  total_count: number;
  offset: number;
  page_size: number;
}

export interface EntityListResponse {
  entities: KGEntity[];
  total_count: number;
  offset: number;
  page_size: number;
}

export interface FrameListResponse {
  frames: KGFrame[];
  total_count: number;
  offset: number;
  page_size: number;
}
