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

1. **The smoke journey completed** — one journey end-to-end as proof the
   loop works before thirty are run through it.
2. **Sync is off on every condition instance.** Three schedulers sharing
   one queue and pushing sync PRs at scratch repos is the failure mode
   D-75.4 names; the production core stays the sole sync writer.
3. **The three instances serve three different KBs.** If two instances
   resolve to the same `kb_ref`, the conditions are not distinct and the
   run would report a difference it never created.
4. **The R8 keys are recorded** — condition name → kb_ref → profile — so
   the results artifact can be keyed and the owner can check what was
   actually served.

**Cost is out of scope here (ruling D-77).** AI usage cost is the
operating user's responsibility, in development and in the product alike:
skills run in the customer's own Claude Code under their licenses, and the
platform ships no model, no keys, and no billing management. The preflight
gates nothing on cost. `cost_usd` stays a recorded field in journey
records, informational only — absent stays absent, never coerced to zero.

This module is deliberately outside `benchmark/`: the CP-5 fence keeps
the CP-2 harness byte-unchanged, and this is new CP-5 tooling.
"""

from __future__ import annotations

import argparse
import json
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


def check_smoke(smoke_record: Path | None) -> list[Check]:
    """The smoke journey: one journey end-to-end before thirty.

    This gates on the loop working, not on what it cost. Per D-77, cost is
    the operating user's responsibility and nothing here blocks on it —
    ``cost_usd`` is reported alongside for the record and gates nothing.
    """
    if smoke_record is None:
        return [Check("smoke journey completed", False, "no --smoke-record given; run one journey first")]

    try:
        record = json.loads(smoke_record.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [Check("smoke journey completed", False, f"unreadable: {exc}")]

    drafts = record.get("drafts") or []
    executed = [d for d in drafts if d.get("executed")]
    cost = record.get("cost_usd")

    return [
        Check(
            "smoke journey completed",
            bool(drafts),
            f"case={record.get('case_id')} condition={record.get('condition')} "
            f"backend={record.get('backend')} drafts={len(drafts)}"
            # Informational only (D-77.3): absent stays absent.
            f" cost_usd={cost!r}",
        ),
        Check(
            "smoke journey reached execution",
            bool(executed),
            f"{len(executed)} of {len(drafts)} draft(s) executed"
            + ("" if executed else " — the loop did not close end-to-end"),
        ),
    ]


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
    ap.add_argument("--skip-smoke", action="store_true", help="probe instances only")
    ap.add_argument(
        "--smoke-record",
        type=Path,
        help="journey record from the one smoke journey (end-to-end proof of the loop)",
    )
    args = ap.parse_args(argv)

    probes: list[InstanceProbe] = []
    for spec in args.instance:
        if "=" not in spec:
            ap.error(f"--instance expects CONDITION=URL, got {spec!r}")
        condition, url = spec.split("=", 1)
        probes.append(probe_instance(condition, url))

    checks: list[Check] = []
    if not args.skip_smoke:
        checks += check_smoke(args.smoke_record)
    if probes:
        checks += check_instances(probes)
    if not checks:
        ap.error("nothing to check: pass --instance and/or drop --skip-smoke")

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
