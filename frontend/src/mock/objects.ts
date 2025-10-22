// Mock data for objects
export interface Property {
  predicate: string;
  object: string;
  object_type: 'uri' | 'literal';
  datatype?: string;
}

export interface RDFObject {
  id: number;
  space_id: string;
  graph_id: number;
  object_uri: string;
  object_type: 'Node' | 'Edge';
  rdf_type: string;
  subject: string;
  predicate: string;
  object: string;
  context: string;
  created_time: string;
  last_modified: string;
  properties_count: number;
  properties: Property[];
}

export const mockObjects: RDFObject[] = [
  // Space1 objects
  {
    id: 1,
    space_id: 'space1',
    graph_id: 1,
    object_uri: 'http://vital.ai/ontology/Person#john-doe',
    object_type: 'Node',
    rdf_type: 'http://vital.ai/ontology/Person',
    subject: 'http://vital.ai/ontology/Person#john-doe',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Person',
    context: 'http://vital.ai/graph/knowledge-base',
    created_time: '2024-01-15T10:30:00Z',
    last_modified: '2024-01-20T14:15:00Z',
    properties_count: 8,
    properties: [
      { predicate: 'http://vital.ai/ontology/firstName', object: 'John', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/lastName', object: 'Doe', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/email', object: 'john.doe@acme.com', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/age', object: '32', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#integer' },
      { predicate: 'http://vital.ai/ontology/department', object: 'Engineering', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/salary', object: '95000.00', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#decimal' },
      { predicate: 'http://vital.ai/ontology/isActive', object: 'true', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#boolean' },
      { predicate: 'http://vital.ai/ontology/startDate', object: '2022-03-15T09:00:00Z', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#dateTime' }
    ]
  },
  {
    id: 2,
    space_id: 'space1',
    graph_id: 1,
    object_uri: 'http://vital.ai/ontology/Organization#acme-corp',
    object_type: 'Node',
    rdf_type: 'http://vital.ai/ontology/Organization',
    subject: 'http://vital.ai/ontology/Organization#acme-corp',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Organization',
    context: 'http://vital.ai/graph/knowledge-base',
    created_time: '2024-01-14T14:20:00Z',
    last_modified: '2024-01-19T11:30:00Z',
    properties_count: 12,
    properties: [
      { predicate: 'http://vital.ai/ontology/name', object: 'ACME Corporation', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/industry', object: 'Technology', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/founded', object: '1995', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#integer' },
      { predicate: 'http://vital.ai/ontology/employeeCount', object: '2500', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#integer' }
    ]
  },
  {
    id: 3,
    space_id: 'space1',
    graph_id: 2,
    object_uri: 'http://vital.ai/ontology/WorksFor#john-acme',
    object_type: 'Edge',
    rdf_type: 'http://vital.ai/ontology/WorksFor',
    subject: 'http://vital.ai/ontology/Person#john-doe',
    predicate: 'http://vital.ai/ontology/worksFor',
    object: 'http://vital.ai/ontology/Organization#acme-corp',
    context: 'http://vital.ai/graph/ontology-core',
    created_time: '2024-01-16T09:15:00Z',
    last_modified: '2024-01-18T16:45:00Z',
    properties_count: 5,
    properties: [
      { predicate: 'http://vital.ai/ontology/startDate', object: '2022-03-15T09:00:00Z', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#dateTime' },
      { predicate: 'http://vital.ai/ontology/position', object: 'Senior Software Engineer', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/isFullTime', object: 'true', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#boolean' }
    ]
  },
  // Space2 objects
  {
    id: 4,
    space_id: 'space2',
    graph_id: 3,
    object_uri: 'http://vital.ai/ontology/Project#alpha-project',
    object_type: 'Node',
    rdf_type: 'http://vital.ai/ontology/Project',
    subject: 'http://vital.ai/ontology/Project#alpha-project',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Project',
    context: 'http://vital.ai/graph/alpha-entities',
    created_time: '2024-01-13T16:45:00Z',
    last_modified: '2024-01-18T09:20:00Z',
    properties_count: 15,
    properties: [
      { predicate: 'http://vital.ai/ontology/name', object: 'Project Alpha', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/status', object: 'In Progress', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/budget', object: '2500000.00', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#decimal' }
    ]
  },
  {
    id: 5,
    space_id: 'space2',
    graph_id: 4,
    object_uri: 'http://vital.ai/ontology/Task#alpha-task-001',
    object_type: 'Node',
    rdf_type: 'http://vital.ai/ontology/Task',
    subject: 'http://vital.ai/ontology/Task#alpha-task-001',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Task',
    context: 'http://vital.ai/graph/alpha-workflow',
    created_time: '2024-01-12T11:20:00Z',
    last_modified: '2024-01-17T15:45:00Z',
    properties_count: 9,
    properties: [
      { predicate: 'http://vital.ai/ontology/title', object: 'Implement User Authentication', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/status', object: 'In Progress', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/priority', object: 'High', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' }
    ]
  },
  {
    id: 6,
    space_id: 'space2',
    graph_id: 4,
    object_uri: 'http://vital.ai/ontology/PartOf#task-project',
    object_type: 'Edge',
    rdf_type: 'http://vital.ai/ontology/PartOf',
    subject: 'http://vital.ai/ontology/Task#alpha-task-001',
    predicate: 'http://vital.ai/ontology/partOf',
    object: 'http://vital.ai/ontology/Project#alpha-project',
    context: 'http://vital.ai/graph/alpha-workflow',
    created_time: '2024-01-12T12:30:00Z',
    last_modified: '2024-01-17T16:00:00Z',
    properties_count: 3,
    properties: [
      { predicate: 'http://vital.ai/ontology/relationshipType', object: 'contains', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/weight', object: '1.0', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#decimal' }
    ]
  },
  // Space3 objects
  {
    id: 7,
    space_id: 'space3',
    graph_id: 5,
    object_uri: 'http://vital.ai/ontology/Dataset#research-data-001',
    object_type: 'Node',
    rdf_type: 'http://vital.ai/ontology/Dataset',
    subject: 'http://vital.ai/ontology/Dataset#research-data-001',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object: 'http://vital.ai/ontology/Dataset',
    context: 'http://vital.ai/graph/research-dataset',
    created_time: '2024-01-11T09:15:00Z',
    last_modified: '2024-01-16T13:25:00Z',
    properties_count: 18,
    properties: [
      { predicate: 'http://vital.ai/ontology/name', object: 'Customer Behavior Research Dataset', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/format', object: 'CSV', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/recordCount', object: '125000', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#integer' }
    ]
  },
  {
    id: 8,
    space_id: 'space3',
    graph_id: 6,
    object_uri: 'http://vital.ai/ontology/Analysis#analysis-001',
    object_type: 'Node',
    rdf_type: 'http://vital.ai/ontology/Analysis',
    subject: 'http://vital.ai/ontology/Analysis#analysis-001',
    predicate: 'http://www.w3.org/2001/XMLSchema#type',
    object: 'http://vital.ai/ontology/Analysis',
    context: 'http://vital.ai/graph/analysis-results',
    created_time: '2024-01-10T13:30:00Z',
    last_modified: '2024-01-15T10:40:00Z',
    properties_count: 22,
    properties: [
      { predicate: 'http://vital.ai/ontology/title', object: 'Customer Segmentation Analysis', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/status', object: 'Completed', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#string' },
      { predicate: 'http://vital.ai/ontology/accuracy', object: '0.94', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#decimal' }
    ]
  },
  {
    id: 9,
    space_id: 'space3',
    graph_id: 6,
    object_uri: 'http://vital.ai/ontology/AnalyzedBy#data-analysis',
    object_type: 'Edge',
    rdf_type: 'http://vital.ai/ontology/AnalyzedBy',
    subject: 'http://vital.ai/ontology/Dataset#research-data-001',
    predicate: 'http://vital.ai/ontology/analyzedBy',
    object: 'http://vital.ai/ontology/Analysis#analysis-001',
    context: 'http://vital.ai/graph/analysis-results',
    created_time: '2024-01-11T14:20:00Z',
    last_modified: '2024-01-15T11:15:00Z',
    properties_count: 4,
    properties: [
      { predicate: 'http://vital.ai/ontology/analysisDate', object: '2024-01-11T14:20:00Z', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#dateTime' },
      { predicate: 'http://vital.ai/ontology/confidence', object: '0.89', object_type: 'literal', datatype: 'http://www.w3.org/2001/XMLSchema#decimal' }
    ]
  }
];
