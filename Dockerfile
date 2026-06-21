# ---- Stage 1: Build frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY vitalgraph-client-ts/ /vitalgraph-client-ts/
RUN cd /vitalgraph-client-ts && npm ci && npm run build
COPY frontend/package*.json ./
RUN npm ci && npm install --no-save /vitalgraph-client-ts
COPY frontend/ ./
RUN npm run build:only

# ---- Stage 2: Install Python dependencies ----
FROM python:3.12-slim AS python-deps
WORKDIR /app
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    libodbccr2 \
    libodbc2 \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN mkdir -p vitalgraph && touch vitalgraph/__init__.py \
    && pip install --no-cache-dir ".[server]" \
    && rm -rf vitalgraph

# ---- Stage 3: Final production image ----
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq5 \
    libodbc2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from deps stage
COPY --from=python-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-deps /usr/local/bin /usr/local/bin

# Copy VitalSigns config and pre-warm registry cache
COPY vitalhome/ ./vitalhome/
ENV VITAL_HOME=/app/vitalhome
RUN python -c "from vital_ai_vitalsigns.vitalsigns import VitalSigns; VitalSigns()"

# Copy application source and install (no-deps, packages already present)
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY vitalgraph/ ./vitalgraph/
RUN pip install --no-cache-dir --no-deps "."

# Copy frontend build output from Stage 1
COPY --from=frontend-build /frontend/dist ./vitalgraph/api/frontend/dist/

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODE=production \
    PORT=8001 \
    HOST=0.0.0.0

EXPOSE 8001

CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
