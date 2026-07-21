"""Baseline v1 go/no-go preflight (CP-5, rulings D-74.5 / D-75.4).

Assembles the packet the owner signs off before any baseline spend, and
assembles it *mechanically* — every claim in the output is a probe result,
not a runbook step someone asserts they performed.

    .venv/bin/python -m tools.baseline_preflight \
        --instance enriched-kb=http://localhost:8100 \
        --instance machine-kb=http://localhost:8101 \
        --instance no-kb=http://localhost:8102 \
        --model claude-opus-4-8 \
        --out results/preflight

Checks, each a hard gate:

1. **Billing is on subscription.** `ANTHROPIC_API_KEY` unset in this
   environment, and the one smoke journey's own record reports no API
   cost. The evidence is the run's `cost_usd`, not a self-reported auth
   status — what was billed is a fact the run produces. A baseline that
   quietly bills API credit is a spend the owner did not approve.
2. **Sync is off on every condition instance.** Three schedulers sharing
   one queue and pushing sync PRs at scratch repos is the failure mode
   D-75.4 names; the production core stays the sole sync writer.
3. **The three instances serve three different KBs.** If two instances
   resolve to the same `kb_ref`, the conditions are not distinct and the
   run would report a difference it never created.
4. **The R8 keys are recorded** — condition name → kb_ref → profile — so
   the results artifact can be keyed and the owner can check what was
   actually served.

This module is deliberately outside `benchmark/`: the CP-5 fence keeps
the CP-2 harness byte-unchanged, and this is new CP-5 tooling.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class InstanceProbe:
    condition: str
    url: str
    reachable: bool
    kb_ref: str | None = None
    kb_remote: str | None = None
    sync_enabled: bool | None = None
    mcp_enabled: bool | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)


def probe_instance(condition: str, url: str, timeout: float = 10.0) -> InstanceProbe:
    endpoint = f"{url.rstrip('/')}/healthz"
    try:
        with urllib.request.urlopen(endpoint, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return InstanceProbe(condition, url, reachable=False, error=str(exc))

    inst = body.get("instance") or {}
    return InstanceProbe(
        condition=condition,
        url=url,
        reachable=True,
        kb_ref=inst.get("kb_ref"),
        kb_remote=inst.get("kb_remote"),
        sync_enabled=inst.get("sync_enabled"),
        mcp_enabled=inst.get("mcp_enabled"),
        raw=body,
    )


def check_billing(smoke_record: Path | None = None) -> list[Check]:
    """Subscription, not API credit.

    Two signals, and note what each one is worth:

    * ``ANTHROPIC_API_KEY`` unset is *definitive for the API path* — with
      no key, Backend B's ``claude -p`` cannot bill API credit. It is a
      precondition, not a proof of anything positive.
    * The smoke journey's ``cost_usd``, read from the record the harness
      already writes (``total_cost_usd`` from the CLI JSON, journey.py),
      is the empirical signal. This is deliberately *not* a self-reported
      auth-status string: what the run actually billed is a fact the run
      itself produces, and it is the same field the baseline records for
      every journey, so the check and the evidence agree by construction.

    A subscription-billed run reports no API cost. A non-zero cost means
    credit was spent and the preflight fails — that is the whole point of
    running one smoke journey before thirty.
    """
    checks: list[Check] = []

    key = os.environ.get("ANTHROPIC_API_KEY")
    checks.append(
        Check(
            "ANTHROPIC_API_KEY unset",
            key is None or key == "",
            "unset" if not key else f"SET ({len(key)} chars) — would bill API credit",
        )
    )

    if smoke_record is None:
        checks.append(
            Check(
                "smoke journey billed on subscription",
                False,
                "no --smoke-record given; run one journey and pass its record",
            )
        )
        return checks

    try:
        record = json.loads(smoke_record.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        checks.append(Check("smoke journey billed on subscription", False, f"unreadable: {exc}"))
        return checks

    cost = record.get("cost_usd")
    backend = record.get("backend")
    # `None` is not a pass: it means the field was never populated, which
    # tells us nothing about what was billed.
    checks.append(
        Check(
            "smoke journey billed on subscription",
            cost == 0 or cost == 0.0,
            f"backend={backend} cost_usd={cost!r}"
            + ("" if cost == 0 else " — non-zero or absent means this was not verified on-subscription"),
        )
    )
    checks.append(
        Check(
            "smoke journey completed",
            bool(record.get("drafts")),
            f"case={record.get('case_id')} condition={record.get('condition')}",
        )
    )
    return checks


def check_instances(probes: list[InstanceProbe]) -> list[Check]:
    checks: list[Check] = []

    for p in probes:
        checks.append(
            Check(
                f"{p.condition}: reachable",
                p.reachable,
                p.url if p.reachable else f"{p.url} — {p.error}",
            )
        )
        if not p.reachable:
            continue
        checks.append(
            Check(
                f"{p.condition}: sync disabled",
                p.sync_enabled is False,
                f"sync_enabled={p.sync_enabled}",
            )
        )
        checks.append(
            Check(
                f"{p.condition}: MCP armed",
                p.mcp_enabled is True,
                f"mcp_enabled={p.mcp_enabled}",
            )
        )
        checks.append(
            Check(
                f"{p.condition}: kb_ref resolved",
                bool(p.kb_ref),
                f"kb_ref={p.kb_ref or 'MISSING'}",
            )
        )

    live = [p for p in probes if p.reachable and p.kb_ref]
    refs = {p.kb_ref for p in live}
    checks.append(
        Check(
            "the conditions serve distinct KBs",
            len(refs) == len(live) and len(live) == len(probes),
            f"{len(refs)} distinct kb_ref across {len(probes)} instances"
            + ("" if len(refs) == len(live) else " — DUPLICATE: conditions are not distinct"),
        )
    )
    return checks


def build_packet(probes: list[InstanceProbe], checks: list[Check], model_id: str) -> dict:
    return {
        "packet_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_id": model_id,
        "transport": "benchmark-skill-v1",
        "r8_keys": {
            p.condition: {"kb_ref": p.kb_ref, "kb_remote": p.kb_remote, "url": p.url}
            for p in probes
        },
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
        "verdict": "GO" if all(c.ok for c in checks) else "NO-GO",
    }


def render_markdown(packet: dict) -> str:
    lines = [
        "# Baseline v1 — go/no-go preflight",
        "",
        f"**Verdict: {packet['verdict']}**  ·  generated {packet['generated_at']}",
        f"  ·  model `{packet['model_id']}`  ·  transport `{packet['transport']}`",
        "",
        "## Checks",
        "",
        "| ✓ | Check | Detail |",
        "|---|---|---|",
    ]
    for c in packet["checks"]:
        lines.append(f"| {'✅' if c['ok'] else '❌'} | {c['name']} | {c['detail']} |")

    lines += ["", "## R8 keys", "", "| Condition | kb_ref | remote |", "|---|---|---|"]
    for cond, key in packet["r8_keys"].items():
        lines.append(f"| `{cond}` | `{key['kb_ref'] or '—'}` | {key['kb_remote'] or '—'} |")

    if packet["verdict"] != "GO":
        lines += [
            "",
            "> Failing checks block the baseline. Each one is a condition that would",
            "> make the run's numbers mean something other than what they claim.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Baseline v1 go/no-go preflight")
    ap.add_argument(
        "--instance",
        action="append",
        default=[],
        metavar="CONDITION=URL",
        help="condition instance, repeatable (e.g. no-kb=http://localhost:8102)",
    )
    ap.add_argument("--model", required=True, help="pinned model id for the run")
    ap.add_argument("--out", type=Path, help="write packet.json + packet.md here")
    ap.add_argument("--skip-billing", action="store_true", help="probe instances only")
    ap.add_argument(
        "--smoke-record",
        type=Path,
        help="journey record from the one smoke journey — its cost_usd is the billing evidence",
    )
    args = ap.parse_args(argv)

    probes: list[InstanceProbe] = []
    for spec in args.instance:
        if "=" not in spec:
            ap.error(f"--instance expects CONDITION=URL, got {spec!r}")
        condition, url = spec.split("=", 1)
        probes.append(probe_instance(condition, url))

    checks: list[Check] = []
    if not args.skip_billing:
        checks += check_billing(args.smoke_record)
    if probes:
        checks += check_instances(probes)
    if not checks:
        ap.error("nothing to check: pass --instance and/or drop --skip-billing")

    packet = build_packet(probes, checks, args.model)
    md = render_markdown(packet)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "packet.json").write_text(json.dumps(packet, indent=2) + "\n")
        (args.out / "packet.md").write_text(md)

    print(md, end="")
    return 0 if packet["verdict"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
