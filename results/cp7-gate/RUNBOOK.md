# M3 gate demo — operator runbook (Power BI target)

**Machine 1** = this Mac. It hosts the platform: the Docker stack, the
connection to the customer database, the knowledge base.
**Machine 2** = the Windows PC. It plays the customer's analyst. It gets
a web address, a login, and a Power BI credential scoped to one
workspace — nothing else.

Read the whole page once before starting. Every command below is given
for both machines' shells, labelled — do not paste a macOS line into
PowerShell, several will silently do the wrong thing.

**What changed since the previous version of this runbook.** The
July 28 ruling replaced the demo's publishing target: the finish line
is no longer a Looker Studio template link that a human completes, but
a **finished report sitting in the customer's Power BI workspace** —
data delivered by the platform itself, charts designed by the AI in the
session, verified against what actually deployed, and a trust note
rendered inside the report. The Looker path remains on the shelf as a
secondary target; its Act-1 evidence from July 27 stands and is not
re-run. This version's Acts 2–4 are the ruling's amended gate. The
previous runbook is in git history if you need it.

---

## 1. What this demo proves

That a person on a different computer, holding nothing but a login, can
ask a question in plain English and end up with a **finished, working
report in the company's Power BI workspace** — no data source
configured by hand, no credential typed into a chart tool, no chart
built by a human — with the platform refusing, in public and on the
record, anything it cannot ground in documented facts.

Four specific claims, one per act:

| Act | Claim | Runs on |
|---|---|---|
| 1 | A plain-English question becomes checked SQL, returns **real rows**, and ends as an AI-designed, trust-annotated report **in the workspace**, with nothing left for a human except opening it | Machine 2 |
| 2 | Two different data sources are combined into one semantic model **only on a join the knowledge base documents** — and the model carries that join as a real relationship, citing the document that authorises it | Machine 2 |
| 3 | Two things the platform must refuse — publishing somewhere the profile does not allow, and joining two sources on a key nobody documented — are refused and recorded | Machine 2 |
| 4 | Everything above is in a tamper-evident audit trail under the reporter's name — including, per report, the **two** publish calls the new contract requires | Machine 1 |

The interesting evidence is as much the refusals as the successes. A
system that only ever says yes has not been tested.

## 2. Words used below

- **Reporter profile** — the customer-side role this demo acts as. It may
  read the knowledge base, check SQL, run queries against Supabase, and
  publish to Power BI (and, still, Looker Studio). Nothing else. The
  server re-checks this on every single call; the client cannot widen it.
- **The knowledge base (KB)** — the customer's own git repository of
  documentation about their data.
- **Grounding** — the agent may only assert things the KB says. If the KB
  does not settle a question, the honest answer is "gap", never a guess.
- **Push model** — the semantic model (dataset) the **platform** creates
  in the Power BI workspace and fills with the query results it executed
  itself, under the reporter's own guardrails. The session never touches
  the database; it never even sees a database password.
- **PBIR** — the report definition format. The AI writes it in the
  session with a small bundled tool, deploys it through Microsoft's API,
  and **reads it back** to prove what deployed is what was written.
- **Two-call publish** — how publishing works now. Call one
  (`deliver_model`) makes the platform validate everything, run the
  queries, and deliver the data. Call two (`attest`) happens only after
  the deployed report has been read back and verified, and writes the
  permanent record. A delivery that never reaches its attest shows up
  loudly in the operations listing — that state is designed to be
  impossible to miss.
- **Trust element** — a footer the AI must render inside the report
  carrying the KB's warnings about the data, the report's artifact id,
  and the date. The rule exists because chat scrollback dies and the
  report is the only thing every viewer sees.
- **Audit chain / ledger** — every tool call is recorded with who, what,
  and allowed-or-denied. Gaps the agent hits become tracked items.

## 3. Before you start

| Prerequisite | State |
|---|---|
| Reporting views live on the customer database | done — the five views are applied and readable by the query-only role |
| Views documented in the KB (pull request #25) and given meaning (#26) | merged |
| Entra app + service principal, workspace membership, tenant settings | done — `make powerbi-preflight` passed all five checks on July 29 |
| The Power BI leg proven against the real services | done — a live model + report were delivered, verified, attested, and revised on July 29 (`results/cp7-powerbi-live/evidence.json`); two Microsoft-side surprises were found and fixed there rather than here |
| Platform stack rebuilt with the Power BI leg (step 4.2) | **do during prep** |
| Power BI connection registered on the stack (step 4.4) | **do during prep** |
| Reporter profile allows Power BI publishing | **YOURS — a KB pull request** adding `publish_report:powerbi` to `profiles/reporter.yaml` must be merged before Act 1, same review path as every KB change |
| `entities/page.md` certified | **YOURS — must be merged before Act 2.** Act 2 blends on the page mapping in that document; certifying it is a real verification act, not a status edit |
| GA4 and Search Console registered with query-capable credentials | **confirm before Act 2** — Act 2's data is pulled by the platform through those connectors' own query paths, not by Looker; if the GA4 property is still unwired, run Acts 1, 3, 4 and return for Act 2 |
| Machine 2 has Python 3 | **check in step 5.4** — the AI's report-authoring tool is a single Python file with no dependencies |

---

## 4. Machine 1 — prepare the host

### 4.1 Rebuild for the new leg

The Power BI publisher lives in the runner image and the two-call
contract in the core image; both were built after the last stack start.

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
(cd core && npm run build)
docker compose build core runner
```

*Windows PowerShell · machine 2:* nothing to run — the stack lives only
on machine 1.

### 4.2 Give the runner the Power BI credential

The runner resolves the service principal's secret from its own
environment file; the registration carries only a **reference** to it.
This copies the one line across without ever printing the value:

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
grep -q '^POWERBI_CLIENT_SECRET=' .secrets/runner.env || \
  grep '^POWERBI_CLIENT_SECRET=' .secrets/powerbi.env >> .secrets/runner.env
grep -c '^POWERBI_CLIENT_SECRET=' .secrets/runner.env
```

Expect the final line to print `1`. If it prints `2` or more, the file
has duplicates — edit it down to one.

*Windows PowerShell · machine 2:* nothing to run.

### 4.3 Start the stack (new images, new migration)

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
set -a; . .secrets/sync.env; set +a
SYNC_PLATFORM_COMMIT=$(git rev-parse HEAD) CORE_MCP_ENABLED=1 \
CORE_MCP_PUBLISH_PER_HOUR=12 \
CL_BIND=0.0.0.0 CL_HOST_ADDR=192.168.1.4 \
  docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d
```

*Windows PowerShell · machine 2:* nothing to run.

Three settings matter and are easy to get wrong. `CL_BIND=0.0.0.0`
makes the ports answer from another computer. `CL_HOST_ADDR=192.168.1.4`
makes the login redirect resolvable from machine 2 — wrong, it looks
like a login page hanging on `localhost`. **`CORE_MCP_PUBLISH_PER_HOUR=12`
is new and demo-specific**: a Power BI report costs *two* publish calls
(deliver, then attest), and the default budget of four per hour would
strand Act 2 behind Act 1's revisions. Twelve covers the demo with
retries; drop the override after.

The `set -a; . .secrets/sync.env; set +a` line is not decoration.
Without it the stack starts healthy with syncing silently switched off —
that exact mistake once left the platform quietly not syncing for two
days.

The new database migration applies automatically on start; confirm with:

```bash
docker compose logs core | grep -i migrat | tail -2
```

### 4.4 Register the Power BI connection

The registration tells the platform where the workspace is and which
credential *reference* the runner should resolve. Fill the three ids
from `.secrets/powerbi.env` (they are ids, not secrets — the secret
itself stays out of this file):

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
. <(grep -E '^POWERBI_(TENANT|CLIENT|WORKSPACE)' .secrets/powerbi.env | sed 's/^/export /')
cat > /tmp/powerbi-connection.json <<EOF
{
  "system": "powerbi",
  "connector": { "name": "powerbi", "version_constraint": ">=0.1 <0.2" },
  "payload": {
    "config": {
      "system": "powerbi",
      "tenant_id": "$POWERBI_TENANT_ID",
      "client_id": "$POWERBI_CLIENT_ID",
      "workspace_id": "$POWERBI_WORKSPACE_ID"
    },
    "credentials": [
      { "ref": "env://POWERBI_CLIENT_SECRET", "key": "client_secret", "required_for": ["publish"] }
    ],
    "publish": {
      "flags": {
        "create_report": "api", "create_dataset": "yes", "sql_backing": "views",
        "cross_source": "native", "scheduled_refresh": "no", "git_integration": "no"
      }
    }
  }
}
EOF
docker compose exec core node dist/cli.js sync systems set /tmp/powerbi-connection.json \
  || (cd core && node dist/cli.js sync systems set /tmp/powerbi-connection.json)
rm /tmp/powerbi-connection.json
```

*Windows PowerShell · machine 2:* nothing to run.

The `publish.flags` block is what tells the server this target uses the
two-call contract; without it, `mode` is rejected and Act 1 cannot
publish.

### 4.5 Final host checks

*macOS · machine 1:*

```bash
curl -s http://192.168.1.4:8100/healthz
make powerbi-preflight
docker compose logs runner | grep -i "execution preflight" | tail -1
```

*Windows PowerShell · machine 2 (reachability from the far side — this
doubles as step 5.1):*

```powershell
curl.exe -s http://192.168.1.4:8100/healthz
```

> In PowerShell, `curl` is an **alias for `Invoke-WebRequest`**. Always
> type `curl.exe` when you want the real curl.

Expect: healthz JSON with `"mcp_enabled":true`; all five preflight
checks `ok`; `execution preflight passed for postgres`. If the runner
preflight says **FAILED**, it is deliberately refusing to serve queries
because the database role is too powerful — abort and fix the role.

### 4.6 Record the start time

Everything the evidence extractor collects is "since this moment", so
capture it **before machine 2 does anything**.

*macOS · machine 1:*

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
```

*Windows PowerShell · machine 2 (if you would rather read it there):*

```powershell
(Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
```

Write it down. Example: `2026-07-29T15:20:00Z`.

### 4.7 Build the customer's setup bundle

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject/core
node dist/cli.js compile reporter --kb ~/Desktop/kb --url http://192.168.1.4:8100 --out ~/reporter-setup
```

Expect **four** files now — `.mcp.json`, `CLAUDE.md`,
`.claude/skills/report/SKILL.md`, and
`.claude/skills/report/pbir_tool.py`. The last one is new: it is the
AI's report-authoring tool, and it rides the bundle so the session
needs nothing installed beyond Python itself.

> **Build it in your home folder, not on the Desktop.** macOS protects
> `~/Desktop` from remote sessions, so an SSH copy out of it fails with
> `Permission denied` even though you own the files.

---

## 5. Machine 2 — set up the reporter's laptop

### 5.1 Check you can reach the platform

Run the PowerShell command in 4.5. If it does not answer: both machines
on the same network, and machine 1 awake (a sleeping Mac drops the
ports).

### 5.2 Copy the bundle across

**On machine 1 first:** System Settings → General → Sharing → turn on
**Remote Login**. Turn it off again after the demo.

*Windows PowerShell · machine 2:*

```powershell
scp.exe -r alpercamli@192.168.1.4:reporter-setup "$HOME\cp7-demo"
```

*macOS · machine 1 (equivalent push, if you prefer):*

```bash
scp -r ~/reporter-setup <windows-user>@<machine-2-ip>:cp7-demo
```

Copy **the folder, not `folder\*`** — two of the items are hidden
(`.mcp.json`, `.claude\`) and a `*` never matches dot-names; the copy
would "succeed" and leave the session with no server connection, no
skill, and no tool. Do **not** create `cp7-demo` first; `scp` makes it.

### 5.3 Verify all four items arrived

*Windows PowerShell · machine 2:*

```powershell
Get-ChildItem "$HOME\cp7-demo" -Force -Recurse | Select-Object FullName, Length
Get-FileHash "$HOME\cp7-demo\.claude\skills\report\pbir_tool.py" -Algorithm SHA256 | Select-Object -ExpandProperty Hash
```

*macOS · machine 1 (compare against):*

```bash
ls -la ~/reporter-setup/.claude/skills/report/
shasum -a 256 ~/reporter-setup/.claude/skills/report/pbir_tool.py
```

`-Force` is what makes PowerShell list hidden entries. The tool's hash
must match across machines (PowerShell prints uppercase, macOS
lowercase; same value).

### 5.4 Check Python and set the session's Power BI credential

The authoring tool needs Python 3 (any recent one; it uses nothing
outside the standard library):

*Windows PowerShell · machine 2:*

```powershell
python --version
```

If that opens the Microsoft Store instead of printing a version,
install "Python 3.12" from the Store once, then re-check.

Then give the session its Power BI identity — the service principal,
scoped to the one demo workspace and nothing else. Type the three
values from the operator's secret store **into the shell, not into any
file**; they die with the window:

```powershell
$env:POWERBI_TENANT_ID    = "<tenant id>"
$env:POWERBI_CLIENT_ID    = "<app client id>"
$env:POWERBI_CLIENT_SECRET = "<client secret value>"
```

*macOS · machine 1 (only if you ever run the session locally instead):*

```bash
export POWERBI_TENANT_ID="<tenant id>" POWERBI_CLIENT_ID="<app client id>" POWERBI_CLIENT_SECRET="<client secret value>"
```

Note what this credential is **not**: it is not a database password —
no database credential exists anywhere on machine 2, which is one of
the claims Act 4's audit backs up. It opens exactly one Power BI
workspace, as a member.

### 5.5 Start the session and log in

*Windows PowerShell · machine 2 (same window as 5.4 — the variables
must still be set):*

```powershell
cd "$HOME\cp7-demo"
claude
```

A browser opens to the demo login provider. Sign in as
**`reporter`** / **`reporter-dev-pw`**.

The login must happen in a browser **on machine 2**, and the session
token lasts one hour — if the demo runs long, re-run `claude` and log
in again rather than debugging strange failures. `cp7-demo` is
deliberately its own folder: a session started inside the platform
repository would absorb the platform's instructions and stop being a
customer demo.

---

## 6. Act 1 — question to finished report

**Purpose:** the whole amended gate in one act: plain question →
checked SQL → real rows → the platform delivers the data into the
workspace → the AI designs and deploys the report → verifies it → and
the permanent record is written. Zero manual wiring, measured: you
configure no data source, enter no credential into any chart tool, and
build no chart.

**Runs on:** machine 2, in the `claude` session.

**Paste these, one at a time.** Do not name the view — the point is
that the agent finds it.

> What do we know about user signups over time?

> Give me daily new signups for the last 90 days.

> Publish that as a Power BI report.

**What you should see if it worked**

1. The agent searches the KB and reads the page for the signups view,
   showing a **trust block** (status, last verified, which snapshot),
   and relays the warning that days with no signups are missing rather
   than zero.
2. It checks the SQL first (`validate_sql` → pass) and only then runs
   it; **real rows** come back.
3. After you confirm the numbers, publishing runs as a visible
   sequence, not one opaque step: a **deliver** call that returns the
   delivered table schema; the agent generating the report definition
   with the bundled tool; a **deploy**; a **verify** that reads back
   what deployed and confirms it matches; then the **attest** call that
   returns the report's workspace URL.
4. The chart choice should respect the data's shape: daily signups with
   missing days must NOT render as a smooth line unless the view
   provides a gapless calendar — bars with a note is the honest answer.
   (The design rules the AI works under make that a rule, not taste.)
5. `pending_human_steps` is **empty or exactly "open the report"** —
   that emptiness is the gate's number-one measure. Anything more
   listed there is a finding.

**Then open the URL in a browser on machine 2** (sign in with the demo
Microsoft account that can view the workspace). The report is already
finished: charts rendered, and a **trust footer** on the page carrying
the KB's warnings, the artifact id, and the date.

**What to record**

- The report URL and the UTC time you opened it.
- Whether `pending_human_steps` was `[]` or `["open the report"]` —
  verbatim.
- Which visual kinds the AI chose, and whether the spine rule was
  respected (bars vs line for gappy dailies).
- The trust footer's text as rendered in the report — photo or
  screenshot.
- The `verified: true` line (with the definition hash) from the
  verify step in the transcript.

**If it fails:** if rows come back empty, stop — the query ran against
the base table rather than a reporting view, and everything after is
meaningless. If **verify** fails twice, stop and keep the transcript —
never let the agent attest unverified work; that refusal working is
itself evidence, but the demo cannot proceed on it. If publishing is
rate-limited, you have used the twelve-per-hour demo budget — wait, or
restart the stack with a higher override. A `401` from the Microsoft
side means the tenant's service-principal settings regressed — re-run
`make powerbi-preflight` on machine 1 and read its instructions.

## 7. Act 2 — one model, two sources, a documented relationship

**Purpose:** show that a cross-source combination is allowed **because
a document authorises it** — and that under the new target the
combination is structural: one semantic model holding both tables with
a real relationship on the documented keys, not two charts glued
side-by-side.

**Runs on:** machine 2. **Requires the `entities/page.md` certification
PR merged, and GA4 + Search Console registered for governed queries.**

Background: search data (Search Console) and analytics data (GA4) both
describe web pages, and the KB's page document records that Search
Console's `page` and GA4's `pagePath` identify the same thing. That
mapping is the permission slip — and this time the platform itself runs
both queries and delivers both result sets into one model.

**Paste:**

> Compare search impressions and pageviews for our top landing pages,
> blended by page, and publish it as a Power BI report.

**What you should see if it worked**

- The blend cites the entity document; its status reads `verified`
  (the agent may only claim certification the KB actually granted).
- The deliver step returns **two tables**, and the model carries a
  **relationship** between them on `page` ↔ `pagePath`.
- The report publishes through the same deliver → author → deploy →
  verify → attest sequence, and its trust footer names both sources.

**What to record:** the report URL; the entity document named in the
blend and its status; evidence of the relationship — either the
transcript's delivery summary naming it, or (nicer) open the model in
the workspace (Semantic model → Model view; Power BI Desktop on
machine 2 works too) and photograph the relationship line between the
two tables.

**If it fails:** a refusal naming a *missing* key means the
certification PR changed the mapping — stop and re-read the document
rather than rewording the prompt until it passes. If GA4's query path
is not wired, the deliver call will say which system failed — that is
the prerequisite row, not a platform fault.

## 8. Act 3 — the two refusals

**Purpose:** show the platform refusing, server-side and on the record,
rather than relying on the agent's good manners. The publishing target
changed; the honesty rules did not — these are the same two refusals
the previous version of this demo required, and they must behave the
same way.

**Runs on:** machine 2.

### 8a — publishing somewhere the profile does not allow

**Paste:**

> Publish that same report to Google Sheets instead.

**Expect:** a permission refusal from the **server** — it lands in the
audit trail as `denied`. The agent should say plainly what targets it
has and should *not* speculate about others, because it cannot see
them.

### 8b — joining on a key nobody documented

**Paste:**

> Blend the GA4 purchase count with our new subscriptions so I can see
> them per transaction.

**Expect:** a refusal that **names the documented keys** and stops. The
KB's conversion document is explicit that no shared row-level key
exists between a GA4 conversion and a subscription row. The agent then
files a gap (`missing_join_path`) and tells you who was notified.

This is the most important minute of the demo. The honest answer is
"you cannot join these", and the platform gives it instead of
inventing a plausible key.

**What to record:** both refusal messages, verbatim.

**If it fails:** if either succeeds instead of refusing, **stop the
demo** — a publish that should have been denied is a gate failure, not
a curiosity. Keep the output.

## 9. Act 4 — extract the evidence

**Purpose:** everything the demo claims, shown from the server's own
records rather than from prose.

**Runs on:** machine 1, after machine 2's session is finished.

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
results/cp7-gate/extract-audit.sh '<the UTC instant from step 4.6>'
```

*Windows PowerShell · machine 2:* nothing to run.

It writes the evidence files next to the script. Check, in
`audit-chain.txt` and `publish-trail.txt`:

- **Per published report, exactly two `publish_report` rows** — a
  `deliver_model` then an `attest`, both `allowed`, in that order, with
  the attested definition hash matching what Act 1/2's verify printed.
- The **attestation table** carries one row per report revision:
  artifact id, workspace, dataset, report id, definition hash — and no
  delivery is left dangling (a dangling one means a deliver whose
  report never verified; the ops listing `node dist/cli.js publish
  deliveries` prints it loudly if so).
- Act 3's rows: the Sheets publish as `denied`, the undocumented blend
  as a refusal plus a `flag_gap` with kind `missing_join_path`.
- Every row under the reporter's identity, with the full statement or
  artifact pin recorded for validate/execute/publish calls.

**What to record:** commit the generated files; note in the gate note
any row that surprised you, even if the demo passed.

---

## 10. After the demo (STOP-B)

The demo is yours: run it at your pace, record as you go, and stop at
any act whose success criteria are not met — the recorded transcript
of a refusal is worth more than a pushed-through pass.

When the acts are done, the gate closure needs: the recorded items from
each act, the committed Act-4 evidence, and your verdict. The platform
side then finishes the checkpoint bookkeeping (closure note, register
motions, the next checkpoint's entry list). Drop the
`CORE_MCP_PUBLISH_PER_HOUR` override and turn Remote Login off when
you are done.
