# Job-protocol runner image (ruling D1): the Python SDK + the shipped
# connectors, driven by `connectors.sdk.service`. Build context is the
# repo root:
#
#   docker build -f deploy/runner.Dockerfile .
#
# The runner speaks outbound HTTP to the core only (J-2) and resolves
# credential references from its own environment (env-file "vault" for
# local dev, J-4). Note: the postgres connector's ddl-file mode spins
# Docker containers and is not available inside this image — use live
# mode (the compose demo does) or the local CLI harness for DDL runs.

FROM python:3.12-slim
WORKDIR /opt/contextlayer
COPY pyproject.toml constraints.txt ./
COPY snapshot ./snapshot
COPY connectors ./connectors
COPY generator ./generator
COPY lineage ./lineage
COPY benchmark ./benchmark
RUN pip install --no-cache-dir . -c constraints.txt

CMD ["python", "-m", "connectors.sdk.service", "--config", "/etc/contextlayer/runner.yaml", "-v"]
