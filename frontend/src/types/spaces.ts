/**
 * Space types for VitalGraph frontend
 */

export interface Space {
  space: string;
  space_name: string;
  space_description?: string;
  exists?: boolean;
}

export interface SpaceListResponse {
  spaces: Space[];
}
