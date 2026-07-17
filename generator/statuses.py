"""Front-matter status writes — sync's only writes to human-owned files.

KB §6: all contamination/staleness markings land as front-matter edits
(``status``, ``contamination``) inside the drift PR — never body text
below the closing ``---`` fence (KB-4 is the CI backstop; this module is
the only writer). The edit is a formatting-preserving round-trip on the
raw front-matter lines: only the ``status:`` line and the
``contamination:`` line (with any indented block under it) are replaced;
every other byte of the file — including the body, verbatim — survives
untouched, so KB-4 holds by construction, not by diff-discipline.

CLI (invoked by the TypeScript orchestrator, ruling C2):

    python -m generator.statuses --kb DIR INSTRUCTIONS.json

INSTRUCTIONS.json: list of ``{"doc": <rel path>, "status": <value>[,
"contamination": <object|null>]}``. A ``contamination`` key present
(including ``null``) replaces the field (inserted after ``status:`` when
the doc has none); absent leaves the doc's existing value byte-untouched
(the stale transition never touches contamination, KB §5).

stdout: one JSON line ``{"edited": [...], "unchanged": [...]}`` — a doc
already carrying the requested values is left byte-identical. Exit
codes: 0 ok / 1 failed (doc missing, no front-matter, or a post-edit
re-parse mismatch — nothing partially written) / 2 usage.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from generator import frontmatter

_STATUS_LINE = re.compile(r"^status:.*$", re.MULTILINE)
# A top-level key line plus any indented continuation lines under it.
_CONTAMINATION_BLOCK = re.compile(
    r"^contamination:[^\n]*\n(?:[ \t]+[^\n]*\n)*", re.MULTILINE
)


class StatusWriteError(ValueError):
    pass


def _flow_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_flow_scalar(v) for v in value) + "]"
    raise StatusWriteError(f"unsupported contamination value type: {type(value).__name__}")


def _contamination_line(value: dict | None) -> str:
    """One-line YAML flow mapping, keys in insertion order, strings
    JSON-quoted (a valid subset of YAML double-quote escaping, matching
    the frontmatter module's quoting stance)."""
    if value is None:
        return "contamination: null\n"
    if not isinstance(value, dict):
        raise StatusWriteError("contamination must be an object or null")
    inner = ", ".join(f"{k}: {_flow_scalar(v)}" for k, v in value.items())
    return "contamination: {%s}\n" % inner


def apply_instruction(text: str, instruction: dict) -> str:
    """Return the edited file text; raises StatusWriteError on any shape
    the edit cannot make safely."""
    if not text.startswith(frontmatter.FENCE):
        raise StatusWriteError("no front-matter block at byte 0")
    end = text.find("\n---\n", len(frontmatter.FENCE) - 1)
    if end == -1:
        raise StatusWriteError("unterminated front-matter fence")
    head = text[len(frontmatter.FENCE): end + 1]  # raw front-matter lines
    rest = text[end + 1:]  # closing fence + body, byte-preserved

    status = instruction["status"]
    if not isinstance(status, str) or not status:
        raise StatusWriteError("status must be a non-empty string")
    if not _STATUS_LINE.search(head):
        raise StatusWriteError("front-matter has no top-level status: line")
    head = _STATUS_LINE.sub(f"status: {status}", head, count=1)

    if "contamination" in instruction:
        line = _contamination_line(instruction["contamination"])
        if _CONTAMINATION_BLOCK.search(head):
            head = _CONTAMINATION_BLOCK.sub(line, head, count=1)
        else:
            # insert directly after the status line, keeping line order
            # deterministic for docs that never carried the field
            head = _STATUS_LINE.sub(
                lambda m: m.group(0) + "\n" + line.rstrip("\n"), head, count=1
            )

    edited = frontmatter.FENCE + head + rest

    # Round-trip guard: the result must re-split with an identical body
    # and parseable front-matter carrying exactly the requested values.
    fm, body = frontmatter.split(edited)
    _, old_body = frontmatter.split(text)
    if fm is None or body != old_body:
        raise StatusWriteError("post-edit re-parse failed — refusing to write")
    if fm.get("status") != status:
        raise StatusWriteError("post-edit status mismatch — refusing to write")
    if "contamination" in instruction and fm.get("contamination") != instruction["contamination"]:
        raise StatusWriteError("post-edit contamination mismatch — refusing to write")
    return edited


def apply_all(kb_dir: Path, instructions: list[dict]) -> dict:
    """Validate every edit before writing any (all-or-nothing per call)."""
    planned: list[tuple[Path, str]] = []
    edited, unchanged = [], []
    for instruction in instructions:
        rel = instruction["doc"]
        path = kb_dir / rel
        if not path.is_file():
            raise StatusWriteError(f"{rel}: no such doc")
        text = path.read_text(encoding="utf-8")
        try:
            new_text = apply_instruction(text, instruction)
        except StatusWriteError as exc:
            raise StatusWriteError(f"{rel}: {exc}") from exc
        if new_text == text:
            unchanged.append(rel)
        else:
            planned.append((path, new_text))
            edited.append(rel)
    for path, new_text in planned:
        path.write_text(new_text, encoding="utf-8")
    return {"edited": sorted(edited), "unchanged": sorted(unchanged)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m generator.statuses",
        description="Apply sync status/contamination front-matter edits (KB §6).",
    )
    parser.add_argument("--kb", required=True, metavar="DIR")
    parser.add_argument("instructions", metavar="INSTRUCTIONS.json")
    args = parser.parse_args(argv)

    try:
        instructions = json.loads(
            Path(args.instructions).read_text(encoding="utf-8")
        )
        if not isinstance(instructions, list):
            raise StatusWriteError("instructions must be a JSON list")
        result = apply_all(Path(args.kb), instructions)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
