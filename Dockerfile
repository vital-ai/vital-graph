# ---- Stage 1: Build frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY vitalgraph-client-ts/ /vitalgraph-client-ts/
RUN cd /vitalgraph-client-ts && npm ci && npm run build
COPY frontend/package*.json ./
RUN npm ci && npm install --no-save /vitalgraph-client-ts
COPY frontend/ ./
RUN npm run build:only

# ---- Stage 2a: Install slow-building dependencies (cached long-term) ----
FROM python:3.12-slim AS python-heavy
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
# Install slow-building deps first (native compilation + large downloads).
# This layer only rebuilds when the [heavy] group in pyproject.toml changes.
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN mkdir -p vitalgraph && touch vitalgraph/__init__.py \
    && pip install --no-cache-dir ".[heavy]" \
    && rm -rf vitalgraph

# ---- Stage 2b: Install remaining Python dependencies ----
FROM python-heavy AS python-deps
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
RUN python -c "from vital_ai_vitalsigns.vitalsigns import VitalSigns; VitalSigns()" \
    && chmod -R a+rX /usr/local/lib/python3.12/site-packages/vital_ai_vitalsigns/_vitalsigns_cache

# ---- Bake the paraphrase-multilingual-MiniLM-L12-v2 weights into the image ----
#
# The `paraphrase_multilingual_minilm_l12_v2` vectorization provider loads this
# model via transformers AutoModel/AutoTokenizer.  Without it baked in, the
# first vectorization in a fresh container reaches out to huggingface.co —
# unacceptable in a locked-down VPC/Fargate task, and a slow, failure-prone
# cold start everywhere else.
#
# The other local provider (`vitalsigns_onnx`) needs nothing here: its ONNX
# weights ship inside the vital-model-paraphrase-MiniLM-onnx wheel.
# The weights are written with save_pretrained() to a plain DIRECTORY, not left
# in the HF cache.  Warming the cache is NOT enough: AutoTokenizer still issues
# a model-info API call to huggingface.co that fails under HF_HUB_OFFLINE=1
# (AutoModel alone would have been fine).  Loading from a directory path skips
# hub resolution entirely.  Verified byte-identical to a hub load.
#
# The download cache is deleted afterwards: the exported directory is the
# artifact, and keeping both would double the model's ~460MB in the layer.
ARG PARAPHRASE_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENV PARAPHRASE_MODEL_DIR=/app/models/paraphrase-multilingual-MiniLM-L12-v2 \
    HF_HOME=/app/models/hf \
    NLTK_DATA=/app/models/nltk

RUN mkdir -p "$HF_HOME" "$NLTK_DATA" "$PARAPHRASE_MODEL_DIR" \
    && python -c "\
from transformers import AutoModel, AutoTokenizer; \
m='${PARAPHRASE_MODEL}'; d='${PARAPHRASE_MODEL_DIR}'; \
AutoTokenizer.from_pretrained(m).save_pretrained(d); \
AutoModel.from_pretrained(m).save_pretrained(d); \
print('baked', m, '->', d)" \
    && rm -rf "$HF_HOME"/hub "$HF_HOME"/xet \
    && chmod -R a+rX "$PARAPHRASE_MODEL_DIR"

# WeaviateLocalVectorizer._sent_tokenize() calls nltk.sent_tokenize, which loads
# the punkt tables at runtime.  NLTK >= 3.8.2 uses punkt_tab; older releases use
# punkt.  Fetch both so the image works across the range pyproject allows
# (nltk>=3.8.0).
RUN python -c "\
import nltk; \
[nltk.download(p, download_dir='${NLTK_DATA}') for p in ('punkt', 'punkt_tab')]" \
    && chmod -R a+rX "$NLTK_DATA"

# Everything the runtime needs is now on disk — forbid network fetches so a
# missing artifact fails loudly at startup instead of silently egressing.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Copy application source and install (no-deps, packages already present)
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY vitalgraph/ ./vitalgraph/
RUN pip install --no-cache-dir --no-deps "."

# Fail the build if the baked model + punkt tables cannot satisfy an OFFLINE
# load — far better here than as a cold-start failure inside a locked-down VPC.
# Runs after the app install because it exercises the real provider registry.
RUN python -c "\
from vitalgraph.vectorization.registry import get_provider; \
p = get_provider('paraphrase_multilingual_minilm_l12_v2'); \
assert p.dimensions == 384, p.dimensions; \
import asyncio; v = asyncio.run(p.vectorize_text('Offline smoke test. Two sentences.')); \
assert len(v) == 384 and any(abs(x) > 1e-9 for x in v); \
print('offline vectorization OK:', p.model_name)"

# Copy frontend build output from Stage 1
COPY --from=frontend-build /frontend/dist ./vitalgraph/api/frontend/dist/

# Build provenance. A deployed container has no .git directory, so the commit is
# only knowable at build time — the deploying pipeline must pass these through:
#
#   docker build \
#     --build-arg GIT_COMMIT=${{ github.sha }} \
#     --build-arg VITALGRAPH_VERSION=$(...) \
#     --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
#
# Left empty they are simply absent — never wrong, which matters because a stale
# version reads as authoritative. See
# planning/planning_performance/prod_db_saturation_plan.md
ARG GIT_COMMIT=""
ARG VITALGRAPH_VERSION=""
ARG BUILD_TIME=""

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODE=production \
    PORT=8001 \
    HOST=0.0.0.0 \
    VITALGRAPH_GIT_COMMIT=${GIT_COMMIT} \
    VITALGRAPH_BUILD_VERSION=${VITALGRAPH_VERSION} \
    VITALGRAPH_BUILD_TIME=${BUILD_TIME}

# Also expose as OCI image labels so `docker inspect` / registry tooling can read
# provenance without starting the container.
LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      org.opencontainers.image.version=${VITALGRAPH_VERSION} \
      org.opencontainers.image.created=${BUILD_TIME}

EXPOSE 8001

# Run as an unprivileged user with no write access to the application. The only
# runtime writes are to $HOME (ONNX Runtime's cache) and /tmp (import and export
# staging). The numeric id lets an orchestrator verify the user is not root
# without reading /etc/passwd.
#
# Model downloads and the VitalSigns cache are written owner-only by their
# libraries, and every earlier RUN is root, so the offline smoke test above
# cannot see a file this user can't read. Fix permissions in the RUN that
# creates a file (a chmod here would copy the 470 MB model into a new layer).
RUN ! find /app /usr/local/lib/python3.12/site-packages \
        \( -type f ! -perm -o=r \) -o \( -type d ! -perm -o=rx \) | grep . \
    && groupadd --system --gid 10001 vitalgraph \
    && useradd --system --uid 10001 --gid 10001 --create-home \
        --home-dir /home/vitalgraph --shell /usr/sbin/nologin vitalgraph \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data
ENV HOME=/home/vitalgraph
USER 10001:10001

CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
