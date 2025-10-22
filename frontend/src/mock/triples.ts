// Mock data for triples
export interface Triple {
  id: number;
  space_id: string;
  graph_id: number;
  subject: string;
  predicate: string;
  object: string;
  object_type: 'uri' | 'literal';
  created_time: string;
  last_modified: string;
}

export const mockTriples: Triple[] = [
  // Space1, Graph1 triples
  {
    id: 1,
    space_id: 'space1',
    graph_id: 1,
    subject: 'http://vital.ai/ontology/Person#john-doe',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Person',
    object_type: 'uri',
    created_time: '2024-01-15T10:30:00Z',
    last_modified: '2024-01-15T10:30:00Z'
  },
  {
    id: 2,
    space_id: 'space1',
    graph_id: 1,
    subject: 'http://vital.ai/ontology/Person#john-doe',
    predicate: 'http://vital.ai/ontology/hasName',
    object: 'John Doe',
    object_type: 'literal',
    created_time: '2024-01-15T10:31:00Z',
    last_modified: '2024-01-15T10:31:00Z'
  },
  {
    id: 3,
    space_id: 'space1',
    graph_id: 1,
    subject: 'http://vital.ai/ontology/Person#john-doe',
    predicate: 'http://vital.ai/ontology/hasAge',
    object: '35',
    object_type: 'literal',
    created_time: '2024-01-15T10:32:00Z',
    last_modified: '2024-01-15T10:32:00Z'
  },
  {
    id: 4,
    space_id: 'space1',
    graph_id: 1,
    subject: 'http://vital.ai/ontology/Person#jane-smith',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Person',
    object_type: 'uri',
    created_time: '2024-01-15T11:00:00Z',
    last_modified: '2024-01-15T11:00:00Z'
  },
  {
    id: 5,
    space_id: 'space1',
    graph_id: 1,
    subject: 'http://vital.ai/ontology/Person#jane-smith',
    predicate: 'http://vital.ai/ontology/hasName',
    object: 'Jane Smith',
    object_type: 'literal',
    created_time: '2024-01-15T11:01:00Z',
    last_modified: '2024-01-15T11:01:00Z'
  },
  // Space1, Graph2 triples  
  {
    id: 6,
    space_id: 'space1',
    graph_id: 2,
    subject: 'http://vital.ai/ontology/Class#Person',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    object: 'http://vital.ai/ontology/Class#Entity',
    object_type: 'uri',
    created_time: '2024-01-14T14:20:00Z',
    last_modified: '2024-01-14T14:20:00Z'
  },
  {
    id: 7,
    space_id: 'space1',
    graph_id: 2,
    subject: 'http://vital.ai/ontology/Property#hasName',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://www.w3.org/2002/07/owl#DatatypeProperty',
    object_type: 'uri',
    created_time: '2024-01-14T14:21:00Z',
    last_modified: '2024-01-14T14:21:00Z'
  },
  // Space2, Graph3 triples
  {
    id: 8,
    space_id: 'space2',
    graph_id: 3,
    subject: 'http://vital.ai/ontology/Entity#alpha-001',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/AlphaEntity',
    object_type: 'uri',
    created_time: '2024-01-13T16:45:00Z',
    last_modified: '2024-01-13T16:45:00Z'
  },
  {
    id: 9,
    space_id: 'space2',
    graph_id: 3,
    subject: 'http://vital.ai/ontology/Entity#alpha-001',
    predicate: 'http://vital.ai/ontology/hasStatus',
    object: 'active',
    object_type: 'literal',
    created_time: '2024-01-13T16:46:00Z',
    last_modified: '2024-01-13T16:46:00Z'
  }
];
