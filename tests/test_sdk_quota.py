"""SDK quota primitives (connectors/sdk/quota.py, D-12/D-28)."""

import random

from connectors.sdk import QuotaPolicy, TokenBucket, backoff_delays


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_policy_from_rate_limit_applies_defaults_and_ignores_unknown_keys():
    policy = QuotaPolicy.from_rate_limit(
        {"strategy": "token-bucket", "rate_per_s": 2, "burst": 3, "future_knob": True}
    )
    assert policy.strategy == "token-bucket"
    assert policy.rate_per_s == 2 and policy.burst == 3
    assert policy.max_retries == 4  # SDK default
    assert policy.default_retry_after_s == 3600


def test_strategy_none_never_blocks():
    clock = FakeClock()
    bucket = TokenBucket(QuotaPolicy(strategy="none"), clock=clock, sleep=clock.sleep)
    for _ in range(100):
        bucket.acquire()
    assert clock.slept == []


def test_token_bucket_paces_beyond_burst():
    clock = FakeClock()
    policy = QuotaPolicy(strategy="token-bucket", rate_per_s=1, burst=2)
    bucket = TokenBucket(policy, clock=clock, sleep=clock.sleep)
    bucket.acquire()
    bucket.acquire()
    assert clock.slept == []  # burst allowance
    bucket.acquire()
    assert len(clock.slept) == 1 and clock.slept[0] == 1.0  # then paced at rate


def test_token_bucket_refills_with_elapsed_time():
    clock = FakeClock()
    policy = QuotaPolicy(strategy="token-bucket", rate_per_s=1, burst=2)
    bucket = TokenBucket(policy, clock=clock, sleep=clock.sleep)
    bucket.acquire()
    bucket.acquire()
    clock.now += 10  # long idle refills up to burst, never beyond
    bucket.acquire()
    bucket.acquire()
    assert clock.slept == []
    bucket.acquire()
    assert len(clock.slept) == 1


def test_backoff_schedule_is_bounded_exponential_with_jitter():
    policy = QuotaPolicy(max_retries=5, backoff_base_s=1.0, backoff_cap_s=6.0)
    delays = list(backoff_delays(policy, rng=random.Random(7)))
    assert len(delays) == policy.max_retries
    for delay, nominal in zip(delays, [1, 2, 4, 6, 6]):  # capped at 6
        assert 0.8 * nominal <= delay <= 1.2 * nominal
