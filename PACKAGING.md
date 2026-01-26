# VitalGraph Packaging and Distribution Guide

This document explains the new packaging setup for VitalGraph with optional dependencies and pip distribution.

## Overview

VitalGraph now uses a modern `pyproject.toml`-based packaging system with optional dependency groups, eliminating the redundant `setup.py` file.

## Installation Options

### 1. Base Installation (Minimal)
```bash
pip install vital-graph
```
**Dependencies**: Core RDF functionality with AI and advanced graph processing
- **Core**: vital-ai-vitalsigns, vital-ai-haley-kg, rdflib, PyLD, six, python-dotenv
- **AI**: openai
- **Graph**: pyoxigraph

**Use Case**: Minimal installation for basic RDF processing

### 2. Client Installation
```bash
pip install vital-graph[client]
```
**Additional Dependencies**: Client functionality
- requests, pydantic, PyYAML, tabulate, click-repl

**Use Case**: Applications that connect to existing VitalGraph servers

### 3. Server Installation
```bash
pip install vital-graph[server]
```
**Additional Dependencies**: Full server capabilities
- FastAPI, uvicorn, starlette, SQLAlchemy, psycopg, asyncpg, alembic
- pgvector, aiofiles, Jinja2, PyJWT, email-validator, click-repl, tabulate
- pytidb[models], pytidb

**Use Case**: Running a complete VitalGraph server with database

### 4. Development Tools
```bash
pip install vital-graph[dev]
```
**Additional Dependencies**: Development and code quality tools
- pytest, pytest-asyncio, black, flake8, mypy, pre-commit

**Use Case**: Development, code formatting, type checking

### 5. Testing Utilities
```bash
pip install vital-graph[test]
```
**Additional Dependencies**: Testing tools
- pytest, pytest-asyncio, pytest-cov

**Use Case**: Running test suites with coverage

### 6. Documentation Tools
```bash
pip install vital-graph[docs]
```
**Additional Dependencies**: Documentation building
- sphinx, sphinx-rtd-theme, myst-parser

**Use Case**: Building documentation

### 7. Full Installation
```bash
pip install vital-graph[all]
```
**Includes**: All optional dependencies (client, server, dev, test, docs)

### 8. Custom Combinations
```bash
pip install vital-graph[client,dev]
pip install vital-graph[server,test,docs]
```

## Console Scripts

Console scripts are available based on installation:

- **vitalgraphdb**: Server command (requires `[server]` extras)
- **vitalgraphadmin**: Admin command (requires `[server]` extras)  
- **vitalgraph**: Client REPL command (requires `[client]` extras)

## Docker Build

The Docker build process has been updated to use the new packaging:

```dockerfile
# Copy requirements files
COPY pyproject.toml .
COPY README.md .
COPY LICENSE .
COPY MANIFEST.in .

# Install Python dependencies with server extras
RUN pip install --no-cache-dir -e ".[server]"
```

## Development Workflow

### Local Development
```bash
# Clone repository
git clone https://github.com/vital-ai/vital-graph.git
cd vital-graph

# Install in development mode with all features
pip install -e ".[all]"

# Or specific combinations
pip install -e ".[server,dev]"
```

### Building for Distribution
```bash
# Install build tools
pip install build twine

# Build distribution packages
python -m build

# Upload to PyPI (maintainers only)
twine upload dist/*
```

### Testing Installation Scenarios

Use the provided test script to verify installations:

```bash
python test_pip_install.py
```

This script tests:
- Core client dependencies
- Server dependencies (if installed)
- Console script availability
- Module import capabilities

## Package Structure

```
vital-graph/
├── vitalgraph/                 # Main package
│   ├── client/                # Client library (always included)
│   ├── server/                # Server components (server extras)
│   ├── db/                    # Database layer (server extras)
│   ├── api/                   # REST API (server extras)
│   └── ...
├── pyproject.toml             # Modern packaging configuration
├── MANIFEST.in                # Package data inclusion rules
├── README.md                  # Package documentation
└── test_pip_install.py        # Installation test script
```

## Migration from setup.py

The old `setup.py` file has been removed. All configuration is now in `pyproject.toml`:

### Key Changes:
1. **Dependency Management**: Core dependencies minimal, optional extras for specific use cases
2. **Console Scripts**: Properly configured in `[project.scripts]` section
3. **Package Data**: Managed through `[tool.setuptools.package-data]` and `MANIFEST.in`
4. **Tool Configuration**: Black, mypy, pytest configuration included
5. **Metadata**: Enhanced with keywords, URLs, and detailed classifiers

### Benefits:
- **Smaller Default Installation**: Client-only installs are lightweight
- **Flexible Deployment**: Choose only needed dependencies
- **Better Separation**: Clear distinction between client and server components
- **Modern Standards**: Follows PEP 621 and current Python packaging best practices
- **Docker Optimization**: Server containers only install server dependencies

## Publishing Checklist

Before publishing a new version:

1. ✅ Update version in `pyproject.toml`
2. ✅ Test all installation scenarios
3. ✅ Verify console scripts work
4. ✅ Build and test Docker image
5. ✅ Run full test suite
6. ✅ Update CHANGELOG.md
7. ✅ Create git tag
8. ✅ Build distribution: `python -m build`
9. ✅ Upload to PyPI: `twine upload dist/*`

## Troubleshooting

### Common Issues:

**Import Error for Server Components**:
```bash
# Solution: Install server extras
pip install vital-graph[server]
```

**Console Script Not Found**:
```bash
# Solution: Reinstall with appropriate extras
pip install --force-reinstall vital-graph[server]
```

**Docker Build Fails**:
- Ensure `pyproject.toml` is copied before pip install
- Verify server extras are specified: `pip install -e ".[server]"`

### Verification Commands:

```bash
# Check installed packages
pip list | grep vital

# Test imports
python -c "import vitalgraph.client; print('Client OK')"
python -c "import vitalgraph.main; print('Server OK')"

# Test console scripts
vitalgraph --help
vitalgraphdb --help
vitalgraphadmin --help
```
