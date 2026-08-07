"""D-78.2 for AS-19: the assertions, run against output that should fail them.

A conformance item may only be reported green on evidence that could have
failed if the behavior were absent. This takes the *actual* run artifacts
next to it and mutates them four ways — each a real failure mode of the
S1c mode — and shows the scenario's own checks going red.

    .venv/bin/python results/phase2/a5/as19/falsify.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tools.skill_conformance import check_triage_pr_body, check_triage_repair
from tools.skill_scenarios import TRIAGE_EXPECTED, _parse_frontmatter

REPO = Path(__file__).resolve().parents[4]
STAGED = REPO / "tools" / "scenarios" / "triage-kb"
RUN = Path(__file__).resolve().parent / "workdirs" / "enrich-triage"
HASHES = {f"triage.shop.{o['name']}": o["schema_hash"] for o in
          json.loads((STAGED / ".contextlayer/snapshots/triage.json").read_text())["objects"]}


def repairs(mutate=None):
    out = []
    for rel, klass in TRIAGE_EXPECTED.items():
        fm_b, body_b = _parse_frontmatter((STAGED / rel).read_text())
        text = (RUN / "kb" / rel).read_text()
        if mutate:
            text = mutate(rel, text)
        fm_a, body_a = _parse_frontmatter(text)
        out += [(rel, f.detail) for f in check_triage_repair(
            fm_b, fm_a, body_before=body_b, body_after=body_a,
            triage_class=klass, current_schema_hash=HASHES.get(fm_b.get("object")))]
    return out


CASES = {
    "a `confirms-prose` repair that also polished the prose":
        lambda rel, t: t + "\n- one more clarifying sentence.\n" if "exports" in rel else t,
    "the skill certifying its own repair":
        lambda rel, t: t.replace("status: draft", "status: verified").replace(
            "last_verified: null", 'last_verified: "2026-08-07 (enrich)"'),
    "the missing-object doc turned green by deleting the dependency":
        lambda rel, t: t if "orders" not in rel else
        t.replace("status: contaminated", "status: draft").replace("  - triage.shop.legacy_carts\n", ""),
}

if __name__ == "__main__":
    print("as-run:", repairs() or "clean — every repair obeys its class")
    for name, mutate in CASES.items():
        print(f"\n[{name}]")
        for rel, detail in repairs(mutate):
            print(f"    {rel}: {detail}")
    body = (RUN / "out" / "PR-BODY.md").read_text()
    print("\n[a PR body with the certification section removed]")
    for f in check_triage_pr_body(body.split("### Certification")[0], docs=TRIAGE_EXPECTED):
        print(f"    {f.check}: {f.detail}")
