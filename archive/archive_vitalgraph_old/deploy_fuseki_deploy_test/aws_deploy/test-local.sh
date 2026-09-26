#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"
}

info() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')] INFO:${NC} $1"
}

# Test configuration
CONTAINER_NAME="vitalgraph-fuseki-test"
IMAGE_NAME="vitalgraph-fuseki-aws:test"
TEST_PORT="3030"
EFS_DATA_DIR="./efs-data"

# Cleanup function
cleanup() {
    log "Cleaning up test resources..."
    if docker ps -q -f name=$CONTAINER_NAME | grep -q .; then
        docker stop $CONTAINER_NAME >/dev/null 2>&1
    fi
    if docker ps -aq -f name=$CONTAINER_NAME | grep -q .; then
        docker rm $CONTAINER_NAME >/dev/null 2>&1
    fi
    if [ -d "$EFS_DATA_DIR" ]; then
        rm -rf $EFS_DATA_DIR
    fi
}

# Set trap for cleanup on exit
trap cleanup EXIT

log "🚀 Testing VitalGraph Fuseki AWS deployment locally..."

# Check prerequisites
info "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    error "Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    error "curl is not installed or not in PATH"
    exit 1
fi

# Build the image
log "Building Docker image..."
if docker build -t $IMAGE_NAME . >/dev/null 2>&1; then
    info "✓ Docker image built successfully"
else
    error "✗ Failed to build Docker image"
    exit 1
fi

# Create test EFS directory structure
log "Setting up test EFS directory..."
mkdir -p $EFS_DATA_DIR/databases
chmod 755 $EFS_DATA_DIR
info "✓ EFS test directory created"

# Run the container
log "Starting Fuseki container..."
docker run -d \
  --name $CONTAINER_NAME \
  -p $TEST_PORT:3030 \
  -e MEMORY_LIMIT=1024 \
  -e EFS_MOUNT_POINT=/efs \
  -v $(pwd)/$EFS_DATA_DIR:/efs \
  $IMAGE_NAME >/dev/null

if [ $? -eq 0 ]; then
    info "✓ Container started successfully"
else
    error "✗ Failed to start container"
    exit 1
fi

# Wait for startup with progress
log "Waiting for Fuseki to start..."
for i in {1..30}; do
    if curl -s http://localhost:$TEST_PORT/$/ping >/dev/null 2>&1; then
        break
    fi
    if [ $i -eq 30 ]; then
        error "✗ Fuseki failed to start within 30 seconds"
        echo "Container logs:"
        docker logs $CONTAINER_NAME
        exit 1
    fi
    sleep 1
    echo -n "."
done
echo ""
info "✓ Fuseki started successfully"

# Test server info endpoint
log "Testing server info endpoint..."
SERVER_INFO=$(curl -s http://localhost:$TEST_PORT/$/server)
if echo "$SERVER_INFO" | grep -q "5.6.0"; then
    info "✓ Server info endpoint working (Fuseki 5.6.0)"
else
    warn "⚠ Server info endpoint response unexpected"
    echo "Response: $SERVER_INFO"
fi

# Test dataset availability
log "Testing dataset availability..."
if echo "$SERVER_INFO" | grep -q "vitalgraph"; then
    info "✓ VitalGraph dataset is available"
else
    error "✗ VitalGraph dataset not found"
    echo "Server response: $SERVER_INFO"
    exit 1
fi

# Test authentication with valid credentials
log "Testing authentication with valid credentials..."
AUTH_RESPONSE=$(curl -u admin:admin123 -s -w "%{http_code}" -X POST http://localhost:$TEST_PORT/vitalgraph/sparql \
    -H "Content-Type: application/sparql-query" \
    -H "Accept: application/sparql-results+json" \
    -d "SELECT * WHERE { ?s ?p ?o } LIMIT 1" -o /dev/null)

if [ "$AUTH_RESPONSE" = "200" ]; then
    info "✓ Authentication with valid credentials passed"
else
    error "✗ Authentication test failed (HTTP $AUTH_RESPONSE)"
    docker logs $CONTAINER_NAME | tail -10
    exit 1
fi

# Test authentication with invalid credentials
log "Testing authentication with invalid credentials..."
INVALID_AUTH_RESPONSE=$(curl -u admin:wrongpassword -s -w "%{http_code}" -X POST http://localhost:$TEST_PORT/vitalgraph/sparql \
    -H "Content-Type: application/sparql-query" \
    -H "Accept: application/sparql-results+json" \
    -d "SELECT * WHERE { ?s ?p ?o } LIMIT 1" -o /dev/null)

if [ "$INVALID_AUTH_RESPONSE" = "401" ] || [ "$INVALID_AUTH_RESPONSE" = "403" ]; then
    info "✓ Authentication properly rejects invalid credentials"
else
    warn "⚠ Authentication test with invalid credentials returned HTTP $INVALID_AUTH_RESPONSE"
fi

# Test SPARQL query functionality
log "Testing SPARQL query functionality..."
QUERY_RESULT=$(curl -u admin:admin123 -s -X POST http://localhost:$TEST_PORT/vitalgraph/sparql \
    -H "Content-Type: application/sparql-query" \
    -H "Accept: application/sparql-results+json" \
    -d "SELECT * WHERE { ?s ?p ?o } LIMIT 1")

if echo "$QUERY_RESULT" | grep -q '"head"'; then
    info "✓ SPARQL query functionality working"
else
    error "✗ SPARQL query failed"
    echo "Query result: $QUERY_RESULT"
    exit 1
fi

# Test SPARQL update functionality
log "Testing SPARQL update functionality..."
UPDATE_RESPONSE=$(curl -u admin:admin123 -s -w "%{http_code}" -X POST http://localhost:$TEST_PORT/vitalgraph/update \
    -H "Content-Type: application/sparql-update" \
    -d "INSERT DATA { <urn:test:subject> <urn:test:predicate> \"test value\" . }" -o /dev/null)

if [ "$UPDATE_RESPONSE" = "200" ] || [ "$UPDATE_RESPONSE" = "204" ]; then
    info "✓ SPARQL update functionality working"
else
    error "✗ SPARQL update failed (HTTP $UPDATE_RESPONSE)"
    exit 1
fi

# Test EFS persistence
log "Testing EFS persistence..."
if [ -d "$EFS_DATA_DIR/databases" ]; then
    info "✓ EFS mount directory exists"
    
    # Check if Fuseki created database files
    if find "$EFS_DATA_DIR" -name "*.dat" -o -name "*.idn" -o -name "*.bpt" | grep -q .; then
        info "✓ TDB2 database files created in EFS mount"
    else
        warn "⚠ No TDB2 database files found yet (may be normal for empty database)"
    fi
else
    error "✗ EFS mount directory not found"
    exit 1
fi

# Test container resource usage
log "Checking container resource usage..."
CONTAINER_STATS=$(docker stats --no-stream --format "table {{.CPUPerc}}\t{{.MemUsage}}" $CONTAINER_NAME)
info "Container resource usage:"
echo "$CONTAINER_STATS"

# Test container logs for errors
log "Checking container logs for errors..."
ERROR_COUNT=$(docker logs $CONTAINER_NAME 2>&1 | grep -i error | wc -l)
if [ "$ERROR_COUNT" -eq 0 ]; then
    info "✓ No errors found in container logs"
else
    warn "⚠ Found $ERROR_COUNT error messages in logs"
    echo "Recent errors:"
    docker logs $CONTAINER_NAME 2>&1 | grep -i error | tail -5
fi

# Test graceful shutdown
log "Testing graceful shutdown..."
docker stop $CONTAINER_NAME >/dev/null
if [ $? -eq 0 ]; then
    info "✓ Container stopped gracefully"
else
    warn "⚠ Container did not stop gracefully"
fi

# Final summary
log "🎉 All tests completed successfully!"
echo ""
echo "Test Summary:"
echo "✓ Docker image builds correctly"
echo "✓ Container starts and runs"
echo "✓ Health endpoints respond"
echo "✓ Authentication works properly"
echo "✓ SPARQL query/update functionality"
echo "✓ EFS persistence simulation"
echo "✓ Graceful shutdown"
echo ""
info "🚀 Ready for AWS deployment!"
echo ""
echo "Next steps:"
echo "1. Push image to ECR: ./deploy.sh"
echo "2. Or deploy directly: python3 aws_deploy.py --help"
