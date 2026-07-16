# OPERATOR — CP-2 manual baseline (interactive Claude Code)

You are the human transport for the CP-2 baseline: one **fresh interactive
Claude Code session per journey** (subscription-billed), execution through the
`benchmark.mcp_executor` MCP server, records to files, scoring by the
deterministic harness. The full grid is **10 cases × 3 conditions × 3 reps =
90 journeys** (`RB-01`…`RB-10` × `no-kb` / `machine-kb` / `enriched-kb` ×
reps `0,1,2`). Model pin: **`claude-opus-4-8`** — never start a session
without `--model claude-opus-4-8`.

A journey is **valid** only if: the session was fresh (no `--continue` /
`--resume`), you sent exactly one message (the pasted prompt), you never
steered (one sanctioned nudge allowed, see §4), and the journey log was a new
file. Anything else: void it (`rm` the `.jsonl`) and rerun the same rep.

## 1. One-time setup

```sh
cd $HOME/Desktop/DataProject
make conditions            # builds ~/Desktop/cp2-runs/{no-kb,machine-kb,enriched-kb}
```

This builds, per condition, ONLY: an identical `.mcp.json`, an empty
`records/`, and for the two KB conditions the condition's KB under `./kb`
(machine-kb rendered deterministically from the pinned snapshots; enriched-kb
exported from `~/Desktop/kb` at a pinned commit). It records `kb_ref`s and
`snapshot_refs` in `~/Desktop/cp2-runs/manifest.json` and preflights the
isolation invariants.

The runs root is deliberately **outside this repo**: interactive Claude Code
auto-loads `CLAUDE.md` from the cwd's directory ancestry, so condition dirs
under the repo would inhale the repo's `CLAUDE.md` into every session. The
builder refuses any root with a `CLAUDE.md` ancestor, a `~/.claude/CLAUDE.md`,
or stray files in a condition dir. Re-check any time with `make preflight`.

Rebuild (e.g. new enriched pin): `make conditions` + `--force` via
`.venv/bin/python -m benchmark.manual conditions --root ~/Desktop/cp2-runs --force`
— `records/` are preserved, but the manifest refs change, so don't mix
records across different builds.

## 2. Once per terminal

```sh
REPO=$HOME/Desktop/DataProject
source "$REPO/.secrets/env.sh"          # exports SUPABASE_DSN — never echo it
CLAUDE=$(ls -d ~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude | tail -1)
```

(`claude` is not on PATH on this machine; the VS Code extension binary is the
pinned launcher, per D-54. If you have a PATH install, `CLAUDE=claude` is fine
— keep the same binary for the whole baseline.)

## 3. Per journey — exact sequence

Example: case `RB-01`, condition `no-kb`, rep `0`. Substitute per journey;
the record filename convention is **`{case_id}.{condition}.{rep}.jsonl`**.

```sh
cd ~/Desktop/cp2-runs/no-kb                                    # the condition dir
export BENCHMARK_JOURNEY_LOG="$PWD/records/RB-01.no-kb.0.jsonl"   # RE-EXPORT EVERY JOURNEY
"$REPO/.venv/bin/python" -m benchmark.manual prompt --case RB-01 --condition no-kb | pbcopy
# (five pre-rendered starters live at ~/Desktop/cp2-runs/prompts/*.prompt.md —
#  `pbcopy < ../prompts/RB-01.no-kb.prompt.md` is equivalent for those)

"$CLAUDE" --model claude-opus-4-8 \
  --mcp-config .mcp.json --strict-mcp-config \
  --allowedTools "Read,mcp__executor" \
  --disallowedTools "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Task,TodoWrite,Grep,Glob"
```

Then, inside the session:

1. First launch in a dir only: accept the trust prompt; approve the
   `executor` MCP server if asked.
2. Paste (Cmd+V) the copied prompt as the **first and only message**. Enter.
3. Watch. The journey is done when the agent has called
   `mcp__executor__finish` and printed its answer.
4. `/exit`.

The `.mcp.json` reads `BENCHMARK_JOURNEY_LOG` and `SUPABASE_DSN` from your
shell at launch — a missing export fails the executor server loudly at
session start (by design). If the executor shows as failed, exit, fix the
exports, `rm` the log if one was created, and rerun.

## 4. Session conduct (per-journey autonomy)

- **Never** answer the agent's questions, confirm choices, or hint at
  tables/documents. The prompt tells it to proceed on stated assumptions.
- If it stalls or asks anyway, you may send **exactly one** nudge, verbatim,
  at most once per journey:
  > Proceed on your own stated assumptions and finish: execute the query that
  > answers the request, then call mcp__executor__finish. There is no user to
  > answer questions.
- Deny any permission request for tools outside `Read` + `mcp__executor`.
- Crash, rate-limit stop, second nudge needed, or wrong `BENCHMARK_JOURNEY_LOG`:
  the journey is void — `rm` its `.jsonl` and rerun the same rep in a fresh
  session (after the rate-limit window, if that was the cause).
- Run journeys in any order; case-major (all of RB-01, then RB-02…) matches
  how the automated baseline runs and makes progress easy to track.

## 5. After sessions — ingest and check coverage

From the repo root, as often as you like:

```sh
make ingest     # records/*.jsonl -> {case_id}.{condition}.{rep}.json (R3 records)
make status     # coverage grid; shows missing (case, condition, rep) slots
```

Ingest validates each log (name convention, known case, single `finish`) and
writes the R3 record next to it with the fields this transport cannot measure
(tokens, cost, session id) as null. It never overwrites without `--force`.

## 6. Scoring — the exact command

```sh
make score      # == .venv/bin/python -m benchmark.manual score --root ~/Desktop/cp2-runs --out results
```

This validates every record (filename↔content match, condition↔directory
match, no duplicates, one backend), verifies the condition dirs are unchanged
since the build (tree hashes vs `manifest.json`; drift refuses to score),
executes each present case's **golden legs once live** (R5 same-run
correctness — needs `.secrets/`), scores selection/executable/correctness
(R4–R6; selection is parser-extracted from the executed statements in the
record, never the agent's declared list), and writes
`results/<run-id>/results.json` + `report.md` (R8/R9, backend
`claude-code-interactive`). Offline dry-run: add `--no-golden` (correctness
unscored).

## 7. Redlines

- Never commit or copy `~/Desktop/cp2-runs/` into the repo — journey logs and
  records carry raw customer rows. `results/<run-id>/` is sanitized
  (checksums, no row values) and is what gets committed.
- Never echo `SUPABASE_DSN` or paste `.secrets/` contents anywhere (JC-8).
- Never edit records, logs, or the `kb/` trees by hand; `score` verifies the
  trees against the manifest and refuses drift.
- Don't run journeys while `make conditions --force` is mid-rebuild.
