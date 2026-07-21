# Baseline v1 — go/no-go preflight

**Verdict: GO**  ·  generated 2026-07-21T16:59:56.617974Z
  ·  model `claude-opus-4-8`  ·  transport `benchmark-skill-v1`

## Checks

| ✓ | Check | Detail |
|---|---|---|
| ✅ | smoke journey completed | case=RB-01 condition=enriched-kb backend=benchmark-skill-v1 drafts=3 cost_usd=0.686128 |
| ✅ | smoke journey reached execution | 3 of 3 draft(s) executed |
| ✅ | enriched-kb: reachable | http://127.0.0.1:8100 |
| ✅ | enriched-kb: sync disabled | sync_enabled=False |
| ✅ | enriched-kb: MCP armed | mcp_enabled=True |
| ✅ | enriched-kb: kb_ref resolved | kb_ref=14fe1e60cee0c003ba104750ea4e85c1e939f9b4 |
| ✅ | machine-kb: reachable | http://127.0.0.1:8101 |
| ✅ | machine-kb: sync disabled | sync_enabled=False |
| ✅ | machine-kb: MCP armed | mcp_enabled=True |
| ✅ | machine-kb: kb_ref resolved | kb_ref=af1469e0274cd4e8ab1c0d50661a44243a8d05fc |
| ✅ | no-kb: reachable | http://127.0.0.1:8102 |
| ✅ | no-kb: sync disabled | sync_enabled=False |
| ✅ | no-kb: MCP armed | mcp_enabled=True |
| ✅ | no-kb: kb_ref resolved | kb_ref=456d8cc64cc7cb7bd61c516b719377fa7c38f897 |
| ✅ | the conditions serve distinct KBs | 3 distinct kb_ref across 3 instances |

## R8 keys

| Condition | kb_ref | remote |
|---|---|---|
| `enriched-kb` | `14fe1e60cee0c003ba104750ea4e85c1e939f9b4` | https://github.com/AlperCamli/DataAnalyticsTool.git |
| `machine-kb` | `af1469e0274cd4e8ab1c0d50661a44243a8d05fc` | https://github.com/AlperCamli/cl-baseline-machine-kb.git |
| `no-kb` | `456d8cc64cc7cb7bd61c516b719377fa7c38f897` | https://github.com/AlperCamli/cl-baseline-nokb.git |
