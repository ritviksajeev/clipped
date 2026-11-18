# clipped in Docker: dashboard on http://localhost:8000, data in the /data volume.
#   docker compose up -d
ARG NODE_IMAGE=node:20-alpine
ARG PYTHON_IMAGE=python:3.11-slim

FROM ${NODE_IMAGE} AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build --outDir /web --emptyOutDir

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CLIPPED_HOME=/data \
    CLIPPED_SECRETS_FILE=/data/secrets.json \
    CLIPPED_HOST=0.0.0.0 \
    CLIPPED_PORT=8000
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 clipped \
 && mkdir -p /data && chown clipped /data
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY clipped/ ./clipped/
COPY --from=web /web ./clipped/web
RUN pip install .
USER clipped
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/status', headers={'Host': 'localhost'}), timeout=4)" || exit 1
CMD ["clipped", "serve", "--no-browser"]
