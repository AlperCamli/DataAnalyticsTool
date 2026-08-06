"""What the shipped compose files actually put in the core's environment.

Two families of assertion, both born from the same class of failure — a
stack that starts clean and quietly ignores what the operator told it.

**D-94.4 (below):** the publish-budget override must reach the container.

**D-110.2:** feature toggles must live in env files, never in a service's
`environment:` block, because compose ranks `environment:` above
`env_file:` — so a toggle declared there can never be raised by an
overlay. That shape cost the pilot two silent sync-off days (D-84.2) and
a runbook act that served 404 while `/healthz` said `ok` (D-109.8). The
third occurrence was ruled a structural defect, and these tests are what
keep the fix from being undone by the next edit.

Why the D-94.4 case is the *opposite* rule and still correct: a publish
budget is a value this compose file computes from the invoking shell, not
one a deployment supplies. `environment:` is exactly right for it. The
line the tests draw is between those two kinds of value.

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

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "docker-compose.yml"
DEFAULTS_ENV = REPO_ROOT / "deploy" / "core.defaults.env"
GUARD = REPO_ROOT / "deploy" / "check-toggle-env.sh"
LIVE_OVERLAY = REPO_ROOT / "deploy" / "compose.live.yml"
BASELINE_OVERLAY = REPO_ROOT / "deploy" / "compose.baseline.yml"
PILOT_SYNC_ENV = REPO_ROOT / ".secrets" / "sync.env"
VAR = "CORE_MCP_PUBLISH_PER_HOUR"

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI not available"
)


def _resolved(
    *overlays: Path,
    service: str = "core",
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """A service's resolved environment, via `docker compose config`.

    This is the same merge-and-interpolate the real `up` performs, so it
    answers what the container *will* see rather than what the YAML says.
    `config` needs the docker CLI but starts nothing.
    """
    files: list[str] = ["-f", str(COMPOSE)]
    for overlay in overlays:
        files += ["-f", str(overlay)]
    proc = subprocess.run(
        ["docker", "compose", *files, "config"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home()), **(env or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    resolved = yaml.safe_load(proc.stdout)
    return resolved["services"][service]["environment"]


def _core_env(env: dict[str, str] | None = None) -> dict[str, str]:
    return _resolved(env=env)


def _toggles() -> list[str]:
    """The canonical toggle set, read from the guard script that enforces it.

    Read rather than restated so this file cannot drift from the shell
    script an operator actually trips over.
    """
    for line in GUARD.read_text().splitlines():
        if line.startswith("TOGGLES="):
            return line.split("=", 1)[1].strip().strip('"').split()
    raise AssertionError(f"no TOGGLES= line in {GUARD}")


def _env_file_keys(path: Path) -> set[str]:
    keys = set()
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.add(stripped.split("=", 1)[0])
    return keys


def _compose_files() -> list[Path]:
    return [COMPOSE, LIVE_OVERLAY, BASELINE_OVERLAY, REPO_ROOT / "deploy" / "compose.mcp.yml"]


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


@needs_docker
def test_override_reaches_the_core_service() -> None:
    """Set it in the shell → compose resolves it onto the container."""
    assert _core_env({VAR: "12"})[VAR] == "12"


@needs_docker
def test_unset_leaves_the_server_default_in_force() -> None:
    """Unset → empty string, which the core's intVar() reads as "use 4"."""
    assert _core_env()[VAR] == ""


# --- D-110.2: toggles live in env files, and overlays can raise them --------


def test_no_feature_toggle_appears_in_any_environment_block() -> None:
    """The structural half of the fix, asserted at the source.

    A toggle under `environment:` outranks every `env_file:` in every
    overlay, silently. This is the assertion that stops the shape from
    coming back — including in the two forms it likes to return as:
    a `KEY: value` mapping, and a bare `- KEY` pass-through entry.
    """
    toggles = set(_toggles())
    offenders: list[str] = []
    for path in _compose_files():
        compose = yaml.safe_load(path.read_text())
        for name, service in (compose.get("services") or {}).items():
            block = service.get("environment")
            if not block:
                continue
            keys = (
                set(block)
                if isinstance(block, dict)
                else {entry.split("=", 1)[0] for entry in block}
            )
            for hit in sorted(keys & toggles):
                offenders.append(f"{path.name}:{name}:{hit}")
    assert not offenders, (
        "feature toggle(s) in an `environment:` block, where no overlay can "
        f"raise them (D-110.2): {offenders}. Move them to an env file."
    )


def test_every_toggle_has_a_default_in_the_defaults_env_file() -> None:
    """A toggle with no default is a toggle whose off-state is a guess."""
    missing = sorted(set(_toggles()) - _env_file_keys(DEFAULTS_ENV))
    assert not missing, f"{missing} have no default in {DEFAULTS_ENV.name}"


def test_the_core_reports_exactly_the_toggles_the_deployment_layer_knows() -> None:
    """The three-way contract, asserted in one place.

    `FEATURE_TOGGLES` in config.ts is what `/healthz` reports; the guard
    script is what refuses a shell export; `core.defaults.env` is what
    supplies the off-state. A toggle that exists in one and not the others
    is either unreportable, unsettable, or unguessable — so the sets have
    to be identical, and a new toggle costs three lines or a red test.
    """
    config_ts = (REPO_ROOT / "core" / "src" / "config.ts").read_text()
    block = config_ts.split("FEATURE_TOGGLES", 1)[1].split("];", 1)[0]
    reported = set(re.findall(r'env:\s*"([A-Z_][A-Z0-9_]*)"', block))
    assert reported, "could not parse FEATURE_TOGGLES out of config.ts"
    assert reported == set(_toggles()), (
        f"config.ts reports {sorted(reported)} but the guard script enforces "
        f"{sorted(_toggles())}"
    )


@needs_docker
def test_an_overlay_env_file_wins(tmp_path: Path) -> None:
    """The ruling's clause: an overlay value beats the base default.

    Built from a scratch overlay rather than the pilot's own, so this runs
    on a clean checkout with no `.secrets/` — the base stack ships every
    toggle off, and the overlay turns one on with nothing in the shell.
    """
    assert _core_env()["CORE_MCP_ENABLED"] == "0"

    env_file = tmp_path / "over.env"
    env_file.write_text("CORE_MCP_ENABLED=1\n", encoding="utf-8")
    overlay = tmp_path / "compose.over.yml"
    overlay.write_text(
        f"services:\n  core:\n    env_file:\n      - {env_file}\n", encoding="utf-8"
    )

    assert _resolved(overlay)["CORE_MCP_ENABLED"] == "1"


@needs_docker
def test_a_bare_passthrough_entry_is_not_an_escape_hatch(tmp_path: Path) -> None:
    """Why there is no shell override, recorded as a test rather than a claim.

    `environment: [- CORE_MCP_ENABLED]` reads like "defer to the env file
    unless the shell says otherwise". It is not: compose resolves the
    unset case to null and the container ends up with the variable
    **unset**, wiping the env-file value. Verified here so the next person
    who reaches for it finds the answer instead of the two silent days.
    """
    env_file = tmp_path / "over.env"
    env_file.write_text("CORE_MCP_ENABLED=1\n", encoding="utf-8")
    overlay = tmp_path / "compose.over.yml"
    overlay.write_text(
        f"services:\n  core:\n    env_file:\n      - {env_file}\n"
        "    environment:\n      - CORE_MCP_ENABLED\n",
        encoding="utf-8",
    )

    assert _resolved(overlay)["CORE_MCP_ENABLED"] is None


@needs_docker
@pytest.mark.skipif(not PILOT_SYNC_ENV.exists(), reason="no .secrets/sync.env (pilot only)")
def test_the_live_overlay_arms_the_stack_with_nothing_in_the_shell() -> None:
    """The failure D-109.8 hit, asserted against the real overlay.

    Before the fix this needed `set -a; . .secrets/sync.env` first; without
    it the core came up healthy with the MCP surface and the dashboard off,
    serving 404 at `/app/`. The shell here is empty.
    """
    env = _resolved(LIVE_OVERLAY)
    assert env["CORE_MCP_ENABLED"] == "1"
    assert env["SYNC_ENABLED"] == "1"
    assert env["SYNC_GIT_REMOTE"], "the KB remote did not reach the container"


@needs_docker
@pytest.mark.skipif(not PILOT_SYNC_ENV.exists(), reason="no .secrets/sync.env (pilot only)")
def test_the_baseline_overlay_outranks_the_live_env_file() -> None:
    """Layered overlays resolve by list order, last wins.

    D-75.4 requires all three baseline cores to be sync-OFF readers even
    though the live overlay beneath them turns sync on. That inversion now
    holds because `deploy/baseline/enriched.env` is last in the chain —
    a reason, where it used to be a side effect of `environment:` ranking.
    """
    env = _resolved(LIVE_OVERLAY, BASELINE_OVERLAY)
    assert env["SYNC_ENABLED"] == "0"
    assert env["CORE_MCP_ENABLED"] == "1"
    assert _resolved(LIVE_OVERLAY)["SYNC_ENABLED"] == "1"  # the layer it overrode


def test_the_guard_refuses_a_toggle_exported_into_the_shell() -> None:
    """`CORE_MCP_ENABLED=1 make stack-live` is now a loud error, not a no-op.

    Removing the toggles from `environment:` also removed the shell's
    ability to set them, so the old habit had to stop being silent — the
    whole point of the ruling was to stop trading one quiet failure for
    another.
    """
    clean = subprocess.run(["sh", str(GUARD)], capture_output=True, text=True, timeout=30)
    assert clean.returncode == 0, clean.stderr

    for toggle in _toggles():
        dirty = subprocess.run(
            ["sh", str(GUARD)],
            env={"PATH": "/usr/bin:/bin", toggle: "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert dirty.returncode == 1, f"{toggle} exported but the guard passed"
        assert toggle in dirty.stderr
        # JC-8 habit: the guard names variables, never their values.
        assert "=1" not in dirty.stderr
