"""The shipped `docker-compose.yml` actually passes the publish-budget
override into the core container (D-94.4).

Why this file exists: the July 29 gate prep set
`CORE_MCP_PUBLISH_PER_HOUR=12` in front of `docker compose up`, the stack
came up clean, and the server kept its 4-per-hour default — because
compose only forwards the variables a service's `environment:` block
names, and this one was not on the list. Nothing failed; the budget was
simply still four, which an api-class report (two publish calls) exhausts
in one act plus a revision. The runbook grew a workaround; the ruling
replaced it with a one-line passthrough and this read-back.

The test reads the value back out of `docker compose config` — the same
interpolation the real `up` performs — rather than pattern-matching the
YAML source, so a future edit that reintroduces the gap fails here.

`config` needs the docker CLI but starts nothing; when docker is absent
the interpolation assertions skip and the source-level assertion still
runs.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "docker-compose.yml"
VAR = "CORE_MCP_PUBLISH_PER_HOUR"


def _core_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """The core service's resolved environment, via `docker compose config`."""
    proc = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home()), **(env or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    resolved = yaml.safe_load(proc.stdout)
    return resolved["services"]["core"]["environment"]


def test_compose_declares_the_publish_budget_passthrough() -> None:
    """The variable is on the core service's environment list at all."""
    compose = yaml.safe_load(COMPOSE.read_text())
    env = compose["services"]["core"]["environment"]
    assert VAR in env, (
        f"{VAR} is not in the core service's environment block; an override "
        "on the command line will never reach the server"
    )
    # Interpolated from the identically-named host variable, defaulting to
    # empty so config.ts falls back to its own default (intVar treats "" as
    # unset). A hard-coded number here would be a policy change in a compose
    # file, which is not where publish policy lives.
    assert env[VAR] == "${" + VAR + ":-}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available")
def test_override_reaches_the_core_service() -> None:
    """Set it in the shell → compose resolves it onto the container."""
    assert _core_env({VAR: "12"})[VAR] == "12"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available")
def test_unset_leaves_the_server_default_in_force() -> None:
    """Unset → empty string, which the core's intVar() reads as "use 4"."""
    assert _core_env()[VAR] == ""
