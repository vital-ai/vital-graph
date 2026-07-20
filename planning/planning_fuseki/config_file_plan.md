# VitalGraph Configuration Refactoring Plan for ECS Deployment

## Overview
Refactor the VitalGraph configuration system to use **pure environment variable configuration** with AWS Secrets Manager for secure deployment to AWS ECS via GitHub Actions. This eliminates YAML config files in favor of a flat, environment-variable-driven approach that works seamlessly with container orchestration platforms.

## Architecture Decision
**No YAML Config Files** - All configuration will come from:
1. Environment variables (for non-sensitive, environment-specific values)
2. AWS Secrets Manager (for sensitive credentials)
3. Application defaults (hardcoded sensible defaults in code)

**Naming Convention**: Flat structure with prefix
```
VITALGRAPH_<COMPONENT>_<SETTING>=value
```

## Current Configuration Structure

The current config file (`vitalgraphdb-config-fuseki-postgresql.yaml`) contains configuration that will be migrated to environment variables:
- Backend type selection → `VITALGRAPH_BACKEND_TYPE`
- PostgreSQL connection details → `VITALGRAPH_DB_*` variables
- Fuseki connection details → `VITALGRAPH_FUSEKI_*` variables  
- Transaction settings → `VITALGRAPH_TRANSACTION_*` variables
- Backup settings → `VITALGRAPH_BACKUP_*` variables
- SPARQL settings → `VITALGRAPH_SPARQL_*` variables
- Table prefix → `VITALGRAPH_TABLE_PREFIX`
- Application auth → `VITALGRAPH_AUTH_*` variables
- File storage → `VITALGRAPH_STORAGE_*` variables
- Application settings → `VITALGRAPH_APP_*` variables

## Current Implementation Review

### Existing `.env` File
The project already has a `.env` file with the following structure:
- **OpenAI API Key**: `OPENAI_API_KEY` (currently exposed - needs to move to secrets)
- **Application Mode**: `APP_MODE=production`
- **Environment Selection**: `VITALGRAPH_ENVIRONMENT=local` (controls which config file is copied in Docker)
- **Server Configuration**: `PORT=8001`, `HOST=0.0.0.0`
- **JWT Secret**: `JWT_SECRET_KEY` (currently exposed - needs to move to secrets)
- **Keycloak Configuration**: Full Keycloak setup for Fuseki authentication
  - `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`
  - `KEYCLOAK_USERNAME`, `KEYCLOAK_PASSWORD`
- **Fuseki URL**: `FUSEKI_URL` (environment-specific)
- **Weaviate Configuration**: Complete Weaviate setup for Acme Bank deployment
  - Keycloak token URL, client credentials
  - REST and gRPC endpoints

⚠️ **SECURITY NOTE**: The `.env` file contains production credentials including:
- Real OpenAI API key
- Real Keycloak credentials for acmebank.co
- Real Weaviate client secrets
- Production URLs and endpoints

✅ **CONFIRMED**: `.env` is already in `.gitignore` and has never been committed to the repository.

### Existing `docker-compose.yml`
The current Docker Compose setup:
- Uses build arg `VITALGRAPH_ENVIRONMENT` to select config file at build time
- Passes environment variables from `.env` file
- Includes MinIO service for local file storage
- Uses volumes for data persistence
- Has proper health checks for MinIO
- Network configuration for service communication

### Existing `Dockerfile`
The current Dockerfile:
- Uses Python 3.12-slim base image
- Installs Node.js 20 for frontend build
- Uses build arg `VITALGRAPH_ENVIRONMENT` (default: `local`)
- Copies environment-specific config at build time:
  ```dockerfile
  ARG VITALGRAPH_ENVIRONMENT=local
  COPY vitalgraphdb_config/vitalgraphdb-config-${VITALGRAPH_ENVIRONMENT}.yaml /app/vitalgraphdb_config/vitalgraphdb-config.yaml
  ```
- Uses `vitalgraphdb_cmd` as entrypoint (not `vitalgraph_api`)
- Sets `VITAL_HOME=/app/vitalhome` for VitalSigns
- Builds frontend during image build

## Security Classification

### Sensitive Values (AWS Secrets Manager)
These values should NEVER be in the repository and must come from AWS Secrets:

**Database Credentials:**
- `fuseki_postgresql.database.password`
- `fuseki_postgresql.database.username`

**Fuseki Credentials:**
- `fuseki_postgresql.fuseki.username`
- `fuseki_postgresql.fuseki.password`

**Application Auth:**
- `auth.root_username`
- `auth.root_password`
- `JWT_SECRET_KEY` (from .env)

**File Storage Credentials:**
- `file_storage.minio.access_key_id`
- `file_storage.minio.secret_access_key`
- `file_storage.s3.access_key_id`
- `file_storage.s3.secret_access_key`

**External Service Credentials (from .env):**
- `OPENAI_API_KEY`
- `KEYCLOAK_USERNAME`
- `KEYCLOAK_PASSWORD`
- `KEYCLOAK_CLIENT_ID` (if sensitive)
- `WEAVIATE_CLIENT_SECRET`
- `WEAVIATE_USERNAME`
- `WEAVIATE_PASSWORD`

### Environment-Specific Values (Environment Variables)
These values change per environment (dev/staging/prod):

**Database Configuration:**
- `fuseki_postgresql.database.host`
- `fuseki_postgresql.database.port`
- `fuseki_postgresql.database.database`

**Fuseki Configuration:**
- `fuseki_postgresql.fuseki.server_url` (maps to `FUSEKI_URL` in .env)
- `fuseki_postgresql.fuseki.dataset_name`

**File Storage Configuration:**
- `file_storage.backend` (minio vs s3)
- `file_storage.minio.endpoint_url`
- `file_storage.s3.endpoint_url`
- `file_storage.s3.bucket_name`
- `file_storage.s3.region`

**Application Settings:**
- `app.log_level`
- `APP_MODE` (from .env)
- `PORT` (from .env)
- `HOST` (from .env)

**External Service URLs (from .env):**
- `KEYCLOAK_URL`
- `KEYCLOAK_REALM`
- `WEAVIATE_KEYCLOAK_URL`
- `WEAVIATE_REST_URL`
- `WEAVIATE_HTTP_HOST`
- `WEAVIATE_GRPC_HOST`
- `WEAVIATE_GRPC_PORT`
- `WEAVIATE_CLIENT_ID` (if not sensitive)

### Static Configuration Values (Config File)
These values are consistent across environments:
- `backend.type`
- `fuseki_postgresql.database.pool_size`
- `fuseki_postgresql.database.max_overflow`
- `fuseki_postgresql.database.pool_timeout`
- `fuseki_postgresql.database.pool_recycle`
- `fuseki_postgresql.database.enable_quad_logging`
- `fuseki_postgresql.transaction.*`
- `fuseki_postgresql.backup.*`
- `fuseki_postgresql.sparql.*`
- `tables.prefix`
- `file_storage.settings.*`

## Proposed Architecture

### 1. Configuration Loading Strategy

```
Priority Order (highest to lowest):
1. Environment Variables (runtime overrides)
2. AWS Secrets Manager (injected at deployment)
3. Config File (base configuration)
4. Default Values (fallback)
```

### 2. Environment Variable Naming Convention

**Flat structure with prefix** (POSIX-compliant, works everywhere):
```
VITALGRAPH_<COMPONENT>_<SETTING>=value
```

**Complete Variable List**:

**Database Configuration:**
- `VITALGRAPH_DB_HOST` (e.g., localhost, RDS endpoint)
- `VITALGRAPH_DB_PORT` (default: 5432)
- `VITALGRAPH_DB_NAME` (e.g., vitalgraph_prod)
- `VITALGRAPH_DB_USERNAME` (from secrets)
- `VITALGRAPH_DB_PASSWORD` (from secrets)
- `VITALGRAPH_DB_POOL_SIZE` (default: 10)
- `VITALGRAPH_DB_MAX_OVERFLOW` (default: 20)
- `VITALGRAPH_DB_POOL_TIMEOUT` (default: 30)
- `VITALGRAPH_DB_POOL_RECYCLE` (default: 3600)

**Fuseki Configuration:**
- `VITALGRAPH_FUSEKI_URL` (e.g., http://fuseki:3030)
- `VITALGRAPH_FUSEKI_DATASET` (default: vitalgraph)
- `VITALGRAPH_FUSEKI_USERNAME` (from secrets)
- `VITALGRAPH_FUSEKI_PASSWORD` (from secrets)

**Application Configuration:**
- `VITALGRAPH_BACKEND_TYPE` (e.g., fuseki_postgresql)
- `VITALGRAPH_TABLE_PREFIX` (default: vitalgraph_)
- `VITALGRAPH_LOG_LEVEL` (default: INFO)
- `VITALGRAPH_AUTH_ROOT_USERNAME` (from secrets)
- `VITALGRAPH_AUTH_ROOT_PASSWORD` (from secrets)
- `APP_MODE` (production/development)
- `PORT` (default: 8001)
- `HOST` (default: 0.0.0.0)
- `JWT_SECRET_KEY` (from secrets)

**File Storage Configuration:**
- `VITALGRAPH_STORAGE_BACKEND` (minio or s3)
- `VITALGRAPH_STORAGE_ENDPOINT` (for MinIO)
- `VITALGRAPH_STORAGE_BUCKET` (bucket name)
- `VITALGRAPH_STORAGE_REGION` (default: us-east-1)
- `VITALGRAPH_STORAGE_ACCESS_KEY` (from secrets)
- `VITALGRAPH_STORAGE_SECRET_KEY` (from secrets)
- `VITALGRAPH_STORAGE_USE_SSL` (default: true)

**External Services:**
- `OPENAI_API_KEY` (from secrets)
- `KEYCLOAK_URL`
- `KEYCLOAK_REALM`
- `KEYCLOAK_CLIENT_ID` (from secrets)
- `KEYCLOAK_USERNAME` (from secrets)
- `KEYCLOAK_PASSWORD` (from secrets)
- `WEAVIATE_REST_URL`
- `WEAVIATE_HTTP_HOST`
- `WEAVIATE_GRPC_HOST`
- `WEAVIATE_GRPC_PORT`
- `WEAVIATE_CLIENT_ID`
- `WEAVIATE_CLIENT_SECRET` (from secrets)
- `WEAVIATE_USERNAME` (from secrets)
- `WEAVIATE_PASSWORD` (from secrets)

### 3. AWS Secrets Manager Structure

Create a single secret per environment with JSON structure:

**Secret Name**: `vitalgraph/{environment}/credentials`

**Secret Structure**:
```json
{
  "database": {
    "username": "postgres_user",
    "password": "secure_db_password"
  },
  "fuseki": {
    "username": "fuseki_user",
    "password": "secure_fuseki_password"
  },
  "auth": {
    "root_username": "admin",
    "root_password": "secure_admin_password",
    "jwt_secret_key": "secure_jwt_secret_key"
  },
  "s3": {
    "access_key_id": "AKIAIOSFODNN7EXAMPLE",
    "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
  },
  "openai": {
    "api_key": "sk-..."
  },
  "keycloak": {
    "username": "keycloak_user",
    "password": "keycloak_password",
    "client_id": "fuseki-graphdb"
  },
  "weaviate": {
    "client_secret": "weaviate_client_secret",
    "username": "weaviate_user",
    "password": "weaviate_password"
  }
}
```

### 4. Configuration Loading Strategy

**No YAML files** - Enhance existing `VitalGraphConfig` class to load entirely from environment variables.

**Update Existing Class** (`vitalgraph/config/config_loader.py`):

```python
import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Raised when there are configuration loading or validation errors."""
    pass

class VitalGraphConfig:
    """
    VitalGraphDB configuration loader and manager.
    Loads configuration entirely from environment variables with sensible defaults.
    """
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        self.config_data: Dict[str, Any] = self._load_from_env()
        self.config_path: Optional[str] = None  # No file path
        logger.info("Loaded configuration from environment variables")
    
    def _load_from_env(self) -> Dict[str, Any]:
        """Build complete configuration from environment variables."""
        return {
            'backend': {
                'type': os.getenv('VITALGRAPH_BACKEND_TYPE', 'fuseki_postgresql')
            },
            'database': {
                'host': os.getenv('VITALGRAPH_DB_HOST', 'localhost'),
                'port': int(os.getenv('VITALGRAPH_DB_PORT', '5432')),
                'database': os.getenv('VITALGRAPH_DB_NAME', 'vitalgraph'),
                'username': os.getenv('VITALGRAPH_DB_USERNAME', 'postgres'),
                'password': os.getenv('VITALGRAPH_DB_PASSWORD', ''),
                'pool_size': int(os.getenv('VITALGRAPH_DB_POOL_SIZE', '10')),
                'max_overflow': int(os.getenv('VITALGRAPH_DB_MAX_OVERFLOW', '20')),
                'pool_timeout': int(os.getenv('VITALGRAPH_DB_POOL_TIMEOUT', '30')),
                'pool_recycle': int(os.getenv('VITALGRAPH_DB_POOL_RECYCLE', '3600')),
                'enable_quad_logging': os.getenv('VITALGRAPH_DB_ENABLE_QUAD_LOGGING', 'false').lower() == 'true'
            },
            'fuseki': {
                'server_url': os.getenv('VITALGRAPH_FUSEKI_URL', 'http://localhost:3030'),
                'dataset_name': os.getenv('VITALGRAPH_FUSEKI_DATASET', 'vitalgraph'),
                'username': os.getenv('VITALGRAPH_FUSEKI_USERNAME', ''),
                'password': os.getenv('VITALGRAPH_FUSEKI_PASSWORD', '')
            },
            'fuseki_postgresql': {
                'database': {
                    'host': os.getenv('VITALGRAPH_DB_HOST', 'localhost'),
                    'port': int(os.getenv('VITALGRAPH_DB_PORT', '5432')),
                    'database': os.getenv('VITALGRAPH_DB_NAME', 'vitalgraph'),
                    'username': os.getenv('VITALGRAPH_DB_USERNAME', 'postgres'),
                    'password': os.getenv('VITALGRAPH_DB_PASSWORD', ''),
                    'pool_size': int(os.getenv('VITALGRAPH_DB_POOL_SIZE', '10')),
                    'max_overflow': int(os.getenv('VITALGRAPH_DB_MAX_OVERFLOW', '20')),
                    'pool_timeout': int(os.getenv('VITALGRAPH_DB_POOL_TIMEOUT', '30')),
                    'pool_recycle': int(os.getenv('VITALGRAPH_DB_POOL_RECYCLE', '3600'))
                },
                'fuseki': {
                    'server_url': os.getenv('VITALGRAPH_FUSEKI_URL', 'http://localhost:3030'),
                    'dataset_name': os.getenv('VITALGRAPH_FUSEKI_DATASET', 'vitalgraph'),
                    'username': os.getenv('VITALGRAPH_FUSEKI_USERNAME', ''),
                    'password': os.getenv('VITALGRAPH_FUSEKI_PASSWORD', '')
                },
                'transaction': {
                    'timeout': int(os.getenv('VITALGRAPH_TRANSACTION_TIMEOUT', '30')),
                    'isolation_level': os.getenv('VITALGRAPH_TRANSACTION_ISOLATION', 'READ_COMMITTED')
                },
                'backup': {
                    'enabled': os.getenv('VITALGRAPH_BACKUP_ENABLED', 'false').lower() == 'true',
                    'directory': os.getenv('VITALGRAPH_BACKUP_DIR', '/var/backups/vitalgraph')
                },
                'sparql': {
                    'query_timeout': int(os.getenv('VITALGRAPH_SPARQL_QUERY_TIMEOUT', '300')),
                    'max_results': int(os.getenv('VITALGRAPH_SPARQL_MAX_RESULTS', '10000'))
                },
                'table_prefix': os.getenv('VITALGRAPH_TABLE_PREFIX', 'vitalgraph_')
            },
            'tables': {
                'prefix': os.getenv('VITALGRAPH_TABLE_PREFIX', 'vg_')
            },
            'auth': {
                'root_username': os.getenv('VITALGRAPH_AUTH_ROOT_USERNAME', 'admin'),
                'root_password': os.getenv('VITALGRAPH_AUTH_ROOT_PASSWORD', 'admin')
            },
            'file_storage': {
                'backend': os.getenv('VITALGRAPH_STORAGE_BACKEND', 'minio'),
                'minio': {
                    'endpoint_url': os.getenv('VITALGRAPH_STORAGE_ENDPOINT', 'http://localhost:9000'),
                    'access_key_id': os.getenv('VITALGRAPH_STORAGE_ACCESS_KEY', 'minioadmin'),
                    'secret_access_key': os.getenv('VITALGRAPH_STORAGE_SECRET_KEY', 'minioadmin'),
                    'bucket_name': os.getenv('VITALGRAPH_STORAGE_BUCKET', 'vitalgraph-files'),
                    'use_ssl': os.getenv('VITALGRAPH_STORAGE_USE_SSL', 'false').lower() == 'true'
                },
                's3': {
                    'endpoint_url': os.getenv('VITALGRAPH_STORAGE_ENDPOINT', ''),
                    'access_key_id': os.getenv('VITALGRAPH_STORAGE_ACCESS_KEY', ''),
                    'secret_access_key': os.getenv('VITALGRAPH_STORAGE_SECRET_KEY', ''),
                    'bucket_name': os.getenv('VITALGRAPH_STORAGE_BUCKET', 'vitalgraph-files'),
                    'region': os.getenv('VITALGRAPH_STORAGE_REGION', 'us-east-1'),
                    'use_ssl': os.getenv('VITALGRAPH_STORAGE_USE_SSL', 'true').lower() == 'true'
                }
            },
            'app': {
                'log_level': os.getenv('VITALGRAPH_LOG_LEVEL', 'INFO')
            }
        }
    
    # Keep all existing getter methods unchanged:
    # - get_database_config()
    # - get_fuseki_config()
    # - get_fuseki_postgresql_config()
    # - get_auth_config()
    # - get_app_config()
    # - get_backend_config()
    # - get_table_prefix()
    # - get_root_credentials()
    # - get_database_url() (update to use env vars directly)
    # - validate_config()
```

**Usage** (same as before):
```python
from vitalgraph.config.config_loader import get_config

# Load configuration (no path needed)
config = get_config()

# Access values (same interface)
db_config = config.get_database_config()
fuseki_config = config.get_fuseki_config()
db_url = config.get_database_url()
```

## Implementation Plan

### Phase 1: Update Existing Configuration Module

**File**: `vitalgraph/config/config_loader.py`

**Changes Required**:
1. **Remove YAML loading**: Delete `load_config()` method and YAML parsing code
2. **Add `_load_from_env()` method**: Build config dict from environment variables
3. **Update `__init__()`**: Remove `config_path` parameter, call `_load_from_env()`
4. **Update `get_config()`**: Remove `config_path` parameter
5. **Update `reload_config()`**: Remove `config_path` parameter
6. **Update `get_database_url()`**: Already has env var overrides, keep as-is
7. **Keep all getter methods**: No changes to interface

**Key Implementation Details**:
- All configuration sections built from `VITALGRAPH_*` environment variables
- Sensible defaults for all values (localhost, standard ports, etc.)
- Type conversion for integers and booleans
- Same dictionary structure as before for backward compatibility
- All existing getter methods work unchanged

**Optional AWS Secrets Integration** (can be added later if needed):
```python
import boto3
import json
from functools import lru_cache

@lru_cache(maxsize=1)
def load_aws_secrets(secret_name: str, region: str = "us-east-1") -> dict:
    """Load secrets from AWS Secrets Manager (cached)"""
    client = boto3.client('secretsmanager', region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])

def inject_secrets_into_env(environment: str = 'prod'):
    """Optionally inject AWS secrets into environment variables before loading config"""
    secret_name = f"vitalgraph/{environment}/credentials"
    try:
        secrets = load_aws_secrets(secret_name)
        # Map secrets to environment variables
        os.environ.setdefault('VITALGRAPH_DB_USERNAME', secrets['database']['username'])
        os.environ.setdefault('VITALGRAPH_DB_PASSWORD', secrets['database']['password'])
        os.environ.setdefault('VITALGRAPH_FUSEKI_USERNAME', secrets['fuseki']['username'])
        os.environ.setdefault('VITALGRAPH_FUSEKI_PASSWORD', secrets['fuseki']['password'])
        # ... etc
    except Exception as e:
        # Secrets not available (local dev), continue with env vars
        logger.warning(f"Could not load AWS secrets: {e}")
        pass
```

### Phase 2: GitHub Actions Workflow

**File**: `.github/workflows/deploy-ecs.yml`

**Steps**:
1. **Build**: Build Docker image with ECS config file using build arg
2. **Push**: Push to ECR
3. **Configure AWS Credentials**: Use OIDC or IAM user
4. **Fetch Secrets**: Get secret ARN for environment
5. **Update Task Definition**: Inject environment variables and secret references
6. **Deploy**: Update ECS service

**Example Workflow**:
```yaml
name: Deploy to ECS

on:
  push:
    branches: [main, staging, develop]

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: vitalgraph
  ECS_CLUSTER: vitalgraph-cluster
  
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      
      - name: Login to ECR
        uses: aws-actions/amazon-ecr-login@v1
      
      - name: Determine Environment
        id: env
        run: |
          if [[ "${{ github.ref }}" == "refs/heads/main" ]]; then
            echo "environment=prod" >> $GITHUB_OUTPUT
            echo "config_env=ecs" >> $GITHUB_OUTPUT
          elif [[ "${{ github.ref }}" == "refs/heads/staging" ]]; then
            echo "environment=staging" >> $GITHUB_OUTPUT
            echo "config_env=ecs" >> $GITHUB_OUTPUT
          else
            echo "environment=dev" >> $GITHUB_OUTPUT
            echo "config_env=ecs" >> $GITHUB_OUTPUT
          fi
      
      - name: Build and Push
        env:
          IMAGE_TAG: ${{ github.sha }}
        run: |
          # Build Docker image (no config file needed)
          docker build \
            -t $ECR_REPOSITORY:$IMAGE_TAG \
            -t $ECR_REPOSITORY:latest \
            .
          
          # Push both tags
          docker push $ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REPOSITORY:latest
      
      - name: Render Task Definition
        id: render-task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: .aws/task-definition-${{ steps.env.outputs.environment }}.json
          container-name: vitalgraph
          image: ${{ env.ECR_REPOSITORY }}:${{ github.sha }}
          environment-variables: |
            VITALGRAPH_DATABASE_HOST=${{ secrets.DATABASE_HOST }}
            VITALGRAPH_DATABASE_PORT=5432
            VITALGRAPH_DATABASE_NAME=vitalgraph_${{ steps.env.outputs.environment }}
            FUSEKI_URL=${{ secrets.FUSEKI_URL }}
            VITALGRAPH_FILE_STORAGE_BACKEND=s3
            VITALGRAPH_S3_BUCKET_NAME=vitalgraph-files-${{ steps.env.outputs.environment }}
            VITALGRAPH_LOG_LEVEL=INFO
            APP_MODE=production
            PORT=8001
            HOST=0.0.0.0
            KEYCLOAK_URL=${{ secrets.KEYCLOAK_URL }}
            KEYCLOAK_REALM=${{ secrets.KEYCLOAK_REALM }}
            WEAVIATE_REST_URL=${{ secrets.WEAVIATE_REST_URL }}
            WEAVIATE_HTTP_HOST=${{ secrets.WEAVIATE_HTTP_HOST }}
            WEAVIATE_GRPC_HOST=${{ secrets.WEAVIATE_GRPC_HOST }}
            WEAVIATE_GRPC_PORT=50051
      
      - name: Deploy to ECS
        uses: aws-actions/amazon-ecs-deploy-task-definition@v1
        with:
          task-definition: ${{ steps.render-task-def.outputs.task-definition }}
          service: vitalgraph-service-${{ steps.env.outputs.environment }}
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
```

**Key Updates**:
- ✅ No build args needed (no config files)
- ✅ Determines environment from branch (main=prod, staging=staging, develop=dev)
- ✅ Supports multiple task definitions per environment
- ✅ All configuration via environment variables in task definition
- ✅ Waits for service stability after deployment

### Phase 3: ECS Task Definition

**File**: `.aws/task-definition.json`

**Key Sections**:
```json
{
  "family": "vitalgraph",
  "containerDefinitions": [
    {
      "name": "vitalgraph",
      "image": "ECR_IMAGE_URI",
      "environment": [
        {"name": "VITALGRAPH_BACKEND_TYPE", "value": "fuseki_postgresql"},
        {"name": "VITALGRAPH_DB_HOST", "value": "RDS_ENDPOINT"},
        {"name": "VITALGRAPH_DB_PORT", "value": "5432"},
        {"name": "VITALGRAPH_DB_NAME", "value": "vitalgraph_prod"},
        {"name": "VITALGRAPH_DB_POOL_SIZE", "value": "10"},
        {"name": "VITALGRAPH_DB_MAX_OVERFLOW", "value": "20"},
        {"name": "VITALGRAPH_FUSEKI_URL", "value": "http://fuseki:3030"},
        {"name": "VITALGRAPH_FUSEKI_DATASET", "value": "vitalgraph"},
        {"name": "VITALGRAPH_STORAGE_BACKEND", "value": "s3"},
        {"name": "VITALGRAPH_STORAGE_BUCKET", "value": "vitalgraph-files-prod"},
        {"name": "VITALGRAPH_STORAGE_REGION", "value": "us-east-1"},
        {"name": "VITALGRAPH_STORAGE_USE_SSL", "value": "true"},
        {"name": "VITALGRAPH_TABLE_PREFIX", "value": "vitalgraph_"},
        {"name": "VITALGRAPH_LOG_LEVEL", "value": "INFO"},
        {"name": "APP_MODE", "value": "production"},
        {"name": "PORT", "value": "8001"},
        {"name": "HOST", "value": "0.0.0.0"},
        {"name": "KEYCLOAK_URL", "value": "https://keycloak.example.com"},
        {"name": "KEYCLOAK_REALM", "value": "vitalgraph"},
        {"name": "WEAVIATE_REST_URL", "value": "https://weaviate.example.com/v1"},
        {"name": "WEAVIATE_HTTP_HOST", "value": "weaviate.example.com"},
        {"name": "WEAVIATE_GRPC_HOST", "value": "grpc.weaviate.example.com"},
        {"name": "WEAVIATE_GRPC_PORT", "value": "50051"}
      ],
      "secrets": [
        {
          "name": "VITALGRAPH_DB_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:database.username::"
        },
        {
          "name": "VITALGRAPH_DB_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:database.password::"
        },
        {
          "name": "VITALGRAPH_FUSEKI_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:fuseki.username::"
        },
        {
          "name": "VITALGRAPH_FUSEKI_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:fuseki.password::"
        },
        {
          "name": "VITALGRAPH_AUTH_ROOT_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:auth.root_username::"
        },
        {
          "name": "VITALGRAPH_AUTH_ROOT_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:auth.root_password::"
        },
        {
          "name": "JWT_SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:auth.jwt_secret_key::"
        },
        {
          "name": "VITALGRAPH_STORAGE_ACCESS_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:s3.access_key_id::"
        },
        {
          "name": "VITALGRAPH_STORAGE_SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:s3.secret_access_key::"
        },
        {
          "name": "OPENAI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:openai.api_key::"
        },
        {
          "name": "KEYCLOAK_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:keycloak.username::"
        },
        {
          "name": "KEYCLOAK_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:keycloak.password::"
        },
        {
          "name": "KEYCLOAK_CLIENT_ID",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:keycloak.client_id::"
        },
        {
          "name": "WEAVIATE_CLIENT_ID",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:weaviate.client_id::"
        },
        {
          "name": "WEAVIATE_CLIENT_SECRET",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:weaviate.client_secret::"
        },
        {
          "name": "WEAVIATE_USERNAME",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:weaviate.username::"
        },
        {
          "name": "WEAVIATE_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:vitalgraph/prod/credentials:weaviate.password::"
        }
      ]
    }
  ]
}
```

### Phase 4: Dockerfile Updates

**File**: `Dockerfile`

**Current Implementation**:
The Dockerfile currently copies a YAML config file at build time. This will be removed.

**Required Changes for Environment-Variable-Only Approach**:
1. **Remove config file copying** - no YAML files needed
2. **Remove build arg** - no environment selection needed
3. **Configuration via environment variables only** - set at runtime
4. **Maintain existing entrypoint** - uses `vitalgraphdb_cmd`

**Updated Dockerfile** (simplified):
```dockerfile
# Use Python 3.12 slim image for production
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODE=production \
    PORT=8001 \
    HOST=0.0.0.0

# Install system dependencies including Node.js 20
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    libodbccr2 \
    libodbc2 \
    libpq-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY pyproject.toml .
COPY README.md .
COPY LICENSE .
COPY MANIFEST.in .

# Install Python dependencies with server extras
RUN pip install --no-cache-dir -e ".[server]"

# Copy the application code
COPY vitalgraph/ ./vitalgraph/

# Copy frontend source files
COPY frontend/ ./frontend/

# Build frontend (this will copy built files to vitalgraph/api/frontend/)
RUN cd frontend && npm install --production=false && npm run build && npm cache clean --force

COPY vitalhome/ ./vitalhome/

# Set up VitalSigns configuration
ENV VITAL_HOME=/app/vitalhome

# Expose the default port (actual port is configurable via PORT environment variable at runtime)
EXPOSE 8001

# Configuration loaded from environment variables at runtime
# No config files needed in Docker image

# Use the vitalgraphdb script as entrypoint
CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
```

**Key Points**:
- ✅ Removed config file copying (no YAML files needed)
- ✅ Removed build args (no environment selection at build time)
- ✅ Frontend build included in image
- ✅ VitalSigns configuration properly set
- ✅ Single Docker image works for all environments
- ✅ Configuration entirely via environment variables at runtime
- ✅ Existing `VitalGraphConfig` class interface unchanged

### Phase 5: Application Code Updates

**Files to Modify**:
1. `vitalgraph/config/config_loader.py` - Update to load from env vars only
2. Update any code that calls `get_config(config_path)` to call `get_config()` (no path)
3. Remove YAML config files from Docker image (update Dockerfile)
4. Update `.env.example` with all required `VITALGRAPH_*` variables

**Pattern** (same as before, no code changes needed):
```python
from vitalgraph.config.config_loader import get_config

# Load configuration (no path parameter)
config = get_config()
config.validate_config()

# Access configuration (same interface)
db_config = config.get_database_config()
db_host = db_config['host']
db_password = db_config['password']

fuseki_config = config.get_fuseki_config()
fuseki_url = fuseki_config['server_url']

# Or use helper methods
db_url = config.get_database_url()
username, password = config.get_root_credentials()
```

**Code Search Required**:
Find all instances of:
- `get_config(config_path)` → change to `get_config()`
- `VitalGraphConfig(config_path)` → change to `VitalGraphConfig()`
- `reload_config(config_path)` → change to `reload_config()`

## AWS Secrets Manager Setup

### Create Secrets for Each Environment

**Development**:
```bash
aws secretsmanager create-secret \
  --name vitalgraph/dev/credentials \
  --description "VitalGraph development credentials" \
  --secret-string file://secrets-dev.json \
  --region us-east-1
```

**Staging**:
```bash
aws secretsmanager create-secret \
  --name vitalgraph/staging/credentials \
  --description "VitalGraph staging credentials" \
  --secret-string file://secrets-staging.json \
  --region us-east-1
```

**Production**:
```bash
aws secretsmanager create-secret \
  --name vitalgraph/prod/credentials \
  --description "VitalGraph production credentials" \
  --secret-string file://secrets-prod.json \
  --region us-east-1
```

### IAM Policy for ECS Task Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:vitalgraph/*/credentials*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::vitalgraph-files-*",
        "arn:aws:s3:::vitalgraph-files-*/*"
      ]
    }
  ]
}
```

## Security Best Practices

### 1. Secret Rotation
- Enable automatic rotation for database passwords
- Implement rotation Lambda functions
- Update application to handle credential refresh

### 2. Least Privilege
- ECS task role only has access to specific secrets
- Use resource-based policies for S3 buckets
- Separate IAM roles for different environments

### 3. Audit Logging
- Enable CloudTrail for Secrets Manager access
- Monitor secret access patterns
- Alert on unusual access

### 4. Encryption
- Use AWS KMS for secret encryption
- Enable encryption at rest for RDS
- Use TLS for all network communication

### 5. Repository Security
- ✅ `.env` files already in `.gitignore` and never committed
- ✅ `.env.example` already exists for documentation
- Add config file variants to `.gitignore` if not already present:
  - `vitalgraphdb-config-local.yaml` (if contains local credentials)
  - `vitalgraphdb-config-dev.yaml` (if contains dev credentials)
- Use GitHub secrets for workflow variables
- Enable branch protection rules
- Implement secret rotation policies for production credentials

## Migration Steps

### Step 1: Update Configuration Module
1. Update `vitalgraph/config/config_loader.py`:
   - Remove YAML loading code (`load_config()` method)
   - Add `_load_from_env()` method to build config from environment variables
   - Update `__init__()` to not require `config_path` parameter
   - Update `get_config()` and `reload_config()` to not require path
   - Keep all existing getter methods unchanged
2. Write unit tests for environment variable loading
3. Test validation with missing required variables

### Step 2: Update Environment Variable Documentation
1. Update `.env.example` with complete list of all `VITALGRAPH_*` variables
2. Document default values for each variable
3. Mark which variables are required vs optional
4. Add comments explaining each variable's purpose
5. Keep existing YAML config files for backward compatibility (optional)
6. Add deprecation warnings if YAML configs are still used

### Step 3: Update Application Code
1. Search for all calls to `get_config(config_path)` and remove the path parameter
2. Search for all calls to `VitalGraphConfig(config_path)` and remove the path parameter
3. Search for all calls to `reload_config(config_path)` and remove the path parameter
4. Remove any code that determines config file paths (no longer needed)
5. Test locally with `.env` file
6. Verify all configuration access still works (same getter methods)

### Step 4: Setup AWS Infrastructure
1. Create Secrets Manager secrets for each environment
2. Create IAM roles and policies
3. Setup ECS task definitions
4. Configure RDS and Fuseki endpoints

### Step 5: Create GitHub Actions Workflow
1. Create `.github/workflows/deploy-ecs.yml`
2. Add GitHub secrets for AWS credentials
3. Test deployment to dev environment

### Step 6: Test and Validate
1. Deploy to dev environment
2. Validate all services are working
3. Test secret rotation
4. Deploy to staging and prod

## Testing Strategy

### Local Testing
```bash
# Test with .env file (already working)
python -m vitalgraph.cmd.vitalgraphdb_cmd

# Test with explicit env var overrides
export VITALGRAPH_DB_HOST=localhost
export VITALGRAPH_DB_PASSWORD=testpass
export VITALGRAPH_FUSEKI_URL=http://localhost:3030
python -m vitalgraph.cmd.vitalgraphdb_cmd

# Test with Docker Compose (uses .env file)
docker-compose up
```

### ECS Testing
```bash
# Test with environment variables matching ECS task definition
export VITALGRAPH_DB_HOST=rds-endpoint.amazonaws.com
export VITALGRAPH_DB_USERNAME=prod_user
export VITALGRAPH_DB_PASSWORD=prod_pass
export VITALGRAPH_FUSEKI_URL=http://fuseki:3030
export VITALGRAPH_STORAGE_BACKEND=s3
export VITALGRAPH_STORAGE_BUCKET=vitalgraph-files-prod
python -m vitalgraph.cmd.vitalgraphdb_cmd
```

### Integration Testing
1. Deploy to dev environment
2. Run smoke tests against deployed service
3. Validate database connectivity
4. Validate Fuseki connectivity
5. Validate S3 file operations
6. Validate authentication

## Rollback Plan

### If Deployment Fails
1. Revert ECS service to previous task definition
2. Check CloudWatch logs for errors
3. Validate secrets are accessible
4. Verify environment variables are correct

### If Config Loading Fails
1. Add fallback to direct YAML loading
2. Log detailed error messages
3. Implement graceful degradation

## Monitoring and Alerting

### CloudWatch Metrics
- Config loading success/failure rate
- Secret access latency
- Application startup time
- Database connection errors

### CloudWatch Alarms
- Alert on config loading failures
- Alert on secret access denied errors
- Alert on application startup failures

### Logging
- Log config loading process (without sensitive values)
- Log secret fetch attempts
- Log environment variable usage

## Documentation Updates

### Files to Update
1. `README.md` - Add deployment section
2. `docs/DEPLOYMENT.md` - Create deployment guide
3. `docs/CONFIGURATION.md` - Document config system
4. `docs/AWS_SETUP.md` - Document AWS infrastructure setup

### Developer Guide
- How to run locally with different configs
- How to test with AWS secrets locally
- How to add new configuration parameters
- How to rotate secrets

## Conclusion

This plan provides a comprehensive approach to refactoring the VitalGraph configuration system for secure ECS deployment. Key benefits:

1. **Security**: Sensitive credentials never in repository
2. **Flexibility**: Easy to override values per environment
3. **Maintainability**: Clear separation of concerns
4. **Scalability**: Easy to add new environments
5. **Auditability**: All secret access is logged
6. **Automation**: Full CI/CD pipeline via GitHub Actions

The implementation follows AWS best practices and provides a solid foundation for production deployments.
