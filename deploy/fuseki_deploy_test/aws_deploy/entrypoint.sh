#!/bin/bash
set -e

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting VitalGraph Fuseki Server..."

# Ensure database directory exists and has correct permissions
if [ ! -d "/fuseki/databases" ]; then
    log "Creating databases directory..."
    mkdir -p /fuseki/databases
fi

# Check if we're using EFS/persistent storage
if [ -n "$EFS_MOUNT_POINT" ]; then
    log "Using EFS persistent storage at: $EFS_MOUNT_POINT"
    # Create symlink to EFS if it doesn't exist
    if [ ! -L "/fuseki/databases" ]; then
        rm -rf /fuseki/databases
        ln -sf "$EFS_MOUNT_POINT/databases" /fuseki/databases
    fi
    # Ensure EFS directory exists
    mkdir -p "$EFS_MOUNT_POINT/databases"
fi

# Set JVM options based on available memory
if [ -n "$MEMORY_LIMIT" ]; then
    # Calculate heap size as 75% of available memory
    HEAP_SIZE=$((MEMORY_LIMIT * 3 / 4))
    export JAVA_OPTIONS="-Xmx${HEAP_SIZE}m -Xms${HEAP_SIZE}m"
    log "Set heap size to ${HEAP_SIZE}MB based on memory limit ${MEMORY_LIMIT}MB"
fi

# Wait for dependencies if specified
if [ -n "$WAIT_FOR_DEPS" ]; then
    log "Waiting for dependencies: $WAIT_FOR_DEPS"
    for dep in $WAIT_FOR_DEPS; do
        log "Waiting for $dep..."
        until curl -f "$dep" >/dev/null 2>&1; do
            sleep 5
        done
        log "$dep is ready"
    done
fi

# Start Fuseki server
log "Starting Fuseki server with config: /fuseki/config.ttl"
log "Java options: $JAVA_OPTIONS"
log "Database location: /fuseki/databases"

exec /fuseki/fuseki-server \
    --config=/fuseki/config.ttl \
    --port=3030 \
    --verbose
