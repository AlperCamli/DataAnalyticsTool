"""Quota/backoff primitives (manifest `rate_limit`, D-12/D-28).

A connector manifest declares its quota policy (`rate_limit`); these
are the SDK primitives that honor it. Two pieces:

- `TokenBucket` — client-side pacing so a connector never *provokes*
  the source's rate ceiling (strategy `token-bucket`; strategy `none`
  yields a no-op bucket).
- `backoff_delays` — the retry schedule for responses that say "slow
  down" (HTTP 429 / RESOURCE_EXHAUSTED): exponential with ±jitter,
  bounded by the policy's `max_retries`.

What happens when backoff is exhausted is the *connector's* call, but
the contract is fixed: quota exhaustion is raised as `QuotaExceeded`,
which the runner maps to a J-5 deferral — never a failure, never a
consumed retry attempt.

Clocks, sleeps, and randomness are injectable so tests run instantly
and deterministically.
"""

import random
import time
from dataclasses import dataclass
from typing import Callable, Iterator


@dataclass(frozen=True)
class QuotaPolicy:
    """The manifest's `rate_limit` mapping, with SDK defaults applied."""

    strategy: str = "none"
    rate_per_s: float = 5.0
    burst: int = 5
    max_retries: int = 4
    backoff_base_s: float = 1.0
    backoff_cap_s: float = 60.0
    default_retry_after_s: int = 3600

    @classmethod
    def from_rate_limit(cls, rate_limit: dict) -> "QuotaPolicy":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in rate_limit.items() if k in known})


class TokenBucket:
    """Pace calls at `rate_per_s` with a burst allowance of `burst`.

    `acquire()` blocks (via the injected `sleep`) until a token is
    available. A `strategy: none` policy produces a bucket that never
    blocks, so connector code is unconditional.
    """

    def __init__(
        self,
        policy: QuotaPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._active = policy.strategy != "none"
        self._rate = float(policy.rate_per_s)
        self._capacity = float(policy.burst)
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()

    def acquire(self) -> None:
        if not self._active:
            return
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self._rate
            self._sleep(wait)
            self._last = self._clock()
            self._tokens = 1.0
        self._tokens -= 1.0


def backoff_delays(
    policy: QuotaPolicy, *, rng: random.Random | None = None
) -> Iterator[float]:
    """Yield `max_retries` delays: min(base * 2^n, cap) with ±20% jitter.

    Mirrors the job protocol's §5 retry-backoff shape on the connector
    side of the boundary.
    """
    rng = rng or random.Random()
    for attempt in range(policy.max_retries):
        delay = min(policy.backoff_base_s * (2**attempt), policy.backoff_cap_s)
        yield delay * rng.uniform(0.8, 1.2)
