# A-2 — the second-human run (operator runbook)

**Machine 1** = this Mac. It hosts the platform: the Docker stack, the
connection to the customer database, the knowledge base, the dev
identity provider.
**Machine 2** = **your colleague's own computer**. It gets a web address
and a login that belongs to them. Nothing else — no file copied by you,
no credential typed by you, no folder you prepared.

Read the whole page once before starting. Commands are labelled by
machine and shell; do not paste a macOS line into PowerShell.

**What is different about this run.** Every demo so far was run by the
person who built the thing. This one is not, and that is the whole
point: the gate is not "a report was produced", it is "a second human
produced one, under their own identity, with the operator hands-off."
The friction they hit is the deliverable, equal in weight to the report.

---

## 1. What this run proves

| # | Claim | Runs on |
|---|---|---|
| 1 | A person who has never seen this system can get their own setup from a web address, authenticated as themselves — no file copied by the operator | Machine 2 |
| 2 | What they get is *their* profile's setup, decided by the server from their identity, and it carries no credential | Machine 1 (asserted by test) + Machine 2 |
| 3 | They complete a reporter journey of **their own choosing** with the operator silent throughout | Machine 2 |
| 4 | Every audit row for that journey carries **their** identity, not the operator's, not a shared one | Machine 1 |
| 5 | A setup that has gone out of date announces itself instead of quietly narrowing what the session will attempt | Machine 1 |

Claims 2 and 5 also have machine-checked halves that ran before this
page was written (`core/test/setup-bundle.test.ts`, 11 tests): canaries
planted in the compile's environment appear nowhere in the archive, and
the 2026-07-29 failure shape — compile, then grant a new tool, then
connect on the stale bundle — now produces a loud notice at connection
where it once produced silence. The live run is the human half.

## 2. Words used below

- **Setup / bundle** — the small archive the colleague downloads:
  server address, a `CLAUDE.md` describing what their role may do, and
  the skill files. No password, no token, no database anything.
- **Their identity** — an account in the pilot identity provider that is
  *theirs alone*. A shared login would void claim 4 entirely: the audit
  rows would say "reporter", which tells us nothing about whether a
  second human can use this.
- **Hands-off** — you may hand over two pages and answer nothing.
  "I'm not allowed to answer that" is the complete script.
- **Friction note** — one numbered observation of a place the product
  failed to explain itself. Written *during* the run, not reconstructed
  after it.

## 3. Before you start

| Prerequisite | How to check | State |
|---|---|---|
| Platform suites green | `cd core && npx vitest run` | done — **267 passed / 24 files** at this commit |
| The colleague has their own account in the identity provider | O-1 below | **do it now if not** |
| The colleague's machine has Claude Code installed | ask them the day before | if they install it during the run, that is a friction note, not a failure |
| Both machines on the same network; this Mac awake for the whole run | O-2 | a sleeping Mac drops the ports mid-run |
| The KB clone's contamination triage | separate operator item | **34 contaminated docs on `main`.** Not a blocker for this run — but if their journey touches a contaminated doc the session will say so, which is the product working. Record what they make of the message |
| Power BI credential, **only if** their journey ends in a published report | O-4 | you set the three variables *before* handing over, never during (see O-4) |

### 3.0 Rotate the dev IdP passwords before you bind to a network

**Do this first, every time, on any network you do not own.** The base
stack's account list, `deploy/oidc/users.json`, ships with the platform
release and is **published** (`AlperCamli/DataAnalyticsTool`) — with
`steward-dev-pw`, `reporter-dev-pw`, `benchmark-dev-pw` in it. The
moment the stack is bound to anything other than `127.0.0.1`, anyone who
can reach port 8180 and has read the public repo can sign in as the
steward: full KB read, the audit trail, and execution against the
customer database under the exec role.

**Since 2026-08-06 the live accounts live outside git** —
`.secrets/idp-users.json`, mounted over the published file by
`deploy/compose.live.yml`. That is also where the second human's account
belongs: a real person's credentials must not land in a repo, least of
all one that gets published.

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
$EDITOR .secrets/idp-users.json     # same JSON shape; rotated passwords
chmod 600 .secrets/idp-users.json
docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d devidp
# prove the published default no longer works:
curl -sS -X POST http://127.0.0.1:8180/token \
  -d grant_type=password -d username=alper -d password=steward-dev-pw
# expect {"error":"invalid_grant"}
```

On a campus, office, or hotspot network (a `10.x` or `172.16–31.x`
address) treat this as mandatory. Take the binding down again when the
run is over:

```bash
docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d   # CL_BIND unset ⇒ 127.0.0.1
```

A LAN you control (a home router) is lower risk but not zero — the
accounts are still published.

### 3.1 What you may not do

Once you hand over (O-4), you may not: type on their machine, read over
their shoulder and correct them, explain an error message, suggest a
question, or tell them what the tool "meant". If they ask, say you are
not allowed to answer and write down that they asked — **the question
they asked you is itself the finding**.

You may end the run at any point they want to stop.

---

## 4. Machine 1 — prepare the host

### O-1. Give the colleague their own identity

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
# Add ONE entry to the pilot IdP's user list — the git-ignored one
# (§3.0), never the published file. Use their real first name or
# handle: the audit rows carry this string, and "who used it" is the
# question those rows have to answer.
$EDITOR .secrets/idp-users.json
```

The new entry, beside the existing ones:

```json
  {
    "username": "<their-handle>",
    "password": "<a password you generate, not one you reuse>",
    "roles": ["reporter"],
    "display": "<Their Name>"
  }
```

Then restart just the identity provider and confirm the account exists
and carries exactly the reporter role:

```bash
docker compose restart devidp
sleep 2
curl -sS -X POST http://127.0.0.1:8180/token \
  -d grant_type=password -d username='<their-handle>' -d password='<their password>' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"][:12], "…")'
```

**Success criteria:** a token prints. The username is **not** `reporter`
and **not** `alper` — a shared login fails this checkpoint's gate
whatever else happens. The role list is exactly `["reporter"]`.

**What to record:** the username you created (it is the string the
evidence in step 7 filters on).

### O-2. Bring the stack up reachable from their machine

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
ipconfig getifaddr en0    # this Mac's LAN address — 10.22.88.149 on
                          # 2026-08-05. It is DHCP: re-check it on the
                          # day. The address is compiled into the bundle,
                          # so a bundle downloaded at one address stops
                          # connecting when the Mac gets another one.
# Use the make target, not a bare `docker compose up`: it sources
# .secrets/sync.env into the shell, which is the D-84.2 trap — an
# unexported env file yields a stack that looks healthy and never syncs.
# The rebuild is required this time: the download endpoint is new, and
# the image now has to carry the shipped skills it compiles from.
CL_HOST_ADDR=<that address> CL_BIND=0.0.0.0 CORE_MCP_ENABLED=1 make stack-live
curl -sS http://127.0.0.1:8100/healthz | python3 -m json.tool | head -20
```

Then confirm the new surface answers *before* anyone is waiting on it:

```bash
# Unauthenticated: a script gets 401, a browser gets sent to sign in.
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/v1/setup/bundle
curl -sS -o /dev/null -w '%{http_code}\n' -H 'accept: text/html' \
  http://127.0.0.1:8100/v1/setup/bundle
# Your own binding, as the steward — proves the compile works in the
# deployed image (it needs the skills the image now ships):
CL_TOKEN=$(curl -sS -X POST http://127.0.0.1:8180/token \
  -d grant_type=password -d username=alper -d password='<steward pw>' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -sS -H "authorization: Bearer $CL_TOKEN" http://127.0.0.1:8100/v1/setup/status |
  python3 -m json.tool
```

Expect `401` then `302`, and a status body naming profile `steward` with
a `setup_stamp`. A `503 setup_uncompilable` here means the image is
stale — rebuild before handing anything over.

The `instance.public_url` in that output must be
`http://<LAN address>:8100`. It is the address baked into the setup the
colleague downloads; if it says `localhost`, their session will point at
their own machine and nothing will connect.

*On the colleague's machine, before you hand anything over — ask them to
run this one line and read you the answer:*

*macOS/Linux · machine 2:* `curl -sS http://<LAN address>:8100/healthz`
*Windows PowerShell · machine 2:* `curl.exe -sS http://<LAN address>:8100/healthz`

**Success criteria:** `{"status":"ok"...}` on their screen. If it hangs,
fix the network before anything else — this is the one step where you
are still allowed to help.

**What to record:** nothing, unless it failed; then everything.

### O-3. Record the start instant

*macOS · machine 1:*

```bash
date -u +%Y-%m-%dT%H:%M:%SZ | tee results/phase2/a2/window-start.txt
```

**What to record:** that file is the evidence window's left edge. Do not
skip it — step 7 filters on it.

### O-4. Hand over

Give them, on paper or in a message:

1. `results/phase2/a2/COLLEAGUE-BRIEFING.md` (print it or paste it whole).
2. Section 5 of this page — the four colleague steps, nothing else.
3. The download address: **`http://<LAN address>:8100/v1/setup/bundle`**
4. Their username and password from O-1.

If — and only if — you expect their journey to end in a published Power
BI report, set the three publishing variables in the shell they will
start the session from, **before** they begin:

*Windows PowerShell · machine 2 (typed by them, dictated by you, values
from your secret store):*

```powershell
$env:POWERBI_TENANT_ID     = "<tenant id>"
$env:POWERBI_CLIENT_ID     = "<app client id>"
$env:POWERBI_CLIENT_SECRET = "<client secret value>"
```

This is a known rough edge, not a product step: a user should not need
an operator to dictate credentials. Record it as friction note #1 before
the run even starts — it is the honest first finding, and the vault work
that removes it is a later checkpoint.

**Then stop talking.** Sit where you can see and hear, with the notes
file open.

---

## 5. Machine 2 — the colleague's four steps

*(This is the section you hand over. It is written for them.)*

### C-1. Get your setup

Open this address in your browser:

```
http://<LAN address>:8100/v1/setup/bundle
```

You will be asked to sign in. Use the username and password you were
given — they are yours. A file called
`contextlayer-setup-reporter.tar.gz` downloads.

*Nothing to check here. If a file arrived, it worked.*

### C-2. Unpack it

*macOS/Linux:*

```bash
mkdir -p ~/contextlayer && cd ~/contextlayer
tar xzf ~/Downloads/contextlayer-setup-reporter.tar.gz
ls -la
```

*Windows PowerShell:*

```powershell
New-Item -ItemType Directory -Force "$HOME\contextlayer" | Out-Null
cd "$HOME\contextlayer"
tar -xzf "$HOME\Downloads\contextlayer-setup-reporter.tar.gz"
Get-ChildItem -Force -Recurse | Select-Object FullName
```

You should see `CLAUDE.md`, `.mcp.json` and a `.claude` folder. (The
names starting with a dot are hidden by default — that is why the
listing commands above force them to show.)

If your browser already unpacked the download for you, you may have a
`.tar` file or a folder in Downloads instead of the `.tar.gz`. Use
whichever you actually have — `tar xf …tar` for the first, or copy the
folder's contents (including the hidden ones) for the second. If that
sentence is annoying to follow, say so; that is a note worth having.

### C-3. Open the assistant

*macOS/Linux (from the same folder):*

```bash
claude
```

*Windows PowerShell (from the same folder):*

```powershell
claude
```

If it asks whether to trust the folder or approve a server called
`contextlayer`, say yes — that is the file you just downloaded. A
browser may open asking you to sign in again; same username and
password.

### C-4. Ask for what you want

Type your question in your own words. Anything you would actually want
to know from this company's data. If you are not sure where to start,
ask the assistant what it knows about and pick from its answer.

Then just have the conversation. Answer its questions with what you
really think. If it says it cannot do something, believe it and see
where you get to.

**Say out loud anything that confuses you, as it happens.** That is the
part we cannot get any other way.

Stop whenever you have what you wanted — or when you are stuck. Both are
fine.

---

## 6. During the run — the operator's real job

You are writing notes, not helping. Format, one per observation:

```
N. [hh:mm] SEVERITY — what happened, in their words where possible.
   What a user feels: <one sentence, from their side, not the system's>
```

Severities, same ladder as the CP-8 findings: **blocker** (they could
not continue without help), **major** (they continued but wrongly or
after a long stall), **minor** (a stumble they recovered from),
**observation** (a preference or a surprise worth knowing).

Write down, at minimum:

- every question they asked you that you had to refuse to answer;
- every silence longer than about thirty seconds, and what was on screen;
- every place they read something aloud in a puzzled tone — the exact
  words on the screen matter;
- anything they expected to happen that did not;
- what they *thought* the tool had done, at the end, versus what it did.

**Do not tidy these up during the run.** Timestamps and their phrasing
are the value; the CP-8 field-note style keeps the ugly ones unsmoothed.

**Per-act success criteria (yours to judge, at the end, not during):**

| Act | Pass |
|---|---|
| C-1 | The file arrived without you touching their machine |
| C-2 | They found the hidden files and knew the unpack worked |
| C-3 | The session started and connected to the platform |
| C-4 | A journey of their choosing reached an end they understood — a report, a documented refusal, or a clear "the data does not support this" |
| all | You said nothing but "I'm not allowed to answer that" |

A run where C-4 ends in a refusal the colleague *understood* is a pass.
A run where it ends in a report the colleague could not explain is not.

---

## 7. After the run (same day, before this session ends)

> **STANDING RULE — extract same-day.** The 2026-07-29 gate lost two
> acts to a two-day extraction delay: the evidence lived only in a
> running container, and two claims had to be reclassified NOT
> DEMONSTRATED when the rows were finally read. Extract, read the rows
> against the claims, and commit — that day, in that order.

*macOS · machine 1:*

```bash
cd ~/Desktop/DataProject
CL_IDP=http://127.0.0.1:8180 CL_USER='alper' CL_PASSWORD='<steward pw>' \
CL_OUT="$PWD/results/phase2/a2" \
  results/cp7-gate/extract-audit.sh "$(cat results/phase2/a2/window-start.txt)"
```

The extractor is a client of the platform's own governed read APIs, so
it holds no database credential — only your identity. Read the five
files it writes, and check:

- **every row in the window carries the colleague's username** in the
  subject column — not `reporter`, not `alper`. This is gate claim 4,
  and it is a string comparison, not a judgement call:

  ```bash
  cut -d'|' -f2 results/phase2/a2/audit-chain.txt | sort | uniq -c
  ```

- the tools they actually reached, and any `denied` rows — a denial is
  the product working, and worth reading against what they saw;
- any gap the session filed on their behalf (`ledger-events.txt`): a
  first user hitting a documentation hole is the most valuable row in
  the file.

Then write up the notes as
`results/phase2/a2-field-notes/README.md` (numbered, severity,
what-a-user-feels), commit the extracted evidence beside them, and hand
the gate verdict back to the platform side for the checkpoint's
closure bookkeeping.

## 8. If there is only one machine (a deviation, recorded as one)

The gate says *their own machine*, and it says so for a reason: a
machine that was never prepared is the only honest test of whether the
delivery path works. A run on this Mac cannot produce that evidence.
What it **can** still produce, if the colleague is the one at the
keyboard under their own login, is the rest of the gate: their identity
in every audit row, a journey they chose, and an operator who said
nothing. That is a real result with a named hole in it, and it is the
owner's call whether to accept it — record it as a deviation in the gate
note, never as a pass.

Three traps make the difference between "their identity in the rows" and
a run that silently records yours. All three are avoidable:

1. **The browser is already signed in as you.** The platform's own
   session cookie lives in whatever browser you last used. Open the
   download in a **private/incognito window**, or sign out first:
   `curl -sS -X POST http://<address>:8100/v1/auth/logout` will not do
   it — the cookie is the browser's, so use a private window. Confirm
   before they download: the window should ask them to sign in.
2. **Claude Code may reuse a cached login for that server.** If you have
   ever authenticated a session against this core on this machine, the
   client may hold a token for it. Have them start the session from a
   fresh directory, and if the session never asks them to sign in,
   **stop** — the rows would carry the cached identity, not theirs.
3. **The repo's own `CLAUDE.md` leaks into any session started beneath
   it.** Unpack the bundle somewhere outside the repository —
   `~/a2-run`, not `~/Desktop/DataProject/anything`. Otherwise the
   session reads this project's instructions as if they were the
   customer's.

The check that catches all three is the one already in §7: every subject
in `audit-chain.txt` must be their username. Run it *early* — after
their first question, not at the end — because a run recorded under the
wrong identity proves nothing and cannot be repaired afterwards.

**If the colleague is remote and has their own machine**, prefer that
over one machine: put the core on a private mesh (Tailscale or
equivalent) and give them the same address over it. Do **not** publish
this stack on a public tunnel: the pilot's identity provider is
dev-only, its passwords are plaintext in a repo file, and nothing here
is behind TLS. Observation over a screen share is fine — arguably better
for note-taking, since you cannot lean over and help.

**What a one-machine run does and does not evidence:**

| Gate claim | One machine, colleague at the keyboard |
|---|---|
| Download authorized against their own binding | **Yes** |
| Bundle carries no credential | Yes (already machine-checked) |
| Their identity in every audit row | **Yes, if the three traps above are avoided** |
| Journey of their choosing, operator hands-off | **Yes** |
| Delivery works to an unprepared machine | **No — this is the hole.** Their machine already has the repo, the toolchain, and your Claude Code install |

## 9. STOP

**This run is yours and your colleague's.** Nothing in it can be done by
the platform session that wrote this page: the identity is real, the
machine is theirs, the question is theirs, and the value is entirely in
what they do when nobody helps. Run it at your pace; stop at any act
whose criteria are not met and record why. A recorded failure here is
worth more than a run that was quietly assisted into passing.
