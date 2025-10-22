// Mock data for graphs
export interface Graph {
  id: number;
  space_id: string;
  graph_name: string;
  graph_uri: string;
  graph_type: string;
  triple_count: number;
  created_time: string;
  last_modified: string;
  description: string;
  status: string;
}

export const mockGraphs: Graph[] = [
  // Space1 graphs
  {
    id: 0,
    space_id: 'space1',
    graph_name: 'Global',
    graph_uri: 'http://vital.ai/graph/global',
    graph_type: 'Global Graph',
    triple_count: 0,
    created_time: '2024-01-01T00:00:00Z',
    last_modified: '2024-01-01T00:00:00Z',
    description: 'Global graph for files not assigned to a specific graph',
    status: 'active'
  },
  {
    id: 1,
    space_id: 'space1',
    graph_name: 'knowledge-base',
    graph_uri: 'http://vital.ai/graph/knowledge-base',
    graph_type: 'Knowledge Graph',
    triple_count: 15420,
    created_time: '2024-01-15T10:30:00Z',
    last_modified: '2024-01-20T14:15:00Z',
    description: 'Main knowledge base graph',
    status: 'active'
  },
  {
    id: 2,
    space_id: 'space1',
    graph_name: 'ontology-core',
    graph_uri: 'http://vital.ai/graph/ontology-core',
    graph_type: 'Ontology',
    triple_count: 8750,
    created_time: '2024-01-14T14:20:00Z',
    last_modified: '2024-01-19T11:30:00Z',
    description: 'Core ontology definitions',
    status: 'active'
  },
  {
    id: 3,
    space_id: 'space1',
    graph_name: 'user-data',
    graph_uri: 'http://vital.ai/graph/user-data',
    graph_type: 'User Graph',
    triple_count: 2340,
    created_time: '2024-01-16T09:15:00Z',
    last_modified: '2024-01-21T16:20:00Z',
    description: 'User-generated content and preferences',
    status: 'active'
  },
  // Space2 graphs
  {
    id: 0,
    space_id: 'space2',
    graph_name: 'Global',
    graph_uri: 'http://vital.ai/graph/global',
    graph_type: 'Global Graph',
    triple_count: 0,
    created_time: '2024-01-01T00:00:00Z',
    last_modified: '2024-01-01T00:00:00Z',
    description: 'Global graph for files not assigned to a specific graph',
    status: 'active'
  },
  {
    id: 3,
    space_id: 'space2',
    graph_name: 'alpha-entities',
    graph_uri: 'http://vital.ai/graph/alpha-entities',
    graph_type: 'Entity Graph',
    triple_count: 25680,
    created_time: '2024-01-13T16:45:00Z',
    last_modified: '2024-01-18T09:20:00Z',
    description: 'Project Alpha entity relationships',
    status: 'active'
  },
  {
    id: 4,
    space_id: 'space2',
    graph_name: 'alpha-workflow',
    graph_uri: 'http://vital.ai/graph/alpha-workflow',
    graph_type: 'Process Graph',
    triple_count: 12340,
    created_time: '2024-01-12T11:20:00Z',
    last_modified: '2024-01-17T15:45:00Z',
    description: 'Alpha project workflow definitions',
    status: 'processing'
  },
  {
    id: 5,
    space_id: 'space2',
    graph_name: 'beta-experiments',
    graph_uri: 'http://vital.ai/graph/beta-experiments',
    graph_type: 'Experimental Graph',
    triple_count: 5670,
    created_time: '2024-01-11T16:30:00Z',
    last_modified: '2024-01-18T12:10:00Z',
    description: 'Beta experimental data and results',
    status: 'active'
  },
  // Space3 graphs
  {
    id: 0,
    space_id: 'space3',
    graph_name: 'Global',
    graph_uri: 'http://vital.ai/graph/global',
    graph_type: 'Global Graph',
    triple_count: 0,
    created_time: '2024-01-01T00:00:00Z',
    last_modified: '2024-01-01T00:00:00Z',
    description: 'Global graph for files not assigned to a specific graph',
    status: 'active'
  },
  {
    id: 5,
    space_id: 'space3',
    graph_name: 'research-dataset',
    graph_uri: 'http://vital.ai/graph/research-dataset',
    graph_type: 'Data Graph',
    triple_count: 45230,
    created_time: '2024-01-11T09:15:00Z',
    last_modified: '2024-01-16T13:25:00Z',
    description: 'Research data relationships',
    status: 'active'
  },
  {
    id: 6,
    space_id: 'space3',
    graph_name: 'analysis-results',
    graph_uri: 'http://vital.ai/graph/analysis-results',
    graph_type: 'Results Graph',
    triple_count: 18920,
    created_time: '2024-01-10T13:30:00Z',
    last_modified: '2024-01-15T10:40:00Z',
    description: 'Analysis results and conclusions',
    status: 'inactive'
  }
];
