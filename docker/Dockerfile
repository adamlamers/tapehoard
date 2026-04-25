# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend & Runtime
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime
WORKDIR /app/backend

# Install system dependencies and build stenc from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    mt-st \
    tar \
    sqlite3 \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    pandoc \
    git \
    liblzo2-dev \
    zlib1g-dev \
    && git clone https://github.com/scsitape/stenc.git /tmp/stenc \
    && cd /tmp/stenc \
    && ./autogen.sh \
    && ./configure \
    && make && make install \
    && apt-get purge -y build-essential autoconf automake libtool pkg-config pandoc git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/stenc

# Copy backend files
COPY README.md /app/
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./

# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/build /app/backend/static

# Setup volumes and permissions
RUN mkdir -p /app/data /staging /source_data /restores
ENV DATABASE_URL=sqlite:////app/data/tapehoard.db

# Entrypoint
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
