# M3 gate demo — operator runbook

**Machine 1** = this Mac. It hosts the platform: the Docker stack, the
connection to the customer database, the knowledge base.
**Machine 2** = the Windows PC. It plays the customer's analyst. It gets
a web address and a login and nothing else.

Read the whole page once before starting. Every command below is given
for both machines' shells, labelled — do not paste a macOS line into
PowerShell, several will silently do the wrong thing.

---

## 1. What this demo proves

That a person on a different computer, holding nothing but a login, can
ask a question in plain English and get a **published report built from
the customer's real data** — with the platform refusing, in public and
on the record, anything it cannot ground in documented facts.

Four specific claims, one per act:

| Act | Claim | Runs on |
|---|---|---|
| 1 | A plain-English question becomes checked SQL, returns **real rows**, and publishes as a working Looker Studio link | Machine 2 |
| 2 | Two different data sources are combined **only on a join the knowledge base documents**, pointing at the doc that authorises it | Machine 2 |
| 3 | Two things the platform must refuse — publishing somewhere the profile does not allow, and joining two sources on a key nobody documented — are refused and recorded | Machine 2 |
| 4 | Everything above is in a tamper-evident audit trail under the reporter's name | Machine 1 |

The interesting evidence is as much the refusals as the successes. A
system that only ever says yes has not been tested.

## 2. Words used below

- **Reporter profile** — the customer-side role this demo acts as. It may
  read the knowledge base, check SQL, run queries against Supabase, and
  publish to Looker Studio. Nothing else. The server re-checks this on
  every single call; the client cannot widen it.
- **The knowledge base (KB)** — the customer's own git repository of
  documentation about their data. Machine-written pages carry facts;
  human-written pages carry meaning.
- **Grounding** — the agent may only assert things the KB says. If the KB
  does not settle a question, the honest answer is "gap", never a guess.
- **Seed case** — one of ten canned business questions (`RB-01` … `RB-10`)
  used as a standard workload. Act 1 runs `RB-01`; Act 3 uses `RB-08`.
- **Blend** — combining two data sources into one report. Only allowed on
  a key that an *entity document* in the KB explicitly records.
- **Template link** — how publishing works here: the platform builds a URL
  that opens a pre-made Looker Studio report pointed at the right data.
  Nothing exists in Looker until you click it.
- **Audit chain / ledger** — every tool call is recorded with who, what,
  and allowed-or-denied. Gaps the agent hits become tracked items.

## 3. Before you start

| Prerequisite | State |
|---|---|
| Reporting views live on the customer database | done — the five new views are applied and readable by the query-only role |
| Views documented in the KB (pull request #25) | merged — the machine-written pages and the data-flow graph both know them |
| Meaning written for those views (pull request #26) | merged — purposes, reporting notes, warnings |
| Reporter allowed to publish (pull request #23) | merged — confirmed live in the server's own tool list |
| Looker Studio template registered | done — template `00000000-0000-0000-0000-000000000000`, five chart kinds declared |
| Passwords and keys rotated | done — which is what permits exposing this stack to the local network |
| Dates come back as text, not crashes | done — a fault that killed the job runner on any date column is fixed |
| **`entities/page.md` certified** | **YOURS — must be merged before Act 2.** Act 2 blends on the page mapping in that document; certifying it is a real verification act, not a status edit |

If the certification PR is not merged, run Acts 1, 3 and 4 and come back
for Act 2 — do not run Act 2 against a draft and call it certified.

---

## 4. Machine 1 — prepare the host

### 4.1 Confirm the stack is up and reachable

*macOS · machine 1:*

```bash
curl -s http://192.168.1.4:8100/healthz
```

*Windows PowerShell · machine 2 (same check, from the other side — this
is also step 5.1's reachability test):*

```powershell
curl.exe -s http://192.168.1.4:8100/healthz
```

> In PowerShell, `curl` is an **alias for `Invoke-WebRequest`**, which
> takes different flags and returns an object rather than text. Always
> type `curl.exe` when you want the real curl.

Expect JSON containing `"mcp_enabled":true` and `"sync_enabled":true`.

### 4.2 Confirm the runner will actually serve queries

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
docker compose logs runner | grep -i "execution preflight" | tail -1
```

*Windows PowerShell · machine 2:* nothing to run — the stack lives only
on machine 1.

Expect: `execution preflight passed for postgres: {'role': 'contextlayer_exec', …}`

If it says **FAILED**, the runner is deliberately refusing to serve
queries because the database role it was given is too powerful. That is
a safety check working. **Abort the demo and fix the role** — queries
will otherwise hang until they time out, with no useful error.

### 4.3 If the stack needs restarting

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
set -a; . .secrets/sync.env; set +a
SYNC_PLATFORM_COMMIT=$(git rev-parse HEAD) CORE_MCP_ENABLED=1 \
CL_BIND=0.0.0.0 CL_HOST_ADDR=192.168.1.4 \
  docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d
```

*Windows PowerShell · machine 2:* nothing to run.

Two of those settings matter and are easy to get wrong:
`CL_BIND=0.0.0.0` is what makes the ports answer from another computer;
`CL_HOST_ADDR=192.168.1.4` is what makes the login redirect point at an
address machine 2 can resolve. Getting the second wrong looks like a
login page that hangs forever on `localhost`.

The `set -a; . .secrets/sync.env; set +a` line is not decoration.
Without it the stack starts healthy with syncing silently switched off —
that exact mistake left the platform quietly not syncing for two days.

### 4.4 Record the start time

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

Write it down. Example: `2026-07-27T15:20:00Z`.

### 4.5 Build the customer's setup bundle

The platform compiles a profile into a ready-to-use Claude Code setup:
the connection config, a short instruction file, and the report skill.
Skills come from the product image, never from the customer's KB.

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject/core
node dist/cli.js compile reporter --kb ~/Desktop/kb --url http://192.168.1.4:8100 --out ~/reporter-setup
```

*Windows PowerShell · machine 2:* nothing to run — the bundle is built
on machine 1 and copied across in step 5.2.

Expect three files: `.mcp.json`, `CLAUDE.md`,
`.claude/skills/report/SKILL.md` (about 13 KB).

> **Build it in your home folder, not on the Desktop.** macOS protects
> `~/Desktop`, `~/Documents` and `~/Downloads` from remote sessions, so
> an SSH copy out of any of them fails with `Permission denied` even
> though the files are plainly there and you own them. `~/reporter-setup`
> sidesteps that entirely. (Granting the SSH daemon Full Disk Access in
> Privacy & Security would also work, and is a much bigger permission to
> hand out for one file copy.)

---

## 5. Machine 2 — set up the reporter's laptop

### 5.1 Check you can reach the platform

Run the PowerShell command in 4.1. If it does not answer: both machines
on the same network, and machine 1 awake (a sleeping Mac drops the
ports).

### 5.2 Copy the bundle across

Machine 2 is Windows, so AirDrop is not available. Windows 10 and 11
include an OpenSSH client, so `scp.exe` works once machine 1 allows it.

**On machine 1 first:** System Settings → General → Sharing → turn on
**Remote Login**. Turn it off again after the demo.

*Windows PowerShell · machine 2:*

```powershell
scp.exe -r alpercamli@192.168.1.4:reporter-setup "$HOME\cp7-demo"
```

*macOS · machine 1 (equivalent, if you prefer to push rather than pull —
replace the Windows username and address):*

```bash
scp -r ~/reporter-setup <windows-user>@<machine-2-ip>:cp7-demo
```

Two things about that command are deliberate:

- **The remote path has no `~/` and no `Desktop/`.** `scp` starts in your
  home folder already, and the bundle is built there (step 4.5) because
  macOS blocks remote reads of the Desktop.
- **It copies the folder, not `folder/*`.** Two of the three items are
  hidden files — `.mcp.json` and `.claude/` — and a `*` never matches
  names beginning with a dot. `scp -r dir/*` would have copied only
  `CLAUDE.md`, succeeded without complaint, and left the session with no
  server connection and no skill. Copy the folder itself and everything
  comes across.
- Do **not** create `cp7-demo` first. `scp` makes it as a copy of the
  source; if it already exists you end up with
  `cp7-demo\reporter-setup\` and have to `cd` one level deeper.

If you would rather not enable Remote Login at all, any method that puts
those three items in `%USERPROFILE%\cp7-demo` is fine — a USB stick, a
shared folder, OneDrive. Nothing in the bundle is secret: it contains no
password and no token. Whatever you use, **check the hidden files
arrived** — many copy tools skip them by default too.

### 5.3 Verify all three items arrived

A half-copied bundle is the failure mode to catch here: the hidden files
are the ones that carry the server connection and the procedure, and
copy tools skip hidden files quietly.

*Windows PowerShell · machine 2:*

```powershell
Get-ChildItem "$HOME\cp7-demo" -Force -Recurse | Select-Object FullName, Length
(Get-Item "$HOME\cp7-demo\.claude\skills\report\SKILL.md").Length
Get-FileHash "$HOME\cp7-demo\.claude\skills\report\SKILL.md" -Algorithm SHA256 | Select-Object -ExpandProperty Hash
```

`-Force` is what makes `Get-ChildItem` list hidden entries — without it
the output looks convincingly like one file is all there ever was.

*macOS · machine 1 (compare against these):*

```bash
ls -la ~/reporter-setup
wc -c < ~/reporter-setup/.claude/skills/report/SKILL.md
shasum -a 256 ~/reporter-setup/.claude/skills/report/SKILL.md
```

You need all three present — `.mcp.json` (136 bytes), `CLAUDE.md` (906),
`.claude/skills/report/SKILL.md` (13232) — and the skill's byte count
and hash must match across the two machines. (PowerShell prints the hash
in uppercase, macOS lowercase; same value.)

### 5.4 Start the session and log in

*Windows PowerShell · machine 2:*

```powershell
cd "$HOME\cp7-demo"
claude
```

*macOS · machine 1:* nothing to run — machine 1 is the host, not the
customer.

A browser opens to the demo login provider. Sign in as
**`reporter`** / **`reporter-dev-pw`**.

This login provider is for development only. A real customer deployment
points at their own company sign-on and this becomes their normal login
screen.

Two practical notes: the login must happen in a browser **on machine 2**
(the address only resolves on this network), and the session token lasts
one hour — if the demo runs long, re-run `claude` and log in again rather
than debugging strange failures.

`cp7-demo` is deliberately a folder of its own, not a copy of the
platform's source. A session started inside the platform repository
would absorb the platform's own instructions and stop being a customer
demo.

---

## 6. Act 1 — question to published report

**Purpose:** show the whole path working on real data: plain question →
checked SQL → real rows → a link that opens a report.

**Runs on:** machine 2, in the `claude` session.

**Paste these, one at a time.** Do not name the view — the point is that
the agent finds it.

> What do we know about user signups over time?

> Give me daily new signups for the last 90 days.

> Publish that as a Looker Studio report.

**What you should see if it worked**

1. The agent searches the KB and reads the page for the signups view. It
   should show a **trust block**: the document's status, when it was last
   verified, and which data snapshot it reflects. It should also relay
   the warning that days with no signups are missing rather than zero.
2. It checks the SQL first (`validate_sql` → `verdict: pass`) and only
   then runs it. **Real rows come back** — dates like `"2026-07-23"` with
   a count beside them. This is the headline: until the reporting views
   existed, this query returned nothing at all, because the underlying
   table hides every row from this account.
3. Publishing returns a **URL**, plus a short list of steps a human still
   has to complete in Looker Studio. That is normal for template links —
   nothing exists in Looker until a person clicks.

**Then open the link in a browser.**

**What to record**

- The full Looker Studio URL.
- **For each data source in the report: did Looker fill it in, or did it
  ask you to complete a field?** If it asked, write down *exactly which
  field*, word for word. The platform builds that URL using parameter
  names published by Google; if Google renamed one, Looker quietly falls
  back to asking the human. That is not a failure — but which field asked
  is a finding we need.
- Which chart kinds the report actually rendered, out of the five the
  template declares: table, line, bar, scorecard, pivot.
- A screenshot of the opened report.

**If it fails:** if rows come back empty, stop — that means the query ran
against the base table rather than a reporting view, and Act 2 onward
will be meaningless. If publishing errors, capture the error text
verbatim before retrying; a retry can hide the first failure's cause.

## 7. Act 2 — combining two sources, only where documented

**Purpose:** show that a cross-source join is allowed **because a
document authorises it**, not because the agent judged it sensible.

**Runs on:** machine 2. **Requires the `entities/page.md` certification
PR to be merged.**

Background: search data (Google Search Console) and analytics data
(GA4) both describe web pages, and the KB's page document records that
Search Console's `page` and GA4's `pagePath` identify the same thing.
That mapping is the permission slip.

**Paste:**

> Compare search impressions and pageviews for our top landing pages,
> blended by page.

**What you should see if it worked**

- The report is built from two sources, joined on `page` ↔ `pagePath`.
- The join cites the entity document — you can open the page it names and
  read the same mapping yourself.
- It publishes. Neither source is queried by the agent: the reporter is
  only allowed to run queries against Supabase, and Looker pulls Search
  Console and GA4 itself. The request is still checked end to end.
- If the certification PR is merged, the document it cites reads
  `verified`; the agent may only claim certification the KB actually
  granted.

**What to record:** the published URL, the entity document named in the
blend, and whether its status showed as verified.

**If it fails:** a refusal here that names a *missing* key means the
certification PR changed the mapping — stop and re-read the document
rather than rewording the prompt until it passes.

## 8. Act 3 — the two refusals

**Purpose:** show the platform refusing, server-side and on the record,
rather than relying on the agent's good manners.

**Runs on:** machine 2.

### 8a — publishing somewhere the profile does not allow

**Paste:**

> Publish that same report to Google Sheets instead.

**Expect:** a permission refusal. The reporter is allowed to publish to
Looker Studio and nowhere else. The refusal must come from the **server**
— it lands in the audit trail as `denied`. The agent should say so
plainly and should *not* speculate about other places it might publish,
because it cannot see them.

### 8b — joining on a key nobody documented

**Paste:**

> Blend the GA4 purchase count with our new subscriptions so I can see
> them per transaction.

**Expect:** a refusal that **names the documented keys** and stops. The
KB's conversion document is explicit that no shared row-level key exists
between a GA4 conversion and a subscription row — GA4 carries no user
id, and subscriptions store no GA4 identifier. The agent should then file
a gap (`missing_join_path`), which becomes a tracked item.

This is the most important minute of the demo. The honest answer to that
question is "you cannot join these", and the platform gives it instead of
inventing a plausible key.

**What to record:** both refusal messages, verbatim.

**If it fails:** if either succeeds instead of refusing, **stop the demo**
— a publish that should have been denied is a gate failure, not a
curiosity. Keep the output.

## 9. Act 4 — collect the evidence

**Purpose:** turn the demo into committed evidence.

**Runs on:** machine 1, after machine 2 is finished.

*macOS · machine 1* (use the timestamp from 4.4):

```bash
cd ~/Desktop/DataProject
results/cp7-gate/extract-audit.sh '2026-07-27T15:20:00Z'
```

*Windows PowerShell · machine 2:* nothing to run — the audit trail lives
in machine 1's database.

Writes four files beside the script. They are direct dumps of what the
server recorded, not a summary anyone wrote afterwards.

**Check before committing:**

- every row names `reporter` as the subject;
- Act 1 appears as check → run → publish, all allowed, with the SQL text
  stored;
- **two `denied` rows** from Act 3;
- `ledger-events.txt` contains the `missing_join_path` gap, cross-
  referenced to the matching audit row.

Then send me: the start timestamp, the Looker URL, the fields Looker
asked you to complete, the chart kinds rendered, and the two refusal
messages. I will write the gate note and close M3.

---

## 10. Notes on scope

- **Act 2 is deliberately not one of the ten seed cases.** The two
  cross-source seed cases are exactly the ones whose entity documents
  conclude that no shared key exists. Publishing them blended would
  fabricate a join the KB forbids, so the demo instead blends where the
  KB documents a join (the page mapping) and refuses where it does not
  (Act 3b, using seed case `RB-08`). Showing both is stronger evidence
  than showing either.
- **The seed packet is left frozen** even though one of its notes is now
  known to be wrong (it says a status column has no database constraint;
  it does). It is the fixed input a future measurement baseline will be
  compared against, so it gets corrected in one recorded pass when that
  baseline is revived, not piecemeal today. It does not affect this demo.
- **No suppression threshold for small numbers exists yet.** The estate
  has about two dozen users, so a count of 1 can identify a person. Every
  reporting document warns about this, nothing enforces it, and that is
  deliberate: the decision is due before any report reaches an audience
  outside the team. The audience for this demo is you.
