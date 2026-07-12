"""Ephemeral Postgres container lifecycle for ddl-file mode (plan §3.1).

The customer's DDL is *executed* by real Postgres — streamed into `psql
-v ON_ERROR_STOP=1` inside the container — never parsed or interpreted
on this side. Container management is plain `docker` subprocess calls:
ddl-file mode needs it at runtime, so this is connector code, not test
scaffolding (DECISIONS.md D-21).

Failure taxonomy: environment problems (no docker, daemon down, image
won't start) are `SourceUnavailable` (retryable, MP-1/CC-2 — never a
fallback snapshot); DDL that real Postgres rejects is `ConfigError`
(bad customer input, non-retryable). Teardown is unconditional, so a
failed job leaves no container behind (S-6 pairs with the CLI's atomic
write: no partial artifacts of any kind).
"""

import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg

from connectors.sdk.errors import ConfigError, SourceUnavailable

CONTAINER_PREFIX = "ctxlayer-pg-"
START_TIMEOUT_S = 120.0


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, **kwargs)


def _tail(data: bytes | str, limit: int = 2000) -> str:
    text = data.decode(errors="replace") if isinstance(data, bytes) else data
    return text[-limit:].strip()


def docker_available() -> bool:
    try:
        return _run(["docker", "info"], timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _mapped_port(name: str) -> str:
    proc = _run(["docker", "port", name, "5432/tcp"], timeout=30)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SourceUnavailable(
            f"cannot resolve mapped port for container {name}: {_tail(proc.stderr)}"
        )
    # Bound to 127.0.0.1 only, so exactly one line: "127.0.0.1:PORT"
    return proc.stdout.decode().splitlines()[0].rsplit(":", 1)[1].strip()


def _wait_ready(dsn: str, timeout_s: float) -> None:
    # TCP readiness is the correct gate: the official image's init runs a
    # temporary socket-only server first, so a TCP connect can only ever
    # reach the final one.
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as exc:
            if time.monotonic() >= deadline:
                raise SourceUnavailable(
                    f"ephemeral postgres did not become ready within {timeout_s:.0f}s"
                ) from exc
            time.sleep(0.3)


@contextmanager
def ephemeral_postgres(image: str, *, start_timeout_s: float = START_TIMEOUT_S):
    """Start a fresh postgres container; yield (container_name, dsn); always remove it."""
    name = CONTAINER_PREFIX + uuid.uuid4().hex[:12]
    try:
        proc = _run(
            [
                "docker", "run", "--detach", "--rm", "--name", name,
                "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
                "--publish", "127.0.0.1:0:5432",
                image,
            ],
            timeout=600,  # generous: first use of an image pulls it
        )
    except FileNotFoundError as exc:
        raise SourceUnavailable("docker binary not found; ddl-file mode needs Docker") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceUnavailable(f"docker run {image!r} timed out (image pull?)") from exc
    if proc.returncode != 0:
        raise SourceUnavailable(
            f"cannot start postgres container from image {image!r}: {_tail(proc.stderr)}"
        )
    try:
        port = _mapped_port(name)
        dsn = f"postgresql://postgres@127.0.0.1:{port}/postgres"
        _wait_ready(dsn, start_timeout_s)
        yield name, dsn
    finally:
        _run(["docker", "rm", "--force", name], timeout=60)


def apply_ddl(container_name: str, ddl_files: list[Path]) -> None:
    """Stream each DDL file, in listed order, through psql inside the container."""
    for path in ddl_files:
        proc = _run(
            [
                "docker", "exec", "--interactive", container_name,
                "psql", "--username", "postgres", "--dbname", "postgres",
                "-v", "ON_ERROR_STOP=1", "--file", "-",
            ],
            input=path.read_bytes(),
            timeout=600,
        )
        if proc.returncode != 0:
            raise ConfigError(
                f"DDL file {path} rejected by postgres: {_tail(proc.stderr)}"
            )
