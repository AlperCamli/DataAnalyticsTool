# A-5 closure — your steps

**Time: about 5 hours of attention**, and it is meant to be split. Most of
it is reading: ten metric definitions and thirty-three documents, each of
which somebody has to decide about. The machine parts are short.

This run is different from the last one. The B-1 demo was browser clicks
and one terminal command; this one has **real terminal work at the start**,
because the deployment's address moved and nothing on it can be signed into
until that is corrected. After step 1 it settles back into the familiar
shape: read a pull request, decide, merge.

**You will use three things:**

1. **A browser** — GitHub, and the dashboard.
2. **One terminal in the platform folder** — step 1 only, and never again.
3. **One terminal in `~/cl-steward`** — steps 3, 4, and the certifying.

**What the whole run is for.** The knowledge base currently holds 33
documents nobody has re-read since the facts underneath them got sharper,
2 documents anybody has certified, and 10 metric definitions marked draft.
By the end it holds a floor: documents on the report path that a person has
read and signed, metrics that count as certified, and a benchmark check
that runs on every future change. Then one reporter journey to see whether
the floor holds when somebody actually stands on it.

**Three of the thirty-three documents are wrong** — not stale, wrong. They
are called out where they come up. They are the reason this is worth five
hours rather than a status flip.

---

## Addresses you will need

| What | Where |
|---|---|
| The dashboard | **`http://<ADDRESS>:8100/app/`** — step 1 tells you `<ADDRESS>` |
| Your setup download | **`http://<ADDRESS>:8100/v1/setup/bundle`** |
| The knowledge base on GitHub | **https://github.com/AlperCamli/Sample-Knowladge-Base** |
| The platform folder (step 1 only) | **`~/Desktop/DataProject`** |
| The steward folder (everything else) | **`~/cl-steward`** |

**Do not write the address down from this page.** This machine gets its
address from the network and it moved once already — that is what step 1
is fixing. Step 1 prints the current one; use what it prints.

## Sign-ins you will need

Both already exist on this machine; passwords are where they always are,
in your `.secrets/idp-users.json`. This page does not print them.

| Account | Who it is | Used for |
|---|---|---|
| **`alper`** | you, the steward | the dashboard, your setup download, merging, certifying |
| **`eda`** | a reporter — a business user | step 5 only: the floor-check journey |

---

## Before you start

**Write down the time you start.** You will be asked for it at the end,
and it is what pulls the right day's records for the write-up.

Nothing needs checking first. Step 1 checks everything, and if the machine
is in a state step 1 does not expect, step 1 says so.

**You can stop after any numbered step.** Nothing here is a transaction.
Where a step should not be left half-done, it says so at the top.

---

# Step 1 — Correct the deployment's address, and pick up the new skill

**Time: about 20 minutes**, most of it a rebuild you watch.
**Do not split this step.** Finish it in one sitting.

**Where:** a terminal, in `~/Desktop/DataProject`.

**Why this exists.** The deployment has `192.168.1.104` burned into it as
its own public address. This machine is now `192.168.1.102`. Everything
that signs in — the dashboard, your setup download, any session — is sent
to `.104` to authenticate, and nothing answers there. **Right now nobody
can sign in to the pilot at all**, and using `localhost` does not route
around it, because it is the address the server *hands out* that is wrong,
not the address you type.

**A second thing rides on this.** The contamination-triage mode the four
batches in step 4 depend on was built after the running server was last
started, so the server is still serving the old version of the enrich
skill — one with no triage mode at all. The restart below rebuilds the
server from current source, and part 3 of this step brings the new skill
down to your session folder. **Without part 3, all four batches in step 4
fail at their first instruction.**

### 1a — Restart with the right address

**Open a brand-new terminal window.** Not a tab you have been working in.
The stack refuses to start if certain settings are left set in the shell,
and a fresh window is the reliable way not to have them. If it refuses, it
prints exactly which ones and where they belong instead — that is the
guard doing its job, not a fault.

Type:

```
cd ~/Desktop/DataProject
CL_HOST_ADDR=$(ipconfig getifaddr en0) make stack-pilot
```

This reads the machine's current address, rebuilds the server, and starts
it. It takes a few minutes and prints a lot. Let it finish.

**What success looks like:** it ends without an error, and the containers
come up. Then run:

```
curl -s http://127.0.0.1:8100/healthz | python3 -m json.tool
```

You want to see, in that output:

- `"public_url": "http://192.168.1.102:8100"` — **the same address**
  `ipconfig getifaddr en0` prints. If it still says `.104`, the restart did
  not take.
- `"sealed": false` under `vault`.

**Record:** the address from `public_url`. This is `<ADDRESS>` for the rest
of this page.

**If it fails:**

- **`sealed: true`.** The secret store re-locked on restart. Unlock it with
  your unseal key from the password manager:
  ```
  printf 'unseal key: '; read -rs VK; echo
  docker compose exec -T vault vault operator unseal "$VK"
  ```
  Then re-check `/healthz`. (Type the key at the prompt; do not paste it on
  a command line.)
- **`public_url` still shows `.104`.** Stop and report it. Do not carry on
  — every later step signs in through that address.
- **It refuses to start naming settings in the shell.** Close that terminal,
  open a new one, start again.

### 1b — Check you can actually sign in

**Where:** browser, at `http://<ADDRESS>:8100/app/`

Sign in as **`alper`**.

**What success looks like:** the dashboard loads and you are signed in.
This is the thing that has been impossible since the address moved, so it
is worth confirming before you build anything on top of it.

**If it fails:** stop and report what the sign-in page did — whether it
never appeared, bounced somewhere unreachable, or errored. Do not work
around it.

### 1c — Take the new setup down to your steward folder

**Where:** browser, then the terminal.

1. In the browser, still signed in as **`alper`**, go to:
   **`http://<ADDRESS>:8100/v1/setup/bundle`**
2. It downloads a file named `contextlayer-setup-steward.tar.gz`.
3. In a terminal:

```
tar -xzf ~/Downloads/contextlayer-setup-steward.tar.gz -C ~/cl-steward
ls ~/cl-steward/.claude/skills/enrich/
```

**What success looks like:** that `ls` prints **three** names —
`SKILL.md`, `ci_gate.py`, and **`worklist.py`**. The third one is the new
triage mode's tool. If it is not there, step 4 cannot run.

**Your knowledge base copy and drafts are untouched** by this — the
download only replaces the setup files, and it contains no folder called
`kb`.

**If it fails:**

- **Your browser already unpacked the `.gz`** (Safari does this). Then use:
  `tar -xf ~/Downloads/contextlayer-setup-steward.tar -C ~/cl-steward`
- **The download refuses with an error about profiles or roles.** Stop and
  report the exact message.
- **`worklist.py` is missing after unpacking.** Stop and report it. The
  rebuild in 1a did not pick up current source, and step 4 would fail in a
  confusing way instead of an obvious one.

---

# Step 2 — Merge the benchmark check

**Time: about 10 minutes.** Safe to stop after.

**Where:** https://github.com/AlperCamli/Sample-Knowladge-Base/pull/46

This is the pull request titled *"ci: the golden suite comes home, and KB
CI checks it"*. It moves the ten customer-verified test questions into the
knowledge base where they belong, and adds an automated check that runs
them on every future change.

**Why it matters beyond tidiness:** those ten questions and their verified
answers were, until now, shipped *inside the platform's software package*.
Every customer installing that package installed this estate's questions
and a frozen copy of its data structure. That is the defect this merge
closes, and it is the reason it goes first.

1. Open the pull request and **read the diff**. Four files: the suite of
   ten questions, the CI workflow, and a rebuilt checking library with its
   provenance record.
2. Confirm the check named **KB CI** has run and is **green**. It was green
   when this page was written.
3. Click **Merge**.

You will be told the merge is an administrator bypass. Expected — you are
the only person with write access here, and the knowledge base's own
conventions record that.

**What success looks like:** the pull request shows as merged, and the
**next** pull request you open (step 4) shows a check step named
**"Golden benchmark suite integrity (KB-9)"** that was not there before.

**Record:** the merge confirmation. This is the evidence that the CI half
of the benchmark item is live rather than merely built.

**If it fails:** if **KB CI** is red on this pull request, **do not merge
it** — report what the failure says. A red check here means the ten
questions no longer resolve against the estate, which is exactly what the
check exists to tell you.

---

# Step 3 — Certify the metrics

**Time: 45–60 minutes**, nearly all of it reading. Safe to stop after, and
safe to do in two sittings if you commit what you have decided so far.

**Where:** GitHub to read, then a terminal in `~/cl-steward/kb`.

**Read this first — one thing has already happened.** Pull request #48,
the ten metric definitions, **is already merged.** You merged it on
2026-08-07 at 22:02. All ten documents are in the knowledge base now. What
has *not* happened is certification: every one of them still says
`status: draft`, and until you say otherwise, any report built on one of
them will correctly announce itself as resting on a draft.

**What certifying means here.** For a metric document, `status: verified`
**is** the certification — there is no separate ceremony. It is you saying:
*this is our definition of this number, and I stand behind it.* That is
why a session cannot do it and why it is not automated.

### 3a — Read the ten

Read them at
https://github.com/AlperCamli/Sample-Knowladge-Base/tree/main/metrics —
each is short, and each ends with a section called **Known discrepancies**
that is the part worth your attention.

**One you must certify**, or step 5 cannot close:

- **`new-users.md`** — the count of accounts created, from the same SQL
  your own benchmark question RB-01 uses. This is the metric the floor
  check in step 5 stands on.

**Six that should be straightforward:** `organic-search-clicks`,
`completed-exports`, `ai-run-failure-rate`, `job-stage-transitions`,
`conversions`, `activation-rate` — read them anyway, but they document what
the estate does.

**Three where I would want you to think twice**, because certifying them
means vouching for something nobody has yet seen produce a number:

- **`active-subscriptions`** — the `status` column it filters on has **no
  database constraint**, so `active`, `trialing` and `canceled` are grounded
  in an index and your own statement, and the provider's other states
  (`past_due`, `incomplete`, …) are not. A row in one of those is silently
  outside this metric. And **the table held 0 rows on 2026-08-07** —
  nothing in this document has ever been checked against real values.
- **`new-subscriptions`** and **`churn-risk-rate`** — both inherit that
  same gap, and say so.

**Two more things to read with a sharp eye, though neither is a reason not
to certify:**

- **`conversions`** names the seam where GA4 and the database are
  *expected* to disagree, and names the open pricing question
  (`4c4ecb3d` — the Stripe check you still owe) as living exactly at that
  seam. It is correct that it says so; the pricing question does not block
  this metric, because this metric counts conversions and does not price
  them.
- **`activation-rate`** warns that its steps are **not** strictly nested —
  a later step can exceed an earlier one, so it must not be drawn as a
  funnel that only shrinks. If you certify it, you are certifying that
  warning too.

**Leaving one as `draft` is a real answer.** A draft metric is honest and
the system says "draft" out loud wherever it is used. Certifying something
you have not seen return a number is the option with a cost.

### 3b — Flip the ones you accept

In a terminal:

```
cd ~/cl-steward/kb
git checkout main
git pull
```

Then run this **once**, listing at the end only the metrics you decided to
certify. The example lists all ten — **edit the list to your decision.**

```
sed -i '' \
  -e 's/^status: draft$/status: verified/' \
  -e 's/^last_verified: null$/last_verified: "2026-08-08 (Alper Camli)"/' \
  -e 's/^owner: "alper (operator) — pending"$/owner: "alper (operator)"/' \
  metrics/new-users.md \
  metrics/organic-search-clicks.md \
  metrics/completed-exports.md \
  metrics/ai-run-failure-rate.md \
  metrics/job-stage-transitions.md \
  metrics/conversions.md \
  metrics/activation-rate.md \
  metrics/active-subscriptions.md \
  metrics/new-subscriptions.md \
  metrics/churn-risk-rate.md
```

Now **look at what it did** before committing anything:

```
git diff
```

**Read this diff more carefully than you would normally.** Metric documents
are a document type the automated checker does not yet know how to
schema-check — it checks their links, not their front matter. So on these
ten files, your eyes are the check. (That gap is written up as its own
small piece of work; it is not something to fix tonight.)

**What success looks like:** exactly **three changed lines per file** and
nothing else — `status`, `last_verified`, and the owner line losing the
word `pending`. That command was run against copies of these files on this
machine before this page was written, so three is the number to expect. If
you see fewer, or if anything in a document *body* changed, **do not
commit** — report it.

Then:

```
git commit -am "certify: metrics verified by the owner (alper)"
git push origin main
```

**What success looks like:** the push is accepted. This is a direct commit
to a protected branch under your administrator rights — the same act, by
the same route, as your `c2baa54` commit on 2026-08-07 that certified
`subscriptions.md`. Then on GitHub, under **Actions**, a **KB CI** run
appears for your commit and goes green.

**Record:** which metrics you certified and which you left as `draft`, and
your one-line reason for each you left. That list is part of the closure
record — "the operator declined to certify three metrics against an empty
table" is a better result than ten green rows.

**If it fails:**

- **The push is rejected.** Stop and report the message. Do not force
  anything.
- **KB CI goes red on your commit.** Report what it says. Your change was
  three lines of front matter; a failure means something else about the
  knowledge base is unhappy and it should be understood, not patched over.

---

# Step 4 — The four triage batches

**Time: about 50 minutes for batch 1, 35–40 each for batches 2, 3 and 4.**
Roughly 2½ hours in total.

**These split across days safely.** Each batch is one self-contained
session, one pull request, one merge. Do one and stop if you want. Do not
start a second batch before merging the first — two open pull requests
touching the same knowledge base will make you resolve conflicts for no
reason.

**Where:** a terminal in `~/cl-steward`, then GitHub, then back to the
terminal to certify.

### What a batch is

Thirty-three documents in the knowledge base are marked *contaminated*.
That word is scarier than the situation. On 2026-08-04 the platform started
capturing the database's own value constraints for the first time, fifteen
tables gained facts they did not previously have, and every human-written
document that leaned on one of those tables was flagged as *nobody has
re-read this since*. **Nothing was deleted, renamed or broken. The estate
got sharper, and the documents have not been checked against the sharper
version.**

So the expected outcome per document is *"reads correctly, mark it
re-read"*, and the diff for those should be **front matter only — not one
word of the body**. That expectation is what makes the exceptions findable,
and there are three of them.

### The rhythm, the same every time

1. **Open a terminal**, and type:

   ```
   cd ~/cl-steward
   claude
   ```

   That folder is a customer steward's setup and nothing else — no access
   to the platform's source. Running this from anywhere else would let a
   session write from information a real customer's steward would never
   have, which is the mistake this whole arrangement exists to prevent.

2. **Paste the batch's prompt** (below), and leave it alone. Each batch
   takes several minutes and a few dollars of model usage.

3. **What you want to see it do:** update its own copy of the knowledge
   base first; classify each document itself against the constraints;
   re-render and validate; open a pull request; **wait for the automated
   check to actually report**; and tell you it has neither certified nor
   merged anything.

   **If it says its setup is out of date, stop** — step 1c did not take.
   Re-do 1c and start the batch again.

   **If it disagrees with a classification and says so, that is the mode
   working.** Read its reasoning. It is looking at the constraint; this
   page is quoting a plan written a day earlier.

4. **Read the diff on GitHub.** Not the description — the diff.

5. **Certify what you accept, and merge.** Commands below.

### How to certify a batch and merge it

After you have read the diff and want it in, in a terminal:

```
cd ~/cl-steward/kb
git fetch origin
git checkout <the branch the session named>
git pull
```

Then flip the documents you accept — list them at the end:

```
sed -i '' \
  -e 's/^status: draft$/status: verified/' \
  -e 's/^last_verified: null$/last_verified: "2026-08-08 (Alper Camli)"/' \
  systems/supabase/public/ai_runs.md \
  systems/supabase/public/ai_prompt_configs.md
```

Check, commit, push:

```
git diff
git commit -am "certify: batch 1 documents verified (alper)"
git push
```

Then back on GitHub: wait for **KB CI** to run again on your new commit,
confirm it is green, and click **Merge**.

**A pull request with no check showing is not a passing one.** If no check
appears within a couple of minutes, run this from `~/cl-steward/kb` — it
makes one happen and reports it:

```
python3 ~/cl-steward/.claude/skills/enrich/ci_gate.py <pull request number>
```

**If GitHub says the branch is out of date**, click **Update branch** and
wait for the check to re-run. That happens when you merged something else
in between.

**Record, per batch:** the pull request number, the merge confirmation, and
anything the session classified differently from what this page predicted.

---

## Batch 1 — the AI-run family (8 documents)

**Do this one first, and give it the most attention: two of the three
wrong documents are in it.**

**Scrutinise hardest:** that `ai_runs.md` and `ai_prompt_configs.md` come
back with **bodies changed** — they must, because they are wrong. Both
currently say the `flow_type` column is limited to **11 values**. The
database constraint captured on 2026-08-04 allows **13**: both documents
are missing `skills_pool` and `professional_summary`. Anybody writing a
report that filters on the documented list silently drops two kinds of run.
The two documents quote each other, so they have to end up agreeing.

The other six should be front-matter-only. If one of them has a changed
body, the pull request must say why.

**Paste this:**

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 1 of the
A-5 triage plan.

The batch, in this order:
  systems/supabase/public/ai_runs.md
  systems/supabase/public/ai_prompt_configs.md
  systems/supabase/public/ai_suggestions.md
  systems/supabase/public/cv_block_revisions.md
  systems/supabase/reporting/v_ai_runs_by_day.md
  systems/supabase/reporting/v_ai_runs_by_flow.md
  systems/supabase/reporting/v_ai_tokens_by_month.md
  systems/supabase/reporting/v_daily_activity.md

Follow S0 first (working copy at ~/cl-steward/kb, pulled, clean), then
S1c: build the work list with worklist.py, classify each doc yourself
against the snapshot's CHECK constraints, and repair per class.

TWO OF THESE ARE FIX ITEMS, NOT confirms-prose. ai_runs.md and
ai_prompt_configs.md both describe flow_type as an 11-value set. The CHECK
constraint captured on 2026-08-04 admits 13 — the documented list is
missing `skills_pool` and `professional_summary`. Classify both
needs-re-grounding and repair the enumeration in both; they cross-reference
each other ("Same set as supabase.public.ai_runs.flow_type"), so they are
wrong together and must come out agreeing. Say in the PR body what the docs
got wrong and when the constraint appeared.

Verify that against the snapshot before you write anything. If the
constraint does not say what I have just said it says, stop and tell me
rather than writing either version. The same goes for the other six: if you
find yourself editing a body, that doc was misclassified — say so rather
than quietly widening the repair.

Re-render and validate before opening the PR. One PR for the batch, with
the per-doc classification table and the certification block. Do not
certify anything yourself and do not merge.
```

---

## Batch 2 — exports, files and imports (10 documents)

**Time: ~35 minutes.**

**Scrutinise hardest: this one should be boring, and if it is not, reject
it.** All ten are expected to be front-matter-only. **If any document body
has changed and the pull request does not explain that document as a
re-classification, do not merge it** — send it back. A repair that quietly
improves prose while it is in the neighbourhood is precisely what makes the
other thirty-two unreviewable, because you can no longer skim for the
diff that matters.

One trap to know about: `cv_templates.md` says there is no database
constraint on its `status` column. **That is true** and must not be
"corrected".

**Paste this:**

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 2 of the
A-5 triage plan.

The batch:
  systems/supabase/public/exports.md
  systems/supabase/public/cover_letter_exports.md
  systems/supabase/public/cover_letters.md
  systems/supabase/public/files.md
  systems/supabase/public/cv_templates.md
  systems/supabase/public/imports.md
  systems/supabase/reporting/v_exports_by_format.md
  systems/supabase/reporting/v_files_by_type.md
  systems/supabase/reporting/v_imports_by_parser.md
  systems/supabase/reporting/v_activation_funnel_monthly.md

S0, then S1c as written. The plan expects all ten to be confirms-prose —
which means ten front-matter-only diffs, and if you find yourself editing
a body, that doc was misclassified and you should say so rather than
quietly widen the repair. Note that cv_templates.status genuinely has no
CHECK constraint; the doc saying so is correct and stays.

Re-render, validate, one PR, certification left to me.
```

---

## Batch 3 — jobs, CVs and their views (10 documents)

**Time: ~40 minutes.**

**Scrutinise hardest:** `v_jobs_by_status.md`, the third wrong document. It
currently *warns readers* that `public.jobs.status` is **not** constrained
by the database, so new values can turn up unannounced. The constraint
exists:
`CHECK (status IN ('saved','applied','interview','offer','rejected','archived'))`.
The warning is the opposite of the truth, and it is the kind of warning a
report author would act on — building defensive handling for values that
cannot occur.

**This batch also carries `users.md`, which step 5 stands on.** Certify it
if you accept it, or the floor check will report a draft on its path.

Note that `jobs.md` mentions older `interviewing`/`offered` spellings as
history. The constraint does not contradict history; that stays.

**Paste this:**

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 3 of the
A-5 triage plan.

The batch:
  systems/supabase/public/jobs.md
  systems/supabase/public/job_status_history.md
  systems/supabase/public/master_cvs.md
  systems/supabase/public/tailored_cvs.md
  systems/supabase/public/users.md
  systems/supabase/reporting/v_jobs_by_month.md
  systems/supabase/reporting/v_jobs_by_status.md
  systems/supabase/reporting/v_job_status_transitions.md
  systems/supabase/reporting/v_master_cvs_by_language.md
  systems/supabase/reporting/v_cv_production.md

S0, then S1c.

ONE OF THESE IS A FIX ITEM, NOT confirms-prose. v_jobs_by_status.md warns
that public.jobs.status is NOT constrained by a database CHECK, so new
values can appear. It is constrained:
CHECK (status IN ('saved','applied','interview','offer','rejected','archived')).
The doc's warning is the opposite of the truth. Classify it
needs-re-grounding, replace the warning with what the constraint actually
says, and state in the PR body what the doc got wrong.

Verify that against the snapshot before you write. If the constraint is not
there, stop and tell me rather than writing either version. The other nine
are expected to confirm — jobs.md's note about legacy interviewing/offered
spellings is history the constraint does not contradict, and stays.

Re-render, validate, one PR, certification left to me.
```

---

## Batch 4 — entities, GA4 and the leftovers (5 documents)

**Time: ~35 minutes.** This is the last one.

**Scrutinise hardest:** `usage_counters.md` is the odd one. It has **no
contamination marker** but is still marked contaminated — an earlier repair
cleared the marker and left the status behind, at a time when nothing said
what status a repaired document should land in. So its expected outcome is
a one-line status change. **If the session comes back saying its content
hash does not match and it needed real re-grounding, that is a finding** —
read that part carefully rather than waving it through.

The two entity documents are checked differently: what matters is that
every object they claim to map still exists.

**Paste this:**

```
Use the `enrich` skill in contamination-triage mode (S1c) on batch 4 of the
A-5 triage plan — the last one.

The batch:
  entities/conversion.md
  entities/user.md
  systems/ga4/dimensions.md
  systems/supabase/reporting/v_user_cohorts.md
  systems/supabase/public/usage_counters.md

S0, then S1c. Two things specific to this batch:

- usage_counters.md has NO contamination marker but is still
  `status: contaminated` — PR #37 re-grounded it and cleared the marker
  without moving the status. Check its hash against the current snapshot
  and land it `draft` like any other repair; if the hash does not match,
  it is a real re-grounding and should be treated as one, and said so
  plainly in the PR body.
- entities/*.md are entity docs: their `maps:` block is the contamination
  contract, so check that every mapped object still resolves before you
  call either one confirmed.

Everything else is expected to confirm, front-matter only. If you find
yourself editing a body outside the two cases above, say so rather than
widening the repair quietly.

Re-render, validate, one PR, certification left to me.
```

---

# Step 5 — The floor check: does a real question find a certified answer?

**Time: 30–40 minutes.**

**Do this after the last batch is merged**, in the same sitting or the next
one — but not before, because what it measures is exactly what the batches
and step 3 just put in place.

**Where:** browser first, then a terminal in `~/cl-reporter`.

**What this is.** Everything up to here was preparation seen from the
inside: statuses, merges, certifications. This step asks the only question
that matters from the outside — **a business user asks for something in
their own words; does the answer come back resting on knowledge a person
signed for?** The system will say out loud what it stood on. If any part of
the path is still draft or unread, it will say that too, and that is a
result rather than a failure.

The question is your own benchmark case RB-01: *how many new users are
signing up?*

### 5a — Get the reporter's setup

1. In the browser, **sign out**, then sign in as **`eda`**.
2. Go to **`http://<ADDRESS>:8100/v1/setup/bundle`**.
3. It downloads `contextlayer-setup-reporter.tar.gz`.
4. In a terminal:

```
tar -xzf ~/Downloads/contextlayer-setup-reporter.tar.gz -C ~/cl-reporter
cat ~/cl-reporter/.mcp.json
```

**What success looks like:** the address in that file is `<ADDRESS>` — the
one step 1 printed — and it says `profile=reporter`.

**Why as `eda` and not as you:** what is being measured is a business
user's floor, and a business user has a business user's visibility. Running
it under the steward identity would measure something no customer will ever
experience.

### 5b — Run the journey

```
cd ~/cl-reporter
claude
```

**Paste this:**

```
Use the `report` skill for this request, end to end:

  "How many new users are signing up? I want to watch new users over time."

Window: June 2026 (2026-06-01 to 2026-06-30, UTC), daily buckets. Resolve it
through the knowledge base, validate the SQL, execute it, and produce the
report artifact.

When you are done, print the artifact's `trust_notes` block verbatim, and
say plainly whether any doc or metric on the path is draft, stale or
contaminated.
```

A browser sign-in will be needed when it first connects — sign in as
**`eda`**. It carries no password of its own and there is none to give it;
that is by design.

**What success looks like — the trust notes must show all three:**

1. **`supabase.reporting.v_user_signups_by_day`** cited as **verified**
   (it already was, since 2026-08-05);
2. **`supabase.public.users`** cited as **verified** — this is batch 3's
   work showing up;
3. **`metrics/new-users`** cited as a **certified** metric — this is step
   3's work showing up;

and **no draft, stale or contaminated warning anywhere on the report path.**

**Record:** the report artifact, and the trust notes block copied out
verbatim. Save both into `results/phase2/a5/floor-check/`. If you would
rather not deal with file paths, paste them to me in step 6 and I will
file them.

**If it comes back short of that** — a draft warning, a metric it will not
treat as certified, a document it cannot see — **record exactly what it
said and carry on to step 6.** Do not go back and flip statuses to make it
come out green. A floor check that reports the floor it found is doing its
job; one that reports the floor we wanted is worth nothing. The last two
runs of this kind each turned up a real defect, and both were found by the
gap between what the screen said and what had actually happened.

**If it never connects at all:** stop and report it. That is the step 1
problem returning, and it needs the address fixed, not a retry.

---

# Step 6 — Tell the session you are done

**Time: 2 minutes.**

Come back to the Claude Code session in the platform folder — the one you
are reading this from, not any of the ones you started in `~/cl-steward` or
`~/cl-reporter` — and say:

> **done — started at HH:MM**

with the time you wrote down at the very beginning.

Then hand over what you recorded:

- the address from step 1;
- the merge for #46;
- which metrics you certified and which you left draft, with your reasons;
- the four batch pull request numbers and merges;
- the floor check's trust notes;
- and **anything that surprised you, annoyed you, contradicted this page,
  or that you rejected** — especially that. A rejected pull request is the
  most useful thing one of these runs can produce, and it has happened
  before.

---

## Planning your sittings

| Sitting | Steps | Time | Notes |
|---|---|---|---|
| **1** | 1, 2, 3 | ~1h 30m | Step 1 must be finished in one go. After it, the pilot is signed-in-able again — that alone is worth doing today. |
| **2** | Batch 1 | ~50m | The heaviest reading. Two wrong documents. |
| **3** | Batches 2 and 3 | ~1h 15m | Or one each. Merge one before starting the next. |
| **4** | Batch 4, then step 5, then step 6 | ~1h 15m | **Keep these together** — the floor check should follow the last merge. |

**Safe to stop after:** any numbered step, and after any individual batch.
**Do not stop in the middle of:** step 1 (the stack is half-restarted), or
between a batch's session finishing and your merge (a pull request left
open blocks the next batch).

---

## What "done" proves — the closure checklist

Mirrored from `GATE-CHECK.md`, which grades three items from the customer
onboarding playbook. When you come back, these get re-graded against what
you actually did, with the evidence pointing at your merges.

**Item 3 — hot objects documented, report-path documents human-verified.**
Open today: 2 verified, 33 contaminated, 21 draft (the 11 that were
already there, plus #48's ten metrics).

- [ ] Batch 1 merged, and the `flow_type` 11-vs-13 error corrected in both documents
- [ ] Batch 2 merged (front-matter-only, or an explained exception)
- [ ] Batch 3 merged, and the false "no constraint" warning corrected
- [ ] Batch 4 merged, `usage_counters.md`'s stranded status resolved
- [ ] Documents you accepted carry `status: verified` and your name and date
- [ ] Contamination count at end state: **0** where it is 33 today

**Item 4 — every seed request resolves to entities and certified metrics.**
Open today: ten metrics merged, none certified.

- [ ] Metrics you accept flipped to `verified` under your own name
- [ ] Metrics you declined recorded as declined, with your reason
- [ ] The floor check's own evidence: a request resolving through a
      certified metric (step 5)

**Item 6 — benchmark baseline recorded and CI-wired.**
Partial today, and it stays partial on purpose.

- [ ] KB #46 merged — the check goes from *armed and demonstrated* to
      *enforcing on every future change*
- [ ] KB-9 seen running on a later pull request
- [ ] **The baseline half stays open**, and closes only when BASELINE-1
      runs. That is the three-condition accuracy measurement, and it is
      deliberately trigger-gated: it waits for the first customer
      conversation that quotes value, and it costs 8–13 hours of your
      attention, booked rather than squeezed in. **This checklist does not
      claim it.** Item 6 will be re-graded as *CI half green, baseline half
      open on its trigger* — not as closed.

**And the test that is honestly red today:**

- [ ] The contamination test in the platform's own suite currently fails,
      because it asserts the knowledge base carries no contaminated
      document and the knowledge base carries 33. It goes green when your
      four merges land. **Nothing was deleted or relaxed to make it look
      better in the meantime**, and if it is still red after the merges,
      that is a finding to chase rather than a number to adjust.

**Still riding, and not part of this run:** the Stripe check for the
pricing question (`4c4ecb3d`) — an ordinary knowledge update now, against a
document that is already repaired; and the security housekeeping — the
vault rekey, the root-token revoke, and four rows in
`SECRETS-INVENTORY.md`.

---

## If something looks wrong

**The dashboard address does not load, at any point after step 1.**
This machine's address can change again when it reconnects to the network.
Re-run `ipconfig getifaddr en0`. If it differs from what step 1 printed,
that is the same fault returning — re-run step 1a and 1c. Say that it
happened, because a deployment whose address moves under it is a product
problem, not an inconvenience.

**A session says its setup is out of date.**
Believe it. Re-do step 1c and start that batch again. It is designed to say
this rather than quietly run an old version of itself.

**A session says it cannot find its knowledge base copy, or that the copy
has uncommitted changes.**
Stop and say so. It is meant to stop rather than overwrite anything, and if
it is stopping there is something to look at.

**A pull request shows no automated check.**
It is not a passing one. Run the check-forcer named in step 4, or close and
reopen the pull request, and wait. Merging on an absent check is the one
shortcut with a real defect behind it.

**You disagree with a document a session wrote.**
Do not merge it. Say what is wrong. That is the review, and it is the only
review — nothing else in this system is going to catch it.

**You want to stop halfway.**
You can, at the boundaries named above. Everything already merged stays
merged, every certification stays certified, and the rest can be picked up
another day. Just say where you stopped.
