# VitalGraph Fuseki Docker Setup

This directory contains Docker Compose configuration to run Apache Jena Fuseki for testing the VitalGraph Fuseki implementation.

## Quick Start

1. **Start Fuseki Server:**
   ```bash
   cd /Users/hadfield/Local/vital-git/vital-graph/fuseki/docker
   docker-compose up -d
   ```

2. **Check Server Status:**
   ```bash
   docker-compose ps
   curl http://localhost:3030/$/ping
   ```

3. **Access Fuseki Web UI:**
   - URL: http://localhost:3030
   - Username: admin
   - Password: admin123

4. **Stop Fuseki Server:**
   ```bash
   docker-compose down
   ```

## Configuration

### Dataset Configuration
- **Dataset Name:** `vitalgraph`
- **Storage:** TDB2 (high-performance triple store)
- **Location:** `/fuseki/databases/vitalgraph` (persisted in Docker volume)
- **Union Default Graph:** Enabled (allows querying across all named graphs)

### Available Endpoints
- **SPARQL Query:** `http://localhost:3030/vitalgraph/sparql`
- **SPARQL Update:** `http://localhost:3030/vitalgraph/update`
- **Graph Store (Read/Write):** `http://localhost:3030/vitalgraph/data`
- **Upload:** `http://localhost:3030/vitalgraph/upload`

### VitalGraph Implementation Usage
The Fuseki implementation expects:
- **Server URL:** `http://localhost:3030`
- **Dataset Name:** `vitalgraph`
- **Authentication:** Basic Auth (admin/admin123)

## Testing the Implementation

### 1. Basic Connectivity Test
```bash
# Test server ping
curl http://localhost:3030/$/ping

# Test dataset query endpoint
curl -X POST http://localhost:3030/vitalgraph/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -u admin:admin123 \
  -d "SELECT * WHERE { ?s ?p ?o } LIMIT 10"
```

### 2. VitalGraph Space Operations Test
```python
# Example Python test
import asyncio
from vitalgraph.db.fuseki.fuseki_space_impl import FusekiSpaceImpl
from vitalgraph.db.space_inf import BackendConfig

async def test_fuseki():
    config = BackendConfig(
        backend_type="fuseki",
        server_url="http://localhost:3030",
        dataset_name="vitalgraph",
        username="admin",
        password="admin123"
    )
    
    fuseki_impl = FusekiSpaceImpl(config)
    
    # Test space creation
    success = await fuseki_impl.init_space_storage("test_space")
    print(f"Space creation: {success}")
    
    # Test space listing
    spaces = await fuseki_impl.list_spaces()
    print(f"Spaces: {spaces}")
    
    await fuseki_impl.close()

# Run test
asyncio.run(test_fuseki())
```

### 3. SPARQL Query Test
```bash
# Test space metadata query
curl -X POST http://localhost:3030/vitalgraph/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -u admin:admin123 \
  -d 'PREFIX vital: <http://vital.ai/ontology/vital-core#>
      SELECT ?space ?segmentID WHERE {
        GRAPH <urn:vitalgraph:spaces> {
          ?space a vital:VitalSegment ;
                 vital:hasSegmentID ?segmentID .
        }
      }'
```

## Directory Structure
```
fuseki/docker/
├── docker-compose.yml          # Docker Compose configuration
├── config/
│   └── config.ttl             # Fuseki server configuration
├── databases/                 # TDB2 database files (auto-created)
├── logs/                      # Fuseki server logs (auto-created)
└── README.md                  # This file
```

## Troubleshooting

### Common Issues

1. **Port 3030 already in use:**
   ```bash
   # Check what's using the port
   lsof -i :3030
   # Change port in docker-compose.yml if needed
   ```

2. **Permission issues with volumes:**
   ```bash
   # Fix permissions
   sudo chown -R $USER:$USER ./databases ./logs
   ```

3. **Container won't start:**
   ```bash
   # Check logs
   docker-compose logs fuseki
   ```

4. **Dataset not accessible:**
   - Verify the dataset name matches in config.ttl and your code
   - Check authentication credentials
   - Ensure the container is fully started (wait for healthcheck)

### Useful Commands

```bash
# View real-time logs
docker-compose logs -f fuseki

# Restart service
docker-compose restart fuseki

# Clean up everything (removes data!)
docker-compose down -v

# Execute commands in container
docker-compose exec fuseki bash
```

## Performance Tuning

For production use, consider:

1. **Increase JVM memory:**
   ```yaml
   environment:
     - JVM_ARGS=-Xmx4g -Xms2g
   ```

2. **Enable TDB2 statistics:**
   ```turtle
   <#vitalgraph_dataset> rdf:type tdb2:DatasetTDB2 ;
       tdb2:location "/fuseki/databases/vitalgraph" ;
       tdb2:unionDefaultGraph true ;
       tdb2:enableStats true .
   ```

3. **Add resource limits:**
   ```yaml
   deploy:
     resources:
       limits:
         memory: 4G
         cpus: '2'
   ```
