# Weaviate API Test Script

Test script for accessing a Weaviate deployment via REST API, GraphQL API, and gRPC API.

## Overview

This script tests connectivity to a Weaviate instance with JWT authentication via Keycloak.

**Endpoints tested:**
- REST API: Configured via `WEAVIATE_REST_URL`
- GraphQL API: `{WEAVIATE_REST_URL}/graphql`
- gRPC API: Configured via `WEAVIATE_GRPC_HOST` and `WEAVIATE_GRPC_PORT`

## Prerequisites

1. **Dependencies installed:**
   ```bash
   pip install weaviate-client requests python-dotenv
   ```
   
   Or install with server dependencies:
   ```bash
   pip install -e ".[server]"
   ```

2. **Configuration in `.env` file:**
   
   The script loads credentials from `/Users/hadfield/Local/vital-git/vital-graph/.env`
   
   Required environment variables (see `.env` file for actual values):
   ```bash
   # Weaviate Configuration
   WEAVIATE_KEYCLOAK_URL=<keycloak-token-endpoint-url>
   WEAVIATE_CLIENT_ID=<client-id>
   WEAVIATE_CLIENT_SECRET=<client-secret>
   WEAVIATE_USERNAME=<username>
   WEAVIATE_PASSWORD=<password>
   WEAVIATE_REST_URL=<weaviate-rest-api-url>
   WEAVIATE_HTTP_HOST=<weaviate-http-host>
   WEAVIATE_GRPC_HOST=<weaviate-grpc-host>
   WEAVIATE_GRPC_PORT=<grpc-port>
   ```
   
   **Note:** All credentials are stored in the `.env` file at the project root. Never commit credentials to version control.

## Running the Test

```bash
cd /Users/hadfield/Local/vital-git/vital-graph
python test_scripts/weaviate/test_weaviate_api.py
```

## What the Script Tests

1. **JWT Token Acquisition**
   - Authenticates with Keycloak using OAuth2 password grant
   - Obtains JWT access token (expires in 5 minutes)
   - Displays token expiration time

2. **REST API Test**
   - Calls `/v1/meta` endpoint
   - Verifies Weaviate version and module count
   - Expected: Version 1.34.0 with ~40 modules

3. **GraphQL API Test**
   - Executes GraphQL introspection query
   - Verifies GraphQL endpoint is responding
   - Tests query execution capability

4. **gRPC API Test**
   - Connects via Weaviate Python client
   - Lists all collections in the instance
   - Verifies gRPC connectivity and functionality

## Expected Output

```
==============================================================================
WEAVIATE API TEST SCRIPT
==============================================================================

Configuration loaded:
  - Keycloak: <keycloak-url>
  - REST API: <weaviate-rest-url>
  - gRPC: <weaviate-grpc-host>:<port>

→ Getting JWT token from Keycloak...
✓ Token obtained (expires in 300 seconds)

→ Testing REST API (/v1/meta)...
✓ REST API working
  - Version: 1.34.0
  - Modules: 40

→ Testing GraphQL API...
✓ GraphQL API working

→ Testing gRPC API (via Python client)...
✓ gRPC API working
  - Collections: 5
  - Collection names: Collection1, Collection2, ...

==============================================================================
TEST SUMMARY
==============================================================================
✅ PASS - REST API
✅ PASS - GraphQL API
✅ PASS - gRPC API

✅ All endpoints working!
```

## Troubleshooting

### Token Expired Error
JWT tokens expire in 5 minutes. If you see authentication errors, the script will automatically request a new token.

### Connection Errors
- Verify network connectivity to your Weaviate deployment
- Check that SSL certificates are trusted
- Ensure firewall allows HTTPS (443) and gRPC (50051) traffic

### Missing Dependencies
```bash
pip install weaviate-client requests python-dotenv
```

### Configuration Errors
Verify all required environment variables are set in `.env` file at project root.

## Security Notes

- **Credentials in `.env`**: Keep the `.env` file secure and never commit to version control
- **Token Expiration**: JWT tokens expire in 5 minutes for security
- **HTTPS**: All REST/GraphQL traffic uses HTTPS with SSL certificates
- **gRPC**: Currently configured without TLS (grpc_secure=False)

## Architecture Details

**Authentication Flow:**
1. Client → Keycloak: OAuth2 password grant with client credentials
2. Keycloak → Client: JWT access token
3. Client → Weaviate: Bearer token in Authorization header

**Load Balancer:**
- Type: Network Load Balancer (NLB)
- SSL Termination: Yes (with appropriate SSL certificate)
- Ports: 443 (HTTPS), 50051 (gRPC)

**Weaviate Version:**
- Version: Varies by deployment
- Modules: Varies by configuration
- Deployment: Configured via environment variables
