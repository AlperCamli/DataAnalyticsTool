# JC-4 fix — verification under deliberate load

Standard set by **D-96.3f**: *three consecutive full-suite runs UNDER
DELIBERATE LOAD*. Not three green runs on an idle machine — a green run
on an idle machine proves nothing about a contention flake.

## Result

**3 / 3 green.** 188 tests, 19 files, every run.

| Run | Started (UTC) | Exit | Suite duration | JC-4 test |
|---|---|---|---|---|
| 1 | 11:29:29 | 0 | 548.96 s | pass, 22.99 s |
| 2 | 11:38:41 | 0 | 523.31 s | pass, 21.76 s |
| 3 | 11:47:27 | 0 | 539.03 s | pass, 21.41 s |

For contrast, the failure this replaces was a **35.3 s lease-expiry
timeout** (D-85). The three JC-4 timings sit inside a 1.6 s band, which
is the point: with a 16:1 heartbeat margin the reclaim path is no longer
racing the sweeper.

## The load

`jc4-verify.sh`, run on this machine (8 cores):

- a **`docker build --no-cache`** of the core image looping continuously
  beside the suite — 204,368 lines of build log over the three runs, so
  the daemon and disk were genuinely contended, not nominally;
- a **CPU ring of 7 spinners** (cores − 1), so the suite competed for
  every core it wanted;
- 20 s of spin-up before run 1, so the first run was not measured on a
  quiet machine.

Suite wall-clock under this load ran ~9 minutes against roughly half that
idle — the contention was real and is visible in the numbers.

## What is NOT claimed

- This does not prove the **docker-heavy sync flake** is gone. That is a
  different animal (container-start latency, not lease protocol) and
  D-96.3f keeps it under quarantine-with-trigger: *the next occurrence
  must be captured with full output before any re-run green.* No
  occurrence appeared in these three runs, which is evidence of nothing
  either way.
- `expect(requeued.attempt).toBe(2)` was deliberately left strict. At a
  16:1 margin a spurious expiry is a real signal; softening the
  assertion would have traded the flake for blindness.
