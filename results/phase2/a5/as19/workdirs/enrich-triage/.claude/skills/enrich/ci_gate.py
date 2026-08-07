#!/usr/bin/env python3
"""Do not hand over a pull request whose CI never reported (D-116.4).

Finding, live on the pilot: KB PR #40 was opened at 22:59:45 and **no
`pull_request` workflow run appeared**. The operator closed and reopened
it at 23:06 as a workaround; two runs then materialized at 23:17 and
23:18 against the unchanged head sha, and the merge went in 38 seconds
after the first one reported green. Every other pull request in that
repository got its run within about three seconds of opening.

So the failure mode is *not* "CI is broken" and not "the branch was
delivered wrongly" — a new branch legitimately produces a `CreateEvent`
with no `PushEvent`, which is what the first reading of this suspected.
It is that **a host's `pull_request` trigger is a promise nobody can
enforce from this side of the wire**, and the delivery path treated its
absence as if it were a pass. A merge with no reported check is only
acceptable when the check demonstrably ran, which means somebody has to
look, and looking is a thing a script does better than a person at 23:17.

What this does, in order:

1. resolves the pull request's head sha (never a branch name — a branch
   moves, a check run belongs to a commit);
2. waits for at least one check run on that sha;
3. if none has appeared by ``--grace``, causes one **once**: close and
   reopen the pull request. `reopened` is in the default trigger types,
   so it needs no `workflow` token scope and no change to the CI file —
   the same lever the operator pulled by hand, pulled deterministically
   and *reported*;
4. waits for the runs to complete and prints them with their URLs.

Exit codes are the whole point: **2 means no check ever reported**, and
that is a different fact from 1 (a check ran and failed). Both are
"do not merge"; only one of them is a defect in the diff.

Everything goes through `gh`, so authentication is the operator's own
and this file holds no credential.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

# Every check run GitHub reports for a commit, with the conclusions that
# mean "green". `neutral` and `skipped` are green here: a workflow that
# deliberately no-ops on a path is not a failure, and treating it as one
# would teach people to ignore this tool.
PASSING = {"success", "neutral", "skipped"}


class GhError(RuntimeError):
    """`gh` itself failed — not the same as a check failing."""


def gh(args: list[str], *, binary: str = "gh") -> str:
    try:
        proc = subprocess.run(
            [binary, *args], capture_output=True, text=True, check=False
        )
    except OSError as err:
        # No `gh` on the machine is a tooling failure like any other, and
        # it must not read as "no check found".
        raise GhError(f"cannot run {binary}: {err}") from err
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def pr_head(pr: str, *, repo: str | None, binary: str = "gh") -> dict:
    args = ["pr", "view", pr, "--json", "number,headRefOid,url,state,headRefName"]
    if repo:
        args += ["--repo", repo]
    return json.loads(gh(args, binary=binary))


def check_runs(sha: str, *, repo: str, binary: str = "gh") -> list[dict]:
    raw = gh(
        ["api", f"repos/{repo}/commits/{sha}/check-runs", "--paginate"], binary=binary
    )
    # --paginate concatenates JSON objects when the endpoint pages; the
    # first page is enough for a KB PR and the fallback is explicit
    # rather than a silent zero.
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = json.loads(raw.split("}{")[0] + "}") if raw.strip() else {}
    return payload.get("check_runs", [])


def repo_slug(*, repo: str | None, binary: str = "gh") -> str:
    if repo:
        return repo
    view = json.loads(gh(["repo", "view", "--json", "nameWithOwner"], binary=binary))
    return view["nameWithOwner"]


def reopen(pr: str, *, repo: str | None, binary: str = "gh") -> None:
    suffix = ["--repo", repo] if repo else []
    gh(["pr", "close", pr, *suffix], binary=binary)
    gh(["pr", "reopen", pr, *suffix], binary=binary)


def gate(
    pr: str,
    *,
    repo: str | None = None,
    grace: float = 120.0,
    timeout: float = 900.0,
    poll: float = 10.0,
    binary: str = "gh",
    sleep=time.sleep,
    now=time.monotonic,
    out=sys.stdout,
) -> int:
    def say(msg: str) -> None:
        print(msg, file=out, flush=True)

    slug = repo_slug(repo=repo, binary=binary)
    pr_info = pr_head(pr, repo=repo, binary=binary)
    sha = pr_info["headRefOid"]
    say(f"PR #{pr_info['number']} in {slug} — head {sha[:8]} ({pr_info['url']})")

    started = now()
    remediated = False
    while True:
        runs = check_runs(sha, repo=slug, binary=binary)
        if runs:
            pending = [r for r in runs if r.get("status") != "completed"]
            if not pending:
                for run in runs:
                    say(
                        f"  {run.get('name')}: {run.get('conclusion')} "
                        f"({run.get('html_url') or run.get('details_url')})"
                    )
                failed = [r for r in runs if r.get("conclusion") not in PASSING]
                if failed:
                    say(
                        f"CHECK FAILED — {len(failed)} of {len(runs)} did not pass. "
                        "The diff is the problem; fix it and push."
                    )
                    return 1
                say(
                    f"CHECK REPORTED GREEN — {len(runs)} run(s) on {sha[:8]}. "
                    "This PR is safe to hand over for review."
                )
                return 0
            say(f"  waiting: {len(pending)} of {len(runs)} run(s) still going")
        elapsed = now() - started
        if not runs and not remediated and elapsed >= grace:
            # The PR #40 shape. Say what is happening and why, because a
            # silent close/reopen in somebody's notification feed is
            # worse than the problem it fixes.
            say(
                f"NO CHECK RUN after {int(elapsed)}s. Causing one: closing and reopening "
                f"PR #{pr_info['number']} (a `reopened` event fires `pull_request` workflows; "
                "the head commit is untouched)."
            )
            reopen(pr, repo=repo, binary=binary)
            remediated = True
            started = now()
        if now() - started >= timeout:
            say(
                f"NO CHECK REPORTED for {sha[:8]} within the timeout"
                + (" (a close/reopen did not produce one either)" if remediated else "")
                + ". DO NOT MERGE on this evidence: the absence of a check is not a pass. "
                "Check the repository's Actions tab before going further."
            )
            return 2
        sleep(poll)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Wait for a KB pull request's CI check to actually report (D-116.4)."
    )
    ap.add_argument("pr", help="pull request number")
    ap.add_argument("--repo", help="owner/name (default: the clone's own remote)")
    ap.add_argument("--grace", type=float, default=120.0,
                    help="seconds to wait before causing a run (default 120)")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="seconds to wait for a reported check (default 900)")
    ap.add_argument("--poll", type=float, default=10.0, help="seconds between polls")
    ap.add_argument("--gh", default="gh", help="gh binary (tests override this)")
    args = ap.parse_args(argv)
    try:
        return gate(
            args.pr,
            repo=args.repo,
            grace=args.grace,
            timeout=args.timeout,
            poll=args.poll,
            binary=args.gh,
        )
    except GhError as err:
        print(f"gh failed: {err}", file=sys.stderr)
        # Tooling failure is its own exit code: it is not evidence that a
        # check ran, and it is not evidence that one did not.
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
