"""Stage CLI for validate_sql's SQL dialect (ruling C1/C2 pattern).

    python -m sqlval REQUEST.json

Reads the request JSON (see ``validate_statement``), prints the verdict
JSON on stdout. Exit 0 = pass, 1 = fail, 2 = usage/internal error.
"""

import json
import sys

from sqlval import validate_statement


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m sqlval REQUEST.json", file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as f:
            request = json.load(f)
    except (OSError, ValueError) as e:
        print(f"error: cannot read request {args[0]}: {e}", file=sys.stderr)
        return 2
    try:
        verdict = validate_statement(request)
    except Exception as e:  # noqa: BLE001 — the gate itself failed, not the SQL
        print(f"error: validator failure: {e}", file=sys.stderr)
        return 2
    json.dump(verdict, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if verdict["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
