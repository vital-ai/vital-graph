// Mock data for data imports and exports

export interface DataImport {
  id: number;
  name: string;
  description: string;
  space_id: string;
  graph_id: number;
  file_name: string;
  file_size: number;
  file_type: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'canceled';
  progress: number; // 0-100
  created_time: string;
  started_time?: string;
  completed_time?: string;
  error_message?: string;
}

export interface DataExport {
  id: number;
  name: string;
  description: string;
  space_id: string;
  graph_id: number;
  export_format: 'rdf/xml' | 'turtle' | 'n-triples' | 'json-ld' | 'n-quads';
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'canceled' | 'expired';
  progress: number; // 0-100
  file_size?: number;
  download_url?: string;
  expires_at?: string;
  created_time: string;
  started_time?: string;
  completed_time?: string;
  error_message?: string;
}

export interface DataMigration {
  id: number;
  name: string;
  description: string;
  source_space_id: string;
  source_graph_id: number;
  target_space_id: string;
  target_graph_id: number;
  migration_type: 'copy' | 'move' | 'sync';
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'canceled';
  progress: number;
  triples_migrated?: number;
  total_triples?: number;
  created_time: string;
  started_time?: string;
  completed_time?: string;
  error_message?: string;
}

export interface DataTrackingRange {
  range_id: number;
  hash_prefix_start: string;
  hash_prefix_end: string;
  current_cursor: string;
  records_processed: number;
  total_records: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  started_time?: string;
  completed_time?: string;
}

export interface DataTracking {
  id: number;
  name: string;
  description: string;
  space_id: string;
  graph_id: number;
  external_system?: string;
  parallel_slices: number;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'paused';
  overall_progress: number;
  ranges: DataTrackingRange[];
  total_records: number;
  records_processed: number;
  created_time: string;
  started_time?: string;
  completed_time?: string;
  last_updated: string;
  error_message?: string;
}

export interface DataCheckpoint {
  id: number;
  name: string;
  description: string;
  space_id: string;
  graph_id: number;
  checkpoint_timestamp: string;
  checkpoint_hash: string;
  purpose: string;
  external_system?: string;
  created_time: string;
  created_by?: string;
}

export const mockDataImports: DataImport[] = [
  {
    id: 1,
    name: "Product Catalog Import",
    description: "Import product catalog data from external system",
    space_id: "space1",
    graph_id: 1,
    file_name: "products.ttl",
    file_size: 2048576, // 2MB
    file_type: "text/turtle",
    status: "completed",
    progress: 100,
    created_time: "2024-01-15T10:30:00Z",
    started_time: "2024-01-15T10:32:00Z",
    completed_time: "2024-01-15T10:35:00Z"
  },
  {
    id: 2,
    name: "Customer Data Import",
    description: "Import customer relationship data",
    space_id: "space1",
    graph_id: 2,
    file_name: "customers.rdf",
    file_size: 1536000, // 1.5MB
    file_type: "application/rdf+xml",
    status: "processing",
    progress: 65,
    created_time: "2024-01-16T14:20:00Z",
    started_time: "2024-01-16T14:22:00Z"
  },
  {
    id: 3,
    name: "Ontology Import",
    description: "Import domain ontology definitions",
    space_id: "space2",
    graph_id: 3,
    file_name: "ontology.owl",
    file_size: 512000, // 500KB
    file_type: "application/rdf+xml",
    status: "pending",
    progress: 0,
    created_time: "2024-01-17T09:15:00Z"
  },
  {
    id: 4,
    name: "Failed Import Test",
    description: "Test import that failed due to format issues",
    space_id: "space1",
    graph_id: 1,
    file_name: "invalid.ttl",
    file_size: 1024000, // 1MB
    file_type: "text/turtle",
    status: "failed",
    progress: 25,
    created_time: "2024-01-14T16:45:00Z",
    started_time: "2024-01-14T16:47:00Z",
    completed_time: "2024-01-14T16:48:00Z",
    error_message: "Invalid Turtle syntax at line 42: Unexpected token"
  }
];

export const mockDataExports: DataExport[] = [
  {
    id: 1,
    name: "Full Graph Export",
    description: "Complete export of product graph for backup",
    space_id: "space1",
    graph_id: 1,
    export_format: "turtle",
    status: "completed",
    progress: 100,
    file_size: 3072000, // 3MB
    download_url: "/api/exports/1/download",
    expires_at: "2024-02-15T10:30:00Z",
    created_time: "2024-01-15T11:00:00Z",
    started_time: "2024-01-15T11:02:00Z",
    completed_time: "2024-01-15T11:05:00Z"
  },
  {
    id: 2,
    name: "Customer Data Export",
    description: "Export customer data for analysis",
    space_id: "space1",
    graph_id: 2,
    export_format: "json-ld",
    status: "processing",
    progress: 80,
    created_time: "2024-01-16T15:30:00Z",
    started_time: "2024-01-16T15:32:00Z"
  },
  {
    id: 3,
    name: "Ontology Export",
    description: "Export ontology for sharing with partners",
    space_id: "space2",
    graph_id: 3,
    export_format: "rdf/xml",
    status: "pending",
    progress: 0,
    created_time: "2024-01-17T10:00:00Z"
  },
  {
    id: 4,
    name: "Expired Export",
    description: "Old export that has expired",
    space_id: "space1",
    graph_id: 1,
    export_format: "n-triples",
    status: "expired",
    progress: 100,
    file_size: 2560000, // 2.5MB
    created_time: "2024-01-10T08:00:00Z",
    started_time: "2024-01-10T08:02:00Z",
    completed_time: "2024-01-10T08:04:00Z",
    expires_at: "2024-01-17T08:04:00Z"
  },
  {
    id: 5,
    name: "Failed Export",
    description: "Export that failed due to system error",
    space_id: "space2",
    graph_id: 4,
    export_format: "turtle",
    status: "failed",
    progress: 15,
    created_time: "2024-01-16T12:00:00Z",
    started_time: "2024-01-16T12:02:00Z",
    completed_time: "2024-01-16T12:03:00Z",
    error_message: "Database connection timeout during export"
  }
];

export const mockDataMigrations: DataMigration[] = [
  {
    id: 1,
    name: "Knowledge Base Migration",
    description: "Migrate knowledge base from research space to production",
    source_space_id: "space2",
    source_graph_id: 3,
    target_space_id: "space1",
    target_graph_id: 1,
    migration_type: "copy",
    status: "completed",
    progress: 100,
    triples_migrated: 25680,
    total_triples: 25680,
    created_time: "2024-01-18T09:00:00Z",
    started_time: "2024-01-18T09:02:00Z",
    completed_time: "2024-01-18T09:15:00Z"
  },
  {
    id: 2,
    name: "User Data Sync",
    description: "Synchronize user data between spaces",
    source_space_id: "space1",
    source_graph_id: 3,
    target_space_id: "space3",
    target_graph_id: 5,
    migration_type: "sync",
    status: "processing",
    progress: 45,
    triples_migrated: 1053,
    total_triples: 2340,
    created_time: "2024-01-19T14:30:00Z",
    started_time: "2024-01-19T14:32:00Z"
  },
  {
    id: 3,
    name: "Ontology Move",
    description: "Move ontology definitions to dedicated space",
    source_space_id: "space1",
    source_graph_id: 2,
    target_space_id: "space2",
    target_graph_id: 4,
    migration_type: "move",
    status: "pending",
    progress: 0,
    total_triples: 8750,
    created_time: "2024-01-20T10:15:00Z"
  },
  {
    id: 4,
    name: "Failed Migration Test",
    description: "Test migration that failed due to permission issues",
    source_space_id: "space3",
    source_graph_id: 6,
    target_space_id: "space1",
    target_graph_id: 1,
    migration_type: "copy",
    status: "failed",
    progress: 12,
    triples_migrated: 2270,
    total_triples: 18920,
    created_time: "2024-01-17T16:00:00Z",
    started_time: "2024-01-17T16:02:00Z",
    completed_time: "2024-01-17T16:05:00Z",
    error_message: "Insufficient permissions to write to target graph"
  },
  {
    id: 5,
    name: "Experimental Data Copy",
    description: "Copy experimental data for analysis",
    source_space_id: "space2",
    source_graph_id: 5,
    target_space_id: "space3",
    target_graph_id: 5,
    migration_type: "copy",
    status: "canceled",
    progress: 28,
    triples_migrated: 1588,
    total_triples: 5670,
    created_time: "2024-01-16T11:20:00Z",
    started_time: "2024-01-16T11:22:00Z",
    completed_time: "2024-01-16T11:30:00Z"
  }
];

export const mockDataTrackings: DataTracking[] = [
  {
    id: 1,
    name: "Customer Data Sync",
    description: "Sync customer data to external CRM system",
    space_id: "space1",
    graph_id: 1,
    external_system: "Salesforce CRM",
    parallel_slices: 4,
    status: "processing",
    overall_progress: 65,
    ranges: [
      {
        range_id: 1,
        hash_prefix_start: "00000000",
        hash_prefix_end: "3FFFFFFF",
        current_cursor: "2A3B4C5D",
        records_processed: 12500,
        total_records: 25000,
        status: "processing",
        started_time: "2024-01-15T10:30:00Z"
      },
      {
        range_id: 2,
        hash_prefix_start: "40000000",
        hash_prefix_end: "7FFFFFFF",
        current_cursor: "6F8A9B2C",
        records_processed: 18750,
        total_records: 25000,
        status: "processing",
        started_time: "2024-01-15T10:30:00Z"
      },
      {
        range_id: 3,
        hash_prefix_start: "80000000",
        hash_prefix_end: "BFFFFFFF",
        current_cursor: "BFFFFFFF",
        records_processed: 25000,
        total_records: 25000,
        status: "completed",
        started_time: "2024-01-15T10:30:00Z",
        completed_time: "2024-01-15T11:45:00Z"
      },
      {
        range_id: 4,
        hash_prefix_start: "C0000000",
        hash_prefix_end: "FFFFFFFF",
        current_cursor: "D1E2F3A4",
        records_processed: 8750,
        total_records: 25000,
        status: "processing",
        started_time: "2024-01-15T10:30:00Z"
      }
    ],
    total_records: 100000,
    records_processed: 65000,
    created_time: "2024-01-15T10:00:00Z",
    started_time: "2024-01-15T10:30:00Z",
    last_updated: "2024-01-15T12:15:00Z"
  },
  {
    id: 2,
    name: "Product Catalog Backup",
    description: "Backup product catalog to external storage",
    space_id: "space2",
    graph_id: 3,
    external_system: "AWS S3",
    parallel_slices: 2,
    status: "completed",
    overall_progress: 100,
    ranges: [
      {
        range_id: 1,
        hash_prefix_start: "00000000",
        hash_prefix_end: "7FFFFFFF",
        current_cursor: "7FFFFFFF",
        records_processed: 50000,
        total_records: 50000,
        status: "completed",
        started_time: "2024-01-14T14:00:00Z",
        completed_time: "2024-01-14T15:30:00Z"
      },
      {
        range_id: 2,
        hash_prefix_start: "80000000",
        hash_prefix_end: "FFFFFFFF",
        current_cursor: "FFFFFFFF",
        records_processed: 50000,
        total_records: 50000,
        status: "completed",
        started_time: "2024-01-14T14:00:00Z",
        completed_time: "2024-01-14T15:20:00Z"
      }
    ],
    total_records: 100000,
    records_processed: 100000,
    created_time: "2024-01-14T13:45:00Z",
    started_time: "2024-01-14T14:00:00Z",
    completed_time: "2024-01-14T15:30:00Z",
    last_updated: "2024-01-14T15:30:00Z"
  },
  {
    id: 3,
    name: "Analytics Data Export",
    description: "Export analytics data for machine learning pipeline",
    space_id: "space1",
    graph_id: 2,
    external_system: "ML Pipeline",
    parallel_slices: 8,
    status: "pending",
    overall_progress: 0,
    ranges: [
      {
        range_id: 1,
        hash_prefix_start: "00000000",
        hash_prefix_end: "1FFFFFFF",
        current_cursor: "00000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 2,
        hash_prefix_start: "20000000",
        hash_prefix_end: "3FFFFFFF",
        current_cursor: "20000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 3,
        hash_prefix_start: "40000000",
        hash_prefix_end: "5FFFFFFF",
        current_cursor: "40000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 4,
        hash_prefix_start: "60000000",
        hash_prefix_end: "7FFFFFFF",
        current_cursor: "60000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 5,
        hash_prefix_start: "80000000",
        hash_prefix_end: "9FFFFFFF",
        current_cursor: "80000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 6,
        hash_prefix_start: "A0000000",
        hash_prefix_end: "BFFFFFFF",
        current_cursor: "A0000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 7,
        hash_prefix_start: "C0000000",
        hash_prefix_end: "DFFFFFFF",
        current_cursor: "C0000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      },
      {
        range_id: 8,
        hash_prefix_start: "E0000000",
        hash_prefix_end: "FFFFFFFF",
        current_cursor: "E0000000",
        records_processed: 0,
        total_records: 37500,
        status: "pending"
      }
    ],
    total_records: 300000,
    records_processed: 0,
    created_time: "2024-01-16T09:00:00Z",
    last_updated: "2024-01-16T09:00:00Z"
  },
  {
    id: 4,
    name: "Order History Sync",
    description: "Sync order history to data warehouse",
    space_id: "space3",
    graph_id: 5,
    external_system: "Data Warehouse",
    parallel_slices: 6,
    status: "failed",
    overall_progress: 23,
    ranges: [
      {
        range_id: 1,
        hash_prefix_start: "00000000",
        hash_prefix_end: "2AAAAAAA",
        current_cursor: "15432ABC",
        records_processed: 8500,
        total_records: 33333,
        status: "failed",
        started_time: "2024-01-13T16:00:00Z"
      },
      {
        range_id: 2,
        hash_prefix_start: "2AAAAAAB",
        hash_prefix_end: "55555555",
        current_cursor: "2AAAAAAB",
        records_processed: 0,
        total_records: 33333,
        status: "pending"
      },
      {
        range_id: 3,
        hash_prefix_start: "55555556",
        hash_prefix_end: "80000000",
        current_cursor: "55555556",
        records_processed: 0,
        total_records: 33333,
        status: "pending"
      },
      {
        range_id: 4,
        hash_prefix_start: "80000001",
        hash_prefix_end: "AAAAAAAA",
        current_cursor: "80000001",
        records_processed: 0,
        total_records: 33333,
        status: "pending"
      },
      {
        range_id: 5,
        hash_prefix_start: "AAAAAAAB",
        hash_prefix_end: "D5555555",
        current_cursor: "AAAAAAAB",
        records_processed: 0,
        total_records: 33333,
        status: "pending"
      },
      {
        range_id: 6,
        hash_prefix_start: "D5555556",
        hash_prefix_end: "FFFFFFFF",
        current_cursor: "D5555556",
        records_processed: 0,
        total_records: 33334,
        status: "pending"
      }
    ],
    total_records: 200000,
    records_processed: 46000,
    created_time: "2024-01-13T15:30:00Z",
    started_time: "2024-01-13T16:00:00Z",
    last_updated: "2024-01-13T16:45:00Z",
    error_message: "Connection timeout to external system"
  }
];

export const mockDataCheckpoints: DataCheckpoint[] = [
  {
    id: 1,
    name: "Daily Backup Checkpoint",
    description: "Daily backup checkpoint for customer data",
    space_id: "space1",
    graph_id: 1,
    checkpoint_timestamp: "2024-01-15T23:59:59Z",
    checkpoint_hash: "a1b2c3d4e5f6789012345678901234567890abcd",
    purpose: "Daily backup",
    external_system: "Backup Service",
    created_time: "2024-01-16T00:05:00Z",
    created_by: "system"
  },
  {
    id: 2,
    name: "Pre-Migration Checkpoint",
    description: "Checkpoint before data migration to new system",
    space_id: "space2",
    graph_id: 3,
    checkpoint_timestamp: "2024-01-14T15:30:00Z",
    checkpoint_hash: "9876543210fedcba0987654321098765432109876",
    purpose: "Pre-migration snapshot",
    external_system: "Migration Tool",
    created_time: "2024-01-14T15:30:15Z",
    created_by: "admin"
  },
  {
    id: 3,
    name: "Sync Completion Marker",
    description: "External sync completion checkpoint",
    space_id: "space1",
    graph_id: 2,
    checkpoint_timestamp: "2024-01-16T14:22:30Z",
    checkpoint_hash: "def456789abc123456789def123456789abcdef12",
    purpose: "Sync completion",
    external_system: "CRM System",
    created_time: "2024-01-16T14:22:45Z",
    created_by: "sync-service"
  },
  {
    id: 4,
    name: "Weekly Archive Point",
    description: "Weekly archival checkpoint for analytics data",
    space_id: "space3",
    graph_id: 5,
    checkpoint_timestamp: "2024-01-14T23:59:59Z",
    checkpoint_hash: "123abc456def789012345678901234567890abcd",
    purpose: "Weekly archive",
    created_time: "2024-01-15T00:01:00Z",
    created_by: "archive-service"
  },
  {
    id: 5,
    name: "Manual Checkpoint",
    description: "Manual checkpoint before system maintenance",
    space_id: "space2",
    graph_id: 4,
    checkpoint_timestamp: "2024-01-13T16:45:00Z",
    checkpoint_hash: "fedcba9876543210fedcba9876543210fedcba98",
    purpose: "Pre-maintenance",
    created_time: "2024-01-13T16:45:30Z",
    created_by: "admin"
  }
];
