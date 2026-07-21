"""Go/no-go preflight gates (CP-5, rulings D-74.5 / D-75.4).

The preflight's whole job is to fail closed: every check must block the
baseline when it cannot positively verify its condition. These tests are
mostly about the *negative* cases, because a preflight that passes when it
should not is worse than no preflight — it launders an unverified run as
an approved one.
"""

from __future__ import annotations

import json

import pytest

from tools.baseline_preflight import (
    Check,
    InstanceProbe,
    build_packet,
    check_billing,
    check_instances,
    render_markdown,
)


def _probe(condition: str, *, kb_ref: str | None, sync: bool = False, mcp: bool = True) -> InstanceProbe:
    return InstanceProbe(
        condition=condition,
        url=f"http://localhost/{condition}",
        reachable=True,
        kb_ref=kb_ref,
        kb_remote=f"git@example/{condition}",
        sync_enabled=sync,
        mcp_enabled=mcp,
    )


def _named(checks: list[Check], fragment: str) -> Check:
    matches = [c for c in checks if fragment in c.name]
    assert matches, f"no check matching {fragment!r} in {[c.name for c in checks]}"
    return matches[0]


class TestBilling:
    def test_api_key_set_blocks_the_run(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
        checks = check_billing(None)
        assert _named(checks, "ANTHROPIC_API_KEY").ok is False

    def test_missing_smoke_record_is_not_a_pass(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        checks = check_billing(None)
        # The precondition passes; the positive evidence is absent, and
        # absence must not read as verified.
        assert _named(checks, "ANTHROPIC_API_KEY").ok is True
        assert _named(checks, "billed on subscription").ok is False

    def test_zero_cost_smoke_record_passes(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rec = tmp_path / "journey.json"
        rec.write_text(json.dumps({
            "case_id": "c1", "condition": "enriched-kb", "backend": "claude-code",
            "cost_usd": 0, "drafts": [{"seq": 1}],
        }))
        checks = check_billing(rec)
        assert _named(checks, "billed on subscription").ok is True
        assert _named(checks, "smoke journey completed").ok is True

    def test_non_zero_cost_blocks_the_run(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rec = tmp_path / "journey.json"
        rec.write_text(json.dumps({"cost_usd": 0.42, "drafts": [{"seq": 1}]}))
        assert _named(check_billing(rec), "billed on subscription").ok is False

    def test_absent_cost_field_blocks_the_run(self, tmp_path, monkeypatch):
        # None means the field was never populated: that tells us nothing
        # about what was billed, so it cannot pass.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rec = tmp_path / "journey.json"
        rec.write_text(json.dumps({"drafts": [{"seq": 1}]}))
        assert _named(check_billing(rec), "billed on subscription").ok is False

    def test_unreadable_record_blocks_the_run(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rec = tmp_path / "journey.json"
        rec.write_text("{not json")
        assert _named(check_billing(rec), "billed on subscription").ok is False


class TestInstances:
    def test_three_distinct_kbs_pass(self):
        probes = [
            _probe("enriched-kb", kb_ref="aaa"),
            _probe("machine-kb", kb_ref="bbb"),
            _probe("no-kb", kb_ref="ccc"),
        ]
        checks = check_instances(probes)
        assert all(c.ok for c in checks), [c for c in checks if not c.ok]

    def test_sync_enabled_on_any_instance_blocks_the_run(self):
        # D-75.4: three schedulers sharing one queue is the failure mode.
        probes = [_probe("machine-kb", kb_ref="bbb", sync=True)]
        assert _named(check_instances(probes), "sync disabled").ok is False

    def test_duplicate_kb_ref_blocks_the_run(self):
        # Two conditions serving the same KB are not two conditions; the
        # run would report a difference it never created.
        probes = [
            _probe("enriched-kb", kb_ref="same"),
            _probe("machine-kb", kb_ref="same"),
        ]
        check = _named(check_instances(probes), "distinct KBs")
        assert check.ok is False
        assert "DUPLICATE" in check.detail

    def test_unreachable_instance_blocks_the_run(self):
        probes = [InstanceProbe("no-kb", "http://down", reachable=False, error="refused")]
        checks = check_instances(probes)
        assert _named(checks, "reachable").ok is False
        assert _named(checks, "distinct KBs").ok is False

    def test_missing_kb_ref_blocks_the_run(self):
        assert _named(check_instances([_probe("no-kb", kb_ref=None)]), "kb_ref resolved").ok is False


class TestPacket:
    def test_verdict_is_go_only_when_every_check_passes(self):
        probes = [_probe("enriched-kb", kb_ref="aaa")]
        assert build_packet(probes, [Check("a", True, "")], "m")["verdict"] == "GO"
        assert build_packet(probes, [Check("a", True, ""), Check("b", False, "")], "m")["verdict"] == "NO-GO"

    def test_packet_records_the_r8_keys_and_pinned_model(self):
        probes = [_probe("enriched-kb", kb_ref="aaa"), _probe("no-kb", kb_ref="ccc")]
        packet = build_packet(probes, [Check("a", True, "")], "claude-opus-4-8")
        assert packet["model_id"] == "claude-opus-4-8"
        assert packet["transport"] == "benchmark-skill-v1"
        assert packet["r8_keys"]["enriched-kb"]["kb_ref"] == "aaa"
        assert packet["r8_keys"]["no-kb"]["kb_ref"] == "ccc"

    def test_markdown_renders_both_verdicts(self):
        probes = [_probe("no-kb", kb_ref="ccc")]
        go = render_markdown(build_packet(probes, [Check("a", True, "ok")], "m"))
        assert "**Verdict: GO**" in go
        nogo = render_markdown(build_packet(probes, [Check("a", False, "bad")], "m"))
        assert "**Verdict: NO-GO**" in nogo
        assert "block the baseline" in nogo


@pytest.mark.parametrize("cost", [0, 0.0])
def test_zero_cost_variants_all_pass(tmp_path, monkeypatch, cost):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rec = tmp_path / "j.json"
    rec.write_text(json.dumps({"cost_usd": cost, "drafts": [{"seq": 1}]}))
    assert _named(check_billing(rec), "billed on subscription").ok is True
