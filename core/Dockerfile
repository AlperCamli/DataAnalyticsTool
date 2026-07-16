# Core service image. Build context is the REPO ROOT (the runtime stage
# carries the Python snapshot library for the J-6 delivery gate — CP-3a
# ruling C1: validation/canonicalization stay Python, invoked as a CLI).
#
#   docker build -f core/Dockerfile .

FROM node:22-slim AS build
WORKDIR /app
COPY core/package.json core/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY core/tsconfig.json ./
COPY core/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*
# The delivery gate needs only the snapshot package + jsonschema (the
# same floor as pyproject.toml, format-nongpl so date-time asserts).
RUN python3 -m venv /opt/validator \
 && /opt/validator/bin/pip install --no-cache-dir 'jsonschema[format-nongpl]>=4.21'
COPY snapshot /opt/contextlayer/snapshot

WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY core/migrations ./migrations
COPY deploy/jobs ./jobs

ENV CORE_VALIDATOR_CMD="/opt/validator/bin/python -m snapshot.accept" \
    PYTHONPATH=/opt/contextlayer \
    CORE_PORT=8100
EXPOSE 8100
CMD ["node", "dist/index.js"]
