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
