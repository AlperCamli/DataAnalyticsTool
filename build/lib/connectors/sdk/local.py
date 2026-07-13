"""Local CLI transport — run a snapshot job without the core job API.

    python -m connectors.sdk.local MODULE:ATTR --config CONFIG.json --out OUT.json

MODULE:ATTR names a `Connector` instance (ATTR defaults to
`connector`), e.g. `connectors.static_demo.connector:connector`.
The config file is the job's `payload.config` as JSON.

Exit codes: 0 job succeeded (snapshot written to --out, §6 canonical
form); 1 job failed (no output file — S-6); 2 usage/loading error;
3 job deferred (quota, J-5 — no output file, retry after the printed
interval). The output write is atomic (temp file + rename), so a
failed job can never leave a partial snapshot behind.
"""

import argparse
import json
import logging
import os
import sys
from importlib import import_module
from pathlib import Path

from connectors.sdk.connector import Connector, RegistrationError
from connectors.sdk.manifest import ManifestError
from connectors.sdk.runner import Job, run_job

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DEFERRED = 0, 1, 2, 3


def load_connector(spec: str) -> Connector:
    module_name, _, attr = spec.partition(":")
    attr = attr or "connector"
    module = import_module(module_name)
    obj = getattr(module, attr)
    if not isinstance(obj, Connector):
        raise TypeError(f"{spec}: expected a Connector instance, got {type(obj).__name__}")
    return obj


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m connectors.sdk.local",
        description="Run a connector's snapshot job locally, writing the "
        "canonical snapshot to a file.",
    )
    parser.add_argument("connector", metavar="MODULE:ATTR",
                        help="dotted path to a Connector instance "
                        "(ATTR defaults to 'connector')")
    parser.add_argument("--config", required=True, metavar="FILE",
                        help="job config (payload.config) as JSON")
    parser.add_argument("--out", required=True, metavar="FILE",
                        help="where to write the snapshot on success")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="log harness phases to stderr")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        stream=sys.stderr, format="%(name)s: %(message)s",
    )

    try:
        connector = load_connector(args.connector)
    except (ImportError, AttributeError, TypeError, ManifestError, RegistrationError) as exc:
        print(f"cannot load connector {args.connector!r}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read config {args.config}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    job = Job.local(config)
    outcome = run_job(connector, job)

    if outcome.status == "succeeded":
        out = Path(args.out)
        write_atomic(out, outcome.snapshot.serialized)
        doc = outcome.snapshot.document
        print(f"{out}: OK — system={doc['system']} source_mode={doc['source_mode']} "
              f"objects={len(doc['objects'])} (job {job.job_id})")
        return EXIT_OK
    if outcome.status == "deferred":
        print(f"job {job.job_id}: DEFERRED retry_after_s={outcome.retry_after_s} — "
              f"{outcome.error.code}: {outcome.error.message}", file=sys.stderr)
        return EXIT_DEFERRED
    error = outcome.error
    print(f"job {job.job_id}: FAILED {error.code} "
          f"({'retryable' if error.retryable else 'non-retryable'}) — {error.message}",
          file=sys.stderr)
    return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
