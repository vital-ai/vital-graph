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

# ---------- Stage 1: install dependencies only (cached until pyproject.toml changes) ----------
COPY pyproject.toml .
COPY README.md .
COPY LICENSE .
COPY MANIFEST.in .

# Copy frontend source files
COPY frontend/ ./frontend/

# Build frontend (this will copy built files to vitalgraph/api/frontend/)
RUN cd frontend && npm install --production=false && npm run build && npm cache clean --force

# Create a minimal package stub so pip can resolve deps without the real source
RUN mkdir -p vitalgraph && touch vitalgraph/__init__.py \
    && pip install --no-cache-dir ".[server]" \
    && rm -rf vitalgraph

# Copy VitalSigns config and pre-warm registry cache (before code layers for caching)
COPY vitalhome/ ./vitalhome/
ENV VITAL_HOME=/app/vitalhome
RUN python -c "from vital_ai_vitalsigns.vitalsigns import VitalSigns; VitalSigns()"

# ---------- Stage 2: install package with real source ----------
COPY vitalgraph/ ./vitalgraph/
RUN pip install --no-cache-dir --no-deps "."


# Expose the default port (actual port is configurable via PORT environment variable at runtime)
EXPOSE 8001


# Use the vitalgraphdb script as entrypoint
CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
