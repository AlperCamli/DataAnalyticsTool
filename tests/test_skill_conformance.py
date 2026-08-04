"""Rule validators for skill output (CP-5 deliverable 7, layer (a)).

Per ruling D-78 these are **regression tests over staged artifacts**, not
the AS-9/10/12 conformance evidence. They pin the rules; they cannot fail
when a skill misbehaves, because every artifact here is written by the
test. The gate evidence is the behavioral scenarios against the fixture
deployment.

Each test stages a good artifact and a bad one, because a validator that
has only ever seen good input is not known to reject anything.
"""

from __future__ import annotations

from tools.skill_conformance import (
    check_artifact_trust,
    check_gap_not_guessed,
    check_purpose_frontmatter,
)


def _codes(findings) -> list[str]:
    return [f.check for f in findings]


class TestPurposeFrontMatter:
    """CP-E4 / AS-12."""

    GOOD_FM = {
        "purpose": "One row per checkout; the commerce fact table.",
        "column_purposes": {"user_id": "The account that placed the order."},
    }

    def test_complete_frontmatter_with_empty_body_is_valid(self):
        # An empty body under complete front-matter is a complete doc, not
        # a stub — the rule must not push authors into writing padding.
        assert check_purpose_frontmatter(self.GOOD_FM, "", columns=["user_id"]) == []

    def test_body_with_only_enum_decoding_is_valid(self):
        body = "## Warnings\n\n`status`: 1 = pending, 2 = shipped, 3 = cancelled.\n"
        assert check_purpose_frontmatter(self.GOOD_FM, body, columns=["user_id"]) == []

    def test_missing_purpose_is_flagged(self):
        findings = check_purpose_frontmatter({"column_purposes": {"a": "x"}}, "")
        assert "CP-E4" in _codes(findings)
        assert any("no `purpose`" in f.detail for f in findings)

    def test_missing_column_purposes_is_flagged_when_columns_exist(self):
        findings = check_purpose_frontmatter({"purpose": "A table."}, "", columns=["user_id"])
        assert any("column_purposes" in f.detail for f in findings)

    def test_body_purpose_section_is_flagged(self):
        # The headline violation: a body section restating front-matter.
        body = "## Purpose\n\nThis table records orders placed by users.\n"
        findings = check_purpose_frontmatter(self.GOOD_FM, body, columns=["user_id"])
        assert any("restates front-matter" in f.detail for f in findings)

    def test_body_duplicating_the_one_liner_verbatim_is_flagged(self):
        body = f"## Overview\n\n{self.GOOD_FM['purpose']}\n"
        findings = check_purpose_frontmatter(self.GOOD_FM, body, columns=["user_id"])
        assert any("duplicates `purpose` verbatim" in f.detail for f in findings)

    def test_multiline_values_are_flagged(self):
        fm = {"purpose": "line one\nline two", "column_purposes": {"a": "x\ny"}}
        findings = check_purpose_frontmatter(fm, "", columns=["a"])
        assert sum("single line" in f.detail for f in findings) == 2


class TestGapNotGuessed:
    """AS-9."""

    UNANSWERABLE = ["subscriptions.status vocabulary"]

    def test_named_gap_with_no_prose_passes(self):
        findings = check_gap_not_guessed(
            unanswerable=self.UNANSWERABLE,
            gaps=["subscriptions.status vocabulary — no DB CHECK; provider-driven, not grounded"],
            drafted_docs={"subscriptions.md": "## Grain\n\nOne row per subscription.\n"},
        )
        assert findings == []

    def test_mention_inside_a_warnings_section_is_correct_behavior(self):
        # Naming the gap in the doc is the desired behavior, not a hit.
        findings = check_gap_not_guessed(
            unanswerable=self.UNANSWERABLE,
            gaps=["subscriptions.status vocabulary not grounded"],
            drafted_docs={
                "subscriptions.md": (
                    "## Warnings\n\nThe subscriptions.status vocabulary is not "
                    "grounded — do not treat as a closed enum.\n"
                )
            },
        )
        assert findings == []

    def test_unrecorded_gap_is_flagged(self):
        findings = check_gap_not_guessed(
            unanswerable=self.UNANSWERABLE,
            gaps=[],
            drafted_docs={},
        )
        assert any("not recorded as a gap" in f.detail for f in findings)

    def test_guessed_prose_is_flagged(self):
        # The failure this rule exists for: the model filled the slot.
        findings = check_gap_not_guessed(
            unanswerable=self.UNANSWERABLE,
            gaps=["subscriptions.status vocabulary not grounded"],
            drafted_docs={
                "subscriptions.md": (
                    "## Column meanings\n\nThe subscriptions.status vocabulary is "
                    "active, canceled, past_due and unpaid.\n"
                )
            },
        )
        assert any("rather than recorded as a gap" in f.detail for f in findings)

    def test_guess_smuggled_into_column_purposes_is_flagged(self):
        # Front-matter is the sharper case: this value renders into the
        # machine doc, where it reads as fact.
        findings = check_gap_not_guessed(
            unanswerable=self.UNANSWERABLE,
            gaps=["subscriptions.status vocabulary not grounded"],
            drafted_docs={},
            frontmatter={
                "subscriptions.md": {
                    "column_purposes": {
                        "status": "subscriptions.status vocabulary: active, canceled, past_due."
                    }
                }
            },
        )
        assert any("renders into the machine doc as fact" in f.detail for f in findings)


class TestArtifactTrust:
    """AS-10."""

    ARTIFACT = {
        "semantics": {
            "metrics": [{"column": "net", "ref": "metrics/net-revenue.md", "certified": True}],
            "dimensions": [{"column": "page", "ref": "entities/page.md"}],
            "trust_notes": [],
        },
        "blend": None,
    }

    def test_verified_docs_need_no_disclosure(self):
        statuses = {"metrics/net-revenue.md": "verified", "entities/page.md": "verified"}
        assert check_artifact_trust(self.ARTIFACT, statuses) == []

    def test_contaminated_doc_without_a_trust_note_is_flagged(self):
        statuses = {"metrics/net-revenue.md": "contaminated", "entities/page.md": "verified"}
        findings = check_artifact_trust(self.ARTIFACT, statuses)
        assert any("net-revenue" in f.detail for f in findings)

    def test_disclosure_in_the_artifact_satisfies_the_rule(self):
        artifact = {
            "semantics": {
                **self.ARTIFACT["semantics"],
                "trust_notes": ["built on contaminated doc metrics/net-revenue.md — user overrode"],
            },
            "blend": None,
        }
        statuses = {"metrics/net-revenue.md": "contaminated", "entities/page.md": "verified"}
        assert check_artifact_trust(artifact, statuses) == []

    def test_draft_and_stale_also_require_disclosure(self):
        for status in ("draft", "stale"):
            statuses = {"metrics/net-revenue.md": status, "entities/page.md": "verified"}
            assert check_artifact_trust(self.ARTIFACT, statuses), f"{status} should require a note"

    def test_blend_key_without_entity_ref_is_flagged(self):
        artifact = {
            "semantics": {"metrics": [], "dimensions": [], "trust_notes": []},
            "blend": {"keys": [{"left_column": "page", "right_column": "pagePath"}]},
        }
        findings = check_artifact_trust(artifact, {})
        assert any("improvised" in f.detail for f in findings)

    def test_blend_key_with_entity_ref_passes(self):
        artifact = {
            "semantics": {"metrics": [], "dimensions": [], "trust_notes": []},
            "blend": {
                "keys": [
                    {
                        "left_column": "page",
                        "right_column": "pagePath",
                        "entity_ref": "entities/page.md",
                    }
                ]
            },
        }
        assert check_artifact_trust(artifact, {}) == []


# --------------------------------------------------------------------------
# CP-V1/CP-V2 — review-sync summary rules (layer (a); AS-7 evidence is the
# behavioral scenario)


from tools.skill_conformance import check_review_summary  # noqa: E402


GOOD_SUMMARY = """\
# Sync review: sync: 4 breaking, 1 additive across drill

Verdict: BREAKING — repair before merge
Four breaking changes contaminate five docs, one through a two-hop lineage path.

## Breaking (ranked by blast radius)
1. `drill.reporting.v_order_totals` — definition_changed — blast radius: 2 docs
   - contaminates `metrics/net-sales.md` (lineage path: `sha256:b6b4…`)
   - contaminates `systems/drill/reporting/v_net_sales.md` (declared dependency)
2. `drill.shop.customers` — column_removed: name — blast radius: 2 docs
   - contaminates `entities/customer.md` (declared dependency)

## Rename candidates (human decision required)
- `drill.shop.customers`: `name` → `full_name` (type text, ordinal 3) — either
  **column renamed** or **column removed + column added**; evidence: same type
  and ordinal; the removal is breaking under both readings

## Additive
- `drill.shop.order_items` — column_added: discount_pct

## Docs marked stale
- `systems/drill/shop/order_items.md`

## Undeclared references (non-authoritative)
- `systems/drill/reporting/v_net_sales.md` mentions `drill.shop.legacy_sessions`
  — body-text mention only; reviewer attention item, not a finding
"""


class TestReviewSummary:
    """CP-V1/CP-V2 pinned over staged summaries — good and bad both, because
    a validator that has only seen good input is not known to reject."""

    def test_good_summary_passes(self):
        assert check_review_summary(GOOD_SUMMARY) == []

    def test_missing_verdict_flagged(self):
        text = GOOD_SUMMARY.replace("Verdict: BREAKING — repair before merge\n", "")
        assert any("Verdict" in f.detail for f in check_review_summary(text))

    def test_additive_verdict_over_breaking_body_is_contradiction(self):
        text = GOOD_SUMMARY.replace(
            "Verdict: BREAKING — repair before merge",
            "Verdict: ADDITIVE-ONLY — safe to merge",
        )
        assert any("ADDITIVE-ONLY but" in f.detail for f in check_review_summary(text))

    def test_breaking_ranked_below_additive_is_flagged(self):
        # Move the Additive section above Breaking.
        head, breaking = GOOD_SUMMARY.split("## Breaking", 1)
        breaking, tail = breaking.split("## Additive", 1)
        reordered = head + "## Additive" + tail.split("## Docs marked stale")[0] \
            + "## Breaking" + breaking + "## Docs marked stale" \
            + tail.split("## Docs marked stale")[1]
        assert any("come first" in f.detail for f in check_review_summary(reordered))

    def test_rename_candidate_with_one_interpretation_is_flagged(self):
        text = GOOD_SUMMARY.replace(
            "either\n  **column renamed** or **column removed + column added**",
            "probably **column renamed**",
        )
        findings = check_review_summary(text)
        assert any("both interpretations" in f.detail for f in findings)

    def test_undeclared_refs_need_the_non_authoritative_marker(self):
        text = GOOD_SUMMARY.replace(" (non-authoritative)", "").replace(
            "; reviewer attention item, not a finding", ""
        )
        assert any("non-authoritative" in f.detail for f in check_review_summary(text))

    def test_merge_claim_is_a_cp_v2_violation(self):
        text = GOOD_SUMMARY + "\nAll clear — I have merged the PR.\n"
        assert any(f.check == "CP-V2" for f in check_review_summary(text))

    def test_breaking_section_without_contaminated_docs_is_flagged(self):
        text = GOOD_SUMMARY.replace("contaminates", "affects")
        assert any("contaminated docs" in f.detail for f in check_review_summary(text))


# --------------------------------------------------------------------------
# review-sync triage.py — the bundled deterministic tool, run over the
# drill fixture's staged world (real front-matter writes by the real
# generator.statuses stage, then triaged)


import json as _json  # noqa: E402
import shutil as _shutil  # noqa: E402
import subprocess as _subprocess  # noqa: E402
import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_REPO = _Path(__file__).resolve().parent.parent
_TRIAGE = _REPO / "core" / "skills" / "review-sync" / "triage.py"
_DRILL = _REPO / "fixtures" / "drill"


class TestReviewSyncTriage:
    def _staged_kb(self, tmp_path):
        kb = tmp_path / "kb"
        _shutil.copytree(_DRILL / "kb-seed", kb)
        scan = _json.loads((_DRILL / "expected" / "scan.json").read_text())
        instructions = [
            {"doc": c["doc"], "status": "contaminated", "contamination": c["contamination"]}
            for c in scan["contaminated"]
        ] + [{"doc": s["doc"], "status": "stale"} for s in scan["stale"]]
        instr = tmp_path / "statuses.json"
        instr.write_text(_json.dumps(instructions))
        proc = _subprocess.run(
            [_sys.executable, "-m", "generator.statuses", "--kb", str(kb), str(instr)],
            capture_output=True, text=True, cwd=_REPO,
        )
        assert proc.returncode == 0, proc.stderr
        return kb

    def _triage(self, kb):
        proc = _subprocess.run(
            [_sys.executable, str(_TRIAGE), "--kb", str(kb), "--json"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def test_triage_over_the_drill_world(self, tmp_path):
        kb = self._staged_kb(tmp_path)
        result = _json.loads(self._triage(kb))
        assert result["counts"]["contaminated"] == 5
        assert result["counts"]["stale"] == 1
        assert result["stale"] == ["systems/drill/shop/order_items.md"]
        # The two-hop lineage path survives the front-matter round trip.
        net_sales = next(
            e for e in result["contaminated"] if e["doc"] == "metrics/net-sales.md"
        )
        assert net_sales["contamination"]["object"] == "drill.reporting.v_order_totals"
        assert net_sales["contamination"]["path"], "lineage path lost in round-trip"
        # Blast ranking: count desc, then object asc — deterministic.
        blast = [(b["object"], b["count"]) for b in result["blast"]]
        assert blast == [
            ("drill.reporting.v_order_totals", 2),
            ("drill.shop.customers", 2),
            ("drill.shop.legacy_sessions", 1),
        ]

    def test_triage_is_deterministic(self, tmp_path):
        kb = self._staged_kb(tmp_path)
        assert self._triage(kb) == self._triage(kb)
