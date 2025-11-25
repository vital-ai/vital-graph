# VitalGraph

VitalGraph is a high-performance knowledge graph database and client library built on PostgreSQL with full SPARQL 1.1 support.

## Installation

VitalGraph offers flexible installation options depending on your use case:

### Client Only (Default - Lightweight)

For applications that only need to connect to existing VitalGraph servers:

```bash
pip install vital-graph[client]
```

This installs dependencies for the VitalGraph client library:
- Basic RDF processing (rdflib, PyLD)
- Advanced graph processing (pyoxigraph) - now included by default
- AI capabilities (openai) - now included by default
- HTTP client (requests)
- Configuration management (PyYAML, pydantic)
- CLI tools (click-repl, tabulate)

### Server Installation

For running a complete VitalGraph server with database capabilities:

```bash
pip install vital-graph[server]
```

This includes all server dependencies:
- FastAPI web framework and uvicorn server
- PostgreSQL drivers (psycopg, asyncpg)
- Database ORM (SQLAlchemy, alembic)
- Vector database support (pgvector)
- Authentication (PyJWT, email-validator)
- TiDB integration (pytidb[models], pytidb)

### Development Setup

For development with all tools:

```bash
pip install vital-graph[dev]
```

Includes pytest, black, mypy, and other development tools.

### Full Installation

For everything:

```bash
pip install vital-graph[all]
```

### Custom Combinations

You can combine multiple extras:

```bash
pip install vital-graph[client,dev]
pip install vital-graph[server,test,docs]
```

## Quick Start

### Client Usage

```python
from vitalgraph.client import VitalGraphClient

# Initialize client with config file
client = VitalGraphClient("path/to/config.yaml")

# Connect to server
await client.open()

# Execute SPARQL queries
results = await client.sparql.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")

# Close connection
await client.close()
```

### Server Usage

```bash
# Start VitalGraph server
vitalgraphdb

# Or with custom config
vitalgraphdb --config /path/to/vitalgraphdb-config.yaml
```

## Features

- **Full SPARQL 1.1 Support**: SELECT, CONSTRUCT, ASK, DESCRIBE, UPDATE operations
- **High Performance**: PostgreSQL-backed with optimized query translation
- **RESTful API**: Complete REST API for all operations
- **Client Library**: Python client with authentication and session management
- **Docker Support**: Ready-to-use Docker containers
- **Knowledge Graph Types**: Built-in support for VitalSigns ontologies
- **Real-time Updates**: WebSocket support for live data updates

## Architecture

VitalGraph consists of:

- **Client Library** (`vitalgraph.client`): Lightweight REST API client
- **Server** (`vitalgraph.server`): FastAPI-based graph database server
- **Database Layer** (`vitalgraph.db`): PostgreSQL integration with SPARQL translation
- **Admin Tools** (`vitalgraphadmin`): Database administration utilities

## Documentation

- [Installation Guide](docs/installation.md)
- [Client API Reference](docs/client-api.md)
- [Server Configuration](docs/server-config.md)
- [SPARQL Examples](docs/sparql-examples.md)

## License

Apache License 2.0