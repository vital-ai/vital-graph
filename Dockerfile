# Use Python 3.11 slim image for production
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODE=production \
    PORT=8001 \
    HOST=0.0.0.0

# Install system dependencies including Node.js
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY setup.py .
COPY README.md .
COPY LICENSE .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy the application code
COPY vitalgraph/ ./vitalgraph/

# Copy database configuration files
COPY vitalgraphdb_config/ ./vitalgraphdb_config/

# Copy frontend source files
COPY frontend/ ./frontend/

# Build frontend (this will copy built files to vitalgraph/api/frontend/)
RUN cd frontend && npm install && npm run build

# Expose the default port (actual port is configurable via PORT environment variable at runtime)
EXPOSE 8001

# Use the vitalgraphdb script as entrypoint
CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
