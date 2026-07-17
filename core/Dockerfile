# Core service image. Build context is the REPO ROOT: the runtime stage
# carries the Python package (snapshot + generator + lineage) for the
# J-6 delivery gate and the CP-3b sync-stage CLIs (rulings C1/C2 —
# deterministic artifact work stays Python, invoked as CLIs), plus git
# for the orchestrator's KB mechanics (D2) and the built wheel for the
# §10 vendored-wheel carry.
#
#   docker build -f core/Dockerfile .

FROM node:22-slim AS build
WORKDIR /app
COPY core/package.json core/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY core/tsconfig.json ./
COPY core/src ./src
RUN npm run build && npm prune --omit=dev

# The platform wheel (§10): built from source so the image's carry
# artifact always matches the code it ships.
FROM python:3.12-slim AS wheelbuild
WORKDIR /src
COPY pyproject.toml constraints.txt ./
COPY snapshot ./snapshot
COPY connectors ./connectors
COPY generator ./generator
COPY lineage ./lineage
RUN pip wheel --no-deps --no-cache-dir -w /wheels .

FROM node:22-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git \
 && rm -rf /var/lib/apt/lists/*
# One venv serves both the delivery gate (jsonschema) and the sync-stage
# CLIs (PyYAML for front-matter, jinja2 for renders, sqlglot for lineage
# re-derivation) — pinned exactly as CI pins them.
COPY constraints.txt /opt/contextlayer/constraints.txt
RUN python3 -m venv /opt/validator \
 && /opt/validator/bin/pip install --no-cache-dir -c /opt/contextlayer/constraints.txt \
      'jsonschema[format-nongpl]>=4.21' 'PyYAML>=6.0' 'jinja2>=3.1' 'sqlglot>=25'
COPY snapshot /opt/contextlayer/snapshot
COPY generator /opt/contextlayer/generator
COPY lineage /opt/contextlayer/lineage
COPY --from=wheelbuild /wheels /opt/contextlayer/wheels

WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY core/migrations ./migrations
COPY deploy/jobs ./jobs
COPY fixtures/drill /opt/contextlayer/fixtures/drill

ENV CORE_VALIDATOR_CMD="/opt/validator/bin/python -m snapshot.accept" \
    SYNC_PYTHON="/opt/validator/bin/python" \
    SYNC_WHEEL_PATH="/opt/contextlayer/wheels" \
    PYTHONPATH=/opt/contextlayer \
    CORE_PORT=8100
EXPOSE 8100
CMD ["node", "dist/index.js"]
