"""Dev tool: recompute every schema_hash in a snapshot file and rewrite it
pretty-printed with sorted keys (§6 rule 1 allows pretty-printing for
storage). Used to fill fixture hashes; C-4 then verifies them in CI.

    .venv/bin/python tools/fill_hashes.py fixtures/*.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapshot.hashing import schema_hash


def main(paths: list[str]) -> int:
    for path in paths:
        p = Path(path)
        snapshot = json.loads(p.read_text(encoding="utf-8"))
        for obj in snapshot["objects"]:
            obj["schema_hash"] = schema_hash(obj)
        p.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{path}: {len(snapshot['objects'])} hashes filled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
