// Mock data for files
export interface File {
  id: number;
  space_id: string;
  graph_id: number;
  filename: string;
  file_path: string;
  file_size: number;
  file_type: string;
  upload_time: string;
  last_modified: string;
}

export const mockFiles: File[] = [
  // Space1 files
  {
    id: 1,
    space_id: 'space1',
    graph_id: 0, // Global
    filename: 'document1.pdf',
    file_path: '/uploads/document1.pdf',
    file_size: 2048576,
    file_type: 'application/pdf',
    upload_time: '2024-01-15T10:30:00Z',
    last_modified: '2024-01-15T10:30:00Z'
  },
  {
    id: 2,
    space_id: 'space1',
    graph_id: 1, // knowledge-base
    filename: 'meeting-notes.docx',
    file_path: '/uploads/meeting-notes.docx',
    file_size: 512000,
    file_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    upload_time: '2024-01-14T14:20:00Z',
    last_modified: '2024-01-16T09:15:00Z'
  },
  {
    id: 7,
    space_id: 'space1',
    graph_id: 2, // ontology-core
    filename: 'ontology-spec.owl',
    file_path: '/uploads/ontology-spec.owl',
    file_size: 1024000,
    file_type: 'application/rdf+xml',
    upload_time: '2024-01-13T12:00:00Z',
    last_modified: '2024-01-18T16:30:00Z'
  },
  // Space2 files
  {
    id: 3,
    space_id: 'space2',
    graph_id: 0, // Global
    filename: 'alpha-requirements.pdf',
    file_path: '/uploads/alpha-requirements.pdf',
    file_size: 1536000,
    file_type: 'application/pdf',
    upload_time: '2024-01-13T16:45:00Z',
    last_modified: '2024-01-13T16:45:00Z'
  },
  {
    id: 4,
    space_id: 'space2',
    graph_id: 3, // alpha-entities
    filename: 'alpha-timeline.xlsx',
    file_path: '/uploads/alpha-timeline.xlsx',
    file_size: 768000,
    file_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    upload_time: '2024-01-12T11:20:00Z',
    last_modified: '2024-01-15T14:30:00Z'
  },
  {
    id: 8,
    space_id: 'space2',
    graph_id: 4, // alpha-workflow
    filename: 'workflow-definition.json',
    file_path: '/uploads/workflow-definition.json',
    file_size: 256000,
    file_type: 'application/json',
    upload_time: '2024-01-11T14:15:00Z',
    last_modified: '2024-01-17T10:45:00Z'
  },
  // Space3 files
  {
    id: 5,
    space_id: 'space3',
    graph_id: 0, // Global
    filename: 'research-data.csv',
    file_path: '/uploads/research-data.csv',
    file_size: 3072000,
    file_type: 'text/csv',
    upload_time: '2024-01-11T09:15:00Z',
    last_modified: '2024-01-14T16:45:00Z'
  },
  {
    id: 6,
    space_id: 'space3',
    graph_id: 5, // research-dataset
    filename: 'analysis-report.pdf',
    file_path: '/uploads/analysis-report.pdf',
    file_size: 2560000,
    file_type: 'application/pdf',
    upload_time: '2024-01-10T13:30:00Z',
    last_modified: '2024-01-12T10:20:00Z'
  },
  {
    id: 9,
    space_id: 'space3',
    graph_id: 6, // analysis-results
    filename: 'statistical-output.txt',
    file_path: '/uploads/statistical-output.txt',
    file_size: 128000,
    file_type: 'text/plain',
    upload_time: '2024-01-09T11:00:00Z',
    last_modified: '2024-01-15T09:20:00Z'
  }
];
