"""Deliverable 2 — the three context conditions (R1).

One journey prompt is run under three, and only three, context-access
regimes (product spec §11); execution access is identical in all three.

* **no-kb** — no KB files. The agent discovers structure live
  (``information_schema`` for SQL, the GA4 metadata endpoint, GSC's fixed
  schema) and executes. ``context_root`` is ``None``.
* **machine-kb** — the KB deterministically re-derived by rendering the
  latest snapshots with *empty* enrichment and excluding every human-owned
  file. This is exactly ``generator.render`` into a fresh directory: it
  writes only machine docs (``*.schema.md``, machine ``index.md``) and
  bootstraps the root ``index.md`` / ``conventions.md`` templates; human
  files (``entities/``, human object docs, ``_notes.md``, the enriched
  ``conventions.md``) are never produced. Empty enrichment renders every
  purpose/description slot as ``—``.
* **enriched-kb** — the full customer KB clone at a pinned ``kb_ref``.

Scope note: the machine condition is the generator's snapshot→tree render.
Lineage (``lineage/graph.json``) is a separate machine artifact and is
*not* included — for the CVBuilder estate it carries no view edges (17
tables, 0 views) and the FK structure it would surface is already in the
machine object docs (foreign keys + referenced-by). Recorded as a
deliberate boundary, revisitable if an estate with views makes lineage
material to the machine condition.

The build is deterministic: same snapshots -> byte-identical tree (dates
come from ``captured_at``, no wall clock), so the machine-kb ref is stable
across rebuilds and safe to key results by (R8).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from generator.render import RenderResult, render_tree

_PKG = Path(__file__).resolve().parent
DEFAULT_SNAPSHOTS = tuple(sorted((_PKG / "suite" / "snapshots").glob("*.json")))
DEFAULT_ENRICHED_KB = Path.home() / "Desktop" / "kb"

NO_KB = "no-kb"
MACHINE_KB = "machine-kb"
ENRICHED_KB = "enriched-kb"


def is_machine_file(rel: str) -> bool:
    """A file the deterministic render is allowed to produce.

    Machine docs (``index.md``, ``*.schema.md``) plus the two bootstrapped
    root templates. Anything else under the tree is human-owned and must
    not appear in a machine-kb build.
    """
    name = Path(rel).name
    return name in ("index.md", "conventions.md") or name.endswith(".schema.md")


@dataclass(frozen=True)
class Condition:
    """One context-access regime for a journey run."""

    name: str
    context_root: Path | None  # readable-file root; None => live discovery only
    ref: str  # machine-kb content ref, enriched kb_ref (git sha), or a live sentinel


@dataclass(frozen=True)
class MachineKbBuild:
    out_dir: Path
    files: tuple[str, ...]
    manifest: dict[str, str]  # rel path -> sha256:hex
    ref: str  # sha256 over the canonical manifest — the machine-kb content id
    render: RenderResult = field(repr=False, default_factory=RenderResult)

    def condition(self) -> Condition:
        return Condition(MACHINE_KB, self.out_dir, self.ref)


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_ref(manifest: dict[str, str]) -> str:
    canonical = "".join(f"{rel}  {digest}\n" for rel, digest in sorted(manifest.items()))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_machine_kb(
    out_dir: Path | str,
    snapshot_paths: Sequence[Path] = DEFAULT_SNAPSHOTS,
    *,
    clean: bool = True,
) -> MachineKbBuild:
    """Build the machine-kb condition into ``out_dir`` (R1).

    Renders the snapshots into a *fresh* directory so no human sibling can
    influence the render or survive in the tree; then verifies the
    exclusion invariant (only machine files present) and returns a content
    manifest whose hash is the machine-kb ref.
    """
    out_dir = Path(out_dir)
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshots = [json.loads(Path(p).read_text(encoding="utf-8")) for p in snapshot_paths]
    render = render_tree(snapshots, out_dir)

    files = sorted(
        p.relative_to(out_dir).as_posix()
        for p in out_dir.rglob("*")
        if p.is_file()
    )
    leaked = [rel for rel in files if not is_machine_file(rel)]
    if leaked:
        raise AssertionError(
            f"machine-kb build leaked human-owned files (R1 exclusion): {leaked}"
        )
    manifest = {rel: _sha256_file(out_dir / rel) for rel in files}
    return MachineKbBuild(
        out_dir=out_dir,
        files=tuple(files),
        manifest=manifest,
        ref=_manifest_ref(manifest),
        render=render,
    )


def _git_ref(repo: Path) -> str:
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def no_kb_condition() -> Condition:
    return Condition(NO_KB, None, "live-discovery")


def enriched_kb_condition(kb_root: Path = DEFAULT_ENRICHED_KB) -> Condition:
    return Condition(ENRICHED_KB, kb_root, _git_ref(kb_root))


def machine_kb_condition(out_dir: Path | str, snapshot_paths: Sequence[Path] = DEFAULT_SNAPSHOTS) -> Condition:
    return build_machine_kb(out_dir, snapshot_paths).condition()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a benchmark context condition (R1).")
    sub = parser.add_subparsers(dest="condition", required=True)
    m = sub.add_parser(MACHINE_KB, help="render the machine-kb condition from snapshots")
    m.add_argument("--out", required=True, type=Path)
    m.add_argument("--snapshot", type=Path, action="append", dest="snapshots")
    args = parser.parse_args(argv)

    if args.condition == MACHINE_KB:
        snaps = args.snapshots or list(DEFAULT_SNAPSHOTS)
        build = build_machine_kb(args.out, snaps)
        print(f"machine-kb: {len(build.files)} files -> {args.out}")
        print(f"  render: written {len(build.render.written)} · "
              f"bootstrapped {len(build.render.bootstrapped)}")
        print(f"  ref: {build.ref}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
