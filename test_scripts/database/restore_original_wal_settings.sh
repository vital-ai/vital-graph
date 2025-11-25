#!/bin/bash
# Script to restore original WAL settings after bulk import

echo "🔄 Restoring Original WAL Settings..."
psql-17 -h host.docker.internal -U postgres -d vitalgraphdb << 'EOF'
ALTER SYSTEM SET max_wal_size = '4GB';
ALTER SYSTEM SET checkpoint_timeout = '30min';
ALTER SYSTEM SET wal_buffers = '4MB';
ALTER SYSTEM SET maintenance_work_mem = '1GB';
SELECT pg_reload_conf();
\q
EOF

echo "✅ Original settings restored"
