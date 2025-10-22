// Mock data for spaces
export interface Space {
  id: number;
  tenant: string;
  space: string;
  space_name: string;
  description: string;
  created_time: string;
  last_modified: string;
}

export const mockSpaces: Space[] = [
  {
    id: 1,
    tenant: 'default',
    space: 'space1',
    space_name: 'Default Space',
    description: 'Default workspace for general use',
    created_time: '2024-01-01T00:00:00Z',
    last_modified: '2024-01-01T00:00:00Z'
  },
  {
    id: 2,
    tenant: 'default',
    space: 'space2',
    space_name: 'Research Space',
    description: 'Research and development workspace',
    created_time: '2024-01-02T00:00:00Z',
    last_modified: '2024-01-02T00:00:00Z'
  },
  {
    id: 3,
    tenant: 'default',
    space: 'space3',
    space_name: 'Analytics Space',
    description: 'Data analytics and reporting workspace',
    created_time: '2024-01-03T00:00:00Z',
    last_modified: '2024-01-03T00:00:00Z'
  }
];
