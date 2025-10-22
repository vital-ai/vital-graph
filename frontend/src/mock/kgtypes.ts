// Mock data for Knowledge Graph Types
export interface KGType {
  id: number;
  space_id: string;
  graph_id: number;
  uri: string;
  type_name: string;
  description: string;
  type_uri: string;
  properties: string[];
  created_at: string;
  updated_at: string;
}

export const mockKGTypes: KGType[] = [
  {
    id: 1,
    space_id: 'space1',
    graph_id: 1,
    uri: 'http://vital.ai/ontology/vital-core#Person',
    type_name: 'Person',
    description: 'Represents a human individual with personal attributes',
    type_uri: 'http://vital.ai/ontology/vital-core#KGEntityType',
    properties: ['name', 'email', 'birthDate', 'address'],
    created_at: '2024-01-15T10:30:00Z',
    updated_at: '2024-01-15T10:30:00Z'
  },
  {
    id: 2,
    space_id: 'space1',
    graph_id: 1,
    uri: 'http://vital.ai/ontology/vital-core#Organization',
    type_name: 'Organization',
    description: 'Represents a business entity or institutional organization',
    type_uri: 'http://vital.ai/ontology/vital-core#KGEntityType',
    properties: ['name', 'industry', 'foundedDate', 'headquarters'],
    created_at: '2024-01-15T11:00:00Z',
    updated_at: '2024-01-15T11:00:00Z'
  },
  {
    id: 3,
    space_id: 'space1',
    graph_id: 1,
    uri: 'http://vital.ai/ontology/vital-core#Location',
    type_name: 'Location',
    description: 'Represents a geographic location or place',
    type_uri: 'http://vital.ai/ontology/vital-core#KGEntityType',
    properties: ['name', 'latitude', 'longitude', 'country', 'region'],
    created_at: '2024-01-15T11:30:00Z',
    updated_at: '2024-01-15T11:30:00Z'
  },
  {
    id: 4,
    space_id: 'space1',
    graph_id: 1,
    uri: 'http://vital.ai/ontology/vital-core#Document',
    type_name: 'Document',
    description: 'Represents a text document or file',
    type_uri: 'http://vital.ai/ontology/vital-core#KGFrameType',
    properties: ['title', 'content', 'author', 'createdDate', 'format'],
    created_at: '2024-01-15T12:00:00Z',
    updated_at: '2024-01-15T12:00:00Z'
  },
  {
    id: 5,
    space_id: 'space1',
    graph_id: 2,
    uri: 'http://vital.ai/ontology/vital-core#Product',
    type_name: 'Product',
    description: 'Represents a commercial product or service offering',
    type_uri: 'http://vital.ai/ontology/vital-core#KGEntityType',
    properties: ['name', 'description', 'price', 'category', 'manufacturer'],
    created_at: '2024-01-16T09:00:00Z',
    updated_at: '2024-01-16T09:00:00Z'
  },
  {
    id: 6,
    space_id: 'space1',
    graph_id: 2,
    uri: 'http://vital.ai/ontology/vital-core#Event',
    type_name: 'Event',
    description: 'Represents a temporal occurrence or happening',
    type_uri: 'http://vital.ai/ontology/vital-core#KGFrameType',
    properties: ['name', 'startDate', 'endDate', 'location', 'description'],
    created_at: '2024-01-16T09:30:00Z',
    updated_at: '2024-01-16T09:30:00Z'
  },
  {
    id: 7,
    space_id: 'space2',
    graph_id: 3,
    uri: 'http://research.org/ontology/core#Publication',
    type_name: 'Publication',
    description: 'Represents an academic or research publication',
    type_uri: 'http://research.org/ontology/core#KGFrameType',
    properties: ['title', 'authors', 'journal', 'publishedDate', 'doi'],
    created_at: '2024-01-17T10:00:00Z',
    updated_at: '2024-01-17T10:00:00Z'
  },
  {
    id: 8,
    space_id: 'space2',
    graph_id: 3,
    uri: 'http://research.org/ontology/core#Researcher',
    type_name: 'Researcher',
    description: 'Represents an academic researcher or scientist',
    type_uri: 'http://research.org/ontology/core#KGEntityType',
    properties: ['name', 'affiliation', 'expertise', 'publications', 'orcid'],
    created_at: '2024-01-17T10:30:00Z',
    updated_at: '2024-01-17T10:30:00Z'
  },
  {
    id: 9,
    space_id: 'space3',
    graph_id: 4,
    uri: 'http://finance.org/ontology/core#Transaction',
    type_name: 'Transaction',
    description: 'Represents a financial transaction or exchange',
    type_uri: 'http://finance.org/ontology/core#KGSlotType',
    properties: ['amount', 'currency', 'date', 'fromAccount', 'toAccount'],
    created_at: '2024-01-18T14:00:00Z',
    updated_at: '2024-01-18T14:00:00Z'
  },
  {
    id: 10,
    space_id: 'space3',
    graph_id: 4,
    uri: 'http://finance.org/ontology/core#Account',
    type_name: 'Account',
    description: 'Represents a financial account or wallet',
    type_uri: 'http://finance.org/ontology/core#KGEntityType',
    properties: ['accountNumber', 'balance', 'accountType', 'owner', 'bank'],
    created_at: '2024-01-18T14:30:00Z',
    updated_at: '2024-01-18T14:30:00Z'
  }
];
