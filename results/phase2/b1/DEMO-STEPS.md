# B-1 closure demo — your steps

**Time: about 40 minutes**, most of it waiting for a session to write and
for a check to run.

Everything is already set up and running. You do not need to start, stop,
build or configure anything. There are no files to edit.

**You will use two things and nothing else:**

1. **A browser** — for all but one step.
2. **One terminal window**, once, in step 5. You will type two lines and
   then talk to a session in plain English.

The whole run is: somebody asks for knowledge the knowledge base does not
have → you decide → a session writes it → you merge it → the person who
asked sees the answer come back. Two requests are filed on purpose: one
you will say yes to, one you will say no to, because saying no has never
been tried on the real system.

**Do not open a terminal anywhere except step 5, and in step 5 do not use
any folder except the one named.** The point of the run is to prove the
product works from where a customer's steward actually sits. A run from
somewhere else proves nothing about the product.

---

## Addresses you will need

| What | Where |
|---|---|
| The dashboard | **http://192.168.1.104:8100/app/** |
| The knowledge base on GitHub | **https://github.com/AlperCamli/Sample-Knowladge-Base** |
| The one folder for step 5 | **`~/cl-steward`** |

## Sign-ins you will need

Two accounts, both already on this machine. Passwords are where they have
always been, in your `.secrets/idp-users.json` — this page does not print
them.

| Account | Who it is | Used for |
|---|---|---|
| **`eda`** | a reporter — a business user | filing the two requests, and seeing the answers come back |
| **`alper`** | you, the steward | approving, declining, delivering, merging |

`eda` files and you decide, because the whole point is that those are two
different people. `eda`'s "What came back" is empty right now, so any
number that appears on it during this run was put there by this run.

---

## Before you start — 30 seconds

Open **http://192.168.1.104:8100/app/** in your browser.

You should get a sign-in page or the dashboard. **If the page does not
load at all**, skip to *If something looks wrong* at the bottom — but try
it first, because it was working when this page was written.

Nothing else needs checking. The system was stood up and verified this
afternoon: five connections tested green, the knowledge base copy is
clean and up to date, and the session folder in step 5 is current.

**Write down the time you start.** You will be asked for it at the end.

---

# Step 1 — Sign in as the reporter and file the first request

**Where:** http://192.168.1.104:8100/app/

1. Sign in as **`eda`**.
2. In the left-hand menu, click **Gap Triage**.
3. Find the form headed **"Ask for something, or report a gap"**.
4. Leave the choice on **Knowledge request** (the first option).
5. Fill in the three boxes with the text below. Copy each block exactly.

**Box 1 — "What is missing, in your own words":**

```
The daily activity view has a column for every action, but nothing anywhere says which one we actually report as the headline daily number. Every dashboard built on it so far has picked a different column, and no amount of reading the view settles it, because the answer is not in the database — it is our reporting convention, and it is written down nowhere.
```

**Box 2 — "Object it is about (optional)":**

```
supabase.reporting.v_mart_fact_daily
```

**Box 3 — "What it should say, if you know (optional)":**

```
cvs_tailored is our headline daily activity figure. Internally we call it "tailorings", and it is the number to show whenever a report says "activity" without qualifying it.

The reason is that a tailored CV is the point where a user gets the thing they came to us for. Everything before it is setup. So jobs_created is upstream intent rather than delivered value, and belongs in a funnel step, not in an activity headline. And ai_runs_started is an infrastructure and cost signal — it moves for reasons that have nothing to do with how many people used the product that day, so it should never be presented as a usage number on a business report.

None of this changes the view. It is how we read it.
```

6. Click **Send request**.

**Read this before you paste it.** Box 3 is a statement about how *your*
business reads its own numbers. It is only worth filing if you agree with
it. If you would put it differently, put it differently — the demo works
just as well with your words, and a request you do not believe is not a
demonstration of anything.

**What success looks like:** a green confirmation saying *"Filed. This is
issue …, now at 1 occurrence(s), routed to …"*, with an issue id.

**Expect a small notice** under that confirmation reading *"Contains
quoted text. Stored exactly as you wrote it — nothing was removed."*
That is correct and is not an error. It is the system telling you it
noticed quotation marks in what you wrote and **kept them**. An earlier
version of this product silently deleted things that looked like values,
and nobody was told; this notice is what replaced that. It is meant to
appear.

**Record:** the issue id, and a screenshot of the confirmation with the
warning badge.

---

# Step 2 — File the second request (the one you will decline)

**Where:** the same form, still signed in as **`eda`**.

Same three boxes, new text.

**Box 1 — "What is missing, in your own words":**

```
The signups view tells me how many accounts were created on a day but not which ones, so when there is a spike I cannot tell a real week from one person opening test accounts. Please put the per-account detail into the doc so a number can be traced back to the people behind it.
```

**Box 2 — "Object it is about (optional)":**

```
supabase.reporting.v_user_signups_by_day
```

**Box 3 — "What it should say, if you know (optional)":**

```
Add a table to the signups view doc listing each signup day next to the accounts created on it — email address and account id — so anyone reading a spike can see who it was. If that is too much for one doc, at least list the days where a single named account is the whole count, since those are the ones that mislead.
```

Click **Send request**.

This one is a reasonable-sounding request that should be turned down, and
in step 3 you will turn it down. It is here because declining has never
been tried on the real system — only in tests — and a passing test is not
a demonstration.

**What success looks like:** a second green confirmation with a second
issue id. No warning badge this time.

**Record:** the second issue id.

---

# Step 3 — Sign in as yourself and decide

**Where:** the same dashboard.

1. Click **sign out** (top right), then sign in as **`alper`**.
2. Go to **Gap Triage**. You are on the **Knowledge requests** tab.
3. You will see both requests, each showing the filer's own words in a
   quoted box.

Read them. The quoted box is `eda`'s words shown to you as *hers* — the
system is quoting her, not adopting what she said.

### 3a — Approve the first one

On the request about the **daily activity view**, click
**Approve — worth drafting**.

**What success looks like:** the card moves to approved, showing your
name and the time.

**What this does not do**, and the screen says so: it does not write
anything into the knowledge base and it does not open anything. It means
*worth drafting*. Nothing is certified until you merge a diff yourself in
step 6.

### 3b — Decline the second one

On the request about the **signups view**, click **Reject…**, then paste
this into the reason box:

```
Declining. This view is deliberately a date and a count. It reads a row-level-security-protected table as its owner, and the only reason that opening is allowed at all is that there is no path from a number back to a person. Putting addresses or account ids into the knowledge base would defeat that control and publish identifying data into a repository the whole team reads. The need is real — trace it in the app under its own access rules, not here.
```

Click **Reject with this reason**.

Again: only send this if you agree with it. It is the real reason the
request should be declined, but it should be your reason.

**Record:** a screenshot of both verdicts, showing your name and the times.

---

# Step 4 — Check the decline reached her, then hand the work over

### 4a — See the decline arrive

1. Sign out. Sign in as **`eda`**.
2. Look at the bottom of the left-hand menu: **What came back** should
   now carry a **badge with 1** on it.
3. Click it. You should see the declined request with **"Declined by
   alper"** and the full reason you wrote.

This is the half of the reply path that has never been shown working on
the real system. **Read the reason on screen and check it is word for
word what you typed.**

**Record:** a screenshot of the badge, and a screenshot of the reason as
`eda` sees it.

### 4b — Deliver the approved work

1. Sign out. Sign in as **`alper`**.
2. Go to **Gap Triage**, **Knowledge requests** tab.
3. Scroll to the panel at the bottom and click
   **Deliver batch to the enrich skill**.

**What success looks like:** it confirms a batch was cut, containing 1
request.

This still writes nothing. It hands a session a work list.

**Record:** the batch id it reports.

---

# Step 5 — The one terminal step

This is the only time you touch a terminal. Two lines, then plain English.

Open a terminal and type exactly:

```
cd ~/cl-steward
claude
```

That folder is a customer's steward setup and nothing else — it has no
access to the platform's source code, and that is deliberate. **Do not
run this from anywhere else**, and do not point it at another folder. A
session run from the wrong place would be writing from information a real
customer's steward would never have, which is exactly the mistake this
run exists to avoid repeating.

When the session starts, paste this and press enter:

```
A knowledge request has been approved and delivered to you as a batch. Please run the enrich skill in its queue-driven batch mode: read the batch, draft what it asks for, and open the pull request.

Two things before you start. There is an older batched request about subscription pricing that is blocked on a check I have not finished — if it shows up in your batch list, leave it exactly where it is, do not draft it, and say in your pull request body that you left it and why. And when the pull request is open, hand it over unmerged: I will read the diff and merge it myself.
```

Then leave it alone and watch. It takes a few minutes and costs a few
dollars in model usage.

**What success looks like** — five things, in roughly this order:

1. It updates its own copy of the knowledge base before doing anything.
2. It reads the request through the server, and **does not ask you for a
   password or a token**. It has none, and there is none to give it.
3. It writes one document, re-renders, and checks it — reporting
   something like *0 errors, 0 warnings*.
4. It opens a pull request on GitHub, then **waits for the automated
   check to actually report** before saying anything about it.
5. It tells you the pull request is open and that it has **not** merged it.

**Two things worth reading in what it says**, because they are the
product behaving well rather than politely:

- It should say it **opened a pull request** — never that it "added" or
  "updated" the knowledge base. Nothing is in the knowledge base until you
  merge.
- It should say **whose name the new document cites as its source**, and
  why that name. The source should be `eda` — the person who actually
  filed it — and the date it was filed.

**If it asks you a question instead of drafting, answer it honestly, even
if the answer is "I don't know".** Asking is an allowed outcome, not a
failure.

**Record:** the pull request number and link, and copy out the session's
closing message.

---

# Step 6 — Read the diff and merge it. This is the act.

**Where:** https://github.com/AlperCamli/Sample-Knowladge-Base/pulls

1. Open the pull request the session just made.
2. **Read the diff.** Not the description — the diff. This is the review,
   and it is the only review.
3. Check the automated check has run and is green. **A pull request with
   no check showing is not a passing one.** If no check appears, close the
   pull request and reopen it — that causes one — and wait for it.
4. If the document is right, click **Merge**.

You will be told the merge is an administrator bypass, because you are
the only person here with write access. That is expected and it is written
down in the knowledge base's own conventions. The bypass merge **is** the
act of certifying this document. What it is not is a second pair of eyes,
and nothing claims it was.

**If the document is wrong, do not merge it.** Say what is wrong. A
refusal here is a result, not a failure of the run — the last time this
was tried, the pull request was rightly rejected and that rejection was
the most useful thing the day produced.

**Record:** a screenshot of the check, and the merge confirmation.

---

# Step 7 — Watch the answer reach the person who asked

**Where:** the dashboard.

1. Sign out. Sign in as **`eda`**.
2. Click **What came back**.

**This is not instant.** The system checks for merged pull requests every
five minutes, so give it up to five minutes and refresh.

**What success looks like:** the badge goes to **2**, and the approved
request now shows as **resolved**, pointing at the pull request you
merged.

That is the loop closed: she asked, you decided, a session drafted, you
certified, and she was told — without anybody emailing anybody.

**Record:** a screenshot of both items in her inbox — one declined with
your reason, one resolved with the merge.

---

# Step 8 — Tell the session you are done

Come back to this Claude Code session (the one in the platform folder,
not the one from step 5) and say:

> **done — started at HH:MM**

with the time you wrote down at the beginning. That time is needed to
pull the right day's records for the write-up.

Then hand over anything you recorded, and **anything that surprised you,
annoyed you, or did not match this page** — especially that. The last two
of these runs each turned up real defects, and both were found by
somebody noticing that the screen said one thing and the system had done
another.

---

## If something looks wrong

**The dashboard address does not load.**
This machine's network address can change when it reconnects to the
network, and this page has today's baked in. Try
**http://localhost:8100/app/** instead. If that loads but sign-in fails
or bounces you somewhere unreachable, stop and say so — that needs one
change at the platform end, and it is a 2-minute fix, not a rebuild.

**Sign-in works but a page is empty or an action fails.**
Note exactly what you clicked and exactly what it said, and carry on if
you can. The message matters more than the recovery.

**The session in step 5 says its setup is out of date.**
It should not — it was refreshed and checked this afternoon. If it says
so anyway, that is worth reporting on its own; let it carry on, because
it is told to trust the server rather than its own local copy.

**The session in step 5 says it cannot find its knowledge base copy, or
that the copy has uncommitted changes.**
Stop and say so. It is meant to stop rather than overwrite anything, and
if it is stopping there is something to look at.

**You want to stop halfway.**
You can. Nothing here is a transaction. The requests stay filed, the
verdicts stay recorded, and it can be picked up later — say where you
stopped.
